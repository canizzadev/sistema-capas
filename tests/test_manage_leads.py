"""
Unit tests for execution/manage_leads.py
Uses a temporary file-based SQLite DB — fully isolated per test.

Run with: python -m pytest tests/test_manage_leads.py -v
"""

import json
import os
import tempfile
import pytest
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.manage_leads import (
    init_db,
    create_lead,
    get_lead,
    get_lead_by_number,
    update_status,
    update_lead,
    append_conversation,
    get_leads_by_status,
    get_all_leads,
    is_opt_out,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
    ALL_STATUSES,
)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Create a fresh temporary DB file for each test and expose its path."""
    db_file = str(tmp_path / "test_leads.db")
    init_db(db_path=db_file)
    # Store in a module-level variable so helpers can access it
    fresh_db.path = db_file
    yield db_file


def _db():
    """Return the current test's DB path."""
    return fresh_db.path


def _make_lead(**overrides):
    """Helper to create a lead with sensible defaults."""
    defaults = {
        "instagram_url": "https://instagram.com/dra.teste",
        "username": "dra.teste",
        "whatsapp_number": "5511999990001",
        "formatted_name": "Dra. Teste",
        "specialty_line": "Dermatologista",
        "headline": "Transformando a saúde da pele",
        "cover_path": ".tmp/capas/dra_teste.zip",
        "db_path": _db(),
    }
    defaults.update(overrides)
    return create_lead(**defaults)


# ============================================================
# init_db tests
# ============================================================

class TestInitDb:
    def test_init_db_creates_table(self):
        """Table should exist after init_db."""
        import sqlite3
        conn = sqlite3.connect(_db())
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='leads'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_db_idempotent(self):
        """Calling init_db twice should not raise."""
        init_db(db_path=_db())
        init_db(db_path=_db())


# ============================================================
# create_lead tests
# ============================================================

class TestCreateLead:
    def test_create_lead_returns_dict(self):
        lead = _make_lead()
        assert isinstance(lead, dict)
        assert lead["id"] is not None
        assert lead["username"] == "dra.teste"
        assert lead["status"] == "cover_generated"
        assert lead["conversation_history"] == "[]"
        assert lead["created_at"] is not None
        assert lead["updated_at"] is not None

    def test_create_lead_all_fields(self):
        lead = _make_lead()
        expected_keys = {
            "id", "instagram_url", "username", "whatsapp_number",
            "formatted_name", "specialty_line", "headline", "cover_path",
            "status", "contact_classification", "warm_up_message",
            "warm_up_sent_at", "last_lead_reply_at", "send_error_at",
            "conversation_history", "created_at", "updated_at",
        }
        assert expected_keys == set(lead.keys())

    def test_create_lead_duplicate_number_rejected(self):
        _make_lead(whatsapp_number="5511999990002")
        with pytest.raises(ValueError, match="already exists"):
            _make_lead(whatsapp_number="5511999990002")


# ============================================================
# get_lead tests
# ============================================================

class TestGetLead:
    def test_get_lead_by_id(self):
        created = _make_lead()
        fetched = get_lead(created["id"], db_path=_db())
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["username"] == "dra.teste"

    def test_get_lead_not_found(self):
        result = get_lead(99999, db_path=_db())
        assert result is None

    def test_get_lead_by_number(self):
        _make_lead(whatsapp_number="5511999990003")
        fetched = get_lead_by_number("5511999990003", db_path=_db())
        assert fetched is not None
        assert fetched["whatsapp_number"] == "5511999990003"

    def test_get_lead_by_number_not_found(self):
        result = get_lead_by_number("0000000000", db_path=_db())
        assert result is None


# ============================================================
# update_status tests
# ============================================================

class TestUpdateStatus:
    def test_valid_transition(self):
        lead = _make_lead()
        result = update_status(lead["id"], "warm_up_sent", db_path=_db())
        assert result is True
        updated = get_lead(lead["id"], db_path=_db())
        assert updated["status"] == "warm_up_sent"

    def test_full_happy_path(self):
        """Walk through the entire status flow to meeting_scheduled."""
        lead = _make_lead()
        lid = lead["id"]
        assert update_status(lid, "warm_up_sent", db_path=_db())
        assert update_status(lid, "warm_up_responded", db_path=_db())
        assert update_status(lid, "message_sent", db_path=_db())
        assert update_status(lid, "awaiting_response", db_path=_db())
        assert update_status(lid, "in_conversation", db_path=_db())
        assert update_status(lid, "meeting_scheduled", db_path=_db())
        final = get_lead(lid, db_path=_db())
        assert final["status"] == "meeting_scheduled"

    def test_invalid_transition_skips(self):
        lead = _make_lead()
        result = update_status(lead["id"], "in_conversation", db_path=_db())
        assert result is False
        unchanged = get_lead(lead["id"], db_path=_db())
        assert unchanged["status"] == "cover_generated"

    def test_terminal_status_blocks_transition(self):
        lead = _make_lead()
        lid = lead["id"]
        update_status(lid, "warm_up_sent", db_path=_db())
        update_status(lid, "warm_up_responded", db_path=_db())
        update_status(lid, "message_sent", db_path=_db())
        update_status(lid, "awaiting_response", db_path=_db())
        update_status(lid, "opt_out", db_path=_db())
        assert update_status(lid, "in_conversation", db_path=_db()) is False
        assert get_lead(lid, db_path=_db())["status"] == "opt_out"

    def test_opt_out_never_reversed(self):
        lead = _make_lead()
        lid = lead["id"]
        update_status(lid, "warm_up_sent", db_path=_db())
        update_status(lid, "warm_up_responded", db_path=_db())
        update_status(lid, "message_sent", db_path=_db())
        update_status(lid, "awaiting_response", db_path=_db())
        update_status(lid, "opt_out", db_path=_db())
        for status in ALL_STATUSES:
            assert update_status(lid, status, db_path=_db()) is False

    def test_invalid_status_name(self):
        lead = _make_lead()
        result = update_status(lead["id"], "nonexistent_status", db_path=_db())
        assert result is False

    def test_lead_not_found(self):
        result = update_status(99999, "warm_up_sent", db_path=_db())
        assert result is False


