"""
Unit tests for D2 observability.

Spec: plans/D2-observabilidade.md
Implementation: observability.py
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

import observability
from observability import instrument


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text().strip().split("\n")
    return [json.loads(ln) for ln in lines if ln]


@pytest.fixture
def tmp_log_path(tmp_path, monkeypatch):
    """Redirect observability writes to a fresh tmp path."""
    log_path = tmp_path / ".observability" / "usage.jsonl"
    monkeypatch.setattr(observability, "_LOG_PATH", log_path)
    return log_path


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_instrument_preserves_return_value(tmp_log_path):
    @instrument
    async def my_tool(x):
        return x * 2

    assert await my_tool(21) == 42


async def test_instrument_logs_success_entry(tmp_log_path):
    @instrument
    async def my_tool():
        await asyncio.sleep(0.01)
        return "ok"

    await my_tool()

    entries = _read_jsonl(tmp_log_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "my_tool"
    assert e["status"] == "ok"
    assert isinstance(e["latency_ms"], int)
    assert e["latency_ms"] >= 10
    assert "timestamp" in e


async def test_instrument_logs_error_entry_and_reraises(tmp_log_path):
    @instrument
    async def failing_tool():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await failing_tool()

    entries = _read_jsonl(tmp_log_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "failing_tool"
    assert e["status"] == "error"
    assert e["error_type"] == "ValueError"
    assert "boom" in e["error_message"]


async def test_instrument_appends_not_overwrites(tmp_log_path):
    @instrument
    async def tool_a():
        return 1

    @instrument
    async def tool_b():
        return 2

    await tool_a()
    await tool_b()
    await tool_a()

    entries = _read_jsonl(tmp_log_path)
    assert len(entries) == 3
    assert [e["tool"] for e in entries] == ["tool_a", "tool_b", "tool_a"]


async def test_instrument_creates_directory(tmp_log_path):
    assert not tmp_log_path.parent.exists()

    @instrument
    async def tool():
        return "x"

    await tool()
    assert tmp_log_path.parent.exists()
    assert tmp_log_path.exists()


async def test_instrument_logging_failure_does_not_break_tool(tmp_log_path, monkeypatch):
    """If writing the log fails, the tool's return value still propagates."""
    real_open = open

    def fake_open(file, mode="r", *args, **kwargs):
        if ".observability" in str(file):
            raise PermissionError("simulated log write failure")
        return real_open(file, mode, *args, **kwargs)

    import builtins
    monkeypatch.setattr(builtins, "open", fake_open)

    @instrument
    async def healthy_tool():
        return "still works"

    result = await healthy_tool()
    assert result == "still works"


async def test_timestamp_format_is_iso8601_utc_z(tmp_log_path):
    @instrument
    async def tool():
        return 1

    await tool()
    entries = _read_jsonl(tmp_log_path)
    ts = entries[0]["timestamp"]
    assert ts.endswith("Z"), f"timestamp does not end in Z: {ts!r}"
    datetime.fromisoformat(ts.replace("Z", "+00:00"))
