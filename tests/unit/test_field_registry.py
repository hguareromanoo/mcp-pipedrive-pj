"""
Unit tests for FieldsRegistry — fully mocked, no network.

Covers: cache hit/miss/expired, fallback to stale cache on API failure,
lookups (positive + negative), serialization (default + custom + unknown),
concurrency safety.

Implementation lives in field_registry.py. Spec in plans/registry-field-registry.md.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest
import respx

from field_registry import FieldsRegistry

BASE = "https://api.pipedrive.com/v1"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _wrap(data):
    """Wrap a payload as Pipedrive's envelope."""
    return {"success": True, "data": data}


def _mock_all_endpoints(
    respx_mock,
    deal_fields,
    person_fields,
    org_fields,
    pipelines,
    stages,
    users,
):
    """Register all six schema endpoints with the given payloads. Returns a dict
    of {path: route} so tests can assert on call_count without depending on
    respx.routes name-based lookup."""
    routes = {}
    routes["dealFields"] = respx_mock.get(f"{BASE}/dealFields").mock(
        return_value=httpx.Response(200, json=_wrap(deal_fields))
    )
    routes["personFields"] = respx_mock.get(f"{BASE}/personFields").mock(
        return_value=httpx.Response(200, json=_wrap(person_fields))
    )
    routes["organizationFields"] = respx_mock.get(f"{BASE}/organizationFields").mock(
        return_value=httpx.Response(200, json=_wrap(org_fields))
    )
    routes["pipelines"] = respx_mock.get(f"{BASE}/pipelines").mock(
        return_value=httpx.Response(200, json=_wrap(pipelines))
    )
    routes["stages"] = respx_mock.get(f"{BASE}/stages").mock(
        return_value=httpx.Response(200, json=_wrap(stages))
    )
    routes["users"] = respx_mock.get(f"{BASE}/users").mock(
        return_value=httpx.Response(200, json=_wrap(users))
    )
    return routes


# ── Loading: cache miss / hit / expired ──────────────────────────────────────


@respx.mock
async def test_ensure_loaded_fetches_when_no_cache(
    tmp_path,
    sample_deal_fields_response,
    sample_person_fields_response,
    sample_org_fields_response,
    sample_pipelines_response,
    sample_stages_response,
    sample_users_response,
):
    """No cache file → all 6 endpoints called → cache written → memory populated."""
    cache = tmp_path / "schema.json"
    assert not cache.exists()

    routes = _mock_all_endpoints(
        respx,
        sample_deal_fields_response,
        sample_person_fields_response,
        sample_org_fields_response,
        sample_pipelines_response,
        sample_stages_response,
        sample_users_response,
    )

    registry = FieldsRegistry(cache_path=str(cache), ttl_hours=6)
    await registry.ensure_loaded()

    # Cache file written
    assert cache.exists()
    data = json.loads(cache.read_text())
    assert set(data.keys()) >= {
        "_loaded_at",
        "deal_fields",
        "person_fields",
        "org_fields",
        "pipelines",
        "stages",
        "users",
    }

    # All 6 endpoints were called
    for route in routes.values():
        assert route.call_count == 1


@respx.mock
async def test_ensure_loaded_uses_cache_when_fresh(tmp_path, fresh_cache_dict):
    """Cache exists and < TTL → memory loads from disk, zero HTTP calls."""
    cache = tmp_path / "schema.json"
    cache.write_text(json.dumps(fresh_cache_dict))

    # Register a route that would fail the test if called.
    failing = respx.get(f"{BASE}/dealFields").mock(return_value=httpx.Response(500))

    registry = FieldsRegistry(cache_path=str(cache), ttl_hours=6)
    await registry.ensure_loaded()

    assert failing.call_count == 0
    # And resolution works (proves memory was populated)
    assert registry.field_key("deal", "Setor da Empresa")


@respx.mock
async def test_ensure_loaded_refreshes_when_expired(
    tmp_path,
    fresh_cache_dict,
    sample_deal_fields_response,
    sample_person_fields_response,
    sample_org_fields_response,
    sample_pipelines_response,
    sample_stages_response,
    sample_users_response,
):
    """Cache older than TTL → API is called → cache rewritten with new timestamp."""
    cache = tmp_path / "schema.json"
    stale = dict(fresh_cache_dict)
    stale["_loaded_at"] = time.time() - (7 * 3600)  # 7h ago, TTL is 6h
    cache.write_text(json.dumps(stale))

    routes = _mock_all_endpoints(
        respx,
        sample_deal_fields_response,
        sample_person_fields_response,
        sample_org_fields_response,
        sample_pipelines_response,
        sample_stages_response,
        sample_users_response,
    )

    registry = FieldsRegistry(cache_path=str(cache), ttl_hours=6)
    await registry.ensure_loaded()

    assert routes["dealFields"].call_count == 1
    new = json.loads(cache.read_text())
    assert new["_loaded_at"] > stale["_loaded_at"]


