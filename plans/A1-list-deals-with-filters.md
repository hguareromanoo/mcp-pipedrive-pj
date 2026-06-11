# Tool: `list_deals_with_filters` (A1)

List Pipedrive deals filtering by any combination of native and custom fields,
with caller-controlled subset of fields returned per deal (`include_fields`).
This is the foundational read primitive: B1, B2, B3 all descend from it.

Spec lives here. Implementation in `tools/list_deals_with_filters.py`.
Depends on `field_registry.FieldsRegistry` (see `plans/registry-field-registry.md`).

---

## Signature

```python
from typing import Literal

@mcp.tool(
    name="list_deals_with_filters",
    annotations={
        "title": "List Deals With Filters",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_deals_with_filters(
    nucleo: str | None = None,
    portfolio: list[str] | None = None,
    canal: str | None = None,
    setor: str | None = None,
    cn_name: str | None = None,
    stage: str | None = None,
    pipeline: str | None = None,
    status: Literal["open", "won", "lost", "deleted", "all_not_deleted"] = "all_not_deleted",
    start_date: str | None = None,
    end_date: str | None = None,
    include_fields: list[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    List Pipedrive deals matching the given filters. All filters are optional;
    omitting all returns up to `limit` deals with status=all_not_deleted.

    Filters by native fields (status, owner, stage, pipeline, period) are
    pushed to the Pipedrive query string. Filters by custom fields (núcleo,
    portfólio, canal, setor) are applied in memory after fetching, so the
    tool may fetch up to 5x `limit` before truncating.

    Args:
        nucleo: One of "NDados", "NCiv", "NCon", "NTec", "WI", "NI" — filters by Etiqueta.
        portfolio: List of portfolio names — deal must have at least one (set intersection).
        canal: One of "Inbound", "Outbound", "Fidelização", "Indicação".
        setor: Setor da Empresa label (exact match).
        cn_name: Owner display name — resolved to user_id via registry.
        stage: Stage display name — resolved to stage_id (requires pipeline if ambiguous).
        pipeline: Pipeline display name — resolved to pipeline_id.
        status: Pipedrive native status filter.
        start_date: ISO date "YYYY-MM-DD"; filters deals by add_time >= start_date.
        end_date: ISO date "YYYY-MM-DD"; filters deals by add_time <= end_date.
        include_fields: Subset of fields to return per deal. Defaults to a
            curated enxuto subset (see FieldsRegistry.serialize_deal).
        limit: Max deals returned (default 100). Internal pagination uses pages of 500.

    Returns:
        List of dicts. Each dict reflects `include_fields` or the default subset.

    Raises:
        ValueError: filter value unknown to current Pipedrive schema (e.g. nucleo="Marciano"),
                    or include_fields entry unknown. Message lists valid options.
        RuntimeError: API failure during pagination. Message indicates which page
                      failed and how many deals had been accumulated.
    """
```

---

## Internal Execution Flow

