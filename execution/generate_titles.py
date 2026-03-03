import os
import json
import re
import time
import logging
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

# Ensure the client is setup
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- Simple TTL cache for GPT title results ---
_titles_cache = {}
_CACHE_TTL = 600  # 10 minutes

def _cache_key(name: str, bio: str) -> str:
    return f"{name}||{bio}"

def _cache_get(key: str):
    entry = _titles_cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        logger.debug("GPT cache hit for key")
        return entry["data"]
    return None

def _cache_set(key: str, data: dict):
    _titles_cache[key] = {"data": data, "ts": time.time()}

def clean_bio(bio: str) -> dict:
    """
    Strips emojis and extracts professional registration numbers.
    Returns: {"cleaned_bio": str, "registration": str}
    """
    if not bio:
        return {"cleaned_bio": "", "registration": ""}
        
    # Remove emojis using a regex pattern that catches most unicode emojis
    # We use a safer unicode category approach that avoids bad ranges across python versions
    emoji_pattern = re.compile(r'[^\w\s,.\-/?!;:\'\"()]', flags=re.UNICODE)
    
    cleaned_bio = emoji_pattern.sub(r'', bio)
    
    # Extract primary registration info: CRM, CRO, CRP, CRN, CRF, COREN, CREFITO, CREFONO, CRBM, CRBio, CRMV, CREF, CRTR, CRESS
    # Matches the acronym optionally followed by anything (like spaces, dots, hyphens) and captures both type and digits.
    councils_regex = r'\b(CRM|CRO|CRP|CRN|CRF|COREN|CREFITO|CREFONO|CRBM|CRBio|CRMV|CREF|CRTR|CRESS).*?(\d+)'
    reg_pattern = re.search(councils_regex, bio, re.IGNORECASE)
    if reg_pattern:
        c_type = reg_pattern.group(1).upper()
        council_type = "CRBio" if c_type == "CRBIO" else c_type
        registration = reg_pattern.group(2)
    else:
        council_type = ""
        registration = "-"
    
    # Extract RQE if present
    rqe_pattern = re.search(r'\bRQE.*?(\d+)', bio, re.IGNORECASE)
    rqe = rqe_pattern.group(1) if rqe_pattern else ""
    
    return {
        "cleaned_bio": cleaned_bio.strip(),
        "council_type": council_type,
        "registration": registration,
        "rqe": rqe
    }

def generate_titles(name: str, bio: str) -> dict:
    """
    Generates a professional formatted name, specialty line, and headline 
    for a Brazilian healthcare professional based on their name and bio.
    Returns: {"formatted_name": str, "specialty_line": str, "headline": str}
    """
    extracted = clean_bio(bio)
    cleaned_bio = extracted["cleaned_bio"]
    council_type = extracted["council_type"]
    registration = extracted["registration"]
    rqe = extracted["rqe"]
    
    # Registration formatting
    reg_text = f"{council_type}: {registration}" if registration != "-" else "-"
    rqe_text = f" RQE: {rqe}" if rqe else ""
    
    # Check cache first
    ck = _cache_key(name, bio)
    cached = _cache_get(ck)
    if cached is not None:
        return cached

    prompt = f"""
    Given the name '{name}', the raw biography '{bio}', the cleaned biography '{cleaned_bio}', and the professional registration '{reg_text}'{rqe_text}, generate a professional profile for this Brazilian healthcare professional.

    You must follow these instructions exactly:
    - For formatted_name: infer gender from the name and add Dr. or Dra. before the full name.
    - For specialty_line: identify the specialty from the bio. Then create exactly 2 personalized words that capture the essence of their work — these words must use the first letter capitalized, be connected with & or a comma, and must NOT be generic words like 'Saúde' or 'Bem-Estar'. They must reflect something specific from the bio. Then append the registration info. Format exactly: [Especialidade] – [Palavra1 & Palavra2] – {reg_text}{rqe_text}
    - For headline: write exactly 1 sentence in Portuguese, between 12 and 14 words, ending with period or exclamation mark. The sentence must use specific vocabulary from the bio — if they mention a technique, a philosophy, a target audience, or a differentiator, use it. Never use generic phrases like 'cuidando da sua saúde' or 'transformando vidas'. The headline must sound like it was written by a professional copywriter who read the full bio carefully.

    Return only valid JSON, no markdown, no explanation.
    {{
        "formatted_name": "...",
        "specialty_line": "...",
        "headline": "..."
    }}
    """

    try:
        logger.info("Calling GPT-4o-mini for '%s'", name)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert at organizing information about Brazilian healthcare professionals for prospecting."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content.strip()

        # Fallback parsing if GPT includes markdown
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]

        data = json.loads(content)
        result = {
            "formatted_name": data.get("formatted_name", name),
            "specialty_line": data.get("specialty_line", f"Especialista – {reg_text}{rqe_text}"),
            "headline": data.get("headline", "Profissional de saúde dedicado.")
        }
        logger.info("GPT titles generated successfully for '%s'", name)
        _cache_set(ck, result)
        return result
    except json.JSONDecodeError as e:
        logger.error("Failed to parse GPT response as JSON for '%s': %s", name, e)
        return {
            "formatted_name": name,
            "specialty_line": f"Erro de processamento – {reg_text}{rqe_text}",
            "headline": "Erro ao interpretar resposta da IA."
        }
    except Exception as e:
        logger.error("GPT call failed for '%s': %s", name, e)
        return {
            "formatted_name": name,
            "specialty_line": f"Erro de processamento – {reg_text}{rqe_text}",
            "headline": str(e)
        }
