# Developer Expansion Guide (Cookbook)

This document provides a standardized recipe for expanding the **agent-testbed** mesh by adding or creating a new Specialist Agent or FastMCP Server compliant with distributed tracing and auth standards.

---

## 🏗️ 1. Adding a New Specialist Agent

Follow this recipe to spin up a new node (e.g., `CarRentalSpecialist`).

### Step A: Folder Layout
Create standard standalone wrappers:
```bash
agents/NewSpecialist/
├── main.py                    # Loader wrapper ( FastAPI )
└── new_specialist/            # Actual logic package
    ├── __init__.py
    ├── agent.py               # LlmAgent formulation
    └── prompt.py              # prompt instructions
```

### Step B: Core Entry Point layout (`main.py`)

> [!IMPORTANT]
> **Runtime-specific initialization.** Cloud Run / GKE specialists call `setup_telemetry()` to install a `TracerProvider` with the authenticated OTLP exporter. **Agent Engine agents (RootRouter, BookingOrchestrator) must NOT call `setup_telemetry()`** — the Vertex AI platform creates its own `TracerProvider` and calling it again would overwrite platform trace export. Agent Engine agents call `setup_authenticated_transport()` instead, which only installs the HTTPX/Requests OIDC auth hooks. See [AGENTS.md](../AGENTS.md) and [ADK_INSTRUMENTATION.md](ADK_INSTRUMENTATION.md) for details.

**Cloud Run / GKE Specialist** (`main.py`) — you MUST enforce this loader sequence:
```python
# 1. Initialize Telemetry immediately (before FastAPI / ADK imports)
from testbed_utils.telemetry import setup_telemetry
setup_telemetry()

import sys, os, uuid
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from .new_specialist.agent import agent
from google.adk.runners import InMemoryRunner

runner = InMemoryRunner(agent=agent)
app = FastAPI()

# 2. Instrument Inbound Contexts
FastAPIInstrumentor.instrument_app(app)

@app.post("/chat")
async def chat_endpoint(request):
    # standard async runner loop triggers
    pass
```

**Agent Engine Agent** (`main.py`) — use `setup_authenticated_transport()` instead:
```python
# Do NOT call setup_telemetry() — the platform owns the TracerProvider.
# Only install the OIDC auth hooks for outbound A2A calls.
from testbed_utils.telemetry import setup_authenticated_transport
setup_authenticated_transport()
```

### Step C: Tool Formulation (`agent.py`)
If calling other agents (A2A), use standard `httpx` without header overrides. If calling MCP, manually inject `meta`.

---

## 🛠️ 2. Adding a New FastMCP Server

Follow this recipe to create a Context Endpoint node.

### Step A: Layout
```bash
mcp_servers/New_MCP/
└── main.py                    # FastMCP server handles 
```

### Step B: Code Layout (`main.py`)
```python
# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.logging import setup_logging
from testbed_utils.telemetry import setup_telemetry

setup_telemetry()
logger = setup_logging()

from mcp.server.fastmcp import Context, FastMCP
from opentelemetry import trace
from opentelemetry.propagate import extract

tracer = trace.get_tracer(__name__)
mcp = FastMCP("New_MCP")


def _extract_trace_context(ctx: Context | None):
    """Pull W3C traceparent from MCP _meta injected by clients."""
    if ctx is None:
        return {}
    meta_obj = (
        ctx.request_context.meta
        if ctx.request_context and hasattr(ctx.request_context, "meta")
        else None
    )
    if hasattr(meta_obj, "model_dump"):
        meta_dict = meta_obj.model_dump()
    elif isinstance(meta_obj, dict):
        meta_dict = meta_obj
    else:
        meta_dict = {}
    return extract(meta_dict)


# 1. Setup a standard Tool. Wrap the body in a span whose parent context is
#    pulled from the MCP _meta bag, so trace propagation chains correctly.
@mcp.tool()
async def query_data(parameter: str, ctx: Context) -> dict:
    """Description explaining triggers correctly context binds."""
    with tracer.start_as_current_span(
        "mcp.tool_call.query_data", context=_extract_trace_context(ctx)
    ) as span:
        span.set_attribute("mcp.tool.name", "query_data")
        span.set_attribute("mcp.tool.arguments.parameter", parameter)
        return {"payload": "contextual data"}


if __name__ == "__main__":
    # fastmcp handles sse loops natively
    mcp.run()
```

---

## 🚀 3. Deploying Integrations

To consolidate the node into full meshes correctly:

1.  **Add to Orchestrator (`scripts/deploy.py`)**: Add folder coordinates inside `services = [...]` dictionary allocations keeping parallel concurrently triggers.
2.  **Add to Cloud Resources (`terraform/`)**: Create standard resource bindings (e.g. `google_cloud_run_v2_service` or equivalent deployment yaml maps trigger bounds securely).
3.  **Update Call graph references** inside central orchestrators making outbound function tools forward endpoints coordinates appropriately outwards backwards.
