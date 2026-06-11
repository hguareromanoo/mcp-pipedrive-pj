"""
Shared fixtures for unit and integration tests.

- Unit tests (tests/unit/) use respx to mock HTTP calls and `mock_registry`
  to get a fully populated FieldsRegistry without hitting the network.
- Integration tests (tests/integration/) are marked @pytest.mark.integration
  and hit the real Pipedrive instance via the token in .env. They are
  skipped automatically when the token is absent.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env once at the start of the test session so PIPEDRIVE_API_TOKEN and
# PIPEDRIVE_BASE_URL are available to both unit (which set fakes) and
# integration (which use the real values).
@pytest.fixture(scope="session", autouse=True)
def _load_env():
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env", override=False)
    # Provide a deterministic fake token for unit tests if none set.
    os.environ.setdefault("PIPEDRIVE_API_TOKEN", "test-token-for-unit")
    os.environ.setdefault("PIPEDRIVE_BASE_URL", "https://api.pipedrive.com/v1")


# ── Integration gating ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _skip_integration_if_no_token(request):
    """Skip any test marked `integration` if a real token is not configured."""
    if request.node.get_closest_marker("integration"):
        token = os.getenv("PIPEDRIVE_API_TOKEN")
        if not token or token == "test-token-for-unit":
            pytest.skip("PIPEDRIVE_API_TOKEN not set; skipping integration test")


# ── Sample API responses (realistic shape, used by mocks) ────────────────────


@pytest.fixture
def sample_deal_fields_response():
    """Mirrors GET /v1/dealFields — list of field metadata."""
    return [
        # Custom enum
        {
            "key": "6ea1ea74da5fbb8cb6a8dd741a96a9bc8b4e379f",
            "name": "Setor da Empresa",
            "field_type": "enum",
            "options": [
                {"id": 156, "label": "Computer Software & Internet"},
                {"id": 158, "label": "Education"},
                {"id": 167, "label": "Information Technology & Services"},
            ],
        },
        # Custom enum
        {
            "key": "97d0502cc2b489986844a93b374656e5acf179e1",
            "name": "Canal de Entrada",
            "field_type": "enum",
            "options": [
                {"id": 27, "label": "Inbound"},
                {"id": 28, "label": "Outbound"},
                {"id": 29, "label": "Fidelização"},
                {"id": 30, "label": "Indicação"},
            ],
        },
        # Custom set
        {
            "key": "e4339ab04542dcd1e1215e4bc17ee2bcf45a9652",
            "name": "Portfólio",
            "field_type": "set",
            "options": [
                {"id": 207, "label": "NDados - DSaaS"},
                {"id": 219, "label": "NDados - Extração"},
                {"id": 312, "label": "NDados - IA Generativa"},
            ],
        },
        # Custom varchar
        {
            "key": "ede9bf995bb2d7e50ea8ffbfd24cb56e72232ff0",
            "name": "Link Drive das Gravações",
            "field_type": "varchar",
            "options": None,
        },
        # Native set
        {
            "key": "label",
            "name": "Etiqueta",
            "field_type": "set",
            "options": [
                {"id": 31, "label": "NCiv"},
                {"id": 32, "label": "NDados"},
                {"id": 33, "label": "NCon"},
                {"id": 34, "label": "NTec"},
                {"id": 152, "label": "WI"},
                {"id": 286, "label": "NI"},
            ],
        },
        # Native varchar_options
        {
            "key": "lost_reason",
            "name": "Motivo da perda",
            "field_type": "varchar_options",
            "options": [
                {"id": 15, "label": "Budget"},
                {"id": 20, "label": "Timing"},
                {"id": 22, "label": "Falha no Contato"},
            ],
        },
        # Custom enum — Hunter
        {
            "key": "hunter_hash",
            "name": "Hunter",
            "field_type": "enum",
            "options": [
                {"id": 500, "label": "Hunter A"},
                {"id": 501, "label": "Hunter B"},
            ],
        },
        # Custom enum — SDR
        {
            "key": "sdr_hash",
            "name": "SDR",
            "field_type": "enum",
            "options": [
                {"id": 600, "label": "SDR A"},
                {"id": 601, "label": "SDR B"},
            ],
        },
        # Custom enum — Número de Funcionários
        {
            "key": "0b2be49fb7615b170878d944a7cb05f6ec8f9e27",
            "name": "Número de Funcionários",
            "field_type": "enum",
            "options": [
                {"id": 184, "label": "11-50"},
                {"id": 185, "label": "51-200"},
                {"id": 186, "label": "201-500"},
            ],
        },
        # Native enum — Origem
        {
            "key": "origin",
            "name": "Origem",
            "field_type": "enum",
            "options": [
                {"id": 1, "label": "Site"},
                {"id": 2, "label": "Indicação"},
            ],
        },
        # Custom enum — Suborigem
        {
            "key": "suborigem_hash",
            "name": "Suborigem",
            "field_type": "enum",
            "options": [
                {"id": 10, "label": "Form LP"},
                {"id": 11, "label": "Email"},
            ],
        },
        # Native built-ins (no options)
        {"key": "title", "name": "Title", "field_type": "varchar", "options": None},
        {"key": "value", "name": "Value", "field_type": "monetary", "options": None},
        {"key": "stage_id", "name": "Stage", "field_type": "stage", "options": None},
        {"key": "pipeline_id", "name": "Pipeline", "field_type": "double", "options": None},
        {"key": "status", "name": "Status", "field_type": "varchar", "options": None},
        {"key": "add_time", "name": "Add time", "field_type": "date", "options": None},
        {"key": "update_time", "name": "Update time", "field_type": "date", "options": None},
        {"key": "user_id", "name": "Owner", "field_type": "user", "options": None},
    ]


@pytest.fixture
def sample_person_fields_response():
    return [
        {"key": "name", "name": "Name", "field_type": "varchar", "options": None},
        {"key": "email", "name": "Email", "field_type": "varchar", "options": None},
        {"key": "phone", "name": "Phone", "field_type": "phone", "options": None},
        {"key": "job_title", "name": "Job title", "field_type": "varchar", "options": None},
    ]


@pytest.fixture
def sample_org_fields_response():
    return [
        {"key": "name", "name": "Name", "field_type": "varchar", "options": None},
    ]


@pytest.fixture
def sample_pipelines_response():
    return [
        {"id": 1, "name": "Funil Comercial"},
        {"id": 2, "name": "Funil Outbound"},
    ]


@pytest.fixture
def sample_stages_response():
    return [
        {"id": 5, "name": "AT Marcada", "pipeline_id": 1, "order_nr": 1},
        {"id": 6, "name": "Proposta Apresentada", "pipeline_id": 1, "order_nr": 2},
        {"id": 7, "name": "Negociação", "pipeline_id": 1, "order_nr": 3},
        {"id": 10, "name": "AT Marcada", "pipeline_id": 2, "order_nr": 1},  # duplicate name across pipelines
    ]


@pytest.fixture
def sample_users_response():
    return [
        {"id": 100, "name": "Henrique Romano", "email": "h@example.com", "active_flag": True},
        {"id": 101, "name": "João Silva", "email": "j@example.com", "active_flag": True},
        {"id": 102, "name": "Maria Souza", "email": "m@example.com", "active_flag": False},
    ]


@pytest.fixture
def sample_person_response():
    """A single person as returned by GET /v1/persons/{id}."""
    return {
        "id": 555,
        "name": "Ana Cliente",
        "job_title": "CTO",
        "email": [{"value": "ana@cliente.com", "primary": True, "label": "work"}],
        "phone": [{"value": "+5511999999999", "primary": True, "label": "mobile"}],
        "org_id": {"value": 777, "name": "Cliente X Ltda"},
    }


@pytest.fixture
def sample_org_response():
    """A single organization as returned by GET /v1/organizations/{id}."""
    return {
        "id": 777,
        "name": "Cliente X Ltda",
        "address": "Av. Paulista, 1000, São Paulo - SP",
        "owner_id": {"value": 100, "name": "Henrique Romano"},
    }


@pytest.fixture
def sample_notes_response():
    """A list of notes as returned by GET /v1/notes?deal_id={id}."""
    return [
        {
            "id": 9001,
            "content": "AT realizada em 01/06. Cliente interessado em DSaaS.",
            "add_time": "2026-06-01 14:30:00",
            "user": {"id": 100, "name": "Henrique Romano"},
        },
        {
            "id": 9002,
            "content": "Follow-up agendado para próxima semana.",
            "add_time": "2026-06-02 10:00:00",
            "user": {"id": 101, "name": "João Silva"},
        },
    ]


@pytest.fixture
def sample_activities_response():
    """A list of activities as returned by GET /v1/deals/{id}/activities."""
    return [
        {
            "id": 8001,
            "type": "meeting",
            "subject": "Apresentação de Proposta",
            "due_date": "2026-06-15",
            "done": False,
            "note": "Levar slides v3",
        },
        {
            "id": 8002,
            "type": "call",
            "subject": "Call de descoberta",
            "due_date": "2026-06-01",
            "done": True,
            "note": "",
        },
    ]


@pytest.fixture
def sample_deal_response():
    """A single deal as returned by GET /v1/deals/{id}, with custom field hashes filled."""
    return {
        "id": 1234,
        "title": "Cliente X — Projeto de Previsão",
        "value": 48000,
        "currency": "BRL",
        "status": "open",
        "stage_id": 5,
        "pipeline_id": 1,
        "user_id": {"id": 100, "name": "Henrique Romano"},
        "owner_name": "Henrique Romano",
        "label": "32",  # NDados
        "add_time": "2026-05-01 10:00:00",
        "update_time": "2026-06-01 12:00:00",
        # Custom fields by hash
        "6ea1ea74da5fbb8cb6a8dd741a96a9bc8b4e379f": 167,  # Setor: IT & Services
        "97d0502cc2b489986844a93b374656e5acf179e1": 28,   # Canal: Outbound
        "e4339ab04542dcd1e1215e4bc17ee2bcf45a9652": "207,312",  # Portfólio: DSaaS, IA Generativa
        "ede9bf995bb2d7e50ea8ffbfd24cb56e72232ff0": "https://drive.example.com/folder",
        "lost_reason": None,
    }


# ── Cache and registry fixtures ──────────────────────────────────────────────


@pytest.fixture
def fresh_cache_dict(
    sample_deal_fields_response,
    sample_person_fields_response,
    sample_org_fields_response,
    sample_pipelines_response,
    sample_stages_response,
    sample_users_response,
):
    """
    Combined cache dict (matches what FieldsRegistry writes to disk).
    Tests that need a pre-populated registry use this written to a tmp file.
    """
    def _index_fields(raw):
        return {
            f["name"]: {
                "key": f["key"],
                "field_type": f["field_type"],
                "options": {opt["id"]: opt["label"] for opt in (f.get("options") or [])} or None,
            }
            for f in raw
        }

    return {
        "_loaded_at": time.time(),
        "deal_fields": _index_fields(sample_deal_fields_response),
        "person_fields": _index_fields(sample_person_fields_response),
        "org_fields": _index_fields(sample_org_fields_response),
        "pipelines": {str(p["id"]): p["name"] for p in sample_pipelines_response},
        "stages": {
            str(s["id"]): {"name": s["name"], "pipeline_id": s["pipeline_id"], "order_nr": s["order_nr"]}
            for s in sample_stages_response
        },
        "users": {str(u["id"]): u["name"] for u in sample_users_response},
    }


@pytest.fixture
async def mock_registry(tmp_path, fresh_cache_dict):
    """
    A FieldsRegistry instance pointed at a tmp cache file, pre-populated.
    Loading from disk skips any API calls.
    """
    from field_registry import FieldsRegistry

    cache_path = tmp_path / "schema.json"
    cache_path.write_text(json.dumps(fresh_cache_dict))

    registry = FieldsRegistry(cache_path=str(cache_path), ttl_hours=6)
    await registry.ensure_loaded()
    return registry


@pytest.fixture(scope="session")
async def real_registry():
    """
    A FieldsRegistry instance loaded from the real Pipedrive API.
    Session-scoped so the load happens once per pytest run.

    NOTE: tests that use this fixture MUST be marked @pytest.mark.integration.
    The skip-if-no-token fixture above gates them out when token is absent,
    but this fixture itself will not check — callers must opt in via marker.
    """
    from field_registry import FieldsRegistry

    cache_dir = Path(__file__).resolve().parent.parent / ".cache"
    cache_dir.mkdir(exist_ok=True)
    registry = FieldsRegistry(
        cache_path=str(cache_dir / "pipedrive_schema.json"),
        ttl_hours=6,
    )
    await registry.ensure_loaded()
    return registry
