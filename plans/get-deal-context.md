# Tool: `get_deal_context`

Full deal briefing for the NDados commercial team. Combines Pipedrive CRM data
(deal, contact, organization, notes, activities) with transcribed meeting recordings
from Google Drive via AssemblyAI. Returns a single markdown document ready for use
as pre-meeting context or sales intelligence input.

---

## Signature

```python
@mcp.tool()
async def get_deal_context(
    deal_id: int | None = None,
    deal_name: str | None = None
) -> str:
    """
    Returns a full markdown briefing for a Pipedrive deal.
    Includes deal metadata, contact, organization, notes, activities,
    and transcribed meeting recordings from Google Drive (via AssemblyAI).

    Provide either deal_id (preferred) or deal_name (triggers a search).
    """
```

---

## Internal Execution Flow

```
Step 1 — Resolve deal
  if deal_name provided:
    GET /deals/search?term={deal_name}&limit=5
    → pick first result → extract deal_id
  GET /deals/{deal_id}
  → extract: title, value, currency, probability, status,
             stage_id, pipeline_id, expected_close_date,
             owner_id.name, person_id, org_id,
             DRIVE_FIELD, CANAL_FIELD, PORTFOLIO_FIELD,
             SETOR_FIELD, FUNCIONARIOS_FIELD, LOST_REASON_FIELD, LABEL_FIELD

Step 2 — Parallel fetch (asyncio.gather)
  ├── GET /persons/{person_id}
  │     → name, job_title, email[0].value, phone[0].value
  ├── GET /organizations/{org_id}
  │     → name
  ├── GET /stages/{stage_id}
  │     → name
  └── GET /notes?deal_id={deal_id}&limit=50&sort=add_time+DESC
        → [{content, add_time, user.name}, ...]

Step 3 — Fetch activities
  GET /deals/{deal_id}/activities
  → [{type, subject, due_date, done, note}, ...]

Step 4 — Transcribe meetings (if drive_link exists)
  drive_link = deal.get(DRIVE_FIELD)
  if drive_link and drive_link.lower() != "n/a":
    context = {
      "org_name":        org["name"],
      "person_name":     person["name"],
      "person_position": person.get("job_title", "[INDEFINIDO]"),
      "org_setor":       resolve_enum(SETOR_OPTIONS, deal.get(SETOR_FIELD))
    }
    result = process_media_at_drive({"drive_link": drive_link, **context})
    transcriptions = result["drive_transcriptions"]

Step 5 — Compose and return markdown
```

---

## Field Resolution

All enum/set fields must be resolved before rendering. Import from `fields.py`:

```python
from fields import (
    DRIVE_FIELD, CANAL_FIELD, PORTFOLIO_FIELD, SETOR_FIELD,
    FUNCIONARIOS_FIELD, LOST_REASON_FIELD, LABEL_FIELD,
    CANAL_OPTIONS, SETOR_OPTIONS, FUNCIONARIOS_OPTIONS,
    PORTFOLIO_OPTIONS, LOST_REASON_OPTIONS, LABEL_OPTIONS,
    resolve_enum, resolve_set
)

# Usage examples
canal      = resolve_enum(CANAL_OPTIONS,      deal.get(CANAL_FIELD))
setor      = resolve_enum(SETOR_OPTIONS,      deal.get(SETOR_FIELD))
headcount  = resolve_enum(FUNCIONARIOS_OPTIONS, deal.get(FUNCIONARIOS_FIELD))
portfolio  = resolve_set(PORTFOLIO_OPTIONS,   deal.get(PORTFOLIO_FIELD))   # → list[str]
labels     = resolve_set(LABEL_OPTIONS,       deal.get(LABEL_FIELD))       # → list[str]
lost_reason = resolve_enum(LOST_REASON_OPTIONS, deal.get(LOST_REASON_FIELD))
# lost_reason only rendered when deal["status"] == "lost"
```

---

## AssemblyAI Context Enrichment

`process_audio` in `pipeline/pipeline.py` accepts a `context` dict that builds
a domain-specific transcription prompt and word_boost list.

