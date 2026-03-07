# Directive: Google Calendar Scheduling

> Script: `execution/check_calendar.py`
> Relies on: `GOOGLE_CALENDAR_ID` in `.env`, plus `credentials.json` (OAuth2).

---

## Purpose

Enables the Conversational Agent to fetch real-time availability from a Google Calendar and seamlessly book meetings that the AI has confirmed with a lead.

---

## Authentication Rules

- **OAuth2 Flow**: Uses Google's standard `InstalledAppFlow`.
- **First Run**: The very first time `get_calendar_service()` is called, if `token.json` is missing, it will open a browser window requesting auth via `credentials.json`.
- **Server Environment**: On a headless server, this auth flow must be completed locally first, and then the generated `token.json` file must be uploaded to the server alongside `credentials.json`.
- **Fallback**: If `credentials.json` does NOT exist, the script intercepts the failure and returns mock availability slots instead of crashing, allowing testing to continue.

---

## Functions

### `get_available_slots(days_ahead=5, slots_needed=3) -> List[str]`
1. Uses the Google Calendar `freebusy` API to check `CALENDAR_ID`.
2. Scans from "tomorrow" up to `days_ahead`.
3. Filters days by `MEETING_DAYS` in `.env`.
4. Filters hours between 09:00 and 18:00 (hardcoded business hours).
5. Ensures slots are at least 30 minutes long (`CALENDAR_MEETING_DURATION_MINUTES`).
6. Ensures variety (if one slot is found, skips a few hours before picking the next one).
7. Returns formatted Portuguese strings: `["Sexta-feira, 15/03 às 14:00", ...]`

### `book_slot(date_str, time_str, lead_name, lead_number) -> str`
1. Creates an event on `CALENDAR_ID`.
2. Title format: `Prospecção: Reunião com {lead_name}`
3. Body includes the lead's WhatsApp number.
4. Returns the successful Event ID.
5. *(Note for V1)*: Precise date/time NLP parsing from Portuguese text is mocked to fallback to "tomorrow 14:00" if parsing fails, ensuring the booking API itself works.

---

## Usage in Agent System

1. Agent calls `get_available_slots()`.
2. Agent injects those string options into its reply (e.g., "Manda o melhor pra você: D1 às H1 ou D2 às H2?").
3. Lead responds with an option.
4. Agent prompts GPT to output `{ action: "book_calendar" }`.
5. Code intercepts `action == book_calendar`, calls `book_slot`, and then transitions the lead to `meeting_scheduled`.

---

*Created: 2026-03-06*
