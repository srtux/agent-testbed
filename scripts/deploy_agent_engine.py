"""Deployment script for all Agent Engine agents."""

import os
import sys
import shutil
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor
import json
import yaml

# Ensure we can import the agents from the local filesystem during deployment setup
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import vertexai
import google.cloud.storage
from google.oauth2.credentials import Credentials

# Monkeypatch google.cloud.storage.Client to inject access token if available
# This fixes the issue where Vertex AI SDK uploads to GCS using a client that falls back to ADC
original_storage_client = google.cloud.storage.Client

def custom_storage_client(*args, **kwargs):
    if 'credentials' not in kwargs:
        token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN")
        if token:
            kwargs['credentials'] = Credentials(token)
    return original_storage_client(*args, **kwargs)

google.cloud.storage.Client = custom_storage_client
from absl import app, flags
from dotenv import load_dotenv
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# Agents will be loaded dynamically in create() to ensure they are picked standalone.


FLAGS = flags.FLAGS
flags.DEFINE_string("project_id", None, "GCP project ID.")
flags.DEFINE_string("location", None, "GCP location.")
flags.DEFINE_string("bucket", None, "GCP bucket.")
flags.DEFINE_string("resource_id", None, "ReasoningEngine resource ID.")
flags.DEFINE_string("custom_domain", None, "Base custom domain for stable service URLs.")
flags.DEFINE_string("psc_network_attachment", None, "PSC Network Attachment for VPC egress.")
flags.DEFINE_string("vpc_project_id", None, "Project ID containing the VPC.")
flags.DEFINE_string("vpc_name", None, "VPC network name.")

flags.DEFINE_bool("list", False, "List all agents.")
flags.DEFINE_bool("create", False, "Creates new agents.")
flags.DEFINE_bool("delete", False, "Deletes an existing agent.")
flags.mark_bool_flags_as_mutual_exclusive(["create", "delete", "list"])


def manual_find_packages(base_dir):
    """Manually find packages by looking for directories with __init__.py."""
    packages = []
    for root, dirs, files in os.walk(base_dir):
        if "__init__.py" in files:
            # Get relative path and convert to package notation
            rel_path = os.path.relpath(root, base_dir)
            if rel_path == ".":
                continue
            packages.append(rel_path.replace(os.sep, "."))
    return packages


def create_agent(config, custom_domain, project_id, location, bucket, service_urls=None, existing_agents_lookup=None, psc_network_attachment=None, vpc_project_id=None, vpc_name=None) -> None:
    """Creates an agent engine for the given agent."""
    import importlib.util
    import cloudpickle

    agent_dir = os.path.abspath(os.path.join(project_root, config["dir"]))
    module_name = f"main_{config['name']}"
    spec = importlib.util.spec_from_file_location(module_name, os.path.join(agent_dir, "main.py"))
    agent_module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = agent_module

    spec.loader.exec_module(agent_module)

    # Register by value to ensure all standalone agent code is serialized
    cloudpickle.register_pickle_by_value(agent_module)
    
    # Dynamically register all nested packages inside the agent's directory
    # so cloudpickle serializes them by value as well, preventing ModuleNotFoundError on remote.
    for name, cp_module in list(sys.modules.items()):
        if hasattr(cp_module, "__file__") and cp_module.__file__:
            if cp_module.__file__.startswith(agent_dir):
                cloudpickle.register_pickle_by_value(cp_module)
    
    # Also register testbed_utils to prevent remote ModuleNotFoundError
    import testbed_utils.telemetry
    cloudpickle.register_pickle_by_value(testbed_utils.telemetry)
    
    import vertexai
    from google.oauth2.credentials import Credentials
    token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN")
    credentials = Credentials(token) if token else None

    vertexai.init(
        project=project_id,
        location=location,
        staging_bucket=f"gs://{bucket}",
        credentials=credentials,
    )

    agent_obj = agent_module.agent

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


    # Build service URLs - from custom domain or terraform outputs
    urls = {}
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
            "FLIGHT_SPECIALIST_AUDIENCE": service_urls.get('flight_specialist_audience', ''),
            "WEATHER_SPECIALIST_AUDIENCE": service_urls.get('weather_specialist_audience', ''),
            "PROFILE_MCP_AUDIENCE": service_urls.get('profile_mcp_audience', ''),
        }
    else:
        print(f"  Warning: No custom_domain or service_urls provided for {agent_obj.name}")

    # Build URL Audience Map for OIDC hook mapped back-channels
    import json
    audience_map = {}
    if service_urls:
        if service_urls.get('flight_specialist_url') and service_urls.get('flight_specialist_audience'):
            audience_map[service_urls['flight_specialist_url']] = service_urls['flight_specialist_audience']
        if service_urls.get('weather_specialist_url') and service_urls.get('weather_specialist_audience'):
            audience_map[service_urls['weather_specialist_url']] = service_urls['weather_specialist_audience']
        if service_urls.get('profile_mcp_url') and service_urls.get('profile_mcp_audience'):
            audience_map[service_urls['profile_mcp_url']] = service_urls['profile_mcp_audience']

    env_vars = {
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
        "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED": "true",
        "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
        "LOG_FORMAT": "JSON",
        "LOG_LEVEL": "INFO",
        "RUNNING_IN_AGENT_ENGINE": "true",
        "PYTHONPATH": "/code:/code/site-packages:/code/.venv/lib/python3.12/site-packages:.",
        "URL_AUDIENCE_MAP": json.dumps(audience_map),
        **urls,
    }

    # Config for Private Service Connect Interface
    psc_interface_config = None
    if psc_network_attachment:
        if not vpc_project_id or not vpc_name:
            print("  Warning: psc_network_attachment provided but vpc_project_id or vpc_name is missing. Skipping PSC config.")
        else:
            # Support reading comma-separated domains from environment
            dns_domains_str = os.environ.get("PSC_DNS_DOMAINS", "run.app.")
            dns_domains = [d.strip() for d in dns_domains_str.split(",") if d.strip()]
            
            dns_peering_configs = []
            for domain in dns_domains:
                dns_peering_configs.append({
                    "domain": domain,
                    "target_project": vpc_project_id,
                    "target_network": vpc_name,
                })
                
            psc_interface_config = {
                "network_attachment": psc_network_attachment,
                "dns_peering_configs": dns_peering_configs,
            }
            print(f"  Configuring Agent with PSC interface attached to {psc_network_attachment}")
            print(f"  DNS Peering Domains: {', '.join(dns_domains)}")

    print(f"🤖 Deploying {agent_obj.name}...")
    resource_name = None
    existing_resource_name = existing_agents_lookup.get(agent_obj.name) if existing_agents_lookup else None
    try:
        if existing_resource_name:
            print(f"🤖 Updating existing agent {agent_obj.name} ({existing_resource_name})...")
            remote_agent = agent_engines.update(
                resource_name=existing_resource_name,
                agent_engine=adk_app,
                requirements=requirements,
                env_vars=env_vars,
                psc_interface_config=psc_interface_config,
            )
        else:
            print(f"🤖 Creating new agent {agent_obj.name}...")
            remote_agent = agent_engines.create(
                adk_app,
                display_name=agent_obj.name,
                requirements=requirements,
                env_vars=env_vars,
                psc_interface_config=psc_interface_config,
            )
        resource_name = remote_agent.resource_name
        print(f"✅ Deployed remote agent {agent_obj.name}: {resource_name}")
    except Exception as e:
        print(f"❌ Error creating agent {agent_obj.name}: {e}")
        print("  Attempting to recover resource name via list()...")
        import time
        time.sleep(5)
        try:
            remote_agents = agent_engines.AgentEngine.list()
            for agent in remote_agents:
                if agent.display_name == agent_obj.name:
                    print(f"  ✅ Recovered resource name for {agent_obj.name}: {agent.resource_name}")
                    return agent.resource_name
        except Exception as list_e:
            print(f"  Failed to list agents during recovery: {list_e}")
        raise e
    print()
    return resource_name


