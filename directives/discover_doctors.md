# Directive: Automatic Doctor Discovery Pipeline

## Goal
Automatically discover new medical professionals on Instagram without manual URL input.
The system generates search terms, searches Google via Firecrawl, scrapes profiles,
analyzes them with Claude AI (bio + photo), and saves approved doctors for promotion
into the existing prospecting pipeline.

## Inputs
- `target_count` (int): Number of Instagram usernames to evaluate (default: 50)
- Configuration via `.env`:
  - `FIRECRAWL_API_KEY` — API key for Firecrawl search
  - `ANTHROPIC_API_KEY` — API key for Claude Vision analysis
  - `MIN_FOLLOWERS` — Minimum follower count (default: 1000)
  - `MIN_BIO_LENGTH` — Minimum bio character length (default: 20)
  - `DISCOVERY_DELAY_SEARCH` — Seconds between search requests (default: 3)
  - `DISCOVERY_DELAY_SCRAPE` — Seconds between scrape requests (default: 2)
  - `DISCOVERY_DELAY_ANALYSIS` — Seconds between AI analysis requests (default: 1)

## Pipeline Flow

```
1. Generate Search Terms
   └─ Random combination: specialty × city × prefix template
   └─ 30 specialties, 30 cities, 9 templates
   └─ Checks discovery_search_log to skip already-searched terms

2. Firecrawl Search (Google)
   └─ POST https://api.firecrawl.dev/v1/search
   └─ Extracts Instagram usernames from URLs + content via regex
   └─ Filters out /reel/, /explore/, /p/, /tv/, etc.

3. Deduplication
   └─ is_already_processed() checks 3 tables:
      - discovered_doctors (approved)
      - rejected_profiles (rejected)
      - leads (already in pipeline)

4. Instagram Scrape
   └─ Uses existing scrape_profile() with new fields:
      - followers (int or None)
      - profile_pic_url (str)

5. Filter 1: Minimum Followers
   └─ Reject if followers < MIN_FOLLOWERS
   └─ Skip filter if followers is None (data unavailable)

6. Filter 2: Bio Analysis (Claude AI)
   └─ Reject if bio length < MIN_BIO_LENGTH
   └─ analyze_bio() evaluates: eh_medico, bio_profissional, tem_especialidade
   └─ Extracts especialidade_detectada

7. Filter 3: Photo Analysis (Claude Vision)
   └─ analyze_photo() evaluates: fundo_liso, foto_profissional, alta_qualidade
   └─ Approved if 2/3 criteria pass
   └─ Skipped if no profile_pic_url available

8. Save Result
   └─ Approved → discovered_doctors table
   └─ Rejected → rejected_profiles table (with reason)
```

## Database Tables

### discovered_doctors
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| username | TEXT UNIQUE | Instagram username |
| name | TEXT | Display name |
| bio | TEXT | Profile bio |
| external_link | TEXT | External URL from profile |
| followers | INTEGER | Follower count |
| profile_pic_url | TEXT | HD profile picture URL |
| especialidade_detectada | TEXT | AI-detected medical specialty |
| cidade_busca | TEXT | City from search term |
| photo_analysis | TEXT (JSON) | Full Claude Vision analysis |
| bio_analysis | TEXT (JSON) | Full Claude bio analysis |
| created_at | TEXT | ISO 8601 timestamp |

### rejected_profiles
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| username | TEXT | Instagram username |
| rejection_reason | TEXT | Why the profile was rejected |
| created_at | TEXT | ISO 8601 timestamp |

### discovery_search_log
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| search_term | TEXT | The search query used |
| results_found | INTEGER | Number of usernames extracted |
| created_at | TEXT | ISO 8601 timestamp |

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/discover` | Start discovery pipeline. Body: `{"target_count": 50}` |
| GET | `/discovered` | List all approved discovered doctors |
| GET | `/discovery-stats` | Aggregate stats (approved, rejected, searches) |
| POST | `/discovered/{id}/promote` | Move doctor to leads table with status `cover_generated` |

## Outputs

### POST /discover response
```json
{
  "approved": 5,
  "rejected": 12,
  "skipped": 3,
  "errors": 2,
  "total_searched": 8,
  "details": [
    {"username": "dra.silva", "status": "approved", "reason": "Aprovado — Dermatologia"},
    {"username": "joao123", "status": "rejected", "reason": "Bio reprovada: não é médico"}
  ]
}
```

### POST /discovered/{id}/promote response
```json
{
  "status": "promoted",
  "lead_id": 42,
  "username": "dra.silva"
}
```

## Tools / Scripts

| File | Responsibility |
|------|---------------|
| `execution/discover_doctors.py` | Search term generation + Firecrawl API + username extraction |
| `execution/scrape_instagram.py` | Instagram scraping (adapted with followers + profile_pic_url) |
| `execution/analyze_profile.py` | Claude AI bio analysis + Claude Vision photo analysis |
| `execution/manage_discovery.py` | Database CRUD for discovery tables |
| `execution/discovery_pipeline.py` | Pipeline orchestrator |
| `execution/api.py` | HTTP endpoints (4 new routes) |
| `static/index.html` | Frontend discovery tab |
| `static/app.js` | Frontend JS (startDiscovery, loadDiscovered, promoteDoctor) |
| `static/style.css` | Discovery table, log, and stats styles |

## Edge Cases

1. **Firecrawl API key missing**: Returns empty results, logs error
2. **Anthropic API key missing**: Raises RuntimeError, pipeline logs error and continues
3. **Instagram rate-limited**: scrape_profile returns error, profile saved as rejected
4. **Duplicate username**: `save_approved()` catches IntegrityError, counts as skipped
5. **No followers data**: Filter 1 (min followers) is skipped — profile proceeds to bio analysis
6. **No profile pic URL**: Filter 3 (photo analysis) is skipped — profile can still be approved
7. **Empty bio**: Immediately rejected without calling Claude API
8. **Search term already used**: `was_searched()` returns True, term skipped
9. **Claude returns non-JSON**: Caught by try/except, profile marked as rejected with error reason
10. **Promoted doctor duplicate**: `create_lead()` catches IntegrityError (unique whatsapp_number), returns 409

## Separation of Concerns

- `discovered_doctors` and `leads` are **separate tables** — a doctor only enters `leads` after explicit "Promote" action
- Discovery flow does NOT trigger WhatsApp messages or cover generation
- After promotion, the doctor enters the existing pipeline at status `cover_generated`
- The `whatsapp_number` is set as `pending_{username}` placeholder — must be filled manually before WhatsApp flow begins
