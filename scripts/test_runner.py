import os
import sys
import subprocess
import json

def _resolve_endpoint(url):
    """Ensures the endpoint URL has the /chat path when it's an HTTP URL."""
    if url and not url.startswith("projects/") and not url.endswith("/chat"):
        return url.rstrip("/") + "/chat"
    return url

def local():
    """Runs tests locally against localhost."""
    print("🧪 Running unit tests...")
    subprocess.run(["pytest", "tests/test_mcp_meta.py"], check=True)

    print("\n🧪 Make sure you have `uv run run-all` running in another terminal window!")
    print("Running integration tests against http://localhost:8080...")
    os.environ["ROOT_ROUTER_ENDPOINT"] = "http://localhost:8080/chat"

    # We use pytest for integration tests too
    subprocess.run(["pytest", "tests/integration_test.py", "-v", "-s"], check=True)

def remote():
    """Runs tests remotely against a deployed Cloud endpoint."""
    ae1_url = os.environ.get("ROOT_ROUTER_URL") or os.environ.get("ROOT_ROUTER_ENDPOINT")

    if not ae1_url:
        # Attempt to read from agent_engine_outputs.json
        output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_engine_outputs.json")
        if os.path.exists(output_path):
            try:
                with open(output_path) as f:
                    outputs = json.load(f)
                    ae1_url = outputs.get("RootRouter")
            except Exception as e:
                print(f"⚠️ Warning: Failed to read agent_engine_outputs.json: {e}")

    if not ae1_url:
        print("❌ Error: ROOT_ROUTER_URL environment variable or agent_engine_outputs.json with 'RootRouter' is required to run remote tests.")
        print("Example: ROOT_ROUTER_URL=https://my-router-url.a.run.app uv run test-remote")
        sys.exit(1)

    ae1_url = _resolve_endpoint(ae1_url)
    print(f"🧪 Running remote integration tests against {ae1_url}...")
    os.environ["ROOT_ROUTER_ENDPOINT"] = ae1_url
    subprocess.run(["pytest", "tests/integration_test.py", "-v", "-s"], check=True)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "remote":
        remote()
    else:
        local()
