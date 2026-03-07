# Planning --- Behind Prospecting Automation
Based on: canizzadev/sistema-capas + agente.md + antigravity.md

---

## What Already Exists

execution/api.py --- FastAPI server, 4 endpoints:
  GET /                serves static/index.html
  POST /extract        scrapes profiles + generates GPT titles
  POST /extract-batch  scrapes + exports Excel with progress tracking
  POST /generate-cover full pipeline: scrape + Gemini + Pillow + ZIP

execution/scrape_instagram.py  3-tier scraper, 5-min TTL cache
execution/generate_titles.py   GPT-4o-mini, 10-min TTL cache, outputs: formatted_name, specialty_line, headline
execution/generate_cover.py    Pillow + Gemini 2.5 Flash outpainting + ReportLab PDF + ZIP
static/index.html              Frontend served by FastAPI

Cover generation: 5-10 minutes reduced to 15-30 seconds.

---

## Decisions Locked

| Decision | Value |
|---|---|
| WhatsApp API | Z-API (credentials to be provided) |
| Agent model | gpt-4o-mini |
| Meeting availability | All business days, full business hours, from integrated calendar |
| Meeting days configured via | CALENDAR_MEETING_DAYS in .env |
| Out-of-hours requests | WhatsApp notification to TEAM_NOTIFICATION_NUMBER |
| Team notification number | To be provided |
| Frontend scope | Minimal additions to static/index.html (add 2 fields to existing form only) |
| Lead lost logic | Context-based AI evaluation + one temporal anchor (see section below) |
| Warm-up cadence | Any business day, Monday preferred start. Blocks of 25, 45-90s delay, 90-min gap between blocks. |
| Follow-up cadence | Tue-Fri. Max 1 follow-up per lead per day. Agent-evaluated per context. |
| Sequence messages | Stored in config/sequence_messages.json, loaded at runtime |

---

## Central Operational Rules

These rules are non-negotiable and override any other instruction in this document.
They must be enforced in the system prompt AND in code.

RULE 1 — NO INVENTION
  The agent never invents information about Behind: products, pricing, timelines, guarantees.
  If the lead asks something not covered in the system prompt: redirect to the meeting.
  Response: "Na reuniao a gente detalha tudo, vale muito a pena!"

RULE 2 — NO UNCONFIRMED MEETINGS
  The agent never confirms a meeting without calling check_calendar.py first.
  Offering a slot is not confirmation. The meeting is only confirmed after book_slot() returns event_id.
  Only then: send confirmation to lead + notify team.

RULE 3 — NO AI DISCLOSURE
  The agent never identifies itself as an AI.
  It represents the Behind team at all times.
  Response if asked: "Sou da equipe Behind, especializada em sites para medicos!"

---

## Anti-Block Strategy

WhatsApp blocks accounts that send unsolicited bulk messages to cold leads.
Risk compounds when: messages go to many numbers quickly, content is promotional,
and recipients have not interacted with the number before.

Two-stage approach:

STAGE 1 --- Warm-Up (any business day, Monday preferred start)
  Send a single short neutral message from config/warmup_messages.json.
  No promotional content, no links, no media.
  Sent in blocks of 25 contacts spread across the business day.
  45-90s random delay between sends within a block.
  Minimum 90-minute gap between blocks.
  After sending: wait. Do nothing until lead replies.

STAGE 2 --- Full Prospecting (triggered by lead response, any day)
  Lead responded = they are real, reachable, willing to engage.
  Agent reads the response and classifies contact type (see Contact Classification).
  Agent sends one personalized reply to what the lead said.
  Then immediately dispatches the 5-part sequence variant matching the contact type.
  This reduces operational risk by keeping the interaction in a conversational pattern
  rather than a broadcast pattern from WhatsApp's perspective.

FOLLOW-UP WINDOW (Tuesday to Friday)
  Only leads who responded to the warm-up receive follow-ups.
  Maximum 1 follow-up per lead per day.
  Agent evaluates conversation context to decide message content.

---

## Warm-Up Message Pool

Stored in config/warmup_messages.json. Editable without code changes.

