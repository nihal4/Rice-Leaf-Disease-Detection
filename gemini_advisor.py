# =============================================================================
# gemini_advisor.py — Gemini API integration using google-genai (new SDK)
# 4 classes: Bacterial_Leaf_Blight, Brown_Spot, Leaf_Blast, Tungro
# =============================================================================

import logging

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Disease name → Bangla translation
# --------------------------------------------------------------------------- #
DISEASE_BANGLA: dict[str, str] = {
    "Bacterial_Leaf_Blight": "ব্যাকটেরিয়াল লিফ ব্লাইট",
    "Brown_Spot":            "ব্রাউন স্পট",
    "Leaf_Blast":            "লিফ ব্লাস্ট",
    "Tungro":                "টুংরো",
}

# Fallback advice when Gemini is unreachable
_FALLBACK_ADVICE: dict[str, str] = {
    "Bacterial_Leaf_Blight": (
        "ব্যাকটেরিয়াল লিফ ব্লাইট রোগের জন্য:\n"
        "• আক্রান্ত পাতা ও গাছ সরিয়ে ফেলুন।\n"
        "• ক্ষেতে পানি নিষ্কাশনের ব্যবস্থা করুন।\n"
        "• কপার অক্সিক্লোরাইড (Copper Oxychloride) স্প্রে করুন।\n"
        "• নাইট্রোজেন সার কম ব্যবহার করুন।\n"
        "⚠️ পরামর্শের জন্য স্থানীয় কৃষি অফিসে যোগাযোগ করুন।"
    ),
    "Brown_Spot": (
        "ব্রাউন স্পট রোগের জন্য:\n"
        "• ম্যানকোজেব (Mancozeb) বা থায়োফানেট-মিথাইল স্প্রে করুন।\n"
        "• সুষম সার ব্যবহার করুন, বিশেষত পটাশ।\n"
        "• রোগাক্রান্ত গাছের অবশিষ্টাংশ পুড়িয়ে ফেলুন।\n"
        "⚠️ পরামর্শের জন্য স্থানীয় কৃষি অফিসে যোগাযোগ করুন।"
    ),
    "Leaf_Blast": (
        "লিফ ব্লাস্ট রোগের জন্য:\n"
        "• ট্রাইসাইক্লাজোল (Tricyclazole) বা ইসোপ্রোথিওলেন স্প্রে করুন।\n"
        "• নাইট্রোজেন সার অতিরিক্ত দেওয়া বন্ধ করুন।\n"
        "• রোগ-প্রতিরোধী ধানের জাত ব্যবহার করুন।\n"
        "⚠️ পরামর্শের জন্য স্থানীয় কৃষি অফিসে যোগাযোগ করুন।"
    ),
    "Tungro": (
        "টুংরো রোগের জন্য:\n"
        "• আক্রান্ত গাছ তুলে পুড়িয়ে ফেলুন।\n"
        "• সবুজ পাতাহপার (Green Leafhopper) পোকা দমনে ইমিডাক্লোপ্রিড স্প্রে করুন।\n"
        "• রোগ-প্রতিরোধী ধানের জাত ব্যবহার করুন।\n"
        "• একই সময়ে চাষ করুন যাতে পোকার বিস্তার কমে।\n"
        "⚠️ পরামর্শের জন্য স্থানীয় কৃষি অফিসে যোগাযোগ করুন।"
    ),
}

_GENERIC_FALLBACK = (
    "দুঃখিত, এই মুহূর্তে বিস্তারিত পরামর্শ দেওয়া সম্ভব হচ্ছে না।\n"
    "অনুগ্রহ করে স্থানীয় কৃষি বিশেষজ্ঞের সাথে যোগাযোগ করুন।"
)


class GeminiAdvisor:
    """
    Uses Google Gemini (gemini-2.0-flash) via the new google-genai SDK
    to generate Bangla treatment advice for detected rice leaf diseases.
    """

    def __init__(self, api_key: str):
        try:
            from google import genai
            self._client = genai.Client(api_key=api_key)
            self._model  = "gemini-2.0-flash"
            logger.info("Gemini client ready (model: %s)", self._model)
        except ImportError as exc:
            raise RuntimeError(
                "google-genai is not installed. Run: pip install google-genai"
            ) from exc
        except Exception as exc:
            logger.error("Failed to initialise Gemini: %s", exc)
            self._client = None

    def _build_prompt(self, disease_bangla: str) -> str:
        return (
            f"আমার ধান গাছের পাতায় '{disease_bangla}' রোগ ধরা পড়েছে।\n"
            "নিচের বিষয়গুলো সহজ বাংলায় কৃষকদের মতো করে বুঝিয়ে বলো:\n"
            "১. এই রোগ কী এবং কেন হয়? (২-৩ বাক্য)\n"
            "২. এখনই কী করণীয়? (৩-৪টি পয়েন্ট)\n"
            "৩. কোন ওষুধ বা স্প্রে ব্যবহার করবো? (নাম সহ)\n"
            "৪. ভবিষ্যতে কীভাবে প্রতিরোধ করবো? (২-৩টি পয়েন্ট)\n"
            "উত্তর শুধু বাংলায় দাও। সহজ ভাষায় লেখো।"
        )

    def get_advice(self, disease_name: str, confidence: float) -> str:
        disease_bangla = DISEASE_BANGLA.get(disease_name, disease_name)

        if self._client is None:
            logger.warning("Gemini client not initialised — using fallback.")
            return _FALLBACK_ADVICE.get(disease_name, _GENERIC_FALLBACK)

        try:
            logger.info("Calling Gemini for disease: %s", disease_name)
            response = self._client.models.generate_content(
                model=self._model,
                contents=self._build_prompt(disease_bangla),
            )
            advice = response.text.strip()
            logger.info("Gemini response received (%d chars).", len(advice))
            return advice
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            return _FALLBACK_ADVICE.get(disease_name, _GENERIC_FALLBACK)
