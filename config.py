# =============================================================================
# config.py — All configuration for Rice Disease Bot
# =============================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------------------
# Telegram
# -----------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# -----------------------------------------------------------------------------
# Gemini
# -----------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# -----------------------------------------------------------------------------
# Hugging Face — model hosted remotely, downloaded once and cached locally
# HF_MODEL_URL format:
#   https://huggingface.co/YOUR_HF_USERNAME/rice-disease-model/resolve/main/rice_disease_resnet50.onnx
# -----------------------------------------------------------------------------
HF_MODEL_URL = os.getenv(
    "HF_MODEL_URL",
    ""
)
HF_TOKEN = os.getenv("HF_TOKEN", "")   # leave empty if repo is public

# -----------------------------------------------------------------------------
# Model
# -----------------------------------------------------------------------------
CLASS_INDICES_PATH = os.getenv("CLASS_INDICES_PATH", "models/class_indices.json")
MODEL_CACHE_DIR    = os.getenv("MODEL_CACHE_DIR",    "models/cache")
IMAGE_SIZE         = (224, 224)

# -----------------------------------------------------------------------------
# Bot behaviour
# -----------------------------------------------------------------------------
MAX_IMAGE_SIZE_MB    = 10
CONFIDENCE_THRESHOLD = 0.50

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
LOG_LEVEL = "INFO"
