"""
Integration tests for A1 list_deals_with_filters — hits the real Pipedrive
instance of the Poli Júnior using PIPEDRIVE_API_TOKEN from .env.

Skipped automatically when token is missing (see tests/conftest.py).
Assertions are resilient to data drift: structural (returned list is well-formed,
filters reduce counts, custom fields resolve to labels) rather than value-exact.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


# ── Helper to call the tool ──────────────────────────────────────────────────


async def _call_tool(registry, **kwargs):
    from mcp.server.fastmcp import FastMCP
    from tools.list_deals_with_filters import register

    captured = {}
    stub = FastMCP("test-stub-int")
    original_tool = stub.tool

    def capturing_tool(*a, **kw):
        decorator = original_tool(*a, **kw)

        def wrapper(fn):
            captured["fn"] = fn
            return decorator(fn)

        return wrapper

    stub.tool = capturing_tool
    register(stub, registry)
    return await captured["fn"](**kwargs)


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_real_api_list_open_deals_small_limit(real_registry):
    """Returns a well-formed list; respects limit; default subset shape."""
    result = await _call_tool(real_registry, status="open", limit=5)
    assert isinstance(result, list)
    assert len(result) <= 5
    if result:
        expected_keys = {
            "id", "title", "value", "currency", "stage_name", "pipeline_name",
            "owner_name", "status", "label_names", "add_time", "update_time",
        }
        assert set(result[0].keys()) == expected_keys


async def test_real_api_filter_by_nucleo_NDados(real_registry):
    """All returned deals have NDados in label_names."""
    result = await _call_tool(real_registry, nucleo="NDados", limit=10)
    assert isinstance(result, list)
    for deal in result:
        assert "NDados" in deal["label_names"], (
            f"Deal {deal['id']} returned but label_names={deal['label_names']}"
        )


async def test_real_api_filter_by_period_recent(real_registry):
    """All returned deals have add_time within the requested window."""
    end = date.today()
    start = end - timedelta(days=90)
    result = await _call_tool(
        real_registry,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        limit=10,
    )
    assert isinstance(result, list)
    for deal in result:
        # add_time format is "YYYY-MM-DD HH:MM:SS"
        deal_date = deal["add_time"][:10]
        assert start.isoformat() <= deal_date <= end.isoformat(), (
            f"Deal {deal['id']} add_time={deal['add_time']} outside window"
        )


async def test_real_api_include_fields_exact_keys(real_registry):
    """include_fields filters output to exactly those keys, nothing more."""
    result = await _call_tool(
        real_registry,
        include_fields=["title", "value", "Setor da Empresa"],
        limit=3,
    )
    assert isinstance(result, list)
    for deal in result:
        assert set(deal.keys()) == {"title", "value", "Setor da Empresa"}


async def test_real_api_include_fields_resolves_custom_to_label(real_registry):
    """A custom field (Setor da Empresa) returns a human-readable label, not a hash or int."""
    result = await _call_tool(
        real_registry,
        include_fields=["title", "Setor da Empresa"],
        limit=5,
    )
    for deal in result:
        setor = deal["Setor da Empresa"]
        if setor is None or setor == "":
            continue
        assert isinstance(setor, str), f"Setor da Empresa returned non-string: {setor!r}"
        # Should not look like a hash or pure int
        assert not setor.isdigit(), f"Setor da Empresa looks like an unresolved ID: {setor!r}"


async def test_real_api_unknown_nucleo_raises_helpful_error(real_registry):
    """Unknown núcleo name raises ValueError with valid options in the message."""
    with pytest.raises(ValueError) as exc:
        await _call_tool(real_registry, nucleo="Marciano")
    msg = str(exc.value)
    assert any(n in msg for n in ["NDados", "NCiv", "NCon", "NTec", "WI", "NI"]), (
        f"Error message did not list valid núcleos: {msg}"
    )


async def test_real_api_compound_filter_reduces_count(real_registry):
    """Adding a filter never increases the result count."""
    base = await _call_tool(real_registry, status="open", limit=100)
    filtered = await _call_tool(real_registry, status="open", nucleo="NDados", limit=100)
    assert len(filtered) <= len(base), (
        f"Adding nucleo filter increased count: {len(base)} → {len(filtered)}"
    )


async def test_real_api_pagination_works(real_registry):
    """Requesting more than one page worth of deals exercises pagination logic."""
    # Just verify the call doesn't blow up with a larger limit and returns a list.
    result = await _call_tool(real_registry, limit=150)
    assert isinstance(result, list)
    assert len(result) <= 150
