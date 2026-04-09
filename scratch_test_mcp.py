import os
import vertexai
from vertexai import agent_engines

vertexai.init(project="agent-o11y", location="us-central1")

ae = agent_engines.AgentEngine("projects/38829824347/locations/us-central1/reasoningEngines/1691533218391523328")

prompt = "I need to travel to SFO from JFK for a convention on May 12, 2026 and return on May 15, 2026. My member ID is M-12345. Can you build the entire itinerary?"

print(f"Sending prompt: {prompt}")
response = ae.stream_query(
    user_id="test_user_mcp",
    message=prompt
)

for event in response:
    print(event)
