import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app.database import touch_user, create_job, update_job, get_job
from app.media import (
    MediaError,
    safe_name,
    convert_gif_to_mp4,
    convert_webm_to_mp4,
    convert_webp_to_mp4,
    extract_audio,
    extract_subtitles,
    screenshot,
    make_clip,
    probe,
)

log = logging.getLogger(__name__)

SUPPORTED = {
    "gif", "webp", "webm", "mp4",
    "mkv", "mov", "avi", "m4v",
}


def _buttons(job_id, ext):
    options = []

    if ext == "gif":
        options.append([
            InlineKeyboardButton(
                "🎞 GIF → MP4",
                callback_data=f"do|{job_id}|gif_mp4",
            )
        ])

    elif ext == "webp":
        options.append([
            InlineKeyboardButton(
                "🎬 Sticker → MP4",
                callback_data=f"do|{job_id}|webp_mp4",
            )
        ])

    elif ext == "webm":
        options.append([
            InlineKeyboardButton(
                "🎬 WEBM → MP4",
                callback_data=f"do|{job_id}|webm_mp4",
            )
        ])

    if ext in {"mp4", "mkv", "mov", "avi", "m4v", "webm"}:
        options.extend([
            [
                InlineKeyboardButton(
                    "🎧 Extract audio (MP3)",
                    callback_data=f"do|{job_id}|audio",
                )
            ],
            [
                InlineKeyboardButton(
                    "📝 Extract subtitles",
                    callback_data=f"do|{job_id}|subs",
                )
            ],
            [
                InlineKeyboardButton(
                    "📸 Screenshot",
                    callback_data=f"do|{job_id}|shot",
                )
            ],
            [
                InlineKeyboardButton(
                    "✂️ Create 30-second clip",
                    callback_data=f"do|{job_id}|clip",
                )
            ],
        ])

    options.append([
        InlineKeyboardButton(
            "✏️ Rename file",
            callback_data=f"do|{job_id}|rename",
        )
    ])

    options.append([
        InlineKeyboardButton(
            "ℹ️ Media information",
            callback_data=f"do|{job_id}|info",
        )
    ])

    return InlineKeyboardMarkup(options)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if user:
        touch_user(user)

    if message:
        await message.reply_text(
            "✨ *Media Studio is ready!*\n\n"
            "Send a GIF, WEBP sticker, WEBM or video to get started.\n\n"
            "Choose an action from the menu after uploading.\n\n"
            "Current Telegram Bot API upload/download limits apply.",
            parse_mode="Markdown",
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if message:
        await message.reply_text(
            "✨ Media Studio Help\n\n"
            "Send a supported media file to get started.\n\n"
            "Available tools:\n"
            "• GIF to MP4 conversion\n"
            "• WEBP sticker to MP4 conversion\n"
            "• WEBM to MP4 conversion\n"
            "• MP3 audio extraction\n"
            "• Subtitle extraction\n"
            "• Screenshots\n"
            "• 30-second video clips\n"
            "• File renaming\n"
            "• Media information"
        )


async def receive_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    touch_user(user)

    item = message.document or message.video or message.animation

    if not item:
        return

    filename = safe_name(
        getattr(item, "file_name", None)
        or f"media_{item.file_unique_id}"
    )

    ext = Path(filename).suffix.lower().lstrip(".")

    if not ext and message.animation:
        ext = "gif"

    if not ext and message.video:
        ext = "mp4"

    if ext not in SUPPORTED:
        await message.reply_text(
            "❌ Unsupported format.\n\n"
            "Supported formats: GIF, WEBP, WEBM, MP4, "
            "MKV, MOV, AVI and M4V."
        )
        return

    size = item.file_size or 0

    if size > settings.max_upload_mb * 1024 * 1024:
        await message.reply_text(
            f"❌ File exceeds this deployment's "
            f"{settings.max_upload_mb} MB intake limit."
        )
        return

    job_id = uuid.uuid4().hex[:12]

    create_job({
        "job_id": job_id,
        "telegram_id": user.id,
        "file_id": item.file_id,
        "file_unique_id": item.file_unique_id,
        "filename": filename,
        "extension": ext,
        "size": size,
        "status": "queued",
        "created_at": datetime.now(timezone.utc),
    })

    await message.reply_text(
        "✨ File received successfully!\n\n"
        "Choose what you'd like to do:",
        reply_markup=_buttons(job_id, ext),
    )


async def do_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    job_id = None
    workdir = None

    try:
        parts = query.data.split("|", 2)

        if len(parts) != 3:
            raise MediaError("Invalid action request.")

        _, job_id, action = parts

        job = get_job(job_id, query.from_user.id)

        if not job:
            await query.edit_message_text(
                "This job is unavailable. Please upload the file again."
            )
            return

        if action == "rename":
            context.user_data["rename_job_id"] = job_id

            await query.edit_message_text(
                "✏️ Send the new filename.\n\n"
                "You can include or omit the extension. "
                "The original extension will be preserved."
            )
            return

        if action == "info":
            await query.edit_message_text(
                "🔎 Reading media information..."
            )
        else:
            await query.edit_message_text(
                "⏳ Processing started..."
            )

        update_job(
            job_id,
            {
                "status": "processing",
                "action": action,
            },
        )

        workdir = Path(settings.temp_dir) / job_id
        workdir.mkdir(parents=True, exist_ok=True)

        source = workdir / safe_name(job["filename"])

        tg_file = await context.bot.get_file(job["file_id"])

        await tg_file.download_to_drive(
            custom_path=str(source)
        )

        if action == "info":
            info = await probe(source)

            fmt = info.get("format", {})
            streams = info.get("streams", [])

            summary = (
                f"📁 {job['filename']}\n"
                f"Size: {job['size'] / 1024 / 1024:.2f} MB\n"
                f"Duration: {fmt.get('duration', 'unknown')} sec\n"
                f"Streams: {len(streams)}"
            )

            await query.edit_message_text(summary)

            update_job(
                job_id,
                {"status": "completed"},
            )
            return

        suffixes = {
            "gif_mp4": ".mp4",
            "webp_mp4": ".mp4",
            "webm_mp4": ".mp4",
            "audio": ".mp3",
            "subs": ".srt",
            "shot": ".jpg",
            "clip": ".mp4",
        }

        suffix = suffixes.get(action)

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

        if not output.exists():
            raise MediaError("Processing did not produce an output file.")

        await query.edit_message_text(
            "📤 Uploading your result..."
        )

        with output.open("rb") as stream:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=stream,
                filename=output.name,
                caption="✅ Processing completed!",
            )

        update_job(
            job_id,
            {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc),
            },
        )

    except MediaError as exc:
        log.warning("Media operation failed: %s", exc)

        if job_id:
            update_job(
                job_id,
                {
                    "status": "failed",
                    "error": str(exc)[:500],
                },
            )

        if query.message:
            await query.message.reply_text(
                "❌ Could not process this file.\n"
                "Check that it contains the requested media stream."
            )

    except Exception:
        log.exception("Unexpected job failure")

        if job_id:
            try:
                update_job(
                    job_id,
                    {"status": "failed"},
                )
            except Exception:
                log.exception("Could not update failed job status")

        if query.message:
            await query.message.reply_text(
                "❌ Something went wrong. Please retry with the file."
            )

    finally:
        if workdir and workdir.exists():
            await asyncio.to_thread(
                shutil.rmtree,
                workdir,
                True,
            )


