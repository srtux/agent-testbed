"""Deployment script for all Agent Engine agents."""

import os
import sys

# Ensure we can import the agents
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import vertexai
from absl import app, flags
from dotenv import load_dotenv
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# Import the agents
from agents.RootRouter.main import agent as root_router_agent
from agents.BookingOrchestrator.main import agent as booking_agent

FLAGS = flags.FLAGS
flags.DEFINE_string("project_id", None, "GCP project ID.")
flags.DEFINE_string("location", None, "GCP location.")
flags.DEFINE_string("bucket", None, "GCP bucket.")
flags.DEFINE_string("resource_id", None, "ReasoningEngine resource ID.")

flags.DEFINE_bool("list", False, "List all agents.")
flags.DEFINE_bool("create", False, "Creates new agents.")
flags.DEFINE_bool("delete", False, "Deletes an existing agent.")
flags.mark_bool_flags_as_mutual_exclusive(["create", "delete", "list"])


def create_agent(agent_obj) -> None:
    """Creates an agent engine for the given agent."""
    adk_app = AdkApp(agent=agent_obj, enable_tracing=True)

    # Core dependencies needed for Testbed ADK agents
    requirements = [
        "fastapi>=0.135.1",
        "google-adk>=1.26.0",
        "mcp>=1.26.0",
        "opentelemetry-api>=1.38.0",
        "opentelemetry-exporter-gcp-trace>=1.11.0",
        "opentelemetry-instrumentation-fastapi>=0.59b0",
        "opentelemetry-sdk>=1.38.0",
        "uvicorn>=0.41.0",
        "pydantic>=2.10.6,<3.0.0",
        "google-cloud-aiplatform[adk,agent-engines]>=1.93.0",
        "google-genai>=1.5.0",
        "httpx>=0.28.0"
    ]
    
    # We pass the shared 'testbed_utils' directory so the remote engine has access to it.
    testbed_utils_dir = os.path.join(project_root, "testbed_utils")
    
    # Optionally, we can inject env vars (e.g. downstream agent URLs) if needed downstream
    # For now, it relies on standard env vars at runtime.
    
    print(f"Deploying {agent_obj.name}...")
    remote_agent = agent_engines.create(
        adk_app,
        display_name=agent_obj.name,
        requirements=requirements,
        extra_packages=[testbed_utils_dir],
        env_vars={
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
            "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED": "true",
            "LOG_FORMAT": "JSON",
            "LOG_LEVEL": "INFO",
            "RUNNING_IN_AGENT_ENGINE": "true"
        }
    )
    print(f"Created remote agent {agent_obj.name}: {remote_agent.resource_name}")
    print()


import concurrent.futures

def create() -> None:
    """Deploy all configured ADK agents in parallel."""
    agents = [root_router_agent, booking_agent]
    
    print(f"🚀 Deploying {len(agents)} agents in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        # We wrap it in a list to ensure we wait for all to complete and catch exceptions
        futures = {executor.submit(create_agent, agent): agent for agent in agents}
        for future in concurrent.futures.as_completed(futures):
            agent = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"❌ Error deploying {agent.name}: {e}")
                # We don't exit immediately so other agents can continue, 
                # but we could if we wanted a fail-fast behavior.


def delete(resource_id: str) -> None:
    """Deletes a given agent by resource ID."""
    remote_agent = agent_engines.get(resource_id)
    remote_agent.delete(force=True)
    print(f"Deleted remote agent: {resource_id}")


def list_agents() -> None:
    """Lists all deployed agent engines."""
    remote_agents = agent_engines.list()
    template = """
{agent.name} ("{agent.display_name}")
- Create time: {agent.create_time}
- Update time: {agent.update_time}
"""
    remote_agents_string = "\n".join(
        template.format(agent=agent) for agent in remote_agents
    )
    print(f"All remote agents:\n{remote_agents_string}")


def _main(argv: list[str] | None = None) -> None:
    del argv  # unused
    load_dotenv(os.path.join(project_root, ".env"))

    project_id = (
        FLAGS.project_id
        if FLAGS.project_id
        else os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("PROJECT_ID"))
    )
    location = (
        FLAGS.location if FLAGS.location else os.getenv("GOOGLE_CLOUD_LOCATION", os.getenv("REGION", "us-central1"))
    )
    bucket = (
        FLAGS.bucket
        if FLAGS.bucket
        else os.getenv("GOOGLE_CLOUD_STORAGE_BUCKET")
    )

    if not bucket and project_id:
        bucket = f"{project_id}-deploy-artifacts"

    print(f"PROJECT: {project_id}")
    print(f"LOCATION: {location}")
    print(f"BUCKET: {bucket}")

    if not project_id:
        print("Missing required environment variable: GOOGLE_CLOUD_PROJECT or PROJECT_ID")
        sys.exit(1)
    elif not location:
        print("Missing required environment variable: GOOGLE_CLOUD_LOCATION or REGION")
        sys.exit(1)
    elif not bucket:
        print("Missing required environment variable: GOOGLE_CLOUD_STORAGE_BUCKET")
        sys.exit(1)

    vertexai.init(
        project=project_id,
        location=location,
        staging_bucket=f"gs://{bucket}",
    )

    if FLAGS.list:
        list_agents()
    elif FLAGS.create:
        create()
    elif FLAGS.delete:
        if not FLAGS.resource_id:
            print("resource_id is required for delete")
            sys.exit(1)
        delete(FLAGS.resource_id)
    else:
        # Default behavior
        print("No command flag provided. Defaulting to --create.")
        create()

def main():
    app.run(_main)

if __name__ == "__main__":
    main()
