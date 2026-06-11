# MCP Pipedrive — Poli Júnior

Read-only MCP server that exposes the Poli Júnior Pipedrive CRM to Claude
(Desktop or Code) as composable tools. Built for the four commercial cargos
of the PJ: Diretor Executivo, Gerente Comercial de Núcleo, Líder de Outbound,
e Coordenador de Negócios.

The MCP focuses strictly on Pipedrive data — listing, filtering, aggregating,
fetching individual entities. Meeting transcription, Drive integration, and
any write-side workflow are explicitly out of scope (they belong to other,
purpose-built MCPs).

---

## Architecture

```
mcp-pipedrive-pj/
├── server.py              # FastMCP entrypoint + monkey-patches mcp.tool with observability
├── pipedrive.py           # Async HTTP client: pd() returns body['data']; pd_raw() returns full envelope
├── field_registry.py      # FieldsRegistry: dynamic schema discovery + disk cache (TTL 6h)
├── fields.py              # LEGACY hardcoded hashes/options used only by get_deal_context
├── observability.py       # instrument() decorator → .observability/usage.jsonl per tool call
│
├── tools/
│   ├── list_deals_with_filters.py   # A1 — filtros compostos + include_fields
│   ├── base_gets.py                  # A4 — 7 read tools (person, org, notes, activities, list_*)
│   ├── analytics.py                  # B1/B2/B3 — conversion / lost reasons / owner activity
│   ├── get_deal_context.py           # Legacy CRM briefing (uses fields.py, no transcription)
│   └── find_deals.py                 # Legacy text search (redundant with A1; candidate for removal)
│
├── plans/                 # Per-tool specs (signature, internal flow, error handling)
├── tests/
│   ├── unit/              # respx mocks + mock_registry fixture
│   └── integration/       # Real Pipedrive instance, gated on PIPEDRIVE_API_TOKEN
└── pytest.ini
```

### FieldsRegistry — why it exists

Pipedrive custom fields are addressed by opaque hash keys (`6ea1ea74...`) and
their enum options are numeric IDs. The PJ instance also renames fields,
adds options (new núcleo, new sector), and deletes/recreates fields over time.

`FieldsRegistry` discovers the schema at runtime, caches it in
`.cache/pipedrive_schema.json` (TTL 6h, falls back to stale cache when the
API is unreachable), and exposes resolution by human-readable name:

```python
registry.field_key("deal", "Setor da Empresa")      # → hash
registry.option_id("deal", "Etiqueta", "NDados")    # → 32
registry.user_id_by_name("Henrique Romano")         # → 100
registry.serialize_deal(deal, include_fields=[...]) # → human-readable dict
```

All v1 tools resolve names through the registry. None of them imports from
`fields.py`. The legacy `get_deal_context` tool still uses `fields.py` —
migration to the registry is a follow-up task (a.k.a. "C5").

### Observability

`observability.instrument(fn)` wraps every registered tool. Each invocation
writes one JSON line to `.observability/usage.jsonl`:

```json
{"timestamp":"2026-06-10T17:23:09.104Z","tool":"list_deals_with_filters","latency_ms":1347,"status":"ok"}
```

On error:

```json
{"timestamp":"...","tool":"get_person","latency_ms":87,"status":"error","error_type":"ValueError","error_message":"Person not found: 999999"}
```

Failures during the log write are swallowed silently so they never block the
tool's return.

---

## Tools

