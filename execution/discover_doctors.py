"""
discover_doctors.py — Doctor Discovery via Firecrawl + Google Search
Generates randomized search terms combining medical specialties and Brazilian cities,
then uses the Firecrawl Search API to find Instagram profiles of doctors.

Main functions:
  - generate_search_terms(count) -> list of search term strings
  - search_instagram_profiles(term) -> list of extracted usernames
  - run_search_batch(terms) -> dict with all discovered usernames and stats
"""

import os
import re
import random
import logging
import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"

# ---------------------------------------------------------------------------
# Specialty and city lists (configurable)
# ---------------------------------------------------------------------------

SPECIALTIES = [
    "dermatologista",
    "cirurgião plástico",
    "cirurgiã plástica",
    "ortopedista",
    "cardiologista",
    "oftalmologista",
    "ginecologista",
    "urologista",
    "neurologista",
    "endocrinologista",
    "pediatra",
    "psiquiatra",
    "otorrinolaringologista",
    "gastroenterologista",
    "oncologista",
    "reumatologista",
    "nefrologista",
    "pneumologista",
    "angiologista",
    "nutrólogo",
    "geriatra",
    "mastologista",
    "proctologista",
    "hepatologista",
    "infectologista",
    "medicina estética",
    "harmonização facial",
    "cirurgião dentista",
    "implantodontista",
    "ortodontista",
]

CITIES = [
    "São Paulo",
    "Rio de Janeiro",
    "Belo Horizonte",
    "Curitiba",
    "Porto Alegre",
    "Brasília",
    "Salvador",
    "Recife",
    "Fortaleza",
    "Goiânia",
    "Campinas",
    "Manaus",
    "Florianópolis",
    "Vitória",
    "Belém",
    "Ribeirão Preto",
    "Sorocaba",
    "Santos",
    "São José dos Campos",
    "Joinville",
    "Londrina",
    "Maringá",
    "Niterói",
    "Bauru",
    "Piracicaba",
    "Jundiaí",
    "Carapicuíba",
    "Uberlândia",
    "Natal",
    "Campo Grande",
]

# Prefixes to randomize search variation
_PREFIXES = [
    "médico {specialty} em {city} instagram",
    "dra {specialty} {city} instagram",
    "dr {specialty} {city} instagram",
    "{specialty} em {city} instagram",
    "médica {specialty} {city} instagram",
    "consultório {specialty} {city} instagram",
    "clínica {specialty} {city} instagram",
    "doutor {specialty} em {city} instagram",
    "doutora {specialty} {city} instagram",
]

# Instagram URL patterns to exclude (not profiles)
_EXCLUDED_PATH_PATTERNS = [
    "/reel/", "/reels/", "/explore/", "/p/", "/tv/",
    "/stories/", "/live/", "/tags/", "/locations/",
    "/accounts/", "/directory/",
]


# ---------------------------------------------------------------------------
# Search term generation
# ---------------------------------------------------------------------------

def generate_search_terms(count: int = 20) -> list:
    """
    Generate a list of randomized search terms combining specialties, cities, and prefixes.
    Returns up to `count` unique terms.
    """
    terms = set()
    attempts = 0
    max_attempts = count * 5  # avoid infinite loop

    while len(terms) < count and attempts < max_attempts:
        specialty = random.choice(SPECIALTIES)
        city = random.choice(CITIES)
        template = random.choice(_PREFIXES)
        term = template.format(specialty=specialty, city=city)
        terms.add(term)
        attempts += 1

    result = list(terms)
    random.shuffle(result)
    logger.info("Generated %d search terms", len(result))
    return result[:count]


# ---------------------------------------------------------------------------
# Username extraction
# ---------------------------------------------------------------------------

def _extract_usernames_from_text(text: str) -> set:
    """
    Extract Instagram usernames from a block of text using regex.
    Looks for instagram.com/username patterns.
    """
    usernames = set()

    # Match instagram.com/username (with optional www. or any subdomain)
    url_pattern = re.compile(
        r'(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9_.]{1,30})(?:/|\?|$)',
        re.IGNORECASE,
    )

    for match in url_pattern.finditer(text):
        raw_url = match.group(0)
        username = match.group(1).lower().strip(".")

        # Skip excluded paths (check the full URL for path segments like /reel/, /p/, etc.)
        if any(excl.strip("/") == username for excl in _EXCLUDED_PATH_PATTERNS):
            continue
        if any(excl in raw_url for excl in _EXCLUDED_PATH_PATTERNS):
            continue

        # Skip generic Instagram pages
        if username in ("about", "legal", "privacy", "terms", "developer", "help", "api"):
            continue

        if len(username) >= 2:
            usernames.add(username)

    return usernames


# ---------------------------------------------------------------------------
# Firecrawl search
# ---------------------------------------------------------------------------

def search_instagram_profiles(term: str) -> list:
    """
    Use the Firecrawl Search API to search Google for a given term.
    Extracts Instagram usernames from the results.

    Returns a list of unique username strings.
    """
    if not FIRECRAWL_API_KEY:
        logger.error("FIRECRAWL_API_KEY not set in .env")
        return []

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": term,
        "limit": 10,
    }

    try:
        resp = requests.post(
            FIRECRAWL_SEARCH_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

        if resp.status_code != 200:
            logger.warning("Firecrawl API returned %d for term '%s': %s", resp.status_code, term, resp.text[:300])
            return []

        data = resp.json()
        results = data.get("data", [])

        all_usernames = set()

        for item in results:
            # Extract from URL
            url = item.get("url", "")
            all_usernames.update(_extract_usernames_from_text(url))

            # Extract from title
            title = item.get("title", "")
            all_usernames.update(_extract_usernames_from_text(title))

            # Extract from description/content
            description = item.get("description", "")
            all_usernames.update(_extract_usernames_from_text(description))

            markdown = item.get("markdown", "")
            all_usernames.update(_extract_usernames_from_text(markdown))

        usernames = sorted(all_usernames)
        logger.info("Search term '%s' found %d usernames: %s", term, len(usernames), usernames)
        return usernames

    except requests.exceptions.Timeout:
        logger.warning("Firecrawl API timed out for term '%s'", term)
        return []
    except Exception as e:
        logger.error("Firecrawl search error for '%s': %s", term, e)
        return []


# ---------------------------------------------------------------------------
# Batch search
# ---------------------------------------------------------------------------

def run_search_batch(terms: list) -> dict:
    """
    Run searches for a list of terms and aggregate discovered usernames.

    Returns:
        {
            "usernames": list of unique usernames,
            "term_results": {term: [usernames]},
            "total_terms": int,
            "total_unique": int,
        }
    """
    all_usernames = set()
    term_results = {}

    for term in terms:
        found = search_instagram_profiles(term)
        term_results[term] = found
        all_usernames.update(found)

    result = {
        "usernames": sorted(all_usernames),
        "term_results": term_results,
        "total_terms": len(terms),
        "total_unique": len(all_usernames),
    }

    logger.info(
        "Batch search complete: %d terms, %d unique usernames",
        len(terms), len(all_usernames),
    )

    return result
