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

    class MyAdkApp(AdkApp):
        def query(self, *args, **kwargs):
            response_text = ""
            for event in self.stream_query(*args, **kwargs):
                if hasattr(event, "content") and event.content:
                    for part in event.content.parts:
                        if part.text:
                            response_text += part.text
            return response_text

        def stream_query(self, *args, **kwargs):
            yield from super().stream_query(*args, **kwargs)

    adk_app = MyAdkApp(agent=agent_obj)

    # Core dependencies needed for Testbed ADK agents
    requirements = [
        "absl-py==2.4.0",
        "aiohappyeyeballs==2.6.1",
        "aiohttp==3.13.5",
        "aiosignal==1.4.0",
        "aiosqlite==0.22.1",
        "alembic==1.18.4",
        "annotated-doc==0.0.4",
        "annotated-types==0.7.0",
        "anyio==4.13.0",
        "asgiref==3.11.1",
        "attrs==26.1.0",
        "authlib==1.6.9",
        "certifi==2026.2.25",
        "cffi==2.0.0",
        "charset-normalizer==3.4.7",
        "click==8.3.2",
        "cloudpickle==3.1.2",
        "cryptography==46.0.7",
        "distro==1.9.0",
        "docstring-parser==0.17.0",
        "fastapi==0.135.3",
        "frozenlist==1.8.0",
        "google-adk==2.0.0a2",
        "google-api-core==2.30.2",
        "google-api-python-client==2.194.0",
        "google-auth==2.49.1",
        "google-auth-httplib2==0.3.1",
        "google-cloud-aiplatform==1.146.0",
        "google-cloud-appengine-logging==1.9.0",
        "google-cloud-audit-log==0.5.0",
        "google-cloud-bigquery==3.41.0",
        "google-cloud-bigquery-storage==2.37.0",
        "google-cloud-bigtable==2.36.0",
        "google-cloud-core==2.5.1",
        "google-cloud-dataplex==2.18.0",
        "google-cloud-discoveryengine==0.13.12",
        "google-cloud-iam==2.22.0",
        "google-cloud-logging==3.15.0",
        "google-cloud-monitoring==2.30.0",
        "google-cloud-pubsub==2.36.0",
        "google-cloud-resource-manager==1.17.0",
        "google-cloud-secret-manager==2.27.0",
        "google-cloud-spanner==3.64.0",
        "google-cloud-speech==2.38.0",
        "google-cloud-storage==3.10.1",
        "google-cloud-trace==1.19.0",
        "google-crc32c==1.8.0",
        "google-genai==1.71.0",
        "google-resumable-media==2.8.2",
        "googleapis-common-protos==1.74.0",
        "graphviz==0.21",
        "grpc-google-iam-v1==0.14.4",
        "grpc-interceptor==0.15.4",
        "grpcio==1.80.0",
        "grpcio-status==1.80.0",
        "h11==0.16.0",
        "httpcore==1.0.9",
        "httplib2==0.31.2",
        "httpx==0.28.1",
        "httpx-sse==0.4.3",
        "idna==3.11",
        "importlib-metadata==8.7.1",
        "iniconfig==2.3.0",
        "jsonschema==4.26.0",
        "jsonschema-specifications==2025.9.1",
        "mako==1.3.10",
        "markupsafe==3.0.3",
        "mcp==1.27.0",
        "mmh3==5.2.1",
        "multidict==6.7.1",
        "opentelemetry-api==1.38.0",
        "opentelemetry-exporter-gcp-logging==1.11.0a0",
        "opentelemetry-exporter-gcp-monitoring==1.11.0a0",
        "opentelemetry-exporter-gcp-trace==1.11.0",
        "opentelemetry-exporter-otlp-proto-common==1.38.0",
        "opentelemetry-exporter-otlp-proto-grpc==1.38.0",
        "opentelemetry-exporter-otlp-proto-http==1.38.0",
        "opentelemetry-instrumentation==0.59b0",
        "opentelemetry-instrumentation-asgi==0.59b0",
        "opentelemetry-instrumentation-fastapi==0.59b0",
        "opentelemetry-instrumentation-google-genai==0.7b0",
        "opentelemetry-instrumentation-httpx==0.59b0",
        "opentelemetry-instrumentation-requests==0.59b0",
        "opentelemetry-instrumentation-vertexai==2.0b0",
        "opentelemetry-proto==1.38.0",
        "opentelemetry-resourcedetector-gcp==1.11.0a0",
        "opentelemetry-sdk==1.38.0",
        "opentelemetry-semantic-conventions==0.59b0",
        "opentelemetry-util-genai==0.3b0",
        "opentelemetry-util-http==0.59b0",
        "packaging==26.0",
        "pluggy==1.6.0",
        "propcache==0.4.1",
        "proto-plus==1.27.2",
        "protobuf==6.33.6",
        "pyarrow==23.0.1",
        "pyasn1==0.6.3",
        "pyasn1-modules==0.4.2",
        "pycparser==3.0",
        "pydantic==2.12.5",
        "pydantic-core==2.41.5",
        "pydantic-settings==2.13.1",
        "pygments==2.20.0",
        "pyjwt==2.12.1",
        "pyopenssl==26.0.0",
        "pyparsing==3.3.2",
        "pytest==9.0.3",
        "pytest-asyncio==1.3.0",
        "python-dateutil==2.9.0.post0",
        "python-dotenv==1.2.2",
        "python-multipart==0.0.24",
        "pyyaml==6.0.3",
        "referencing==0.37.0",
        "requests==2.33.1",
        "rpds-py==0.30.0",
        "six==1.17.0",
        "sniffio==1.3.1",
        "sqlalchemy==2.0.49",
        "sqlalchemy-spanner==1.17.3",
        "sqlparse==0.5.5",
        "sse-starlette==3.3.4",
        "starlette==0.52.1",
        "tenacity==9.1.4",
        "typing-extensions==4.15.0",
        "typing-inspection==0.4.2",
        "tzlocal==5.3.1",
        "uritemplate==4.2.0",
        "urllib3==2.6.3",
        "uvicorn==0.44.0",
        "watchdog==6.0.0",
        "websockets==15.0.1",
        "wrapt==1.17.3",
        "yarl==1.23.0",
        "zipp==3.23.0"
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