| Tool | Persona-alvo | What it does |
|---|---|---|
| `list_deals_with_filters` | DE / Gerente / LO / CN | Lista deals com filtros compostos: núcleo, portfólio, canal, setor, CN owner, stage, pipeline, status, período. `include_fields` controla shape do output. |
| `get_person` | todas | Busca pessoa (contato) por ID com `include_fields` opcional. |
| `get_organization` | todas | Busca organização por ID com `include_fields` opcional. |
| `get_notes` | todas | Notas atreladas a um deal / pessoa / org (exatamente um). |
| `get_activities` | todas | Atividades (calls, meetings, tasks) atreladas a um deal / pessoa / org. Filtro opcional `done`. |
| `list_pipelines` | todas | Funis configurados no Pipedrive (id + name). |
| `list_stages` | todas | Etapas, opcionalmente filtradas por pipeline. |
| `list_users` | todas | Usuários do workspace (resolução de nomes de CN/owner). |
| `get_conversion_rates` | DE / Gerente | Close-rate e win-rate sobre o conjunto filtrado, com `group_by` opcional (núcleo, canal, owner, portfólio). |
| `get_lost_reasons_analysis` | DE / Gerente | Agregação de "Motivo da perda" sobre deals lost. Filtro de data aplica em `lost_time`. |
| `get_owner_activity` | DE / LO | Snapshot por owner: deals por status, hot/cold, tasks atrasadas, valor open. |
| `get_deal_context` | CN / todas | Briefing markdown do deal (CRM apenas — sem transcrição). Legado, ainda usa `fields.py`. |
| `find_deals` | (legacy) | Busca por termo no título. Redundante com `list_deals_with_filters`. |

---

## Setup

### Requirements

- Python 3.13+
- Pipedrive REST API token (https://app.pipedrive.com/settings/personal/api)

### Install

```bash
git clone https://github.com/hguareromanoo/mcp-pipedrive-pj.git
cd mcp-pipedrive-pj
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt        # runtime
pip install -r requirements-dev.txt    # + pytest, respx, etc.
```

### Configure

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
# edit .env to add your PIPEDRIVE_API_TOKEN
```

### Run as Claude Desktop MCP

Add this entry to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pipedrive-pj": {
      "command": "/abs/path/to/mcp-pipedrive-pj/venv/bin/python",
      "args": ["/abs/path/to/mcp-pipedrive-pj/server.py"],
      "env": {
        "PIPEDRIVE_API_TOKEN": "your_token_here",
        "PYTHONPATH": "/abs/path/to/mcp-pipedrive-pj"
      }
    }
  }
}
```

Restart Claude Desktop. The 13 tools above appear under `pipedrive-pj`.

### Smoke test (from terminal)

```bash
source venv/bin/activate
python -c "import server; print('server.py imports OK')"
```

---

## Tests

```bash
source venv/bin/activate

# Unit (mocked via respx, no network)
pytest tests/unit/ -v

# Integration (hits the real Pipedrive instance via PIPEDRIVE_API_TOKEN)
pytest tests/integration/ -v

# Everything (≈ 2.5 min, dominated by integration tests against the real API)
pytest tests/
```

Tests gated on `@pytest.mark.integration` skip automatically when
`PIPEDRIVE_API_TOKEN` is absent. Current baseline: **116 passing.**

---

## Scope decisions baked in

- **Read-only in v1.** Bulk write operations on Pipedrive are explicitly out
  of scope. The 4 legacy write-side CN tools (`log_meeting`, `advance_deal`,
  `register_prospect`, `resolve_deal`) were removed — they are easier to do
  directly in the Pipedrive UI.
- **Meeting transcription is NOT here.** Drive + AssemblyAI integration was
  removed: typical PJ recording folders carry 7-8 `.mkv` files of 500MB-1.4GB
  each, totaling 30+ minutes of work per call. That does not fit a
  synchronous MCP request-response model. A separate "meeting intelligence"
  MCP is the right home for it.
- **`include_fields` everywhere.** Read tools accept a subset of fields to
  return, keeping LLM context windows tight.
- **API quirks documented in `PRD.md`.** The two that bit us:
  - `/v1/deals` filters by `user_id`, not `owner_id` (the latter is silently
    ignored by the API).
  - `start_date` / `end_date` on `/v1/deals` filter by `update_time`, not
    `add_time` — A1 applies the date window in memory to honor the
    documented contract.

---

## Status

- v1 feature-complete: A1, A4 (×7), B1, B2, B3, D2 (observability),
  FieldsRegistry, 116 passing tests.
- Legacy survivors: `get_deal_context` (kept), `find_deals` (kept, candidate
  for next cleanup).
- Pendente: piloto com early adopters (1 CN, 1 LO, 1 Gerente) + skills
  layered per cargo + handoff plan for after the original CIC steps down.
