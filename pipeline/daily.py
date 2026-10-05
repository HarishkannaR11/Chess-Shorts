"""
Headless "make one Short and publish it" job.

Shared by publish.py (GitHub Actions, cron, Docker) and the FastAPI scheduler
in main.py, so every deployment generates, checks and uploads the same way.
"""
import os
import json
import shutil
import asyncio
import logging
import subprocess

import aiosqlite

from database.db import DB_PATH, init_db, save_video, save_series_puzzle, update_video_status
from pipeline.setup import setup_assets
from pipeline.assets_setup import setup_music, download_sounds

logger = logging.getLogger(__name__)

FORMATS = ["flash", "story", "series"]
MAX_SHORT_SECONDS = 180          # YouTube treats vertical videos up to 3 min as Shorts
MIN_HOURS_BETWEEN_UPLOADS = 20   # once-a-day guard (tolerates late cron runs)


def _add_custom_ffmpeg_to_path():
    """Honour FFMPEG_PATH / FFPROBE_PATH from .env, same as main.py."""
    for path_env in ["FFMPEG_PATH", "FFPROBE_PATH"]:
        custom_path = os.environ.get(path_env)
        if custom_path:
            custom_dir = os.path.dirname(custom_path)
            if custom_dir and os.path.isdir(custom_dir) and custom_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = custom_dir + os.pathsep + os.environ.get("PATH", "")


async def ensure_local_puzzles(limit: int = 50000):
    """Fill the offline puzzle cache on first run (Flash/Series read from it)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM local_puzzles")
        count = (await cursor.fetchone())[0]
    if count:
        return
    logger.info("Initializing local puzzle dataset (one-time). This may take a minute...")
    try:
        from download_puzzles import download_puzzles
        await asyncio.to_thread(download_puzzles, limit)
    except Exception as e:
        # Not fatal: Flash/Series fall back to the Lichess puzzle API
        logger.error(f"Failed to init local puzzles: {e}")


async def prepare_environment():
    """Everything a run needs before generating: DB schema, puzzle cache, assets."""
    _add_custom_ffmpeg_to_path()
    await init_db()
    await ensure_local_puzzles()
    await setup_assets()
    await download_sounds()
    await setup_music()


async def get_next_format() -> str:
    """Rotate formats based on the last one generated (flash -> story -> series)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT format FROM used_content ORDER BY created_at DESC LIMIT 1")
            row = await cursor.fetchone()
        if not row:
            return "flash"
        return {"flash": "story", "story": "series"}.get(row[0], "flash")
    except Exception as e:
        logger.warning(f"Error getting next format from database: {e}. Defaulting to flash.")
        return "flash"


async def hours_since_last_upload() -> float | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT (julianday('now') - julianday(MAX(uploaded_at))) * 24 FROM videos WHERE status = 'uploaded'"
        )
        row = await cursor.fetchone()
    return row[0] if row and row[0] is not None else None


async def _generate(fmt: str) -> dict:
    """Render one video and return what's needed to save and upload it."""
    if fmt == "flash":
        from pipeline.flash import generate_flash
        result = await generate_flash()
        return {
            "title": result["title"],
            "description": "Can you find the winning move? Follow Knightify Chess for a new puzzle every day.",
            "tags": ["chess", "tactics", "puzzle", "chesspuzzle"],
            "video_path": result["video_path"],
            "thumbnail_path": result["thumbnail_path"],
            "script_json": {"hook": result["hook"]},
            "hook": result["hook"],
        }

    if fmt == "story":
        from pipeline.story import generate_story
        # No hardcoded fallback positions when nobody is reviewing the video
        result = await generate_story(allow_fallback=False)
        script = result["script"]
        tags = script.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        return {
            "title": result["title"],
            "description": script.get("description", ""),
            "tags": tags + ["chessstory", "grandmaster"],
            "video_path": result["video_path"],
            "thumbnail_path": result["thumbnail_path"],
            "script_json": script,
            "hook": script.get("hook", ""),
        }

    if fmt == "series":
        from pipeline.series import generate_series
        result = await generate_series("outputs")
        series_id = await save_series_puzzle({
            'puzzle_number': result['puzzle_number'],
            'fen': "",
            'moves': "",
            'rating': result['rating'],
            'theme': result['script']['theme'],
            'video_path': result['video_path'],
            'thumbnail_path': result['thumbnail_path']
        })
        return {
            "title": result["title"],
            "description": f"Can you solve puzzle #{result['puzzle_number']}? A new one every day on Knightify Chess.",
            "tags": ["chess", "puzzle", "chesspuzzle", "dailypuzzle"],
            "video_path": result["video_path"],
            "thumbnail_path": result["thumbnail_path"],
            "script_json": result["script"],
            "hook": result["title"],
            "series_id": series_id,
        }

    raise ValueError(f"Unknown format: {fmt}")


