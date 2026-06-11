# B — Analytics Tools (B1, B2, B3)

Three aggregation tools for Diretor, Gerente e LO. All three operate over the
current state of the funnel (v1 has no event store, so per-deal history is not
available). All three live in a single module `tools/analytics.py` with a
single `register(mcp, registry)` that adds them.

## Shared design

- **Read-only.** Annotations `readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=True`.
- **Filter vocabulary mirrors A1.** Same `nucleo`, `portfolio`, `canal`, `setor`, `cn_name`, `pipeline`, `start_date`, `end_date` parameters. Same semantics. Same error contract (unknown filter value → ValueError listing valid options, via re-raised KeyError from registry).
- **Implementation strategy:** internally fetch deals using the SAME function `_fetch_filtered_deals` that A1 wraps. Avoid duplicating the pagination + post-filter loop. The cleanest pattern is to extract that logic into a helper inside `tools/list_deals_with_filters.py` (e.g. `fetch_filtered_deals(registry, ...)`) and import it from `tools/analytics.py`. v1 implementation note for the agent: it's acceptable to just call the registered tool function via a re-export, or duplicate the small loop — the agent picks whichever is cleaner.
- **Date filter:** apply in memory on `add_time` for the deal-set selection (same as A1 does — Pipedrive's API-level start_date/end_date filters by update_time which is misleading). For B2 lost reasons, also accept date filter on `lost_time`, applied in memory.
- **Output shape:** dict (not list). Each tool returns a structured dict with `overall` summary + optional `by_<dim>` breakdown when a `group_by` parameter is provided.
- **No `include_fields`.** Analytics tools return computed aggregates, not deal lists. Their output shape is fixed per spec.

## B1 — `get_conversion_rates`

```python
async def get_conversion_rates(
    nucleo: str | None = None,
    portfolio: list[str] | None = None,
    canal: str | None = None,
    setor: str | None = None,
    cn_name: str | None = None,
    pipeline: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    group_by: Literal["nucleo", "canal", "owner", "portfolio", None] = None,
) -> dict:
    """
    Compute close-rate and win-rate statistics for deals matching the filters.

    v1 LIMITATION: without per-deal stage history, this tool cannot compute
    stage-to-stage transition rates (e.g. "% of AT-marcada deals that reached
    Proposta"). It can only compute terminal-state ratios.

    Returns:
        {
            "overall": {
                "total":      int,        # all deals matching filters
                "open":       int,
                "won":        int,
                "lost":       int,
                "deleted":    int,
                "close_rate": float | None,  # won / (won + lost), null if won+lost = 0
                "win_rate":   float | None,  # won / total, null if total = 0
                "total_value_won":  float,
                "total_value_lost": float,
            },
            "by_group": {  # present only if group_by != None
                "<group_value>": {<same shape as "overall">},
                ...
            },
            "group_by": "<group_by>" | None,
            "filters_applied": {<echo of filters>},
            "v1_note": "Stage-to-stage transition rates not available in v1 (no event store).",
        }
    """
```

Internal flow:
1. `await registry.ensure_loaded()`
2. Fetch all matching deals using same filter chain as A1 (status="all_not_deleted" by default to capture won + lost + open).
3. Compute overall stats by iterating the deal list once and counting by `status` field.
4. If `group_by` is provided, group deals by the resolved field (`label_names`, `Canal de Entrada`, `owner_name`, `Portfólio`) and compute the same stats per group.
5. Return dict.

## B2 — `get_lost_reasons_analysis`

```python
async def get_lost_reasons_analysis(
    nucleo: str | None = None,
    portfolio: list[str] | None = None,
    canal: str | None = None,
    cn_name: str | None = None,
    pipeline: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    group_by: Literal["owner", "canal", "nucleo", "portfolio", None] = None,
) -> dict:
    """
    Aggregate lost reasons across deals with status=lost matching the filters.

    Date filter applies to lost_time (when the deal was marked lost), not add_time.

    Returns:
        {
            "total_lost": int,
            "total_value_lost": float,
            "by_reason": {
                "<reason_label>": {
                    "count":      int,
                    "percentage": float,    # of total_lost
                    "total_value": float,
                },
                ...
            },
            "by_group": {  # present only if group_by != None
                "<group_value>": {
                    "total_lost": int,
                    "by_reason": {...},
                },
                ...
            },
            "group_by": "<group_by>" | None,
            "filters_applied": {<echo>},
        }
    """
```

Internal flow:
1. `await registry.ensure_loaded()`
2. Force `status="lost"` in the underlying fetch.
3. For period filter, post-filter by `lost_time` (not `add_time`) in memory.
4. For each lost deal, resolve `lost_reason` field (varchar_options) to its label via registry. Aggregate counts.
5. Compute percentages relative to `total_lost`.
6. If `group_by` is provided, repeat aggregation per group.
7. Return dict.

## B3 — `get_owner_activity`

```python
async def get_owner_activity(
    nucleo: str | None = None,
    portfolio: list[str] | None = None,
    canal: str | None = None,
    pipeline: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    owners: list[str] | None = None,  # restrict to specific owners (display names)
) -> dict:
    """
    Per-owner activity snapshot: how many deals each owner holds, broken down by
    status; how many of their open deals are "hot" vs "cold" by Pipedrive UI
    convention; how many tasks they have overdue.

    Definitions:
      - hot: deal has at least one activity due in the future AND not done.
      - cold: deal has no future activity OR the only activities are past-due.
      - overdue: activity with due_date < today AND done = false.

    The tool issues 1 deals call + N activities calls (one per owner's deals
    aggregate, batched via /v1/activities?user_id=...&done=0). Limit total
    activity records fetched at 1000 per owner.

    Returns:
        {
            "by_owner": {
                "<owner_name>": {
                    "deals_total": int,
                    "deals_open": int,
                    "deals_won": int,
                    "deals_lost": int,
                    "hot_count":  int,    # subset of deals_open
                    "cold_count": int,    # subset of deals_open
                    "tasks_overdue": int,
                    "total_value_open": float,
                },
                ...
            },
            "filters_applied": {<echo>},
        }
    """
```

Internal flow:
1. `await registry.ensure_loaded()`
2. Fetch all matching deals (status=all_not_deleted).
3. Group deals by `owner_name`.
4. Optionally filter to only `owners` list (resolve each via `user_id_by_name`; KeyError → ValueError).
5. For each owner group, compute:
   - deals_total, deals_open, deals_won, deals_lost (from `status` field of each deal).
   - total_value_open (sum of `value` where status=open).
6. To compute hot/cold and tasks_overdue, fetch activities via `pd("GET", "activities", params={"user_id": owner_id, "done": 0, "limit": 1000})`. For each open deal, check if any activity exists with `due_date >= today`. Hot = yes; cold = no.
7. `tasks_overdue`: count activities where `due_date < today` and `done=0`, scoped to deals in the matching set.
8. Return dict.

Performance note: this tool can fan out to many API calls (one per owner). v1 cap at 20 owners; raise ValueError if more.

## Module structure

```python
# tools/analytics.py

from __future__ import annotations
from typing import Literal
from datetime import date
from mcp.server.fastmcp import FastMCP
from field_registry import FieldsRegistry
from pipedrive import pd, pd_raw

# Optional: import the helper from A1 if the agent decides to factor it out.
# from tools.list_deals_with_filters import _fetch_filtered_deals

_READ_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def register(mcp: FastMCP, registry: FieldsRegistry) -> None:
    @mcp.tool(name="get_conversion_rates", annotations={"title": "Get Conversion Rates", **_READ_ANNOTATIONS})
    async def get_conversion_rates(...): ...

    @mcp.tool(name="get_lost_reasons_analysis", annotations={"title": "Lost Reasons Analysis", **_READ_ANNOTATIONS})
    async def get_lost_reasons_analysis(...): ...

    @mcp.tool(name="get_owner_activity", annotations={"title": "Owner Activity", **_READ_ANNOTATIONS})
    async def get_owner_activity(...): ...
```

`server.py` adds:
```python
from tools.analytics import register as reg_analytics
reg_analytics(mcp, registry)
```

## Test plan

**Unit (`tests/unit/test_analytics.py`):** ~15 tests with respx + mock_registry.

- B1: 5 tests — overall stats (no filters), filter by nucleo, group_by=canal, empty result returns zeros, unknown filter value raises.
- B2: 5 tests — overall lost reasons, group_by=owner, percentage adds to 100, date window filters by lost_time not add_time, empty result returns empty by_reason.
- B3: 5 tests — basic per-owner snapshot, owners= filter, hot/cold classification with mocked activities, owners> 20 raises, activities pagination.

**Integration (`tests/integration/test_analytics_real.py`):** ~6 tests.

- B1 real: `get_conversion_rates(nucleo="NDados", start_date="...")` returns sensible shape.
- B1 group_by: returns by_group dict, group keys are real values.
- B2 real: `get_lost_reasons_analysis(nucleo="NDados")` returns by_reason with known reasons.
- B3 real: `get_owner_activity(nucleo="NDados")` returns by_owner with real names.
- Compound: B1 with multiple filters reduces total vs no-filter.
- Unknown filter raises ValueError.
