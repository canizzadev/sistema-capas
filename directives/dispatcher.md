# Directive: Queue Dispatcher

> Script: `execution/queue_dispatcher.py`
> Relies on: `WARMUP_BLOCK_SIZE`, `WARMUP_BLOCK_GAP_MINUTES`, `WARMUP_MIN_DELAY_SECONDS`, `WARMUP_MAX_DELAY_SECONDS` in `.env`

---

## Purpose

The automated heartbeat of the Behind prospecting system. Runs as an infinite background daemon that manages time-sensitive, batch operations: dispatching initial warm-up messages, triggering intelligent mid-week follow-ups, and executing the Friday end-of-week cleanup.

---

## Operating Modes

### 1. Warm-up Dispatch
- Runs continuously during business hours.
- Finds leads with status `cover_generated`.
- Takes batches of size `WARMUP_BLOCK_SIZE` (default 25).
- Sends the `warm_up` message to each lead via `send_whatsapp.py`, sleeping a random duration between `WARMUP_MIN_DELAY` and `WARMUP_MAX_DELAY` (45-90s) between sends.
- Once the block is sent, the daemon sleeps for `WARMUP_BLOCK_GAP_MINUTES` (90 mins) to protect the WhatsApp account reputation before attempting the next block.

### 2. General Follow-up
- Runs only from Tuesday to Friday inside business hours.
- Queries leads in active states: `message_sent` or `awaiting_response`.
- Calls the AI Brain (`generate_system_followup` in `conversational_agent.py`) to evaluate the lead's history and generate a context-aware follow-up message to revive the conversation.
- **Throttle**: Ensures a maximum of 1 system-initiated follow-up per lead every 12 hours to avoid spamming.

### 3. Friday Clean-up
- Activates automatically during the last hour of the Friday send window (e.g., 17:00 - 18:00 if `WHATSAPP_SEND_WINDOW_END` is 18:00).
- Applies to all active leads (`warm_up_sent`, `message_sent`, `awaiting_response`).
- Forces the AI Brain to evaluate the entire week's history.
- The AI generates a polite graceful close message and permanently marks the lead as `lost` if they demonstrated zero interest across the week. If they showed interest but are slow, the AI leaves them untouched for the next week.

---

## Usage

Simply run the dispatcher as a background process:
```bash
python -m execution.queue_dispatcher
```
It will log all batching and follow-up activities to standard out.

---

*Created: 2026-03-06*
