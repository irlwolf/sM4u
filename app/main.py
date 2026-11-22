import asyncio
import logging
import os
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from app.media import convert_media, ConversionError

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("sticker-mp4")

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "18"))

telegram_app = Application.builder().token(BOT_TOKEN).build()


async def process_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    media = message.animation or message.sticker or message.document
    if media is None:
        await message.reply_text(
            "Send me a GIF, Telegram sticker, or WEBM video sticker and I'll convert it to MP4."
        )
        return

    # Telegram animated stickers may be TGS (vector animation) or WEBM (video sticker).
    sticker = message.sticker
    if sticker and sticker.is_animated:
        await message.reply_text(
            "TGS animated stickers are not enabled in this first build. "
            "GIF, static WEBP stickers, and WEBM video stickers are supported."
        )
        return

    file_size = getattr(media, "file_size", None)
    if file_size and file_size > MAX_UPLOAD_MB * 1024 * 1024:
        await message.reply_text(f"File too large. Maximum supported size is {MAX_UPLOAD_MB} MB.")
        return

    status = await message.reply_text("⏳ Downloading and converting…")
    workdir = Path(tempfile.mkdtemp(prefix="tg-convert-"))
    try:
        tg_file = await media.get_file()
        suffix = ".bin"
        if message.animation:
            suffix = ".gif"
        elif sticker and sticker.is_video:
            suffix = ".webm"
        elif sticker:
            suffix = ".webp"
        elif message.document and message.document.file_name:
            suffix = Path(message.document.file_name).suffix.lower() or ".bin"

        input_path = workdir / f"input{suffix}"
        output_path = workdir / "converted.mp4"
        await tg_file.download_to_drive(custom_path=input_path)

        await asyncio.to_thread(convert_media, input_path, output_path, suffix)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise ConversionError("The converter did not produce an MP4 file.")
        if output_path.stat().st_size > 49 * 1024 * 1024:
            raise ConversionError("The converted video is too large to send through Telegram.")

        with output_path.open("rb") as video:
            await message.reply_video(
                video=video,
                filename="converted.mp4",
                supports_streaming=True,
                caption="✅ Converted to MP4",
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
            )
        await status.delete()
    except ConversionError as exc:
        await status.edit_text(f"❌ Conversion failed: {exc}")
    except Exception:
        log.exception("Media conversion failed")
        try:
            await status.edit_text("❌ Something went wrong while processing this file. Please try another.")
        except Exception:
            pass
    finally:
        for item in workdir.glob("*"):
            try:
                item.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            workdir.rmdir()
        except OSError:
            pass


telegram_app.add_handler(MessageHandler(
    filters.ANIMATION | filters.Sticker.ALL | filters.Document.ALL,
    process_media,
))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_app.initialize()
    await telegram_app.start()
    if WEBHOOK_URL:
        await telegram_app.bot.set_webhook(
            url=f"{WEBHOOK_URL}/telegram/{WEBHOOK_SECRET}",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            secret_token=WEBHOOK_SECRET,
        )
        log.info("Bot started; webhook configured")
    else:
        log.warning("WEBHOOK_URL is empty; webhook registration skipped. Set it and redeploy.")
    yield
    try:
        await telegram_app.bot.delete_webhook()
    finally:
        await telegram_app.stop()
        await telegram_app.shutdown()


api = FastAPI(title="Telegram GIF & Sticker to MP4 Bot", lifespan=lifespan)


@api.get("/")
async def root():
    return {"name": "Telegram GIF & Sticker to MP4 Bot", "status": "ok"}


@api.get("/health")
async def health():
    return {"status": "healthy"}


@api.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if not secrets.compare_digest(secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")
    if x_telegram_bot_api_secret_token and not secrets.compare_digest(
        x_telegram_bot_api_secret_token, WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403, detail="Invalid Telegram secret")
    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_app.bot)
        await telegram_app.update_queue.put(update)
    except Exception as exc:
        log.exception("Invalid webhook update")
        raise HTTPException(status_code=400, detail="Invalid update") from exc
    return {"ok": True}