async def handle_rename_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    job_id = context.user_data.get("rename_job_id")

    if not job_id:
        return

    message = update.effective_message

    if not message or not message.text:
        return

    job = get_job(job_id, update.effective_user.id)

    if not job:
        context.user_data.pop("rename_job_id", None)

        await message.reply_text(
            "That file session has expired. Please upload the file again."
        )
        return

    requested = message.text.strip()

    if not requested or len(requested) > 100:
        await message.reply_text(
            "Please send a filename between 1 and 100 characters."
        )
        return

    old_ext = Path(job["filename"]).suffix
    new_stem = Path(requested).stem
    clean_stem = safe_name(new_stem, "renamed")

    if not clean_stem or clean_stem in {".", ".."}:
        await message.reply_text(
            "Invalid filename. Please try another name."
        )
        return

    new_name = clean_stem + old_ext

    workdir = Path(settings.temp_dir) / job_id
    workdir.mkdir(parents=True, exist_ok=True)

    source = workdir / safe_name(job["filename"])
    destination = workdir / new_name

    context.user_data.pop("rename_job_id", None)

    try:
        await message.reply_text(
            "⏳ Preparing your renamed file..."
        )

        tg_file = await context.bot.get_file(job["file_id"])

        await tg_file.download_to_drive(
            custom_path=str(source)
        )

        await asyncio.to_thread(
            source.rename,
            destination,
        )

        with destination.open("rb") as stream:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=stream,
                filename=new_name,
                caption="✅ File renamed successfully!",
            )

        update_job(
            job_id,
            {
                "status": "completed",
                "renamed_to": new_name,
            },
        )

    except Exception:
        log.exception("Rename operation failed")

        update_job(
            job_id,
            {
                "status": "failed",
                "action": "rename",
            },
        )

        await message.reply_text(
            "❌ Rename failed. Please upload the file again and retry."
        )

    finally:
        await asyncio.to_thread(
            shutil.rmtree,
            workdir,
            True,
        )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    if context.error:
        log.error(
            "Telegram update processing failed",
            exc_info=(
                type(context.error),
                context.error,
                context.error.__traceback__,
            ),
        )
    else:
        log.error("Telegram update processing failed without exception details")


def build_bot():
    application = (
        Application.builder()
        .token(settings.bot_token)
        .build()
    )

    application.add_error_handler(error_handler)

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_cmd)
    )

    application.add_handler(
        CallbackQueryHandler(
            do_action,
            pattern=r"^do\|",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_rename_text,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Document.ALL
            | filters.VIDEO
            | filters.ANIMATION,
            receive_media,
        )
    )

    return application
