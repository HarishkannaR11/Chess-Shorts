import subprocess
import json
import logging

logger = logging.getLogger(__name__)

def verify_audio(file_path: str) -> dict:
    """Verify that the given video/audio file contains an audio stream."""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", file_path
        ], capture_output=True, text=True)
        
        data = json.loads(result.stdout)
        audio_streams = [s for s in data.get("streams", []) 
                         if s.get("codec_type") == "audio"]
        
        if not audio_streams:
            logger.error(f"NO AUDIO in {file_path}")
            return {"has_audio": False}
        
        stream = audio_streams[0]
        logger.info(f"Audio OK: {file_path} | "
                    f"duration={stream.get('duration')}s | "
                    f"channels={stream.get('channels')}")
        return {
            "has_audio": True,
            "duration": float(stream.get("duration", 0) or 0),
            "channels": stream.get("channels"),
            "codec": stream.get("codec_name")
        }
    except Exception as e:
        logger.error(f"Failed to verify audio for {file_path}: {e}")
        return {"has_audio": False, "error": str(e)}
