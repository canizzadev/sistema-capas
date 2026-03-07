"""
send_whatsapp.py — WhatsApp Message Sender via Z-API
Handles all outbound WhatsApp communication for the Behind prospecting system.

4 send modes:
  send_warm_up(number, lead_id)     -> bool
  send_sequence(lead_id)            -> dict
  send_followup(lead_id, message)   -> bool
  send_notification(number, message) -> bool

All modes:
  - Check send window (08:00-18:00 business days, configurable via .env)
  - Check opt_out in DB before sending (except send_notification)
  - Retry once after 30s on failure
  - Log every attempt to .tmp/whatsapp_logs/{date}_{number}.json
  - On second failure: set send_error_at, notify team

Learned:
  - Each message paragraph = separate WhatsApp message with random delay
  - Cover delivery: unpack ZIP, send capa.png only — never the ZIP file
  - Maximum 1 follow-up per lead per day (Tue-Fri)
  - Z-API endpoint: POST https://api.z-api.io/instances/{INSTANCE}/token/{TOKEN}/send-text
  - Z-API image:    POST https://api.z-api.io/instances/{INSTANCE}/token/{TOKEN}/send-image
"""

import os
import json
import time
import random
import base64
import zipfile
import logging
from io import BytesIO
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

from execution.manage_leads import (
    get_lead,
    get_lead_by_number,
    update_lead,
    update_status,
    append_conversation,
    is_opt_out,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from .env
# ---------------------------------------------------------------------------

WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
WHATSAPP_INSTANCE = os.getenv("WHATSAPP_INSTANCE", "")
SEND_WINDOW_START = os.getenv("WHATSAPP_SEND_WINDOW_START", "08:00")
SEND_WINDOW_END = os.getenv("WHATSAPP_SEND_WINDOW_END", "18:00")
TEAM_NOTIFICATION_NUMBER = os.getenv("TEAM_NOTIFICATION_NUMBER", "")

# Warm-up delays
WARMUP_MIN_DELAY = int(os.getenv("WARMUP_MIN_DELAY_SECONDS", "45"))
WARMUP_MAX_DELAY = int(os.getenv("WARMUP_MAX_DELAY_SECONDS", "90"))

# Sequence delays
SEQ_TEXT_MIN_DELAY = int(os.getenv("SEQUENCE_MIN_DELAY_SECONDS", "3"))
SEQ_TEXT_MAX_DELAY = int(os.getenv("SEQUENCE_MAX_DELAY_SECONDS", "5"))
SEQ_IMAGE_MIN_DELAY = int(os.getenv("SEQUENCE_IMAGE_MIN_DELAY_SECONDS", "4"))
SEQ_IMAGE_MAX_DELAY = int(os.getenv("SEQUENCE_IMAGE_MAX_DELAY_SECONDS", "6"))

# Z-API base URL
ZAPI_BASE_URL = "https://api.z-api.io/instances/{instance}/token/{token}"

# Log directory
WHATSAPP_LOG_DIR = os.path.join(".tmp", "whatsapp_logs")

# Expose configuration as a dict so other modules (e.g. queue_dispatcher)
# can check send-window status without importing private helpers.
config = {
    "is_window_open": lambda: _is_within_send_window(),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_log_dir():
    """Create the log directory if it doesn't exist."""
    os.makedirs(WHATSAPP_LOG_DIR, exist_ok=True)


def _get_br_now():
    """Get current datetime in Brazil timezone (UTC-3)."""
    br_tz = timezone(timedelta(hours=-3))
    return datetime.now(br_tz)


def _is_within_send_window() -> bool:
    """Check if current time is within the configured send window (business days only)."""
    now = _get_br_now()
    # Monday=0, Sunday=6. Business days = 0-4
    if now.weekday() > 4:
        logger.info("Outside send window: weekend (day=%d)", now.weekday())
        return False

    start_h, start_m = map(int, SEND_WINDOW_START.split(":"))
    end_h, end_m = map(int, SEND_WINDOW_END.split(":"))

    start_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end_time = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    if not (start_time <= now <= end_time):
        logger.info("Outside send window: %s (window: %s-%s)", now.strftime("%H:%M"), SEND_WINDOW_START, SEND_WINDOW_END)
        return False
    return True


def _log_send_attempt(number: str, payload: dict, response_data: dict, success: bool):
    """Log a send attempt to .tmp/whatsapp_logs/{date}_{number}.json."""
    _ensure_log_dir()
    now = _get_br_now()
    filename = "{}_{}.json".format(now.strftime("%Y-%m-%d_%H%M%S"), number)
    log_entry = {
        "timestamp": now.isoformat(),
        "number": number,
        "payload": payload,
        "response": response_data,
        "success": success,
    }
    filepath = os.path.join(WHATSAPP_LOG_DIR, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(log_entry, f, ensure_ascii=False, indent=2)
        logger.debug("Send attempt logged: %s", filepath)
    except Exception as e:
        logger.warning("Failed to write send log: %s", e)


def _zapi_url(endpoint: str) -> str:
    """Build a Z-API endpoint URL."""
    base = ZAPI_BASE_URL.format(instance=WHATSAPP_INSTANCE, token=WHATSAPP_API_KEY)
    return "{}/{}".format(base, endpoint)


def _send_text_message(number: str, message: str) -> dict:
    """
    Send a single text message via Z-API.
    Returns {"success": True/False, "response": {...}, "error": "..."}.
    """
    url = _zapi_url("send-text")
    headers = {
        "Content-Type": "application/json",
        "Client-Token": WHATSAPP_API_KEY,
    }
    payload = {
        "phone": number,
        "message": message,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp_data = resp.json() if resp.text else {}
        success = resp.status_code == 200
        _log_send_attempt(number, payload, resp_data, success)

        if not success:
            logger.warning("Z-API send-text failed (status=%d): %s", resp.status_code, resp_data)
            return {"success": False, "response": resp_data, "error": "status_{}".format(resp.status_code)}

        logger.info("Text message sent to %s", number)
        return {"success": True, "response": resp_data}
    except requests.RequestException as e:
        logger.error("Z-API send-text request error: %s", e)
        _log_send_attempt(number, payload, {"error": str(e)}, False)
        return {"success": False, "response": {}, "error": str(e)}


def _send_image_message(number: str, image_base64: str, caption: str = "") -> dict:
    """
    Send an image via Z-API using base64 encoding.
    Returns {"success": True/False, "response": {...}, "error": "..."}.
    """
    url = _zapi_url("send-image")
    headers = {
        "Content-Type": "application/json",
        "Client-Token": WHATSAPP_API_KEY,
    }
    payload = {
        "phone": number,
        "image": "data:image/png;base64,{}".format(image_base64),
    }
    if caption:
        payload["caption"] = caption

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp_data = resp.json() if resp.text else {}
        success = resp.status_code == 200
        # Log without the full base64 to save space
        log_payload = {**payload, "image": "[base64_image_omitted]"}
        _log_send_attempt(number, log_payload, resp_data, success)

        if not success:
            logger.warning("Z-API send-image failed (status=%d): %s", resp.status_code, resp_data)
            return {"success": False, "response": resp_data, "error": "status_{}".format(resp.status_code)}

        logger.info("Image sent to %s", number)
        return {"success": True, "response": resp_data}
    except requests.RequestException as e:
        logger.error("Z-API send-image request error: %s", e)
        _log_send_attempt(number, {"phone": number, "image": "[omitted]"}, {"error": str(e)}, False)
        return {"success": False, "response": {}, "error": str(e)}


def _send_with_retry(send_fn, *args, lead_id: Optional[int] = None) -> dict:
    """
    Execute a send function. On failure, retry once after 30 seconds.
    If second attempt also fails: set send_error_at on lead (if lead_id provided)
    and notify team.
    """
    result = send_fn(*args)
    if result.get("success"):
        return result

    # First failure — retry after 30s
    logger.warning("First send attempt failed, retrying in 30s...")
    time.sleep(30)
    result = send_fn(*args)

    if result.get("success"):
        return result

    # Second failure — mark send_error and notify team
    logger.error("Send failed after retry. Marking send_error.")
    now_iso = datetime.now(timezone.utc).isoformat()

    if lead_id is not None:
        update_lead(lead_id, send_error_at=now_iso)
        lead = get_lead(lead_id)
        lead_name = lead.get("formatted_name", "Unknown") if lead else "Unknown"
        lead_number = args[0] if args else "Unknown"
        _notify_team_send_error(lead_name, lead_number, lead_id)

    return result


def _notify_team_send_error(lead_name: str, lead_number: str, lead_id: int):
    """Send a notification to the team about a send error."""
    if not TEAM_NOTIFICATION_NUMBER:
        logger.warning("TEAM_NOTIFICATION_NUMBER not set, cannot notify team about send_error")
        return

    msg = "[SEND_ERROR] Lead: {} | Number: {} | Lead ID: {}".format(lead_name, lead_number, lead_id)
    # Direct send without retry to avoid infinite loop
    _send_text_message(TEAM_NOTIFICATION_NUMBER, msg)


def _extract_capa_from_zip(zip_path: str) -> Optional[bytes]:
    """Extract capa.png from a ZIP file. Returns image bytes or None."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.lower().endswith(".png"):
                    return zf.read(name)
        logger.warning("No PNG file found in ZIP: %s", zip_path)
        return None
    except Exception as e:
        logger.error("Failed to extract capa from ZIP '%s': %s", zip_path, e)
        return None


def _load_warmup_messages() -> list:
    """Load warm-up messages from config/warmup_messages.json."""
    try:
        with open("config/warmup_messages.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load warmup_messages.json: %s", e)
        return ["Bom dia"]  # Fallback


def _load_sequence_messages() -> dict:
    """Load sequence messages from config/sequence_messages.json."""
    try:
        with open("config/sequence_messages.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load sequence_messages.json: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Public API — 4 send modes
# ---------------------------------------------------------------------------

def send_warm_up(number: str, lead_id: int) -> bool:
    """
    Send a single warm-up message to a lead.
    Picks a random message from warmup_messages.json.
    Updates lead status to warm_up_sent on success.

    Returns True if message was sent successfully.
    """
    # Pre-flight checks
    if not _is_within_send_window():
        logger.info("Warm-up skipped for %s: outside send window", number)
        return False

    if is_opt_out(number):
        logger.info("Warm-up skipped for %s: opt_out", number)
        return False

    lead = get_lead(lead_id)
    if lead is None:
        logger.warning("Lead %d not found for warm-up", lead_id)
        return False

    if lead["status"] != "cover_generated":
        logger.warning("Lead %d not in cover_generated status (current: %s)", lead_id, lead["status"])
        return False

    # Pick a random warm-up message (never repeat for same number handled by DB)
    messages = _load_warmup_messages()
    used = lead.get("warm_up_message")
    available = [m for m in messages if m != used]
    if not available:
        available = messages  # All used, reset pool
    message = random.choice(available)

    # Send with retry
    result = _send_with_retry(_send_text_message, number, message, lead_id=lead_id)
    if not result.get("success"):
        return False

    # Update lead state
    now_iso = datetime.now(timezone.utc).isoformat()
    update_lead(lead_id, warm_up_message=message, warm_up_sent_at=now_iso)
    update_status(lead_id, "warm_up_sent")
    append_conversation(lead_id, "agent", message)
    logger.info("Warm-up sent to lead %d (%s): '%s'", lead_id, number, message)
    return True


def send_sequence(lead_id: int) -> dict:
    """
    Send the 5-part message sequence to a lead.
    Sequence variant is chosen based on contact_classification (A/B/C/D).
    Message [3] is always capa.png extracted from the ZIP.

    Delays: 3-5s between text messages, 4-6s before image.

    Returns dict with keys: success (bool), messages_sent (int), errors (list).
    """
    lead = get_lead(lead_id)
    if lead is None:
        return {"success": False, "messages_sent": 0, "errors": ["Lead not found"]}

    number = lead["whatsapp_number"]

    if is_opt_out(number):
        return {"success": False, "messages_sent": 0, "errors": ["Lead is opt_out"]}

    # Determine variant
    classification = lead.get("contact_classification", "B")  # Default to direct doctor
    if classification not in ("A", "B", "C", "D"):
        classification = "B"

    # Load sequence messages
    seq_data = _load_sequence_messages()
    variant = seq_data.get(classification)
    if not variant or "messages" not in variant:
        return {"success": False, "messages_sent": 0, "errors": ["Sequence variant '{}' not found".format(classification)]}

    messages = variant["messages"]
    name = lead.get("formatted_name", "")

    # Extract capa.png from ZIP
    cover_path = lead.get("cover_path", "")
    capa_bytes = None
    if cover_path:
        capa_bytes = _extract_capa_from_zip(cover_path)

    result = {"success": True, "messages_sent": 0, "errors": []}

    for i, msg_template in enumerate(messages):
        # Check if this is the image token
        if msg_template == "__IMAGE__":
            # Delay before image
            delay = random.uniform(SEQ_IMAGE_MIN_DELAY, SEQ_IMAGE_MAX_DELAY)
            logger.debug("Sequence delay before image: %.1fs", delay)
            time.sleep(delay)

            if capa_bytes:
                img_b64 = base64.b64encode(capa_bytes).decode("utf-8")
                send_result = _send_with_retry(_send_image_message, number, img_b64, lead_id=lead_id)
                if send_result.get("success"):
                    result["messages_sent"] += 1
                    append_conversation(lead_id, "agent", "[capa.png enviada]")
                else:
                    result["errors"].append("Image send failed at message {}".format(i + 1))
                    # Continue with remaining messages
            else:
                logger.warning("No capa image available for lead %d, skipping image message", lead_id)
                result["errors"].append("No capa image available")
        else:
            # Text message — replace {name} placeholder
            msg = msg_template.replace("{name}", name)

            # Delay between text messages (skip for first message)
            if i > 0:
                delay = random.uniform(SEQ_TEXT_MIN_DELAY, SEQ_TEXT_MAX_DELAY)
                logger.debug("Sequence delay: %.1fs", delay)
                time.sleep(delay)

            send_result = _send_with_retry(_send_text_message, number, msg, lead_id=lead_id)
            if send_result.get("success"):
                result["messages_sent"] += 1
                append_conversation(lead_id, "agent", msg)
            else:
                result["errors"].append("Text send failed at message {}".format(i + 1))
                result["success"] = False
                # Stop sequence on text failure
                break

    # Update status if all messages sent
    if result["messages_sent"] == len(messages):
        update_status(lead_id, "message_sent")
        update_status(lead_id, "awaiting_response")
        logger.info("Full sequence sent to lead %d (%s), variant %s", lead_id, number, classification)
    else:
        result["success"] = False

    return result


def send_followup(lead_id: int, message: str) -> bool:
    """
    Send a follow-up message to a lead.
    Called by the queue_dispatcher during Tue-Fri follow-up loop.

    Returns True if sent successfully.
    """
    lead = get_lead(lead_id)
    if lead is None:
        logger.warning("Lead %d not found for follow-up", lead_id)
        return False

    number = lead["whatsapp_number"]

    if not _is_within_send_window():
        logger.info("Follow-up skipped for %s: outside send window", number)
        return False

    if is_opt_out(number):
        logger.info("Follow-up skipped for %s: opt_out", number)
        return False

    result = _send_with_retry(_send_text_message, number, message, lead_id=lead_id)
    if result.get("success"):
        append_conversation(lead_id, "agent", message)
        logger.info("Follow-up sent to lead %d (%s)", lead_id, number)
        return True

    return False


def send_notification(number: str, message: str) -> bool:
    """
    Send a team notification message.
    Used for: meeting_scheduled, out_of_hours_request, send_error, opt_out, lost.
    Does NOT check opt_out (team notifications are always sent).
    Does NOT check send window (team alerts are urgent).

    Returns True if sent successfully.
    """
    if not number:
        logger.warning("send_notification called with empty number")
        return False

    result = _send_with_retry(_send_text_message, number, message)
    if result.get("success"):
        logger.info("Notification sent to %s", number)
        return True

    logger.error("Notification failed to %s: %s", number, result.get("error"))
    return False
