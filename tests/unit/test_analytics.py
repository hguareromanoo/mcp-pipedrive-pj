"""
Unit tests for B1/B2/B3 analytics tools — fully mocked via respx.

Spec: plans/B-analytics.md
Implementation: tools/analytics.py
"""
from __future__ import annotations

import httpx
import pytest
import respx

BASE = "https://api.pipedrive.com/v1"


def _envelope(items, more=False, next_start=None):
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
    status: str = "open",
    value: float = 10000,
    owner_name: str = "Henrique Romano",
    label: str = "32",
    canal_id: int = 28,
    portfolio_csv: str = "207",
    setor_id: int = 167,
    add_time: str = "2026-05-01 10:00:00",
    won_time: str | None = None,
    lost_time: str | None = None,
    lost_reason_id: int | None = None,
    hunter_id: int | None = None,
    sdr_id: int | None = None,
    funcionarios_id: int | None = None,
    origem_id: int | None = None,
    suborigem_id: int | None = None,
    stage_id: int = 5,
    pipeline_id: int = 1,
):
    return {
        "id": id,
        "title": f"Deal {id}",
        "value": value,
        "currency": "BRL",
        "status": status,
        "stage_id": stage_id,
        "pipeline_id": pipeline_id,
        "user_id": {"id": 100, "name": owner_name},
        "owner_name": owner_name,
        "label": label,
        "add_time": add_time,
        "update_time": add_time,
        "won_time": won_time,
        "lost_time": lost_time,
        "lost_reason": lost_reason_id,
        "97d0502cc2b489986844a93b374656e5acf179e1": canal_id,
        "e4339ab04542dcd1e1215e4bc17ee2bcf45a9652": portfolio_csv,
        "6ea1ea74da5fbb8cb6a8dd741a96a9bc8b4e379f": setor_id,
        "hunter_hash": hunter_id,
        "sdr_hash": sdr_id,
        "0b2be49fb7615b170878d944a7cb05f6ec8f9e27": funcionarios_id,
        "origin": origem_id,
        "suborigem_hash": suborigem_id,
    }


async def _call_tool(mock_registry, tool_name, **kwargs):
    from mcp.server.fastmcp import FastMCP
    from tools.analytics import register

    captured: dict[str, object] = {}
    stub = FastMCP("test-stub-analytics")
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
    assert fn is not None
    return await fn(**kwargs)


# ── B1 get_conversion_rates ──────────────────────────────────────────────────


@respx.mock
async def test_b1_overall_stats(mock_registry):
    deals = [
        _make_deal(1, status="open", value=10000),
        _make_deal(2, status="open", value=20000),
        _make_deal(3, status="won", value=30000),
        _make_deal(4, status="lost", value=15000),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))

    result = await _call_tool(mock_registry, "get_conversion_rates")
    overall = result["overall"]
    assert overall["total"] == 4
    assert overall["open"] == 2
    assert overall["won"] == 1
    assert overall["lost"] == 1
    assert overall["close_rate"] == 0.5  # 1 / (1+1)
    assert overall["win_rate"] == 0.25   # 1 / 4
    assert overall["total_value_won"] == 30000
    assert overall["total_value_lost"] == 15000


@respx.mock
async def test_b1_filter_by_nucleo(mock_registry):
    deals = [
        _make_deal(1, status="won", label="32"),       # NDados
        _make_deal(2, status="won", label="31"),       # NCiv (filtered out)
        _make_deal(3, status="lost", label="32"),      # NDados
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, "get_conversion_rates", nucleo="NDados")
    assert result["overall"]["total"] == 2
    assert result["overall"]["won"] == 1
    assert result["overall"]["lost"] == 1


