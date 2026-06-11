"""
A1 — list_deals_with_filters

See plans/A1-list-deals-with-filters.md for the full spec.
"""
from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from field_registry import FieldsRegistry
from pipedrive import pd_raw


def _csv_to_int_set(raw: Any) -> set[int]:
    """'27,29' or 27 or None → {27, 29} or {27} or set()."""
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


def register(mcp: FastMCP, registry: FieldsRegistry) -> None:
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
        List Pipedrive deals filtering by any combination of business attributes
        (núcleo, portfólio, canal, setor, CN owner, stage, pipeline, status, period).

        Use this whenever the user asks for a slice of the funnel:
        "deals abertos do NDados", "propostas no Outbound em Maio",
        "cards do CN João em Educação", "todos os ganhos no Q1 do NCiv".
        This is the workhorse for any "listar/ver/quais cards..." question.

        Filters by custom fields accept human-readable names, not IDs.
        Unknown values raise ValueError with the valid list embedded.

        Args:
            nucleo: One of "NDados", "NCiv", "NCon", "NTec", "WI", "NI".
            portfolio: List of portfolio names (e.g. ["NDados - DSaaS"]); deal must match at least one.
            canal: One of "Inbound", "Outbound", "Fidelização", "Indicação".
            setor: Setor da Empresa display name (e.g. "Information Technology & Services").
            cn_name: Owner display name (resolved to user_id internally).
            stage: Stage display name (e.g. "AT Marcada").
            pipeline: Pipeline display name (e.g. "Funil Comercial").
            status: "open" | "won" | "lost" | "deleted" | "all_not_deleted" (default).
            start_date / end_date: ISO YYYY-MM-DD; filter by deal add_time.
            include_fields: Subset of fields per deal. Default returns 11 enxuto keys
                (id, title, value, currency, stage_name, pipeline_name, owner_name,
                status, label_names, add_time, update_time). To see custom fields
                like "Setor da Empresa" or "Portfólio", list them here.
            limit: Max deals returned (default 100; cap on aggregate pagination is 5000).

        Returns:
            List of dicts. Each dict has the default subset or the include_fields requested.
            Empty list if no deals match.
        """

        # Step 1 — Ensure schema is loaded
        await registry.ensure_loaded()

        # Step 2 — Resolve filter values to API identifiers
        label_option_id: int | None = None
        portfolio_option_ids: list[int] = []
        canal_option_id: int | None = None
        setor_option_id: int | None = None
        owner_id: int | None = None
        pipeline_id_int: int | None = None
        stage_id_int: int | None = None

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
            if cn_name is not None:
                owner_id = registry.user_id_by_name(cn_name)
            if pipeline is not None:
                pipeline_id_int = None
                for pid, pname in registry._pipelines.items():
                    if pname == pipeline:
                        pipeline_id_int = pid
                        break
                if pipeline_id_int is None:
                    valid = sorted(registry._pipelines.values())
                    raise KeyError(
                        f"Pipeline '{pipeline}' não encontrado. Pipelines válidos: {valid}"
                    )
            if stage is not None:
                stage_id_int = registry.stage_id_by_name(stage, pipeline_id_int)
        except KeyError as e:
            # Re-raise registry KeyErrors as ValueError with helpful message
            raise ValueError(str(e)) from e

        # Step 3 — Build native query params
        params: dict[str, Any] = {"limit": 500, "start": 0}
        if status:
            params["status"] = status
        if owner_id is not None:
            # Pipedrive's /v1/deals filter is `user_id`, not `owner_id`.
            # Using `owner_id` is silently ignored by the API.
            params["user_id"] = owner_id
        if stage_id_int is not None:
            params["stage_id"] = stage_id_int
        if pipeline_id_int is not None:
            params["pipeline_id"] = pipeline_id_int
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        # Step 4 — Paginate
        # Early-termination target: if custom (post-)filters are present we may
        # need to fetch more than `limit` because some will be filtered out.
        # Without custom filters, we can stop as soon as we have `limit` deals.
        has_post_filter = any(
            f is not None
            for f in (nucleo, portfolio, canal, setor, start_date, end_date)
        )
        fetch_target = limit * 5 if has_post_filter else limit

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
            if len(deals) >= fetch_target:
                break
            params["start"] = pg.get("next_start") or (params["start"] + 500)
            if len(deals) > 5000:
                raise RuntimeError(
                    "Pagination exceeded safety cap of 5000 deals; tighten filters."
                )

        # Step 5 — Post-filter custom fields in memory
        canal_key = registry.field_key("deal", "Canal de Entrada") if canal is not None else None
        setor_key = registry.field_key("deal", "Setor da Empresa") if setor is not None else None
        portfolio_key = registry.field_key("deal", "Portfólio") if portfolio is not None else None
        label_key = "label"

        def matches(deal: dict) -> bool:
            if nucleo is not None:
                ids = _csv_to_int_set(deal.get(label_key))
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
            # Pipedrive's /v1/deals start_date/end_date filter by update_time,
            # not add_time. The tool's contract is "filter by add_time", so we
            # apply the date window in memory.
            if start_date is not None or end_date is not None:
                add_time = deal.get("add_time")
                if not add_time:
                    return False
                deal_date = str(add_time)[:10]
                if start_date is not None and deal_date < start_date:
                    return False
                if end_date is not None and deal_date > end_date:
                    return False
            return True

        deals = [d for d in deals if matches(d)]

        # Step 6 — Truncate to limit
        deals = deals[:limit]

        # Step 7 — Serialize each deal
        return [registry.serialize_deal(d, include_fields) for d in deals]