Pool (current):
  "Bom dia"
  "Bom dia."
  "Bom dia. Tudo bem?"
  "Bom dia. Com quem estou falando?"
  "Bom dia tudo bem?"
  "Bom dia!"
  "Bom dia com quem falo?"
  "Bom dia. Com quem falo?"

Rule: selected randomly per lead at dispatch time.
The same message is never sent to the same number twice (stored in DB as warm_up_message).

---

## Contact Classification --- Core of the Personalization Engine

When the lead responds to the warm-up, the agent classifies contact type
before sending the sequence. Classification drives which of the 4 variants is used.

Classification matrix:
  A: Secretary of female doctor  (secretaria da Dra.)
  B: Female doctor directly      (Dra. diretamente)
  C: Secretary of male doctor    (secretaria do Dr.)
  D: Male doctor directly        (Dr. diretamente)

Detection process (3 steps, always in this order):
  STEP 1 — Infer from warm-up reply:
    Third-person reference ("a Dra. / o Dr.")  => secretary
    First-person ("sou a Dra. / sou o Dr.")    => doctor directly
    Gender: inferred from formatted_name stored in lead record

  STEP 2 — If ambiguous after step 1:
    Agent asks: "Estou falando com a Dra. [name] ou com a secretaria?"
    Wait for confirmation before proceeding.

  STEP 3 — Save result:
    Store final classification in contact_classification column in DB.
    Never re-classify a lead that already has contact_classification set.

---

## The 5-Part Sequence --- 4 Variants

Stored in config/sequence_messages.json. Editable without code changes.
Each variant = 5 separate WhatsApp messages.
Delays: 3-5s random between text messages. 4-6s before image (message 3).
Message [3] is always capa.png unpacked from the ZIP. Never send the ZIP file.
Behance link is always: https://www.behance.net/behindltda

IMPORTANT: Before message [1], the agent always sends one personalized reply
to whatever the lead said in the warm-up response. Only then does the sequence start.

NOTE: Variants B and D use identical copy except for "medica/medico" in message [1].
This is intentional. When speaking directly to the doctor, the relationship is the same
regardless of gender. Only the specialty noun changes.

--- VARIANT A: Secretaria da Dra. [name] ---

[1] Acompanhei o trabalho da Dra. [name] no Instagram e, por ver que ela e uma medica
    muito competente, pedi para a equipe preparar com carinho um site profissional que
    pode fortalecer ainda mais sua presenca digital e atrair muito mais pacientes.
[2] Vou compartilhar a secao inicial aqui embaixo para a Dra. dar uma olhada!
[3] capa.png
[4] Gostaria bastante de marcar uma reuniao para apresentar o site por completo!
    A Dra. teria algum horario disponivel na agenda?
[5] Ah, tambem vou deixar o portfolio da Behind a Dra. conhecer melhor os projetos.
    https://www.behance.net/behindltda

--- VARIANT B / D: [Dra./Dr.] [name] diretamente ---

[1] Acompanhei seu trabalho no Instagram e, por ver que voce e uma [medica/medico]
    muito competente, pedi para a equipe preparar com carinho um site profissional que
    pode fortalecer ainda mais sua presenca digital e atrair muito mais pacientes.
[2] Vou compartilhar a secao inicial aqui embaixo para voce dar uma olhada!
[3] capa.png
[4] Gostaria bastante de marcar uma reuniao para apresentar o site por completo!
    Voce teria algum horario disponivel na agenda?
[5] Ah, tambem vou deixar o portfolio da Behind para voce conhecer melhor os projetos.
    https://www.behance.net/behindltda

--- VARIANT C: Secretaria do Dr. [name] ---

[1] Acompanhei o trabalho do Dr. [name] no Instagram e, por ver que ele e um medico
    muito competente, pedi para a equipe preparar com carinho um site profissional que
    pode fortalecer ainda mais sua presenca digital e atrair muito mais pacientes.
[2] Vou compartilhar a secao inicial aqui embaixo para o Dr. dar uma olhada!
[3] capa.png
[4] Gostaria bastante de marcar uma reuniao para apresentar o site por completo!
    O Dr. teria algum horario disponivel na agenda?
