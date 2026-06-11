"""
Integration tests for B1/B2/B3 — hits the real Pipedrive instance of the PJ via .env.
Skipped automatically when PIPEDRIVE_API_TOKEN is missing.
Assertions are resilient to data drift.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def _call_tool(registry, tool_name, **kwargs):
    from mcp.server.fastmcp import FastMCP
    from tools.analytics import register

    captured: dict[str, object] = {}
    stub = FastMCP("test-stub-analytics-int")
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
    return await captured[tool_name](**kwargs)


# ── B1 ───────────────────────────────────────────────────────────────────────


async def test_real_b1_basic_shape(real_registry):
    result = await _call_tool(real_registry, "get_conversion_rates", nucleo="NDados")
    assert "overall" in result
    o = result["overall"]
    for key in ("total", "open", "won", "lost", "close_rate", "win_rate", "total_value_won", "total_value_lost"):
        assert key in o
    assert isinstance(o["total"], int)
    assert o["total"] >= 0


async def test_real_b1_group_by_canal(real_registry):
    result = await _call_tool(real_registry, "get_conversion_rates", nucleo="NDados", group_by="canal")
    assert "by_group" in result
    assert isinstance(result["by_group"], dict)


async def test_real_b1_unknown_nucleo_raises(real_registry):
    with pytest.raises(ValueError):
        await _call_tool(real_registry, "get_conversion_rates", nucleo="Marciano")


# ── B2 ───────────────────────────────────────────────────────────────────────


async def test_real_b2_basic_shape(real_registry):
    result = await _call_tool(real_registry, "get_lost_reasons_analysis", nucleo="NDados")
    assert "total_lost" in result
    assert "by_reason" in result
    assert isinstance(result["by_reason"], dict)


# ── B3 ───────────────────────────────────────────────────────────────────────


async def test_real_b3_basic_shape(real_registry):
    result = await _call_tool(real_registry, "get_owner_activity", nucleo="NDados")
    assert "by_owner" in result
    assert isinstance(result["by_owner"], dict)
    for owner_name, stats in result["by_owner"].items():
        for key in ("deals_total", "deals_open", "deals_won", "deals_lost", "hot_count", "cold_count", "tasks_overdue", "total_value_open"):
            assert key in stats, f"Missing key {key} for owner {owner_name}"
