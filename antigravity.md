# antigravity.md
# Universal Observations — Read Before Any Implementation

> Derived from reading canizzadev/sistema-capas. Consult before any action.

---

## 1. Before Creating Any Script or Automation

Always check first:
- Does execution/ already have a script for this?
- Does directives/ already cover this flow?
- Does the action consume paid tokens (OpenAI, Gemini)? — Confirm with user first.
- Is the action irreversible (WhatsApp send, Calendar event)? — Confirm before executing.

Never:
- Create duplicate scripts without checking existing ones.
- Overwrite directives without asking.
- Run external-impact actions without a dry-run/sandbox mode first.

---

## 2. Mandatory Architecture — 3 Layers, No Mixing

| Layer | Responsibility | Location |
|---|---|---|
| Directive | What and why | directives/ |
| Orchestration | Order and error handling | AI agent |
| Execution | Deterministic work | execution/ |

The agent does NOT scrape Instagram directly.
The agent does NOT call OpenAI or Gemini directly.
The agent reads the directive, defines inputs/outputs, and calls the right script.

---

## 3. Existing Stack — Know It Before Extending It

| Component | Technology | File |
|---|---|---|
| Web framework | FastAPI + Uvicorn | execution/api.py |
| Frontend | StaticFiles, static/index.html | execution/api.py |
| Instagram scraping | requests + BeautifulSoup (3-tier) | execution/scrape_instagram.py |
| AI copy generation | OpenAI GPT-4o-mini | execution/generate_titles.py |
| Image outpainting | Google Gemini 2.5 Flash Image | execution/generate_cover.py |
| Image compositing | Pillow | execution/generate_cover.py |
| PDF export | ReportLab | execution/generate_cover.py |
| Batch export | openpyxl | execution/api.py |
| Config | python-dotenv (.env) | All scripts |

Do not introduce new AI providers, image libraries, or web frameworks without user approval.

### Directory Structure

```
execution/      Python scripts — deterministic execution layer
directives/     SOPs in Markdown — what to do and why
static/         Frontend assets served by FastAPI (fonts/, seta.png, index.html)
config/         JSON config files editable without code changes
                  warmup_messages.json   — warm-up message pool
                  sequence_messages.json — 4 sequence variants (A/B/C/D)
.tmp/           Intermediate files (capas/, whatsapp_logs/) — never commit, always regenerated
.env            Environment variables and API keys
credentials.json, token.json  — Google OAuth (in .gitignore)
```

When a new script requires editable configuration (message pools, thresholds, templates),
store it as JSON in config/ and load it at runtime. Never hardcode these values in scripts.

---

## 4. API and Caching Rules

### scrape_instagram.py
- 3-tier fallback: i.instagram.com API > ?__a=1 endpoint > HTML meta tags
- 5-minute in-memory TTL cache — never bypass
- 2-second delay between requests in batch mode
- Error types: invalid_url, private_profile, not_found, rate_limited, timeout, scrape_failed
- Always handle all 5 error types explicitly. Never assume success.

### generate_titles.py
- Model: gpt-4o-mini — do not upgrade to gpt-4o without cost check with user
- 10-minute in-memory TTL cache keyed by name||bio
- Output keys: formatted_name, specialty_line, headline
- GPT may return markdown fences — strip before JSON parsing (already handled, preserve it)
- Always provide fallback values — a failed GPT call must never crash the cover pipeline

### generate_cover.py
- Uses gemini-2.5-flash-image for 16:9 outpainting
- Mirror-blur fallback if Gemini fails — preserve this fallback in any refactor
- Gemini is the most expensive call in the pipeline — never call it twice for the same image

---

## 5. Cover Generation Rules

- Output: always a ZIP with capa.png + capa.pdf
- PDF dimensions fixed: 841.89 x 438.49 pt
- PNG canvas fixed: 1920 x 1000 px
- Fonts in static/fonts/ — use safe_load_font(), fall back to ImageFont.load_default()
- Button icon at static/seta.png — if missing, pipeline continues without it (no exception)
- Brand color: always run through validate_hex_color() before use
- Gradient button: brand color +0.35L lightened, -0.10L darkened in HSL space
- Design coordinates are mapped from Figma. Do not change base_x or curr_y without user instruction.

---

## 6. Upload Constraints (api.py)

- MAX_UPLOAD_SIZE = 10 MB hard limit
- ALLOWED_IMAGE_TYPES = image/jpeg, image/png, image/webp
- All new endpoints accepting images must enforce these same constraints.

---

## 7. WhatsApp Rules (not yet built)

- Send window: 08:00-18:00 business days only (configurable via .env)
- Each message paragraph = separate WhatsApp message with random delay between
- Log every send attempt to .tmp/whatsapp_logs/{date}_{number}.json
- On failure: retry once after 30 seconds. If still fails: status = send_error, notify user.
- Always check opt_out in DB before sending. opt_out = abort immediately.
- Cover delivery: unpack ZIP, send capa.png only — never the ZIP file.
- Maximum 1 follow-up per lead per day (Tue-Fri).

---

## 8. Lead Database Rules (not yet built)

