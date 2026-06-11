# NDados Pipedrive MCP Server

Python MCP server for Pipedrive CRM, built for the NDados nucleus at Poli Júnior.
Extends standard Pipedrive CRUD with intent-centered tools that combine Pipedrive data,
Google Drive, and AssemblyAI into high-context outputs for the commercial team.

---

## Architecture

```
mcp_server/
├── server.py                    # FastMCP entrypoint — tool registration
├── fields.py                    # ✅ DONE — Pipedrive field keys + enum option maps
├── pipedrive.py                 # Pipedrive API client (async httpx)
├── tools/
│   └── get_deal_context.py      # Intent-centered tool — see get-deal-context.md
└── pipeline/
    ├── node_process_media_at_drive.py   # Google Drive download + file routing
    └── pipeline.py                      # AssemblyAI transcription + Docling PDF
```

### Two layers of tools

**Layer 1 — Pipedrive CRUD (port from TypeScript reference)**
Standard create/read/update/delete for deals, persons, organizations, activities,
notes, pipelines, stages. Reference implementation:
https://github.com/GarethWright/PipeDrive-MCP-Server/blob/master/src/index.ts

Port the patterns directly to Python/httpx. The TypeScript file covers all endpoints
and serves as the source of truth for parameter names and API paths.

**Layer 2 — Intent-centered tools (new)**
Tools that fulfill a complete user intent in one call, composing multiple
Pipedrive endpoints + external services internally. Currently planned:
- `get_deal_context` — full deal briefing with transcribed meetings (see get-deal-context.md)

---

## Stack

| Concern | Tool |
|---|---|
| MCP framework | `fastmcp` (Python) |
| HTTP client | `httpx` with `asyncio.gather` for parallel requests |
| Google Drive | `google-api-python-client` + OAuth2 (`google-auth-oauthlib`) |
| Transcription | `assemblyai` SDK |
| PDF extraction | `docling` |
| Transport | `stdio` (local, Claude Desktop / Claude Code) |

---

## Environment Variables

```env
# Pipedrive
PIPEDRIVE_API_TOKEN=your_token_here
PIPEDRIVE_BASE_URL=https://api.pipedrive.com/v1   # default, override for custom domains

# AssemblyAI
ASSEMBLYAI_API_KEY=your_key_here

# Google Drive OAuth (file paths, not values)
GOOGLE_CREDENTIALS_FILE=./credentials.json        # OAuth client ID from GCP
GOOGLE_TOKEN_FILE=./token.json                     # auto-created after first auth flow
```

No MinIO required — files are downloaded from Drive to a local temp dir,
passed directly to AssemblyAI SDK by file path, then cleaned up.

---

## Key Files Already Built

### `fields.py` ✅
All Pipedrive custom field hash keys and enum option maps, with resolver helpers.
Do not hardcode field keys anywhere else in the codebase — always import from here.

```python
from fields import (
    DRIVE_FIELD, CANAL_FIELD, PORTFOLIO_FIELD, SETOR_FIELD,
    FUNCIONARIOS_FIELD, LOST_REASON_FIELD, LABEL_FIELD,
    CANAL_OPTIONS, SETOR_OPTIONS, FUNCIONARIOS_OPTIONS,
    PORTFOLIO_OPTIONS, LOST_REASON_OPTIONS, LABEL_OPTIONS,
    resolve_enum, resolve_set
)
```

### `pipeline/node_process_media_at_drive.py` (from repo)
Downloads all files from a Google Drive folder link and routes by file type.
Entry point: `process_media_at_drive(state: dict) -> dict`

- Input: `state = {"drive_link": "https://drive.google.com/..."}`
- Output: `{"drive_transcriptions": ["[Áudio/Vídeo - file.mp4]:\nSpeaker A: ...", ...]}`
- Handles: folders and single files, audio/video → AssemblyAI, PDF → Docling, text → read
- Manages: temp dir creation, per-file cleanup, error isolation per file

### `pipeline/pipeline.py` (from repo)
Core processing functions.

`process_audio(file_path: str, context: dict) -> str`
- Sends local file to AssemblyAI SDK (handles upload internally)
- `context` keys: `org_name`, `person_name`, `person_position`, `org_setor`
- Context builds a domain-specific prompt for NDados sales meetings
- Returns speaker-labeled transcript: `"Speaker A: ...\nSpeaker B: ..."`
- Config: `speaker_labels=True`, `language_detection=True`, `word_boost=[NDados terms]`

`process_pdf(file_path: str) -> str`
- Extracts PDF content via Docling, returns markdown

`cleanup_local_file(filepath: str)` — safe temp file removal

---

## Pipedrive API Patterns

Base URL: `https://api.pipedrive.com/v1`
Auth: `?api_token={PIPEDRIVE_API_TOKEN}` appended to every request (query param).

All responses follow:
```json
{ "success": true, "data": { ... } }
```
Always access `response["data"]`. On error: `{ "success": false, "error": "..." }`.

Enum and set fields in deal/person/org responses return **numeric IDs**, not labels.
Always resolve through the option maps in `fields.py`.

---

## Claude Desktop Config (stdio)

```json
{
  "mcpServers": {
    "ndados-pipedrive": {
      "command": "python",
      "args": ["path/to/server.py"],
      "env": {
        "PIPEDRIVE_API_TOKEN": "...",
        "ASSEMBLYAI_API_KEY": "...",
        "GOOGLE_CREDENTIALS_FILE": "path/to/credentials.json",
        "GOOGLE_TOKEN_FILE": "path/to/token.json"
      }
    }
  }
}
```

---

## Implementation Order

1. `pipedrive.py` — async API client with `pd(method, path, data, params)` helper
2. `server.py` — FastMCP scaffold with env var validation on startup
3. `tools/get_deal_context.py` — first intent-centered tool (see get-deal-context.md)
4. CRUD tools — port from TypeScript reference, register in `server.py`
