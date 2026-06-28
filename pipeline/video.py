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
    
    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    script_data = data.get("script", {})
    puzzle_data = data.get("puzzle", {})
    
    if os.name == 'nt':
        font_path = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts\\arialbd.ttf'
        font_path_ffmpeg = font_path.replace('\\', '/').replace(':', '\\:')
    else:
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        font_path_ffmpeg = font_path.replace('\\', '/').replace(':', '\\:')

    # Get voice duration
    voice_info = verify_audio(voice_path)
    if not voice_info.get("has_audio"):
        raise ValueError(f"Audio lost at voice generation - check {voice_path}")
    total_voice_duration = voice_info["duration"]

    # Calculate dynamic caption times
    sections = {
        "hook": script_data.get("hook", ""),
        "setup": script_data.get("setup", ""),
        "tension": script_data.get("tension", ""),
        "reveal": script_data.get("reveal", ""),
        "lesson": script_data.get("lesson", ""),
        "cta": script_data.get("cta", "")
    }
    
    total_words = sum(len(s.split()) for s in sections.values() if s)
    current_time = 0.0
    section_times = {}
    
    for name, text in sections.items():
        if not text:
            continue
        word_count = len(text.split())
        duration = (word_count / total_words) * total_voice_duration if total_words > 0 else 0
        section_times[name] = {
            "start": current_time,
            "end": current_time + duration,
            "text": text
        }
        current_time += duration

    # 1. Frames -> silent video
    silent_video = os.path.join("outputs", "video_silent.mp4")
    frames_pattern = os.path.join(frames_dir, "frame_%04d.png")
    
    cmd1 = [
        "ffmpeg", "-y",
        "-framerate", "30",
        "-i", frames_pattern,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-t", "30",
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
                # We start adding inputs from index 1
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
    # Check if sfx video has audio
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

    # Step 4: Add Captions to video_with_voice -> video_captioned.mp4
    video_captioned = os.path.join("outputs", "video_captioned.mp4")
    filters = []
    
    # Base text
    player = puzzle_data.get("player", "Player").replace("'", "’").replace(":", "\\:")
    opponent = puzzle_data.get("opponent", "Opponent").replace("'", "’").replace(":", "\\:")
    event_str = f"{puzzle_data.get('event', 'Event')} {puzzle_data.get('year', '2023')}".replace("'", "’").replace(":", "\\:")
    
    filters.append(
        f"scale=1080:1080,pad=1080:1920:0:280:black,"
        f"drawtext=text='{player}':fontsize=52:fontcolor=#FFD700:x=(w-text_w)/2:y=80:fontfile='{font_path_ffmpeg}',"
        f"drawtext=text='vs':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=140:fontfile='{font_path_ffmpeg}',"
        f"drawtext=text='{opponent}':fontsize=52:fontcolor=white:x=(w-text_w)/2:y=180:fontfile='{font_path_ffmpeg}',"
        f"drawtext=text='{event_str}':fontsize=34:fontcolor=gray:x=(w-text_w)/2:y=240:fontfile='{font_path_ffmpeg}'"
    )
    
    for name, data in section_times.items():
        text = "\\n".join(textwrap.wrap(data["text"], width=30)[:2])
        text = text.replace("'", "’").replace(":", "\\:")
        
        filters.append(
            f"drawtext=text='{text}':"
            f"fontfile='{font_path_ffmpeg}':"
            f"fontsize=52:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:"
            f"y=1450:"
            f"borderw=4:"
            f"bordercolor=black:"
            f"enable='between(t,{data['start']:.2f},{data['end']:.2f})'"
        )
    
    caption_filter = ",".join(filters)
    
    cmd4 = [
        "ffmpeg", "-y",
        "-i", video_with_voice,
        "-vf", caption_filter,
        "-c:v", "libx264", "-b:v", "2500k",
        "-c:a", "copy",
        video_captioned
    ]
    run_cmd(cmd4)

    # Step 5: Add background music
    from pipeline.assets_setup import get_random_track
    import shutil
    
    track = get_random_track("story")
    if not track:
        shutil.copy(video_captioned, output_path)
    else:
        normalized = normalize_music_file(track)
        if not normalized:
            shutil.copy(video_captioned, output_path)
        else:
            cmd5 = [
                "ffmpeg", "-y",
                "-i", video_captioned,
                "-stream_loop", "-1", "-i", normalized,
                "-filter_complex", (
                    "[0:a]volume=1.0[voicesfx];"
                    "[1:a]volume=0.12,afade=t=in:st=0:d=2,afade=t=out:st=27:d=3[music];"
                    "[voicesfx][music]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
                ),
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                "-t", "30",
                output_path
            ]
            run_cmd(cmd5)
            
            if not verify_audio(output_path).get("has_audio"):
                raise ValueError("Audio lost at step 5 (Music) - check FFmpeg command")

    logger.info(f"Video saved to {output_path}")
    return output_path
