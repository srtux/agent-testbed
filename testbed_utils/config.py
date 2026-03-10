import os

# Model versions
DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")
DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

# Feature Flags
ENABLE_DETAILED_LOGGING = os.environ.get("ENABLE_DETAILED_LOGGING", "true").lower() == "true"
