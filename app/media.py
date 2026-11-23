import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

class MediaError(Exception):
    pass

def _run(args, timeout=900):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, check=False, text=True)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Processing timed out.") from exc
    if p.returncode:
        raise MediaError((p.stderr or "FFmpeg failed")[-1200:])
    return p

async def run(args, timeout=900):
    return await asyncio.to_thread(_run, args, timeout)

def safe_name(value, fallback="output"):
    name = Path(value or fallback).name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return (name or fallback)[:100]

async def probe(path):
    p = await run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                   "-of", "json", str(path)], timeout=60)
    import json
    return json.loads(p.stdout)

async def convert_gif_to_mp4(src, dst):
    await run(["ffmpeg", "-y", "-i", str(src), "-movflags", "+faststart",
               "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
               str(dst)])

async def convert_webm_to_mp4(src, dst):
    await run(["ffmpeg", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(dst)])

async def convert_webp_to_mp4(src, dst):
    await run(["ffmpeg", "-y", "-loop", "1", "-i", str(src), "-t", "3",
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
               "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(dst)])

async def extract_audio(src, dst):
    await run(["ffmpeg", "-y", "-i", str(src), "-vn", "-map", "0:a:0?",
               "-c:a", "libmp3lame", "-q:a", "2", str(dst)])

async def extract_subtitles(src, dst):
    await run(["ffmpeg", "-y", "-i", str(src), "-map", "0:s:0", "-c:s", "srt", str(dst)])

async def screenshot(src, dst, seconds="1"):
    await run(["ffmpeg", "-y", "-ss", seconds, "-i", str(src), "-frames:v", "1", str(dst)])

async def make_clip(src, dst, start, duration=30):
    start = max(0.0, float(start))
    duration = min(30.0, max(1.0, float(duration)))
    await run(["ffmpeg", "-y", "-ss", str(start), "-i", str(src), "-t", str(duration),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-c:a", "aac", "-movflags", "+faststart", str(dst)])

async def rename_file(src, dst):
    await asyncio.to_thread(shutil.copy2, src, dst)
