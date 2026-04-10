import os

# Model versions
DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")
DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

# Feature Flags
ENABLE_DETAILED_LOGGING = (
    os.environ.get("ENABLE_DETAILED_LOGGING", "true").lower() == "true"
)

# Mock fare data for local compute tools
FARE_TABLE = {
    "SFO": 350,
    "JFK": 450,
    "LAX": 320,
    "ORD": 380,
    "LHR": 850,
    "CDG": 820,
    "NRT": 950,
    "SYD": 1100,
}

CAR_RATE_TABLE = {
    "economy": 45,
    "compact": 55,
    "midsize": 70,
    "suv": 95,
    "luxury": 150,
}

LOYALTY_DISCOUNTS = {
    "Gold": 0.15,
    "Silver": 0.10,
    "Bronze": 0.05,
}
