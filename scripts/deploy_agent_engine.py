"""Deployment script for all Agent Engine agents."""

import os
import sys

# Ensure we can import the agents
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import vertexai
import shutil
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
flags.DEFINE_string("custom_domain", None, "Base custom domain for stable service URLs.")

flags.DEFINE_bool("list", False, "List all agents.")
flags.DEFINE_bool("create", False, "Creates new agents.")
flags.DEFINE_bool("delete", False, "Deletes an existing agent.")
flags.mark_bool_flags_as_mutual_exclusive(["create", "delete", "list"])


def create_agent(agent_obj, custom_domain, service_urls=None) -> None:
    """Creates an agent engine for the given agent."""
    adk_app = AdkApp(agent=agent_obj)

    # Core dependencies needed for Testbed ADK agents
    requirements = [
        "fastapi>=0.135.1",
        "google-adk>=1.26.0",
        "mcp>=1.26.0",
        "opentelemetry-api>=1.38.0",
        "opentelemetry-exporter-gcp-logging",
        "opentelemetry-exporter-gcp-monitoring",
        "opentelemetry-exporter-otlp-proto-grpc",
        "opentelemetry-instrumentation-fastapi>=0.59b0",
        "opentelemetry-instrumentation-google-genai>=0.7b0",
        "opentelemetry-instrumentation-httpx>=0.59b0",
        "opentelemetry-instrumentation-requests>=0.59b0",
        "opentelemetry-instrumentation-vertexai>=2.0b0",
        "opentelemetry-sdk>=1.38.0",
        "uvicorn>=0.41.0",
        "pydantic>=2.10.6,<3.0.0",
        "google-cloud-aiplatform[adk,agent-engines]>=1.93.0",
        "google-genai>=1.5.0",
        "httpx>=0.28.0",
        "requests>=2.32.0"
    ]

    # We create a temporary staging directory to package 'agents' and 'testbed_utils'
    # as top-level packages for the remote engine.
    staging_dir = os.path.join(project_root, f"staging_{agent_obj.name}")
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir)
    shutil.copytree(os.path.join(project_root, "agents"), os.path.join(staging_dir, "agents"), dirs_exist_ok=True)
    shutil.copytree(os.path.join(project_root, "testbed_utils"), os.path.join(staging_dir, "testbed_utils"), dirs_exist_ok=True)

    # Build service URLs - from custom domain or terraform outputs
    if custom_domain:
        urls = {
            "FLIGHT_SPECIALIST_URL": f"https://flight-specialist.{custom_domain}/chat",
            "WEATHER_SPECIALIST_URL": f"https://weather-specialist.{custom_domain}/chat",
            "PROFILE_MCP_URL": f"https://profile-mcp.{custom_domain}/sse",
            "INVENTORY_MCP_URL": f"https://inventory-mcp.{custom_domain}/sse",
            "HOTEL_SPECIALIST_URL": f"https://hotel-specialist.{custom_domain}/chat",
            "CAR_RENTAL_SPECIALIST_URL": f"https://car-rental.{custom_domain}/chat",
        }
    elif service_urls:
        urls = {
            "FLIGHT_SPECIALIST_URL": f"{service_urls.get('flight_specialist_url', '')}/chat",
            "WEATHER_SPECIALIST_URL": f"{service_urls.get('weather_specialist_url', '')}/chat",
            "PROFILE_MCP_URL": f"{service_urls.get('profile_mcp_url', '')}/sse",
            "INVENTORY_MCP_URL": f"{service_urls.get('inventory_mcp_url', '')}/sse",
            "HOTEL_SPECIALIST_URL": f"{service_urls.get('hotel_specialist_url', '')}/chat",
            "CAR_RENTAL_SPECIALIST_URL": f"{service_urls.get('car_rental_url', '')}/chat",
        }
    else:
        urls = {}
        print(f"  Warning: No custom_domain or service_urls provided for {agent_obj.name}")

    env_vars = {
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
        "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED": "true",
        "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
        "LOG_FORMAT": "JSON",
        "LOG_LEVEL": "INFO",
        "RUNNING_IN_AGENT_ENGINE": "true",
        "PYTHONPATH": ".",
        **urls,
    }

    print(f"🤖 Deploying {agent_obj.name}...")
    resource_name = None
    try:
        remote_agent = agent_engines.create(
            adk_app,
            display_name=agent_obj.name,
            requirements=requirements,
            extra_packages=[staging_dir],
            env_vars=env_vars
        )
        resource_name = remote_agent.resource_name
        print(f"✅ Created remote agent {agent_obj.name}: {resource_name}")
    finally:
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir)
    print()
    return resource_name


import concurrent.futures
import json

def create(custom_domain, service_urls=None) -> dict:
    """Deploy all configured ADK agents in parallel. Returns dict of agent_name -> resource_name."""
    agents = [root_router_agent, booking_agent]
    results = {}

    print(f"🚀 Deploying {len(agents)} agents in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {executor.submit(create_agent, agent, custom_domain, service_urls): agent for agent in agents}
        for future in concurrent.futures.as_completed(futures):
            agent = futures[future]
            try:
                resource_name = future.result()
                if resource_name:
                    results[agent.name] = resource_name
            except Exception as e:
                print(f"❌ Error deploying {agent.name}: {e}")

    # Write results to a JSON file for the deploy orchestrator to consume
    output_path = os.path.join(project_root, "agent_engine_outputs.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Agent Engine outputs written to {output_path}")
    return results


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
    custom_domain = (
        FLAGS.custom_domain
        if FLAGS.custom_domain
        else os.getenv("CUSTOM_DOMAIN")
    )

    if not bucket and project_id:
        bucket = f"{project_id}-deploy-artifacts"

    print(f"PROJECT: {project_id}")
    print(f"LOCATION: {location}")
    print(f"BUCKET: {bucket}")
    print(f"CUSTOM_DOMAIN: {custom_domain}")

    if not project_id:
        print("Missing required: GOOGLE_CLOUD_PROJECT or PROJECT_ID or --project_id")
        sys.exit(1)
    elif not location:
        print("Missing required: GOOGLE_CLOUD_LOCATION or REGION or --location")
        sys.exit(1)
    elif not bucket:
        print("Missing required: GOOGLE_CLOUD_STORAGE_BUCKET or --bucket")
        sys.exit(1)

    if not custom_domain:
        print("No custom domain set. Will read service URLs from terraform outputs or env vars.")

    # Read service_urls from JSON file if it exists (written by deploy.py)
    service_urls_path = os.path.join(project_root, "terraform_service_urls.json")
    service_urls = None
    if os.path.exists(service_urls_path):
        with open(service_urls_path) as f:
            service_urls = json.load(f)
        print(f"Loaded service URLs from {service_urls_path}")

    vertexai.init(
        project=project_id,
        location=location,
        staging_bucket=f"gs://{bucket}",
    )

    if FLAGS.list:
        list_agents()
    elif FLAGS.create:
        create(custom_domain, service_urls)
    elif FLAGS.delete:
        if not FLAGS.resource_id:
            print("resource_id is required for delete")
            sys.exit(1)
        delete(FLAGS.resource_id)
    else:
        print("No command flag provided. Defaulting to --create.")
        create(custom_domain, service_urls)

def main():
    app.run(_main)

if __name__ == "__main__":
    main()
