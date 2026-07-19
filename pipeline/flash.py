import os
import random
import logging
import time
import json
import httpx
import subprocess
import textwrap
import asyncio
from database.db import is_fen_used, is_hook_used_recently, mark_content_used, get_local_puzzle
from pipeline.board import generate_flash_frames
from pipeline.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

FLASH_HOOKS = [
    "Can YOU find it? 🤔",
    "99% miss this move",
    "Spot the winning move!",
    "Only geniuses see this",
    "White to move. Find it.",
    "This move wins everything",
    "The ONLY move that works",
    "Puzzle rating: {rating}. Solve it!",
    "Even GMs struggle with this",
    "Find the move in 3 seconds",
    "What would Magnus play here?",
    "This wins instantly. See it?",
    "One move changes everything",
    "The move nobody expects",
    "Chess IQ test: find the move"
]

def run_cmd(cmd: list):
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg failed: {result.stderr}")
        raise RuntimeError(f"FFmpeg command failed: {result.stderr}")

async def fetch_unique_flash_puzzle():
    local_p = await get_local_puzzle(1300, 2300)
    if local_p:
        logger.info(f"Using local puzzle {local_p['puzzle']['id']} (rating {local_p['puzzle']['rating']})")
        return local_p
        
    async with httpx.AsyncClient(verify=get_ssl_context()) as client:
        for attempt in range(40):
            try:
                resp = await client.get("https://lichess.org/api/puzzle/next")
                if resp.status_code == 429:
                    logger.warning("Lichess rate limit hit. Sleeping...")
                    await asyncio.sleep(5)
                    continue
                    
                resp.raise_for_status()
                data = resp.json()
                
                game = data.get("game", {})
                puzzle = data.get("puzzle", {})
                pgn = game.get("pgn", "")
                rating = puzzle.get("rating", 1500)
                
                if not (1300 <= rating <= 2300):
                    logger.info(f"Puzzle rating {rating} outside 1300-2300, retrying...")
                    await asyncio.sleep(0.5)
                    continue
                    
                if await is_fen_used(pgn):
                    logger.info("Puzzle already used, retrying...")
                    await asyncio.sleep(0.5)
                    continue
                    
                return data
            except Exception as e:
                logger.error(f"Failed to fetch puzzle: {e}")
                await asyncio.sleep(2)
                
        raise ValueError("Failed to find a unique, suitable puzzle for Flash after 40 tries.")

