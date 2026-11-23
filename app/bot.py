import asyncio
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import settings
from app.database import touch_user, create_job, update_job, get_job, db
from app.media import (MediaError, safe_name, convert_gif_to_mp4, convert_webm_to_mp4,
                       convert_webp_to_mp4, extract_audio, extract_subtitles,
                       screenshot, make_clip, rename_file, probe)

log = logging.getLogger(__name__)
SUPPORTED = {"gif", "webp", "webm", "mp4", "mkv", "mov", "avi", "m4v"}

def _buttons(job_id, ext):
    options = []
    if ext == "gif":
        options.append([InlineKeyboardButton("🎞 GIF → MP4", callback_data=f"do|{job_id}|gif_mp4")])
    elif ext == "webp":
        options.append([InlineKeyboardButton("🎬 Sticker → MP4", callback_data=f"do|{job_id}|webp_mp4")])
    elif ext == "webm":
        options.append([InlineKeyboardButton("🎬 WEBM → MP4", callback_data=f"do|{job_id}|webm_mp4")])
    if ext in {"mp4", "mkv", "mov", "avi", "m4v", "webm"}:
        options.extend([
            [InlineKeyboardButton("🎧 Extract audio (MP3)", callback_data=f"do|{job_id}|audio")],
            [InlineKeyboardButton("📝 Extract subtitles", callback_data=f"do|{job_id}|subs")],
            [InlineKeyboardButton("📸 Screenshot", callback_data=f"do|{job_id}|shot")],
            [InlineKeyboardButton("✂️ Create 30-second clip", callback_data=f"do|{job_id}|clip")],
        ])
    options.append([InlineKeyboardButton("✏️ Rename file", callback_data=f"do|{job_id}|rename")])
    options.append([InlineKeyboardButton("ℹ️ Media information", callback_data=f"do|{job_id}|info")])
    return InlineKeyboardMarkup(options)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    touch_user(update.effective_user)
    await update.message.reply_text(
        "✨ *Media Studio is ready*\n\nSend a GIF, sticker, WEBM or video to get started.\n"
        "Choose an action from the menu after upload.\n\n"
        "Current Telegram Bot API upload/download limit applies. Large-file links and URL imports are being added in a later phase.",
        parse_mode="Markdown",
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a supported media file. Available tools include conversion, audio extraction, "
        "subtitle extraction, screenshots, 30-second clips and media information."
    )

async def receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    touch_user(user)
    msg = update.effective_message
    item = msg.document or msg.video or msg.animation
    if not item:
        return
    filename = safe_name(getattr(item, "file_name", None) or f"media_{item.file_unique_id}")
    ext = Path(filename).suffix.lower().lstrip(".")
    if not ext and msg.animation:
        ext = "gif"
    if not ext and msg.video:
        ext = "mp4"
    if ext not in SUPPORTED:
        await msg.reply_text("That format is not supported yet. Try GIF, WEBP, WEBM or MP4/MKV/MOV.")
        return
    size = item.file_size or 0
    if size > settings.max_upload_mb * 1024 * 1024:
        await msg.reply_text(f"File is above this deployment's {settings.max_upload_mb} MB intake limit.")
        return
    job_id = uuid.uuid4().hex[:12]
    create_job({
        "job_id": job_id, "telegram_id": user.id, "file_id": item.file_id,
        "file_unique_id": item.file_unique_id, "filename": filename, "extension": ext,
        "size": size, "status": "queued", "created_at": datetime.now(timezone.utc),
    })
    await msg.reply_text("✨ File received. Choose what you'd like to do:",
                         reply_markup=_buttons(job_id, ext))

