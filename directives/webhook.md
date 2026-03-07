# Directive: WhatsApp Webhook Receiver

> Endpoint: `POST /webhook/whatsapp` in `execution/api.py`
> Connected to: Z-API webhook configuration

---

## Purpose

Receives all inbound WhatsApp messages from Z-API. Routes to the correct processing branch based on lead status. Does NOT send messages — delegates to `send_whatsapp.py` and `conversational_agent.py`.

---

## Z-API Payload Structure

```json
{
  "phone": "5511999990001",
  "text": {
    "message": "Bom dia, sou a secretária da Dra."
  }
}
```

The endpoint handles both `text.message` (object format) and plain `text` (string format) payloads.

---

## Branch Routing

| Lead Status | Branch | Action |
|---|---|---|
| `warm_up_sent` | **A** | Classify contact → personalized reply → 5-part sequence |
| `message_sent` | **B** | Transition to `in_conversation` → conversation mode |
| `awaiting_response` | **B** | Transition to `in_conversation` → conversation mode |
| `in_conversation` | **B** | Continue conversation mode |
| Terminal / other | — | Log message, no action |
| Unknown number | — | Ignore |

---

## What the Webhook Always Does

1. Finds lead by phone number
2. Appends message to `conversation_history`
3. Updates `last_lead_reply_at`
4. Routes to appropriate branch

---

## Dependencies

- `execution/manage_leads.py` — status checks, updates, conversation history
- `execution/conversational_agent.py` (P7) — classification + conversation (imported dynamically, graceful fallback if not yet available)
- `execution/send_whatsapp.py` — called by conversational_agent for outbound replies

---

## Edge Cases

- **Unknown number**: Returns `{"status": "unknown_number"}`, no error
- **Empty payload**: Returns `{"status": "ignored"}`
- **Agent not available**: Logs warning, message is still saved to history
- **Terminal status lead**: Message saved but no action taken

---

*Created: 2026-03-06*
