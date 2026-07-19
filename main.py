import os
import json
import logging
from dotenv import load_dotenv
load_dotenv()

# Prepend custom FFmpeg paths to system PATH for child processes
for path_env in ["FFMPEG_PATH", "FFPROBE_PATH"]:
    custom_path = os.environ.get(path_env)
    if custom_path:
        custom_dir = os.path.dirname(custom_path)
        if custom_dir and os.path.isdir(custom_dir) and custom_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = custom_dir + os.pathsep + os.environ.get("PATH", "")

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler


from pipeline.puzzle import fetch_champion_game
from pipeline.script import generate_script
from pipeline.voice import generate_voice
from pipeline.board import generate_frames
from pipeline.video import combine_video
from pipeline.thumbnail import generate_thumbnail
from pipeline.upload import upload_to_youtube
from pipeline.setup import setup_assets
from pipeline.assets_setup import setup_music, download_sounds
from pipeline.series import generate_series
from database.db import (
    init_db, save_video, get_all_videos, update_video_status, 
    get_stats, delete_video, get_all_series, get_series_stats, save_series_puzzle
)


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    
    # Preload local puzzles if missing
    import sqlite3
    try:
        conn = sqlite3.connect('database/chess_shorts.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM local_puzzles")
        if c.fetchone()[0] == 0:
            import subprocess
            logger.info("Initializing local puzzle dataset (one-time). This may take a minute...")
            subprocess.run(["python", "download_puzzles.py"])
        conn.close()
    except Exception as e:
        logger.error(f"Failed to init local puzzles: {e}")
        
    await setup_assets()
    await download_sounds()
    await setup_music()
    
    # Load schedule
    sched_path = os.path.join("config", "schedule.json")
    if os.path.exists(sched_path):
        try:
            with open(sched_path, "r") as f:
                sched = json.load(f)
            if sched.get("enabled"):
                time_str = sched.get("time", "09:00")
                hour, minute = map(int, time_str.split(':'))
                scheduler.add_job(run_scheduled_cycle, 'cron', hour=hour, minute=minute, id="daily_video", replace_existing=True)
                logger.info(f"Scheduled 1x/day video generation cycle for {time_str}")
        except Exception as e:
            logger.error(f"Error loading schedule: {e}")
            
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(title="Chess Shorts API", lifespan=lifespan)
app.mount("/files", StaticFiles(directory="."), name="files")

class PuzzleModel(BaseModel):
    fen: str
    moves: List[str]
    rating: int
    themes: List[str]
    player: str = "Magnus Carlsen"
    opponent: str = "Unknown"
    event: str = "Event"
    year: str = "2023"
    tactic: str = "Tactics"
    source: str = "unknown"

class VoiceRequest(BaseModel):
    text: str

class BoardRequest(BaseModel):
    fen: str
    moves: List[str]

class ThumbnailRequest(BaseModel):
    fen: str
    title: str
    rating: int

class UploadRequest(BaseModel):
    video_id: int
    privacy_status: str = "public"

class ScheduleRequest(BaseModel):
    time: str
    enabled: bool = True

@app.get("/puzzle")
async def get_puzzle():
    """Fetch and return a random champion game/puzzle."""
    try:
        puzzle_data = await fetch_champion_game()
        return puzzle_data
    except Exception as e:
        logger.error(f"Failed to fetch puzzle: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/script")
async def create_script(puzzle: PuzzleModel):
    """Accept puzzle dict, return generated script."""
    try:
        # Convert pydantic model to dict
        script_data = generate_script(puzzle.model_dump())
        return script_data
    except Exception as e:
        logger.error(f"Failed to generate script: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from pipeline.flash import generate_flash
from pipeline.story import generate_story
from pipeline.analytics import sync_all_uploaded_analytics

@app.post("/analytics/sync")
async def sync_analytics():
    """Trigger a sync of video views and retention percentages from YouTube."""
    try:
        res = await sync_all_uploaded_analytics()
        return res
    except Exception as e:
        logger.error(f"Failed to sync analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/flash")
async def api_generate_flash():
    """Generate a 10s Puzzle Flash video."""
    try:
        result = await generate_flash()
        
        # Save to DB
        db_id = await save_video({
            "title": result["title"],
            "description": "Can you find the winning move? #chess #tactics #puzzle",
            "thumbnail_path": result["thumbnail_path"],
            "video_path": result["video_path"],
            "script_json": json.dumps({"hook": result["hook"], "tags": "chess, tactics, shorts"}),
            "format": "flash",
            "hook": result["hook"]
        })
        result["db_id"] = db_id
        return result
    except Exception as e:
        logger.error(f"Error in Flash pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/story")
async def api_generate_story():
    """Generate a 30s Champion Story video."""
    try:
        result = await generate_story()
        
        # Save to DB
        db_id = await save_video({
            "title": result["title"],
            "description": result["script"].get("description", ""),
            "thumbnail_path": result["thumbnail_path"],
            "video_path": result["video_path"],
            "script_json": result["script"],
            "format": "story",
            "hook": result["script"].get("hook", "")
        })
        result["db_id"] = db_id
        return result
    except Exception as e:
        logger.error(f"Error in Story pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/series")
async def generate_series_endpoint(number: int = None):
    try:
        result = await generate_series("outputs", target_number=number)
        db_id = await save_series_puzzle({
            'puzzle_number': result['puzzle_number'],
            'fen': "",
            'moves': "",
            'rating': result['rating'],
            'theme': result['script']['theme'],
            'video_path': result['video_path'],
            'thumbnail_path': result['thumbnail_path']
        })
        
        video_id = await save_video({
            "title": result["title"],
            "description": f"Can you solve puzzle #{result['puzzle_number']}?",
            "thumbnail_path": result["thumbnail_path"],
            "video_path": result["video_path"],
            "script_json": json.dumps(result["script"]),
            "format": "series",
            "hook": result["title"]
        })
        return {"status": "success", "video_id": video_id, "series_id": db_id, **result}
    except Exception as e:
        logger.error(f"Series generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/series")
async def get_series_list():
    return await get_all_series()

@app.get("/series/stats")
async def get_series_stats_endpoint():
    return await get_series_stats()

from fastapi.responses import StreamingResponse

@app.get("/generate/series/bulk")
async def bulk_generate_series(count: int = 5):
    count = min(count, 10)
    async def event_generator():
        for i in range(1, count + 1):
            try:
                result = await generate_series("outputs")
                await save_series_puzzle({
                    'puzzle_number': result['puzzle_number'],
                    'rating': result['rating'],
                    'theme': result['script']['theme'],
                    'video_path': result['video_path'],
                    'thumbnail_path': result['thumbnail_path']
                })
                await save_video({
                    "title": result["title"],
                    "description": f"Can you solve puzzle #{result['puzzle_number']}?",
                    "thumbnail_path": result["thumbnail_path"],
                    "video_path": result["video_path"],
                    "script_json": json.dumps(result["script"]),
                    "format": "series",
                    "hook": result["title"]
                })
                yield f"data: {json.dumps({'done': i, 'total': count, 'number': result['puzzle_number']})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/voice")
async def create_voice(req: VoiceRequest):
    """Generate voice from text, return file path."""
    try:
        path = await generate_voice(req.text)
        return {"voice_path": path}
    except Exception as e:
        logger.error(f"Failed to generate voice: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/board")
async def create_board_frames(req: BoardRequest):
    """Generate board frames, return frame paths."""
    try:
        paths = generate_frames(req.fen, req.moves)
        return {"frame_paths": paths}
    except Exception as e:
        logger.error(f"Failed to generate board frames: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/phase2")
async def run_phase2():
    """Run full phase 2: take script.json, generate voice + board frames together."""
    try:
        script_path = os.path.join("outputs", "script.json")
        if not os.path.exists(script_path):
            raise FileNotFoundError("script.json not found in outputs/ directory. Run /generate first.")
            
        with open(script_path, "r") as f:
            data = json.load(f)
            
        puzzle = data.get("puzzle", {})
        script = data.get("script", {})
        
        # Combine text for voice generation
        text_parts = [
            script.get("hook", ""),
            script.get("explanation", ""),
            script.get("solution", ""),
            script.get("cta", "")
        ]
        full_text = " ".join([str(p) for p in text_parts if p])
        
        # Run generation
        voice_path = await generate_voice(full_text)
        
        fen = puzzle.get("fen", "")
        moves = puzzle.get("moves", [])
        frame_paths = generate_frames(fen, moves)
        
        return {
            "status": "success",
            "voice_path": voice_path,
            "frames_count": len(frame_paths),
            "frame_paths": frame_paths
        }
    except Exception as e:
        logger.error(f"Error in phase 2 pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/video")
async def create_video():
    """Run combine_video(), returns output path."""
    try:
        script_path = os.path.join("outputs", "script.json")
        voice_path = os.path.join("outputs", "voice.mp3")
        frames_dir = os.path.join("outputs", "frames")
        output_path = os.path.join("outputs", "final.mp4")
        
        path = combine_video(script_path, voice_path, frames_dir, output_path)
        return {"video_path": path}
    except Exception as e:
        logger.error(f"Failed to combine video: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/thumbnail")
async def create_thumbnail(req: ThumbnailRequest):
    """Generate thumbnail."""
    try:
        output_path = os.path.join("outputs", "thumbnail.png")
        path = generate_thumbnail(req.fen, req.title, req.rating, output_path)
        return {"thumbnail_path": path}
    except Exception as e:
        logger.error(f"Failed to generate thumbnail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pipeline")
async def run_master_pipeline():
    """MASTER ENDPOINT: runs full pipeline in order."""
    try:
        os.makedirs("outputs", exist_ok=True)
        
        # 1. GET puzzle
        puzzle_data = await fetch_champion_game()
        
        # 2. Generate script
        script_data = generate_script(puzzle_data)
        
        script_path = os.path.join("outputs", "script.json")
        with open(script_path, "w") as f:
            json.dump({"puzzle": puzzle_data, "script": script_data}, f, indent=4)
            
        # 3. Generate voice
        text_parts = [
            script_data.get("hook", ""),
            script_data.get("explanation", ""),
            script_data.get("solution", ""),
            script_data.get("cta", "")
        ]
        full_text = " ".join([str(p) for p in text_parts if p])
        voice_path = await generate_voice(full_text)
        
        # 4. Generate board frames
        fen = puzzle_data.get("fen", "")
        moves = puzzle_data.get("moves", [])
        frames_paths = generate_frames(fen, moves)
        
        # 5. Combine video
        frames_dir = os.path.join("outputs", "frames")
        video_output_path = os.path.join("outputs", "final.mp4")
        final_video = combine_video(script_path, voice_path, frames_dir, video_output_path)
        
        # 6. Generate thumbnail
        title = script_data.get("title", f"{puzzle_data.get('player')} Brilliancy")
        rating = puzzle_data.get("rating", 1500)
        thumb_output_path = os.path.join("outputs", "thumbnail.png")
        final_thumb = generate_thumbnail(
            fen, 
            puzzle_data.get('player', 'Unknown'), 
            puzzle_data.get('opponent', 'Unknown'), 
            puzzle_data.get('event', 'Event'), 
            str(puzzle_data.get('year', '2023')), 
            puzzle_data.get('tactic', 'Tactic'), 
            thumb_output_path
        )
        
        # 7. Save to DB
        db_id = await save_video({
            "title": title,
            "description": script_data.get("description", ""),
            "thumbnail_path": final_thumb,
            "video_path": final_video,
            "script_json": script_data
        })
        
        return {
            "status": "success",
            "db_id": db_id,
            "metadata": {
                "puzzle_rating": rating,
                "moves_count": len(moves)
            },
            "files": {
                "script": script_path,
                "voice": voice_path,
                "video": final_video,
                "thumbnail": final_thumb
            }
        }
    except Exception as e:
        logger.error(f"Error in master pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def is_youtube_quota_exhausted() -> bool:
    """Check if the YouTube Data API quota is exhausted using a cheap 1-unit call."""
    try:
        from pipeline.upload import get_authenticated_service
        youtube = get_authenticated_service()
        youtube.channels().list(part="id", mine=True).execute()
        return False
    except Exception as e:
        err_msg = str(e).lower()
        if "quotaexceeded" in err_msg or "quota exceeded" in err_msg:
            logger.warning(f"YouTube quota is exhausted: {e}")
            return True
        logger.error(f"Error checking YouTube quota: {e}")
        return False

async def get_next_format() -> str:
    """Query the last used format from the database to rotate formats (flash -> story -> series)."""
    try:
        import aiosqlite
        from database.db import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT format FROM used_content ORDER BY created_at DESC LIMIT 1")
            row = await cursor.fetchone()
            if not row:
                return "flash"
            last_format = row[0]
            if last_format == "flash":
                return "story"
            elif last_format == "story":
                return "series"
            else:
                return "flash"
    except Exception as e:
        logger.warning(f"Error getting next format from database: {e}. Defaulting to flash.")
        return "flash"

async def run_scheduled_cycle():
    """Scheduled job that runs daily: checks quota, rotates formats, generates, and saves as pending."""
    logger.info("Starting scheduled video generation cycle...")
    if is_youtube_quota_exhausted():
        logger.warning("YouTube quota is exhausted for today. Skipping scheduled run gracefully.")
        return
        
    fmt = await get_next_format()
    logger.info(f"Scheduled Run - Selected format: {fmt}")
    
    try:
        if fmt == "flash":
            from pipeline.flash import generate_flash
            logger.info("Executing Flash video generator...")
            result = await generate_flash()
            db_id = await save_video({
                "title": result["title"],
                "description": "Can you find the winning move? #chess #tactics #puzzle #shorts",
                "thumbnail_path": result["thumbnail_path"],
                "video_path": result["video_path"],
                "script_json": json.dumps({"hook": result["hook"], "tags": "chess, tactics, shorts"}),
                "format": "flash",
                "hook": result["hook"]
            })
            
        elif fmt == "story":
            from pipeline.story import generate_story
            logger.info("Executing Story video generator...")
            result = await generate_story()
            db_id = await save_video({
                "title": result["title"],
                "description": result["script"].get("description", "") + "\n\n#shorts #chess #story",
                "thumbnail_path": result["thumbnail_path"],
                "video_path": result["video_path"],
                "script_json": json.dumps(result["script"]),
                "format": "story",
                "hook": result["script"].get("hook", "")
            })
            
        else: # series
            from pipeline.series import generate_series
            logger.info("Executing Series video generator...")
            result = await generate_series("outputs")
            series_db_id = await save_series_puzzle({
                'puzzle_number': result['puzzle_number'],
                'fen': "",
                'moves': "",
                'rating': result['rating'],
                'theme': result['script']['theme'],
                'video_path': result['video_path'],
                'thumbnail_path': result['thumbnail_path']
            })
            db_id = await save_video({
                "title": result["title"],
                "description": f"Can you solve puzzle #{result['puzzle_number']}? #shorts #chess #series",
                "thumbnail_path": result["thumbnail_path"],
                "video_path": result["video_path"],
                "script_json": json.dumps(result["script"]),
                "format": "series",
                "hook": result["title"]
            })
            
        logger.info(f"Video generated successfully and saved to DB with ID: {db_id} as pending.")
            
    except Exception as e:
        logger.error(f"Scheduled video generation cycle failed: {e}", exc_info=True)

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the dashboard UI."""
    try:
        with open("dashboard/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

@app.get("/videos")
async def get_videos():
    """Return all videos from db."""
    try:
        return await get_all_videos()
    except Exception as e:
        logger.error(f"Failed to get videos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def fetch_stats():
    """Return DB stats."""
    try:
        return await get_stats()
    except Exception as e:
        logger.error(f"Failed to fetch stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/music/status")
async def music_status():
    """Return music tracks availability status."""
    from pipeline.assets_setup import scan_music_library
    import os
    tracks = scan_music_library()
    flash_count = len(tracks["flash"])
    story_count = len(tracks["story"])
    
    warnings = []
    if flash_count == 0:
        warnings.append("⚠️ No flash music. Add .mp3 files to assets/music/flash/")
    if story_count == 0:
        warnings.append("⚠️ No story music. Add .mp3 files to assets/music/story/")
        
    return {
        "flash": {
            "count": flash_count,
            "tracks": [os.path.basename(t) for t in tracks["flash"]],
            "ready": flash_count > 0
        },
        "story": {
            "count": story_count,
            "tracks": [os.path.basename(t) for t in tracks["story"]],
            "ready": story_count > 0
        },
        "warnings": warnings
    }

@app.post("/upload")
async def trigger_upload(req: UploadRequest):
    """Upload a specific video to YouTube."""
    try:
        videos = await get_all_videos()
        video = next((v for v in videos if v["id"] == req.video_id), None)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
            
        try:
            # Handle standard json
            script = json.loads(video["script_json"])
            if not isinstance(script, dict):
                script = {}
        except Exception:
            # Fallback if it was saved as a stringified python dictionary or is missing
            import ast
            try:
                script = ast.literal_eval(video["script_json"]) if video.get("script_json") else {}
                if not isinstance(script, dict):
                    script = {}
            except Exception:
                script = {}
                
        title = video["title"]
        description = video["description"]
        tags = script.get("tags", "chess, tactics, shorts")
        if isinstance(tags, str):
            tags = tags.split(",")
        tags = [t.strip() for t in tags if t.strip()]
        
        yt_url, yt_id = upload_to_youtube(
            video_path=video["video_path"],
            thumbnail_path=video["thumbnail_path"],
            title=title,
            description=description,
            tags=tags,
            privacy=req.privacy_status
        )
        
        await update_video_status(req.video_id, "uploaded", yt_url, yt_id)
        return {"status": "success", "youtube_url": yt_url}
        
    except Exception as e:
        logger.error(f"Failed to upload video: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/videos/{video_id}")
async def remove_video(video_id: int):
    """Delete video from DB and optionally its files."""
    try:
        video = await delete_video(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
            
        # Optional: delete physical files
        for path_key in ["video_path", "thumbnail_path"]:
            if video.get(path_key) and os.path.exists(video[path_key]):
                try:
                    os.remove(video[path_key])
                except OSError as oe:
                    logger.warning(f"Could not delete file {video[path_key]}: {oe}")
                    
        return {"status": "success", "deleted": video_id}
    except Exception as e:
        logger.error(f"Failed to delete video: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/schedule")
async def update_schedule(req: ScheduleRequest):
    """Update automation schedule."""
    try:
        os.makedirs("config", exist_ok=True)
        sched_path = os.path.join("config", "schedule.json")
        
        data = {"time": req.time, "enabled": req.enabled}
        with open(sched_path, "w") as f:
            json.dump(data, f, indent=4)
            
        # Update APScheduler
        if scheduler.get_job("daily_video"):
            scheduler.remove_job("daily_video")
            
        if req.enabled:
            hour, minute = map(int, req.time.split(':'))
            scheduler.add_job(run_scheduled_cycle, 'cron', hour=hour, minute=minute, id="daily_video", replace_existing=True)
            logger.info(f"Scheduled 1x/day video generation cycle for {req.time}")
            
        return {"status": "success", "schedule": data}
    except Exception as e:
        logger.error(f"Failed to update schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))
