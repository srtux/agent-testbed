"""Shared MCP client helper for calling FastMCP tools with trace propagation."""

import json
import logging

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject

logger = logging.getLogger(__name__)


def _normalize_mcp_url(url: str) -> str:
    """Normalize MCP URL to SSE endpoint."""
    if url.endswith("/mcp/call_tool"):
        return url.replace("/mcp/call_tool", "/sse")
    return url


async def call_mcp_tool(mcp_url: str, tool_name: str, arguments: dict, fallback: dict | None = None) -> dict:
    """Call an MCP tool via SSE with automatic trace propagation and JSON parsing.

    Args:
        mcp_url: The MCP server SSE endpoint URL.
        tool_name: Name of the MCP tool to invoke.
        arguments: Arguments dict to pass to the tool.
        fallback: Value to return if the call fails. Defaults to empty dict.

    Returns:
        Parsed JSON response from the MCP tool, or fallback on error.
    """
    if fallback is None:
        fallback = {}

    mcp_url = _normalize_mcp_url(mcp_url)

    try:
        async with sse_client(mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)

                res = await session.call_tool(tool_name, arguments=arguments, meta=meta)
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        try:
                            return json.loads(data)
                        except json.JSONDecodeError:
                            return {"raw_text": data}
                    return data
    except Exception as e:
        logger.warning(f"MCP call to {tool_name} at {mcp_url} failed: {e}")
        return fallback

    return fallback
