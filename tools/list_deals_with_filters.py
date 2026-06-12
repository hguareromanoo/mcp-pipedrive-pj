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
        funcionarios: list[str] | None = None,
        origem: str | None = None,
        suborigem: str | None = None,
        cn_name: str | None = None,
        hunter: str | None = None,
        sdr: str | None = None,
        stage: str | None = None,
        pipeline: str | None = None,
        status: Literal["open", "won", "lost", "deleted", "all_not_deleted"] = "all_not_deleted",
        motivo_perda: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        won_start_date: str | None = None,
        won_end_date: str | None = None,
        lost_start_date: str | None = None,
        lost_end_date: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        include_fields: list[str] | None = None,
        limit: int | None = 100,
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
            funcionarios: List of company-size buckets (e.g. ["201-500", "501-1,000"]); deal must match at least one.
            origem: Origem display name (top-level lead source).
            suborigem: Suborigem display name (drill-down of origem).
            cn_name: Owner display name (resolved to user_id internally).
            hunter: Hunter display name (custom enum field — prospector).
            sdr: SDR display name (custom enum field — qualifier).
            stage: Stage display name (e.g. "AT Marcada").
            pipeline: Pipeline display name (e.g. "Funil Comercial").
            status: "open" | "won" | "lost" | "deleted" | "all_not_deleted" (default).
            motivo_perda: Loss reason display name (e.g. "Budget"). Requires status="lost".
            start_date / end_date: ISO YYYY-MM-DD; filter by deal add_time.
            won_start_date / won_end_date: ISO YYYY-MM-DD; filter by won_time
                (when deal was won). Deals without won_time are excluded.
            lost_start_date / lost_end_date: ISO YYYY-MM-DD; filter by lost_time
                (when deal was lost). Deals without lost_time are excluded.
            min_value / max_value: Filter by deal value (BRL). Deals without value are excluded.
            include_fields: Subset of fields per deal. Default returns 11 enxuto keys
                (id, title, value, currency, stage_name, pipeline_name, owner_name,
                status, label_names, add_time, update_time). To see custom fields
                like "Setor da Empresa" or "Portfólio", list them here.
            limit: Max deals returned (default 100). Pass `None` to fetch ALL
                matching deals (no cap). Use with care on broad filters.

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
        funcionarios_option_ids: list[int] = []
        origem_option_id: int | None = None
        suborigem_option_id: int | None = None
        owner_id: int | None = None
        hunter_option_id: int | None = None
        sdr_option_id: int | None = None
        motivo_perda_option_id: int | None = None
        pipeline_id_int: int | None = None
        stage_id_int: int | None = None

        if motivo_perda is not None and status != "lost":
            raise ValueError(
                "motivo_perda só é válido quando status='lost'. "
                f"Status atual: {status!r}."
            )

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
            if motivo_perda is not None:
                motivo_perda_option_id = registry.option_id(
                    "deal", "Motivo da perda", motivo_perda
                )
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
        # Early-termination target: when limit is bounded and post-filters are
        # present we fetch up to 5× limit to compensate for in-memory drops.
        # When limit is None, paginate ALL matching pages (no cap) — per user
        # request "listar all deals".
        has_post_filter = any(
            f is not None
            for f in (
                nucleo, portfolio, canal, setor, funcionarios, origem, suborigem,
                hunter, sdr, motivo_perda,
                start_date, end_date,
                won_start_date, won_end_date, lost_start_date, lost_end_date,
                min_value, max_value,
            )
        )
        fetch_target: int | None
        if limit is None:
            fetch_target = None
        elif has_post_filter:
            fetch_target = limit * 5
        else:
            fetch_target = limit

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
            if not items:
                break
            deals.extend(items)
            pg = (page.get("additional_data") or {}).get("pagination") or {}
            if not pg.get("more_items_in_collection"):
                break
            if fetch_target is not None and len(deals) >= fetch_target:
                break
            next_start = pg.get("next_start")
            if next_start is None:
                break
            params["start"] = next_start
            # Safety cap only when limit is bounded; limit=None is opt-in for full pull.
            if limit is not None and len(deals) > 5000:
                raise RuntimeError(
                    "Pagination exceeded safety cap of 5000 deals; tighten filters or pass limit=None."
                )

        # Step 5 — Post-filter custom fields in memory
        canal_key = registry.field_key("deal", "Canal de Entrada") if canal is not None else None
        setor_key = registry.field_key("deal", "Setor da Empresa") if setor is not None else None
        portfolio_key = registry.field_key("deal", "Portfólio") if portfolio is not None else None
        funcionarios_key = registry.field_key("deal", "Número de Funcionários") if funcionarios is not None else None
        origem_key = registry.field_key("deal", "Origem") if origem is not None else None
        suborigem_key = registry.field_key("deal", "Suborigem") if suborigem is not None else None
        hunter_key = registry.field_key("deal", "Hunter") if hunter is not None else None
        sdr_key = registry.field_key("deal", "SDR") if sdr is not None else None
        motivo_perda_key = registry.field_key("deal", "Motivo da perda") if motivo_perda is not None else None
        label_key = "label"

        def _in_date_window(ts: Any, start: str | None, end: str | None) -> bool:
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
            if motivo_perda is not None and motivo_perda_key is not None:
                if _to_int(deal.get(motivo_perda_key)) != motivo_perda_option_id:
                    return False
            # Pipedrive's /v1/deals start_date/end_date filter by update_time,
            # not add_time. The tool's contract is "filter by add_time", so we
            # apply the date window in memory.
            if start_date is not None or end_date is not None:
                if not _in_date_window(deal.get("add_time"), start_date, end_date):
                    return False
            if won_start_date is not None or won_end_date is not None:
                if not _in_date_window(deal.get("won_time"), won_start_date, won_end_date):
                    return False
            if lost_start_date is not None or lost_end_date is not None:
                if not _in_date_window(deal.get("lost_time"), lost_start_date, lost_end_date):
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

        deals = [d for d in deals if matches(d)]

        # Step 6 — Truncate to limit (None = return all)
        if limit is not None:
            deals = deals[:limit]

        # Step 7 — Serialize each deal
        return [registry.serialize_deal(d, include_fields) for d in deals]