def create(custom_domain, project_id, location, bucket, service_urls=None, psc_network_attachment=None, vpc_project_id=None, vpc_name=None) -> dict:
    """Deploy all configured ADK agents in parallel. Returns dict of agent_name -> resource_name."""
    agent_configs = [
        {"name": "RootRouter", "dir": "agents/RootRouter"},
        {"name": "BookingOrchestrator", "dir": "agents/BookingOrchestrator"}
    ]


    print("Listing existing agents...")
    existing_agents_lookup = {}
    outputs_path = os.path.join(project_root, "agent_engine_outputs.json")
    if os.path.exists(outputs_path):
        try:
            with open(outputs_path) as f:
                existing_agents_lookup = json.load(f)
                print(f"Loaded {len(existing_agents_lookup)} existing agents from agent_engine_outputs.json (fast fallback)")
        except Exception as e:
            print(f"Warning: Could not read agent_engine_outputs.json: {e}")

    if not existing_agents_lookup:
        try:
            remote_agents = agent_engines.AgentEngine.list()
            existing_agents_lookup = {agent.display_name: agent.resource_name for agent in remote_agents if getattr(agent, "display_name", "")}
            print(f"Found {len(existing_agents_lookup)} existing agents via list().")
        except Exception as e:
            print(f"Warning: Could not list existing agents: {e}")

    results = {}

    print(f"🚀 Deploying {len(agent_configs)} agents sequentially...")
    for config in agent_configs:
        try:
            resource_name = create_agent(config, custom_domain, project_id, location, bucket, service_urls, existing_agents_lookup, psc_network_attachment, vpc_project_id, vpc_name)
            results[config["name"]] = resource_name
            print(f"✅ Deployed remote agent {config['name']}: {resource_name}")
        except Exception as e:
            print(f"❌ Error deploying {config['name']}: {e}")


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
    psc_network_attachment = (
        FLAGS.psc_network_attachment
        if FLAGS.psc_network_attachment
        else os.getenv("PSC_NETWORK_ATTACHMENT")
    )
    vpc_project_id = (
        FLAGS.vpc_project_id
        if FLAGS.vpc_project_id
        else os.getenv("VPC_PROJECT_ID")
    )
    vpc_name = (
        FLAGS.vpc_name
        if FLAGS.vpc_name
        else os.getenv("VPC_NAME")
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

    from google.oauth2.credentials import Credentials
    token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN")
    credentials = Credentials(token) if token else None

    vertexai.init(
        project=project_id,
        location=location,
        staging_bucket=f"gs://{bucket}",
        credentials=credentials,
    )

    if FLAGS.list:
        list_agents()
    elif FLAGS.create:
        create(custom_domain, project_id, location, bucket, service_urls, psc_network_attachment, vpc_project_id, vpc_name)
    elif FLAGS.delete:
        if not FLAGS.resource_id:
            print("resource_id is required for delete")
            sys.exit(1)
        delete(FLAGS.resource_id)
    else:
        print("No command flag provided. Defaulting to --create.")
        create(custom_domain, project_id, location, bucket, service_urls, psc_network_attachment, vpc_project_id, vpc_name)

def main():
    app.run(_main)

if __name__ == "__main__":
    main()
