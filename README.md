# Telegram GIF & Sticker to MP4 Bot

A Python Telegram bot deployed as a Dockerized Koyeb **Web Service**. It receives Telegram webhooks and uses FFmpeg to convert GIFs, static WEBP stickers, and WEBM video stickers to MP4.

## Current MVP support

| Input | Status |
|---|---|
| GIF animation | Supported |
| Static WEBP sticker | Supported (3-second MP4) |
| WEBM video sticker | Supported |
| TGS animated sticker | Not yet supported; planned next phase |

MP4/H.264 does not preserve an alpha channel. The current output uses a black background. Static stickers are not animated; they are held for three seconds.

## Requirements

- Python 3.12+ for local development
- Docker with FFmpeg in the image
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Koyeb account and a GitHub repository

## Run locally

1. Copy `.env.example` to `.env` and fill in the values.
2. Install FFmpeg locally.
3. Install Python dependencies:

   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # macOS/Linux:
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. For webhook testing, expose local port 8000 through a trusted HTTPS tunnel and set `WEBHOOK_URL` to that HTTPS base URL.
5. Run:

   ```bash
   uvicorn app.main:api --host 0.0.0.0 --port 8000
   ```

## Deploy on Koyeb Free

Koyeb Free only supports a Web Service, not a Worker. This project uses a webhook server for that reason.

1. Push this project to a GitHub repository.
2. In Koyeb, create **Web Service → GitHub** and select the repository.
3. Select the **Dockerfile** builder.
4. Choose the Free instance and a supported region (Frankfurt or Washington, D.C.).
5. Set environment variables:
   - `BOT_TOKEN`: token from BotFather
   - `WEBHOOK_SECRET`: a random secret, 32+ characters recommended
   - `WEBHOOK_URL`: leave blank for the first deployment
   - `MAX_UPLOAD_MB`: `18`
6. Set the exposed HTTP port to `8000` if Koyeb does not detect it automatically.
7. Set the HTTP health check path to `/health`.
8. Deploy. The service can start with `WEBHOOK_URL` blank and will skip webhook registration.
9. Copy the public HTTPS domain assigned by Koyeb. Set `WEBHOOK_URL` to that domain (for example `https://your-app-your-org.koyeb.app`, no trailing slash) and redeploy. The app registers the Telegram webhook at startup.

If the domain changes later, update `WEBHOOK_URL` and redeploy.

## Important free-tier limitations

- Koyeb Free instances have 512 MB RAM, 0.1 vCPU, 2 GB SSD, and scale to zero after one hour without traffic.
- Free instances are not suitable for heavy or high-volume video processing.
- A sleeping service can delay Telegram webhook processing until Koyeb wakes it.
- Telegram Bot API hosted file downloads have size limits; this app uses an 18 MB upload cap by default.
- Files are temporary and deleted after conversion. Do not rely on local storage for persistence.
- Do not run multiple replicas with the same webhook unless you have designed update processing for that topology.

## Security

- Never commit `.env` or publish your bot token.
- Use a strong random `WEBHOOK_SECRET`.
- Rotate the bot token via BotFather if it is exposed.
- The webhook path and Telegram secret header are validated.
- The bot accepts media only and does not execute user-supplied commands or files.

## Next development milestone

Add TGS rendering (for Telegram vector animated stickers), conversion progress, queue/concurrency limits, file-duration controls, and tests. TGS rendering is intentionally not claimed as supported in this initial build.
