import os
import json
import glob
import random
import logging
import subprocess
import textwrap
from dotenv import load_dotenv
from pipeline.audio_check import verify_audio

load_dotenv()
logger = logging.getLogger(__name__)

def run_cmd(cmd: list):
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg failed with error:\n{result.stderr}")
            raise RuntimeError(f"FFmpeg command failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Command execution error: {e}")
        raise

def get_video_duration(path: str) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ], capture_output=True, text=True)
    return float(result.stdout.strip())

def normalize_music_file(input_path: str) -> str:
    """
    Converts any audio format to standard mp3 for FFmpeg.
    Handles: .mp3, .wav, .m4a, .ogg, .flac
    Returns path to normalized mp3.
    """
    output_path = f"outputs/temp_music.mp3"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ar", "44100",      # standard sample rate
        "-ac", "2",          # stereo
        "-b:a", "192k",      # good quality
        "-vn",               # no video
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Music normalize failed: {result.stderr}")
        return None
    
    return output_path

def combine_video(script_path: str, voice_path: str, frames_dir: str, output_path: str, move_timestamps: list = None) -> str:
    """
    Combine board frames, voice audio, and move sounds into the final 30s video using FFmpeg.
    """
    logger.info("Starting video combination process...")
    os.makedirs("outputs", exist_ok=True)
    os.makedirs(frames_dir, exist_ok=True)
    
    # 1. Frames -> silent video
    silent_video = os.path.join("outputs", "video_silent.mp4")
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

    # 2. Silent video + piece sounds -> video_with_sfx.mp4
    video_with_sfx = os.path.join("outputs", "video_with_sfx.mp4")
    if move_timestamps:
        inputs = ["ffmpeg", "-y", "-i", silent_video]
        filter_parts = []
        mix_labels = []
        
        for i, move in enumerate(move_timestamps):
            delay_ms = int(move["time"] * 1000)
            sound_file = "capture.mp3" if move.get("is_capture") else "move.mp3"
            sound_path = os.path.join("assets", "sounds", sound_file)
            
            # Fallback if mp3 doesn't exist but wav does
            if not os.path.exists(sound_path):
                alt_path = sound_path.replace(".mp3", ".wav")
                if os.path.exists(alt_path):
                    sound_path = alt_path
            
            if os.path.exists(sound_path):
                inputs.extend(["-i", sound_path])
                filter_parts.append(
                    f"[{i+1}:a]adelay={delay_ms}|{delay_ms},"
                    f"volume=0.8[s{i}]"
                )
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
            
            # verify audio
            if not verify_audio(video_with_sfx).get("has_audio"):
                raise ValueError("Audio lost at step 2 (SFX) - check FFmpeg command")
        else:
            import shutil
            shutil.copy(silent_video, video_with_sfx)
    else:
        import shutil
        shutil.copy(silent_video, video_with_sfx)

    # 3. Mix voice over sfx -> video_with_voice.mp4
    video_with_voice = os.path.join("outputs", "video_with_voice.mp4")
    cmd3 = [
        "ffmpeg", "-y", 
        "-i", video_with_sfx,
        "-i", voice_path
    ]
    has_sfx = verify_audio(video_with_sfx).get("has_audio")
    
    if has_sfx:
        filter_complex3 = (
            "[0:a]volume=0.3[sfx];"
            "[1:a]volume=1.0[voice];"
            "[sfx][voice]amix=inputs=2:duration=longest[aout]"
        )
        cmd3.extend([
            "-filter_complex", filter_complex3,
            "-map", "0:v", "-map", "[aout]"
        ])
    else:
        # Just map voice
        cmd3.extend([
            "-map", "0:v", "-map", "1:a"
        ])
        
    cmd3.extend(["-c:v", "copy", "-c:a", "aac", video_with_voice])
    run_cmd(cmd3)
    
    if not verify_audio(video_with_voice).get("has_audio"):
        raise ValueError("Audio lost at step 3 (Voice) - check FFmpeg command")

    # Step 5: Add background music
    from pipeline.assets_setup import get_random_track
    import shutil
    
    track = get_random_track("story")
    if not track:
        shutil.copy(video_with_voice, output_path)
    else:
        normalized = normalize_music_file(track)
        if not normalized:
            shutil.copy(video_with_voice, output_path)
        else:
            duration = get_video_duration(video_with_voice)
            fade_out_start = max(0, duration - 3.0)
            cmd5 = [
                "ffmpeg", "-y",
                "-i", video_with_voice,
                "-stream_loop", "-1", "-i", normalized,
                "-filter_complex", (
                    f"[0:a]volume=1.0[voicesfx];"
                    f"[1:a]volume=0.12,afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start}:d=3[music];"
                    f"[voicesfx][music]amix=inputs=2:duration=longest:dropout_transition=2,"
                    f"loudnorm=I=-14:LRA=11:TP=-1.5[aout]"
                ),
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                "-t", str(duration),
                output_path
            ]
            run_cmd(cmd5)
            
            if not verify_audio(output_path).get("has_audio"):
                raise ValueError("Audio lost at step 5 (Music) - check FFmpeg command")

    logger.info(f"Video saved to {output_path}")
    return output_path
