# Directive: Lead Database Manager

> Script: `execution/manage_leads.py`
> Database: SQLite at `DB_PATH` (from `.env`, default `./sistema_capas.db`)

---

## Purpose

Single source of truth for all lead state. Every prospecting module reads and writes leads through this script. Never modify the database directly — always use the functions below.

---

## Schema — `leads` Table

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `instagram_url` | TEXT | Original Instagram profile URL |
| `username` | TEXT | Extracted Instagram username |
| `whatsapp_number` | TEXT UNIQUE | Lead's WhatsApp number (prevents duplicate campaigns) |
| `formatted_name` | TEXT | GPT-formatted doctor name |
| `specialty_line` | TEXT | GPT-extracted specialty |
| `headline` | TEXT | GPT-generated headline |
| `cover_path` | TEXT | Path to generated cover ZIP |
| `status` | TEXT | Current flow status (see below) |
| `contact_classification` | TEXT | A/B/C/D (set after warm-up reply) |
| `warm_up_message` | TEXT | Which warm-up message was sent |
| `warm_up_sent_at` | TEXT | ISO 8601 timestamp |
| `last_lead_reply_at` | TEXT | ISO 8601 timestamp of last reply |
| `send_error_at` | TEXT | ISO 8601 timestamp of last send error |
| `conversation_history` | TEXT | JSON array of `{role, message, timestamp}` |
| `created_at` | TEXT | ISO 8601 |
| `updated_at` | TEXT | ISO 8601 |

---

## Status Flow

```
cover_generated → warm_up_sent → warm_up_responded → message_sent
  → awaiting_response → in_conversation
    → meeting_scheduled  [terminal]
    → lost               [terminal]
    → opt_out            [terminal]
```

**Terminal states** (`meeting_scheduled`, `lost`, `opt_out`): No further transitions allowed. `opt_out` is **never** reversible.

`send_error` is a **side state** — set via `send_error_at` field, does not replace the flow status.

---

## Functions

| Function | When to call |
|---|---|
| `create_lead(...)` | After `/prospect` creates a new lead with `cover_generated` |
| `get_lead(id)` | Fetch full lead data by ID |
| `get_lead_by_number(number)` | Before creating a lead — check for duplicates |
| `update_status(id, status)` | On every status transition (validates the flow) |
| `update_lead(id, **fields)` | Update metadata fields (classification, timestamps, etc.) |
| `append_conversation(id, role, msg)` | After every sent or received message |
| `get_leads_by_status(status)` | Queue dispatcher: batch fetch by status |
| `get_all_leads()` | Dashboard: list all leads |
| `is_opt_out(number)` | Before any send — **always** check this first |

---

## Rules

1. **Never delete** lead records — only update status.
2. **opt_out is terminal** — no script may revert it.
3. **Always check** `is_opt_out()` or `get_lead_by_number()` before sending messages.
4. **Status changes** must use `update_status()` — never write status directly.
5. **Conversation history** is append-only via `append_conversation()`.
6. All timestamps are **UTC ISO 8601**.

---

## Edge Cases

- **Duplicate number**: `create_lead()` raises `ValueError`. Caller must handle.
- **Invalid transition**: `update_status()` returns `False` and logs a warning.
- **Lead not found**: All functions return `None` or `False` gracefully — never crash.

---

*Created: 2026-03-06*