@respx.mock
async def test_load_falls_back_to_disk_when_api_fails_with_stale_cache(
    tmp_path, fresh_cache_dict, caplog
):
    """API 500 + stale cache exists → load stale, log warning, do not raise."""
    cache = tmp_path / "schema.json"
    stale = dict(fresh_cache_dict)
    stale["_loaded_at"] = time.time() - (12 * 3600)
    cache.write_text(json.dumps(stale))

    respx.get(f"{BASE}/dealFields").mock(return_value=httpx.Response(500))

    registry = FieldsRegistry(cache_path=str(cache), ttl_hours=6)
    await registry.ensure_loaded()  # Must not raise

    assert registry.field_key("deal", "Setor da Empresa")
    # A warning should be logged about using stale cache
    assert any("stale" in r.message.lower() or "cache" in r.message.lower() for r in caplog.records)


@respx.mock
async def test_load_raises_when_api_fails_and_no_cache(tmp_path):
    """API 500 + no cache → RuntimeError with clear message."""
    cache = tmp_path / "schema.json"
    assert not cache.exists()

    respx.get(f"{BASE}/dealFields").mock(return_value=httpx.Response(500))

    registry = FieldsRegistry(cache_path=str(cache), ttl_hours=6)
    with pytest.raises(RuntimeError) as exc:
        await registry.ensure_loaded()

    assert "schema" in str(exc.value).lower() or "pipedrive" in str(exc.value).lower()


@respx.mock
async def test_refresh_overwrites_cache(
    tmp_path,
    fresh_cache_dict,
    sample_deal_fields_response,
    sample_person_fields_response,
    sample_org_fields_response,
    sample_pipelines_response,
    sample_stages_response,
    sample_users_response,
):
    """refresh() forces a re-fetch even with fresh cache."""
    cache = tmp_path / "schema.json"
    cache.write_text(json.dumps(fresh_cache_dict))

    routes = _mock_all_endpoints(
        respx,
        sample_deal_fields_response,
        sample_person_fields_response,
        sample_org_fields_response,
        sample_pipelines_response,
        sample_stages_response,
        sample_users_response,
    )

    registry = FieldsRegistry(cache_path=str(cache), ttl_hours=6)
    await registry.ensure_loaded()  # cache hit, no HTTP
    assert routes["dealFields"].call_count == 0

    old_ts = json.loads(cache.read_text())["_loaded_at"]
    await asyncio.sleep(0.01)
    await registry.refresh()

    assert routes["dealFields"].call_count == 1
    new_ts = json.loads(cache.read_text())["_loaded_at"]
    assert new_ts > old_ts


# ── Field resolution ─────────────────────────────────────────────────────────


async def test_field_key_resolves_known_name(mock_registry):
    """Display name → hash for custom fields."""
    assert mock_registry.field_key("deal", "Setor da Empresa") == "6ea1ea74da5fbb8cb6a8dd741a96a9bc8b4e379f"
    assert mock_registry.field_key("deal", "Canal de Entrada") == "97d0502cc2b489986844a93b374656e5acf179e1"
    assert mock_registry.field_key("deal", "Portfólio") == "e4339ab04542dcd1e1215e4bc17ee2bcf45a9652"


async def test_field_key_resolves_native_name(mock_registry):
    """Native fields use their native key (not a hash)."""
    assert mock_registry.field_key("deal", "Etiqueta") == "label"
    assert mock_registry.field_key("deal", "Motivo da perda") == "lost_reason"
    assert mock_registry.field_key("deal", "Stage") == "stage_id"


async def test_field_key_raises_on_unknown_name(mock_registry):
    """Unknown display name → KeyError with valid names listed."""
    with pytest.raises(KeyError) as exc:
        mock_registry.field_key("deal", "CampoQueNaoExiste")
    msg = str(exc.value)
    assert "Setor da Empresa" in msg or "Canal de Entrada" in msg


async def test_option_id_resolves_known_label(mock_registry):
    """Label → numeric ID for enum/set fields."""
    assert mock_registry.option_id("deal", "Setor da Empresa", "Education") == 158
    assert mock_registry.option_id("deal", "Canal de Entrada", "Outbound") == 28
    assert mock_registry.option_id("deal", "Etiqueta", "NDados") == 32


async def test_option_id_raises_on_unknown_label(mock_registry):
    """Unknown label → KeyError with valid labels listed."""
    with pytest.raises(KeyError) as exc:
        mock_registry.option_id("deal", "Canal de Entrada", "Marciano")
    msg = str(exc.value)
    assert "Inbound" in msg or "Outbound" in msg


async def test_option_label_resolves_known_id(mock_registry):
    """ID → label."""
    assert mock_registry.option_label("deal", "Canal de Entrada", 28) == "Outbound"
    assert mock_registry.option_label("deal", "Etiqueta", 32) == "NDados"


async def test_option_label_unknown_returns_placeholder(mock_registry):
    """Unknown ID does NOT raise — returns placeholder."""
    result = mock_registry.option_label("deal", "Canal de Entrada", 9999)
    assert "9999" in result
    assert "desconhecido" in result.lower()


