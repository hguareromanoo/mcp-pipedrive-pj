# Module: `field_registry.FieldsRegistry`

Dynamic registry that discovers and caches Pipedrive schema (custom field hashes, enum/set option IDs, pipelines, stages, users) so that tools resolve human-readable names to API identifiers at runtime instead of importing hardcoded constants from `fields.py`.

The registry is the foundation under all v1 read tools (A1, A4, B1, B2, B3, C2). It is not a tool itself — it does not register with FastMCP — it is a Python class instantiated once in `server.py` and passed into each tool's `register()`.

---

## Public Interface

```python
from typing import Literal

class FieldsRegistry:
    def __init__(
        self,
        cache_path: str = ".cache/pipedrive_schema.json",
        ttl_hours: int = 6,
    ) -> None: ...

    # ── Loading ───────────────────────────────────────────────────────────────
    async def ensure_loaded(self) -> None:
        """
        Idempotent load. Sequence:
          1. If in-memory state is populated AND fresh → return.
          2. Else if cache file exists AND fresh → load from disk → return.
          3. Else fetch from Pipedrive API, write cache, populate memory → return.
          4. If API fetch fails AND cache file exists (even stale) → load stale
             cache, log warning, return.
          5. If API fetch fails AND no cache → raise RuntimeError.
        """

    async def refresh(self) -> None:
        """Force re-fetch from API. Overwrites cache and memory."""

    # ── Field resolution ──────────────────────────────────────────────────────
    def field_key(self, entity: Literal["deal", "person", "org"], display_name: str) -> str:
        """
        Resolve a field display name to its Pipedrive key/hash.
        Native fields (e.g. "Etapa" → "stage_id") and custom fields (e.g. "Setor"
        → a 40-char hash) both supported.
        Raises KeyError with list of valid names if not found.
        """

    def option_id(self, entity: str, field_name: str, label: str) -> int:
        """
        Resolve an enum/set option label to its numeric ID.
        Example: option_id("deal", "Etiqueta", "NDados") → 32
        Raises KeyError with list of valid labels if not found.
        """

    def option_label(self, entity: str, field_name: str, option_id: int) -> str:
        """
        Reverse: numeric option ID to its label.
        Returns "[ID desconhecido: N]" if not found. Does not raise.
        """

    # ── Native lookups ────────────────────────────────────────────────────────
    def pipeline_name(self, pipeline_id: int) -> str:
        """Pipeline ID to name. Returns f'Funil {id}' if unknown."""

    def stage_name(self, stage_id: int) -> str:
        """Stage ID to name. Returns f'Etapa {id}' if unknown."""

    def user_name(self, user_id: int) -> str:
        """User ID to name. Returns f'Usuário {id}' if unknown."""

    def user_id_by_name(self, name: str) -> int:
        """User name to ID (exact match). Raises KeyError if not found."""

    def stage_id_by_name(self, name: str, pipeline_id: int | None = None) -> int:
        """
        Stage name to ID. If multiple stages share the name across pipelines,
        pipeline_id disambiguates. Raises if ambiguous without disambiguator.
        """

    # ── Serialization ─────────────────────────────────────────────────────────
    def serialize_deal(self, deal: dict, include_fields: list[str] | None = None) -> dict:
        """
        Convert raw Pipedrive deal dict (with hashes and numeric IDs) into a
        human-readable dict.

        Without include_fields: default subset (11 keys):
            id, title, value, currency, stage_name, pipeline_name,
            owner_name, status, label_names, add_time, update_time

        With include_fields: only those keys. Each must be one of:
          - a key from the default subset
          - a known field display name (e.g. "Setor", "Canal de Entrada",
            "Portfólio", "Número de Funcionários")

        Custom fields resolve as:
          - enum   → label string
          - set    → list[str] of labels
          - varchar → raw string
          - varchar_options (e.g. lost_reason) → label string

        Raises ValueError if any include_fields entry is unknown.
        """
```

---

## Internal State

After `ensure_loaded()`:

```python
self._deal_fields:   dict[str, FieldMeta]   # keyed by display_name (e.g. "Setor")
self._person_fields: dict[str, FieldMeta]
self._org_fields:    dict[str, FieldMeta]
self._pipelines:     dict[int, str]         # id → name
self._stages:        dict[int, StageMeta]   # id → {name, pipeline_id, order_nr}
self._users:         dict[int, str]         # id → name
self._loaded_at:     float                  # unix timestamp
```

