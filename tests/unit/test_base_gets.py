"""
Unit tests for A4 base_gets — fully mocked via respx.

Spec: plans/A4-base-gets.md
Implementation: tools/base_gets.py

Tests exercise each of the 7 tools directly by capturing them through a stub
FastMCP instance, then injecting a `mock_registry` and mocking the Pipedrive
HTTP layer via respx.
"""
from __future__ import annotations

import httpx
import pytest
import respx

BASE = "https://api.pipedrive.com/v1"


def _envelope(data):
    return {"success": True, "data": data}


async def _call_tool(mock_registry, tool_name, **kwargs):
    """Invoke a named tool from tools.base_gets by capturing the decorated function."""
    from mcp.server.fastmcp import FastMCP
    from tools.base_gets import register

    captured: dict[str, object] = {}
    stub = FastMCP("test-stub-base-gets")
    original_tool = stub.tool

    def capturing_tool(*a, **kw):
        decorator = original_tool(*a, **kw)
        name = kw.get("name") or (a[0] if a else None)

        def wrapper(fn):
            captured[name] = fn
            return decorator(fn)

        return wrapper

    stub.tool = capturing_tool
    register(stub, mock_registry)
    fn = captured.get(tool_name)
    assert fn is not None, f"Tool {tool_name!r} not registered. Registered: {list(captured)}"
    return await fn(**kwargs)


# ── get_person ───────────────────────────────────────────────────────────────


@respx.mock
async def test_get_person_happy_path(mock_registry, sample_person_response):
    respx.get(f"{BASE}/persons/555").mock(
        return_value=httpx.Response(200, json=_envelope(sample_person_response))
    )
    result = await _call_tool(mock_registry, "get_person", person_id=555)
    assert result["id"] == 555
    assert result["name"] == "Ana Cliente"
    assert result["email"] == "ana@cliente.com"
    assert result["phone"] == "+5511999999999"
    assert result["org_name"] == "Cliente X Ltda"
    assert result["job_title"] == "CTO"


@respx.mock
async def test_get_person_not_found_raises(mock_registry):
    respx.get(f"{BASE}/persons/999999").mock(
        return_value=httpx.Response(200, json={"success": True, "data": None})
    )
    with pytest.raises(ValueError) as exc:
        await _call_tool(mock_registry, "get_person", person_id=999999)
    assert "999999" in str(exc.value)


@respx.mock
async def test_get_person_include_fields_subset(mock_registry, sample_person_response):
    respx.get(f"{BASE}/persons/555").mock(
        return_value=httpx.Response(200, json=_envelope(sample_person_response))
    )
    result = await _call_tool(
        mock_registry,
        "get_person",
        person_id=555,
        include_fields=["name", "email"],
    )
    assert set(result.keys()) == {"name", "email"}
    assert result["email"] == "ana@cliente.com"


@respx.mock
async def test_get_person_include_fields_unknown_raises(mock_registry, sample_person_response):
    respx.get(f"{BASE}/persons/555").mock(
        return_value=httpx.Response(200, json=_envelope(sample_person_response))
    )
    with pytest.raises(ValueError):
        await _call_tool(
            mock_registry,
            "get_person",
            person_id=555,
            include_fields=["CampoQueNaoExiste"],
        )


# ── get_organization ─────────────────────────────────────────────────────────


@respx.mock
async def test_get_organization_happy_path(mock_registry, sample_org_response):
    respx.get(f"{BASE}/organizations/777").mock(
        return_value=httpx.Response(200, json=_envelope(sample_org_response))
    )
    result = await _call_tool(mock_registry, "get_organization", org_id=777)
    assert result["id"] == 777
    assert result["name"] == "Cliente X Ltda"
    assert result["address"] == "Av. Paulista, 1000, São Paulo - SP"
    assert result["owner_name"] == "Henrique Romano"


@respx.mock
async def test_get_organization_not_found_raises(mock_registry):
    respx.get(f"{BASE}/organizations/999999").mock(
        return_value=httpx.Response(200, json={"success": True, "data": None})
    )
    with pytest.raises(ValueError) as exc:
        await _call_tool(mock_registry, "get_organization", org_id=999999)
    assert "999999" in str(exc.value)


@respx.mock
async def test_get_organization_include_fields_subset(mock_registry, sample_org_response):
    respx.get(f"{BASE}/organizations/777").mock(
        return_value=httpx.Response(200, json=_envelope(sample_org_response))
    )
    result = await _call_tool(
        mock_registry,
        "get_organization",
        org_id=777,
        include_fields=["name", "address"],
    )
    assert set(result.keys()) == {"name", "address"}