async def generate_flash(output_base_dir="outputs"):
    logger.info("Starting Flash generation...")
    timestamp = int(time.time())
    output_dir = os.path.join(output_base_dir, f"flash_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Fetch puzzle
    puzzle_data = await fetch_unique_flash_puzzle()
    rating = puzzle_data["puzzle"]["rating"]
    pgn = puzzle_data["game"]["pgn"]
    
    # 2. Pick hook
    hook_template = random.choice(FLASH_HOOKS)
    for _ in range(10):
        if not await is_hook_used_recently(hook_template):
            break
        hook_template = random.choice(FLASH_HOOKS)
        
    hook_text = hook_template.format(rating=rating)
    
    # 3. Generate board frames
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    # Lichess puzzle API "pgn" field is actually just a space separated move list, wait!
    # Ah, the `pgn` is actually space-separated moves from start pos.
    # Actually wait, `initialPly` tells us how many moves to skip to reach puzzle start.
    # And `puzzle["solution"]` is the actual solution moves.
    # Let's just use the logic from puzzle.py to get the fen and solution moves.
    pgn_str = puzzle_data["game"]["pgn"]
    import chess
    if "/" in pgn_str:
        b = chess.Board(pgn_str)
    else:
        moves = pgn_str.split()
        b = chess.Board()
        for m in moves:
            b.push_san(m)
    fen = b.fen()
    sol_moves = puzzle_data["puzzle"]["solution"]
    
    frames_dir = os.path.join(output_dir, "frames")
    frames_result = generate_flash_frames(
        fen, sol_moves, 
        rating=rating, 
        themes=puzzle_data.get("puzzle", {}).get("themes", []),
        cta_text="Can you solve it? Follow Knightify Chess for more!",
        output_dir=output_dir
    )
    frame_paths = frames_result["frames"]
    move_timestamps = frames_result["move_timestamps"]
    
    # 4. Generate video
    video_path = os.path.join(output_dir, "final.mp4")
    
    from pipeline.assets_setup import get_random_track
    bg_music = get_random_track("flash")
        
    frames_pattern = os.path.join(frames_dir, "frame_%04d.png")
        
    silent_video = os.path.join(output_dir, "silent.mp4")
    
    cmd1 = [
        "ffmpeg", "-y",
        "-framerate", "30",
        "-i", frames_pattern,
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        silent_video
    ]
    run_cmd(cmd1)
    
    video_with_sfx = os.path.join(output_dir, "video_with_sfx.mp4")
    if move_timestamps:
        inputs = ["ffmpeg", "-y", "-i", silent_video]
        filter_parts = []
        mix_labels = []
        
        for i, move in enumerate(move_timestamps):
            delay_ms = int(move["time"] * 1000)
            sound_file = "capture.mp3" if move.get("is_capture") else "move.mp3"
            sound_path = os.path.join("assets", "sounds", sound_file)
            
            if not os.path.exists(sound_path):
                alt_path = sound_path.replace(".mp3", ".wav")
                if os.path.exists(alt_path):
                    sound_path = alt_path
            
            if os.path.exists(sound_path):
                inputs.extend(["-i", sound_path])
                filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms},volume=0.8[s{i}]")
                mix_labels.append(f"[s{i}]")
                
        if filter_parts:
            n_sounds = len(mix_labels)
            mix_labels_str = "".join(mix_labels)
            filter_parts.append(f"{mix_labels_str}amix=inputs={n_sounds}:duration=longest[sfx]")
            filter_complex = ";".join(filter_parts)
            
            inputs.extend([
                "-filter_complex", filter_complex,
                "-map", "0:v", "-map", "[sfx]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                video_with_sfx
            ])
            run_cmd(inputs)
        else:
            import shutil
            shutil.copy(silent_video, video_with_sfx)
    else:
        import shutil
        shutil.copy(silent_video, video_with_sfx)
    
    if bg_music:
        from pipeline.video import normalize_music_file, get_video_duration
        normalized = normalize_music_file(bg_music)
        if normalized:
            from pipeline.audio_check import verify_audio
            has_sfx = verify_audio(video_with_sfx).get("has_audio")
            duration = get_video_duration(video_with_sfx)
            
            cmd2 = [
                "ffmpeg", "-y",
                "-i", video_with_sfx,
                "-stream_loop", "-1", "-i", normalized
            ]
            
            if has_sfx:
                cmd2.extend([
                    "-filter_complex", f"[0:a]volume=1.0[sfx];[1:a]volume=0.18,afade=t=in:st=0:d=0.5,afade=t=out:st={duration-1}:d=1.0,atrim=duration={duration}[music];[sfx][music]amix=inputs=2:duration=longest,loudnorm=I=-14:LRA=11:TP=-1.5[aout]",
                    "-map", "0:v", "-map", "[aout]"
                ])
            else:
                cmd2.extend([
                    "-filter_complex", f"[1:a]volume=0.18,afade=t=in:st=0:d=0.5,afade=t=out:st={duration-1}:d=1.0,atrim=duration={duration},loudnorm=I=-14:LRA=11:TP=-1.5[aout]",
                    "-map", "0:v", "-map", "[aout]"
                ])
                
            cmd2.extend([
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                "-t", str(duration),
                video_path
            ])
            run_cmd(cmd2)
        else:
            import shutil
            shutil.copy(video_with_sfx, video_path)
    else:
        import shutil
        shutil.copy(video_with_sfx, video_path)
    
    # 5. Thumbnail
    thumb_path = os.path.join(output_dir, "thumbnail.png")
    first_frame = os.path.join(frames_dir, "frame_0000.png")
    if os.path.exists(first_frame):
        import shutil
        shutil.copy(first_frame, thumb_path)
        
    # Mark used
    await mark_content_used(pgn, hook=hook_text, format="flash")
    
    script_path = os.path.join(output_dir, "script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump({"hook": hook_text, "rating": rating}, f)
        
    return {
        "video_path": video_path,
        "thumbnail_path": thumb_path,
        "title": f"Can you find the winning move? (Rating: {rating})",
        "hook": hook_text
    }
