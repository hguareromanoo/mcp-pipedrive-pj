"""
Integration tests for A4 base_gets — hits the real Pipedrive instance of the
Poli Júnior via PIPEDRIVE_API_TOKEN in .env.

Skipped automatically when token is missing (see tests/conftest.py).
Strategy:
  - Pure registry-read tools (list_pipelines/stages/users): assert non-empty
    structural shape.
  - API-call tools (get_person/get_organization/get_notes/get_activities):
    discover a real ID first via list_deals_with_filters, then use it.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def _call_tool(registry, tool_name, **kwargs):
    from mcp.server.fastmcp import FastMCP
    from tools.base_gets import register

    captured: dict[str, object] = {}
    stub = FastMCP("test-stub-base-gets-int")
    original_tool = stub.tool

    def capturing_tool(*a, **kw):
        decorator = original_tool(*a, **kw)
        name = kw.get("name") or (a[0] if a else None)

        def wrapper(fn):
            captured[name] = fn
            return decorator(fn)

        return wrapper

    stub.tool = capturing_tool
    register(stub, registry)
    fn = captured.get(tool_name)
    assert fn is not None
    return await fn(**kwargs)


async def _pick_first_deal_with(real_registry, **filters):
    """Helper: use list_deals_with_filters to find a real deal matching filters."""
    from mcp.server.fastmcp import FastMCP
    from tools.list_deals_with_filters import register as reg_list

    captured: dict[str, object] = {}
    stub = FastMCP("test-helper")
    original_tool = stub.tool

    def capturing_tool(*a, **kw):
        decorator = original_tool(*a, **kw)

        def wrapper(fn):
            captured["fn"] = fn
            return decorator(fn)

        return wrapper

    stub.tool = capturing_tool
    reg_list(stub, real_registry)
    result = await captured["fn"](limit=5, **filters)
    return result


# ── Registry-only tools ──────────────────────────────────────────────────────


async def test_real_list_pipelines_non_empty(real_registry):
    result = await _call_tool(real_registry, "list_pipelines")
    assert isinstance(result, list)
    assert len(result) > 0
    assert {"id", "name"}.issubset(set(result[0].keys()))


async def test_real_list_stages_non_empty(real_registry):
    result = await _call_tool(real_registry, "list_stages")
    assert isinstance(result, list)
    assert len(result) > 0
    assert {"id", "name", "pipeline_id", "pipeline_name"}.issubset(set(result[0].keys()))


async def test_real_list_stages_filtered_by_known_pipeline(real_registry):
    pipelines = await _call_tool(real_registry, "list_pipelines")
    first_pipeline_name = pipelines[0]["name"]
    result = await _call_tool(real_registry, "list_stages", pipeline=first_pipeline_name)
    assert isinstance(result, list)
    assert all(s["pipeline_name"] == first_pipeline_name for s in result)


async def test_real_list_users_non_empty(real_registry):
    result = await _call_tool(real_registry, "list_users")
    assert isinstance(result, list)
    assert len(result) > 0
    assert {"id", "name"}.issubset(set(result[0].keys()))


# ── API-call tools (use real deal to discover IDs) ──────────────────────────


async def test_real_get_notes_for_deal(real_registry):
    deals = await _pick_first_deal_with(real_registry, status="open")
    if not deals:
        pytest.skip("No open deals in the PJ instance; cannot exercise get_notes.")
    deal_id = deals[0]["id"]
    result = await _call_tool(real_registry, "get_notes", deal_id=deal_id)
    assert isinstance(result, list)
    # Notes list may be empty for a deal — that's a valid result. Just verify shape.
    for note in result:
        assert {"id", "content", "add_time", "user_name"}.issubset(set(note.keys()))


async def test_real_get_activities_for_deal(real_registry):
    deals = await _pick_first_deal_with(real_registry, status="open")
    if not deals:
        pytest.skip("No open deals in the PJ instance; cannot exercise get_activities.")
    deal_id = deals[0]["id"]
    result = await _call_tool(real_registry, "get_activities", deal_id=deal_id)
    assert isinstance(result, list)
    for act in result:
        assert {"id", "type", "subject", "due_date", "done"}.issubset(set(act.keys()))


async def test_real_get_person_not_found_raises(real_registry):
    with pytest.raises(ValueError):
        await _call_tool(real_registry, "get_person", person_id=999999999)
