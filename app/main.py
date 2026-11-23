import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from app.config import settings, validate_settings
from app.database import connect_database, close_database
from app.bot import build_bot

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
bot_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_app
    validate_settings()
    connect_database()
    bot_app = build_bot()
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.bot.set_webhook(
        url=f"{settings.webhook_url}/telegram/webhook",
        secret_token=settings.webhook_secret,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
    yield
    await bot_app.bot.delete_webhook(drop_pending_updates=False)
    await bot_app.stop()
    await bot_app.shutdown()
    close_database()

app = FastAPI(title="Telegram Media Studio", version="0.1.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    payload = await request.json()
    update = Update.de_json(payload, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}
