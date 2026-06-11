# A4 — Base Gets (gets básicos)

Seven thin read tools that wrap Pipedrive primitives. They exist so the LLM has named, discoverable handles to fetch individual entities (`get_person`, `get_organization`), list children of a deal (`get_notes`, `get_activities`), or enumerate schema entries already in `FieldsRegistry` (`list_pipelines`, `list_stages`, `list_users`).

Together with A1 (`list_deals_with_filters`) these form the read primitive layer that B1, B2, B3, C2 will compose on top of.

All seven tools live in a single module `tools/base_gets.py` (one file, one `register(mcp, registry)` that adds all of them). This keeps the surface tight and the shared helpers in one place.

---

## Shared design rules

- **Read-only.** All tools have `readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=True`.
- **Schema-aware via FieldsRegistry.** Resolution of names↔IDs and serialization of entity dicts always go through the registry. No imports from `fields.py`.
- **`include_fields` only where it makes sense.** Entity-get tools (`get_person`, `get_organization`) accept `include_fields: list[str] | None` and delegate filtering to the registry-equivalent serializer. List-of-entities tools (`get_notes`, `get_activities`, `list_pipelines`, `list_stages`, `list_users`) return a fixed, enxuto shape since the items are already small.
- **Error contract.** Entity-by-ID with unknown ID → `ValueError("<entity> not found: <id>")`. List endpoint with no results → empty list (not error). Filter value resolved via registry but unknown → `ValueError` with valid options listed (caught from KeyError and re-raised, same pattern as A1).
- **Pagination.** Of the four API-call tools, only `get_notes` and `get_activities` might paginate. Use `pd_raw` if and only if the caller may need more than the default page size (50). For v1, cap returned items at `limit` and document that more pages can be fetched in a follow-up if needed; do not auto-paginate beyond the cap.

## Tool 1 — `get_person`

```python
async def get_person(
    person_id: int,
    include_fields: list[str] | None = None,
) -> dict:
    """
    Fetch a single Pipedrive person by ID.

    Returns:
        Dict with default subset: {id, name, email, phone, job_title, org_name}.
        With include_fields, only those keys; each must be in the default subset
        or be a known person field display name (e.g. "Email", "Phone").

    Raises:
        ValueError: person_id not found, or include_fields entry unknown.
    """
```

Internal flow:
1. `await registry.ensure_loaded()`
2. `person = await pd("GET", f"persons/{person_id}")`. If `None`, raise `ValueError(f"Person not found: {person_id}")`.
3. Serialize via a helper `serialize_person(person, include_fields)` analogous to `serialize_deal`.
   Default subset:
   - `id`, `name`, `job_title`, `email` (first entry's value), `phone` (first entry's value), `org_name` (from `org_id.name` or `org_id` dict shape).
4. Return dict.

## Tool 2 — `get_organization`

```python
async def get_organization(
    org_id: int,
    include_fields: list[str] | None = None,
) -> dict:
    """
    Fetch a single Pipedrive organization by ID.

    Returns:
        Dict with default subset: {id, name, address, owner_name}.
        With include_fields, only those keys.

    Raises:
        ValueError: org_id not found, or include_fields entry unknown.
    """
```

Internal flow: analogous to `get_person`, calling `GET /v1/organizations/{id}`.

Default subset: `id`, `name`, `address` (the human-readable string Pipedrive provides), `owner_name`.

## Tool 3 — `get_notes`

```python
async def get_notes(
    deal_id: int | None = None,
    person_id: int | None = None,
    org_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Fetch notes attached to a deal, person, or organization. Exactly one of
    deal_id / person_id / org_id must be provided.

    Returns:
        List of dicts: {id, content, add_time, user_name}, most recent first.
        Empty list if no notes.

    Raises:
        ValueError: if none of deal_id/person_id/org_id provided, or if more than one provided.
    """
```

