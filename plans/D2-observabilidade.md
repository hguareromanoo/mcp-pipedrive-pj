# D2 — Observabilidade

Instrumentação leve para capturar uso real do MCP no Claude Desktop. Cada
invocação de tool grava uma linha JSON em `.observability/usage.jsonl` (append-only)
com timestamp, nome da tool, latência em ms, status (ok/error), e — em caso de
erro — tipo e mensagem da exceção.

Sustenta o DoD outlier do Card de Experimento ("uso documentado") sem dependência
externa: o log é um arquivo JSONL local, consultável com `jq` ou `wc -l`.

## Public surface

Um único módulo `observability.py` na raiz do repo, com:

```python
def instrument(fn):
    """
    Decorator that wraps an async tool function. Captures tool_name (from fn.__name__),
    latency_ms (perf_counter delta), status ("ok" | "error"), and on error: error_type
    (exception class name) + error_message (str(e) truncated to 500 chars).

    Writes one JSON line per call to `.observability/usage.jsonl` (relative to cwd).
    Re-raises the original exception in the error path.

    Returns a new async function with functools.wraps preserved.
    """
```

That's the only public symbol the rest of the code needs.

## Integration in `server.py`

Right after `mcp = FastMCP("pipedrive_mcp")` and before any `register()` call:

```python
import observability
_original_tool = mcp.tool

def _instrumented_tool(*args, **kwargs):
    decorator = _original_tool(*args, **kwargs)
    def wrapper(fn):
        return decorator(observability.instrument(fn))
    return wrapper

mcp.tool = _instrumented_tool
```

This monkey-patches the `mcp.tool` decorator so every subsequent `@mcp.tool(...)`
silently adds `instrument()` around the function. No change to the existing tool
modules.

## JSONL entry shape

```json
{
  "timestamp": "2026-06-09T15:42:31.123Z",
  "tool": "list_deals_with_filters",
  "latency_ms": 1243,
  "status": "ok"
}
```

On error:

```json
{
  "timestamp": "2026-06-09T15:42:31.123Z",
  "tool": "get_person",
  "latency_ms": 87,
  "status": "error",
  "error_type": "ValueError",
  "error_message": "Person not found: 999999"
}
```

## File handling

- Path: `<cwd>/.observability/usage.jsonl` — cwd is whatever Claude Desktop sets
  for the server process (usually the dir containing server.py if `cwd` is in
  the JSON config; otherwise wherever Claude Desktop boots the server).
- Create the `.observability/` directory if it doesn't exist (best effort —
  failure to write log must NEVER block the tool from returning).
- Open with mode `"a"` and write a single line per call, no buffering tricks.
- Concurrent calls are safe enough for v1 — POSIX append-mode writes of short
  lines (< 4KB) are atomic on macOS. We don't need a lock.

## Failure mode

If logging itself raises (e.g. disk full, permission denied), swallow the
exception silently — the tool's result is more important than the log entry.

## Tests (`tests/unit/test_observability.py`)

7 unit tests, no respx (this is pure-Python):

1. `test_instrument_preserves_return_value` — wrapped fn returns same value as wrapped.
2. `test_instrument_logs_success_entry` — call wrapped fn, read jsonl, assert tool name + latency_ms + status=ok.
3. `test_instrument_logs_error_entry_and_reraises` — wrapped fn raises ValueError, instrument logs entry with status=error, error_type=ValueError, error_message includes the original message, and re-raises.
4. `test_instrument_appends_not_overwrites` — call twice, assert 2 lines in the file.
5. `test_instrument_creates_directory` — `.observability/` does not exist before; first call creates it.
6. `test_instrument_logging_failure_does_not_break_tool` — monkey-patch open to raise; wrapped fn still returns its value normally.
7. `test_timestamp_format_is_iso8601_utc_z` — timestamp string ends in "Z" and parses via datetime.fromisoformat.

All tests use `tmp_path` and `monkeypatch.chdir(tmp_path)` so writes go to a temp dir.

## Skeleton

`observability.py` starts as:

```python
"""D2 — Observability. See plans/D2-observabilidade.md."""

from __future__ import annotations
import functools

def instrument(fn):
    """See plans/D2-observabilidade.md."""
    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        raise NotImplementedError
    return wrapped
```

The agent fills in the body.

## Done criteria

- 7 unit tests pass.
- `server.py` boots and `python -c "import server"` succeeds.
- After a manual call to any tool, `.observability/usage.jsonl` exists with at least one valid JSON line.
- All 109 previously-passing tests still pass.
- Total: 116 passing.
