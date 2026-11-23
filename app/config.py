import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    webhook_url: str = os.getenv("WEBHOOK_URL", "").rstrip("/")
    db_uri: str = os.getenv("DB_URI", "")
    db_name: str = os.getenv("DB_NAME", "telegram_media_suite")
    port: int = int(os.getenv("PORT", "8000"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "18"))
    temp_dir: str = os.getenv("TEMP_DIR", "/tmp/telegram-media-suite")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()

def validate_settings():
    missing = [name for name, value in {
        "BOT_TOKEN": settings.bot_token,
        "WEBHOOK_SECRET": settings.webhook_secret,
        "WEBHOOK_URL": settings.webhook_url,
        "DB_URI": settings.db_uri,
    }.items() if not value]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    if not all(c.isalnum() or c in "_-" for c in settings.webhook_secret):
        raise RuntimeError("WEBHOOK_SECRET may contain only letters, numbers, '_' and '-'.")
