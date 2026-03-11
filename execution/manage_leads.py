"""
manage_leads.py — Lead Database Manager (SQLite)
Foundation module for the Behind prospecting automation system.

Responsibility: All CRUD operations on the leads table.
Schema uses standard SQL only — supports migration from SQLite to PostgreSQL
without rewrites.

Run init_db() on import to ensure the table exists.
All timestamps are stored as ISO 8601 strings.

Learned:
  - Never delete lead records — only update status.
  - opt_out is terminal — no script may revert it.
  - Before any new send: check phone number in DB. No duplicate campaigns.
  - Store full conversation history as JSON in conversation_history column.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = os.getenv("DB_PATH", "./sistema_capas.db")

# ---------------------------------------------------------------------------
# Status flow definitions
# ---------------------------------------------------------------------------

# Valid transitions: current_status -> set of allowed next statuses
VALID_TRANSITIONS = {
    "awaiting_number":    {"cover_generated"},
    "cover_generated":    {"warm_up_sent"},
    "warm_up_sent":       {"warm_up_responded"},
    "warm_up_responded":  {"message_sent"},
    "message_sent":       {"awaiting_response"},
    "awaiting_response":  {"in_conversation", "lost", "opt_out"},
    "in_conversation":    {"meeting_scheduled", "lost", "opt_out"},
}

# Terminal states — no further transitions allowed
TERMINAL_STATES = {"meeting_scheduled", "lost", "opt_out"}

# All valid statuses (for validation)
ALL_STATUSES = set(VALID_TRANSITIONS.keys()) | TERMINAL_STATES

# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    instagram_url           TEXT    NOT NULL,
    username                TEXT    NOT NULL,
    whatsapp_number         TEXT    NOT NULL UNIQUE,
    formatted_name          TEXT    NOT NULL DEFAULT '',
    specialty_line          TEXT    NOT NULL DEFAULT '',
    headline                TEXT    NOT NULL DEFAULT '',
    cover_path              TEXT    NOT NULL DEFAULT '',
    status                  TEXT    NOT NULL DEFAULT 'cover_generated',
    contact_classification  TEXT    DEFAULT NULL,
    warm_up_message         TEXT    DEFAULT NULL,
    warm_up_sent_at         TEXT    DEFAULT NULL,
    last_lead_reply_at      TEXT    DEFAULT NULL,
    send_error_at           TEXT    DEFAULT NULL,
    conversation_history    TEXT    NOT NULL DEFAULT '[]',
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL
);
"""


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a connection with row_factory set to sqlite3.Row for dict-like access."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _row_to_dict(row) -> Optional[dict]:
    """Convert a sqlite3.Row to a plain dict, or return None."""
    if row is None:
        return None
    return dict(row)


def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Optional[str] = None) -> None:
    """Create the leads table if it does not exist."""
    conn = _get_connection(db_path)
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        logger.info("Database initialised (path=%s)", db_path or DB_PATH)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def create_lead(
    instagram_url: str,
    username: str,
    whatsapp_number: str,
    formatted_name: str = "",
    specialty_line: str = "",
    headline: str = "",
    cover_path: str = "",
    status: str = "cover_generated",
    db_path: Optional[str] = None,
) -> dict:
    """
    Insert a new lead with the given status (default: cover_generated).
    Returns the full row as a dict.
    Raises ValueError if the whatsapp_number already exists.
    """
    if status not in ALL_STATUSES:
        raise ValueError(f"Invalid initial status: '{status}'")
    now = _now_iso()
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO leads (
                instagram_url, username, whatsapp_number,
                formatted_name, specialty_line, headline,
                cover_path, status, conversation_history,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)
            """,
            (
                instagram_url, username, whatsapp_number,
                formatted_name, specialty_line, headline,
                cover_path, status, now, now,
            ),
        )
        conn.commit()
        lead_id = cursor.lastrowid
        logger.info("Lead created: id=%d, number=%s", lead_id, whatsapp_number)
        result = _row_to_dict(
            conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        )
        return result  # type: ignore[return-value]
    except sqlite3.IntegrityError as e:
        logger.warning("Duplicate whatsapp_number '%s': %s", whatsapp_number, e)
        raise ValueError(f"Lead with whatsapp_number '{whatsapp_number}' already exists.") from e
    finally:
        conn.close()


def get_lead(lead_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    """Fetch a single lead by ID. Returns dict or None."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def get_lead_by_number(whatsapp_number: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Fetch a single lead by WhatsApp number. Used for duplicate check before sends."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM leads WHERE whatsapp_number = ?", (whatsapp_number,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Status management
# ---------------------------------------------------------------------------