Internal flow:
1. Validate exactly one of the three IDs is provided.
2. `await pd("GET", "notes", params={<entity>_id: id, "limit": limit, "sort": "add_time DESC"})`.
3. Map each note dict: `{"id": note["id"], "content": note["content"], "add_time": note["add_time"], "user_name": (note.get("user") or {}).get("name", "—")}`.
4. Return list.

## Tool 4 — `get_activities`

```python
async def get_activities(
    deal_id: int | None = None,
    person_id: int | None = None,
    org_id: int | None = None,
    done: bool | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Fetch activities attached to a deal, person, or organization, optionally
    filtered by done status. Exactly one of deal_id/person_id/org_id must be provided.

    Returns:
        List of dicts: {id, type, subject, due_date, done, note}.
        Empty list if no activities.

    Raises:
        ValueError: if none or more than one of deal_id/person_id/org_id provided.
    """
```

Internal flow:
1. Validate exactly one entity ID.
2. If `deal_id`: `await pd("GET", f"deals/{deal_id}/activities", params={"limit": limit})`. Pipedrive supports a `done` filter (0 or 1) on this endpoint — pass it if `done is not None`.
3. If `person_id` or `org_id`: `await pd("GET", "activities", params={<entity>_id: id, "limit": limit, **maybe_done})`.
4. Map each activity dict: `{"id", "type", "subject", "due_date", "done": bool(act.get("done")), "note"}`.
5. Return list.

## Tool 5 — `list_pipelines`

```python
def list_pipelines() -> list[dict]:
    """
    List all pipelines configured in the Pipedrive instance.

    Returns:
        List of {id, name}, sorted by id ascending. Empty list if none.
    """
```

Pure registry read. No `await` of API. Just `await registry.ensure_loaded()` (since registry methods need it), then iterate `registry._pipelines`. Sorted by id.

(Implementation may choose to add a public `pipelines_list()` method on FieldsRegistry instead of touching `_pipelines` directly. Both acceptable for v1.)

## Tool 6 — `list_stages`

```python
def list_stages(pipeline: str | None = None) -> list[dict]:
    """
    List stages, optionally filtered by pipeline name.

    Returns:
        List of {id, name, pipeline_id, pipeline_name, order_nr}, sorted by
        (pipeline_id, order_nr) ascending. Empty list if pipeline name given but
        no stages match.

    Raises:
        ValueError: pipeline name given but not found in schema (with valid pipeline names listed).
    """
```

Resolve pipeline name → id via registry (same pattern as A1). Filter `registry._stages` by `pipeline_id`. Decorate each stage with `pipeline_name`.

## Tool 7 — `list_users`

```python
def list_users(active_only: bool = True) -> list[dict]:
    """
    List Pipedrive users (members of the workspace).

    Returns:
        List of {id, name}, sorted by name. Empty list if none.

    Notes:
        active_only is a placeholder for v1.1. FieldsRegistry currently does not
        persist the active_flag; the parameter is accepted but ignored. v1.1 may
        store active_flag in cache and filter accordingly.
    """
```

Pure registry read. Iterate `registry._users`. Sort by name.

---

## Registration (in `tools/base_gets.py`)

```python
def register(mcp: FastMCP, registry: FieldsRegistry) -> None:
    @mcp.tool(name="get_person", annotations=_READ_ANNOTATIONS)
    async def get_person(...): ...

    @mcp.tool(name="get_organization", annotations=_READ_ANNOTATIONS)
    async def get_organization(...): ...

    @mcp.tool(name="get_notes", annotations=_READ_ANNOTATIONS)
    async def get_notes(...): ...

    @mcp.tool(name="get_activities", annotations=_READ_ANNOTATIONS)
    async def get_activities(...): ...

    @mcp.tool(name="list_pipelines", annotations=_READ_ANNOTATIONS)
    async def list_pipelines(): ...

    @mcp.tool(name="list_stages", annotations=_READ_ANNOTATIONS)
    async def list_stages(pipeline=None): ...

    @mcp.tool(name="list_users", annotations=_READ_ANNOTATIONS)
    async def list_users(active_only=True): ...
```

