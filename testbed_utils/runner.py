"""Shared helper for running ADK agents and collecting text responses."""

import uuid
from google.genai import types


async def run_agent(runner, user_id: str, prompt: str, session_id: str | None = None) -> str | None:
    """Run an ADK agent and collect the full text response.

    Args:
        runner: An InMemoryRunner instance.
        user_id: User ID for the session.
        prompt: The prompt text to send.
        session_id: Optional session ID (defaults to a new UUID).

    Returns:
        The concatenated text response, or None if the agent produced no text.
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    final_response = None
    message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    return final_response
