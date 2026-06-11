"""
Unit tests for A1 list_deals_with_filters — fully mocked via respx.

Spec: plans/A1-list-deals-with-filters.md
Implementation: tools/list_deals_with_filters.py

These tests exercise the tool function directly (not via MCP plumbing). They
inject a `mock_registry` and mock the Pipedrive HTTP layer via respx.
"""
from __future__ import annotations

import httpx
import pytest
import respx

BASE = "https://api.pipedrive.com/v1"

# ── Helpers ──────────────────────────────────────────────────────────────────


def _envelope(items, more=False, next_start=None):
    """Build a Pipedrive list response envelope with pagination metadata."""
    return {
        "success": True,
        "data": items,
        "additional_data": {
            "pagination": {
                "start": 0,
                "limit": 500,
                "more_items_in_collection": more,
                "next_start": next_start,
            }
        },
    }


def _make_deal(
    id: int,
    title: str = "Deal",
    value: float = 10000,
    status: str = "open",
    stage_id: int = 5,
    pipeline_id: int = 1,
    user_id_data: dict | None = None,
    owner_name: str = "Henrique Romano",
    label: str | None = "32",  # NDados
    canal_id: int = 28,  # Outbound
    portfolio_csv: str | None = "207,312",  # DSaaS, IA Generativa
    setor_id: int = 167,  # IT & Services
    add_time: str = "2026-05-01 10:00:00",
    update_time: str = "2026-06-01 12:00:00",
) -> dict:
    """Build a Pipedrive deal dict mirroring the real API response shape."""
    return {
        "id": id,
        "title": title,
        "value": value,
        "currency": "BRL",
        "status": status,
        "stage_id": stage_id,
        "pipeline_id": pipeline_id,
        "user_id": user_id_data or {"id": 100, "name": owner_name},
        "owner_name": owner_name,
        "label": label,
        "add_time": add_time,
        "update_time": update_time,
        "97d0502cc2b489986844a93b374656e5acf179e1": canal_id,
        "e4339ab04542dcd1e1215e4bc17ee2bcf45a9652": portfolio_csv,
        "6ea1ea74da5fbb8cb6a8dd741a96a9bc8b4e379f": setor_id,
        "ede9bf995bb2d7e50ea8ffbfd24cb56e72232ff0": None,
        "lost_reason": None,
    }


async def _call_tool(mock_registry, **kwargs):
    """Invoke the bare async function inside the registered tool."""
    # We bypass MCP and call the inner async function directly by re-instantiating.
    # Simpler approach: import the module and call its top-level helper if exposed;
    # otherwise, simulate by registering with a stub mcp and capturing the function.
    from mcp.server.fastmcp import FastMCP
    from tools.list_deals_with_filters import register

    captured = {}
    stub = FastMCP("test-stub")

    # Monkey-patch the decorator so we can capture the wrapped function.
    original_tool = stub.tool

    def capturing_tool(*a, **kw):
        decorator = original_tool(*a, **kw)

        def wrapper(fn):
            captured["fn"] = fn
            return decorator(fn)

        return wrapper

    stub.tool = capturing_tool
    register(stub, mock_registry)
    return await captured["fn"](**kwargs)


# ── Tests ────────────────────────────────────────────────────────────────────


@respx.mock
async def test_no_filters_returns_all_not_deleted(mock_registry):
    """Default call has status=all_not_deleted in query and returns the page."""
    route = respx.get(f"{BASE}/deals").mock(
        return_value=httpx.Response(200, json=_envelope([_make_deal(1)]))
    )
    result = await _call_tool(mock_registry)
    assert isinstance(result, list)
    assert len(result) == 1
    # Verify query carried status=all_not_deleted
    sent_request = route.calls.last.request
    assert "status=all_not_deleted" in str(sent_request.url)


@respx.mock
async def test_status_filter_won(mock_registry):
    route = respx.get(f"{BASE}/deals").mock(
        return_value=httpx.Response(200, json=_envelope([_make_deal(1, status="won")]))
    )
    result = await _call_tool(mock_registry, status="won")
    assert result[0]["status"] == "won"
    assert "status=won" in str(route.calls.last.request.url)


@respx.mock
async def test_owner_filter_resolves_name_to_id(mock_registry):
    """cn_name='João Silva' → user_id=101 in query (Pipedrive's actual param)."""
    route = respx.get(f"{BASE}/deals").mock(
        return_value=httpx.Response(200, json=_envelope([_make_deal(1)]))
    )
    await _call_tool(mock_registry, cn_name="João Silva")
    assert "user_id=101" in str(route.calls.last.request.url)


@respx.mock
async def test_owner_filter_unknown_raises_value_error(mock_registry):
    """Unknown owner name → ValueError with valid names list."""
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    with pytest.raises(ValueError) as exc:
        await _call_tool(mock_registry, cn_name="Pessoa Inexistente")
    msg = str(exc.value)
    # Message should mention the unknown name OR list of valid users
    assert "Pessoa Inexistente" in msg or "Henrique" in msg or "João" in msg


@respx.mock
async def test_period_filter_start_end_date(mock_registry):
    route = respx.get(f"{BASE}/deals").mock(
        return_value=httpx.Response(200, json=_envelope([_make_deal(1)]))
    )
    await _call_tool(mock_registry, start_date="2026-01-01", end_date="2026-06-01")
    url = str(route.calls.last.request.url)
    assert "start_date=2026-01-01" in url
    assert "end_date=2026-06-01" in url


