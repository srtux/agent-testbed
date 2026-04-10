import os
import shutil
import subprocess
import sys
import time

from testbed_utils.services import LOCAL_SERVICES


def _kill_port(port: int) -> None:
    """Terminate any process listening on the given port."""
    if not shutil.which("lsof"):
        return
    check = subprocess.run(
        ["lsof", "-ti", f":{port}"], capture_output=True, text=True
    )
    pids = [p for p in check.stdout.strip().split("\n") if p]
    if not pids:
        return
    print(f"  Port {port} in use by PID(s): {', '.join(pids)} — terminating...")
    for pid in pids:
        subprocess.run(["kill", pid], capture_output=True)
    time.sleep(0.5)
    for pid in pids:
        subprocess.run(["kill", "-9", pid], capture_output=True)


def main():
    """Runs all Agents and MCP servers locally using uvicorn on specific ports."""

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    processes = []

    print("Starting all testbed services locally...")

    try:
        for svc in LOCAL_SERVICES:
            svc_dir = os.path.join(root_dir, svc.path)
            if not os.path.exists(svc_dir):
                print(f"Warning: Directory not found for {svc.name} at {svc_dir}")
                continue

            print(f"Starting {svc.name} on port {svc.port}...")
            _kill_port(svc.port)

            env = os.environ.copy()
            # Override to false locally so setup_telemetry() initializes a provider
            env["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "false"
            # Uvicorn reads .env natively via --env-file below.

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
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            processes.append(p)
            # Give each service a moment to bind to the port before starting the next
            time.sleep(0.5)

        print("\nAll services are running. Press Ctrl+C to stop all.")
        print("  RootRouter Interface: http://localhost:8080/chat")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down all services...")
        for p in processes:
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        print("Done.")


if __name__ == "__main__":
    main()
