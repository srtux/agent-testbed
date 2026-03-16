# Model Context Protocol (MCP) Integration Guide

This document describes how agents connect to **FastMCP** Context servers using Server-Sent Events (SSE) inside the **agent-testbed**.

---

## 🛰️ 1. Concept: Structured Context Retrieval

Unlike A2A which handles prompt delegation recursively, **MCP** allows agents to fetch static context tables (e.g., User Profiles, Inventory thresholds) using structured payloads securely.

*   **Protocol**: Server-Sent Events (SSE) running over HTTP transport sockets.

---

## 💻 2. Implementation Example

Outbound calls utilize generic `ClientSession` streams to bridge trigger loops accurately.

```python
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import os

async def fetch_profile(member_id: str) -> dict:
    mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")

    async with sse_client(mcp_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Context Propagation setup
            meta = {}
            inject_opentelemetry_headers(meta) 

            response = await session.call_tool(
                "get_user_preferences",
                arguments={"user_id": member_id},
                meta=meta
            )
            return response.content[0].text
```

---

## 🔍 3. Manual Context Propagation (Tracing)

Because transport sessions multiplex streams natively, standard HTTP global Client instrumentors **cannot** cleanly bind specific tool calls to span coordinate threads comfortably.

1.  **Setup Envelope**: Create dictionary `meta = {}`.
2.  **Injection Hook**: Use OpenTelemetry propagate `inject(meta)` to pack standard W3C `traceparent` coordinates inside this bag.
3.  **Placement**: Pass `meta=meta` inside the `.call_tool()` wrapper position triggers.

---

## 📥 4. Server-Side Extraction

On the destination listener (FastMCP socket), custom extractor nodes intercept the `.meta` dictionary envelopes prior forwarding trigger hooks into `@app.tool()` decorators backward, binding distributed context graphs appropriately securely.

This explicitly maintains trace cascades flowing completely cascaded seamlessly!
