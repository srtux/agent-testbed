import os
import pytest
import httpx
import json
from dotenv import load_dotenv

# Ensure environment vars from .env are loaded (contains GOOGLE_CLOUD_PROJECT)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Setup the endpoint depending on whether this is local or remote
ENDPOINT = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")

@pytest.mark.asyncio
async def test_full_agent_orchestration():
    """
    Sends a complex master prompt to the RootRouter.
    The goal is to trigger the full distributed waterfall.
    """
    print(f"\nSending payload to {ENDPOINT}")
    
    prompt_text = "I need to travel to SFO for a convention next Tuesday and return next Friday. Can you build the entire itinerary?"
    user_id = "integration_tester_001"
    
    if ENDPOINT.startswith("projects/"):
        print(f"\nQuerying Vertex AI Reasoning Engine: {ENDPOINT}")
        import vertexai
        from vertexai import agent_engines
        
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        
        if not project_id:
            pytest.fail("GOOGLE_CLOUD_PROJECT is required to query Reasoning Engine.")
            
        print(f"Initializing vertexai with project={project_id}, location={location}")
        vertexai.init(project=project_id, location=location)
        
        ae = agent_engines.AgentEngine(ENDPOINT)
        
        # Use stream_query as recommended for Reasoning Engines
        response = ae.stream_query(
            user_id=user_id,
            message=prompt_text
        )
        
        final_response = ""
        for event in response:
            # Handle both dictionary (AgentEngine) and object (local runner) formats
            is_dict = isinstance(event, dict)
            content = event.get("content") if is_dict else getattr(event, "content", None)
            
            if content:
                parts = content.get("parts", []) if is_dict else getattr(content, "parts", [])
                for part in parts:
                    part_text = part.get("text") if is_dict else getattr(part, "text", None)
                    if part_text:
                        print(part_text, end="", flush=True)
                        final_response += part_text
                        
        assert final_response, "No response from Reasoning Engine."
        data = {"status": "complete", "orchestration_summary": final_response}
        
    else:
        payload = {
            "user_id": user_id,
            "prompt": prompt_text
        }
        
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(ENDPOINT, json=payload)
            
            # 1. We successfully connected to the router
            assert response.status_code == 200, f"Router failed with status {response.status_code}: {response.text}"
            
            data = response.json()
            print(f"\nRouter Response:\n{json.dumps(data, indent=2)}")
            
            # 2. It successfully finalized
            assert data.get("status") == "complete", "Did not complete successfully."
            
    # 3. Ensure the summary actually has text reflecting the downstream nodes
    summary = data.get("orchestration_summary", "").lower()
    
    # The prompt forces a trip to SFO which means:
    # 1. CR Profile is accessed for loyalty tier/home airport
    # 2. FlightSpecialist routes hotels
    # 3. WeatherSpecialist fetches conditions
    # 4. BookingOrchestrator finalizes it and gives a summary
    assert len(summary) > 20, "Summary is too short or missing."
    assert any(x in summary for x in ["sfo", "san francisco", "cloud suites"]), "Summary did not recognize destination."
