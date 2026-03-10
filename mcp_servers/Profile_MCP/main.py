# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging

setup_telemetry()
logger = setup_logging()

from mcp.server.fastmcp import FastMCP, Context
from opentelemetry.propagate import extract
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

tracer = trace.get_tracer(__name__)


# --- FastMCP Server ---
mcp = FastMCP("Profile_MCP")

def _extract_trace_context(ctx: Context):
    """Helper to pull W3C traceparent from MCP _meta injected by clients."""
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

@mcp.tool()
async def get_user_preferences(user_id: str, ctx: Context) -> dict:
    """Gets the user preferences. Extracts OTel trace context from the MCP _meta bag."""
    with tracer.start_as_current_span(
        "mcp.tool_call.get_user_preferences",
        context=_extract_trace_context(ctx)
    ) as span:
        span.set_attribute("mcp.tool.name", "get_user_preferences")
        span.set_attribute("mcp.tool.arguments.user_id", user_id)
        
        logger.info(f"Fetching user preferences for {user_id}")
        
        # Mock preferences
        prefs = {
            "home_airport": "SFO",
            "loyalty_tier": "Gold",
            "preferences": {"seat": "aisle"}
        }
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
