"""
full_pipeline.py — End-to-End Doctor Prospecting Pipeline
Orchestrates the complete flow from discovery to lead registration:
  Phase 1: Discovery (search terms → Firecrawl → usernames)
  Phase 2: Scrape + Filters (Instagram → followers → bio AI → photo AI)
  Phase 3: Color detection (Claude Vision → Pillow fallback)
  Phase 4: Cover generation (generate_cover_zip)
  Phase 5: Phone extraction (bio regex → external link scrape)
  Phase 6: Lead registration (create_lead with appropriate status)

Main function: run_full_pipeline(target_count, on_progress) -> dict
"""

import os
import time
import logging
import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DELAY_COVER = float(os.getenv("DISCOVERY_DELAY_COVER", "2"))
DELAY_PHONE = float(os.getenv("DISCOVERY_DELAY_PHONE", "1"))
COVERS_DIR = os.path.join(".tmp", "covers")


def run_full_pipeline(target_count: int = 30, on_progress=None) -> dict:
    """
    Full end-to-end pipeline: discovery → filters → cover → phone → lead.

    Args:
        target_count: number of Instagram usernames to evaluate
        on_progress: optional callback(data: dict) for real-time updates
            data keys: phase, current, total, username, message, stats

    Returns:
        {
            "leads_created": int,
            "awaiting_number": int,
            "covers_generated": int,
            "rejected": int,
            "skipped": int,
            "errors": int,
            "details": [{"username": str, "status": str, "message": str, "lead_id": int|None}, ...],
        }
    """
    from execution.discovery_pipeline import run_discovery
    from execution.detect_color import detect_brand_color
    from execution.generate_cover import generate_cover_zip
    from execution.generate_titles import generate_titles
    from execution.extract_phone import extract_phone
    from execution.manage_leads import create_lead, get_lead_by_number
    from execution.manage_discovery import get_discovered_doctors, delete_discovered_doctor

    stats = {
        "leads_created": 0,
        "awaiting_number": 0,
        "covers_generated": 0,
        "rejected": 0,
        "skipped": 0,
        "errors": 0,
        "details": [],
    }

    def _progress(phase, current, total, username, message):
        data = {
            "phase": phase,
            "current": current,
            "total": total,
            "username": username,
            "message": message,
            "stats": {k: v for k, v in stats.items() if k != "details"},
        }
        logger.info("[FullPipeline] %s — @%s — %s", phase, username, message)
        if on_progress:
            try:
                on_progress(data)
            except Exception:
                pass

    # Ensure covers directory exists
    os.makedirs(COVERS_DIR, exist_ok=True)

    # ===== PHASE 1+2: Discovery + Filters =====
    _progress("discovery", 0, target_count, "", "Iniciando descoberta e filtros...")

    discovery_result = run_discovery(target_count)

    stats["rejected"] = discovery_result.get("rejected", 0)
    stats["skipped"] = discovery_result.get("skipped", 0)
    stats["errors"] = discovery_result.get("errors", 0)

    # Copy discovery detail entries for rejected/skipped/error
    for d in discovery_result.get("details", []):
        if d["status"] != "approved":
            stats["details"].append({
                "username": d["username"],
                "status": d["status"],
                "message": d["reason"],
                "lead_id": None,
            })

    _progress("discovery", target_count, target_count, "",
              f"Descoberta concluída: {discovery_result.get('approved', 0)} aprovados")

    # ===== PHASE 3-6: Process each approved doctor =====
    approved_doctors = get_discovered_doctors()

    if not approved_doctors:
        _progress("complete", 0, 0, "", "Nenhum médico aprovado para processar")
        return stats

    total = len(approved_doctors)

    for idx, doctor in enumerate(approved_doctors):
        username = doctor["username"]
        instagram_url = f"https://www.instagram.com/{username}/"
        bio = doctor.get("bio", "")
        external_link = doctor.get("external_link", "")
        profile_pic_url = doctor.get("profile_pic_url", "")

        try:
            # --- Phase 3: GPT Titles ---
            _progress("titles", idx + 1, total, username, "Gerando títulos com GPT...")

            name = doctor.get("name", username)
            try:
                gpt_data = generate_titles(name, bio)
                formatted_name = gpt_data.get("formatted_name", name)
                specialty_line = gpt_data.get("specialty_line", doctor.get("especialidade_detectada", ""))
                headline = gpt_data.get("headline", "")
            except Exception as e:
                logger.warning("GPT titles failed for @%s: %s", username, e)
                formatted_name = name
                specialty_line = doctor.get("especialidade_detectada", "")
                headline = ""

            # --- Phase 3b: Color Detection ---
            _progress("color", idx + 1, total, username, "Detectando cor da marca...")

            brand_color = detect_brand_color(profile_pic_url)

            # --- Phase 4: Cover Generation ---
            _progress("cover", idx + 1, total, username, f"Gerando capa (cor: {brand_color})...")

            cover_path = ""
            try:
                # Download profile pic for cover generation
                if profile_pic_url:
                    pic_resp = requests.get(profile_pic_url, timeout=15, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                    })
                    if pic_resp.status_code == 200:
                        photo_bytes = pic_resp.content
                        zip_bytes = generate_cover_zip(photo_bytes, brand_color, instagram_url)

                        cover_filename = f"{username}_capa.zip"
                        cover_path = os.path.join(COVERS_DIR, cover_filename)
                        with open(cover_path, "wb") as f:
                            f.write(zip_bytes)

                        stats["covers_generated"] += 1
                        _progress("cover", idx + 1, total, username, f"Capa salva: {cover_filename}")
                    else:
                        logger.warning("Could not download profile pic for @%s: HTTP %d", username, pic_resp.status_code)
                else:
                    logger.info("No profile_pic_url for @%s, skipping cover", username)
            except Exception as e:
                logger.error("Cover generation failed for @%s: %s", username, e)
                # Continue without cover — not a blocker

            if DELAY_COVER > 0:
                time.sleep(DELAY_COVER)

            # --- Phase 5: Phone Extraction ---
            _progress("phone", idx + 1, total, username, "Buscando número de WhatsApp...")

            phone_number = extract_phone(bio, external_link)

            if DELAY_PHONE > 0 and external_link:
                time.sleep(DELAY_PHONE)

            # --- Phase 6: Lead Registration ---
            _progress("registration", idx + 1, total, username, "Registrando lead...")

            # Check if already a lead (by username-based placeholder or real number)
            if phone_number:
                existing = get_lead_by_number(phone_number)
                if existing:
                    stats["skipped"] += 1
                    stats["details"].append({
                        "username": username,
                        "status": "skipped",
                        "message": f"Número {phone_number} já existe como lead (ID: {existing['id']})",
                        "lead_id": existing["id"],
                    })
                    delete_discovered_doctor(doctor["id"])
                    continue

            if phone_number:
                # Full lead with number → status cover_generated
                lead = create_lead(
                    instagram_url=instagram_url,
                    username=username,
                    whatsapp_number=phone_number,
                    formatted_name=formatted_name,
                    specialty_line=specialty_line,
                    headline=headline,
                    cover_path=cover_path,
                    status="cover_generated",
                )
                stats["leads_created"] += 1
                stats["details"].append({
                    "username": username,
                    "status": "lead_created",
                    "message": f"Lead criado (ID: {lead['id']}) — WhatsApp: {phone_number}",
                    "lead_id": lead["id"],
                })
                _progress("registration", idx + 1, total, username,
                          f"Lead criado (ID: {lead['id']}) com número {phone_number}")
            else:
                # No number found → status awaiting_number
                placeholder = f"pending_{username}"
                try:
                    lead = create_lead(
                        instagram_url=instagram_url,
                        username=username,
                        whatsapp_number=placeholder,
                        formatted_name=formatted_name,
                        specialty_line=specialty_line,
                        headline=headline,
                        cover_path=cover_path,
                        status="awaiting_number",
                    )
                    stats["awaiting_number"] += 1
                    stats["details"].append({
                        "username": username,
                        "status": "awaiting_number",
                        "message": f"Lead criado (ID: {lead['id']}) — aguardando número de WhatsApp",
                        "lead_id": lead["id"],
                    })
                    _progress("registration", idx + 1, total, username,
                              f"Lead criado sem número (ID: {lead['id']}) — aguardando inserção manual")
                except ValueError:
                    # Placeholder already exists
                    stats["skipped"] += 1
                    stats["details"].append({
                        "username": username,
                        "status": "skipped",
                        "message": "Lead com placeholder já existe",
                        "lead_id": None,
                    })

            # Remove from discovered_doctors after processing
            delete_discovered_doctor(doctor["id"])

        except Exception as e:
            logger.error("Full pipeline error for @%s: %s", username, e)
            stats["errors"] += 1
            stats["details"].append({
                "username": username,
                "status": "error",
                "message": str(e),
                "lead_id": None,
            })

    _progress("complete", total, total, "", (
        f"Pipeline concluído: {stats['leads_created']} leads, "
        f"{stats['awaiting_number']} aguardando número, "
        f"{stats['covers_generated']} capas, "
        f"{stats['rejected']} rejeitados, "
        f"{stats['errors']} erros"
    ))

    return stats
