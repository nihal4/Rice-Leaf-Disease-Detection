# =============================================================================
# bot.py — Rice Leaf Disease Telegram Bot  (secured)
# - Pure webhook mode (no polling / no 409 Conflict)
# - aiohttp serves webhook + /healthz on the same PORT
# - Webhook secret validated on every incoming request
# - Per-user rate limiting
# - Keep-alive self-ping to prevent Render free-tier sleep
# =============================================================================

import asyncio
import logging
import os
import sys
import time
from datetime import datetime

import aiohttp
from aiohttp import web
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from gemini_advisor import DISEASE_BANGLA, GeminiAdvisor
from predictor import RiceLeafPredictor

# --------------------------------------------------------------------------- #
# Logging — suppress httpx so the token never appears in logs
# --------------------------------------------------------------------------- #
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Globals
# --------------------------------------------------------------------------- #
predictor: RiceLeafPredictor | None = None
gemini: GeminiAdvisor | None        = None

# Per-user rate limiting  {user_id: last_request_timestamp}
_last_request: dict[int, float] = {}

DISEASE_EMOJI: dict[str, str] = {
    "Bacterial_Leaf_Blight": "🔴",
    "Brown_Spot":            "🟤",
    "Leaf_Blast":            "💥",
    "Tungro":                "🟡",
}


# =========================================================================== #
# /start
# =========================================================================== #
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🌾 *ধান রোগ নির্ণয় বট-এ স্বাগতম!*\n\n"
        "আমি আপনার ধান গাছের পাতার ছবি দেখে রোগ "
        "শনাক্ত করতে পারি এবং চিকিৎসার পরামর্শ দিতে পারি।\n\n"
        "📸 *কীভাবে ব্যবহার করবেন:*\n"
        "১. একটি পাতা গাছ থেকে তুলুন\n"
        "২. সাদা কাগজের উপর রাখুন\n"
        "৩. পাতার ছবি তুলে এই বটে পাঠান\n\n"
        "আমি যে রোগগুলো চিনতে পারি:\n"
        "🔴 ব্যাকটেরিয়াল লিফ ব্লাইট\n"
        "🟤 ব্রাউন স্পট\n"
        "💥 লিফ ব্লাস্ট\n"
        "🟡 টুংরো\n\n"
        "এখনই একটি পাতার ছবি পাঠান! 👇",
        parse_mode=ParseMode.MARKDOWN,
    )


# =========================================================================== #
# /help
# =========================================================================== #
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ℹ️ *সাহায্য / Help*\n\n"
        "📸 *ভালো ছবি তোলার নিয়ম:*\n"
        "• পাতাটি সাদা কাগজের উপর রাখুন\n"
        "• ভালো আলোতে ছবি তুলুন\n"
        "• পাতার পুরো অংশ ছবিতে ধরুন\n"
        "• ঝাপসা বা অন্ধকারে তোলা ছবি পাঠাবেন না\n\n"
        "🤖 *এই বট কী করতে পারে:*\n"
        "• ধান পাতার ছবি দেখে রোগ শনাক্ত করতে পারে\n"
        "• রোগের নাম বাংলায় জানাতে পারে\n"
        "• চিকিৎসার পরামর্শ বাংলায় দিতে পারে\n\n"
        "❌ *এই বট যা করতে পারে না:*\n"
        "• ধান ছাড়া অন্য ফসলের রোগ চিনতে পারে না\n"
        "• পেশাদার কৃষি বিশেষজ্ঞের বিকল্প নয়\n\n"
        "🌾 *যে ৪টি রোগ চেনা যায়:*\n"
        "১. 🔴 ব্যাকটেরিয়াল লিফ ব্লাইট\n"
        "২. 🟤 ব্রাউন স্পট\n"
        "৩. 💥 লিফ ব্লাস্ট\n"
        "৪. 🟡 টুংরো\n\n"
        "📞 গুরুতর সমস্যায় স্থানীয় কৃষি অফিসে যোগাযোগ করুন।",
        parse_mode=ParseMode.MARKDOWN,
    )


