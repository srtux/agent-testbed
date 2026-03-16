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
You MUST enforce the following loader sequences:
```python
# 1. Initialize Telemetry immediately
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
from mcp.server.fastmcp import FastMCP
import os

mcp = FastMCP("New_MCP")

# 1. Setup a standard Tool
@mcp.tool()
async def query_data(parameter: str):
    """Description explaining triggers correctly context binds"""
    return "Pay load contextual data"

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