[5] Ah, tambem vou deixar o portfolio da Behind para o Dr. conhecer melhor os projetos.
    https://www.behance.net/behindltda

NOTE: Messages stored without accents in config/sequence_messages.json for safe JSON handling.
The execution script must encode them in UTF-8 when dispatching via Z-API.
The actual WhatsApp messages must use proper Portuguese with full accent marks.

---

## Lead Classification Logic

Primary rule: context-based AI evaluation.
Single temporal anchor: end-of-week check.

MARK AS LOST if ANY of these conditions are met — evaluated as one unified rule:
  - Lead explicitly refuses AND ignores or refuses again after one graceful reversal attempt.
  - Friday end-of-send-window: lead has shown zero interest signal across the entire week
    (no question, no curiosity, no meeting signal, only bare one-word replies or silence).
  - status = warm_up_sent AND no reply received by Friday end-of-send-window.

  All three conditions share the same evaluation moment (Friday cleanup) and the same outcome.
  The Friday check is the only time-based anchor. Everything else is context-evaluated.

KEEP AS INTERESTED (never mark lost) if ANY of these are true:
  - Lead asked any question about the service, site, process, or price.
  - Lead asked for more time ("me manda na semana que vem", "me fala depois").
  - Lead opened the meeting topic even briefly.
  - Any signal exists that they might schedule.

MARK AS OPT-OUT (terminal) if:
  - Lead uses explicit opt-out language AND ignores or refuses after graceful close attempt.
  - opt_out is terminal. No script may ever reverse it.

GRACEFUL CLOSE:
  Before marking lost or opt_out, agent always sends:
  "Tudo bem! Fico a disposicao caso queira conversar no futuro. Ate mais!"
  Then stops all contact immediately.

---

## Calendar Integration Rules

Available slots: full business hours from Google Calendar.
Meeting days: defined by CALENDAR_MEETING_DAYS in .env (default: all business days).
Duration: CALENDAR_MEETING_DURATION_MINUTES (default 30 min).

Out-of-hours requests:
  If lead proposes a time outside business hours or on a weekend:
    Agent says: "Nossas reunioes acontecem em horario comercial. Posso verificar
                 o que temos disponivel e ja te passo as opcoes!"
    Then: send WhatsApp notification to TEAM_NOTIFICATION_NUMBER with lead name,
          number, and the out-of-hours request via send_whatsapp.py.
    Then: offer standard available slots as fallback.

The agent NEVER confirms a meeting without calling check_calendar.py first (see Central Rules).

---

## Team Notification Events

All events below trigger a WhatsApp message to TEAM_NOTIFICATION_NUMBER via send_whatsapp.py.
Format for all: "[EVENT] Lead: {name} | Number: {whatsapp_number} | Detail: {detail}"

| Event | Detail |
|---|---|
| meeting_scheduled | Date, time, and lead name |
| out_of_hours_request | Requested time + lead number |
| send_error | Which send failed and lead ID |
| opt_out | Lead name and final message sent |
| lost (Friday cleanup) | Lead name and last interaction date |

---

## Conversational Agent --- System Prompt Architecture

Model: gpt-4o-mini (AGENT_MODEL in .env)
Full conversation history in every API call.
Two operating modes:
  classification_mode  detects contact type from warm-up response
  conversation_mode    objection handling + meeting scheduling + follow-ups

