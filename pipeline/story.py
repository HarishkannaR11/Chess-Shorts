import os
import time
import json
import logging
from pipeline.puzzle import fetch_champion_game
from pipeline.script import generate_script
from pipeline.voice import generate_voice
from pipeline.board import generate_frames
from pipeline.video import combine_video
from pipeline.thumbnail import generate_thumbnail
from database.db import mark_content_used

logger = logging.getLogger(__name__)

async def generate_story(output_base_dir="outputs"):
    """MASTER ENDPOINT logic: runs full story pipeline in order."""
    logger.info("Starting Story generation...")
    timestamp = int(time.time())
    output_dir = os.path.join(output_base_dir, f"story_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. GET puzzle (champion game)
    from database.db import get_last_champion
    last_champ = await get_last_champion()
    
    rotation = ["Magnus Carlsen", "Praggnanandhaa R", "Hikaru Nakamura", "Viswanathan Anand"]
    
    target_champ = "Magnus Carlsen"
    if last_champ in rotation:
        next_idx = (rotation.index(last_champ) + 1) % len(rotation)
        target_champ = rotation[next_idx]
        
    puzzle_data = await fetch_champion_game(target_player=target_champ)
    
    # 2. Generate script
    script_data = generate_script(puzzle_data)
    
    script_path = os.path.join(output_dir, "script.json")
    with open(script_path, "w") as f:
        json.dump({"puzzle": puzzle_data, "script": script_data}, f, indent=4)
        
    # 3. Generate voice
    # User spec: "Generate voice from full_script only"
    full_text = script_data.get("full_script", "")
    if not full_text:
        # Fallback if old format
        text_parts = [
            script_data.get("hook", ""),
            script_data.get("setup", ""),
            script_data.get("tension", ""),
            script_data.get("reveal", ""),
            script_data.get("lesson", ""),
            script_data.get("cta", "")
        ]
        full_text = " ".join([str(p) for p in text_parts if p])
        
    voice_path = await generate_voice(full_text)
    
    # Move voice file to our directory
    new_voice_path = os.path.join(output_dir, "voice.mp3")
    if os.path.exists(voice_path):
        import shutil
        shutil.move(voice_path, new_voice_path)
    
    # 4. Generate board frames
    fen = puzzle_data.get("fen", "")
    moves = puzzle_data.get("moves", [])
    frames_result = generate_frames(fen, moves)
    frames_paths = frames_result["frames"]
    move_timestamps = frames_result["move_timestamps"]
    
    # Move frames to our directory
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    import shutil
    for fp in frames_paths:
        if os.path.exists(fp):
            shutil.move(fp, os.path.join(frames_dir, os.path.basename(fp)))
            
    # 5. Combine video
    video_output_path = os.path.join(output_dir, "final.mp4")
    final_video = combine_video(script_path, new_voice_path, frames_dir, video_output_path, move_timestamps=move_timestamps)
    
    # 6. Generate thumbnail
    title = script_data.get("title", f"{puzzle_data.get('player')} Brilliancy")
    rating = puzzle_data.get("rating", 2800)
    thumb_output_path = os.path.join(output_dir, "thumbnail.png")
    final_thumb = generate_thumbnail(
        fen, 
        puzzle_data.get('player', 'Unknown'), 
        puzzle_data.get('opponent', 'Unknown'), 
        puzzle_data.get('event', 'Event'), 
        str(puzzle_data.get('year', '2023')), 
        puzzle_data.get('tactic', 'Tactic'), 
        thumb_output_path
    )
    
    # Mark used in our new format-aware DB
    hook = script_data.get("hook", "")
    await mark_content_used(fen, player=puzzle_data.get('player'), event=puzzle_data.get('event'), hook=hook, format="story")
    
    return {
        "video_path": final_video,
        "thumbnail_path": final_thumb,
        "title": title,
        "script": script_data
    }
