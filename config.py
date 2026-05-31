# =============================================================================
# config.py — All configuration. Secrets loaded from environment only.
# NEVER hardcode secrets here — use Render environment variables or .env
# =============================================================================

import os
import sys
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    """Get env var or exit with a clear message — never expose the value."""
    val = os.getenv(key, "")
    return val

# -----------------------------------------------------------------------------
# Telegram
# -----------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")

# Webhook settings (required for Render web service)
# WEBHOOK_URL = your Render public URL, e.g. https://rice-bot.onrender.com
WEBHOOK_URL    = os.getenv("WEBHOOK_URL", "")
# Random secret so only Telegram can POST to your webhook endpoint
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# -----------------------------------------------------------------------------
# Gemini
# -----------------------------------------------------------------------------
GEMINI_API_KEY = _require("GEMINI_API_KEY")

# -----------------------------------------------------------------------------
# Hugging Face
# -----------------------------------------------------------------------------
HF_MODEL_URL = os.getenv(
    "HF_MODEL_URL",
    ""
)
HF_TOKEN = os.getenv("HF_TOKEN", "")  # empty = public repo

# -----------------------------------------------------------------------------
# Model
# -----------------------------------------------------------------------------
CLASS_INDICES_PATH = os.getenv("CLASS_INDICES_PATH", "")
MODEL_CACHE_DIR    = os.getenv("MODEL_CACHE_DIR",    "")
IMAGE_SIZE         = (224, 224)

# -----------------------------------------------------------------------------
# Bot behaviour
# -----------------------------------------------------------------------------
MAX_IMAGE_SIZE_MB    = 10
CONFIDENCE_THRESHOLD = 0.50

# -----------------------------------------------------------------------------
# Logging — never set to DEBUG in production (may expose request details)
# -----------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "")
