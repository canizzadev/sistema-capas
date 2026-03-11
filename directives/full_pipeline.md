# Full Pipeline — Prospecção End-to-End

## Visão Geral
Pipeline automático que executa todo o fluxo de prospecção médica:
Descoberta → Filtros → Títulos GPT → Cor da Marca → Capa → Telefone → Lead

## Fluxo de Fases

### Fase 1+2: Discovery + Filters (`discovery_pipeline.py`)
- Gera termos de busca (especialidade + cidade + template)
- Busca no Google via Firecrawl → extrai usernames do Instagram
- Scrape de cada perfil → filtro de followers → análise de bio (Claude) → análise de foto (Claude)
- Aprovados salvos em `discovered_doctors`, rejeitados em `rejected_profiles`

### Fase 3: Títulos GPT (`generate_titles.py`)
- Gera `formatted_name`, `specialty_line`, `headline` via GPT

### Fase 3b: Detecção de Cor (`detect_color.py`)
- Cascade: Claude Vision → Pillow (dominant color) → default `#27AE60`
- Garante contraste WCAG AA (≥ 4.5:1 com branco)
- Auto-escurece em passos de 15% se contraste insuficiente

### Fase 4: Geração de Capa (`generate_cover.py`)
- Download da foto de perfil → `generate_cover_zip(photo_bytes, brand_color, instagram_url)`
- Salva ZIP (PNG + PDF) em `.tmp/covers/{username}_capa.zip`

### Fase 5: Extração de Telefone (`extract_phone.py`)
- Cascade: regex na bio → scrape do link externo via Firecrawl
- 6 padrões regex priorizados: wa.me > WhatsApp API > +55 > parênteses > espaçado > dígitos
- Normaliza para E.164 sem +: `5511999999999`
- Prefere mobile (9 dígitos após DDD, começa com 9)

### Fase 6: Registro de Lead (`manage_leads.py`)
- **Com número** → `create_lead(status="cover_generated")` → entra no fluxo de WhatsApp
- **Sem número** → `create_lead(status="awaiting_number")` → aguarda inserção manual

## Endpoints da API

| Endpoint | Método | Descrição |
|---|---|---|
| `/pipeline/start` | POST | Inicia pipeline em background. Body: `{"target_count": 30}`. Retorna `{"task_id": "uuid"}` |
| `/pipeline/progress/{task_id}` | GET | Progresso em tempo real (phase, current, total, username, message, stats) |
| `/pipeline/results/{task_id}` | GET | Resultados finais quando status = completed |
| `/leads/awaiting-number` | GET | Lista leads com status `awaiting_number` |
| `/leads/{id}/set-number` | POST | Define número WhatsApp. Body: `{"whatsapp_number": "5511..."}`. Transiciona para `cover_generated` |

## Status `awaiting_number`
- Novo estado no início da máquina de estados do lead
- Transição válida: `awaiting_number` → `cover_generated` (via `/leads/{id}/set-number`)
- Leads nesse status aparecem na seção "Leads Aguardando Número" do frontend
- Placeholder no banco: `pending_{username}` (substituído ao inserir número real)

## Arquivos Envolvidos
- `execution/full_pipeline.py` — orquestrador principal
- `execution/discovery_pipeline.py` — fase 1+2
- `execution/detect_color.py` — fase 3b
- `execution/extract_phone.py` — fase 5
- `execution/generate_titles.py` — fase 3
- `execution/generate_cover.py` — fase 4
- `execution/manage_leads.py` — fase 6
- `execution/api.py` — endpoints REST

## Variáveis de Ambiente
```
DISCOVERY_DELAY_COVER=2      # delay entre geração de capas (segundos)
DISCOVERY_DELAY_PHONE=1      # delay após scrape de link externo
DEFAULT_BRAND_COLOR=#27AE60  # cor fallback se detecção falhar
MIN_FOLLOWERS=1000           # mínimo de seguidores
MIN_BIO_LENGTH=20            # mínimo de caracteres na bio
```

## Retorno do Pipeline
```json
{
  "leads_created": 5,
  "awaiting_number": 3,
  "covers_generated": 8,
  "rejected": 12,
  "skipped": 2,
  "errors": 1,
  "details": [
    {"username": "dra.maria", "status": "lead_created", "message": "...", "lead_id": 42}
  ]
}
```

## Edge Cases
- Foto de perfil indisponível → capa não gerada, lead ainda é criado
- Claude Vision falha → Pillow fallback → cor default
- Número já existe como lead → skip (não duplica)
- Placeholder já existe → skip
- Erro em qualquer fase individual → logado, pipeline continua com próximo médico
