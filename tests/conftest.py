import asyncio
import os
import shutil
import subprocess
import time

import pytest

from testbed_utils.services import LOCAL_SERVICES


def pytest_configure(config):
    """Register custom marks used by this suite."""
    config.addinivalue_line("markers", "asyncio: mark test as asyncio-compatible")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run `async def` tests without requiring pytest-asyncio."""
    testfunction = pyfuncitem.obj
    if asyncio.iscoroutinefunction(testfunction):
        kwargs = {
            arg: pyfuncitem.funcargs[arg]
            for arg in pyfuncitem._fixtureinfo.argnames
            if arg in pyfuncitem.funcargs
        }
        asyncio.run(testfunction(**kwargs))
        return True
    return None


@pytest.fixture(scope="session", autouse=True)
def start_local_services():
    """Automatically starts all local services (Agents and MCP servers) for the test session."""
    # Check if we are running local tests
    endpoint = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")
    if "localhost" not in endpoint and not os.environ.get("FORCE_LOCAL_SERVICES"):
        print("Skipping local services startup as endpoint is not localhost.")
        yield
        return

    print("Starting all testbed services locally for testing...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    processes = []
    log_files = []

    try:
        for svc in LOCAL_SERVICES:
            svc_dir = os.path.join(root_dir, svc.path)
            if not os.path.exists(svc_dir):
                print(f"Warning: Directory not found for {svc.name} at {svc_dir}")
                continue

            # Skip startup if the port is already bound
            if shutil.which("lsof"):
                check = subprocess.run(
                    ["lsof", "-ti", f":{svc.port}"],
                    capture_output=True,
                    text=True,
                )
                if check.stdout.strip():
                    print(
                        f"Port {svc.port} already in use, skipping startup for {svc.name}."
                    )
                    continue

            env = os.environ.copy()
            # Set to true to disable manual trace setup in setup_telemetry() for local tests,
            # avoiding connection errors to localhost:4317 if no collector is running.
            env["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "true"
            # Force ADK to use Vertex AI (via patched google_llm.py)
            env["USE_VERTEX_AI"] = "true"
            # Enable mock LLM for fast local testing
            env["USE_MOCK_LLM"] = "true"

            # Create log file for the service
            log_dir = os.path.join(root_dir, "tests", "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = open(os.path.join(log_dir, f"{svc.name}.log"), "w")
            log_files.append(log_file)

            # Start service
            p = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "uvicorn",
                    "main:app",
                    "--port",
                    str(svc.port),
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

        print("All services started.")

        yield  # Run tests

    finally:
        print("\nShutting down all services...")
        for p in processes:
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

        # Close log files
        for f in log_files:
            try:
                f.flush()
            finally:
                f.close()

        print("Done.")
