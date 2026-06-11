"""
Integration tests for FieldsRegistry — hits the real Pipedrive instance of the
Poli Júnior using PIPEDRIVE_API_TOKEN from .env.

Skipped automatically when token is missing (see tests/conftest.py).
Assertions are resilient to data drift: structural (non-empty, expected display
names present) rather than value-exact.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


# Canonical names that should exist in the PJ's Pipedrive schema. If any of
# these fails, it is a real signal of drift (someone renamed a field or removed
# an option) and the test SHOULD fail to surface it.
EXPECTED_DEAL_FIELDS = [
    "Canal de Entrada",
    "Setor da Empresa",
    "Portfólio",
    "Número de Funcionários",
    "Link (Drive) das Gravações",  # parens are part of the real name
    "Etiqueta",
    "Motivo da perda",  # lowercase 'p' in the real schema
]

EXPECTED_CANAIS = ["Inbound", "Outbound", "Fidelização", "Indicação"]
EXPECTED_NUCLEOS = ["NDados", "NCiv", "NCon", "NTec", "WI", "NI"]


async def test_real_api_loads_schema(real_registry):
    """ensure_loaded() against real API completes without raising."""
    # Lazy assertion: internal state should be non-empty.
    # We test via public methods to avoid coupling to internals.
    assert real_registry.field_key("deal", "Etiqueta") == "label"


async def test_real_api_known_custom_fields_present(real_registry):
    """All canonical deal field display names resolve to non-empty keys."""
    for name in EXPECTED_DEAL_FIELDS:
        key = real_registry.field_key("deal", name)
        assert isinstance(key, str)
        assert len(key) > 0, f"Empty key for '{name}'"


async def test_real_api_known_canal_options_present(real_registry):
    """All canonical Canal de Entrada options resolve to int IDs."""
    for label in EXPECTED_CANAIS:
        option_id = real_registry.option_id("deal", "Canal de Entrada", label)
        assert isinstance(option_id, int)
        assert option_id > 0


async def test_real_api_known_nucleos_present(real_registry):
    """All canonical núcleos resolve as Etiqueta option IDs."""
    for nucleo in EXPECTED_NUCLEOS:
        option_id = real_registry.option_id("deal", "Etiqueta", nucleo)
        assert isinstance(option_id, int)
        assert option_id > 0


async def test_real_api_pipelines_non_empty(real_registry):
    """At least one pipeline exists in the PJ's Pipedrive. Inspect cache file."""
    cache_path = Path(__file__).resolve().parent.parent.parent / ".cache" / "pipedrive_schema.json"
    data = json.loads(cache_path.read_text())
    assert len(data["pipelines"]) > 0, "No pipelines loaded from real API"


async def test_real_api_users_non_empty(real_registry):
    """At least one user exists. Inspect cache file (user IDs in Pipedrive are
    8-digit globals, so a numeric scan is meaningless)."""
    cache_path = Path(__file__).resolve().parent.parent.parent / ".cache" / "pipedrive_schema.json"
    data = json.loads(cache_path.read_text())
    assert len(data["users"]) > 0, "No users loaded from real API"


async def test_real_api_cache_written(real_registry):
    """After ensure_loaded(), the cache file exists with the expected keys."""
    cache_path = Path(__file__).resolve().parent.parent.parent / ".cache" / "pipedrive_schema.json"
    assert cache_path.exists(), f"Cache file missing at {cache_path}"

    data = json.loads(cache_path.read_text())
    expected_top_keys = {
        "_loaded_at",
        "deal_fields",
        "person_fields",
        "org_fields",
        "pipelines",
        "stages",
        "users",
    }
    assert expected_top_keys.issubset(set(data.keys()))

    assert isinstance(data["_loaded_at"], (int, float))
    assert len(data["deal_fields"]) > 0
    assert len(data["pipelines"]) > 0
    assert len(data["users"]) > 0


async def test_real_api_cache_hit_skips_second_load(real_registry):
    """
    Second ensure_loaded() call in the same session is a no-op (memory cache hit).
    Verifiable via _loaded_at: it does not change.
    """
    # Capture timestamp from cache file written by session-scoped fixture
    cache_path = Path(__file__).resolve().parent.parent.parent / ".cache" / "pipedrive_schema.json"
    ts_before = json.loads(cache_path.read_text())["_loaded_at"]

    # Calling ensure_loaded again should not touch the cache (memory is fresh)
    await real_registry.ensure_loaded()

    ts_after = json.loads(cache_path.read_text())["_loaded_at"]
    assert ts_after == ts_before
