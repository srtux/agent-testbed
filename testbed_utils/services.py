"""Canonical local-dev service definitions for the testbed.

Used by scripts/run_all.py and tests/conftest.py to avoid duplicating the
port/path mapping for the 6 agents and 2 MCP servers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    name: str
    path: str
    port: int


LOCAL_SERVICES: list[Service] = [
    # Agents
    Service("RootRouter", "agents/RootRouter", 8080),
    Service("BookingOrchestrator", "agents/BookingOrchestrator", 8081),
    Service("FlightSpecialist", "agents/FlightSpecialist", 8082),
    Service("WeatherSpecialist", "agents/WeatherSpecialist", 8083),
    Service("HotelSpecialist", "agents/HotelSpecialist", 8084),
    Service("CarRentalSpecialist", "agents/CarRentalSpecialist", 8085),
    # MCP Servers
    Service("Profile_MCP", "mcp_servers/Profile_MCP", 8090),
    Service("Inventory_MCP", "mcp_servers/Inventory_MCP", 8091),
]