System prompt assembled dynamically per request:

  IDENTITY BLOCK
    You are a member of the Behind team, a digital agency specializing in
    professional websites for doctors. Cordial, professional, brief.
    Never identify as AI. Never invent product info. (See Central Operational Rules)

  CONTACT CONTEXT BLOCK (injected per lead)
    Doctor name: {formatted_name}
    Specialty: {specialty_line}
    Contact type: {contact_classification}
    Lead status: {status}
    Conversation so far: {conversation_history}

  BEHAVIORAL RULES BLOCK
    - Short messages. One idea per message. Never a wall of text.
    - Never confirm a meeting without checking the calendar.
    - Price question -> redirect to meeting.
    - Already has a site -> ask about results.
    - No time -> offer 20-min flexible call.
    - 3 messages no reply post-sequence -> evaluate context -> apply Lead Classification Logic.
    - Any opt-out signal -> graceful close -> stop forever.
    - Max 1 follow-up per lead per day.

  OBJECTION PLAYBOOK BLOCK
    Ja tenho site   -> "Que otimo! Como ele tem performado para atrair pacientes?
                        Nosso foco e justamente esse resultado..."
    Sem tempo       -> "Entendo! Sao so 20 minutinhos, posso me adaptar ao seu horario."
    Quanto custa?   -> "Na reuniao apresento tudo com os detalhes! Vale muito a pena ver."
    Nao interessa   -> One reversal attempt, then graceful close.
    Quem e voce?    -> "Sou da equipe Behind, uma agencia especializada em sites para medicos."

  MEETING SCHEDULING BLOCK
    1. Detect intent signal
    2. get_available_slots() -> 2-3 real options from check_calendar.py
    3. Offer specific options ("que tal quinta as 14h ou sexta as 10h?")
    4. Lead confirms
    5. book_slot() -> event_id
    6. Send confirmation message to lead
    7. Notify team via WhatsApp to TEAM_NOTIFICATION_NUMBER
    8. Status = meeting_scheduled

  TRAINING NOTES
    - Feel like a real person, not a robot.
    - WhatsApp register: short, natural, no bullet points, no formal headers.
    - Emoji: minimal and natural only.
    - Never start two consecutive messages the same way.
    - Match the formality level of the lead.

---

# MODULE SPECS

## Module 1.1 --- Frontend: Prospecting Fields
  Add 2 fields to existing form in static/index.html:
    WhatsApp number (required)
    Doctor name override (optional — used when scraping returns a clinic name)
  Frontend calls /generate-cover then POST /prospect sequentially.
  No new pages, no redesign. Minimal additions only.

## Module 1.2 --- POST /prospect
  Receives: instagram_url, whatsapp_number, cover_path.
  Creates lead in DB: status = cover_generated.
  Returns: {status: queued, lead_id}.

## Module 1.3 --- execution/manage_leads.py
  SQLite manager. Standard SQL, PostgreSQL-ready.
  Schema includes: warm_up_sent_at, warm_up_message, last_lead_reply_at,
                   contact_classification, send_error_at.
  Directive: directives/manage_leads.md

## Module 1.4 --- execution/send_whatsapp.py
  send_warm_up(number, lead_id) -> bool
  send_sequence(lead_id) -> dict   includes personalized reply before sequence
  send_followup(lead_id, message) -> bool
  send_notification(number, message) -> bool   used for all team alerts
  All modes: check window + check opt_out + retry once after 30s + log to .tmp/whatsapp_logs/.
  On second failure: set send_error, call send_notification to team.
  Directive: directives/prospecting_whatsapp.md

## Module 1.5 --- POST /webhook/whatsapp
  Z-API webhook receiver.
  Branch A (warm_up_sent): classify -> personalized reply -> sequence
  Branch B (message_sent+): conversation mode agent -> reply -> status eval
  Directive: directives/webhook.md

## Module 1.6 --- execution/conversational_agent.py
  classification_mode + conversation_mode.
  gpt-4o-mini. Reuses generate_titles.py client pattern.
  Enforces Central Operational Rules 1, 2, and 3 in system prompt.
  Directive: directives/conversational_agent.md

## Module 1.7 --- execution/check_calendar.py
  get_available_slots() -> list of {date, time, display}
  book_slot(date, time, lead_name, lead_number) -> event_id or None
  No cancel_slot() in V1.
  Filters by CALENDAR_MEETING_DAYS and business hours. No double-booking.
  Out-of-hours: triggers send_notification via send_whatsapp.py.
  OAuth2 via credentials.json + token.json.
  Directive: directives/scheduling.md

## Module 2.1 --- Lead Dashboard
  GET /leads endpoint + status badges in frontend.

