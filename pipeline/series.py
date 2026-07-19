import os
import random
import logging
import time
import json
import httpx
import textwrap
import subprocess
import asyncio
from database.db import get_next_puzzle_number, is_fen_used, mark_content_used, get_local_puzzle
from pipeline.board import generate_series_frames
from pipeline.audio_check import verify_audio
from pipeline.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

SERIES_HOOKS = [
    "Chess Puzzle #{number} 🧩",
    "Daily Puzzle #{number} - Can you solve it?",
    "Puzzle #{number}: Rating {rating}",
    "#{number} - Find the winning move!",
    "Chess Challenge #{number}",
    "Puzzle #{number} - {theme} theme",
    "Daily Chess #{number} 🔥",
    "Can YOU solve Puzzle #{number}?",
    "Chess Puzzle #{number} - {difficulty}",
    "#{number} Daily Grind 🎯"
]

def run_cmd(cmd: list):
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg failed: {result.stderr}")
        raise RuntimeError(f"FFmpeg command failed: {result.stderr}")

async def fetch_unique_series_puzzle(number: int):
    if number <= 50: min_r, max_r = 0, 1500
    elif number <= 100: min_r, max_r = 1400, 1700
    elif number <= 200: min_r, max_r = 1600, 1900
    elif number <= 500: min_r, max_r = 1800, 2200
    else: min_r, max_r = 2000, 3500
    
    local_p = await get_local_puzzle(min_r, max_r)
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
                
                if not (min_r <= rating <= max_r):
                    await asyncio.sleep(0.5)
                    continue
                    
                if await is_fen_used(pgn):
                    await asyncio.sleep(0.5)
                    continue
                    
                return data
            except Exception as e:
                logger.warning(f"Lichess API error: {e}")
                await asyncio.sleep(2)
        raise ValueError(f"Failed to find a unique puzzle in range {min_r}-{max_r} after 40 tries.")

async def generate_series(output_base_dir="outputs", target_number=None):
    if target_number:
        number = target_number
    else:
        number = await get_next_puzzle_number()
        
    logger.info(f"Generating Puzzle Series #{number}...")
    timestamp = int(time.time())
    output_dir = os.path.join(output_base_dir, f"series_{number}_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    
    puzzle_data = await fetch_unique_series_puzzle(number)
    rating = puzzle_data["puzzle"]["rating"]
    pgn = puzzle_data["game"]["pgn"]
    themes = puzzle_data["puzzle"]["themes"]
    theme = themes[0].capitalize() if themes else "Tactics"
    
    if rating < 1400: difficulty = "Beginner"
    elif rating < 1600: difficulty = "Intermediate"
    elif rating < 1800: difficulty = "Advanced"
    elif rating < 2000: difficulty = "Expert"
    else: difficulty = "Grandmaster Level"
    
    hook_template = random.choice(SERIES_HOOKS)
    hook_text = hook_template.format(number=number, rating=rating, theme=theme, difficulty=difficulty)
    
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
    first_frame = os.path.join(frames_dir, "frame_0000.png")
    frames_result = generate_series_frames(
        fen, sol_moves, number,
        rating=rating,
        themes=themes,
        cta_text="Can you solve it? Follow Knightify Chess for more!",
        output_dir=output_dir
    )
    frame_paths = frames_result["frames"]
    move_timestamps = frames_result["move_timestamps"]
    
    silent_video = os.path.join(output_dir, "silent.mp4")
    video_path = os.path.join(output_dir, "final.mp4")
    
    frames_pattern = os.path.join(frames_dir, "frame_%04d.png")
    
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
    inputs = ["ffmpeg", "-y", "-i", silent_video]
    filter_parts = []
    mix_labels = []
    
    input_idx = 1
    for i, move in enumerate(move_timestamps):
        delay_ms = int(move["time"] * 1000)
        sound_file = "capture.mp3" if move.get("is_capture") else "move.mp3"
        sound_path = os.path.join("assets", "sounds", sound_file)
        if not os.path.exists(sound_path):
            sound_path = sound_path.replace(".mp3", ".wav")
            
        if os.path.exists(sound_path):
            inputs.extend(["-i", sound_path])
            filter_parts.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume=0.8[s{i}]")
            mix_labels.append(f"[s{i}]")
            input_idx += 1
            
    chime_path = os.path.join("assets", "sounds", "correct.wav")
    if os.path.exists(chime_path):
        inputs.extend(["-i", chime_path])
        delay_ms = 5000
        filter_parts.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume=1.0[chime]")
        mix_labels.append("[chime]")
        input_idx += 1
        
    if filter_parts:
        n_sounds = len(mix_labels)
        mix_labels_str = "".join(mix_labels)
        filter_parts.append(f"{mix_labels_str}amix=inputs={n_sounds}:duration=longest[sfx]")
        
        inputs.extend([
            "-filter_complex", ";".join(filter_parts),
            "-map", "0:v", "-map", "[sfx]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            video_with_sfx
        ])
        run_cmd(inputs)
    else:
        import shutil
        shutil.copy(silent_video, video_with_sfx)
        
    from pipeline.assets_setup import get_random_track
    bg_music = get_random_track("flash")
    
    if bg_music:
        from pipeline.video import normalize_music_file, get_video_duration
        normalized = normalize_music_file(bg_music)
        if normalized:
            from pipeline.audio_check import verify_audio
            has_sfx = verify_audio(video_with_sfx).get("has_audio")
            duration = get_video_duration(video_with_sfx)
            
            cmd2 = ["ffmpeg", "-y", "-i", video_with_sfx, "-stream_loop", "-1", "-i", normalized]
            if has_sfx:
                cmd2.extend([
                    "-filter_complex", f"[0:a]volume=1.0[sfx];[1:a]volume=0.18,afade=t=in:st=0:d=0.5,afade=t=out:st={duration-1}:d=1,atrim=duration={duration}[music];[sfx][music]amix=inputs=2:duration=longest,loudnorm=I=-14:LRA=11:TP=-1.5[aout]",
                    "-map", "0:v", "-map", "[aout]"
                ])
            else:
                cmd2.extend([
                    "-filter_complex", f"[1:a]volume=0.18,afade=t=in:st=0:d=0.5,afade=t=out:st={duration-1}:d=1,atrim=duration={duration},loudnorm=I=-14:LRA=11:TP=-1.5[aout]",
                    "-map", "0:v", "-map", "[aout]"
                ])
            cmd2.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-t", str(duration), video_path])
            run_cmd(cmd2)
        else:
            import shutil
            shutil.copy(video_with_sfx, video_path)
    else:
        import shutil
        shutil.copy(video_with_sfx, video_path)
        
    from pipeline.thumbnail import generate_series_thumbnail
    thumb_path = os.path.join(output_dir, "thumbnail.png")
    generate_series_thumbnail(fen, number, rating, thumb_path)
    
    await mark_content_used(pgn, hook=hook_text, format="series")
    
    script_data = {"hook": hook_text, "rating": rating, "theme": theme, "difficulty": difficulty}
    script_path = os.path.join(output_dir, "script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script_data, f)
        
    return {
        "video_path": video_path,
        "thumbnail_path": thumb_path,
        "title": hook_text,
        "script": script_data,
        "puzzle_number": number,
        "rating": rating
    }
