#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

_missing = [v for v in ["PIPEDRIVE_API_TOKEN"] if not os.getenv(v)]
if _missing:
    print(f"Missing required env vars: {', '.join(_missing)}", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("pipedrive_mcp")

# D2 — observability: wrap every @mcp.tool with instrument() so each tool
# invocation gets logged to .observability/usage.jsonl (append-only JSONL).
# Logging failures never block the tool from returning.
import observability
_original_tool = mcp.tool

def _instrumented_tool(*args, **kwargs):
    decorator = _original_tool(*args, **kwargs)
    def wrapper(fn):
        return decorator(observability.instrument(fn))
    return wrapper

mcp.tool = _instrumented_tool

# Shared FieldsRegistry for v1 read tools. Lazy-loaded: ensure_loaded() is
# called inside each tool, so server startup does not block on Pipedrive.
from field_registry import FieldsRegistry
registry = FieldsRegistry()

# Legacy tools (using fields.py directly).
# C5 (2026-06-10): write-side CN tools (log_meeting, advance_deal, register_prospect,
# resolve_deal) were removed — preferred via Pipedrive UI. find_deals kept for now
# but redundant with list_deals_with_filters; candidate for next cleanup pass.
from tools.get_deal_context import register as reg_context
from tools.find_deals import register as reg_find

for register in [reg_context, reg_find]:
    register(mcp)

# v1 read tools (using FieldsRegistry).
from tools.list_deals_with_filters import register as reg_list_deals
reg_list_deals(mcp, registry)

from tools.base_gets import register as reg_base_gets
reg_base_gets(mcp, registry)

from tools.analytics import register as reg_analytics
reg_analytics(mcp, registry)

if __name__ == "__main__":
    mcp.run()
