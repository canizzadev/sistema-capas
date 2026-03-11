# Directive: WhatsApp Message Sender (Z-API)

> Script: `execution/send_whatsapp.py`
> API: Z-API (`WHATSAPP_API_KEY` + `WHATSAPP_INSTANCE` in `.env`)

---

## Purpose

All outbound WhatsApp communication for the Behind prospecting system. No other script should call Z-API directly — always use this module.

---

## 4 Send Modes

| Function | When to call | Checks opt_out? | Checks window? |
|---|---|---|---|
| `send_warm_up(number, lead_id)` | Queue dispatcher warm-up batch | ✅ Yes | ✅ Yes |
| `send_sequence(lead_id)` | After contact classification on warm-up reply | ✅ Yes | ❌ No (triggered by reply) |
| `send_followup(lead_id, message)` | Queue dispatcher Tue-Fri follow-up loop | ✅ Yes | ✅ Yes |
| `send_notification(number, message)` | Team alerts (errors, meetings, opt-outs) | ❌ No | ❌ No |

---

## Send Window

- Default: 08:00–18:00 Brazil time, business days (Mon–Fri)
- Configured via `WHATSAPP_SEND_WINDOW_START` / `WHATSAPP_SEND_WINDOW_END` in `.env`
- `send_notification` bypasses this — team alerts are always sent

---

## Retry Logic

1. First attempt fails → wait 30 seconds → retry once
2. Second attempt fails → set `send_error_at` on lead → notify team via `send_notification`
3. `send_error` does NOT replace the lead's flow status

---

## Sequence Dispatch Rules

- Variant (A/B/C/D) based on `contact_classification` in DB
- Delays: 3–5s between text, 4–6s before image
- `__IMAGE__` token → extract `capa.png` from lead's ZIP → send as base64
- Never send the ZIP file itself
- On completion: status → `message_sent` → `awaiting_response`

---

## Logging

Every send attempt is logged to `.tmp/whatsapp_logs/{date}_{number}.json`
containing: timestamp, number, payload (image data omitted), response, success flag.

---

## Critical Rules

1. **Always check `is_opt_out()` before sending** (except `send_notification`)
2. **Never bypass the send window** for warm-ups or follow-ups
3. **Never send the ZIP file** — only the extracted PNG
4. **Config files are in `config/`** — `warmup_messages.json`, `sequence_messages.json`
5. **Log every attempt** — success or failure

---

## Required .env Variables

```
WHATSAPP_API_KEY=
WHATSAPP_INSTANCE=
WHATSAPP_SEND_WINDOW_START=08:00
WHATSAPP_SEND_WINDOW_END=18:00
WARMUP_MIN_DELAY_SECONDS=45
WARMUP_MAX_DELAY_SECONDS=90
SEQUENCE_MIN_DELAY_SECONDS=3
SEQUENCE_MAX_DELAY_SECONDS=5
SEQUENCE_IMAGE_MIN_DELAY_SECONDS=4
SEQUENCE_IMAGE_MAX_DELAY_SECONDS=6
TEAM_NOTIFICATION_NUMBER=
```

---

*Created: 2026-03-06*
