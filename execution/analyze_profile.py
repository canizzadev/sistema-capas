"""
analyze_profile.py — AI-powered profile analysis using Claude Vision (Anthropic API)
Analyzes Instagram profile photos and bios to determine if a profile
belongs to a legitimate medical professional with a professional presence.

Two main functions:
  - analyze_photo(profile_pic_url) -> dict with photo quality assessment
  - analyze_bio(bio) -> dict with bio professionalism assessment

Uses the Anthropic Messages API directly via requests (no SDK dependency).
"""

import os
import base64
import logging
import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_VERSION = "2023-06-01"


def _call_anthropic(messages: list, max_tokens: int = 1024) -> str:
    """
    Send a request to the Anthropic Messages API.
    Returns the text content of the first response block.
    Raises RuntimeError on API errors.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)

    if resp.status_code != 200:
        logger.error("Anthropic API error %d: %s", resp.status_code, resp.text[:500])
        raise RuntimeError(f"Anthropic API returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    content_blocks = data.get("content", [])
    if content_blocks:
        return content_blocks[0].get("text", "")
    return ""


def _download_image_as_base64(url: str) -> tuple:
    """
    Download an image and return (base64_data, media_type).
    Raises RuntimeError if download fails.
    """
    resp = requests.get(url, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download image: HTTP {resp.status_code}")

    content_type = resp.headers.get("Content-Type", "image/jpeg")
    # Normalize content type
    if "jpeg" in content_type or "jpg" in content_type:
        media_type = "image/jpeg"
    elif "png" in content_type:
        media_type = "image/png"
    elif "gif" in content_type:
        media_type = "image/gif"
    elif "webp" in content_type:
        media_type = "image/webp"
    else:
        media_type = "image/jpeg"  # default fallback

    b64 = base64.b64encode(resp.content).decode("utf-8")
    return b64, media_type


# ---------------------------------------------------------------------------
# Photo analysis
# ---------------------------------------------------------------------------

def analyze_photo(profile_pic_url: str) -> dict:
    """
    Download the profile picture and analyze it with Claude Vision.

    Returns:
        {
            "aprovado": bool,
            "motivo": str,
            "fundo_liso": bool,
            "foto_profissional": bool,
            "alta_qualidade": bool
        }

    Returns a rejection dict if the image cannot be downloaded or analyzed.
    """
    if not profile_pic_url:
        return {
            "aprovado": False,
            "motivo": "URL da foto de perfil não disponível",
            "fundo_liso": False,
            "foto_profissional": False,
            "alta_qualidade": False,
        }

    try:
        b64_data, media_type = _download_image_as_base64(profile_pic_url)
    except Exception as e:
        logger.warning("Failed to download profile pic: %s", e)
        return {
            "aprovado": False,
            "motivo": f"Não foi possível baixar a imagem: {e}",
            "fundo_liso": False,
            "foto_profissional": False,
            "alta_qualidade": False,
        }

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Analise esta foto de perfil do Instagram de um possível médico. "
                        "Avalie os seguintes critérios:\n"
                        "1. A foto tem fundo liso ou de consultório/clínica? (fundo_liso)\n"
                        "2. É uma foto profissional (boa iluminação, enquadramento, vestimenta profissional como jaleco)? (foto_profissional)\n"
                        "3. A imagem é de alta qualidade (não pixelada, não cortada, não é logo/desenho)? (alta_qualidade)\n\n"
                        "Responda EXATAMENTE neste formato JSON, sem texto adicional:\n"
                        '{"aprovado": true/false, "motivo": "explicação breve", '
                        '"fundo_liso": true/false, "foto_profissional": true/false, "alta_qualidade": true/false}\n\n'
                        "A foto é aprovada se pelo menos 2 dos 3 critérios forem verdadeiros."
                    ),
                },
            ],
        }
    ]

    try:
        response_text = _call_anthropic(messages, max_tokens=256)
        # Parse JSON from response (handle possible markdown wrapping)
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        import json
        result = json.loads(clean)

        # Ensure all expected keys exist
        return {
            "aprovado": result.get("aprovado", False),
            "motivo": result.get("motivo", ""),
            "fundo_liso": result.get("fundo_liso", False),
            "foto_profissional": result.get("foto_profissional", False),
            "alta_qualidade": result.get("alta_qualidade", False),
        }
    except Exception as e:
        logger.error("Photo analysis failed for URL: %s — %s", profile_pic_url[:80], e)
        return {
            "aprovado": False,
            "motivo": f"Erro na análise da foto: {e}",
            "fundo_liso": False,
            "foto_profissional": False,
            "alta_qualidade": False,
        }


# ---------------------------------------------------------------------------
# Bio analysis
# ---------------------------------------------------------------------------

def analyze_bio(bio: str) -> dict:
    """
    Analyze an Instagram bio to determine if it belongs to a medical professional.

    Returns:
        {
            "aprovado": bool,
            "motivo": str,
            "eh_medico": bool,
            "bio_profissional": bool,
            "tem_especialidade": bool,
            "especialidade_detectada": str
        }

    Returns a rejection dict if bio is empty or analysis fails.
    """
    if not bio or not bio.strip():
        return {
            "aprovado": False,
            "motivo": "Bio vazia ou não disponível",
            "eh_medico": False,
            "bio_profissional": False,
            "tem_especialidade": False,
            "especialidade_detectada": "",
        }

    messages = [
        {
            "role": "user",
            "content": (
                f"Analise esta bio de Instagram e determine se pertence a um médico:\n\n"
                f'"{bio}"\n\n'
                "Avalie os seguintes critérios:\n"
                "1. É um médico ou médica? Procure por indicadores como: Dr., Dra., CRM, "
                "médico(a), cirurgião/cirurgiã, especialidades médicas (eh_medico)\n"
                "2. A bio é profissional (não é pessoal/lifestyle)? (bio_profissional)\n"
                "3. Menciona alguma especialidade médica? Se sim, qual? (tem_especialidade, especialidade_detectada)\n\n"
                "Responda EXATAMENTE neste formato JSON, sem texto adicional:\n"
                '{"aprovado": true/false, "motivo": "explicação breve", '
                '"eh_medico": true/false, "bio_profissional": true/false, '
                '"tem_especialidade": true/false, "especialidade_detectada": "nome da especialidade ou string vazia"}\n\n'
                "A bio é aprovada se eh_medico for true E bio_profissional for true."
            ),
        }
    ]

    try:
        response_text = _call_anthropic(messages, max_tokens=256)
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        import json
        result = json.loads(clean)

        return {
            "aprovado": result.get("aprovado", False),
            "motivo": result.get("motivo", ""),
            "eh_medico": result.get("eh_medico", False),
            "bio_profissional": result.get("bio_profissional", False),
            "tem_especialidade": result.get("tem_especialidade", False),
            "especialidade_detectada": result.get("especialidade_detectada", ""),
        }
    except Exception as e:
        logger.error("Bio analysis failed: %s", e)
        return {
            "aprovado": False,
            "motivo": f"Erro na análise da bio: {e}",
            "eh_medico": False,
            "bio_profissional": False,
            "tem_especialidade": False,
            "especialidade_detectada": "",
        }
