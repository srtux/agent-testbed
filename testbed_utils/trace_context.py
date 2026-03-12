"""Shared helper for extracting W3C trace context from MCP _meta objects."""

from opentelemetry.propagate import extract


def extract_trace_context(ctx):
    """Pull W3C traceparent from the MCP _meta bag injected by clients.

    Works with FastMCP Context objects. Returns an OTel context suitable
    for passing to tracer.start_as_current_span(context=...).
    """
    if ctx is None:
        return {}
    meta_obj = ctx.request_context.meta if ctx.request_context and hasattr(ctx.request_context, 'meta') else None
    if hasattr(meta_obj, 'model_dump'):
        meta_dict = meta_obj.model_dump()
    elif hasattr(meta_obj, 'dict'):
        meta_dict = meta_obj.dict()
    elif isinstance(meta_obj, dict):
        meta_dict = meta_obj
    else:
        meta_dict = {}
    return extract(meta_dict)