```
Step 1 — Ensure schema is loaded
  await registry.ensure_loaded()

Step 2 — Resolve filter values to API identifiers
  For each non-None custom filter:
    nucleo     → label_option_id  = registry.option_id("deal", "Etiqueta", nucleo)
    portfolio  → portfolio_option_ids = [registry.option_id("deal", "Portfólio", p) for p in portfolio]
    canal      → canal_option_id     = registry.option_id("deal", "Canal de Entrada", canal)
    setor      → setor_option_id     = registry.option_id("deal", "Setor da Empresa", setor)
  For each non-None native-via-name filter:
    cn_name    → owner_id = registry.user_id_by_name(cn_name)
    pipeline   → pipeline_id_int = next k for k,v in pipelines if v == pipeline (raise if not found)
    stage      → stage_id_int = registry.stage_id_by_name(stage, pipeline_id_int)
  All KeyError raised by registry are caught and re-raised as ValueError with
  helpful message + list of valid options. (The agent's own ValueError for
  include_fields is left to FieldsRegistry to raise.)

Step 3 — Build native query params
  params = { "limit": 500, "start": 0 }                # page size = 500 (Pipedrive max)
  if status:        params["status"]      = status
  if owner_id:      params["owner_id"]    = owner_id
  if stage_id_int:  params["stage_id"]    = stage_id_int
  if pipeline_id_int: params["pipeline_id"] = pipeline_id_int
  if start_date:    params["start_date"]  = start_date
  if end_date:      params["end_date"]    = end_date

Step 4 — Paginate
  deals: list[dict] = []
  while True:
    page = await pd_with_pagination("GET", "deals", params=params)
    # page is dict with keys: "data" (list) and "additional_data.pagination"
    items = page["data"] or []
    deals.extend(items)
    pg = (page.get("additional_data") or {}).get("pagination") or {}
    if not pg.get("more_items_in_collection"):
      break
    params["start"] = pg.get("next_start") or (params["start"] + 500)
    # Safety cap: don't loop forever
    if len(deals) > 5000:
      raise RuntimeError("Pagination exceeded safety cap of 5000 deals; tighten filters.")

Step 5 — Post-filter custom fields in memory
  setor_key     = registry.field_key("deal", "Setor da Empresa")
  canal_key     = registry.field_key("deal", "Canal de Entrada")
  portfolio_key = registry.field_key("deal", "Portfólio")
  label_key     = "label"  # native

  def matches(deal: dict) -> bool:
    if nucleo is not None:
      raw = deal.get(label_key)
      ids = _csv_to_int_set(raw)
      if label_option_id not in ids:
        return False
    if portfolio is not None:
      raw = deal.get(portfolio_key)
      ids = _csv_to_int_set(raw)
      if not set(portfolio_option_ids) & ids:
        return False
    if canal is not None:
      if _to_int(deal.get(canal_key)) != canal_option_id:
        return False
    if setor is not None:
      if _to_int(deal.get(setor_key)) != setor_option_id:
        return False
    return True

  deals = [d for d in deals if matches(d)]

Step 6 — Truncate to limit
  deals = deals[:limit]

Step 7 — Serialize each deal
  return [registry.serialize_deal(d, include_fields) for d in deals]
```

---

## Pagination Note

`pipedrive.pd()` returns only `body["data"]` — it discards `additional_data`,
which is where Pipedrive puts the pagination cursor. A1 needs both, so it
cannot use `pd()` as-is.

**Decision:** add a thin sibling helper `pd_raw()` in `pipedrive.py` that
returns the full response body (not just `data`). A1 uses `pd_raw()` for the
paginated `GET /v1/deals` call. Other tools continue using `pd()`.

```python
# pipedrive.py — sibling helper

async def pd_raw(method: str, path: str, data: dict | None = None, params: dict | None = None) -> Any:
    """Like pd() but returns the full envelope (data + additional_data)."""
    merged = {**(params or {}), "api_token": os.environ["PIPEDRIVE_API_TOKEN"]}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=method.upper(),
            url=f"{_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
            params=merged,
            json=data,
        )
        response.raise_for_status()
        body = response.json()
    if not body.get("success"):
        raise ValueError(body.get("error", "Pipedrive API error"))
    return body
```

This is the only modification to `pipedrive.py` in this entrega. `pd()` stays unchanged.

---

## Helper utilities (inside `tools/list_deals_with_filters.py`)

```python
def _csv_to_int_set(raw) -> set[int]:
    """'27,29' or 27 or None → {27, 29} or {27} or set()."""
    if raw is None or raw == "":
        return set()
    if isinstance(raw, int):
        return {raw}
    return {int(x.strip()) for x in str(raw).split(",") if x.strip()}


def _to_int(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None
```

---

## Output Format

Each deal is a dict produced by `registry.serialize_deal(deal, include_fields)`.

Default keys (when `include_fields is None`):
```
id, title, value, currency, stage_name, pipeline_name, owner_name,
status, label_names, add_time, update_time
```

Custom subset example:
```python
include_fields=["title", "value", "Setor da Empresa"]
# →  { "title": "...", "value": 48000, "Setor da Empresa": "Information Technology & Services" }
```