## Module 2.2 --- execution/queue_dispatcher.py
  Warm-up dispatch: blocks of 25, 45-90s delay within block, 90-min gap between blocks.
  Follow-up dispatch: Tue-Fri, agent-evaluated per lead, max 1 per lead per day.
  End-of-week cleanup (Friday, end of send window): agent evaluates and marks lost where appropriate.

## Module 2.3 --- Conversation Viewer
  Per-lead panel: history, take over, re-enable AI, manual overrides.

---

# FULL PIPELINE

ANY BUSINESS DAY --- Warm-Up Dispatch
  queue_dispatcher.py: blocks of 25 warm-ups across business day
  45-90s delay within block, 90-min gap between blocks
  Status: cover_generated -> warm_up_sent
  (Monday is preferred start day. Warm-up is not locked to Monday only.)

SAME DAY (as responses arrive)
  POST /webhook/whatsapp fires
  Branch A: status = warm_up_sent
    Agent runs classification_mode
    Saves contact_classification to DB
    Sends personalized reply to warm-up response
    Dispatches 5-part sequence (variant per classification)
    Status: warm_up_responded -> message_sent -> awaiting_response

TUESDAY TO FRIDAY --- Follow-Up Loop
  queue_dispatcher.py: one follow-up per eligible lead per day
  Agent generates contextual message per lead
  Agent evaluates: meeting intent? refusal? silence?
  Status transitions as appropriate

FRIDAY --- End-of-Week Cleanup
  queue_dispatcher.py: agent evaluates all non-terminal leads
  Zero-interest leads -> status = lost -> team notified

ANY DAY --- Incoming Reply
  POST /webhook/whatsapp fires
  Branch B: status = message_sent or awaiting_response or in_conversation
    Full history loaded from DB
    Agent runs conversation_mode
    Status = in_conversation

AI CONVERSATION OUTCOMES
  Meeting interest detected:
    check_calendar.py: get_available_slots()
    Agent offers 2-3 specific options
    Lead confirms -> book_slot() -> event_id
    Confirmation sent to lead
    Team notified via send_notification()
    Status = meeting_scheduled  [terminal]

  Opt-out detected:
    Graceful close sent
    Status = opt_out  [terminal]

  Explicit refusal + failed reversal:
    Graceful close sent
    Status = lost  [terminal]

---

## Status Flow

cover_generated -> warm_up_sent -> warm_up_responded -> message_sent
  -> awaiting_response -> in_conversation
    -> meeting_scheduled  [terminal]
    -> lost               [terminal]
    -> opt_out            [terminal]

send_error: side state. Set on double send failure. Does not replace flow status.

All lost/opt_out conditions are fully described in Lead Classification Logic above.
opt_out is always terminal. Never delete records. Never revert opt_out.

---

## Final Copy Reference — Humanized Portuguese

This section contains the exact text that must appear in WhatsApp messages.
config/sequence_messages.json stores these without accents for safe JSON handling.
The execution script resolves accents at runtime via UTF-8 encoding.
This section is the canonical source of truth for copy review and future edits.

--- GRACEFUL CLOSE (all cases: lost + opt_out) ---

"Tudo bem! Fico à disposição caso queira conversar no futuro. Até mais!"

--- VARIANT A: Secretária da Dra. [nome] ---

[1] Acompanhei o trabalho da Dra. [nome] no Instagram e, por ver que ela é uma médica
    muito competente, pedi para a equipe preparar com carinho um site profissional que
    pode fortalecer ainda mais sua presença digital e atrair muito mais pacientes.
[2] Vou compartilhar a seção inicial aqui embaixo para a Dra. dar uma olhada!
[3] capa.png
[4] Gostaria bastante de marcar uma reunião para apresentar o site por completo!
    A Dra. teria algum horário disponível na agenda?
[5] Ah, também vou deixar o portfólio da Behind a Dra. conhecer melhor os projetos.
    https://www.behance.net/behindltda

--- VARIANT B: Dra. [nome] diretamente ---

[1] Acompanhei seu trabalho no Instagram e, por ver que você é uma médica
    muito competente, pedi para a equipe preparar com carinho um site profissional que
    pode fortalecer ainda mais sua presença digital e atrair muito mais pacientes.