`_READ_ANNOTATIONS` is a module-level constant.

`server.py` adds:

```python
from tools.base_gets import register as reg_base_gets
reg_base_gets(mcp, registry)
```

---

## Helper serializers

Two small helpers in `tools/base_gets.py`, analogous to `registry.serialize_deal`:

```python
PERSON_DEFAULT_KEYS = ["id", "name", "job_title", "email", "phone", "org_name"]
ORG_DEFAULT_KEYS = ["id", "name", "address", "owner_name"]


def _serialize_person(person: dict, registry: FieldsRegistry, include_fields: list[str] | None) -> dict:
    """Project person dict to default subset or include_fields. Custom fields
    resolved via registry just like serialize_deal."""
    ...


def _serialize_organization(org: dict, registry: FieldsRegistry, include_fields: list[str] | None) -> dict:
    ...
```

Behavior of `include_fields` mirrors `registry.serialize_deal`:
- `None` → default subset.
- list of strings → exactly those keys, each must be a default key OR a known person/org field display name from the registry.
- Unknown name → `ValueError` listing valid options.

Note that there's a real argument for putting these inside `FieldsRegistry` (as `serialize_person`, `serialize_organization` siblings of `serialize_deal`). v1.1 may do this consolidation; for v1, the helpers live in `tools/base_gets.py` to keep the registry change surface minimal in this fatia.

---

## Pipedrive API endpoints consumed

| Endpoint | Used by |
|---|---|
| `GET /v1/persons/{id}` | `get_person` |
| `GET /v1/organizations/{id}` | `get_organization` |
| `GET /v1/notes?deal_id=…` (or person_id/org_id) | `get_notes` |
| `GET /v1/deals/{id}/activities` | `get_activities(deal_id=…)` |
| `GET /v1/activities?person_id=…` (or org_id) | `get_activities(person_id=… or org_id=…)` |
| (no API) — registry read | `list_pipelines`, `list_stages`, `list_users` |

---

## Test plan

**Unit (`tests/unit/test_base_gets.py`):** ~16 tests with respx mocks + `mock_registry`.

- `get_person`: happy path; not-found raises ValueError; include_fields subset; include_fields unknown raises.
- `get_organization`: same 4 cases.
- `get_notes`: returns mapped list; no-id raises; multi-id raises; empty list when none; routes deal_id vs person_id vs org_id.
- `get_activities`: returns mapped list; deal_id route uses `/deals/{id}/activities`; person/org route uses `/activities?<id>=`; `done` filter passes through.
- `list_pipelines`: returns sorted list of dicts; works without API call.
- `list_stages`: returns full list when no pipeline; filtered by pipeline name; unknown pipeline raises.
- `list_users`: returns sorted by name.

**Integration (`tests/integration/test_base_gets_real.py`):** ~8 tests against the real PJ Pipedrive.

- `test_real_list_pipelines_non_empty`
- `test_real_list_stages_for_known_pipeline_returns_stages` (use first pipeline from `list_pipelines`)
- `test_real_list_users_non_empty`
- `test_real_get_person_known_id_works` — find one person via a deal first, then resolve. Or accept any one user_id with a person attached.
- `test_real_get_organization_known_id_works` — same strategy.
- `test_real_get_notes_for_deal` — pick first deal from A1, call get_notes(deal_id=…), assert list.
- `test_real_get_activities_for_deal` — pick first deal from A1, call get_activities(deal_id=…), assert list and shape.
- `test_real_get_person_not_found_raises` — call with absurd ID like 999999999, expect ValueError.

The "pick first deal from A1" pattern is fragile but the data exists; if the instance is empty (no deals), the test skips with a clear message.

---

## Done criteria

- 16 unit tests green
- 8 integration tests green (with token)
- All 7 tools registered in `server.py`
- No changes outside `tools/base_gets.py` and `server.py` (and the new test files)
