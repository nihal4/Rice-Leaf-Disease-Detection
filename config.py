# =============================================================================
# config.py — All configuration. Secrets loaded from environment only.
# NEVER hardcode secrets here — use Render environment variables or .env
# =============================================================================

import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Get env var or exit immediately with a clear message if missing."""
    val = os.getenv(key, "").strip()
    if not val:
        print(f"❌ FATAL: Required environment variable '{key}' is not set.")
        sys.exit(1)
    return val


# -----------------------------------------------------------------------------
# Telegram
# -----------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")

WEBHOOK_URL    = _require("WEBHOOK_URL")
WEBHOOK_SECRET = _require("WEBHOOK_SECRET")

# -----------------------------------------------------------------------------
# Gemini
# -----------------------------------------------------------------------------
GEMINI_API_KEY = _require("GEMINI_API_KEY")

# -----------------------------------------------------------------------------
# Hugging Face
# -----------------------------------------------------------------------------
HF_MODEL_URL = _require("HF_MODEL_URL")
HF_TOKEN     = os.getenv("HF_TOKEN", "")   # empty = public repo

# -----------------------------------------------------------------------------
# Model
# -----------------------------------------------------------------------------
CLASS_INDICES_PATH = _require("CLASS_INDICES_PATH")
MODEL_CACHE_DIR    = os.getenv("MODEL_CACHE_DIR", "models/cache")
IMAGE_SIZE         = (224, 224)

# -----------------------------------------------------------------------------
# Bot behaviour
# -----------------------------------------------------------------------------
MAX_IMAGE_SIZE_MB    = 30
CONFIDENCE_THRESHOLD = 0.50
RATE_LIMIT_SECONDS   = 5       # min seconds between requests per user

# -----------------------------------------------------------------------------
# Logging — never set to DEBUG in production (may expose request details)
# -----------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")