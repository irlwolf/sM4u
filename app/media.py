import subprocess
from pathlib import Path

class ConversionError(Exception):
    pass

def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=90
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("Conversion timed out (90 seconds).") from exc
    if result.returncode != 0:
        detail = (result.stderr or "FFmpeg error").strip().splitlines()[-1]
        raise ConversionError(detail[:300])

def convert_media(source: Path, target: Path, suffix: str) -> None:
    suffix = suffix.lower()
    common = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vf", "scale=512:512:force_original_aspect_ratio=decrease:flags=lanczos,"
               "pad=512:512:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p",
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-movflags", "+faststart", "-t", "20", str(target),
    ]

    if suffix == ".webp":
        # Static WEBP sticker: render a 3-second MP4 on a black background.
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", "30", "-i", str(source),
            "-vf", "scale=512:512:force_original_aspect_ratio=decrease:flags=lanczos,"
                   "pad=512:512:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
            "-t", "3", "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "23", "-movflags", "+faststart", str(target),
        ]
    elif suffix in {".gif", ".webm", ".mp4", ".mov", ".mkv"}:
        command = common
    else:
        raise ConversionError("Unsupported format. Send a GIF, WEBP sticker, or WEBM video sticker.")

    _run(command)