# =========================================================================== #
# Photo handler  (with rate limiting)
# =========================================================================== #
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user    = update.effective_user
    user_id = user.id if user else 0
    chat_id = update.effective_chat.id
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Rate limiting ──────────────────────────────────────────────────────── #
    now     = time.monotonic()
    elapsed = now - _last_request.get(user_id, 0)
    if elapsed < config.RATE_LIMIT_SECONDS:
        wait = int(config.RATE_LIMIT_SECONDS - elapsed) + 1
        await update.message.reply_text(
            f"⏳ একটু অপেক্ষা করুন। {wait} সেকেন্ড পরে আবার চেষ্টা করুন।"
        )
        return
    _last_request[user_id] = now

    # ── Download image ─────────────────────────────────────────────────────── #
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    wait_msg = await update.message.reply_text("⏳ ছবি বিশ্লেষণ করা হচ্ছে...")

    try:
        photo     = update.message.photo[-1]
        file_size = photo.file_size or 0
        if file_size > config.MAX_IMAGE_SIZE_MB * 1024 * 1024:
            await wait_msg.edit_text(
                f"❌ ছবিটি অনেক বড় ({file_size // (1024*1024)} MB)। "
                f"{config.MAX_IMAGE_SIZE_MB} MB-এর ছোট ছবি পাঠান।"
            )
            return
        photo_file  = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await photo_file.download_as_bytearray())
    except Exception as exc:
        logger.error("user_id=%s | Download error: %s", user_id, type(exc).__name__)
        await wait_msg.edit_text("❌ ছবি ডাউনলোড করা সম্ভব হয়নি। আবার চেষ্টা করুন।")
        return

    # ── Run inference ──────────────────────────────────────────────────────── #
    try:
        result = predictor.predict(image_bytes, config.CONFIDENCE_THRESHOLD)
    except ValueError:
        await wait_msg.edit_text("❌ ছবিটি পড়া সম্ভব হয়নি। ভিন্ন ছবি পাঠান।")
        return
    except Exception as exc:
        logger.error("user_id=%s | Prediction error: %s", user_id, type(exc).__name__)
        await wait_msg.edit_text("❌ দুঃখিত, ছবিটি বিশ্লেষণ করা সম্ভব হয়নি। আবার চেষ্টা করুন।")
        return

    class_name     = result["class_name"]
    confidence     = result["confidence"]
    is_low_conf    = result["is_low_confidence"]
    conf_pct       = round(confidence * 100, 1)
    disease_bangla = DISEASE_BANGLA.get(class_name, class_name)
    emoji          = DISEASE_EMOJI.get(class_name, "🌿")

    logger.info("[%s] user_id=%s | disease=%s | confidence=%.1f%%",
                timestamp, user_id, class_name, conf_pct)

    await wait_msg.edit_text(
        f"{emoji} *রোগ শনাক্ত হয়েছে!*\n\n"
        f"রোগের নাম: *{disease_bangla}*\n"
        f"নিশ্চিততা: *{conf_pct}%*\n\n"
        "⏳ চিকিৎসার পরামর্শ তৈরি করা হচ্ছে...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── Get Gemini advice ──────────────────────────────────────────────────── #
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        advice_text = gemini.get_advice(class_name, confidence)
    except Exception as exc:
        logger.error("user_id=%s | Gemini error: %s", user_id, type(exc).__name__)
        advice_text = (
            "দুঃখিত, এই মুহূর্তে পরামর্শ পাওয়া সম্ভব হচ্ছে না।\n"
            "স্থানীয় কৃষি বিশেষজ্ঞের সাথে যোগাযোগ করুন।"
        )

    advice_msg = (
        "💊 *চিকিৎসার পরামর্শ:*\n\n"
        f"{advice_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *দ্রষ্টব্য:* এটি AI-এর পরামর্শ। গুরুতর "
        "সমস্যায় কৃষি বিশেষজ্ঞের সাথে যোগাযোগ করুন।"
    )
    if is_low_conf:
        advice_msg += (
            f"\n\n⚠️ নিশ্চিততা কম ({conf_pct}%)।\n"
            "আরও ভালো আলোতে পাতার ছবি তুলে আবার পাঠান।"
        )

    await update.message.reply_text(advice_msg, parse_mode=ParseMode.MARKDOWN)


# =========================================================================== #
# Non-photo handler
# =========================================================================== #
async def non_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📸 অনুগ্রহ করে একটি ধান পাতার ছবি পাঠান।\n"
        "/help লিখুন সাহায্যের জন্য।"
    )


# =========================================================================== #
# Error handler
# =========================================================================== #
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error: %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ দুঃখিত, একটি সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        )


