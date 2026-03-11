"""
detect_color.py — Automatic Brand Color Detection
Detects an appropriate brand color from a doctor's profile picture.

Cascade strategy:
  1. Claude Vision suggests a harmonious color
  2. Fallback: extract dominant color from image using Pillow

The color must have sufficient contrast with white text (WCAG AA ≥ 4.5:1).
"""

import os
import io
import logging
import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_BRAND_COLOR = os.getenv("DEFAULT_BRAND_COLOR", "#27AE60")

# ---------------------------------------------------------------------------
# Contrast utilities
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert '#RRGGBB' to (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (R, G, B) to '#RRGGBB'."""
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, r)),
        max(0, min(255, g)),
        max(0, min(255, b)),
    )


def _relative_luminance(r: int, g: int, b: int) -> float:
    """Calculate relative luminance per WCAG 2.0."""
    def linearize(c):
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _contrast_ratio_with_white(hex_color: str) -> float:
    """Calculate contrast ratio between a color and white."""
    r, g, b = _hex_to_rgb(hex_color)
    lum = _relative_luminance(r, g, b)
    # White luminance = 1.0
    return (1.0 + 0.05) / (lum + 0.05)


def _darken_for_contrast(hex_color: str, min_ratio: float = 4.5) -> str:
    """
    Darken a color until it meets the minimum contrast ratio with white.
    Reduces brightness in steps of 10%.
    """
    r, g, b = _hex_to_rgb(hex_color)

    for _ in range(20):  # max 20 iterations
        current = _rgb_to_hex(r, g, b)
        if _contrast_ratio_with_white(current) >= min_ratio:
            return current
        r = int(r * 0.85)
        g = int(g * 0.85)
        b = int(b * 0.85)

    return _rgb_to_hex(r, g, b)


# ---------------------------------------------------------------------------
# Claude Vision color detection
# ---------------------------------------------------------------------------

def detect_color_with_ai(profile_pic_url: str) -> str:
    """
    Send the profile picture to Claude Vision and ask for a harmonious brand color.
    Returns a hex color string or None on failure.
    """
    from execution.analyze_profile import _call_anthropic, _download_image_as_base64

    if not profile_pic_url:
        return None

    try:
        b64_data, media_type = _download_image_as_base64(profile_pic_url)
    except Exception as e:
        logger.warning("Could not download image for color detection: %s", e)
        return None

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
                        "Analise esta foto de perfil de um médico. "
                        "Sugira UMA cor hexadecimal que harmonize com a paleta da foto "
                        "E tenha bom contraste com texto branco sobreposto. "
                        "A cor deve ser elegante e profissional. "
                        "Responda APENAS com JSON: {\"hex\": \"#XXXXXX\", \"motivo\": \"...\"}"
                    ),
                },
            ],
        }
    ]

    try:
        import json
        response_text = _call_anthropic(messages, max_tokens=128)
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(clean)
        hex_color = result.get("hex", "")

        if not hex_color or not hex_color.startswith("#") or len(hex_color) != 7:
            logger.warning("Claude returned invalid hex: %s", hex_color)
            return None

        # Ensure contrast with white
        ratio = _contrast_ratio_with_white(hex_color)
        if ratio < 4.5:
            logger.info("Claude color %s has low contrast (%.1f), darkening...", hex_color, ratio)
            hex_color = _darken_for_contrast(hex_color)

        logger.info("AI detected color: %s (reason: %s)", hex_color, result.get("motivo", ""))
        return hex_color

    except Exception as e:
        logger.warning("Claude color detection failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Pillow fallback: dominant color extraction
# ---------------------------------------------------------------------------

def detect_color_from_image(image_bytes: bytes) -> str:
    """
    Extract the dominant non-neutral color from image bytes using Pillow.
    Returns a hex color with sufficient contrast against white.
    """
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        # Resize for speed
        img = img.resize((100, 100))
        pixels = list(img.getdata())

        # Filter out near-white, near-black, and gray pixels
        colored_pixels = []
        for r, g, b in pixels:
            brightness = (r + g + b) / 3
            # Skip very dark or very light
            if brightness < 30 or brightness > 225:
                continue
            # Skip grays (low saturation)
            max_c = max(r, g, b)
            min_c = min(r, g, b)
            if max_c - min_c < 25:
                continue
            colored_pixels.append((r, g, b))

        if not colored_pixels:
            logger.info("No colored pixels found, using default")
            return DEFAULT_BRAND_COLOR

        # Average the colored pixels
        avg_r = sum(p[0] for p in colored_pixels) // len(colored_pixels)
        avg_g = sum(p[1] for p in colored_pixels) // len(colored_pixels)
        avg_b = sum(p[2] for p in colored_pixels) // len(colored_pixels)

        hex_color = _rgb_to_hex(avg_r, avg_g, avg_b)

        # Ensure contrast
        ratio = _contrast_ratio_with_white(hex_color)
        if ratio < 4.5:
            hex_color = _darken_for_contrast(hex_color)

        logger.info("Pillow extracted color: %s from %d colored pixels", hex_color, len(colored_pixels))
        return hex_color

    except Exception as e:
        logger.error("Pillow color extraction failed: %s", e)
        return DEFAULT_BRAND_COLOR


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_brand_color(profile_pic_url: str) -> str:
    """
    Cascade: try Claude Vision first, then Pillow extraction.
    Always returns a valid hex color.
    """
    # Strategy A: Claude Vision
    color = detect_color_with_ai(profile_pic_url)
    if color:
        return color

    # Strategy B: Download image and extract with Pillow
    if profile_pic_url:
        try:
            resp = requests.get(profile_pic_url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            if resp.status_code == 200:
                return detect_color_from_image(resp.content)
        except Exception as e:
            logger.warning("Could not download image for Pillow fallback: %s", e)

    # Strategy C: Default
    logger.info("All color detection failed, using default: %s", DEFAULT_BRAND_COLOR)
    return DEFAULT_BRAND_COLOR
