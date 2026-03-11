"""
manage_discovery.py — Discovery Database Manager (SQLite)
Manages the doctor discovery pipeline tables, separate from the leads table.

Tables:
  - discovered_doctors: approved profiles awaiting promotion to leads
  - rejected_profiles: profiles that failed analysis filters
  - discovery_search_log: tracks which search terms have been used

Run init_discovery_db() on import to ensure tables exist.
All timestamps are stored as ISO 8601 strings.
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
# Database helpers (same pattern as manage_leads.py)
# ---------------------------------------------------------------------------

def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _row_to_dict(row) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

CREATE_DISCOVERED_DOCTORS_SQL = """
CREATE TABLE IF NOT EXISTS discovered_doctors (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    username                TEXT    NOT NULL UNIQUE,
    name                    TEXT    NOT NULL DEFAULT '',
    bio                     TEXT    NOT NULL DEFAULT '',
    external_link           TEXT    NOT NULL DEFAULT '',
    followers               INTEGER DEFAULT NULL,
    profile_pic_url         TEXT    NOT NULL DEFAULT '',
    especialidade_detectada TEXT    NOT NULL DEFAULT '',
    cidade_busca            TEXT    NOT NULL DEFAULT '',
    photo_analysis          TEXT    NOT NULL DEFAULT '{}',
    bio_analysis            TEXT    NOT NULL DEFAULT '{}',
    created_at              TEXT    NOT NULL
);
"""

CREATE_REJECTED_PROFILES_SQL = """
CREATE TABLE IF NOT EXISTS rejected_profiles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    username                TEXT    NOT NULL,
    rejection_reason        TEXT    NOT NULL DEFAULT '',
    created_at              TEXT    NOT NULL
);
"""

CREATE_DISCOVERY_SEARCH_LOG_SQL = """
CREATE TABLE IF NOT EXISTS discovery_search_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    search_term             TEXT    NOT NULL,
    results_found           INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT    NOT NULL
);
"""


def init_discovery_db(db_path: Optional[str] = None) -> None:
    conn = _get_connection(db_path)
    try:
        conn.execute(CREATE_DISCOVERED_DOCTORS_SQL)
        conn.execute(CREATE_REJECTED_PROFILES_SQL)
        conn.execute(CREATE_DISCOVERY_SEARCH_LOG_SQL)
        conn.commit()
        logger.info("Discovery tables initialised (path=%s)", db_path or DB_PATH)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Discovered doctors — CRUD
# ---------------------------------------------------------------------------

def save_approved(data: dict, db_path: Optional[str] = None) -> dict:
    """
    Insert an approved doctor profile.
    data must contain at least 'username'.
    Returns the full row as a dict.
    """
    now = _now_iso()
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO discovered_doctors (
                username, name, bio, external_link, followers,
                profile_pic_url, especialidade_detectada, cidade_busca,
                photo_analysis, bio_analysis, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("username", ""),
                data.get("name", ""),
                data.get("bio", ""),
                data.get("external_link", ""),
                data.get("followers"),
                data.get("profile_pic_url", ""),
                data.get("especialidade_detectada", ""),
                data.get("cidade_busca", ""),
                json.dumps(data.get("photo_analysis", {}), ensure_ascii=False),
                json.dumps(data.get("bio_analysis", {}), ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
        doc_id = cursor.lastrowid
        logger.info("Approved doctor saved: id=%d, username=%s", doc_id, data.get("username"))
        result = _row_to_dict(
            conn.execute("SELECT * FROM discovered_doctors WHERE id = ?", (doc_id,)).fetchone()
        )
        return result  # type: ignore[return-value]
    except sqlite3.IntegrityError as e:
        logger.warning("Duplicate username '%s' in discovered_doctors: %s", data.get("username"), e)
        raise ValueError(f"Doctor '{data.get('username')}' already in discovered_doctors.") from e
    finally:
        conn.close()


def get_discovered_doctors(db_path: Optional[str] = None) -> List[dict]:
    """Return all discovered doctors, newest first."""
    conn = _get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM discovered_doctors ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]  # type: ignore[misc]
    finally:
        conn.close()


def get_discovered_doctor(doctor_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    """Fetch a single discovered doctor by ID."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM discovered_doctors WHERE id = ?", (doctor_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def delete_discovered_doctor(doctor_id: int, db_path: Optional[str] = None) -> bool:
    """Remove a discovered doctor after promotion. Returns True if deleted."""
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM discovered_doctors WHERE id = ?", (doctor_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Rejected profiles
# ---------------------------------------------------------------------------

def save_rejected(username: str, reason: str, db_path: Optional[str] = None) -> None:
    """Log a rejected profile with the reason."""
    now = _now_iso()
    conn = _get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO rejected_profiles (username, rejection_reason, created_at) VALUES (?, ?, ?)",
            (username, reason, now),
        )
        conn.commit()
        logger.info("Rejected profile: username=%s, reason=%s", username, reason)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Search log
# ---------------------------------------------------------------------------

def log_search(term: str, count: int, db_path: Optional[str] = None) -> None:
    """Record a search term and how many results it returned."""
    now = _now_iso()
    conn = _get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO discovery_search_log (search_term, results_found, created_at) VALUES (?, ?, ?)",
            (term, count, now),
        )
        conn.commit()
        logger.info("Search logged: term='%s', results=%d", term, count)
    finally:
        conn.close()


def was_searched(term: str, db_path: Optional[str] = None) -> bool:
    """Check if a search term has already been used."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM discovery_search_log WHERE search_term = ?", (term,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cross-table checks
# ---------------------------------------------------------------------------

def is_already_processed(username: str, db_path: Optional[str] = None) -> bool:
    """
    Check if a username already exists in discovered_doctors, rejected_profiles,
    or the main leads table.
    """
    conn = _get_connection(db_path)
    try:
        # Check discovered_doctors
        row = conn.execute(
            "SELECT id FROM discovered_doctors WHERE username = ?", (username,)
        ).fetchone()
        if row:
            return True

        # Check rejected_profiles
        row = conn.execute(
            "SELECT id FROM rejected_profiles WHERE username = ?", (username,)
        ).fetchone()
        if row:
            return True

        # Check main leads table
        row = conn.execute(
            "SELECT id FROM leads WHERE username = ?", (username,)
        ).fetchone()
        if row:
            return True

        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def get_discovery_stats(db_path: Optional[str] = None) -> dict:
    """Return aggregate statistics for the discovery pipeline."""
    conn = _get_connection(db_path)
    try:
        approved = conn.execute("SELECT COUNT(*) as c FROM discovered_doctors").fetchone()["c"]
        rejected = conn.execute("SELECT COUNT(*) as c FROM rejected_profiles").fetchone()["c"]
        searches = conn.execute("SELECT COUNT(*) as c FROM discovery_search_log").fetchone()["c"]
        total_results = conn.execute(
            "SELECT COALESCE(SUM(results_found), 0) as c FROM discovery_search_log"
        ).fetchone()["c"]

        return {
            "approved": approved,
            "rejected": rejected,
            "total_searches": searches,
            "total_results_found": total_results,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auto-initialise on import
# ---------------------------------------------------------------------------

init_discovery_db()