async def do_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        _, job_id, action = q.data.split("|", 2)
        job = get_job(job_id, q.from_user.id)
        if not job:
            await q.edit_message_text("This job is unavailable. Please send the file again.")
            return
        if action == "rename":
            context.user_data["rename_job_id"] = job_id
            await q.edit_message_text(
                "✏️ Send the new filename (with or without extension). "
                "The original file extension will be preserved."
            )
            return
        if action == "info":
            await q.edit_message_text("🔎 Reading media information…")
        else:
            await q.edit_message_text("⏳ Processing started…")
        update_job(job_id, {"status": "processing", "action": action})
        workdir = Path(settings.temp_dir) / job_id
        workdir.mkdir(parents=True, exist_ok=True)
        source = workdir / safe_name(job["filename"])
        output = None
        try:
            tg_file = await context.bot.get_file(job["file_id"])
            await tg_file.download_to_drive(custom_path=str(source))
            if action == "info":
                info = await probe(source)
                fmt = info.get("format", {})
                streams = info.get("streams", [])
                summary = (f"📁 {job['filename']}\nSize: {job['size'] / 1024 / 1024:.2f} MB\n"
                           f"Duration: {fmt.get('duration', 'unknown')} sec\n"
                           f"Streams: {len(streams)}")
                await q.edit_message_text(summary)
                update_job(job_id, {"status": "completed"})
                return
            suffix = {
                "gif_mp4": ".mp4", "webp_mp4": ".mp4", "webm_mp4": ".mp4",
                "audio": ".mp3", "subs": ".srt", "shot": ".jpg", "clip": ".mp4",
            }.get(action)
            if not suffix:
                raise MediaError("Unknown action.")
            output = workdir / ("result" + suffix)
            if action == "gif_mp4":
                await convert_gif_to_mp4(source, output)
            elif action == "webp_mp4":
                await convert_webp_to_mp4(source, output)
            elif action == "webm_mp4":
                await convert_webm_to_mp4(source, output)
            elif action == "audio":
                await extract_audio(source, output)
            elif action == "subs":
                await extract_subtitles(source, output)
            elif action == "shot":
                await screenshot(source, output)
            elif action == "clip":
                await make_clip(source, output, 0, 30)
            await q.edit_message_text("📤 Uploading result…")
            with output.open("rb") as f:
                await context.bot.send_document(chat_id=q.message.chat_id, document=f,
                                                filename=output.name, caption="✅ Finished")
            update_job(job_id, {"status": "completed", "completed_at": datetime.now(timezone.utc)})
        finally:
            import shutil
            await asyncio.to_thread(shutil.rmtree, workdir, True)
    except MediaError as exc:
        log.warning("Media operation failed: %s", exc)
        update_job(job_id, {"status": "failed", "error": str(exc)[:500]})
        await q.message.reply_text("❌ Could not process this file. Check that it contains the requested media stream.")
    except Exception:
        log.exception("Unexpected job failure")
        try:
            update_job(job_id, {"status": "failed"})
        except Exception:
            pass
        await q.message.reply_text("❌ Something went wrong. Please retry with the file.")


async def handle_rename_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    job_id = context.user_data.get("rename_job_id")
    if not job_id:
        return
    context.user_data.pop("rename_job_id", None)
    job = get_job(job_id, update.effective_user.id)
    if not job:
        await update.message.reply_text("That file session expired. Please upload the file again.")
        return
    requested = update.message.text.strip()
    if not requested or len(requested) > 100:
        await update.message.reply_text("Please send a filename between 1 and 100 characters.")
        context.user_data["rename_job_id"] = job_id
        return
    old_ext = Path(job["filename"]).suffix
    new_stem = Path(requested).stem
    clean_stem = safe_name(new_stem, "renamed")
    if not clean_stem or clean_stem in {".", ".."}:
        await update.message.reply_text("That filename is not valid. Try another name.")
        context.user_data["rename_job_id"] = job_id
        return
    new_name = clean_stem + old_ext
    workdir = Path(settings.temp_dir) / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / safe_name(job["filename"])
    destination = workdir / new_name
    try:
        await update.message.reply_text("⏳ Preparing your renamed file…")
        tg_file = await context.bot.get_file(job["file_id"])
        await tg_file.download_to_drive(custom_path=str(source))
        await asyncio.to_thread(source.rename, destination)
        with destination.open("rb") as stream:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=stream,
                filename=new_name,
                caption="✅ File renamed successfully",
            )
        update_job(job_id, {"status": "completed", "renamed_to": new_name})
    except Exception:
        log.exception("Rename operation failed")
        update_job(job_id, {"status": "failed", "action": "rename"})
        await update.message.reply_text("❌ Rename failed. Please upload the file again and retry.")
    finally:
        import shutil
        await asyncio.to_thread(shutil.rmtree, workdir, True)

def build_bot():
    app = Application.builder().token(settings.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(do_action, pattern=r"^do\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rename_text))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.ANIMATION, receive_media))
    return app
