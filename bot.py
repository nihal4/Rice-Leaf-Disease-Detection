# =============================================================================
# bot.py — Rice Leaf Disease Telegram Bot
# 4 classes: Bacterial_Leaf_Blight, Brown_Spot, Leaf_Blast, Tungro
# Compatible with python-telegram-bot 21.x and Python 3.14+
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
# Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    stream=sys.stdout,
)
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
    message = (
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
        "এখনই একটি পাতার ছবি পাঠান! 👇"
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


# =========================================================================== #
# /help
# =========================================================================== #
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
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
        "📞 গুরুতর সমস্যায় স্থানীয় কৃষি অফিসে যোগাযোগ করুন।"
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


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

    # Download
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
        logger.error("[%s] user_id=%s | Download error: %s", timestamp, user_id, exc)
        await wait_msg.edit_text("❌ ছবি ডাউনলোড করা সম্ভব হয়নি। আবার চেষ্টা করুন।")
        return

    # Predict
    try:
        result = predictor.predict(image_bytes, config.CONFIDENCE_THRESHOLD)
    except ValueError as exc:
        logger.error("[%s] user_id=%s | Image decode error: %s", timestamp, user_id, exc)
        await wait_msg.edit_text("❌ ছবিটি পড়া সম্ভব হয়নি। ভিন্ন ছবি পাঠান।")
        return
    except Exception as exc:
        logger.error("[%s] user_id=%s | Prediction error: %s", timestamp, user_id, exc)
        await wait_msg.edit_text("❌ দুঃখিত, ছবিটি বিশ্লেষণ করা সম্ভব হয়নি। আবার চেষ্টা করুন।")
        return

    class_name     = result["class_name"]
    confidence     = result["confidence"]
    is_low_conf    = result["is_low_confidence"]
    conf_pct       = round(confidence * 100, 1)
    disease_bangla = DISEASE_BANGLA.get(class_name, class_name)
    emoji          = DISEASE_EMOJI.get(class_name, "🌿")

    logger.info(
        "[%s] user_id=%s | disease=%s | confidence=%.1f%%",
        timestamp, user_id, class_name, conf_pct,
    )

    # Disease detected — send result immediately
    await wait_msg.edit_text(
        f"{emoji} *রোগ শনাক্ত হয়েছে!*\n\n"
        f"রোগের নাম: *{disease_bangla}*\n"
        f"নিশ্চিততা: *{conf_pct}%*\n\n"
        "⏳ চিকিৎসার পরামর্শ তৈরি করা হচ্ছে...",
        parse_mode=ParseMode.MARKDOWN,
    )

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Gemini advice
    try:
        advice_text = gemini.get_advice(class_name, confidence)
    except Exception as exc:
        logger.error("[%s] user_id=%s | Gemini error: %s", timestamp, user_id, exc)
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
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ দুঃখিত, ছবিটি বিশ্লেষণ করা সম্ভব হয়নি। আবার চেষ্টা করুন।"
        )


# =========================================================================== #
# Startup validation
# =========================================================================== #
def _validate_config() -> list[str]:
    errors = []
    if config.TELEGRAM_BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        errors.append("TELEGRAM_BOT_TOKEN is not set")
    if config.GEMINI_API_KEY == "PASTE_YOUR_GEMINI_API_KEY_HERE":
        errors.append("GEMINI_API_KEY is not set")
    if "YOUR_HF_USERNAME" in config.HF_MODEL_URL:
        errors.append("HF_MODEL_URL is not set — replace YOUR_HF_USERNAME in config.py")
    if not os.path.isfile(config.CLASS_INDICES_PATH):
        errors.append(f"Class indices file not found: {config.CLASS_INDICES_PATH}")
    return errors


# =========================================================================== #
# Async main — Python 3.14 compatible
# =========================================================================== #
async def async_main() -> None:
    global predictor, gemini

    errors = _validate_config()
    if errors:
        print("\n❌ Configuration errors:")
        for e in errors:
            print(f"   • {e}")
        print()
        sys.exit(1)

    logger.info("Initialising ResNet50 predictor…")
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
    except Exception as exc:
        logger.warning("Gemini init failed (%s) — fallback advice will be used.", exc)

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

    print("\n🌾 Rice Disease Bot is running! Press Ctrl+C to stop.\n")

    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot is polling. Press Ctrl+C to stop.")
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await app.updater.stop()
            await app.stop()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()