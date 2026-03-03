# Directive: Instagram Profile Extractor + GPT Title Generator

## Goal
Build a FastAPI backend that:
1. Receives a list of public Instagram profile URLs
2. Scrapes each profile's name, bio, and external link
3. Sends that data to OpenAI GPT to generate a title and subtitle for each person
4. Returns all results as JSON

## Inputs
- A JSON body with a list of Instagram profile URLs
- Example: { "urls": ["https://instagram.com/username1", "https://instagram.com/username2"] }

## Tools / Scripts to Use
- `execution/scrape_instagram.py` — handles scraping each profile
- `execution/generate_titles.py` — handles GPT API call
- `execution/api.py` — FastAPI app that ties everything together

## Outputs
A JSON response like:
```json
[
  {
    "username": "username1",
    "name": "Full Name",
    "bio": "Bio text here",
    "external_link": "https://theirwebsite.com",
    "formatted_name": "Dr. Full Name",
    "specialty_line": "Especialidade – Palavra Palavra – Conselho: 12345 RQE: 6789",
    "headline": "A headline in Portuguese, exactly 12 to 14 words, highly personalized."
  }
]
```

## Scraping Approach
Use the `requests` library and `beautifulsoup4` to attempt multiple strategies, as Instagram aggressively blocks automated requests:
1. Attempt the JSON endpoint with mobile headers `https://i.instagram.com/api/v1/users/web_profile_info/?username={username}`
2. Attempt the standard desktop web JSON endpoint `https://www.instagram.com/{username}/?__a=1&__d=dis`
3. Fallback to requesting `https://www.instagram.com/{username}/` as HTML and parsing `<meta property="og:...">` tags using BeautifulSoup.

Parse the JSON response or meta tags for: full_name, biography, external_url.

## GPT Integration
Use the OpenAI Python SDK (openai>=1.0.0).
Model: gpt-4o-mini (cheap and fast).

Before calling GPT, pre-process the bio in Python: 
- Remove all emojis using regex (`re.sub`).
- Extract registrations using regex for Brazilian health councils: CRM (médicos), CRO (dentistas), CRP (psicólogos), CRN (nutricionistas), CRF (farmacêuticos), COREN (enfermeiros), CREFITO (fisioterapeutas), CREFONO (fonoaudiólogos), CRBM (biomédicos), CRBio (biólogos), CRMV (médicos veterinários), CREF (educadores físicos), CRTR (técnicos em radiologia), CRESS (assistentes sociais). Capture both type and digits. Extract RQE if present.

Prompt the model with the person's name, cleaned bio, and registration info to generate:
- Infer gender from the name and add Dr. or Dra. before the full name.
- Identify the healthcare specialty from the bio. If unclear, use 'Profissional Especialista em [área]'.
- Create 2 personalized words related to the specialty (first letter of each capitalized, must be specific and creative, not generic).
- Format line 2 as: [Especialidade] – [2 palavras] – [Conselho]: [número] RQE: [número] (or dash if none).
- Write a headline in Portuguese, 12 to 14 words, ending with period or exclamation, highly personalized using specific bio details, never generic.

## Environment Variables
- OPENAI_API_KEY — loaded from .env using python-dotenv

## Edge Cases
- If a profile is private or doesn't exist, return an error message for that entry and continue
- If bio is empty, still generate a title based only on the name
- Handle rate limiting with a 2-second delay between requests