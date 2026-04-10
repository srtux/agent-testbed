import os
import subprocess
import time

import pytest


@pytest.fixture(scope="session", autouse=True)
def start_local_services():
    """Automatically starts all local services (Agents and MCP servers) for the test session."""
    # Check if we are running local tests
    endpoint = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")
    if "localhost" not in endpoint and not os.environ.get("FORCE_LOCAL_SERVICES"):
        print("Skipping local services startup as endpoint is not localhost.")
        yield
        return

    print("🚀 Starting all testbed services locally for testing...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    services = [
        {"name": "RootRouter", "path": "agents/RootRouter", "port": 8080},
        {
            "name": "BookingOrchestrator",
            "path": "agents/BookingOrchestrator",
            "port": 8081,
        },
        {"name": "FlightSpecialist", "path": "agents/FlightSpecialist", "port": 8082},
        {"name": "WeatherSpecialist", "path": "agents/WeatherSpecialist", "port": 8083},
        {"name": "HotelSpecialist", "path": "agents/HotelSpecialist", "port": 8084},
        {
            "name": "CarRentalSpecialist",
            "path": "agents/CarRentalSpecialist",
            "port": 8085,
        },
        {"name": "Profile_MCP", "path": "mcp_servers/Profile_MCP", "port": 8090},
        {"name": "Inventory_MCP", "path": "mcp_servers/Inventory_MCP", "port": 8091},
    ]

    processes = []
    log_files = []

    try:
        for svc in services:
            svc_dir = os.path.join(root_dir, svc["path"])
            if not os.path.exists(svc_dir):
                print(f"⚠️ Warning: Directory not found for {svc['name']} at {svc_dir}")
                continue

            # Check if port in use
            check = subprocess.run(
                f"lsof -ti:{svc['port']}", shell=True, capture_output=True, text=True
            )
            if check.stdout.strip():
                print(
                    f"Port {svc['port']} already in use, skipping startup for {svc['name']}."
                )
                continue

            env = os.environ.copy()
            # Set to true to disable manual trace setup in setup_telemetry() for local tests,
            # avoiding connection errors to localhost:4317 if no collector is running.
            env["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "true"
            # Force ADK to use Vertex AI (via patched google_llm.py)
            env["USE_VERTEX_AI"] = "true"

            # Create log file for the service
            log_dir = os.path.join(root_dir, "tests", "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = open(os.path.join(log_dir, f"{svc['name']}.log"), "w")
            log_files.append(log_file)

            # Start service
            p = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "uvicorn",
                    "main:app",
                    "--port",
                    str(svc["port"]),
                    "--env-file",
                    "../../.env",
                ],
                cwd=svc_dir,
                env=env,
                stdout=log_file,
                stderr=log_file,
            )
            processes.append(p)
            time.sleep(0.5)  # Give it time to bind

        print("✅ All services started.")

        yield  # Run tests

    finally:
        print("\n🛑 Shutting down all services...")
        for p in processes:
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

        # Close log files
        for f in log_files:
            f.close()

        print("Done.")
