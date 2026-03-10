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
mcp = FastMCP("Inventory_MCP")

def _extract_trace_context(ctx: Context | None):
    """Helper to pull W3C traceparent from MCP _meta injected by clients."""
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

@mcp.tool()
async def get_hotel_inventory(destination: str, ctx: Context) -> dict:
    """Mock database check for hotels."""
    with tracer.start_as_current_span("mcp.tool_call.get_hotel_inventory", context=_extract_trace_context(ctx)) as span:
        span.set_attribute("mcp.tool.name", "get_hotel_inventory")
        span.set_attribute("mcp.tool.arguments.destination", destination)
        logger.info(f"Serving inventory for {destination}")
        return {"cost": 250, "hotel_name": f"{destination} Cloud Suites"}

@mcp.tool()
async def get_weather(location: str, ctx: Context) -> dict:
    """Mock database check for weather."""
    with tracer.start_as_current_span("mcp.tool_call.get_weather", context=_extract_trace_context(ctx)) as span:
        span.set_attribute("mcp.tool.name", "get_weather")
        span.set_attribute("mcp.tool.arguments.location", location)
        logger.info(f"Serving weather for {location}")
        return {"condition": "Sunny", "temperature_c": 24}

@mcp.tool()
async def commit_booking(user_id: str, flight_id: str = "", hotel_id: str = "", car_id: str = "", ctx: Context = None) -> dict:
    """Mock database command for committing bookings."""
    with tracer.start_as_current_span("mcp.tool_call.commit_booking", context=_extract_trace_context(ctx)) as span:
        span.set_attribute("mcp.tool.name", "commit_booking")
        span.set_attribute("mcp.tool.arguments.user_id", user_id)
        logger.info(f"Committing entire travel plan for {user_id} (flight={flight_id}, hotel={hotel_id}, car={car_id})")
        return {"status": "success", "confirmation": "CNF-INVENTORY-OK"}

# --- FastAPI App Wrapping FastMCP ---
app = mcp.sse_app()
FastAPIInstrumentor.instrument_app(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8091)
