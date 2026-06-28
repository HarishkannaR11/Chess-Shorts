import os
import wave
import struct
import math
import logging

logger = logging.getLogger(__name__)

def create_fallback_tick(filepath: str):
    """Generate 8s subtle clock tick loop (440Hz beep every 1s, 10% volume)."""
    sample_rate = 44100
    duration = 8
    volume = 0.1
    
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for t_sec in range(duration):
            for i in range(sample_rate):
                # 0.05 seconds beep at the start of each second
                if i < sample_rate * 0.05:
                    value = math.sin(2 * math.pi * 440.0 * (i / sample_rate)) * volume * 32767.0
                else:
                    value = 0.0
                
                packed_value = struct.pack('<h', int(value))
                wav_file.writeframes(packed_value)

def create_fallback_hum(filepath: str):
    """Generate 30s subtle low hum (110Hz sine wave, 5% volume)."""
    sample_rate = 44100
    duration = 30
    volume = 0.05
    
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for i in range(sample_rate * duration):
            value = math.sin(2 * math.pi * 110.0 * (i / sample_rate)) * volume * 32767.0
            packed_value = struct.pack('<h', int(value))
            wav_file.writeframes(packed_value)

def create_correct_chime(filepath: str):
    """Generate short ascending 3-note chime C5 -> E5 -> G5."""
    sample_rate = 44100
    notes = [
        (523.25, 0.15), # C5
        (659.25, 0.15), # E5
        (783.99, 0.3)   # G5
    ]
    volume = 0.5
    
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for freq, duration in notes:
            for i in range(int(sample_rate * duration)):
                fade = 1.0 - (i / (sample_rate * duration))
                value = math.sin(2 * math.pi * freq * (i / sample_rate)) * volume * fade * 32767.0
                packed_value = struct.pack('<h', int(value))
                wav_file.writeframes(packed_value)
def create_fallback_sound(filepath: str, duration: float, freq: float, volume: float):
    sample_rate = 44100
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for i in range(int(sample_rate * duration)):
            fade = 1.0 - (i / (sample_rate * duration))
            value = math.sin(2 * math.pi * freq * (i / sample_rate)) * volume * fade * 32767.0
            packed_value = struct.pack('<h', int(value))
            wav_file.writeframes(packed_value)

async def download_sounds():
    import httpx
    sounds_dir = os.path.join("assets", "sounds")
    os.makedirs(sounds_dir, exist_ok=True)
    
    move_path = os.path.join(sounds_dir, "move.mp3")
    if not os.path.exists(move_path) and not os.path.exists(os.path.join(sounds_dir, "move.wav")):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get("https://raw.githubusercontent.com/lichess-org/lila/master/public/sound/standard/Move.mp3")
                r.raise_for_status()
                with open(move_path, "wb") as f:
                    f.write(r.content)
        except Exception as e:
            logger.warning(f"Failed to download move.mp3: {e}. Using fallback.")
            create_fallback_sound(os.path.join(sounds_dir, "move.wav"), 0.08, 800.0, 0.5)
            
    capture_path = os.path.join(sounds_dir, "capture.mp3")
    if not os.path.exists(capture_path) and not os.path.exists(os.path.join(sounds_dir, "capture.wav")):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get("https://raw.githubusercontent.com/lichess-org/lila/master/public/sound/standard/Capture.mp3")
                r.raise_for_status()
                with open(capture_path, "wb") as f:
                    f.write(r.content)
        except Exception as e:
            logger.warning(f"Failed to download capture.mp3: {e}. Using fallback.")
            create_fallback_sound(os.path.join(sounds_dir, "capture.wav"), 0.12, 600.0, 0.7)

_last_used_track = {"flash": None, "story": None}

def scan_music_library() -> dict:
    """
    Scans assets/music/ folders and returns available tracks.
    No downloading - user provides files manually.
    """
    import glob
    
    flash_tracks = glob.glob("assets/music/flash/*.mp3") + \
                   glob.glob("assets/music/flash/*.wav") + \
                   glob.glob("assets/music/flash/*.m4a")
    
    story_tracks = glob.glob("assets/music/story/*.mp3") + \
                   glob.glob("assets/music/story/*.wav") + \
                   glob.glob("assets/music/story/*.m4a")
    
    logger.info(f"Music library: {len(flash_tracks)} flash tracks, "
                f"{len(story_tracks)} story tracks")
    
    if not flash_tracks:
        logger.warning("No flash music found in assets/music/flash/")
        logger.warning("Add .mp3 files from YouTube Audio Library")
    
    if not story_tracks:
        logger.warning("No story music found in assets/music/story/")
        logger.warning("Add .mp3 files from YouTube Audio Library")
    
    return {
        "flash": flash_tracks,
        "story": story_tracks
    }

def get_random_track(format_type: str) -> str | None:
    """
    Returns random track path for given format.
    format_type: "flash" or "story"
    Never picks same track twice in a row.
    """
    import random
    
    tracks = scan_music_library()[format_type]
    
    if not tracks:
        logger.warning(f"No {format_type} music. Using silence.")
        return None
    
    last_track = _last_used_track.get(format_type)
    available = [t for t in tracks if t != last_track]
    if not available:
        available = tracks  # only 1 track, allow repeat
    
    chosen = random.choice(available)
    _last_used_track[format_type] = chosen
    logger.info(f"Selected music: {os.path.basename(chosen)}")
    return chosen

async def setup_music():
    """No-op for backwards compatibility with main.py, but runs correct_chime check."""
    correct_chime = os.path.join("assets", "sounds", "correct.wav")
    if not os.path.exists(correct_chime):
        os.makedirs(os.path.dirname(correct_chime), exist_ok=True)
        create_correct_chime(correct_chime)
        logger.info("Generated Series correct chime (C5-E5-G5)")
    scan_music_library()
