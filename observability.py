"""D2 — Observability. See plans/D2-observabilidade.md.

Lightweight instrumentation: wrap each MCP tool function with `instrument(fn)`
to capture (tool_name, latency_ms, status, error) into a JSONL log at
`.observability/usage.jsonl`. Logging failures NEVER block tool execution.

The log path is anchored to the directory containing this module so it works
regardless of the cwd that Claude Desktop sets when launching the server.
"""
from __future__ import annotations

import functools
import json
import time
from datetime import datetime, timezone
from pathlib import Path


_REPO_DIR = Path(__file__).resolve().parent
_LOG_PATH = _REPO_DIR / ".observability" / "usage.jsonl"


def _now_iso_z() -> str:
    """ISO 8601 UTC timestamp with millisecond precision and 'Z' suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _write_entry(entry: dict) -> None:
    """Append entry as one JSON line. Swallow any IO failure silently — the
    tool's result is more important than the log line."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def instrument(fn):
    """See plans/D2-observabilidade.md."""

    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
        except Exception as e:
            latency_ms = int((time.perf_counter() - start) * 1000)
            _write_entry({
                "timestamp": _now_iso_z(),
                "tool": fn.__name__,
                "latency_ms": latency_ms,
                "status": "error",
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
            })
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        _write_entry({
            "timestamp": _now_iso_z(),
            "tool": fn.__name__,
            "latency_ms": latency_ms,
            "status": "ok",
        })
        return result

    return wrapped