def check_video(path: str) -> list:
    """Hard checks a Short must pass before upload. Returns the problems found."""
    if not path or not os.path.exists(path):
        return [f"video file missing: {path}"]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True
    )
    if probe.returncode != 0:
        return [f"ffprobe failed: {probe.stderr.strip()[:200]}"]
    info = json.loads(probe.stdout)
    streams = info.get("streams", [])

    problems = []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        problems.append("no video stream")
    elif int(video.get("height", 0)) <= int(video.get("width", 0)):
        problems.append(f"not vertical ({video.get('width')}x{video.get('height')})")
    if not any(s.get("codec_type") == "audio" for s in streams):
        problems.append("no audio stream")
    duration = float(info.get("format", {}).get("duration") or 0)
    if not 3 <= duration <= MAX_SHORT_SECONDS:
        problems.append(f"duration {duration:.1f}s outside 3-{MAX_SHORT_SECONDS}s")
    return problems


def _cleanup_render_files(video_path: str):
    """Frames are only needed for encoding and take hundreds of MB per video."""
    out_dir = os.path.dirname(video_path)
    shutil.rmtree(os.path.join(out_dir, "frames"), ignore_errors=True)
    for name in ("silent.mp4", "video_with_sfx.mp4"):
        try:
            os.remove(os.path.join(out_dir, name))
        except FileNotFoundError:
            pass


async def _mark_series_uploaded(series_id: int, youtube_url: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE puzzle_series SET status = 'uploaded', youtube_url = ? WHERE id = ?",
            (youtube_url, series_id)
        )
        await db.commit()


async def publish_daily(fmt: str = None, upload: bool = True, privacy: str = "public", force: bool = False) -> dict:
    """
    Generate one Short, QA it, and upload it to YouTube.

    fmt:     "flash" | "story" | "series", or None to follow the rotation
             (falling back to the next format if one fails).
    upload:  False renders and records the video without publishing it.
    force:   skip the once-a-day guard.

    Returns a summary dict; raises if nothing publishable was produced or the
    upload failed, so schedulers see a failed run.
    """
    await prepare_environment()

    if upload and not force:
        hours = await hours_since_last_upload()
        if hours is not None and hours < MIN_HOURS_BETWEEN_UPLOADS:
            logger.info(f"Last upload was {hours:.1f}h ago; skipping (use force to override).")
            return {"status": "skipped", "reason": f"last upload {hours:.1f}h ago"}

    if upload:
        # Fail fast on bad credentials before spending minutes rendering
        from pipeline.upload import get_authenticated_service
        await asyncio.to_thread(get_authenticated_service)

    available = list(FORMATS)
    if not os.getenv("GROQ_API_KEY"):
        available.remove("story")
        logger.warning("GROQ_API_KEY not set - the Story format is disabled.")

    if fmt:
        if fmt not in available:
            raise ValueError(f"Format '{fmt}' is not available (available: {', '.join(available)})")
        candidates = [fmt]
    else:
        first = await get_next_format()
        start = FORMATS.index(first)
        candidates = [f for f in FORMATS[start:] + FORMATS[:start] if f in available]

    errors = []
    for candidate in candidates:
        logger.info(f"Generating a {candidate} Short...")
        try:
            video = await _generate(candidate)
        except Exception as e:
            logger.error(f"{candidate} generation failed: {e}", exc_info=True)
            errors.append(f"{candidate}: {e}")
            continue
        problems = check_video(video["video_path"])
        if problems:
            logger.error(f"{candidate} video failed QA: {'; '.join(problems)}")
            errors.append(f"{candidate}: QA failed ({'; '.join(problems)})")
            continue
        break
    else:
        raise RuntimeError("Could not produce a publishable Short. " + " | ".join(errors))

    _cleanup_render_files(video["video_path"])

    db_id = await save_video({
        "title": video["title"],
        "description": video["description"],
        "thumbnail_path": video["thumbnail_path"],
        "video_path": video["video_path"],
        "script_json": video["script_json"],
        "format": candidate,
        "hook": video["hook"],
    })
    summary = {
        "status": "generated",
        "format": candidate,
        "title": video["title"],
        "video_path": video["video_path"],
        "db_id": db_id,
    }
    if not upload:
        logger.info(f"Dry run: {candidate} video saved to {video['video_path']} (not uploaded).")
        return summary

    from pipeline.upload import upload_to_youtube
    youtube_url, youtube_id = await asyncio.to_thread(
        upload_to_youtube,
        video_path=video["video_path"],
        thumbnail_path=video["thumbnail_path"],
        title=video["title"],
        description=video["description"],
        tags=video["tags"],
        privacy=privacy,
    )
    await update_video_status(db_id, "uploaded", youtube_url, youtube_id)
    if video.get("series_id"):
        await _mark_series_uploaded(video["series_id"], youtube_url)

    logger.info(f"Published {candidate} Short: {youtube_url}")
    summary.update(status="uploaded", youtube_url=youtube_url, youtube_id=youtube_id, privacy=privacy)
    return summary
