# Directive: Conversational Agent (AI Brain)

> Script: `execution/conversational_agent.py`
> Relies on: `AGENT_MODEL` and `OPENAI_API_KEY` in `.env`

---

## Purpose

Acts as the intelligence layer for the Behind prospecting system. Evaluates incoming messages and chooses the correct conversational response, enforcing the overarching business rules (graceful close, objection handling, meeting focus).

---

## Modus Operandi

The agent operates in two distinct branches (triggered by `api.py` webhook):

### Branch A (`handle_warm_up_response`)
- **When**: Lead responds to the initial warm-up message.
- **Goal**: Classify the contact (Doctor, Secretary, Busy, Generic) and seamlessly bridge into the 5-part message sequence.
- **Process**:
  1. Prompts GPT-4o-mini to return a JSON with `classification` and `personalized_reply`.
  2. Updates DB with classification.
  3. Sends `personalized_reply`.
  4. Calls `send_whatsapp.send_sequence(lead_id)`.

### Branch B (`handle_conversation_reply`)
- **When**: Lead responds after the sequence is dispatched (in statuses `message_sent`, `awaiting_response`, `in_conversation`).
- **Goal**: Handle objections, push for a 20-min strategy meeting, and offer real calendar slots.
- **Process**:
  1. Pulls full conversation history from DB.
  2. Requests available slots from `check_calendar.py` (P8).
  3. Prompts GPT-4o-mini with Identity, Obection Playbook, Slots, and History.
  4. Returns JSON with `response`, `status_update` (`unchanged`, `meeting_scheduled`, `lost`, `opt_out`), and `action` (`book_calendar`, `none`).
  5. Sends the response via `send_whatsapp`.
  6. Automatically updates the lead status if a terminal state is reached, sending a team notification.

---

## Fallbacks & Resilience

- **JSON Parsing**: The script strips markdown block formatting (` ```json ... ``` `) specifically because LLMs often wrap JSON outputs.
- **API Failure Branch A**: Defaults to classification "B" and triggers the sequence anyway, ensuring prospects don't get stuck.
- **API Failure Branch B**: Sends a polite generic connection error message so the conversation can be retried by the prospect.

---

## Missing Components (To Be Implemented)

- **`check_calendar.py`**: The agent currently mocks calendar slots and booking behaviors via `try/except ImportError`. Once P8 is implemented, the agent will dynamically inject real Google Calendar slots into the prompt and trigger real bookings.

---

*Created: 2026-03-06*
