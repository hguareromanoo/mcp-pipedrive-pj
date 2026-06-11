"""
FieldsRegistry — dynamic Pipedrive schema discovery + cache.

See plans/registry-field-registry.md for the full spec.

This module replaces the hardcoded constants in fields.py for all new tools (A1+).
Existing tools (get_deal_context and CN write-side) keep using fields.py until
migration in C5 (post-v1).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Literal

from pipedrive import pd

logger = logging.getLogger(__name__)


# Default subset of keys returned by serialize_deal() when include_fields is None.
_DEFAULT_DEAL_KEYS = [
    "id",
    "title",
    "value",
    "currency",
    "stage_name",
    "pipeline_name",
    "owner_name",
    "status",
    "label_names",
    "add_time",
    "update_time",
]


_REPO_DIR = Path(__file__).resolve().parent
_DEFAULT_CACHE_PATH = str(_REPO_DIR / ".cache" / "pipedrive_schema.json")


class FieldsRegistry:
    def __init__(
        self,
        cache_path: str = _DEFAULT_CACHE_PATH,
        ttl_hours: int = 6,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.ttl_seconds = ttl_hours * 3600

        # Internal state — populated by ensure_loaded() / refresh() / _load_cache()
        self._deal_fields: dict[str, dict[str, Any]] = {}
        self._person_fields: dict[str, dict[str, Any]] = {}
        self._org_fields: dict[str, dict[str, Any]] = {}
        self._pipelines: dict[int, str] = {}
        self._stages: dict[int, dict[str, Any]] = {}
        self._users: dict[int, str] = {}
        self._loaded_at: float = 0.0

        self._load_lock = asyncio.Lock()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _is_fresh(self, ts: float) -> bool:
        return ts > 0 and (time.time() - ts) < self.ttl_seconds

    def _entity_dict(self, entity: str) -> dict[str, dict[str, Any]]:
        if entity == "deal":
            return self._deal_fields
        if entity == "person":
            return self._person_fields
        if entity == "org":
            return self._org_fields
        raise ValueError(f"Entidade desconhecida: {entity!r}. Use 'deal', 'person' ou 'org'.")

    def _index_fields(self, raw: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for f in raw:
            opts = f.get("options")
            options: dict[int, str] | None
            if opts:
                options = {}
                for o in opts:
                    try:
                        options[int(o["id"])] = o["label"]
                    except (TypeError, ValueError):
                        # Some native fields (e.g. status) use string IDs like "open".
                        # Skip them — registry's option_id/option_label deal only with
                        # numeric-keyed enums/sets.
                        continue
                if not options:
                    options = None
            else:
                options = None
            out[f["name"]] = {
                "key": f["key"],
                "field_type": f.get("field_type"),
                "options": options,
            }
        return out

    def _populate_from_cache_dict(self, data: dict[str, Any]) -> None:
        def _norm_fields(d: dict[str, Any]) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for name, meta in (d or {}).items():
                opts = meta.get("options")
                if opts:
                    opts = {int(k): v for k, v in opts.items()}
                else:
                    opts = None
                out[name] = {
                    "key": meta["key"],
                    "field_type": meta.get("field_type"),
                    "options": opts,
                }
            return out

        self._deal_fields = _norm_fields(data.get("deal_fields", {}))
        self._person_fields = _norm_fields(data.get("person_fields", {}))
        self._org_fields = _norm_fields(data.get("org_fields", {}))
        self._pipelines = {int(k): v for k, v in (data.get("pipelines") or {}).items()}
        self._stages = {
            int(k): {
                "name": v["name"],
                "pipeline_id": int(v["pipeline_id"]),
                "order_nr": int(v.get("order_nr", 0)),
            }
            for k, v in (data.get("stages") or {}).items()
        }
        self._users = {int(k): v for k, v in (data.get("users") or {}).items()}
        self._loaded_at = float(data.get("_loaded_at", 0.0))

    def _serialize_cache_dict(self) -> dict[str, Any]:
        def _ser_fields(d: dict[str, dict[str, Any]]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for name, meta in d.items():
                opts = meta.get("options")
                ser_opts = (
                    {str(k): v for k, v in opts.items()} if opts else None
                )
                out[name] = {
                    "key": meta["key"],
                    "field_type": meta.get("field_type"),
                    "options": ser_opts,
                }
            return out

        return {
            "_loaded_at": self._loaded_at,
            "deal_fields": _ser_fields(self._deal_fields),
            "person_fields": _ser_fields(self._person_fields),
            "org_fields": _ser_fields(self._org_fields),
            "pipelines": {str(k): v for k, v in self._pipelines.items()},
            "stages": {
                str(k): {
                    "name": v["name"],
                    "pipeline_id": v["pipeline_id"],
                    "order_nr": v.get("order_nr", 0),
                }
                for k, v in self._stages.items()
            },
            "users": {str(k): v for k, v in self._users.items()},
        }

    def _try_read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            return json.loads(self.cache_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cache de schema do Pipedrive corrompido em %s: %s", self.cache_path, e)
            return None

    def _write_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._serialize_cache_dict()
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    async def _fetch_from_api(self) -> None:
        results = await asyncio.gather(
            pd("GET", "/dealFields"),
            pd("GET", "/personFields"),
            pd("GET", "/organizationFields"),
            pd("GET", "/pipelines"),
            pd("GET", "/stages"),
            pd("GET", "/users"),
        )
        deal_raw, person_raw, org_raw, pipelines_raw, stages_raw, users_raw = results

        self._deal_fields = self._index_fields(deal_raw or [])
        self._person_fields = self._index_fields(person_raw or [])
        self._org_fields = self._index_fields(org_raw or [])
        self._pipelines = {int(p["id"]): p["name"] for p in (pipelines_raw or [])}
        self._stages = {
            int(s["id"]): {
                "name": s["name"],
                "pipeline_id": int(s["pipeline_id"]),
                "order_nr": int(s.get("order_nr", 0)),
            }
            for s in (stages_raw or [])
        }
        self._users = {int(u["id"]): u["name"] for u in (users_raw or [])}
        self._loaded_at = time.time()

    async def ensure_loaded(self) -> None:
        # Fast path without lock
        if self._loaded_at and self._is_fresh(self._loaded_at):
            return

        async with self._load_lock:
            # Re-check under lock
            if self._loaded_at and self._is_fresh(self._loaded_at):
                return

            cache_data = self._try_read_cache()
            if cache_data is not None:
                cached_ts = float(cache_data.get("_loaded_at", 0.0))
                if self._is_fresh(cached_ts):
                    self._populate_from_cache_dict(cache_data)
                    return

            # Cache missing or stale → fetch from API.
            try:
                await self._fetch_from_api()
            except Exception as e:
                if cache_data is not None:
                    logger.warning(
                        "Falha ao carregar schema do Pipedrive (%s). Usando cache stale em %s.",
                        e,
                        self.cache_path,
                    )
                    self._populate_from_cache_dict(cache_data)
                    return
                raise RuntimeError(
                    "Não foi possível carregar schema do Pipedrive (sem cache disponível)."
                ) from e

            self._write_cache()

    async def refresh(self) -> None:
        async with self._load_lock:
            await self._fetch_from_api()
            self._write_cache()

    # ── Field resolution ──────────────────────────────────────────────────────

    def field_key(self, entity: Literal["deal", "person", "org"], display_name: str) -> str:
        fields = self._entity_dict(entity)
        if display_name not in fields:
            valid = sorted(fields.keys())
            raise KeyError(
                f"Campo '{display_name}' não encontrado para entidade '{entity}'. "
                f"Campos válidos: {valid}"
            )
        return fields[display_name]["key"]

    def _field_meta(self, entity: str, field_name: str) -> dict[str, Any]:
        fields = self._entity_dict(entity)
        if field_name not in fields:
            valid = sorted(fields.keys())
            raise KeyError(
                f"Campo '{field_name}' não encontrado para entidade '{entity}'. "
                f"Campos válidos: {valid}"
            )
        return fields[field_name]

    def option_id(self, entity: Literal["deal", "person", "org"], field_name: str, label: str) -> int:
        meta = self._field_meta(entity, field_name)
        options = meta.get("options")
        if not options:
            raise KeyError(
                f"Campo '{field_name}' não possui opções."
            )
        for oid, olabel in options.items():
            if olabel == label:
                return int(oid)
        valid = sorted(options.values())
        raise KeyError(
            f"Opção '{label}' não encontrada em '{field_name}'. Opções válidas: {valid}"
        )

    def option_label(self, entity: Literal["deal", "person", "org"], field_name: str, option_id: int) -> str:
        meta = self._field_meta(entity, field_name)
        options = meta.get("options") or {}
        if option_id in options:
            return options[option_id]
        return f"[ID desconhecido: {option_id}]"

    # ── Native lookups ────────────────────────────────────────────────────────

    def pipeline_name(self, pipeline_id: int) -> str:
        return self._pipelines.get(pipeline_id, f"Funil {pipeline_id}")

    def stage_name(self, stage_id: int) -> str:
        meta = self._stages.get(stage_id)
        if meta:
            return meta["name"]
        return f"Etapa {stage_id}"

    def user_name(self, user_id: int) -> str:
        return self._users.get(user_id, f"Usuário {user_id}")

    def user_id_by_name(self, name: str) -> int:
        for uid, uname in self._users.items():
            if uname == name:
                return uid
        valid = sorted(self._users.values())
        raise KeyError(
            f"Usuário '{name}' não encontrado. Usuários válidos: {valid}"
        )

    def stage_id_by_name(self, name: str, pipeline_id: int | None = None) -> int:
        matches = [
            (sid, meta) for sid, meta in self._stages.items() if meta["name"] == name
        ]
        if not matches:
            valid = sorted({meta["name"] for meta in self._stages.values()})
            raise KeyError(
                f"Stage '{name}' não encontrado. Stages válidos: {valid}"
            )
        if pipeline_id is not None:
            for sid, meta in matches:
                if meta["pipeline_id"] == pipeline_id:
                    return sid
            raise KeyError(
                f"Stage '{name}' não existe no pipeline {pipeline_id}."
            )
        if len(matches) > 1:
            pipelines = sorted({meta["pipeline_id"] for _, meta in matches})
            raise KeyError(
                f"Múltiplos stages com nome '{name}' em pipelines {pipelines}. "
                f"Especifique pipeline_id."
            )
        return matches[0][0]

    # ── Serialization ─────────────────────────────────────────────────────────

    def _label_set_field(self, field_meta: dict[str, Any], value: Any) -> list[str]:
        """Decode a 'set' field value (comma-string or list) into list[str] labels."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            ids = [v.strip() for v in value.split(",") if v.strip()]
        elif isinstance(value, list):
            ids = value
        else:
            ids = [value]

        options = field_meta.get("options") or {}
        out: list[str] = []
        for raw_id in ids:
            try:
                oid = int(raw_id)
            except (TypeError, ValueError):
                out.append(str(raw_id))
                continue
            out.append(options.get(oid, f"[ID desconhecido: {oid}]"))
        return out

    def _label_enum_field(self, field_meta: dict[str, Any], value: Any) -> Any:
        if value is None or value == "":
            return None
        try:
            oid = int(value)
        except (TypeError, ValueError):
            return value
        options = field_meta.get("options") or {}
        return options.get(oid, f"[ID desconhecido: {oid}]")

    def _default_subset(self, deal: dict) -> dict:
        # owner: Pipedrive may give a nested {id, name} or just owner_name string.
        owner_name: str | None = None
        user_id = deal.get("user_id")
        if isinstance(user_id, dict):
            owner_name = user_id.get("name") or self.user_name(int(user_id["id"])) if user_id.get("id") else None
        if not owner_name:
            owner_name = deal.get("owner_name")
        if not owner_name and isinstance(user_id, int):
            owner_name = self.user_name(user_id)

        # Stage / pipeline names
        stage_id = deal.get("stage_id")
        stage_name = self.stage_name(int(stage_id)) if stage_id is not None else None

        pipeline_id = deal.get("pipeline_id")
        pipeline_name = self.pipeline_name(int(pipeline_id)) if pipeline_id is not None else None

        # Etiqueta (label) — native 'set' field.
        label_meta = self._deal_fields.get("Etiqueta")
        label_value = deal.get("label")
        if label_meta is not None:
            label_names = self._label_set_field(label_meta, label_value)
        else:
            label_names = [] if not label_value else (
                [str(label_value)] if not isinstance(label_value, list) else [str(x) for x in label_value]
            )

        return {
            "id": deal.get("id"),
            "title": deal.get("title"),
            "value": deal.get("value"),
            "currency": deal.get("currency"),
            "stage_name": stage_name,
            "pipeline_name": pipeline_name,
            "owner_name": owner_name,
            "status": deal.get("status"),
            "label_names": label_names,
            "add_time": deal.get("add_time"),
            "update_time": deal.get("update_time"),
        }

    def _resolve_custom_field_value(self, field_name: str, deal: dict) -> Any:
        meta = self._deal_fields[field_name]
        key = meta["key"]
        ftype = meta.get("field_type")
        raw = deal.get(key)

        if ftype == "set":
            return self._label_set_field(meta, raw)
        if ftype in ("enum", "varchar_options"):
            return self._label_enum_field(meta, raw)
        # varchar, double, date, monetary, etc. — pass through as-is.
        return raw

    def serialize_deal(self, deal: dict, include_fields: list[str] | None = None) -> dict:
        if include_fields is None:
            return self._default_subset(deal)

        default = self._default_subset(deal)
        out: dict[str, Any] = {}
        for name in include_fields:
            if name in _DEFAULT_DEAL_KEYS:
                out[name] = default[name]
            elif name in self._deal_fields:
                out[name] = self._resolve_custom_field_value(name, deal)
            else:
                valid_keys = _DEFAULT_DEAL_KEYS + sorted(self._deal_fields.keys())
                raise ValueError(
                    f"Campo '{name}' não é um campo válido para serialize_deal. "
                    f"Valores aceitos: {valid_keys}"
                )
        return out
