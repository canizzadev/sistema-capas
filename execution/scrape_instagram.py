import logging
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# --- Simple TTL cache for scraped profiles ---
_profile_cache = {}
_CACHE_TTL = 300  # 5 minutes

def _cache_get(key: str):
    entry = _profile_cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        logger.debug("Cache hit for '%s'", key)
        return entry["data"]
    return None

def _cache_set(key: str, data: dict):
    _profile_cache[key] = {"data": data, "ts": time.time()}


def extract_username(url: str) -> str:
    path = urlparse(url).path
    parts = [p for p in path.split('/') if p]
    if parts:
        return parts[0]
    return ""

def _validate_profile_response(user: dict) -> bool:
    """Validates that the scraped user object has the expected shape."""
    if not isinstance(user, dict):
        return False
    # Must have at least one of the core fields
    return any(k in user for k in ("full_name", "biography", "username"))

def scrape_profile(url: str):
    """
    Scrapes Instagram profile metadata.
    Attempts multiple endpoints to avoid rate-limiting and redirects.
    Returns a dict with 'name', 'bio', 'external_link' on success,
    or a dict with 'error' and 'error_type' on failure.

    Error types: 'invalid_url', 'private_profile', 'not_found',
                 'rate_limited', 'timeout', 'scrape_failed'
    """
    username = extract_username(url)
    if not username:
        return {"error": f"Invalid URL format: {url}", "error_type": "invalid_url"}

    # Check cache first
    cached = _cache_get(username)
    if cached is not None:
        return cached

    tier_errors = []

    # Attempt 1: i.instagram.com API endpoint with mobile headers
    api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 198.0.0.32.120",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.instagram.com/{username}/",
        "X-IG-App-ID": "936619743392459", # Standard web app ID
        "Origin": "https://www.instagram.com"
    }

    try:
        resp = requests.get(api_url, headers=mobile_headers, timeout=10)
        if resp.status_code == 429:
            logger.warning("Tier 1 rate-limited (429) for '%s'", username)
            tier_errors.append("Tier 1: rate limited (429)")
        elif resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {}).get("user")
            if user and _validate_profile_response(user):
                if user.get("is_private"):
                    result = {"error": f"Profile is private: {username}", "error_type": "private_profile", "username": username}
                    _cache_set(username, result)
                    return result
                followers_data = user.get("edge_followed_by") or {}
                result = {
                    "username": username,
                    "name": user.get("full_name") or username,
                    "bio": user.get("biography") or "",
                    "external_link": user.get("external_url") or "",
                    "followers": followers_data.get("count") if isinstance(followers_data, dict) else None,
                    "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url") or ""
                }
                logger.info("Tier 1 succeeded for '%s'", username)
                _cache_set(username, result)
                return result
            else:
                tier_errors.append("Tier 1: unexpected response schema")
                logger.warning("Tier 1 response validation failed for '%s'", username)
        else:
            tier_errors.append(f"Tier 1: HTTP {resp.status_code}")
            logger.info("Tier 1 returned HTTP %d for '%s'", resp.status_code, username)
    except requests.exceptions.Timeout:
        tier_errors.append("Tier 1: timeout")
        logger.warning("Tier 1 timed out for '%s'", username)
    except Exception as e:
        tier_errors.append(f"Tier 1: {type(e).__name__}")
        logger.warning("Tier 1 exception for '%s': %s", username, e)

    # Attempt 2: original (?__a=1) endpoint with standard desktop headers
    original_api_url = f"https://www.instagram.com/{username}/?__a=1&__d=dis"
    web_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.instagram.com/"
    }

    try:
        resp = requests.get(original_api_url, headers=web_headers, timeout=10)
        if resp.status_code == 429:
            logger.warning("Tier 2 rate-limited (429) for '%s'", username)
            tier_errors.append("Tier 2: rate limited (429)")
        elif resp.status_code == 200 and "application/json" in resp.headers.get("Content-Type", ""):
            data = resp.json()
            user = data.get("graphql", {}).get("user") or data.get("seo_category_infos", [{}])[0] if "seo_category_infos" in data else data
            if _validate_profile_response(user):
                if user.get("is_private"):
                    result = {"error": f"Profile is private: {username}", "error_type": "private_profile", "username": username}
                    _cache_set(username, result)
                    return result
                followers_data = user.get("edge_followed_by") or {}
                result = {
                    "username": username,
                    "name": user.get("full_name") or username,
                    "bio": user.get("biography") or "",
                    "external_link": user.get("external_url") or "",
                    "followers": followers_data.get("count") if isinstance(followers_data, dict) else None,
                    "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url") or ""
                }
                logger.info("Tier 2 succeeded for '%s'", username)
                _cache_set(username, result)
                return result
            else:
                tier_errors.append("Tier 2: unexpected response schema")
                logger.warning("Tier 2 response validation failed for '%s'", username)
        else:
            tier_errors.append(f"Tier 2: HTTP {resp.status_code}")
            logger.info("Tier 2 returned HTTP %d for '%s'", resp.status_code, username)
    except requests.exceptions.Timeout:
        tier_errors.append("Tier 2: timeout")
        logger.warning("Tier 2 timed out for '%s'", username)
    except Exception as e:
        tier_errors.append(f"Tier 2: {type(e).__name__}")
        logger.warning("Tier 2 exception for '%s': %s", username, e)

    # Attempt 3: Parsing HTML meta tags as fallback
    html_url = f"https://www.instagram.com/{username}/"
    try:
        resp = requests.get(html_url, headers=web_headers, timeout=10)
        if resp.status_code == 404:
            result = {"error": f"Profile not found: {username}", "error_type": "not_found", "username": username}
            _cache_set(username, result)
            return result
        if resp.status_code == 429:
            logger.warning("Tier 3 rate-limited (429) for '%s'", username)
            tier_errors.append("Tier 3: rate limited (429)")
            # All tiers rate-limited
            all_rate_limited = all("rate limited" in e for e in tier_errors)
            if all_rate_limited:
                return {"error": f"Instagram rate-limited all requests for {username}. Try again in a few minutes.", "error_type": "rate_limited", "username": username}
            return {"error": f"All scraping tiers failed for {username}. Details: {'; '.join(tier_errors)}", "error_type": "scrape_failed", "username": username}

        soup = BeautifulSoup(resp.text, 'html.parser')

        # og:title typically "Name (@username) • Instagram photos and videos"
        title_tag = soup.find("meta", property="og:title")
        title_content = title_tag["content"] if title_tag else ""
        name = username
        if "(@" in title_content:
            name = title_content.split("(@")[0].strip()

        # og:description typically contains bio
        desc_tag = soup.find("meta", property="og:description")
        desc_content = desc_tag["content"] if desc_tag else ""
        bio = ""
        # The description usually ends with "... from Name (@username): bio"
        if f"(@{username})" in desc_content:
            parts = desc_content.split(f"(@{username})")
            if len(parts) > 1:
                bio_raw = parts[1].strip()
                if bio_raw.startswith(":"):
                    bio_raw = bio_raw.replace(":", "", 1).strip()
                bio = bio_raw

        # Try to extract followers count from HTML/description
        followers = None
        followers_match = re.search(r'([\d,.]+[MKmk]?)\s*Followers', desc_content)
        if followers_match:
            raw = followers_match.group(1).replace(",", "").replace(".", "")
            suffix = raw[-1].upper() if raw[-1] in "MmKk" else ""
            num_str = raw[:-1] if suffix else raw
            try:
                num = float(num_str)
                if suffix == "K":
                    followers = int(num * 1_000)
                elif suffix == "M":
                    followers = int(num * 1_000_000)
                else:
                    followers = int(num)
            except ValueError:
                pass

        # og:image typically contains the profile picture
        og_image_tag = soup.find("meta", property="og:image")
        profile_pic_url = og_image_tag["content"] if og_image_tag else ""

        # In the fallback, external_link isn't reliably available in meta tags
        result = {
            "username": username,
            "name": name,
            "bio": bio,
            "external_link": "",
            "followers": followers,
            "profile_pic_url": profile_pic_url
        }
        logger.info("Tier 3 (HTML fallback) succeeded for '%s'", username)
        _cache_set(username, result)
        return result
    except requests.exceptions.Timeout:
        tier_errors.append("Tier 3: timeout")
        all_timeout = all("timeout" in e for e in tier_errors)
        error_type = "timeout" if all_timeout else "scrape_failed"
        return {"error": f"All scraping attempts failed for {username}. Details: {'; '.join(tier_errors)}", "error_type": error_type, "username": username}
    except Exception as e:
        tier_errors.append(f"Tier 3: {type(e).__name__}: {e}")
        logger.error("Tier 3 exception for '%s': %s", username, e)
        return {"error": f"All scraping attempts failed for {username}. Details: {'; '.join(tier_errors)}", "error_type": "scrape_failed", "username": username}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        start_time = __import__("time").time()
        result = scrape_profile(f"https://instagram.com/{sys.argv[1]}")
        print(json.dumps(result, indent=2))
        print(f"Time taken: {__import__('time').time() - start_time:.2f} seconds")

