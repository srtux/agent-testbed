import os
import sys
import subprocess
import time
import httpx

def local():
    """Runs tests locally against localhost."""
    print("🧪 Running unit tests...")
    subprocess.run(["pytest", "tests/test_mcp_meta.py"], check=True)
    
    print("\n🧪 Make sure you have `uv run run-all` running in another terminal window!")
    print("Running integration tests against http://localhost:8080...")
    os.environ["RootRouter_ENDPOINT"] = "http://localhost:8080/chat"
    
    # We use pytest for integration tests too
    subprocess.run(["pytest", "tests/integration_test.py", "-v", "-s"])

def remote():
    """Runs tests remotely against a deployed Cloud endpoint."""
    ae1_url = os.environ.get("RootRouter_URL")
    if not ae1_url:
        print("❌ Error: RootRouter_URL environment variable is required to run remote tests.")
        print("Example: RootRouter_URL=https://my-router-url.a.run.app uv run test-remote")
        sys.exit(1)
        
    print(f"🧪 Running remote integration tests against {ae1_url}...")
    os.environ["RootRouter_ENDPOINT"] = ae1_url
    subprocess.run(["pytest", "tests/integration_test.py", "-v", "-s"])

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "remote":
        remote()
    else:
        local()