# ── get_notes ────────────────────────────────────────────────────────────────


@respx.mock
async def test_get_notes_by_deal_id(mock_registry, sample_notes_response):
    route = respx.get(f"{BASE}/notes").mock(
        return_value=httpx.Response(200, json=_envelope(sample_notes_response))
    )
    result = await _call_tool(mock_registry, "get_notes", deal_id=1234)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["id"] == 9001
    assert result[0]["user_name"] == "Henrique Romano"
    assert "deal_id=1234" in str(route.calls.last.request.url)


@respx.mock
async def test_get_notes_by_person_id(mock_registry, sample_notes_response):
    route = respx.get(f"{BASE}/notes").mock(
        return_value=httpx.Response(200, json=_envelope(sample_notes_response))
    )
    await _call_tool(mock_registry, "get_notes", person_id=555)
    assert "person_id=555" in str(route.calls.last.request.url)


async def test_get_notes_no_id_raises(mock_registry):
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "get_notes")


async def test_get_notes_multiple_ids_raises(mock_registry):
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "get_notes", deal_id=1, person_id=2)


@respx.mock
async def test_get_notes_empty(mock_registry):
    respx.get(f"{BASE}/notes").mock(
        return_value=httpx.Response(200, json={"success": True, "data": None})
    )
    result = await _call_tool(mock_registry, "get_notes", deal_id=1234)
    assert result == []


# ── get_activities ───────────────────────────────────────────────────────────


@respx.mock
async def test_get_activities_by_deal_id_uses_deal_endpoint(
    mock_registry, sample_activities_response
):
    route = respx.get(f"{BASE}/deals/1234/activities").mock(
        return_value=httpx.Response(200, json=_envelope(sample_activities_response))
    )
    result = await _call_tool(mock_registry, "get_activities", deal_id=1234)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["subject"] == "Apresentação de Proposta"
    assert result[0]["done"] is False
    assert route.call_count == 1


@respx.mock
async def test_get_activities_by_person_id_uses_activities_endpoint(
    mock_registry, sample_activities_response
):
    route = respx.get(f"{BASE}/activities").mock(
        return_value=httpx.Response(200, json=_envelope(sample_activities_response))
    )
    await _call_tool(mock_registry, "get_activities", person_id=555)
    assert route.call_count == 1
    assert "person_id=555" in str(route.calls.last.request.url)


@respx.mock
async def test_get_activities_done_filter_pass_through(
    mock_registry, sample_activities_response
):
    route = respx.get(f"{BASE}/deals/1234/activities").mock(
        return_value=httpx.Response(200, json=_envelope(sample_activities_response))
    )
    await _call_tool(mock_registry, "get_activities", deal_id=1234, done=True)
    url = str(route.calls.last.request.url)
    assert "done=1" in url or "done=true" in url.lower()


async def test_get_activities_no_id_raises(mock_registry):
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "get_activities")


# ── list_pipelines ───────────────────────────────────────────────────────────


async def test_list_pipelines_returns_sorted_list(mock_registry):
    result = await _call_tool(mock_registry, "list_pipelines")
    assert isinstance(result, list)
    assert len(result) == 2
    # Each item has id and name
    assert {"id", "name"}.issubset(set(result[0].keys()))
    # Sorted by id ascending
    ids = [p["id"] for p in result]
    assert ids == sorted(ids)


# ── list_stages ──────────────────────────────────────────────────────────────


async def test_list_stages_all(mock_registry):
    result = await _call_tool(mock_registry, "list_stages")
    assert isinstance(result, list)
    assert len(result) == 4  # 4 stages in the fixture
    item = result[0]
    assert {"id", "name", "pipeline_id", "pipeline_name", "order_nr"}.issubset(set(item.keys()))


async def test_list_stages_filtered_by_pipeline(mock_registry):
    result = await _call_tool(mock_registry, "list_stages", pipeline="Funil Comercial")
    assert isinstance(result, list)
    assert all(s["pipeline_name"] == "Funil Comercial" for s in result)
    assert len(result) == 3


async def test_list_stages_unknown_pipeline_raises(mock_registry):
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "list_stages", pipeline="Funil Inexistente")


# ── list_users ───────────────────────────────────────────────────────────────


async def test_list_users_returns_sorted_by_name(mock_registry):
    result = await _call_tool(mock_registry, "list_users")
    assert isinstance(result, list)
    assert len(result) == 3
    names = [u["name"] for u in result]
    assert names == sorted(names)
    assert {"id", "name"}.issubset(set(result[0].keys()))
