"""Helpers for extracting OpenTelemetry trace context from MCP request metadata."""

from typing import Any

from opentelemetry.propagate import extract


def extract_trace_context_from_mcp(ctx: Any) -> Any:
    """Extract W3C trace context from MCP `ctx.request_context.meta`.

    Works with dict-like objects and pydantic model objects without importing
    MCP-specific classes, so this helper can be reused by servers and tests.
    """
    if ctx is None:
        return {}

    request_context = getattr(ctx, "request_context", None)
    meta_obj = (
        getattr(request_context, "meta", None) if request_context is not None else None
    )

    if hasattr(meta_obj, "model_dump"):
        meta_dict = meta_obj.model_dump()
    elif hasattr(meta_obj, "dict"):
        meta_dict = meta_obj.dict()
    elif isinstance(meta_obj, dict):
        meta_dict = meta_obj
    else:
        meta_dict = {}

    return extract(meta_dict)