Complete status flow (ordered). Terminal states marked with [T]:

  cover_generated
    -> warm_up_sent
    -> warm_up_responded
    -> message_sent
    -> awaiting_response
    -> in_conversation
    -> meeting_scheduled  [T] positive outcome
    -> lost               [T] no engagement or failed conversion
    -> opt_out            [T] explicit refusal
  
  send_error: side state, not in main flow. Set when send fails twice.
              Notify user. Lead stays in its current flow status.
              Never blocks other leads from being processed.

Status transition rules (exact moments):
  cover_generated    SET when: lead record created in DB after /prospect is called
  warm_up_sent       SET when: send_whatsapp.py confirms warm-up delivery to Z-API
  warm_up_responded  SET when: webhook receives any reply from lead while status = warm_up_sent
  message_sent       SET when: all 5 sequence messages confirmed sent by Z-API
  awaiting_response  SET when: message_sent is complete and no reply yet received
  in_conversation    SET when: webhook receives any reply while status = awaiting_response or in_conversation
  meeting_scheduled  SET when: book_slot() returns a valid event_id and confirmation sent to lead
  lost               SET when: agent evaluates context as no-engagement (see Lead Classification Logic)
  opt_out            SET when: agent detects explicit opt-out AND graceful close message sent

- Never delete lead records — only update status.
- opt_out is terminal — no script may revert it.
- Before any new send: check phone number in DB. No duplicate campaigns.
- Store full conversation history as JSON in a conversation_history column.
- Use standard SQL only — must support migration from SQLite to PostgreSQL without rewrites.

---

## 9. Conversational Agent Rules (not yet built)

CENTRAL OPERATIONAL RULES — these override everything else:
  1. The agent NEVER invents information about Behind, its products, pricing, or services.
     If the lead asks something not covered in the system prompt, redirect to the meeting.
  2. The agent NEVER confirms a meeting without first calling check_calendar.py and
     receiving a valid event_id. Offering a slot is not confirmation. Booking is confirmation.
  3. The agent NEVER identifies itself as an AI. It represents the Behind team.

Additional rules:
- Always include the full conversation history in every API call.
- Any opt-out signal: send graceful close, set status = opt_out, stop all contact immediately.
- Reuse OpenAI client pattern from generate_titles.py.

Lead lost evaluation (contextual, not timer-based):
  MARK LOST if:
    - Lead explicitly refuses AND ignores or refuses again after one reversal attempt.
    - Friday end-of-send-window AND lead has shown zero interest signal across the entire week
      (no question, no curiosity, no meeting signal, no engagement beyond bare replies).
  This end-of-week check is the ONLY time-based rule. Everything else is context-evaluated.

  KEEP AS INTERESTED if ANY of these are true:
    - Lead asked any question (service, site, process, price).
    - Lead asked for more time ("me manda depois", "semana que vem").
    - Lead opened the meeting topic even briefly.

---

## 10. Self-Annealing Loop

1. Read full error message and stack trace.
2. Classify: credential / network / logic / data.
3. Credential/config errors: notify user immediately, do not auto-fix.
4. Logic/data errors: fix script, test, update corresponding directive.
5. External API errors: implement retry with exponential backoff.
6. After fix: document in script header AND in the directive.
7. Never mark a fix complete without confirming the original failure no longer occurs.

---

## 11. Required .env Variables

Stop and notify user if any are missing.

# Already in use
OPENAI_API_KEY          (generate_titles.py)
GOOGLE_API_KEY          (generate_cover.py - Gemini)

# Required for prospecting modules
WHATSAPP_API_KEY=
WHATSAPP_INSTANCE=
WHATSAPP_SEND_WINDOW_START=08:00
WHATSAPP_SEND_WINDOW_END=18:00
WARMUP_BLOCK_SIZE=25
WARMUP_BLOCK_GAP_MINUTES=90
WARMUP_MIN_DELAY_SECONDS=45
WARMUP_MAX_DELAY_SECONDS=90
SEQUENCE_MIN_DELAY_SECONDS=3
SEQUENCE_MAX_DELAY_SECONDS=5
SEQUENCE_IMAGE_MIN_DELAY_SECONDS=4
SEQUENCE_IMAGE_MAX_DELAY_SECONDS=6
FOLLOWUP_THROTTLE_HOURS=24
AGENT_MODEL=gpt-4o-mini
GOOGLE_CALENDAR_ID=
CALENDAR_MEETING_DAYS=monday,tuesday,wednesday,thursday,friday
CALENDAR_MEETING_DURATION_MINUTES=30
TEAM_NOTIFICATION_NUMBER=
DB_PATH=./sistema_capas.db

---

## 12. Pre-Delivery Checklist

- [ ] Script tested with real data or realistic mock?
- [ ] Corresponding directive created or updated?
- [ ] Logging: logger = logging.getLogger(__name__)?
- [ ] In-memory TTL cache for repeated calls?
- [ ] All external API calls in try/except with typed fallbacks?
- [ ] No hardcoded sensitive data?
- [ ] New endpoints follow FastAPI + Pydantic pattern from api.py?
- [ ] Action is reversible, or confirmed by user?

---

*Generated from: execution/api.py, generate_cover.py, generate_titles.py, scrape_instagram.py*
*Repository: canizzadev/sistema-capas*
