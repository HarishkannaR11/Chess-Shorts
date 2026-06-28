import os
import logging
import edge_tts
import asyncio
import subprocess

logger = logging.getLogger(__name__)

async def generate_voice(text: str) -> str:
    """
    Generate voice using edge-tts native library.
    """
    logger.info("Generating voice using edge-tts (en-US-GuyNeural)")
    os.makedirs("outputs", exist_ok=True)
    mp3_path = os.path.join("outputs", "voice.mp3")
    
    communicate = edge_tts.Communicate(
        text=text,
        voice="en-US-GuyNeural",
        rate="+8%",    # slightly fast = energetic
        volume="+10%", # louder
        pitch="-8Hz"   # deeper = authoritative
    )
    
    await communicate.save(mp3_path)
    
    # Verify output exists and duration > 2 seconds
    if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
        logger.error("edge-tts output mp3 is missing or 0 bytes")
        raise ValueError("Invalid voice audio file generated.")
        
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", mp3_path], capture_output=True, text=True)
    if probe.returncode != 0:
        logger.error(f"ffprobe failed on voice.mp3: {probe.stderr}")
        raise ValueError("Generated voice is invalid audio.")
        
    duration = float(probe.stdout.strip() or 0)
    logger.info(f"Voice generated: {duration} seconds")
    
    if duration < 2.0:
        logger.warning("Voice duration is suspiciously short (< 2 seconds)")
        
    return mp3_path
