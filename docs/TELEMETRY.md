# OpenTelemetry Instrumentation & Context Propagation Guide

This document provides a comprehensive detailing of how distributed tracing and context propagation are implemented across the **agent-testbed**, covering Agent-to-Agent (A2A) and Agent-to-MCP Server interactions.

---

## 🚀 Overview

Distributed tracing allows tracking of requests as they travel across multiple independent services (Agents, MCP servers). In this testbed, we use **OpenTelemetry** with traces exported to **Google Cloud Trace** via `telemetry.googleapis.com`.

---

## 🔗 Trace Call Chains

### 1. Agent-to-Agent (A2A)

The call chain goes from an Agent making an outbound HTTP request using `httpx` to another Agent serving requests via `FastAPI`.

*   **Client Side (Outbound)**:
    *   **Tool**: `HTTPXClientInstrumentor`
    *   **Mechanism**: Automatically injects a standard W3C `traceparent` header into outgoing HTTP requests.
    *   **Setup**: Handled by `testbed_utils.telemetry:setup_authenticated_transport()`.

*   **Server Side (Inbound)**:
    *   **Tool**: `FastAPIInstrumentor`
    *   **Mechanism**: Automatically extracts the `traceparent` header from incoming requests.
    *   **Setup**: Must be called explicitly on your FastAPI `app` object:
        ```python
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        app = FastAPI()
        FastAPIInstrumentor.instrument_app(app)
        ```

---

### 2. Agent-to-MCP Server (FastMCP)

The call chain goes from an Agent invoking a tool on an MCP server (e.g., SSE connection). **Since MCP is transport-agnostic, passing trace context requires injecting it into the payload envelope (`_meta` bag).**

*   **Client Side (Outbound)**:
    *   **Mechanism**: Manually `inject` trace W3C context headers into the `_meta` dictionary when making the tool call.
    *   **Implementation**:
        ```python
        from opentelemetry.propagate import inject
        
        async with sse_client(profile_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # <<-- Propagates trace context into meta
                
                res = await session.call_tool(
                    "tool_name", 
                    arguments=args,
                    meta=meta
                )
        ```

*   **Server Side (Inbound)**:
    *   **Mechanism**: Extracted manually from the FastMCP `Context` object passed into the tool handler.
    *   **Implementation**:
        Use the following helper to extract the context safely:
        ```python
        from opentelemetry.propagate import extract
        from mcp.server.fastmcp import Context
        
        def _extract_trace_context(ctx: Context | None):
            if ctx is None: return {}
            meta_obj = ctx.request_context.meta if ctx.request_context and hasattr(ctx.request_context, 'meta') else None
            # Standard dictionary conversion
            if hasattr(meta_obj, 'model_dump'): meta_dict = meta_obj.model_dump()
            elif hasattr(meta_obj, 'dict'): meta_dict = meta_obj.dict()
            else: meta_dict = meta_obj or {}
            
            return extract(meta_dict)
        ```
        Then wrap your tool payload:
        ```python
        @mcp.tool()
        async def my_tool(arg: str, ctx: Context) -> dict:
            with tracer.start_as_current_span(
                "mcp.tool_call.my_tool", 
                context=_extract_trace_context(ctx)
            ) as span:
                # ... logic ...
        ```

---

## ⚙️ Environment Configuration

### 1. runtime setup
*   **Agent Engine**: Platform auto-creates `TracerProvider`. **DO NOT** initialize manually. Call only `setup_authenticated_transport()` to install request auth hooks.
*   **Cloud Run / GKE**: Call `setup_telemetry()` at the module entrance.

### 2. Required variables (Cloud Run / GKE)
Ensure the following variables are set to authenticate with the trace collector:
*   `OTEL_EXPORTER_OTLP_ENDPOINT="https://telemetry.googleapis.com"`
*   `GOOGLE_CLOUD_PROJECT="<your_project_id>"`
*   `OTEL_SERVICE_NAME="<your_service_name>"`

The `testbed_utils.telemetry` package provides authenticated channel hooks out-of-the-box leveraging Application Default Credentials.

---

## 🛠️ Verification Setup

To verify context propagation works correctly, you can run tests asserting that the Server Trace ID perfectly matches the Client Trace ID:
```python
def test_trace_extraction_from_meta():
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("client_span") as client_span:
         client_ctx = client_span.get_span_context()
         meta = {}
         inject(meta)
         
         extracted_context = _extract_trace_context(MockContext(meta=meta))
         
         with tracer.start_as_current_span("server_span", context=extracted_context) as server_span:
              assert server_span.get_span_context().trace_id == client_ctx.trace_id
```
Refer to `tests/test_mcp_meta.py` for fully running integrations.
