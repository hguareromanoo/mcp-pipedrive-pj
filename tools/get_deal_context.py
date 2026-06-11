import asyncio
from mcp.server.fastmcp import FastMCP
from pipedrive import pd
from fields import (
    CANAL_FIELD, PORTFOLIO_FIELD, SETOR_FIELD,
    FUNCIONARIOS_FIELD, LOST_REASON_FIELD, LABEL_FIELD,
    CANAL_OPTIONS, SETOR_OPTIONS, FUNCIONARIOS_OPTIONS,
    PORTFOLIO_OPTIONS, LOST_REASON_OPTIONS, LABEL_OPTIONS,
    resolve_enum, resolve_set,
)


async def _noop():
    return None


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="get_deal_context",
        annotations={
            "title": "Get Full Deal Context",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_deal_context(
        deal_id: int | None = None,
        deal_name: str | None = None,
    ) -> str:
        """
        Returns a full markdown briefing for a Pipedrive deal.

        Combines CRM data (deal, contact, organization, notes, activities).
        Use this before a client meeting, when scoping a project, or to prepare
        a proposal.

        Meeting transcription is intentionally NOT part of this tool — it lives
        in a separate MCP focused on Drive/AssemblyAI. This MCP is purely Pipedrive.

        Provide either deal_id (preferred) or deal_name (triggers a search).
        """
        if deal_id is None and deal_name is None:
            return "Erro: forneça deal_id ou deal_name."

        multiple_warning = ""
        if deal_id is None:
            results = await pd("GET", "deals/search", params={"term": deal_name, "limit": 5})
            items = (results or {}).get("items", [])
            if not items:
                raise ValueError(f"Deal não encontrado: {deal_name}")
            deal_id = items[0]["item"]["id"]
            if len(items) > 1:
                multiple_warning = f"\n*Múltiplos deals encontrados — exibindo: {items[0]['item']['title']}*\n"

        deal = await pd("GET", f"deals/{deal_id}")

        # Extract IDs from nested objects (Pipedrive returns dicts with .value for linked entities)
        def _id(field):
            v = deal.get(field)
            if isinstance(v, dict):
                return v.get("value") or v.get("id")
            return v

        person_id = _id("person_id")
        org_id = _id("org_id")
        pipeline_id = deal.get("pipeline_id")
        stage_id = deal.get("stage_id")
        # owner name is embedded in user_id nested object and also in the convenience field owner_name
        owner_name = deal.get("owner_name") or (deal.get("user_id") or {}).get("name", "[Desconhecido]")

        # Parallel fetch
        person, org, stage, pipeline_data, notes_raw = await asyncio.gather(
            pd("GET", f"persons/{person_id}") if person_id else _noop(),
            pd("GET", f"organizations/{org_id}") if org_id else _noop(),
            pd("GET", f"stages/{stage_id}") if stage_id else _noop(),
            pd("GET", f"pipelines/{pipeline_id}") if pipeline_id else _noop(),
            pd("GET", "notes", params={"deal_id": deal_id, "limit": 50, "sort": "add_time DESC"}),
        )

        activities_raw = await pd("GET", f"deals/{deal_id}/activities")

        notes = notes_raw if isinstance(notes_raw, list) else []
        activities = activities_raw if isinstance(activities_raw, list) else []

        # Resolve enum/set fields
        canal = resolve_enum(CANAL_OPTIONS, deal.get(CANAL_FIELD))
        setor = resolve_enum(SETOR_OPTIONS, deal.get(SETOR_FIELD))
        headcount = resolve_enum(FUNCIONARIOS_OPTIONS, deal.get(FUNCIONARIOS_FIELD))
        portfolio = resolve_set(PORTFOLIO_OPTIONS, deal.get(PORTFOLIO_FIELD))
        labels = resolve_set(LABEL_OPTIONS, deal.get(LABEL_FIELD))
        lost_reason = resolve_enum(LOST_REASON_OPTIONS, deal.get(LOST_REASON_FIELD))
        stage_name = (stage or {}).get("name", f"Etapa {stage_id}")
        pipeline_name = (pipeline_data or {}).get("name", f"Funil {pipeline_id}")

        # Compose markdown
        value_str = f"R$ {deal.get('value'):,.2f}" if deal.get("value") else "—"
        prob = deal.get("probability")
        close_date = deal.get("expected_close_date") or "—"
        status = deal.get("status", "")

        lines = [
            f"# {deal.get('title')} — Contexto Completo",
            multiple_warning,
            f"**Etapa:** {stage_name} | **Funil:** {pipeline_name}",
            f"**Valor:** {value_str} | **Probabilidade:** {prob}%",
            f"**Responsável:** {owner_name} | **Fechamento Previsto:** {close_date}",
            f"**Etiqueta:** {', '.join(labels) if labels else '—'} | **Canal:** {canal}",
            f"**Portfólio:** {' · '.join(portfolio) if portfolio else '—'}",
            "",
            "---",
            "",
        ]

        # Contact
        if person:
            emails = person.get("email") or []
            phones = person.get("phone") or []
            email = emails[0]["value"] if emails else "—"
            phone = phones[0]["value"] if phones else "—"
            lines += [
                "## Contato",
                "",
                f"**Nome:** {person.get('name')} — {person.get('job_title') or '—'}",
                f"**Email:** {email} | **Tel:** {phone}",
                "",
            ]
        else:
            lines += ["## Contato", "", "*Contato não vinculado.*", ""]

        # Organization
        if org:
            lines += [
                "## Empresa",
                "",
                f"**Organização:** {org.get('name')}",
                f"**Setor:** {setor} | **Funcionários:** {headcount}",
                "",
            ]
        else:
            lines += ["## Empresa", "", "*Organização não vinculada.*", ""]

        lines += ["---", ""]

        # Notes
        lines.append("## Notas")
        lines.append("")
        if notes:
            for note in notes:
                user_name = (note.get("user") or {}).get("name", "—")
                add_time = (note.get("add_time") or "")[:10]
                lines.append(f"### [{add_time}] {user_name}")
                lines.append(note.get("content", ""))
                lines.append("")
        else:
            lines.append("*(Sem notas registradas.)*")
            lines.append("")

        lines += ["---", ""]

        # Activities
        lines.append("## Atividades")
        lines.append("")
        if activities:
            lines.append("| Data | Tipo | Assunto | Status |")
            lines.append("|------|------|---------|--------|")
            for act in activities:
                status_icon = "✅ Feita" if act.get("done") else "🔲 Pendente"
                lines.append(
                    f"| {act.get('due_date') or '—'} "
                    f"| {act.get('type') or '—'} "
                    f"| {act.get('subject') or '—'} "
                    f"| {status_icon} |"
                )
        else:
            lines.append("*(Sem atividades registradas.)*")
        lines.append("")

        if status == "lost":
            lines += ["---", f"*— Motivo da Perda: {lost_reason}*"]

        return "\n".join(lines)
