import os
import pytest
import httpx
import json

# Setup the endpoint depending on whether this is local or remote
ENDPOINT = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")

@pytest.mark.asyncio
async def test_full_agent_orchestration():
    """
    Sends a complex master prompt to the RootRouter.
    The goal is to trigger the full distributed waterfall.
    """
    print(f"\nSending payload to {ENDPOINT}")
    
    payload = {
        "user_id": "integration_tester_001",
        "prompt": "I need to travel to SFO for a convention next Tuesday and return next Friday. Can you build the entire itinerary?"
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
