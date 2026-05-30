# =============================================================================
# predictor.py — Remote inference via Hugging Face hosted ONNX model
# No local model file needed — downloads and caches on first call
# =============================================================================

import json
import logging
import os
from io import BytesIO

import numpy as np
import requests
from PIL import Image

logger = logging.getLogger(__name__)


class RiceLeafPredictor:
    """
    Runs inference using an ONNX model hosted on Hugging Face Hub.
    The model is downloaded once and cached locally in models/cache/
    so subsequent restarts are instant.
    """

    def __init__(
        self,
        hf_model_url: str,
        hf_token: str,
        class_indices_path: str,
        image_size: tuple,
        cache_dir: str = "models/cache",
    ):
        """
        Parameters
        ----------
        hf_model_url       : Full URL to the .onnx file on Hugging Face
                             e.g. https://huggingface.co/YOUR_USER/rice-disease-model/resolve/main/rice_disease_resnet50.onnx
        hf_token           : Hugging Face read token (for private repos; can be empty for public)
        class_indices_path : path to class_indices.json
        image_size         : (width, height) e.g. (224, 224)
        cache_dir          : local folder to cache the downloaded model
        """
        self.image_size = image_size
        self.hf_model_url = hf_model_url
        self.hf_token = hf_token

        # ------------------------------------------------------------------ #
        # Load class indices
        # ------------------------------------------------------------------ #
        logger.info("Loading class indices from: %s", class_indices_path)
        with open(class_indices_path, "r", encoding="utf-8") as f:
            raw: dict = json.load(f)
        self.class_names: dict[int, str] = {v: k for k, v in raw.items()}
        logger.info("Classes: %s", self.class_names)

        # ------------------------------------------------------------------ #
        # Download model to cache if not already present
        # ------------------------------------------------------------------ #
        os.makedirs(cache_dir, exist_ok=True)
        model_filename = hf_model_url.split("/")[-1]
        self.cached_model_path = os.path.join(cache_dir, model_filename)

        if os.path.isfile(self.cached_model_path):
            logger.info("Using cached model: %s", self.cached_model_path)
        else:
            self._download_model()

        # ------------------------------------------------------------------ #
        # Load ONNX Runtime session from cached file
        # ------------------------------------------------------------------ #
        logger.info("Loading ONNX model from cache…")
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            self.session = ort.InferenceSession(
                self.cached_model_path,
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            self.input_name  = self.session.get_inputs()[0].name
            self.output_name = self.session.get_outputs()[0].name
            logger.info("ONNX session ready | input='%s'", self.input_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to load ONNX model: {exc}") from exc

        self._warmup()

    # ---------------------------------------------------------------------- #

    def _download_model(self) -> None:
        """Download the ONNX model from Hugging Face to local cache."""
        logger.info("Downloading model from Hugging Face: %s", self.hf_model_url)
        print("⬇️  Downloading model from Hugging Face (one-time, please wait)…")

        headers = {}
        if self.hf_token:
            headers["Authorization"] = f"Bearer {self.hf_token}"

        try:
            response = requests.get(self.hf_model_url, headers=headers, stream=True, timeout=120)
            response.raise_for_status()

            total = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(self.cached_model_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r   {pct:.1f}% ({downloaded // (1024*1024)} MB / {total // (1024*1024)} MB)", end="", flush=True)

            print(f"\n✅ Model downloaded and cached at: {self.cached_model_path}")
            logger.info("Model downloaded: %.1f MB", os.path.getsize(self.cached_model_path) / (1024*1024))

        except requests.exceptions.RequestException as exc:
            # Clean up partial download
            if os.path.isfile(self.cached_model_path):
                os.remove(self.cached_model_path)
            raise RuntimeError(
                f"Failed to download model from Hugging Face.\n"
                f"URL: {self.hf_model_url}\n"
                f"Error: {exc}\n\n"
                "Check that:\n"
                "1. HF_MODEL_URL is correct in config.py\n"
                "2. The model repo is public (or HF_TOKEN is set)\n"
            ) from exc

    def _warmup(self) -> None:
        dummy = np.zeros((1, *self.image_size, 3), dtype=np.float32)
        self.session.run([self.output_name], {self.input_name: dummy})
        logger.info("Model warm-up complete.")

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    def preprocess_image(self, image_bytes: bytes) -> np.ndarray:
        try:
            img = Image.open(BytesIO(image_bytes))
        except Exception as exc:
            raise ValueError(f"Cannot open image: {exc}") from exc

        img = img.convert("RGB")
        img = img.resize(self.image_size, Image.LANCZOS)
        arr = np.array(img, dtype=np.float32) / 255.0
        return np.expand_dims(arr, axis=0)

    def predict(self, image_bytes: bytes, confidence_threshold: float = 0.50) -> dict:
        preprocessed = self.preprocess_image(image_bytes)
        outputs = self.session.run([self.output_name], {self.input_name: preprocessed})
        probs = outputs[0][0]

        predicted_idx = int(np.argmax(probs))
        confidence    = float(probs[predicted_idx])
        class_name    = self.class_names[predicted_idx]

        return {
            "class_name":        class_name,
            "confidence":        confidence,
            "all_probs":         {self.class_names[i]: float(probs[i]) for i in range(len(probs))},
            "is_low_confidence": confidence < confidence_threshold,
        }