# ============================================================
# update_lead tests
# ============================================================

class TestUpdateLead:
    def test_update_single_field(self):
        lead = _make_lead()
        result = update_lead(lead["id"], db_path=_db(), contact_classification="A")
        assert result is True
        updated = get_lead(lead["id"], db_path=_db())
        assert updated["contact_classification"] == "A"

    def test_update_multiple_fields(self):
        lead = _make_lead()
        result = update_lead(
            lead["id"], db_path=_db(),
            warm_up_message="Bom dia!",
            warm_up_sent_at="2026-03-06T12:00:00+00:00",
        )
        assert result is True
        updated = get_lead(lead["id"], db_path=_db())
        assert updated["warm_up_message"] == "Bom dia!"
        assert updated["warm_up_sent_at"] == "2026-03-06T12:00:00+00:00"

    def test_reject_status_update_via_update_lead(self):
        """Status changes must go through update_status(), not update_lead()."""
        lead = _make_lead()
        result = update_lead(lead["id"], db_path=_db(), status="warm_up_sent")
        assert result is False

    def test_reject_unknown_field(self):
        lead = _make_lead()
        result = update_lead(lead["id"], db_path=_db(), nonexistent_field="x")
        assert result is False

    def test_lead_not_found(self):
        result = update_lead(99999, db_path=_db(), formatted_name="test")
        assert result is False

    def test_no_fields_provided(self):
        lead = _make_lead()
        result = update_lead(lead["id"], db_path=_db())
        assert result is False


# ============================================================
# append_conversation tests
# ============================================================

class TestAppendConversation:
    def test_append_single_message(self):
        lead = _make_lead()
        result = append_conversation(lead["id"], "lead", "Bom dia!", db_path=_db())
        assert result is True
        updated = get_lead(lead["id"], db_path=_db())
        history = json.loads(updated["conversation_history"])
        assert len(history) == 1
        assert history[0]["role"] == "lead"
        assert history[0]["message"] == "Bom dia!"
        assert "timestamp" in history[0]

    def test_append_multiple_messages(self):
        lead = _make_lead()
        append_conversation(lead["id"], "lead", "Bom dia!", db_path=_db())
        append_conversation(lead["id"], "agent", "Bom dia! Tudo bem?", db_path=_db())
        append_conversation(lead["id"], "lead", "Sim!", db_path=_db())
        updated = get_lead(lead["id"], db_path=_db())
        history = json.loads(updated["conversation_history"])
        assert len(history) == 3
        assert history[0]["role"] == "lead"
        assert history[1]["role"] == "agent"
        assert history[2]["role"] == "lead"

    def test_append_lead_not_found(self):
        result = append_conversation(99999, "lead", "Oi", db_path=_db())
        assert result is False


# ============================================================
# Query helpers tests
# ============================================================

class TestQueryHelpers:
    def test_get_leads_by_status(self):
        _make_lead(whatsapp_number="5511000000001")
        _make_lead(whatsapp_number="5511000000002")
        _make_lead(whatsapp_number="5511000000003")
        leads = get_leads_by_status("cover_generated", db_path=_db())
        assert len(leads) == 3

    def test_get_leads_by_status_empty(self):
        leads = get_leads_by_status("warm_up_sent", db_path=_db())
        assert leads == []

    def test_get_all_leads(self):
        _make_lead(whatsapp_number="5511000000004")
        _make_lead(whatsapp_number="5511000000005")
        leads = get_all_leads(db_path=_db())
        assert len(leads) == 2

    def test_get_all_leads_empty(self):
        leads = get_all_leads(db_path=_db())
        assert leads == []

    def test_is_opt_out_true(self):
        lead = _make_lead(whatsapp_number="5511000000006")
        lid = lead["id"]
        update_status(lid, "warm_up_sent", db_path=_db())
        update_status(lid, "warm_up_responded", db_path=_db())
        update_status(lid, "message_sent", db_path=_db())
        update_status(lid, "awaiting_response", db_path=_db())
        update_status(lid, "opt_out", db_path=_db())
        assert is_opt_out("5511000000006", db_path=_db()) is True

    def test_is_opt_out_false(self):
        _make_lead(whatsapp_number="5511000000007")
        assert is_opt_out("5511000000007", db_path=_db()) is False

    def test_is_opt_out_number_not_found(self):
        assert is_opt_out("0000000000", db_path=_db()) is False
