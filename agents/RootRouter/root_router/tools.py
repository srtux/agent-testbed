"""Pure local tools for RootRouter."""

import re


async def extract_travel_intent(user_input: str) -> dict:
    """Analyzes the user's input to extract traveling fields (Destination, Dates)."""
    destination = None
    dates = None

    date_pattern = re.findall(
        r"\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}",
        user_input,
        re.IGNORECASE,
    )
    if date_pattern:
        dates = ", ".join(date_pattern)

    return {"destination": destination, "dates": dates, "raw_input": user_input}
