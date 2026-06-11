"""
A4 — Base read tools (gets básicos).

Seven thin read tools registered together: get_person, get_organization,
get_notes, get_activities, list_pipelines, list_stages, list_users.

See plans/A4-base-gets.md for the full spec.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from field_registry import FieldsRegistry
from pipedrive import pd


_READ_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

PERSON_DEFAULT_KEYS = ["id", "name", "job_title", "email", "phone", "org_name"]
ORG_DEFAULT_KEYS = ["id", "name", "address", "owner_name"]


def _first_value(items: Any) -> Any:
    """Extract first 'value' from a list of {value, primary, label} dicts."""
    if not items:
        return None
    if isinstance(items, list):
        first = items[0]
        if isinstance(first, dict):
            return first.get("value")
        return first
    return items


def _nested_name(field: Any) -> str | None:
    """For nested {value, name} or {id, name} dicts, return 'name'."""
    if isinstance(field, dict):
        return field.get("name")
    return None


def _person_default_subset(person: dict) -> dict:
    return {
        "id": person.get("id"),
        "name": person.get("name"),
        "job_title": person.get("job_title"),
        "email": _first_value(person.get("email")),
        "phone": _first_value(person.get("phone")),
        "org_name": _nested_name(person.get("org_id")),
    }


def _org_default_subset(org: dict) -> dict:
    address = org.get("address")
    # Pipedrive returns address either as a string or a structured dict with
    # 'value' as the formatted address.
    if isinstance(address, dict):
        address = address.get("value")
    return {
        "id": org.get("id"),
        "name": org.get("name"),
        "address": address,
        "owner_name": _nested_name(org.get("owner_id")) or org.get("owner_name"),
    }


def _serialize_person(
    person: dict,
    registry: FieldsRegistry,
    include_fields: list[str] | None,
) -> dict:
    """Project a raw Pipedrive person dict to default keys or to the
    caller-specified `include_fields`. Unknown names raise ValueError listing
    valid options (default subset + known person field display names)."""
    default = _person_default_subset(person)
    if include_fields is None:
        return default

    out: dict[str, Any] = {}
    for name in include_fields:
        if name in PERSON_DEFAULT_KEYS:
            out[name] = default[name]
        elif name in registry._person_fields:
            key = registry.field_key("person", name)
            out[name] = person.get(key)
        else:
            valid = PERSON_DEFAULT_KEYS + sorted(registry._person_fields.keys())
            raise ValueError(
                f"Campo '{name}' não é um campo válido para get_person. "
                f"Valores aceitos: {valid}"
            )
    return out


def _serialize_organization(
    org: dict,
    registry: FieldsRegistry,
    include_fields: list[str] | None,
) -> dict:
    """Project a raw Pipedrive organization dict to default keys or to the
    caller-specified `include_fields`. Unknown names raise ValueError listing
    valid options (default subset + known org field display names)."""
    default = _org_default_subset(org)
    if include_fields is None:
        return default

    out: dict[str, Any] = {}
    for name in include_fields:
        if name in ORG_DEFAULT_KEYS:
            out[name] = default[name]
        elif name in registry._org_fields:
            key = registry.field_key("org", name)
            out[name] = org.get(key)
        else:
            valid = ORG_DEFAULT_KEYS + sorted(registry._org_fields.keys())
            raise ValueError(
                f"Campo '{name}' não é um campo válido para get_organization. "
                f"Valores aceitos: {valid}"
            )
    return out


def _exactly_one(**kwargs: Any) -> tuple[str, Any]:
    """Validate exactly one of the kwargs is non-None. Return (name, value)."""
    provided = [(k, v) for k, v in kwargs.items() if v is not None]
    if len(provided) == 0:
        raise ValueError(
            f"Forneça exatamente um dos seguintes: {list(kwargs.keys())}."
        )
    if len(provided) > 1:
        names = [k for k, _ in provided]
        raise ValueError(
            f"Forneça apenas um dos seguintes (recebidos: {names})."
        )
    return provided[0]


def register(mcp: FastMCP, registry: FieldsRegistry) -> None:
    @mcp.tool(name="get_person", annotations={"title": "Get Person", **_READ_ANNOTATIONS})
    async def get_person(
        person_id: int,
        include_fields: list[str] | None = None,
    ) -> dict:
        """
        Fetch a single Pipedrive person (contact) by ID.

        Use when you already have a person_id (typically discovered via
        list_deals_with_filters or get_deal_context) and need contact details:
        nome, cargo, email, telefone, organização.

        This is NOT a search by name — for that, use list_deals_with_filters
        and follow the person_id from the result.

        Args:
            person_id: Pipedrive person ID.
            include_fields: Subset of fields. Default: id, name, job_title, email, phone, org_name.
                Can also request known person field display names (e.g. "Email", "Phone").

        Returns:
            Dict with the requested fields. Raises ValueError if person not found.
        """
        await registry.ensure_loaded()
        try:
            person = await pd("GET", f"persons/{person_id}")
        except Exception as e:
            # Pipedrive returns 404 for unknown IDs which raises in pd().
            raise ValueError(f"Person not found: {person_id}") from e
        if person is None:
            raise ValueError(f"Person not found: {person_id}")
        return _serialize_person(person, registry, include_fields)

    @mcp.tool(name="get_organization", annotations={"title": "Get Organization", **_READ_ANNOTATIONS})
    async def get_organization(
        org_id: int,
        include_fields: list[str] | None = None,
    ) -> dict:
        """
        Fetch a single Pipedrive organization (empresa) by ID.

        Use when you have an org_id (from a deal's org link or from another
        tool) and need the empresa's name, address, or owner.

        NOT a search — for finding orgs by name, use list_deals_with_filters
        and follow the org_id from the result.

        Args:
            org_id: Pipedrive organization ID.
            include_fields: Subset of fields. Default: id, name, address, owner_name.

        Returns:
            Dict with requested fields. Raises ValueError if organization not found.
        """
        await registry.ensure_loaded()
        try:
            org = await pd("GET", f"organizations/{org_id}")
        except Exception as e:
            raise ValueError(f"Organization not found: {org_id}") from e
        if org is None:
            raise ValueError(f"Organization not found: {org_id}")
        return _serialize_organization(org, registry, include_fields)

    @mcp.tool(name="get_notes", annotations={"title": "Get Notes", **_READ_ANNOTATIONS})
    async def get_notes(
        deal_id: int | None = None,
        person_id: int | None = None,
        org_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Fetch notes (commercial commentary) attached to a deal, person, or organization.

        Use when the user wants discussion history or context written by the
        commercial team inside Pipedrive: "como foi a última AT?", "o que o CN
        anotou sobre o card X?", "histórico de conversas com a empresa Y".

        Notes are written by users (CNs, gerentes) and are NOT meeting
        transcriptions — they are short textual updates.

        Returned most recent first.

        Args:
            deal_id / person_id / org_id: Provide EXACTLY ONE of the three.
            limit: Max notes returned (default 50).

        Returns:
            List of {id, content, add_time, user_name}. Empty list if no notes.
            ValueError if none of the IDs (or more than one) is provided.
        """
        name, value = _exactly_one(deal_id=deal_id, person_id=person_id, org_id=org_id)

        params: dict[str, Any] = {
            name: value,
            "limit": limit,
            "sort": "add_time DESC",
        }
        notes = await pd("GET", "notes", params=params)
        if not notes:
            return []
        return [
            {
                "id": n.get("id"),
                "content": n.get("content"),
                "add_time": n.get("add_time"),
                "user_name": (n.get("user") or {}).get("name", "—"),
            }
            for n in notes
        ]

    @mcp.tool(name="get_activities", annotations={"title": "Get Activities", **_READ_ANNOTATIONS})
    async def get_activities(
        deal_id: int | None = None,
        person_id: int | None = None,
        org_id: int | None = None,
        done: bool | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Fetch activities (calls, meetings, tasks) attached to a deal, person, or organization.

        Use when the user wants planned or completed task history:
        "qual a próxima task do card X?", "atividades pendentes do CN João",
        "reuniões já realizadas com a empresa Y", "tem ALG agendado?".

        Activities are the units of work in Pipedrive — distinct from notes
        (which are textual commentary).

        Args:
            deal_id / person_id / org_id: Provide EXACTLY ONE of the three.
            done: True returns only completed; False returns only pending;
                None (default) returns both.
            limit: Max activities returned (default 50).

        Returns:
            List of {id, type, subject, due_date, done, note}. Empty list if no activities.
            ValueError if none of the IDs (or more than one) is provided.
        """
        name, value = _exactly_one(deal_id=deal_id, person_id=person_id, org_id=org_id)

        params: dict[str, Any] = {"limit": limit}
        if done is not None:
            params["done"] = 1 if done else 0

        if name == "deal_id":
            activities = await pd("GET", f"deals/{value}/activities", params=params)
        else:
            params[name] = value
            activities = await pd("GET", "activities", params=params)

        if not activities:
            return []
        return [
            {
                "id": a.get("id"),
                "type": a.get("type"),
                "subject": a.get("subject"),
                "due_date": a.get("due_date"),
                "done": bool(a.get("done")),
                "note": a.get("note"),
            }
            for a in activities
        ]

    @mcp.tool(name="list_pipelines", annotations={"title": "List Pipelines", **_READ_ANNOTATIONS})
    async def list_pipelines() -> list[dict]:
        """
        List all sales pipelines (funis) configured in Pipedrive.

        Use when the user mentions a pipeline by name and you need to know what
        pipelines exist, or as a first step before filtering deals by pipeline.

        Returns:
            List of {id, name}, sorted by id ascending.
        """
        await registry.ensure_loaded()
        items = [{"id": pid, "name": pname} for pid, pname in registry._pipelines.items()]
        return sorted(items, key=lambda x: x["id"])

    @mcp.tool(name="list_stages", annotations={"title": "List Stages", **_READ_ANNOTATIONS})
    async def list_stages(pipeline: str | None = None) -> list[dict]:
        """
        List all stages (etapas) in Pipedrive, optionally filtered by pipeline.

        Use when the user mentions a stage name and you need to verify which
        pipeline it belongs to (some stage names like "AT Marcada" repeat
        across pipelines), or to enumerate stages of a specific pipeline.

        Args:
            pipeline: Pipeline display name (e.g. "Funil Comercial"). If None,
                returns stages of all pipelines. Unknown name raises ValueError.

        Returns:
            List of {id, name, pipeline_id, pipeline_name, order_nr}, sorted
            by (pipeline_id, order_nr) ascending.
        """
        await registry.ensure_loaded()

        pipeline_id_int: int | None = None
        if pipeline is not None:
            for pid, pname in registry._pipelines.items():
                if pname == pipeline:
                    pipeline_id_int = pid
                    break
            if pipeline_id_int is None:
                valid = sorted(registry._pipelines.values())
                raise ValueError(
                    f"Pipeline '{pipeline}' não encontrado. Pipelines válidos: {valid}"
                )

        items: list[dict] = []
        for sid, meta in registry._stages.items():
            if pipeline_id_int is not None and meta["pipeline_id"] != pipeline_id_int:
                continue
            items.append(
                {
                    "id": sid,
                    "name": meta["name"],
                    "pipeline_id": meta["pipeline_id"],
                    "pipeline_name": registry.pipeline_name(meta["pipeline_id"]),
                    "order_nr": meta.get("order_nr", 0),
                }
            )
        return sorted(items, key=lambda x: (x["pipeline_id"], x["order_nr"]))

    @mcp.tool(name="list_users", annotations={"title": "List Users", **_READ_ANNOTATIONS})
    async def list_users(active_only: bool = True) -> list[dict]:
        """
        List Pipedrive users (members of the workspace).

        Use when the user mentions a CN/owner by name and you need to discover
        the exact spelling, or as a preliminary step before filtering deals by
        cn_name. Useful when the user says "deals do Moreno" and you need to
        confirm what "Moreno" matches in the workspace.

        Args:
            active_only: Reserved for v1.1; currently ignored (returns all users).

        Returns:
            List of {id, name}, sorted by name.
        """
        await registry.ensure_loaded()
        items = [{"id": uid, "name": uname} for uid, uname in registry._users.items()]
        return sorted(items, key=lambda x: x["name"])
