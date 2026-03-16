# Model Context Protocol (MCP) Integration Guide

This document describes how agents connect to **FastMCP** servers using Server-Sent Events (SSE) inside the **agent-testbed**.

---

## 🛰️ 1. Concept: Structured Context Retrieval

Unlike A2A which delegates full prompt processing to another agent, **MCP** allows agents to call structured tool endpoints (e.g., User Profiles, Inventory lookups) using typed payloads over an SSE transport.

*   **Protocol**: Server-Sent Events (SSE) running over HTTP.

---

## 💻 2. Implementation Example

Agents use the MCP `sse_client` and `ClientSession` to connect and call tools:

```python
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject
import os

async def fetch_profile(member_id: str) -> dict:
    mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")

    async with sse_client(mcp_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Context Propagation setup
            meta = {}
            inject(meta)

            response = await session.call_tool(
                "get_user_preferences",
                arguments={"user_id": member_id},
                meta=meta
            )
            return response.content[0].text
```

---

## 🔍 3. Manual Context Propagation (Tracing)

Because MCP uses a multiplexed SSE transport, the standard HTTP client instrumentors (e.g., `HTTPXClientInstrumentor`) **cannot** automatically attach trace context to individual tool calls.

Instead, trace context must be propagated manually:

1.  **Create envelope**: `meta = {}`
2.  **Inject trace context**: Call `inject(meta)` from `opentelemetry.propagate` to pack the W3C `traceparent` header into the dictionary.
3.  **Pass with call**: Include `meta=meta` in the `.call_tool()` invocation.

---

## 📥 4. Server-Side Extraction

On the MCP server side (FastMCP), a custom helper extracts the `traceparent` from the `_meta` dictionary passed with each tool call. This restores the trace context so that server-side spans are correctly linked to the calling agent's trace.

See each MCP server's `_extract_trace_context()` function for the implementation (e.g., `mcp_servers/Inventory_MCP/main.py`).