# ── Native lookups ───────────────────────────────────────────────────────────


async def test_pipeline_name_resolves(mock_registry):
    assert mock_registry.pipeline_name(1) == "Funil Comercial"
    assert mock_registry.pipeline_name(2) == "Funil Outbound"


async def test_pipeline_name_unknown_returns_fallback(mock_registry):
    assert "999" in mock_registry.pipeline_name(999)


async def test_stage_name_resolves(mock_registry):
    assert mock_registry.stage_name(5) == "AT Marcada"
    assert mock_registry.stage_name(6) == "Proposta Apresentada"


async def test_user_name_resolves(mock_registry):
    assert mock_registry.user_name(100) == "Henrique Romano"
    assert mock_registry.user_name(101) == "João Silva"


async def test_user_id_by_name_reverse_lookup(mock_registry):
    assert mock_registry.user_id_by_name("João Silva") == 101


async def test_user_id_by_name_unknown_raises(mock_registry):
    with pytest.raises(KeyError):
        mock_registry.user_id_by_name("Pessoa Inexistente")


async def test_stage_id_by_name_unique(mock_registry):
    """Unique stage name resolves without pipeline disambiguation."""
    assert mock_registry.stage_id_by_name("Proposta Apresentada") == 6
    assert mock_registry.stage_id_by_name("Negociação") == 7


async def test_stage_id_by_name_ambiguous_raises(mock_registry):
    """Stage name shared across pipelines requires pipeline_id."""
    # "AT Marcada" exists in pipelines 1 and 2 in the fixture.
    with pytest.raises(KeyError) as exc:
        mock_registry.stage_id_by_name("AT Marcada")
    assert "pipeline" in str(exc.value).lower()


async def test_stage_id_by_name_with_pipeline_disambiguates(mock_registry):
    """Specifying pipeline_id resolves the ambiguity."""
    assert mock_registry.stage_id_by_name("AT Marcada", pipeline_id=1) == 5
    assert mock_registry.stage_id_by_name("AT Marcada", pipeline_id=2) == 10


# ── Serialization ────────────────────────────────────────────────────────────


async def test_serialize_deal_default_subset(mock_registry, sample_deal_response):
    """Default serialization returns the 11-key enxuto subset."""
    out = mock_registry.serialize_deal(sample_deal_response)
    expected_keys = {
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
    }
    assert set(out.keys()) == expected_keys
    assert out["id"] == 1234
    assert out["stage_name"] == "AT Marcada"
    assert out["pipeline_name"] == "Funil Comercial"
    assert out["owner_name"] == "Henrique Romano"
    assert out["label_names"] == ["NDados"]


async def test_serialize_deal_custom_subset(mock_registry, sample_deal_response):
    """include_fields=[...] returns only those, resolving custom fields to labels."""
    out = mock_registry.serialize_deal(
        sample_deal_response,
        include_fields=["title", "value", "Setor da Empresa"],
    )
    assert set(out.keys()) == {"title", "value", "Setor da Empresa"}
    assert out["Setor da Empresa"] == "Information Technology & Services"  # 167 → label


async def test_serialize_deal_custom_set_field_returns_list(mock_registry, sample_deal_response):
    """A set custom field (e.g. Portfólio) resolves to list[str]."""
    out = mock_registry.serialize_deal(
        sample_deal_response,
        include_fields=["title", "Portfólio"],
    )
    assert isinstance(out["Portfólio"], list)
    assert "NDados - DSaaS" in out["Portfólio"]
    assert "NDados - IA Generativa" in out["Portfólio"]


async def test_serialize_deal_unknown_field_raises(mock_registry, sample_deal_response):
    """Unknown name in include_fields raises ValueError with valid options."""
    with pytest.raises(ValueError) as exc:
        mock_registry.serialize_deal(sample_deal_response, include_fields=["XYZ"])
    msg = str(exc.value)
    assert "XYZ" in msg


# ── Concurrency ──────────────────────────────────────────────────────────────


@respx.mock
async def test_concurrent_ensure_loaded_only_fetches_once(
    tmp_path,
    sample_deal_fields_response,
    sample_person_fields_response,
    sample_org_fields_response,
    sample_pipelines_response,
    sample_stages_response,
    sample_users_response,
):
    """Multiple awaiters of ensure_loaded() result in a single set of API calls."""
    cache = tmp_path / "schema.json"

    routes = _mock_all_endpoints(
        respx,
        sample_deal_fields_response,
        sample_person_fields_response,
        sample_org_fields_response,
        sample_pipelines_response,
        sample_stages_response,
        sample_users_response,
    )

    registry = FieldsRegistry(cache_path=str(cache), ttl_hours=6)
    await asyncio.gather(
        registry.ensure_loaded(),
        registry.ensure_loaded(),
        registry.ensure_loaded(),
    )

    # Each endpoint hit exactly once (not three times)
    assert routes["dealFields"].call_count == 1