Pass it from Pipedrive data:
```python
context = {
    "org_name":        org["name"],
    "person_name":     person["name"],
    "person_position": person.get("job_title", "[INDEFINIDO]"),
    "org_setor":       resolve_enum(SETOR_OPTIONS, deal.get(SETOR_FIELD))
}
```

**Bonus — inject Portfólio into word_boost:**
`pipeline.py` has a static `word_boost` list. Consider extending it with the
resolved Portfólio labels for this specific deal before calling `process_audio`,
so AssemblyAI recognizes domain-specific service names (e.g. "DSaaS", "IA de Voz").
This requires a small modification to `process_audio` to accept an optional
`extra_word_boost: list[str]` parameter.

---

## Output Format

```markdown
# {deal_title} — Contexto Completo

**Etapa:** {stage_name} | **Funil:** {pipeline_name}
**Valor:** R$ {value} | **Probabilidade:** {probability}%
**Responsável:** {owner_name} | **Fechamento Previsto:** {expected_close_date}
**Etiqueta:** {labels joined by ", "} | **Canal:** {canal}
**Portfólio:** {portfolio joined by " · "}

---

## Contato

**Nome:** {person_name} — {job_title}
**Email:** {email} | **Tel:** {phone}

## Empresa

**Organização:** {org_name}
**Setor:** {setor} | **Funcionários:** {headcount}

---

## Transcrições de Reuniões

### {filename_1}
{transcript_text with speaker labels}

### {filename_2}
...

*(Sem gravações vinculadas.)* ← if drive_link is empty

---

## Notas

### [{add_time}] {user_name}
{content}

### [{add_time}] {user_name}
...

*(Sem notas registradas.)* ← if empty

---

## Atividades

| Data | Tipo | Assunto | Status |
|------|------|---------|--------|
| {due_date} | {type} | {subject} | ✅ Feita / 🔲 Pendente |
...

*(Sem atividades registradas.)* ← if empty

---
*— Motivo da Perda: {lost_reason}* ← only when status == "lost"
```

---

## Error Handling

| Failure point | Behavior |
|---|---|
| `deal_name` search returns 0 results | Raise `ValueError("Deal não encontrado: {deal_name}")` |
| `deal_name` search returns multiple | Use first result, include note in output: `*Múltiplos deals encontrados — exibindo: {title}*` |
| `person_id` or `org_id` is None | Skip that section, render `*Contato não vinculado.*` |
| Drive link present but inaccessible | Render `*Erro ao acessar Drive: {error}*` in transcriptions section |
| Individual file transcription fails | `node_process_media_at_drive.py` already isolates per-file errors — render as-is |
| AssemblyAI timeout / error | Already handled in `pipeline.py` — RuntimeError propagated, catch and render as `*Erro na transcrição: {error}*` |

---

## External Code References

**`pipeline/node_process_media_at_drive.py`**
- Entry point: `process_media_at_drive(state: dict) -> dict`
- `state` must include `"drive_link"` key
- Optional context keys passed through to `process_audio`: `org_name`, `person_name`, `person_position`, `org_setor`
- Returns: `{"drive_transcriptions": [str, ...]}`
- Source: user's own repo (not GarethWright's)

**`pipeline/pipeline.py`**
- `process_audio(file_path, context)` — transcribes local audio/video via AssemblyAI SDK
- `process_pdf(file_path)` — extracts PDF via Docling → markdown
- `cleanup_local_file(filepath)` — safe temp cleanup
- No MinIO dependency for this tool — MinIO only used in `process_upload` (Streamlit flow)
- Source: user's own repo

**Pipedrive TypeScript reference** (API patterns only, do not copy JS):
https://github.com/GarethWright/PipeDrive-MCP-Server/blob/master/src/index.ts
- See `pipedrive_get_deal`, `pipedrive_list_notes`, `pipedrive_get_deal_activities`,
  `pipedrive_get_person`, `pipedrive_get_organization`, `pipedrive_search_deals`
- Adapt parameter names and endpoint paths to Python/httpx

---

## Dependencies

```
fastmcp
httpx
assemblyai
docling
google-api-python-client
google-auth-oauthlib
google-auth-httplib2
```