The MCP tool returns `list[dict]`. FastMCP serializes the list to JSON for the
client; if structured output (`structuredContent`) is supported, ideally also
expose an `outputSchema` describing each dict. For v1, keep it simple: return
the list directly.

---

## Error Handling

| Failure point | Behavior |
|---|---|
| `nucleo`, `portfolio`, `canal`, `setor`, `cn_name`, `stage`, `pipeline` resolves via registry and raises `KeyError` | Catch and re-raise as `ValueError` with message: `"<filter>='<value>' não é válido. Opções válidas: <list>."` |
| `include_fields` entry unknown | `ValueError` raised by `registry.serialize_deal` propagates with valid-fields list |
| `start_date` or `end_date` not parseable | `ValueError` with format hint `"YYYY-MM-DD"` |
| API timeout / 5xx during pagination | `RuntimeError(f"Falha ao buscar página start={params['start']} após acumular {len(deals)} deals: {original_error}")` |
| Pagination loop exceeds 5000 deals | `RuntimeError("Pagination exceeded safety cap of 5000 deals; tighten filters.")` |
| Empty result set | Return `[]` — not an error |
| Pipedrive returns `{ success: false }` | `pd_raw()` already raises `ValueError`; propagate |

---

## Registration

`tools/list_deals_with_filters.py` exposes:

```python
def register(mcp: FastMCP, registry: FieldsRegistry) -> None:
    """Register list_deals_with_filters with the given registry instance."""
    @mcp.tool(name="list_deals_with_filters", annotations={...})
    async def list_deals_with_filters(...):
        # implementation per Internal Execution Flow above
```

`server.py` is modified minimally:

```python
# server.py — additions only

from field_registry import FieldsRegistry
registry = FieldsRegistry()

# ... existing CN tool registrations unchanged ...

from tools.list_deals_with_filters import register as reg_list
reg_list(mcp, registry)
```

`FieldsRegistry()` is instantiated but NOT loaded eagerly — `ensure_loaded()` is
called inside each tool. This avoids blocking MCP server startup on Pipedrive
availability.

---

## External Code References

- `pipedrive.py:pd()` — used for any non-paginated calls (none currently in A1, but kept for consistency with the rest of the codebase).
- `pipedrive.py:pd_raw()` — NEW sibling helper, added in this entrega. Used by A1 for paginated `GET /v1/deals`.
- `field_registry.FieldsRegistry` — resolves all human names ↔ IDs and serializes deals.
- `fields.py` — NOT used. (Existing tools still use it; A1 does not.)

---

## Dependencies

No new runtime dependencies. Reuses what's already in `requirements.txt`:
- `fastmcp`
- `httpx`

Dev deps for tests in `requirements-dev.txt`: pytest, respx, pytest-asyncio.

---

## API endpoints consumed

| Endpoint | When | Notes |
|---|---|---|
| `GET /v1/deals` | Step 4 (paginated) | Filters: status, owner_id, stage_id, pipeline_id, start_date, end_date, limit=500, start=N |
| `GET /v1/dealFields`, `/v1/personFields`, etc. | Indirectly via `registry.ensure_loaded()` if not yet loaded | Cached by FieldsRegistry |

---

## Open questions for empirical validation (during implementation)

These are things the spec assumes; the agent implementing should verify against the real Pipedrive instance and adjust if reality differs:

1. **`/v1/deals` filter by `pipeline_id`** — does the API support this directly, or only via `filter_id`? If not directly supported, drop from native filters and apply pipeline filter in memory.
2. **`stage_id` filter exclusivity** — passing `stage_id` to `/v1/deals` should return only deals in that stage. Verify.
3. **`label` field shape** — confirm whether Pipedrive returns the label field as `"32"` (string of one ID), `"32,33"` (CSV), or as a list. `fields.py` notes suggest CSV. Adjust `_csv_to_int_set` if needed.
4. **Custom field key in deal payload** — confirm each custom field is present at the top level of the deal dict using its hash as key (the convention `fields.py` uses).

If any assumption fails, the integration tests will reveal it.
