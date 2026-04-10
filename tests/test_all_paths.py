import logging
import os
import importlib
import importlib.util

import pytest
import vertexai
from vertexai import agent_engines

logging.basicConfig(level=logging.INFO)

if importlib.util.find_spec("dotenv") is not None:
    load_dotenv = importlib.import_module("dotenv").load_dotenv
    load_dotenv(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    )


def test_all_paths_waterfall():
    """
    Test that invokes all paths in the multi-agent system:
    AE Agent -> (AE Agent, Cloud Run MCP, Cloud Run Agent, GKE MCP, GKE Agent)
    using the Vertex AI SDK.
    """
    endpoint = os.environ.get("ROOT_ROUTER_ENDPOINT") or os.environ.get(
        "ROOT_ROUTER_URL"
    )
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "agent-o11y")

    if not endpoint:
        pytest.skip("ROOT_ROUTER_ENDPOINT or ROOT_ROUTER_URL not set")

    if not endpoint.startswith("projects/"):
        pytest.skip(
            "This test requires a Vertex AI Reasoning Engine resource ID (starts with projects/)"
        )

    # Extract ID from resource name
    engine_id = endpoint.split("/")[-1]

    # Initialize Vertex AI
    vertexai.init(project=project_id, location="us-central1")

    # Get the existing engine
    ae = agent_engines.get(engine_id)

    # Create a dummy session ID
    import uuid

    session_id = str(uuid.uuid4())
    user_id = "all_paths_tester"

    # Using session directly in stream_query
    print(f"Using session {session_id} for user {user_id}...")

    # Sequence of prompts to trigger all components
    # Adding member ID to all prompts as a workaround for missing session state
    prompts = [
        "I need to travel to SFO from JFK on May 12, 2026 and return on May 15, 2026. My member ID is M-12345.",  # Triggers Profile_MCP (Cloud Run MCP)
        "Find roundtrip flights for these dates. My member ID is M-12345.",  # Triggers FlightSpecialist (Cloud Run Agent)
        "I need a luxury hotel in SFO. My member ID is M-12345.",  # Triggers HotelSpecialist (GKE Agent) and likely Inventory_MCP (GKE MCP)
        "Add a SUV to my booking. My member ID is M-12345.",  # Triggers CarRentalSpecialist (GKE Agent)
        "Finalize and book the itinerary. My member ID is M-12345.",  # Triggers BookingOrchestrator (AE Agent)
    ]

    for i, prompt in enumerate(prompts):
        print(f"\n--- Turn {i + 1}: {prompt} ---")
        response = ae.stream_query(user_id=user_id, message=prompt)

        full_response = ""
        event_count = 0
        for event in response:
            event_count += 1
            print(f"\nEvent: {event}")

            # Extract text handling both dict and object
            text = ""
            if isinstance(event, dict):
                content = event.get("content")
                if content:
                    parts = content.get("parts")
                    if parts:
                        for part in parts:
                            if (
                                isinstance(part, dict)
                                and "text" in part
                                and part["text"]
                            ):
                                text = part["text"]
            else:
                if hasattr(event, "content") and event.content:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            text = part.text

            if text:
                full_response += text
                print(text, end="", flush=True)

        assert event_count > 0, f"No events received in Turn {i + 1}"
        print(
            f"\nTurn {i + 1} completed with {event_count} events. Text response length: {len(full_response)}"
        )

    print("\nAll turns completed successfully!")