def update_status(lead_id: int, new_status: str, db_path: Optional[str] = None) -> bool:
    """
    Transition a lead to a new status following the defined flow.
    Returns True if the transition succeeded, False otherwise.
    Logs warnings for invalid transitions.
    """
    if new_status not in ALL_STATUSES:
        logger.warning("Invalid status '%s' for lead %d", new_status, lead_id)
        return False

    conn = _get_connection(db_path)
    try:
        row = conn.execute("SELECT status FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if row is None:
            logger.warning("Lead %d not found for status update", lead_id)
            return False

        current = row["status"]

        # Terminal states block all further transitions
        if current in TERMINAL_STATES:
            logger.warning(
                "Lead %d is in terminal state '%s', cannot transition to '%s'",
                lead_id, current, new_status,
            )
            return False

        # Check the transition is valid
        allowed = VALID_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            logger.warning(
                "Invalid transition for lead %d: '%s' -> '%s' (allowed: %s)",
                lead_id, current, new_status, allowed,
            )
            return False

        now = _now_iso()
        conn.execute(
            "UPDATE leads SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, lead_id),
        )
        conn.commit()
        logger.info("Lead %d status: '%s' -> '%s'", lead_id, current, new_status)
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Generic field updates
# ---------------------------------------------------------------------------

# Fields that can be updated via update_lead()
UPDATABLE_FIELDS = {
    "formatted_name", "specialty_line", "headline", "cover_path",
    "contact_classification", "warm_up_message", "warm_up_sent_at",
    "last_lead_reply_at", "send_error_at", "whatsapp_number",
}


def update_lead(lead_id: int, db_path: Optional[str] = None, **fields) -> bool:
    """
    Update one or more fields on a lead.
    Only fields in UPDATABLE_FIELDS are accepted. Status changes must go through update_status().
    Returns True if the update succeeded.
    """
    invalid = set(fields.keys()) - UPDATABLE_FIELDS
    if invalid:
        logger.warning("Cannot update restricted fields: %s", invalid)
        return False

    if not fields:
        logger.warning("update_lead called with no fields for lead %d", lead_id)
        return False

    conn = _get_connection(db_path)
    try:
        # Verify lead exists
        row = conn.execute("SELECT id FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if row is None:
            logger.warning("Lead %d not found for update", lead_id)
            return False

        now = _now_iso()
        set_clauses = ", ".join("{} = ?".format(k) for k in fields)
        values = list(fields.values()) + [now, lead_id]

        conn.execute(
            "UPDATE leads SET {}, updated_at = ? WHERE id = ?".format(set_clauses),
            values,
        )
        conn.commit()
        logger.info("Lead %d updated fields: %s", lead_id, list(fields.keys()))
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

def append_conversation(
    lead_id: int, role: str, message: str, db_path: Optional[str] = None
) -> bool:
    """
    Append a message to the lead's conversation_history JSON array.
    Role should be 'lead' or 'agent'.
    Returns True on success.
    """
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT conversation_history FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        if row is None:
            logger.warning("Lead %d not found for conversation append", lead_id)
            return False

        history = json.loads(row["conversation_history"] or "[]")
        history.append({
            "role": role,
            "message": message,
            "timestamp": _now_iso(),
        })

        now = _now_iso()
        conn.execute(
            "UPDATE leads SET conversation_history = ?, updated_at = ? WHERE id = ?",
            (json.dumps(history, ensure_ascii=False), now, lead_id),
        )
        conn.commit()
        logger.info("Lead %d conversation appended (%s): %d messages total", lead_id, role, len(history))
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_leads_by_status(status: str, db_path: Optional[str] = None) -> List[dict]:
    """Return all leads with the given status, ordered by created_at ASC."""
    conn = _get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM leads WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]  # type: ignore[misc]
    finally:
        conn.close()


def get_all_leads(db_path: Optional[str] = None) -> List[dict]:
    """Return all leads, ordered by created_at DESC (newest first)."""
    conn = _get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]  # type: ignore[misc]
    finally:
        conn.close()


def is_opt_out(whatsapp_number: str, db_path: Optional[str] = None) -> bool:
    """Check if a phone number belongs to a lead with status = opt_out."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM leads WHERE whatsapp_number = ? AND status = 'opt_out'",
            (whatsapp_number,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auto-initialise on import
# ---------------------------------------------------------------------------

init_db()
