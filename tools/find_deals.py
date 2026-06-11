from mcp.server.fastmcp import FastMCP
from pipedrive import pd


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="find_deals",
        annotations={
            "title": "Find Deals in the Pipeline",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def find_deals(
        term: str | None = None,
        status: str | None = None,
        stage_id: int | None = None,
        limit: int = 20,
    ) -> str:
        """
        Search for deals in the Pipedrive pipeline.

        Use this to find a specific deal (by name or organization) or to browse
        the pipeline filtered by status or stage. Returns a compact list with
        enough info to pick the right deal for follow-up actions.

        - term: search string (matches deal title or organization name)
        - status: "open", "won", "lost", or "all_not_deleted" (default: open)
        - stage_id: filter by pipeline stage
        - limit: max results (default 20, max 50)
        """
        limit = min(limit, 50)

        if term:
            data = await pd("GET", "deals/search", params={"term": term, "limit": limit})
            items = (data or {}).get("items", [])
            if not items:
                return f"Nenhum deal encontrado para: **{term}**"

            lines = [f"## Deals encontrados: \"{term}\"", ""]
            for entry in items:
                d = entry["item"]
                org = (d.get("organization") or {}).get("name", "—")
                owner = (d.get("user_id") or {}).get("name", "—")
                stage = (d.get("stage") or {}).get("name", "—")
                value = f"R$ {d['value']:,.2f}" if d.get("value") else "—"
                lines.append(f"**[{d['id']}] {d['title']}**")
                lines.append(f"- Empresa: {org} | Etapa: {stage}")
                lines.append(f"- Valor: {value} | Responsável: {owner} | Status: {d.get('status', '—')}")
                lines.append("")
            return "\n".join(lines)

        # Browse mode — list endpoint
        params: dict = {"limit": limit, "status": status or "open"}
        if stage_id is not None:
            params["stage_id"] = stage_id

        data = await pd("GET", "deals", params=params)
        deals = data if isinstance(data, list) else []

        if not deals:
            return "Nenhum deal encontrado com os filtros aplicados."

        filter_desc = f"status={status or 'open'}"
        if stage_id:
            filter_desc += f", stage_id={stage_id}"

        lines = [f"## Pipeline ({filter_desc})", ""]
        for d in deals:
            org = (d.get("org_id") or {}).get("name", "—")
            owner = (d.get("owner_id") or {}).get("name", "—")
            value = f"R$ {d['value']:,.2f}" if d.get("value") else "—"
            close = d.get("expected_close_date") or "—"
            lines.append(f"**[{d['id']}] {d['title']}**")
            lines.append(f"- Empresa: {org} | Valor: {value} | Fechamento: {close}")
            lines.append(f"- Responsável: {owner} | Status: {d.get('status', '—')}")
            lines.append("")

        return "\n".join(lines)
