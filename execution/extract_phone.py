"""
extract_phone.py — WhatsApp Phone Number Extraction
Finds Brazilian phone numbers from Instagram bios and external links.

Cascade strategy:
  1. Regex on bio text (wa.me links, phone patterns)
  2. Scrape external link via Firecrawl (wa.me, api.whatsapp.com, phone patterns)
  3. Return None if not found

All numbers are normalized to E.164 format without +: 5511999999999
"""

import os
import re
import logging
import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/scrape"

# ---------------------------------------------------------------------------
# Phone normalization and validation
# ---------------------------------------------------------------------------

def _normalize_phone(raw: str) -> str:
    """Strip everything except digits from a phone string."""
    return re.sub(r'\D', '', raw)


def _is_valid_br_mobile(number: str) -> bool:
    """
    Validate a normalized Brazilian mobile number.
    Expected: 5511999999999 (13 digits) or 551199999999 (12 digits, landline ok too).
    Must start with 55, then 2-digit DDD (11-99).
    """
    if not number.startswith("55"):
        return False
    if len(number) < 12 or len(number) > 13:
        return False
    ddd = number[2:4]
    if not (11 <= int(ddd) <= 99):
        return False
    return True


def _is_mobile(number: str) -> bool:
    """Check if the number is a mobile (9 digits after DDD, starts with 9)."""
    if len(number) == 13:
        return number[4] == '9'
    return False


def _ensure_country_code(number: str) -> str:
    """Add 55 prefix if missing."""
    digits = _normalize_phone(number)
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) == 11:  # DDD + 9 digits
        return "55" + digits
    if len(digits) == 10:  # DDD + 8 digits (landline)
        return "55" + digits
    return digits


# ---------------------------------------------------------------------------
# Regex patterns for Brazilian phones
# ---------------------------------------------------------------------------

# Matches: (11) 99999-9999, (11) 9999-9999, (11)99999-9999
_PATTERN_PARENS = re.compile(r'\((\d{2})\)\s*(\d{4,5})[- ]?(\d{4})')

# Matches: 11 99999-9999, 11 9999-9999
_PATTERN_SPACED = re.compile(r'\b(\d{2})\s+(\d{4,5})[- ]?(\d{4})\b')

# Matches: 11999999999 (11 digits), 5511999999999 (13 digits)
_PATTERN_PLAIN = re.compile(r'\b(55)?(\d{2})(\d{8,9})\b')

# Matches: wa.me/5511999999999 or wa.me/11999999999
_PATTERN_WAME = re.compile(r'wa\.me/(\d{10,13})')

# Matches: api.whatsapp.com/send?phone=5511999999999
_PATTERN_WHATSAPP_API = re.compile(r'api\.whatsapp\.com/send\?phone=(\d{10,13})')

# Matches: +55 11 99999-9999 or +5511999999999
_PATTERN_PLUS = re.compile(r'\+55\s*\(?(\d{2})\)?\s*(\d{4,5})[- ]?(\d{4})')


def _extract_phones_from_text(text: str) -> list:
    """
    Extract all potential Brazilian phone numbers from text.
    Returns a list of normalized numbers (with 55 prefix), ordered by preference:
    - wa.me links first (highest confidence)
    - WhatsApp API links
    - +55 format
    - Parentheses format
    - Spaced format
    - Plain digits
    """
    found = []

    # Priority 1: wa.me links
    for match in _PATTERN_WAME.finditer(text):
        num = _ensure_country_code(match.group(1))
        if _is_valid_br_mobile(num):
            found.append(("wame", num))

    # Priority 2: WhatsApp API links
    for match in _PATTERN_WHATSAPP_API.finditer(text):
        num = _ensure_country_code(match.group(1))
        if _is_valid_br_mobile(num):
            found.append(("whatsapp_api", num))

    # Priority 3: +55 format
    for match in _PATTERN_PLUS.finditer(text):
        num = "55" + match.group(1) + match.group(2) + match.group(3)
        if _is_valid_br_mobile(num):
            found.append(("plus55", num))

    # Priority 4: Parentheses format
    for match in _PATTERN_PARENS.finditer(text):
        num = "55" + match.group(1) + match.group(2) + match.group(3)
        if _is_valid_br_mobile(num):
            found.append(("parens", num))

    # Priority 5: Spaced format
    for match in _PATTERN_SPACED.finditer(text):
        num = "55" + match.group(1) + match.group(2) + match.group(3)
        if _is_valid_br_mobile(num):
            found.append(("spaced", num))

    # Priority 6: Plain digits
    for match in _PATTERN_PLAIN.finditer(text):
        prefix = match.group(1) or ""
        ddd = match.group(2)
        rest = match.group(3)
        num = _ensure_country_code(prefix + ddd + rest)
        if _is_valid_br_mobile(num):
            found.append(("plain", num))

    return found


def _pick_best_number(candidates: list) -> str:
    """
    From a list of (source, number) tuples, pick the best one.
    Prefers mobile numbers (9 digits after DDD) over landlines.
    """
    if not candidates:
        return None

    # Deduplicate preserving order
    seen = set()
    unique = []
    for source, num in candidates:
        if num not in seen:
            seen.add(num)
            unique.append((source, num))

    # Prefer mobile numbers
    for source, num in unique:
        if _is_mobile(num):
            return num

    # Fallback to first valid
    return unique[0][1]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_phone_from_bio(bio: str) -> str:
    """
    Extract a Brazilian phone number from an Instagram bio.
    Returns normalized number (e.g. '5511999999999') or None.
    """
    if not bio:
        return None

    candidates = _extract_phones_from_text(bio)
    result = _pick_best_number(candidates)

    if result:
        logger.info("Phone found in bio: %s", result)
    return result


def extract_phone_from_link(external_link: str) -> str:
    """
    Scrape an external link (Linktree, personal site, etc.) via Firecrawl
    and extract a WhatsApp number from the content.
    Returns normalized number or None.
    """
    if not external_link or not external_link.strip():
        return None

    if not FIRECRAWL_API_KEY:
        logger.warning("FIRECRAWL_API_KEY not set — skipping link scrape")
        return None

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "url": external_link,
        "formats": ["markdown"],
    }

    try:
        resp = requests.post(FIRECRAWL_SEARCH_URL, headers=headers, json=payload, timeout=20)

        if resp.status_code != 200:
            logger.warning("Firecrawl scrape returned %d for '%s'", resp.status_code, external_link)
            return None

        data = resp.json()
        content = data.get("data", {})

        # Combine all text content
        all_text = " ".join([
            content.get("markdown", ""),
            content.get("rawHtml", ""),
            external_link,  # include the URL itself
        ])

        candidates = _extract_phones_from_text(all_text)
        result = _pick_best_number(candidates)

        if result:
            logger.info("Phone found in external link '%s': %s", external_link, result)
        return result

    except requests.exceptions.Timeout:
        logger.warning("Firecrawl scrape timed out for '%s'", external_link)
        return None
    except Exception as e:
        logger.error("Error scraping external link '%s': %s", external_link, e)
        return None


def extract_phone(bio: str, external_link: str) -> str:
    """
    Cascade extraction: tries bio first, then external link.
    Returns normalized phone number or None.
    """
    # Strategy A: bio regex
    number = extract_phone_from_bio(bio)
    if number:
        return number

    # Strategy B: external link scrape
    number = extract_phone_from_link(external_link)
    if number:
        return number

    return None
