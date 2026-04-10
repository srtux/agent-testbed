# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.logging import setup_logging
from testbed_utils.telemetry import setup_telemetry

setup_telemetry()
logger = setup_logging()

from mcp.server.fastmcp import Context, FastMCP
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from testbed_utils.mcp_trace_context import extract_trace_context_from_mcp

tracer = trace.get_tracer(__name__)


# --- FastMCP Server ---
import os

from mcp.server.transport_security import TransportSecuritySettings

allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
extra_hosts = os.environ.get("ALLOWED_HOSTS")
if extra_hosts:
    allowed_hosts.extend(
        [
            h.strip() + ":*" if ":" not in h else h.strip()
            for h in extra_hosts.split(",")
        ]
    )

mcp = FastMCP(
    "Profile_MCP",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    ),
)


def _extract_trace_context(ctx: Context | None):
    """Helper to pull W3C traceparent from MCP _meta injected by clients."""
    return extract_trace_context_from_mcp(ctx)


@mcp.tool()
async def get_user_preferences(user_id: str, ctx: Context) -> dict:
    """Gets the user preferences. Extracts OTel trace context from the MCP _meta bag."""
    with tracer.start_as_current_span(
        "mcp.tool_call.get_user_preferences", context=_extract_trace_context(ctx)
    ) as span:
        span.set_attribute("mcp.tool.name", "get_user_preferences")
        span.set_attribute("mcp.tool.arguments.user_id", user_id)

        logger.info(f"Fetching user preferences for {user_id}")

        # Mock preferences
        prefs = {
            "home_airport": "SFO",
            "loyalty_tier": "Gold",
            "preferences": {"seat": "aisle"},
        }
        logger.info(f"Returning preferences for {user_id}: {prefs}")
        return prefs


# --- FastAPI App Wrapping FastMCP ---
app = mcp.sse_app()
FastAPIInstrumentor.instrument_app(app)

from starlette.responses import JSONResponse
from starlette.routing import Route

app.routes.append(Route("/health", lambda request: JSONResponse({"status": "ok"})))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8090)
