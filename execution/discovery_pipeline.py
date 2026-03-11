"""
discovery_pipeline.py — Doctor Discovery Pipeline Orchestrator
Coordinates the full discovery flow:
  1. Generate search terms
  2. Search via Firecrawl (Google)
  3. Extract Instagram usernames
  4. Check if already processed
  5. Scrape Instagram profile
  6. Filter by followers count
  7. Analyze bio with Claude AI
  8. Analyze photo with Claude Vision
  9. Save approved to discovered_doctors or rejected to rejected_profiles

Main function: run_discovery(target_count=50) -> dict
"""

import os
import time
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (delays in seconds, from .env)
# ---------------------------------------------------------------------------

MIN_FOLLOWERS = int(os.getenv("MIN_FOLLOWERS", "1000"))
MIN_BIO_LENGTH = int(os.getenv("MIN_BIO_LENGTH", "20"))
DELAY_SEARCH = float(os.getenv("DISCOVERY_DELAY_SEARCH", "3"))
DELAY_SCRAPE = float(os.getenv("DISCOVERY_DELAY_SCRAPE", "2"))
DELAY_ANALYSIS = float(os.getenv("DISCOVERY_DELAY_ANALYSIS", "1"))

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_discovery(target_count: int = 50, on_progress=None) -> dict:
    """
    Run the full discovery pipeline.

    Args:
        target_count: target number of usernames to evaluate (not guaranteed approved)
        on_progress: optional callback(step: str, detail: str) for real-time updates

    Returns:
        {
            "approved": int,
            "rejected": int,
            "skipped": int,
            "errors": int,
            "total_searched": int,
            "details": [{"username": str, "status": str, "reason": str}, ...],
        }
    """
    from execution.discover_doctors import generate_search_terms, search_instagram_profiles
    from execution.scrape_instagram import scrape_profile
    from execution.analyze_profile import analyze_bio, analyze_photo
    from execution.manage_discovery import (
        is_already_processed,
        save_approved,
        save_rejected,
        log_search,
        was_searched,
    )

    def _progress(step, detail=""):
        logger.info("[Pipeline] %s — %s", step, detail)
        if on_progress:
            try:
                on_progress(step, detail)
            except Exception:
                pass

    stats = {
        "approved": 0,
        "rejected": 0,
        "skipped": 0,
        "errors": 0,
        "total_searched": 0,
        "details": [],
    }

    # --- Step 1: Generate search terms ---
    # Estimate: ~3 usernames per term on average
    terms_needed = max(5, (target_count // 3) + 5)
    all_terms = generate_search_terms(terms_needed)
    _progress("terms_generated", f"{len(all_terms)} termos de busca gerados")

    # --- Step 2: Search and collect usernames ---
    discovered_usernames = []  # list of (username, city_from_term)

    for term in all_terms:
        if len(discovered_usernames) >= target_count:
            break

        if was_searched(term):
            _progress("term_skipped", f"Termo já buscado: {term}")
            continue

        _progress("searching", f"Buscando: {term}")
        usernames = search_instagram_profiles(term)
        log_search(term, len(usernames))
        stats["total_searched"] += 1

        # Extract city hint from term for metadata
        city_hint = ""
        for word in term.split():
            if word[0].isupper() and word not in ("Followers", "Instagram"):
                city_hint = word
                break

        for u in usernames:
            if len(discovered_usernames) < target_count:
                discovered_usernames.append((u, city_hint))

        if DELAY_SEARCH > 0:
            time.sleep(DELAY_SEARCH)

    _progress("search_complete", f"{len(discovered_usernames)} usernames coletados")

    # --- Step 3: Process each username ---
    for idx, (username, cidade_busca) in enumerate(discovered_usernames):
        _progress(
            "processing",
            f"[{idx + 1}/{len(discovered_usernames)}] Avaliando @{username}",
        )

        # 3a. Check if already processed
        if is_already_processed(username):
            stats["skipped"] += 1
            stats["details"].append({
                "username": username,
                "status": "skipped",
                "reason": "Já processado anteriormente",
            })
            continue

        # 3b. Scrape Instagram
        profile_url = f"https://www.instagram.com/{username}/"
        profile = scrape_profile(profile_url)

        if "error" in profile:
            stats["errors"] += 1
            save_rejected(username, f"Scrape failed: {profile.get('error_type', 'unknown')}")
            stats["details"].append({
                "username": username,
                "status": "error",
                "reason": f"Scrape: {profile.get('error', 'unknown')}",
            })
            if DELAY_SCRAPE > 0:
                time.sleep(DELAY_SCRAPE)
            continue

        if DELAY_SCRAPE > 0:
            time.sleep(DELAY_SCRAPE)

        # 3c. Filter 1: minimum followers
        followers = profile.get("followers")
        if followers is not None and followers < MIN_FOLLOWERS:
            reason = f"Poucos seguidores: {followers} (mínimo: {MIN_FOLLOWERS})"
            stats["rejected"] += 1
            save_rejected(username, reason)
            stats["details"].append({
                "username": username,
                "status": "rejected",
                "reason": reason,
            })
            _progress("rejected", f"@{username} — {reason}")
            continue

        # 3d. Filter 2: bio analysis
        bio = profile.get("bio", "")
        if len(bio.strip()) < MIN_BIO_LENGTH:
            reason = f"Bio muito curta: {len(bio.strip())} chars (mínimo: {MIN_BIO_LENGTH})"
            stats["rejected"] += 1
            save_rejected(username, reason)
            stats["details"].append({
                "username": username,
                "status": "rejected",
                "reason": reason,
            })
            _progress("rejected", f"@{username} — {reason}")
            continue

        _progress("analyzing_bio", f"@{username} — Analisando bio com IA...")
        bio_result = analyze_bio(bio)

        if DELAY_ANALYSIS > 0:
            time.sleep(DELAY_ANALYSIS)

        if not bio_result.get("aprovado"):
            reason = f"Bio reprovada: {bio_result.get('motivo', 'sem motivo')}"
            stats["rejected"] += 1
            save_rejected(username, reason)
            stats["details"].append({
                "username": username,
                "status": "rejected",
                "reason": reason,
            })
            _progress("rejected", f"@{username} — {reason}")
            continue

        # 3e. Filter 3: photo analysis
        pic_url = profile.get("profile_pic_url", "")
        photo_result = {"aprovado": True, "motivo": "Sem foto para analisar"}

        if pic_url:
            _progress("analyzing_photo", f"@{username} — Analisando foto com Claude Vision...")
            photo_result = analyze_photo(pic_url)

            if DELAY_ANALYSIS > 0:
                time.sleep(DELAY_ANALYSIS)

            if not photo_result.get("aprovado"):
                reason = f"Foto reprovada: {photo_result.get('motivo', 'sem motivo')}"
                stats["rejected"] += 1
                save_rejected(username, reason)
                stats["details"].append({
                    "username": username,
                    "status": "rejected",
                    "reason": reason,
                })
                _progress("rejected", f"@{username} — {reason}")
                continue

        # --- All filters passed: APPROVED ---
        doctor_data = {
            "username": username,
            "name": profile.get("name", ""),
            "bio": bio,
            "external_link": profile.get("external_link", ""),
            "followers": followers,
            "profile_pic_url": pic_url,
            "especialidade_detectada": bio_result.get("especialidade_detectada", ""),
            "cidade_busca": cidade_busca,
            "photo_analysis": photo_result,
            "bio_analysis": bio_result,
        }

        try:
            save_approved(doctor_data)
            stats["approved"] += 1
            stats["details"].append({
                "username": username,
                "status": "approved",
                "reason": f"Aprovado — {bio_result.get('especialidade_detectada', 'especialidade não detectada')}",
            })
            _progress(
                "approved",
                f"@{username} — {bio_result.get('especialidade_detectada', '?')} "
                f"({followers or '?'} seguidores)",
            )
        except ValueError:
            # Duplicate — already exists
            stats["skipped"] += 1
            stats["details"].append({
                "username": username,
                "status": "skipped",
                "reason": "Duplicata em discovered_doctors",
            })

    _progress("complete", (
        f"Concluído: {stats['approved']} aprovados, "
        f"{stats['rejected']} rejeitados, "
        f"{stats['skipped']} já processados, "
        f"{stats['errors']} erros"
    ))

    return stats