# =========================================================================== #
# Startup validation
# =========================================================================== #
def _validate_config() -> list[str]:
    errors = []
    if len(config.WEBHOOK_SECRET) < 16:
        errors.append(
            "WEBHOOK_SECRET must be at least 16 characters. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not config.WEBHOOK_URL.startswith("https://"):
        errors.append("WEBHOOK_URL must start with https://")
    if not os.path.isfile(config.CLASS_INDICES_PATH):
        errors.append(f"Class indices not found: {config.CLASS_INDICES_PATH}")
    return errors


def _log_startup_info() -> None:
    token = config.TELEGRAM_BOT_TOKEN
    token_preview = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "***"
    logger.info("Bot token  : %s", token_preview)
    logger.info("Gemini key : SET ✅")
    logger.info("Webhook URL: %s", config.WEBHOOK_URL)
    logger.info("HF Model   : %s", config.HF_MODEL_URL)


# =========================================================================== #
# aiohttp handlers
# =========================================================================== #
async def handle_webhook(request: web.Request) -> web.Response:
    """
    Receive Telegram updates via POST.
    Validates X-Telegram-Bot-Api-Secret-Token on every request so only
    Telegram's servers can trigger the bot — not arbitrary internet traffic.
    """
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret_header != config.WEBHOOK_SECRET:
        logger.warning("Rejected webhook request — invalid or missing secret header.")
        return web.Response(status=403, text="Forbidden")

    ptb_app: Application = request.app["ptb_app"]
    try:
        data   = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
    except Exception as exc:
        logger.error("Webhook processing error: %s", exc)
    return web.Response(text="OK")


async def handle_health(request: web.Request) -> web.Response:
    """Health check — Render uses GET / or /healthz to show 'Live'."""
    return web.Response(text="OK")


# =========================================================================== #
# Keep-alive — prevents Render free-tier from sleeping
# =========================================================================== #
async def _keep_alive() -> None:
    """Ping /healthz every 10 minutes so Render free tier stays warm."""
    await asyncio.sleep(60)
    health_url = config.WEBHOOK_URL.rstrip("/") + "/healthz"
    logger.info("Keep-alive task started — pinging %s every 10 min", health_url)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    health_url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    logger.debug("Keep-alive ping → %s", resp.status)
            except Exception as exc:
                logger.debug("Keep-alive ping failed (harmless): %s", exc)
            await asyncio.sleep(600)


# =========================================================================== #
# Main
# =========================================================================== #
async def async_main() -> None:
    global predictor, gemini

    errors = _validate_config()
    if errors:
        print("\n❌ Configuration errors:")
        for e in errors:
            print(f"   • {e}")
        sys.exit(1)

    _log_startup_info()

    logger.info("Initialising predictor…")
    try:
        predictor = RiceLeafPredictor(
            hf_model_url=config.HF_MODEL_URL,
            hf_token=config.HF_TOKEN,
            class_indices_path=config.CLASS_INDICES_PATH,
            image_size=config.IMAGE_SIZE,
            cache_dir=config.MODEL_CACHE_DIR,
        )
    except Exception as exc:
        logger.critical("Failed to load model: %s", exc)
        sys.exit(1)

    logger.info("Initialising Gemini advisor…")
    try:
        gemini = GeminiAdvisor(api_key=config.GEMINI_API_KEY)
    except Exception:
        logger.warning("Gemini init failed — fallback advice will be used.")

    ptb_app: Application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .updater(None)
        .build()
    )

    ptb_app.add_handler(CommandHandler("start", start_handler))
    ptb_app.add_handler(CommandHandler("help",  help_handler))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    ptb_app.add_handler(
        MessageHandler(filters.ALL & ~filters.PHOTO & ~filters.COMMAND, non_photo_handler)
    )
    ptb_app.add_error_handler(error_handler)

    port         = int(os.environ.get("PORT", 10000))
    webhook_path = f"/webhook/{config.WEBHOOK_SECRET}"
    webhook_full = f"{config.WEBHOOK_URL}{webhook_path}"

    web_app = web.Application()
    web_app["ptb_app"] = ptb_app
    web_app.router.add_post(webhook_path,  handle_webhook)
    web_app.router.add_get("/healthz",     handle_health)
    web_app.router.add_get("/",            handle_health)

    logger.info("Starting on port %d | webhook path: /webhook/***", port)
    print(f"\n🌾 Rice Disease Bot starting on port {port}\n")

    async with ptb_app:
        await ptb_app.bot.set_webhook(
            url=webhook_full,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            secret_token=config.WEBHOOK_SECRET,
        )
        await ptb_app.start()
        logger.info("Bot is live ✅")

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        asyncio.create_task(_keep_alive())

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await runner.cleanup()
            await ptb_app.stop()
            logger.info("Bot stopped cleanly.")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()