[2] Vou compartilhar a seção inicial aqui embaixo para você dar uma olhada!
[3] capa.png
[4] Gostaria bastante de marcar uma reunião para apresentar o site por completo!
    Você teria algum horário disponível na agenda?
[5] Ah, também vou deixar o portfólio da Behind para você conhecer melhor os projetos.
    https://www.behance.net/behindltda

--- VARIANT C: Secretária do Dr. [nome] ---

[1] Acompanhei o trabalho do Dr. [nome] no Instagram e, por ver que ele é um médico
    muito competente, pedi para a equipe preparar com carinho um site profissional que
    pode fortalecer ainda mais sua presença digital e atrair muito mais pacientes.
[2] Vou compartilhar a seção inicial aqui embaixo para o Dr. dar uma olhada!
[3] capa.png
[4] Gostaria bastante de marcar uma reunião para apresentar o site por completo!
    O Dr. teria algum horário disponível na agenda?
[5] Ah, também vou deixar o portfólio da Behind para o Dr. conhecer melhor os projetos.
    https://www.behance.net/behindltda

--- VARIANT D: Dr. [nome] diretamente ---

[1] Acompanhei seu trabalho no Instagram e, por ver que você é um médico
    muito competente, pedi para a equipe preparar com carinho um site profissional que
    pode fortalecer ainda mais sua presença digital e atrair muito mais pacientes.
[2] Vou compartilhar a seção inicial aqui embaixo para você dar uma olhada!
[3] capa.png
[4] Gostaria bastante de marcar uma reunião para apresentar o site por completo!
    Você teria algum horário disponível na agenda?
[5] Ah, também vou deixar o portfólio da Behind para você conhecer melhor os projetos.
    https://www.behance.net/behindltda

--- OBJECTION RESPONSES ---

Já tenho site:   "Que ótimo! Como ele tem performado para atrair pacientes?
                  Nosso foco é justamente esse resultado..."
Sem tempo:       "Entendo! São só 20 minutinhos, posso me adaptar ao seu horário."
Quanto custa?:   "Na reunião apresento tudo com os detalhes! Vale muito a pena ver."
Quem é você?:    "Sou da equipe Behind, uma agência especializada em sites para médicos!"
Não inventar:    "Na reunião a gente detalha tudo, vale muito a pena!"

---



OPENAI_API_KEY=
GOOGLE_API_KEY=
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
AGENT_MODEL=gpt-4o-mini
GOOGLE_CALENDAR_ID=
CALENDAR_MEETING_DAYS=monday,tuesday,wednesday,thursday,friday
CALENDAR_MEETING_DURATION_MINUTES=30
TEAM_NOTIFICATION_NUMBER=
DB_PATH=./sistema_capas.db

---

## Implementation Order

Priority 1:   manage_leads.py                  Foundation — all state lives here
Priority 2:   config/warmup_messages.json      Needed before any warm-up send
Priority 3:   config/sequence_messages.json    Needed before any sequence send
Priority 4:   send_whatsapp.py (all modes)     Enables all outbound contact
Priority 5:   POST /prospect + frontend fields Connects cover gen to prospecting
Priority 6:   POST /webhook/whatsapp           Receives inbound messages (structure only — fully functional after P7)
Priority 7:   conversational_agent.py          AI brain: classify + converse (activates webhook fully)
Priority 8:   check_calendar.py               Closes the meeting scheduling loop
Priority 9:   queue_dispatcher.py             Automates warm-up + follow-up cadence
Priority 10:  Lead dashboard                  Visibility as volume grows
Priority 11:  Conversation viewer             Human override capability

---

## Still Needed Before Going Live

- Z-API credentials (WHATSAPP_API_KEY + WHATSAPP_INSTANCE)
- Team notification WhatsApp number (TEAM_NOTIFICATION_NUMBER)
- Google Calendar ID (GOOGLE_CALENDAR_ID)

---

Repository: canizzadev/sistema-capas
All decisions incorporated. Ready for implementation.