@respx.mock
async def test_b1_group_by_canal(mock_registry):
    deals = [
        _make_deal(1, status="won", canal_id=27),    # Inbound
        _make_deal(2, status="won", canal_id=28),    # Outbound
        _make_deal(3, status="lost", canal_id=28),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, "get_conversion_rates", group_by="canal")
    assert "by_group" in result
    assert "Inbound" in result["by_group"]
    assert "Outbound" in result["by_group"]
    assert result["by_group"]["Inbound"]["won"] == 1
    assert result["by_group"]["Outbound"]["won"] == 1
    assert result["by_group"]["Outbound"]["lost"] == 1


@respx.mock
async def test_b1_empty_returns_zeros(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    result = await _call_tool(mock_registry, "get_conversion_rates")
    assert result["overall"]["total"] == 0
    assert result["overall"]["close_rate"] is None
    assert result["overall"]["win_rate"] is None


@respx.mock
async def test_b1_unknown_nucleo_raises(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "get_conversion_rates", nucleo="Marciano")


# ── B2 get_lost_reasons_analysis ─────────────────────────────────────────────


@respx.mock
async def test_b2_overall_lost_reasons(mock_registry):
    deals = [
        _make_deal(1, status="lost", lost_reason_id=15, value=10000),  # Budget
        _make_deal(2, status="lost", lost_reason_id=15, value=20000),  # Budget
        _make_deal(3, status="lost", lost_reason_id=20, value=5000),   # Timing
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, "get_lost_reasons_analysis")
    assert result["total_lost"] == 3
    assert result["total_value_lost"] == 35000
    assert "Budget" in result["by_reason"]
    assert result["by_reason"]["Budget"]["count"] == 2
    assert result["by_reason"]["Timing"]["count"] == 1


@respx.mock
async def test_b2_percentages_sum_to_100(mock_registry):
    deals = [
        _make_deal(1, status="lost", lost_reason_id=15),
        _make_deal(2, status="lost", lost_reason_id=20),
        _make_deal(3, status="lost", lost_reason_id=22),
        _make_deal(4, status="lost", lost_reason_id=22),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, "get_lost_reasons_analysis")
    total_pct = sum(r["percentage"] for r in result["by_reason"].values())
    assert abs(total_pct - 100.0) < 0.01


@respx.mock
async def test_b2_group_by_owner(mock_registry):
    deals = [
        _make_deal(1, status="lost", lost_reason_id=15, owner_name="Henrique Romano"),
        _make_deal(2, status="lost", lost_reason_id=20, owner_name="João Silva"),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, "get_lost_reasons_analysis", group_by="owner")
    assert "by_group" in result
    assert "Henrique Romano" in result["by_group"]
    assert "João Silva" in result["by_group"]


@respx.mock
async def test_b2_empty_returns_empty_by_reason(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    result = await _call_tool(mock_registry, "get_lost_reasons_analysis")
    assert result["total_lost"] == 0
    assert result["by_reason"] == {}


@respx.mock
async def test_b2_date_filters_by_lost_time(mock_registry):
    """Date window applies to lost_time, not add_time."""
    deals = [
        _make_deal(
            1, status="lost", lost_reason_id=15,
            add_time="2025-01-01 00:00:00",   # OLD add_time
            lost_time="2026-05-15 10:00:00",  # within window
        ),
        _make_deal(
            2, status="lost", lost_reason_id=20,
            add_time="2026-05-01 00:00:00",   # within window
            lost_time="2026-07-01 10:00:00",  # OUTSIDE window
        ),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry,
        "get_lost_reasons_analysis",
        start_date="2026-05-01",
        end_date="2026-06-30",
    )
    # Only deal 1 (lost in May 2026) should be counted; deal 2 was lost in July.
    assert result["total_lost"] == 1
    assert "Budget" in result["by_reason"]
    assert "Timing" not in result["by_reason"]


# ── B3 get_owner_activity ────────────────────────────────────────────────────


@respx.mock
async def test_b3_basic_per_owner(mock_registry):
    deals = [
        _make_deal(1, status="open", value=10000, owner_name="Henrique Romano"),
        _make_deal(2, status="won", value=20000, owner_name="Henrique Romano"),
        _make_deal(3, status="open", value=5000, owner_name="João Silva"),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    # Activities endpoint: empty for everyone
    respx.get(f"{BASE}/activities").mock(return_value=httpx.Response(200, json=_envelope([])))

    result = await _call_tool(mock_registry, "get_owner_activity")
    by = result["by_owner"]
    assert "Henrique Romano" in by
    assert by["Henrique Romano"]["deals_total"] == 2
    assert by["Henrique Romano"]["deals_open"] == 1
    assert by["Henrique Romano"]["deals_won"] == 1
    assert by["João Silva"]["deals_total"] == 1


@respx.mock
async def test_b3_owners_filter(mock_registry):
    deals = [
        _make_deal(1, owner_name="Henrique Romano"),
        _make_deal(2, owner_name="João Silva"),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    respx.get(f"{BASE}/activities").mock(return_value=httpx.Response(200, json=_envelope([])))
    result = await _call_tool(mock_registry, "get_owner_activity", owners=["Henrique Romano"])
    assert "Henrique Romano" in result["by_owner"]
    assert "João Silva" not in result["by_owner"]


@respx.mock
async def test_b3_unknown_owner_raises(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "get_owner_activity", owners=["Pessoa Inexistente"])


@respx.mock
async def test_b3_hot_cold_classification(mock_registry):
    """hot = at least one future, not-done activity attached to the deal."""
    deal = _make_deal(1, status="open", owner_name="Henrique Romano")
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([deal])))
    # Activity tied to deal 1, due in the future, not done → hot
    future_activity = {
        "id": 9001,
        "deal_id": 1,
        "type": "call",
        "subject": "Próximo passo",
        "due_date": "2099-01-01",
        "done": False,
    }
    respx.get(f"{BASE}/activities").mock(
        return_value=httpx.Response(200, json=_envelope([future_activity]))
    )

    result = await _call_tool(mock_registry, "get_owner_activity")
    h = result["by_owner"]["Henrique Romano"]
    assert h["hot_count"] == 1
    assert h["cold_count"] == 0


@respx.mock
async def test_b3_more_than_20_owners_raises(mock_registry):
    """Safety cap to avoid fan-out explosion."""
    too_many = [f"Owner {i}" for i in range(25)]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "get_owner_activity", owners=too_many)


# ── New filters across all 3 analytics tools ─────────────────────────────────


@respx.mock
async def test_b1_filter_by_hunter(mock_registry):
    """Conversion rate restricted to deals prospected by a specific hunter."""
    deals = [
        _make_deal(1, status="won", hunter_id=500),
        _make_deal(2, status="lost", hunter_id=500),
        _make_deal(3, status="won", hunter_id=501),  # filtered out
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(mock_registry, "get_conversion_rates", hunter="Hunter A")
    assert result["overall"]["total"] == 2
    assert result["overall"]["won"] == 1
    assert result["overall"]["lost"] == 1


@respx.mock
async def test_b1_filter_by_value_range(mock_registry):
    deals = [
        _make_deal(1, status="won", value=5000),     # below min — excluded
        _make_deal(2, status="won", value=20000),
        _make_deal(3, status="lost", value=80000),
        _make_deal(4, status="won", value=200000),   # above max — excluded
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_conversion_rates", min_value=10000, max_value=100000
    )
    assert result["overall"]["total"] == 2
    assert result["overall"]["won"] == 1


@respx.mock
async def test_b1_filter_by_won_date_window(mock_registry):
    deals = [
        _make_deal(1, status="won", won_time="2026-02-15 10:00:00"),
        _make_deal(2, status="won", won_time="2026-07-15 10:00:00"),  # outside
        _make_deal(3, status="open"),                                  # no won_time → excluded by window
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_conversion_rates",
        won_start_date="2026-01-01", won_end_date="2026-06-30",
    )
    assert result["overall"]["total"] == 1
    assert result["overall"]["won"] == 1


@respx.mock
async def test_b2_filter_by_setor(mock_registry):
    """get_lost_reasons_analysis newly accepts `setor`."""
    deals = [
        _make_deal(1, status="lost", setor_id=167, lost_reason_id=15, lost_time="2026-05-01 10:00"),
        _make_deal(2, status="lost", setor_id=158, lost_reason_id=20, lost_time="2026-05-02 10:00"),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_lost_reasons_analysis",
        setor="Information Technology & Services",
    )
    assert result["total_lost"] == 1
    assert "Budget" in result["by_reason"]
    assert "Timing" not in result["by_reason"]


@respx.mock
async def test_b2_filter_by_hunter(mock_registry):
    deals = [
        _make_deal(1, status="lost", hunter_id=500, lost_reason_id=15, lost_time="2026-05-01 10:00"),
        _make_deal(2, status="lost", hunter_id=501, lost_reason_id=15, lost_time="2026-05-02 10:00"),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_lost_reasons_analysis", hunter="Hunter A"
    )
    assert result["total_lost"] == 1


@respx.mock
async def test_b2_filter_by_min_value(mock_registry):
    deals = [
        _make_deal(1, status="lost", value=5000, lost_reason_id=15, lost_time="2026-05-01 10:00"),
        _make_deal(2, status="lost", value=50000, lost_reason_id=20, lost_time="2026-05-02 10:00"),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_lost_reasons_analysis", min_value=10000
    )
    assert result["total_lost"] == 1
    assert "Timing" in result["by_reason"]


@respx.mock
async def test_b3_filter_by_cn_name(mock_registry):
    """get_owner_activity newly accepts `cn_name` to restrict by API filter."""
    route = respx.get(f"{BASE}/deals").mock(
        return_value=httpx.Response(200, json=_envelope([_make_deal(1)]))
    )
    respx.get(f"{BASE}/activities").mock(
        return_value=httpx.Response(200, json=_envelope([]))
    )
    await _call_tool(mock_registry, "get_owner_activity", cn_name="João Silva")
    # cn_name resolves to user_id=101 and is sent as the API param
    assert "user_id=101" in str(route.calls.last.request.url)


@respx.mock
async def test_b3_filter_by_hunter(mock_registry):
    deals = [
        _make_deal(1, status="open", hunter_id=500),
        _make_deal(2, status="open", hunter_id=501),
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    respx.get(f"{BASE}/activities").mock(return_value=httpx.Response(200, json=_envelope([])))
    result = await _call_tool(mock_registry, "get_owner_activity", hunter="Hunter A")
    # Only 1 deal matches; it's owned by Henrique Romano (default)
    h = result["by_owner"]["Henrique Romano"]
    assert h["deals_total"] == 1
    assert h["deals_open"] == 1


@respx.mock
async def test_b3_filter_unknown_hunter_raises(mock_registry):
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    with pytest.raises(ValueError):
        await _call_tool(mock_registry, "get_owner_activity", hunter="Hunter Inexistente")


# ── B1 multi-step funnel (auto when pipeline is set) ─────────────────────────
# Stage fixtures (tests/conftest.py): pipeline 1 ("Funil Comercial") =
#   id=5 "AT Marcada" (order 1), id=6 "Proposta Apresentada" (order 2),
#   id=7 "Negociação" (order 3).
# Pipeline 2 ("Funil Outbound"): id=10 "AT Marcada" (order 1).
# Funnel formula: count(X) = #won + #lost where current stage order_nr ≥ X.


@respx.mock
async def test_b1_funnel_happy_path(mock_registry):
    """Lost deals park at death stage; counts cascade by order_nr."""
    deals = [
        _make_deal(1, status="lost", stage_id=5),  # lost at AT (order 1)
        _make_deal(2, status="lost", stage_id=6),  # lost at Proposta (order 2)
        _make_deal(3, status="lost", stage_id=7),  # lost at Negociação (order 3)
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_conversion_rates", pipeline="Funil Comercial"
    )
    funnel = result["funnel"]
    # 0 won; lost-at-or-past order 1 = 3, order 2 = 2, order 3 = 1
    assert funnel["stages"] == [
        {"name": "AT Marcada", "count": 3},
        {"name": "Proposta Apresentada", "count": 2},
        {"name": "Negociação", "count": 1},
    ]
    rates = [t["rate"] for t in funnel["transitions"]]
    assert rates == [2 / 3, 1 / 2]


@respx.mock
async def test_b1_funnel_won_counts_in_every_stage(mock_registry):
    """A won deal counts in EVERY stage of the funnel."""
    deals = [
        _make_deal(1, status="won", stage_id=5),   # won (at AT) — counts everywhere
        _make_deal(2, status="lost", stage_id=7),  # lost at Negociação
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_conversion_rates", pipeline="Funil Comercial"
    )
    counts = [s["count"] for s in result["funnel"]["stages"]]
    # won=1 (every stage) + lost-at-or-past order: 1, 1, 1
    assert counts == [2, 2, 2]


@respx.mock
async def test_b1_funnel_open_excluded(mock_registry):
    """Open deals are not counted in funnel (polui)."""
    deals = [
        _make_deal(1, status="open", stage_id=5),  # open — excluded
        _make_deal(2, status="open", stage_id=6),  # open — excluded
        _make_deal(3, status="open", stage_id=7),  # open — excluded
        _make_deal(4, status="won", stage_id=7),   # won
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_conversion_rates", pipeline="Funil Comercial"
    )
    counts = [s["count"] for s in result["funnel"]["stages"]]
    # only the 1 won deal counts
    assert counts == [1, 1, 1]


@respx.mock
async def test_b1_funnel_lost_from_other_pipeline_ignored(mock_registry):
    """A lost deal whose stage is from another pipeline is not in the funnel.
    Safety check — in practice _fetch_filtered_deals filters by pipeline natively."""
    deals = [
        _make_deal(1, status="lost", stage_id=7),    # lost at Negociação (pipe 1)
        _make_deal(2, status="lost", stage_id=10),   # stage 10 = pipe 2 — ignored
    ]
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_conversion_rates", pipeline="Funil Comercial"
    )
    counts = [s["count"] for s in result["funnel"]["stages"]]
    # only the 1 lost in pipeline 1 counts
    assert counts == [1, 1, 1]


@respx.mock
async def test_b1_funnel_zero_denominator_rate_is_none(mock_registry):
    """Empty / all-open dataset → all counts 0 → all rates None."""
    deals = [_make_deal(1, status="open", stage_id=5)]  # open is excluded
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope(deals)))
    result = await _call_tool(
        mock_registry, "get_conversion_rates", pipeline="Funil Comercial"
    )
    counts = [s["count"] for s in result["funnel"]["stages"]]
    assert counts == [0, 0, 0]
    rates = [t["rate"] for t in result["funnel"]["transitions"]]
    assert rates == [None, None]


@respx.mock
async def test_b1_funnel_absent_when_pipeline_not_set(mock_registry):
    """No pipeline → no funnel in response (stages are pipeline-scoped)."""
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([_make_deal(1)])))
    result = await _call_tool(mock_registry, "get_conversion_rates")
    assert "funnel" not in result


@respx.mock
async def test_b1_funnel_transitions_count(mock_registry):
    """N stages in pipeline → N-1 transitions."""
    respx.get(f"{BASE}/deals").mock(return_value=httpx.Response(200, json=_envelope([])))
    result = await _call_tool(
        mock_registry, "get_conversion_rates", pipeline="Funil Comercial"
    )
    # Pipeline 1 fixture has 3 stages → 2 transitions
    assert len(result["funnel"]["stages"]) == 3
    assert len(result["funnel"]["transitions"]) == 2