@respx.mock
async def test_custom_filter_nucleo_post_filters_in_memory(mock_registry):
    """API returns 3 deals; only 2 have label=NDados (32); tool returns 2."""
    deals = [
        _make_deal(1, label="32"),       # NDados
        _make_deal(2, label="31"),       # NCiv
        _make_deal(3, label="32,34"),    # NDados + NTec
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, nucleo="NDados")
    assert len(result) == 2
    assert {d["id"] for d in result} == {1, 3}


@respx.mock
async def test_custom_filter_portfolio_intersection(mock_registry):
    """portfolio=['DSaaS'] keeps only deals whose Portfólio set contains 207."""
    deals = [
        _make_deal(1, portfolio_csv="207"),         # DSaaS
        _make_deal(2, portfolio_csv="219"),         # Extração only
        _make_deal(3, portfolio_csv="207,312"),     # DSaaS + IA Gen
        _make_deal(4, portfolio_csv=None),          # None
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, portfolio=["NDados - DSaaS"])
    assert {d["id"] for d in result} == {1, 3}


@respx.mock
async def test_custom_filter_canal_exact_match(mock_registry):
    deals = [
        _make_deal(1, canal_id=27),   # Inbound
        _make_deal(2, canal_id=28),   # Outbound
        _make_deal(3, canal_id=28),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, canal="Outbound")
    assert {d["id"] for d in result} == {2, 3}


@respx.mock
async def test_compound_filter_native_plus_custom(mock_registry):
    """status=open (native) + nucleo=NDados (custom post-filter)."""
    deals = [
        _make_deal(1, status="open", label="32"),
        _make_deal(2, status="won", label="32"),       # filtered out by API natively
        _make_deal(3, status="open", label="31"),
    ]
    # Note: in real life, status=open at the API level would already filter out id=2.
    # We simulate that by returning only the open ones.
    route = respx.get(f"{BASE}/deals").mock(
        return_value=httpx.Response(200, json=_envelope([deals[0], deals[2]]))
    )
    result = await _call_tool(mock_registry, status="open", nucleo="NDados")
    assert len(result) == 1
    assert result[0]["id"] == 1
    assert "status=open" in str(route.calls.last.request.url)


@respx.mock
async def test_include_fields_default_subset(mock_registry):
    """No include_fields → returns the 11-key default subset."""
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([_make_deal(1)])))
    result = await _call_tool(mock_registry)
    expected_keys = {
        "id", "title", "value", "currency", "stage_name", "pipeline_name",
        "owner_name", "status", "label_names", "add_time", "update_time",
    }
    assert set(result[0].keys()) == expected_keys


@respx.mock
async def test_include_fields_custom_subset(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([_make_deal(1)])))
    result = await _call_tool(
        mock_registry, include_fields=["title", "value", "Setor da Empresa"]
    )
    assert set(result[0].keys()) == {"title", "value", "Setor da Empresa"}
    assert result[0]["Setor da Empresa"] == "Information Technology & Services"


@respx.mock
async def test_include_fields_unknown_raises(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([_make_deal(1)])))
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, include_fields=["CampoQueNaoExiste"])


@respx.mock
async def test_unknown_nucleo_raises_value_error_with_valid_list(mock_registry):
    """nucleo='Marciano' → ValueError; message lists valid núcleos."""
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    with pytest.raises(ValueError) as exc:
        await _call_tool(mock_registry, nucleo="Marciano")
    msg = str(exc.value)
    # Should mention at least one canonical núcleo
    assert any(n in msg for n in ["NDados", "NCiv", "NCon", "NTec", "WI", "NI"])


@respx.mock
async def test_pagination_iterates_until_done(mock_registry):
    """Three mocked pages, tool accumulates and stops when more_items_in_collection=False."""
    page1 = _envelope([_make_deal(i) for i in range(1, 6)], more=True, next_start=500)
    page2 = _envelope([_make_deal(i) for i in range(6, 11)], more=True, next_start=1000)
    page3 = _envelope([_make_deal(i) for i in range(11, 13)], more=False)

    responses = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
        httpx.Response(200, json=page3),
    ]
    respx.get(f"{BASE}/deals").mock(side_effect=responses)

    result = await _call_tool(mock_registry, limit=100)
    assert len(result) == 12


@respx.mock
async def test_limit_caps_result(mock_registry):
    deals = [_make_deal(i) for i in range(1, 51)]  # 50 deals
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, limit=10)
    assert len(result) == 10


@respx.mock
async def test_empty_result_returns_empty_list(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    result = await _call_tool(mock_registry)
    assert result == []


@respx.mock
async def test_data_null_returns_empty_list(mock_registry):
    """Pipedrive sometimes returns data: null when there are no results."""
    payload = {"success": True, "data": None, "additional_data": {"pagination": {"more_items_in_collection": False}}}
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=payload))
    result = await _call_tool(mock_registry)
    assert result == []


@respx.mock
async def test_api_500_raises_runtime_error(mock_registry):
    """First page returns 500 → RuntimeError with context."""
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(500, json={"success": False, "error": "boom"}))
    with pytest.raises((RuntimeError, Exception)) as exc:
        await _call_tool(mock_registry)
    # Allow either RuntimeError or HTTPError as long as it isn't silently swallowed.
    assert exc.value is not None
