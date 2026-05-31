# =============================================================================
# bot.py — Rice Leaf Disease Telegram Bot
# - Webhook mode (instant wake-up, no polling)
# - Health check endpoint on / (makes Render show "Live")
# - Security hardened (no token in logs, secrets redacted)
# - Compatible with python-telegram-bot 21.x and Python 3.14+
# =============================================================================

import asyncio
import logging
import os
import sys
from datetime import datetime

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
# Secure logging — suppress httpx (hides token from logs)
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

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Globals
# --------------------------------------------------------------------------- #
predictor: RiceLeafPredictor | None = None
gemini: GeminiAdvisor | None = None

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
# Photo handler
# =========================================================================== #
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user      = update.effective_user
    user_id   = user.id if user else "unknown"
    chat_id   = update.effective_chat.id
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
    # Log error type only — never log full exception (may contain secrets)
    logger.error("Unhandled error: %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ দুঃখিত, একটি সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        )


# =========================================================================== #
# Startup validation — never prints secret values
# =========================================================================== #
def _validate_config() -> list[str]:
    errors = []
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        errors.append("TELEGRAM_BOT_TOKEN is not set")
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "PASTE_YOUR_GEMINI_API_KEY_HERE":
        errors.append("GEMINI_API_KEY is not set")
    if not config.WEBHOOK_URL or "yourdomain" in config.WEBHOOK_URL:
        errors.append("WEBHOOK_URL is not set")
    if "YOUR_HF_USERNAME" in config.HF_MODEL_URL:
        errors.append("HF_MODEL_URL is not set")
    if not os.path.isfile(config.CLASS_INDICES_PATH):
        errors.append(f"Class indices not found: {config.CLASS_INDICES_PATH}")
    return errors


def _log_startup_info() -> None:
    """Log config summary — secrets redacted."""
    token = config.TELEGRAM_BOT_TOKEN
    token_preview = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
    logger.info("Bot token  : %s", token_preview)
    logger.info("Gemini key : SET ✅")
    logger.info("Webhook URL: %s", config.WEBHOOK_URL)
    logger.info("HF Model   : %s", config.HF_MODEL_URL)


# =========================================================================== #
# Async main — webhook mode with health check on /
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

    app: Application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help",  help_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.PHOTO & ~filters.COMMAND, non_photo_handler)
    )
    app.add_error_handler(error_handler)

    port           = int(os.environ.get("PORT", 8080))
    webhook_path   = f"/webhook/{config.WEBHOOK_SECRET}"
    webhook_full   = f"{config.WEBHOOK_URL}{webhook_path}"

    logger.info("Starting webhook on port %d", port)
    print(f"\n🌾 Rice Disease Bot starting on port {port}\n")

    async with app:
        await app.bot.set_webhook(
            url=webhook_full,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        await app.start()

        # start_webhook serves:
        #   POST /webhook/<secret>  ← Telegram messages (secure)
        #   GET  /healthz           ← Render health check (returns 200)
        await app.updater.start_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=webhook_full,
            # Built-in health check path — returns 200 OK, no secret needed
            health_check_url_path="/healthz",
        )

        logger.info("Bot is live. Webhook registered.")

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            logger.info("Bot stopped cleanly.")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()