"""
B — Analytics tools (B1, B2, B3).

Three aggregation tools registered together: get_conversion_rates,
get_lost_reasons_analysis, get_owner_activity.

See plans/B-analytics.md for the full spec.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from field_registry import FieldsRegistry
from pipedrive import pd, pd_raw


_READ_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


# ── Shared helpers ──────────────────────────────────────────────────────────


def _csv_to_int_set(raw: Any) -> set[int]:
    if raw is None or raw == "":
        return set()
    if isinstance(raw, int):
        return {raw}
    if isinstance(raw, list):
        out: set[int] = set()
        for x in raw:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
        return out
    return {int(x.strip()) for x in str(raw).split(",") if x.strip()}


def _to_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _resolve_pipeline(registry: FieldsRegistry, pipeline: str) -> int:
    for pid, pname in registry._pipelines.items():
        if pname == pipeline:
            return pid
    valid = sorted(registry._pipelines.values())
    raise KeyError(
        f"Pipeline '{pipeline}' não encontrado. Pipelines válidos: {valid}"
    )


def _lost_reason_field_name(registry: FieldsRegistry) -> str:
    """Return the actual display name used for the lost-reason field in the
    registry. Real Pipedrive instance uses 'Motivo da perda' (lowercase p),
    but tests use 'Motivo da Perda'."""
    for candidate in ("Motivo da Perda", "Motivo da perda"):
        if candidate in registry._deal_fields:
            return candidate
    # Fallback: any name matching case-insensitively
    for name in registry._deal_fields:
        if name.lower() == "motivo da perda":
            return name
    return "Motivo da Perda"


async def _fetch_filtered_deals(
    registry: FieldsRegistry,
    *,
    nucleo: str | None = None,
    portfolio: list[str] | None = None,
    canal: str | None = None,
    setor: str | None = None,
    funcionarios: list[str] | None = None,
    origem: str | None = None,
    suborigem: str | None = None,
    cn_name: str | None = None,
    hunter: str | None = None,
    sdr: str | None = None,
    pipeline: str | None = None,
    status: str = "all_not_deleted",
    start_date: str | None = None,
    end_date: str | None = None,
    date_field: str = "add_time",
    won_start_date: str | None = None,
    won_end_date: str | None = None,
    lost_start_date: str | None = None,
    lost_end_date: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
) -> list[dict]:
    """Fetch deals with the same filter vocabulary as A1.

    Returns raw deal dicts (not serialized). Date window (start_date/end_date)
    is applied in memory on `date_field` (default add_time; B2 uses lost_time).
    Independent won_*/lost_* date windows always apply to won_time/lost_time.
    """
    # Resolve filter values
    label_option_id: int | None = None
    portfolio_option_ids: list[int] = []
    canal_option_id: int | None = None
    setor_option_id: int | None = None
    funcionarios_option_ids: list[int] = []
    origem_option_id: int | None = None
    suborigem_option_id: int | None = None
    owner_id: int | None = None
    hunter_option_id: int | None = None
    sdr_option_id: int | None = None
    pipeline_id_int: int | None = None

    try:
        if nucleo is not None:
            label_option_id = registry.option_id("deal", "Etiqueta", nucleo)
        if portfolio is not None:
            portfolio_option_ids = [
                registry.option_id("deal", "Portfólio", p) for p in portfolio
            ]
        if canal is not None:
            canal_option_id = registry.option_id("deal", "Canal de Entrada", canal)
        if setor is not None:
            setor_option_id = registry.option_id("deal", "Setor da Empresa", setor)
        if funcionarios is not None:
            funcionarios_option_ids = [
                registry.option_id("deal", "Número de Funcionários", f)
                for f in funcionarios
            ]
        if origem is not None:
            origem_option_id = registry.option_id("deal", "Origem", origem)
        if suborigem is not None:
            suborigem_option_id = registry.option_id("deal", "Suborigem", suborigem)
        if cn_name is not None:
            owner_id = registry.user_id_by_name(cn_name)
        if hunter is not None:
            hunter_option_id = registry.option_id("deal", "Hunter", hunter)
        if sdr is not None:
            sdr_option_id = registry.option_id("deal", "SDR", sdr)
        if pipeline is not None:
            pipeline_id_int = _resolve_pipeline(registry, pipeline)
    except KeyError as e:
        raise ValueError(str(e)) from e

    params: dict[str, Any] = {"limit": 500, "start": 0}
    if status:
        params["status"] = status
    if owner_id is not None:
        # Pipedrive's /v1/deals filter is `user_id`, not `owner_id` (the latter
        # is silently ignored by the API).
        params["user_id"] = owner_id
    if pipeline_id_int is not None:
        params["pipeline_id"] = pipeline_id_int

    deals: list[dict] = []
    while True:
        try:
            page = await pd_raw("GET", "deals", params=params)
        except Exception as e:
            raise RuntimeError(
                f"Falha ao buscar página start={params['start']} após acumular "
                f"{len(deals)} deals: {e}"
            ) from e

        items = page.get("data") or []
        deals.extend(items)
        pg = (page.get("additional_data") or {}).get("pagination") or {}
        if not pg.get("more_items_in_collection"):
            break
        params["start"] = pg.get("next_start") or (params["start"] + 500)
        if len(deals) > 50000:
            raise RuntimeError(
                "Pagination exceeded safety cap of 50000 deals; tighten filters."
            )

    # Post-filter
    canal_key = registry.field_key("deal", "Canal de Entrada") if canal is not None else None
    setor_key = registry.field_key("deal", "Setor da Empresa") if setor is not None else None
    portfolio_key = registry.field_key("deal", "Portfólio") if portfolio is not None else None
    funcionarios_key = registry.field_key("deal", "Número de Funcionários") if funcionarios is not None else None
    origem_key = registry.field_key("deal", "Origem") if origem is not None else None
    suborigem_key = registry.field_key("deal", "Suborigem") if suborigem is not None else None
    hunter_key = registry.field_key("deal", "Hunter") if hunter is not None else None
    sdr_key = registry.field_key("deal", "SDR") if sdr is not None else None

    def _in_window(ts: Any, start: str | None, end: str | None) -> bool:
        if not ts:
            return False
        d = str(ts)[:10]
        if start is not None and d < start:
            return False
        if end is not None and d > end:
            return False
        return True

    def matches(deal: dict) -> bool:
        if nucleo is not None:
            ids = _csv_to_int_set(deal.get("label"))
            if label_option_id not in ids:
                return False
        if portfolio is not None and portfolio_key is not None:
            ids = _csv_to_int_set(deal.get(portfolio_key))
            if not set(portfolio_option_ids) & ids:
                return False
        if canal is not None and canal_key is not None:
            if _to_int(deal.get(canal_key)) != canal_option_id:
                return False
        if setor is not None and setor_key is not None:
            if _to_int(deal.get(setor_key)) != setor_option_id:
                return False
        if funcionarios is not None and funcionarios_key is not None:
            if _to_int(deal.get(funcionarios_key)) not in set(funcionarios_option_ids):
                return False
        if origem is not None and origem_key is not None:
            if _to_int(deal.get(origem_key)) != origem_option_id:
                return False
        if suborigem is not None and suborigem_key is not None:
            if _to_int(deal.get(suborigem_key)) != suborigem_option_id:
                return False
        if hunter is not None and hunter_key is not None:
            if _to_int(deal.get(hunter_key)) != hunter_option_id:
                return False
        if sdr is not None and sdr_key is not None:
            if _to_int(deal.get(sdr_key)) != sdr_option_id:
                return False
        if start_date is not None or end_date is not None:
            if not _in_window(deal.get(date_field), start_date, end_date):
                return False
        if won_start_date is not None or won_end_date is not None:
            if not _in_window(deal.get("won_time"), won_start_date, won_end_date):
                return False
        if lost_start_date is not None or lost_end_date is not None:
            if not _in_window(deal.get("lost_time"), lost_start_date, lost_end_date):
                return False
        if min_value is not None or max_value is not None:
            v = deal.get("value")
            if v is None or v == "":
                return False
            try:
                vf = float(v)
            except (TypeError, ValueError):
                return False
            if min_value is not None and vf < min_value:
                return False
            if max_value is not None and vf > max_value:
                return False
        return True

    return [d for d in deals if matches(d)]


def _empty_stats() -> dict:
    return {
        "total": 0,
        "open": 0,
        "won": 0,
        "lost": 0,
        "deleted": 0,
        "close_rate": None,
        "win_rate": None,
        "total_value_won": 0.0,
        "total_value_lost": 0.0,
    }


def _compute_stats(deals: list[dict]) -> dict:
    stats = _empty_stats()
    for d in deals:
        s = d.get("status")
        stats["total"] += 1
        if s in ("open", "won", "lost", "deleted"):
            stats[s] += 1
        value = d.get("value") or 0
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0
        if s == "won":
            stats["total_value_won"] += value
        elif s == "lost":
            stats["total_value_lost"] += value
    if stats["total"] > 0:
        stats["win_rate"] = stats["won"] / stats["total"]
    if (stats["won"] + stats["lost"]) > 0:
        stats["close_rate"] = stats["won"] / (stats["won"] + stats["lost"])
    return stats


def _group_keys_for_deal(
    deal: dict,
    group_by: str,
    registry: FieldsRegistry,
) -> list[str]:
    """Return one or more group-key strings for a deal under the given dimension."""
    if group_by == "owner":
        return [deal.get("owner_name") or "Sem owner"]
    if group_by == "nucleo":
        ids = _csv_to_int_set(deal.get("label"))
        if not ids:
            return ["Sem etiqueta"]
        labels = [registry.option_label("deal", "Etiqueta", oid) for oid in ids]
        # Join multiple labels with ", " as a single group key per spec
        return [", ".join(sorted(labels))]
    if group_by == "canal":
        canal_key = registry.field_key("deal", "Canal de Entrada")
        cid = _to_int(deal.get(canal_key))
        if cid is None:
            return ["Sem canal"]
        return [registry.option_label("deal", "Canal de Entrada", cid)]
    if group_by == "portfolio":
        portfolio_key = registry.field_key("deal", "Portfólio")
        ids = _csv_to_int_set(deal.get(portfolio_key))
        if not ids:
            return ["Sem portfólio"]
        return [registry.option_label("deal", "Portfólio", oid) for oid in ids]
    return ["Todos"]


def register(mcp: FastMCP, registry: FieldsRegistry) -> None:
    @mcp.tool(
        name="get_conversion_rates",
        annotations={"title": "Get Conversion Rates", **_READ_ANNOTATIONS},
    )
    async def get_conversion_rates(
        nucleo: str | None = None,
        portfolio: list[str] | None = None,
        canal: str | None = None,
        setor: str | None = None,
        funcionarios: list[str] | None = None,
        origem: str | None = None,
        suborigem: str | None = None,
        cn_name: str | None = None,
        hunter: str | None = None,
        sdr: str | None = None,
        pipeline: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        won_start_date: str | None = None,
        won_end_date: str | None = None,
        lost_start_date: str | None = None,
        lost_end_date: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        group_by: Literal["nucleo", "canal", "owner", "portfolio", None] = None,
    ) -> dict:
        """
        Compute close-rate and win-rate statistics for deals matching the filters.

        Use for diagnóstico estratégico: "qual a taxa de conversão do NDados
        no Outbound?", "como o CN João está convertendo em Educação?",
        "win rate da PJ no Q1 vs Q2", "ganho/perda por canal".

        Returns aggregated counts and ratios over the deal set; can optionally
        break down by núcleo / canal / owner / portfólio for comparative views.

        v1 LIMITATION: cannot compute stage-to-stage transition rates (e.g.
        "% que chegou de AT a Proposta") because there's no per-deal stage
        history. Only terminal ratios are available — won/(won+lost) and won/total.

        Args:
            nucleo, portfolio, canal, setor, cn_name, pipeline, start_date,
                end_date: Same vocabulary as list_deals_with_filters.
            group_by: "nucleo" | "canal" | "owner" | "portfolio" | None.
                When set, adds "by_group" breakdown alongside "overall".

        Returns:
            Dict with "overall" {total, open, won, lost, deleted, close_rate,
            win_rate, total_value_won, total_value_lost}, plus optional
            "by_group" with same shape per group key.
        """
        await registry.ensure_loaded()

        deals = await _fetch_filtered_deals(
            registry,
            nucleo=nucleo,
            portfolio=portfolio,
            canal=canal,
            setor=setor,
            funcionarios=funcionarios,
            origem=origem,
            suborigem=suborigem,
            cn_name=cn_name,
            hunter=hunter,
            sdr=sdr,
            pipeline=pipeline,
            status="all_not_deleted",
            start_date=start_date,
            end_date=end_date,
            won_start_date=won_start_date,
            won_end_date=won_end_date,
            lost_start_date=lost_start_date,
            lost_end_date=lost_end_date,
            min_value=min_value,
            max_value=max_value,
        )

        overall = _compute_stats(deals)

        filters_applied = {
            "nucleo": nucleo,
            "portfolio": portfolio,
            "canal": canal,
            "setor": setor,
            "funcionarios": funcionarios,
            "origem": origem,
            "suborigem": suborigem,
            "cn_name": cn_name,
            "hunter": hunter,
            "sdr": sdr,
            "pipeline": pipeline,
            "start_date": start_date,
            "end_date": end_date,
            "won_start_date": won_start_date,
            "won_end_date": won_end_date,
            "lost_start_date": lost_start_date,
            "lost_end_date": lost_end_date,
            "min_value": min_value,
            "max_value": max_value,
        }

        result: dict[str, Any] = {
            "overall": overall,
            "group_by": group_by,
            "filters_applied": filters_applied,
            "v1_note": "Stage-to-stage transition rates not available in v1 (no event store).",
        }

        if group_by is not None:
            grouped: dict[str, list[dict]] = {}
            for d in deals:
                for key in _group_keys_for_deal(d, group_by, registry):
                    grouped.setdefault(key, []).append(d)
            result["by_group"] = {
                key: _compute_stats(ds) for key, ds in grouped.items()
            }

        return result

    @mcp.tool(
        name="get_lost_reasons_analysis",
        annotations={"title": "Lost Reasons Analysis", **_READ_ANNOTATIONS},
    )
    async def get_lost_reasons_analysis(
        nucleo: str | None = None,
        portfolio: list[str] | None = None,
        canal: str | None = None,
        setor: str | None = None,
        funcionarios: list[str] | None = None,
        origem: str | None = None,
        suborigem: str | None = None,
        cn_name: str | None = None,
        hunter: str | None = None,
        sdr: str | None = None,
        pipeline: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        group_by: Literal["owner", "canal", "nucleo", "portfolio", None] = None,
    ) -> dict:
        """
        Aggregate "Motivo da perda" across deals with status=lost matching the filters.

        Use for diagnóstico: "por que estamos perdendo deals no Outbound?",
        "qual motivo de perda mais comum no NDados em Q1?", "perdas do CN João
        por motivo".

        Date window applies to lost_time (when the deal was marked lost), NOT
        add_time — this is the right semantic for "perdas em maio" type questions.

        Args:
            nucleo, portfolio, canal, cn_name, pipeline, start_date, end_date:
                Same vocabulary as list_deals_with_filters.
            group_by: "owner" | "canal" | "nucleo" | "portfolio" | None.

        Returns:
            Dict with total_lost, total_value_lost, by_reason
            {<reason_label>: {count, percentage, total_value}}, plus optional
            by_group breakdown when group_by is set.
        """
        await registry.ensure_loaded()

        deals = await _fetch_filtered_deals(
            registry,
            nucleo=nucleo,
            portfolio=portfolio,
            canal=canal,
            setor=setor,
            funcionarios=funcionarios,
            origem=origem,
            suborigem=suborigem,
            cn_name=cn_name,
            hunter=hunter,
            sdr=sdr,
            pipeline=pipeline,
            status="lost",
            start_date=start_date,
            end_date=end_date,
            date_field="lost_time",
            min_value=min_value,
            max_value=max_value,
        )

        lost_reason_field = _lost_reason_field_name(registry)

        def reason_label(deal: dict) -> str:
            raw = deal.get("lost_reason")
            if raw is None or raw == "":
                return "Sem motivo registrado"
            try:
                oid = int(raw)
            except (TypeError, ValueError):
                return str(raw)
            return registry.option_label("deal", lost_reason_field, oid)

        def reason_value(deal: dict) -> float:
            v = deal.get("value") or 0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        def aggregate(ds: list[dict]) -> dict:
            total_lost = len(ds)
            total_value_lost = sum(reason_value(d) for d in ds)
            by_reason: dict[str, dict] = {}
            for d in ds:
                label = reason_label(d)
                entry = by_reason.setdefault(
                    label, {"count": 0, "percentage": 0.0, "total_value": 0.0}
                )
                entry["count"] += 1
                entry["total_value"] += reason_value(d)
            for label, entry in by_reason.items():
                if total_lost > 0:
                    entry["percentage"] = round(entry["count"] / total_lost * 100, 2)
                else:
                    entry["percentage"] = 0.0
            return {
                "total_lost": total_lost,
                "total_value_lost": total_value_lost,
                "by_reason": by_reason,
            }

        overall = aggregate(deals)

        filters_applied = {
            "nucleo": nucleo,
            "portfolio": portfolio,
            "canal": canal,
            "setor": setor,
            "funcionarios": funcionarios,
            "origem": origem,
            "suborigem": suborigem,
            "cn_name": cn_name,
            "hunter": hunter,
            "sdr": sdr,
            "pipeline": pipeline,
            "start_date": start_date,
            "end_date": end_date,
            "min_value": min_value,
            "max_value": max_value,
        }

        result: dict[str, Any] = {
            "total_lost": overall["total_lost"],
            "total_value_lost": overall["total_value_lost"],
            "by_reason": overall["by_reason"],
            "group_by": group_by,
            "filters_applied": filters_applied,
        }

        if group_by is not None:
            grouped: dict[str, list[dict]] = {}
            for d in deals:
                for key in _group_keys_for_deal(d, group_by, registry):
                    grouped.setdefault(key, []).append(d)
            result["by_group"] = {
                key: {
                    "total_lost": agg["total_lost"],
                    "by_reason": agg["by_reason"],
                }
                for key, agg in ((k, aggregate(v)) for k, v in grouped.items())
            }

        return result

    @mcp.tool(
        name="get_owner_activity",
        annotations={"title": "Owner Activity", **_READ_ANNOTATIONS},
    )
    async def get_owner_activity(
        nucleo: str | None = None,
        portfolio: list[str] | None = None,
        canal: str | None = None,
        setor: str | None = None,
        funcionarios: list[str] | None = None,
        origem: str | None = None,
        suborigem: str | None = None,
        cn_name: str | None = None,
        hunter: str | None = None,
        sdr: str | None = None,
        pipeline: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        owners: list[str] | None = None,
    ) -> dict:
        """
        Per-owner snapshot of pipeline state: deals owned by status, hot/cold
        classification, overdue tasks, total open value.

        Use for accomps: "como está o desempenho do CN João?", "quem tem mais
        cards stuck no funil?", "quem tem tasks atrasadas?", "matriz de
        atividade por owner no NDados".

        Definitions:
          - hot: open deal has at least one activity due in the future AND not done.
          - cold: open deal AND not hot (no future activity, or last activity is past-due done).
          - overdue: activity with due_date < today AND done = False, scoped to deals in the set.

        Performs 1 deals fetch + N activities fetches (one per owner). Cap of 20
        owners per call to avoid fan-out explosion.

        Args:
            nucleo, portfolio, canal, pipeline, start_date, end_date: filters.
            owners: List of owner display names to restrict to (resolved via
                registry). Unknown names raise ValueError. If None, returns
                stats for every owner that has at least one matching deal.

        Returns:
            Dict with by_owner {<owner_name>: {deals_total, deals_open,
            deals_won, deals_lost, hot_count, cold_count, tasks_overdue,
            total_value_open}}.
        """
        await registry.ensure_loaded()

        # Cap check must come BEFORE user_id resolution per spec.
        if owners is not None and len(owners) > 20:
            raise ValueError(
                f"Máximo 20 owners por chamada (recebidos {len(owners)})."
            )

        # Resolve owner names to IDs (for filter restriction)
        allowed_names: set[str] | None = None
        if owners is not None:
            try:
                for name in owners:
                    registry.user_id_by_name(name)
            except KeyError as e:
                raise ValueError(str(e)) from e
            allowed_names = set(owners)

        deals = await _fetch_filtered_deals(
            registry,
            nucleo=nucleo,
            portfolio=portfolio,
            canal=canal,
            setor=setor,
            funcionarios=funcionarios,
            origem=origem,
            suborigem=suborigem,
            cn_name=cn_name,
            hunter=hunter,
            sdr=sdr,
            pipeline=pipeline,
            status="all_not_deleted",
            start_date=start_date,
            end_date=end_date,
            min_value=min_value,
            max_value=max_value,
        )

        # Group deals by owner_name
        by_owner_deals: dict[str, list[dict]] = {}
        for d in deals:
            name = d.get("owner_name") or "Sem owner"
            if allowed_names is not None and name not in allowed_names:
                continue
            by_owner_deals.setdefault(name, []).append(d)

        # If owners list was given, ensure every owner appears (even with 0 deals)
        if allowed_names is not None:
            for name in allowed_names:
                by_owner_deals.setdefault(name, [])

        # Fetch activities once for the whole set, then group by deal_id
        # Use /v1/activities with done=0 to pull open activities. Paginate up to 1000.
        activities: list[dict] = []
        try:
            page = await pd_raw(
                "GET",
                "activities",
                params={"done": 0, "limit": 500, "start": 0},
            )
            activities.extend(page.get("data") or [])
            pg = (page.get("additional_data") or {}).get("pagination") or {}
            # Limit total activities to avoid runaway fetches
            while pg.get("more_items_in_collection") and len(activities) < 1000:
                start = pg.get("next_start") or (len(activities))
                page = await pd_raw(
                    "GET",
                    "activities",
                    params={"done": 0, "limit": 500, "start": start},
                )
                activities.extend(page.get("data") or [])
                pg = (page.get("additional_data") or {}).get("pagination") or {}
        except Exception:
            activities = []

        today = date.today().isoformat()

        # Build deal_id → set of activities for fast lookup
        deal_to_activities: dict[int, list[dict]] = {}
        for a in activities:
            did = a.get("deal_id")
            if did is None:
                continue
            try:
                did_int = int(did)
            except (TypeError, ValueError):
                continue
            deal_to_activities.setdefault(did_int, []).append(a)

        def is_done(a: dict) -> bool:
            d = a.get("done")
            if isinstance(d, bool):
                return d
            try:
                return bool(int(d))
            except (TypeError, ValueError):
                return bool(d)

        by_owner: dict[str, dict] = {}
        for owner_name, owner_deals in by_owner_deals.items():
            deals_total = len(owner_deals)
            deals_open = sum(1 for d in owner_deals if d.get("status") == "open")
            deals_won = sum(1 for d in owner_deals if d.get("status") == "won")
            deals_lost = sum(1 for d in owner_deals if d.get("status") == "lost")
            total_value_open = 0.0
            for d in owner_deals:
                if d.get("status") == "open":
                    v = d.get("value") or 0
                    try:
                        total_value_open += float(v)
                    except (TypeError, ValueError):
                        pass

            # hot/cold/overdue
            hot_count = 0
            cold_count = 0
            tasks_overdue = 0
            owner_deal_ids = {int(d["id"]) for d in owner_deals if d.get("id") is not None}

            for d in owner_deals:
                if d.get("status") != "open":
                    continue
                did = d.get("id")
                try:
                    did_int = int(did)
                except (TypeError, ValueError):
                    cold_count += 1
                    continue
                acts = deal_to_activities.get(did_int, [])
                has_future = False
                for a in acts:
                    if is_done(a):
                        continue
                    due = a.get("due_date")
                    if due and str(due) >= today:
                        has_future = True
                        break
                if has_future:
                    hot_count += 1
                else:
                    cold_count += 1

            # tasks_overdue: count activities (across all deals of this owner)
            # where due_date < today AND not done
            for did_int in owner_deal_ids:
                for a in deal_to_activities.get(did_int, []):
                    if is_done(a):
                        continue
                    due = a.get("due_date")
                    if due and str(due) < today:
                        tasks_overdue += 1

            by_owner[owner_name] = {
                "deals_total": deals_total,
                "deals_open": deals_open,
                "deals_won": deals_won,
                "deals_lost": deals_lost,
                "hot_count": hot_count,
                "cold_count": cold_count,
                "tasks_overdue": tasks_overdue,
                "total_value_open": total_value_open,
            }

        filters_applied = {
            "nucleo": nucleo,
            "portfolio": portfolio,
            "canal": canal,
            "setor": setor,
            "funcionarios": funcionarios,
            "origem": origem,
            "suborigem": suborigem,
            "cn_name": cn_name,
            "hunter": hunter,
            "sdr": sdr,
            "pipeline": pipeline,
            "start_date": start_date,
            "end_date": end_date,
            "min_value": min_value,
            "max_value": max_value,
            "owners": owners,
        }

        return {
            "by_owner": by_owner,
            "filters_applied": filters_applied,
        }
