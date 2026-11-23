
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()

    webhook_secret: str = os.getenv(
        "WEBHOOK_SECRET", ""
    ).strip()

    webhook_url: str = os.getenv(
        "WEBHOOK_URL", ""
    ).strip().rstrip("/")

    db_uri: str = os.getenv("DB_URI", "").strip()

    db_name: str = os.getenv(
        "DB_NAME",
        "telegram_media_suite",
    ).strip()

    port: int = int(
        os.getenv("PORT", "8000")
    )

    max_upload_mb: int = int(
        os.getenv("MAX_UPLOAD_MB", "18")
    )

    temp_dir: str = os.getenv(
        "TEMP_DIR",
        "/tmp/telegram-media-suite",
    )

    log_level: str = os.getenv(
        "LOG_LEVEL",
        "INFO",
    ).upper()


settings = Settings()


def validate_settings():
    missing = []

    required = {
        "BOT_TOKEN": settings.bot_token,
        "WEBHOOK_SECRET": settings.webhook_secret,
        "WEBHOOK_URL": settings.webhook_url,
        "DB_URI": settings.db_uri,
    }

    for name, value in required.items():
        if not value:
            missing.append(name)

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )

    if not all(
        char.isalnum() or char in "_-"
        for char in settings.webhook_secret
    ):
        raise RuntimeError(
            "WEBHOOK_SECRET may contain only letters, "
            "numbers, '_' and '-'."
        )

    if settings.max_upload_mb <= 0:
        raise RuntimeError(
            "MAX_UPLOAD_MB must be greater than zero."
        )

    if not settings.webhook_url.startswith("https://"):
        raise RuntimeError(
            "WEBHOOK_URL must be an HTTPS URL."
        )
        
