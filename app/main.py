
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from telegram import Update

from app.config import settings, validate_settings
from app.database import connect_database, close_database
from app.bot import build_bot


logging.basicConfig(
    level=getattr(
        logging,
        settings.log_level,
        logging.INFO,
    ),
    format=(
        "%(asctime)s %(levelname)s "
        "%(name)s: %(message)s"
    ),
)

log = logging.getLogger("telegram-media-studio")

bot_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_app

    log.info("Starting Telegram Media Studio...")

    validate_settings()

    connect_database()

    bot_app = build_bot()

    await bot_app.initialize()

    await bot_app.start()

    webhook_url = (
        f"{settings.webhook_url}/telegram/webhook"
    )

    await bot_app.bot.set_webhook(
        url=webhook_url,
        secret_token=settings.webhook_secret,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )

    log.info(
        "Bot started successfully. Webhook configured: %s",
        webhook_url,
    )

    try:
        yield

    finally:
        log.info("Shutting down Telegram Media Studio...")

        if bot_app:
            try:
                await bot_app.bot.delete_webhook(
                    drop_pending_updates=False
                )
            except Exception:
                log.exception("Could not delete Telegram webhook")

            try:
                await bot_app.stop()
            except Exception:
                log.exception("Could not stop Telegram application")

            try:
                await bot_app.shutdown()
            except Exception:
                log.exception("Could not shut down Telegram application")

        close_database()

        log.info("Application shutdown complete.")


app = FastAPI(
    title="Telegram Media Studio",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {
        "name": "Telegram Media Studio",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "bot_initialized": bot_app is not None,
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if (
        request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )
        != settings.webhook_secret
    ):
        log.warning(
            "Rejected Telegram webhook: invalid secret"
        )

        raise HTTPException(
            status_code=403,
            detail="Forbidden",
        )

    if bot_app is None:
        log.error(
            "Webhook received before bot initialization"
        )

        raise HTTPException(
            status_code=503,
            detail="Bot is not initialized",
        )

    try:
        payload = await request.json()

        update = Update.de_json(
            payload,
            bot_app.bot,
        )

        if update is None:
            raise ValueError("Invalid Telegram update payload")

        log.info(
            "Received Telegram update: update_id=%s",
            update.update_id,
        )

        await bot_app.process_update(update)

        log.info(
            "Telegram update dispatched: update_id=%s",
            update.update_id,
        )

        return {
            "ok": True,
        }

    except Exception:
        log.exception(
            "Telegram webhook processing failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed",
        )