`FieldMeta` (typed dict or dataclass):
```python
{
    "key": str,             # the hash or native key
    "display_name": str,
    "field_type": str,      # "enum", "set", "varchar", "double", "date", etc.
    "options": dict[int, str] | None,   # for enum/set fields only
}
```

`StageMeta`:
```python
{
    "name": str,
    "pipeline_id": int,
    "order_nr": int,
}
```

---

## Cache Format

File: `.cache/pipedrive_schema.json` (relative to repo root by default).

```json
{
  "_loaded_at": 1733692800.0,
  "deal_fields":   { "<display_name>": { "key": "...", "field_type": "...", "options": {...} | null }, ... },
  "person_fields": { ... },
  "org_fields":    { ... },
  "pipelines":     { "1": "Nome do Funil", ... },
  "stages":        { "5": { "name": "AT Marcada", "pipeline_id": 1, "order_nr": 2 }, ... },
  "users":         { "123": "João Silva", ... }
}
```

JSON keys are strings (since JSON doesn't allow int keys); deserialization converts where appropriate.

TTL check uses `_loaded_at` not file mtime — explicit and deterministic.

---

## API Endpoints Consumed (during refresh)

All via `pipedrive.pd("GET", path)`. Six calls, can be parallelized with `asyncio.gather`.

| Endpoint | Purpose |
|---|---|
| `GET /v1/dealFields` | All deal fields (custom + native) with options |
| `GET /v1/personFields` | Person fields |
| `GET /v1/organizationFields` | Organization fields |
| `GET /v1/pipelines` | Pipeline list |
| `GET /v1/stages` | All stages across pipelines |
| `GET /v1/users` | User list (active + inactive) |

`/v1/dealFields` (and siblings) response shape:
```json
{
  "data": [
    {
      "key": "6ea1ea74da5fbb8cb6a8dd741a96a9bc8b4e379f",
      "name": "Setor da Empresa",
      "field_type": "enum",
      "options": [{ "id": 167, "label": "Information Technology & Services" }, ...]
    },
    ...
  ]
}
```

For fields without options (varchar, double, date), `options` is `null` or missing.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| First-time load, API 5xx | RuntimeError with explanation: "Não foi possível carregar schema do Pipedrive (sem cache disponível)." |
| Refresh fails but cache exists (any age) | Log warning, fall back to cached values, continue. |
| Cache file corrupt JSON | Log warning, treat as no-cache; if API also fails, RuntimeError. |
| `field_key` for unknown name | KeyError with message listing valid display names for that entity. |
| `option_id` for unknown label | KeyError with message listing valid labels for that field. |
| `option_label` for unknown ID | Return `"[ID desconhecido: N]"` (does not raise, mirrors current `fields.py` behavior). |
| `serialize_deal` with unknown `include_fields` entry | ValueError with message listing valid keys + field display names. |
| `stage_id_by_name` ambiguous | KeyError saying "Múltiplos stages com nome X em pipelines Y, Z. Especifique pipeline_id." |

---

## Concurrency

`ensure_loaded()` is async and uses an internal asyncio.Lock to prevent concurrent loads from racing. The first caller in a contention wins and loads; subsequent callers await the lock then short-circuit because state is now fresh.

---

## Test Strategy

Unit (mocked via respx) covers all logic paths: cache hit/miss/expired, fallback to stale cache on API failure, lookups (positive + negative), serialization (default + custom + unknown), concurrency safety.

Integration (real API in `tests/integration/`) validates that:
- The schema actually loads against the PJ's Pipedrive instance.
- Expected display names ("Canal de Entrada", "Setor da Empresa", "Portfólio", "Número de Funcionários", "Link Drive das Gravações", "Etiqueta") are present.
- Expected option labels (núcleos: NDados/NCiv/NCon/NTec/WI/NI; canais: Inbound/Outbound/Fidelização/Indicação) are resolvable.

Integration tests are gated on `PIPEDRIVE_API_TOKEN` being present; skipped with a clear message otherwise.

---

## Dependencies

```
httpx              # already in requirements.txt (used by pipedrive.py)
python-dotenv      # already in requirements.txt
```

No new runtime deps. Dev deps: pytest, respx, pytest-asyncio, pytest-cov (in `requirements-dev.txt`).
