import os
import logging
import edge_tts
import asyncio
import subprocess
import shutil

logger = logging.getLogger(__name__)

# ── silence-trimming helpers ──────────────────────────────────────────────────

def _trim_silence(mp3_in: str, mp3_out: str,
                  lead_ms: int = 100, trail_ms: int = 100) -> None:
    """
    Use FFmpeg's silenceremove filter to strip leading/trailing silence from a
    clip, then pad back to exactly `lead_ms` / `trail_ms` of silence on each
    end so adjacent crossfades have a tiny natural breath room.
    """
    # Step 1: strip silence
    stripped = mp3_out + ".strip.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", mp3_in,
        "-af",
        # remove leading silence below -40dB; remove trailing silence below -40dB
        "silenceremove=start_periods=1:start_silence=0.04:start_threshold=-40dB"
        ":stop_periods=-1:stop_silence=0.04:stop_threshold=-40dB",
        "-ar", "44100", "-ac", "1",
        stripped
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not os.path.exists(stripped):
        # fallback: just copy
        shutil.copy(mp3_in, mp3_out)
        return

    # Step 2: re-pad to lead_ms / trail_ms using adelay + apad
    pad_lead  = lead_ms
    pad_trail = trail_ms
    cmd2 = [
        "ffmpeg", "-y", "-i", stripped,
        "-af", f"adelay={pad_lead}|{pad_lead},apad=pad_dur={pad_trail/1000:.3f}",
        "-ar", "44100", "-ac", "1",
        mp3_out
    ]
    r2 = subprocess.run(cmd2, capture_output=True)
    if r2.returncode != 0:
        shutil.copy(mp3_in, mp3_out)
    if os.path.exists(stripped):
        os.remove(stripped)


def _crossfade_concat(clips: list[str], out_path: str,
                      xfade_ms: int = 75) -> None:
    """
    Concatenate a list of mono mp3 clips with an `acrossfade` between every
    adjacent pair, then write to out_path.
    Works for any number of clips >= 1.
    """
    if len(clips) == 1:
        shutil.copy(clips[0], out_path)
        return

    # Build a filter_complex that chains acrossfade
    # Each input is [N:a]; we progressively crossfade pairs.
    n = len(clips)
    xfade_s = xfade_ms / 1000.0
    inputs = []
    for c in clips:
        inputs += ["-i", c]

    # label strategy: [a0], then acrossfade([a0],[1:a]) -> [a1], etc.
    fc_parts = []
    prev_label = "[0:a]"
    for i in range(1, n):
        next_label = f"[cf{i}]" if i < n - 1 else "[aout]"
        fc_parts.append(
            f"{prev_label}[{i}:a]acrossfade=d={xfade_s:.3f}:c1=tri:c2=tri{next_label}"
        )
        prev_label = next_label

    filter_complex = ";".join(fc_parts)
    cmd = (
        ["ffmpeg", "-y"] + inputs
        + ["-filter_complex", filter_complex,
           "-map", "[aout]",
           "-ar", "44100", "-ac", "1",
           out_path]
    )
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        logger.warning(f"crossfade concat failed: {r.stderr.decode()[:300]}, falling back to simple concat")
        # fallback: simple concat via concat demuxer
        list_file = out_path + ".list"
        with open(list_file, "w") as f:
            for c in clips:
                f.write(f"file '{os.path.abspath(c)}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", out_path],
            capture_output=True
        )
        os.remove(list_file)


# ── sentence splitting ────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """
    Split a script into natural TTS sentences.  Splits on  .  ?  !  followed
    by whitespace, while keeping the punctuation with the preceding sentence.
    Short fragments (<= 3 words) are merged into the next sentence to avoid
    micro-clips that cause audible stutter.
    """
    import re
    # split on sentence-ending punctuation
    raw = re.split(r'(?<=[.?!])\s+', text.strip())

    merged: list[str] = []
    carry = ""
    for sent in raw:
        sent = sent.strip()
        if not sent:
            continue
        candidate = (carry + " " + sent).strip() if carry else sent
        if len(candidate.split()) <= 3 and raw.index(sent) < len(raw) - 1:
            # too short — carry forward
            carry = candidate
        else:
            merged.append(candidate)
            carry = ""
    if carry:
        if merged:
            merged[-1] = merged[-1] + " " + carry
        else:
            merged.append(carry)
    return merged


# ── public API ────────────────────────────────────────────────────────────────

async def generate_voice(text: str,
                         trim_lead_ms: int = 80,
                         trim_trail_ms: int = 80,
                         xfade_ms: int = 75) -> tuple:
    """
    Generate voice using edge-tts and return (mp3_path, word_boundaries).

    Improvements vs old version:
      - Splits the script into sentences and synthesises each separately.
      - Trims leading/trailing silence (<80 ms kept) from every clip.
      - Crossfades adjacent clips by ~75 ms so there are no hard seams.
      - Word-boundary timestamps are globally re-aligned to match the
        trimmed+crossfaded timeline so captions stay in sync.
      - Final file is always trimmed to the last spoken word + 200 ms of
        trailing room (no dead air at the end).
    """
    logger.info("Generating voice using edge-tts (per-sentence, silence-trimmed)")
    os.makedirs("outputs", exist_ok=True)
    tmp_dir = os.path.join("outputs", "_voice_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    sentences = _split_sentences(text)
    logger.info(f"Script split into {len(sentences)} sentences")

    per_sentence_boundaries: list[list[dict]] = []
    raw_clips: list[str] = []

    # ── 1. Synthesise each sentence ──────────────────────────────────────────
    for idx, sent in enumerate(sentences):
        raw_mp3 = os.path.join(tmp_dir, f"raw_{idx:02d}.mp3")

        communicate = edge_tts.Communicate(
            text=sent,
            voice="en-US-GuyNeural",
            rate="+8%",
            volume="+10%",
            pitch="-8Hz",
        )

        wbs: list[dict] = []
        with open(raw_mp3, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    wbs.append({
                        "word":  chunk["text"],
                        "start": chunk["offset"] / 10_000_000.0,
                        "end":   (chunk["offset"] + chunk["duration"]) / 10_000_000.0,
                    })

        per_sentence_boundaries.append(wbs)
        raw_clips.append(raw_mp3)

    # ── 2. Trim silence from each clip ───────────────────────────────────────
    trimmed_clips: list[str] = []
    clip_durations: list[float] = []   # actual duration after trimming

    for idx, raw in enumerate(raw_clips):
        trimmed = os.path.join(tmp_dir, f"trim_{idx:02d}.mp3")
        _trim_silence(raw, trimmed, lead_ms=trim_lead_ms, trail_ms=trim_trail_ms)
        # measure trimmed duration
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", trimmed],
            capture_output=True, text=True
        )
        dur = float(probe.stdout.strip() or 0)
        clip_durations.append(dur)
        trimmed_clips.append(trimmed)

    # ── 3. Re-align word boundaries to global timeline ───────────────────────
    #
    # After trimming: each clip i starts at global_offset[i].
    # The crossfade of xfade_s seconds means clip i+1 starts at:
    #   global_offset[i] + dur[i] - xfade_s
    # (the last xfade_s seconds of clip i overlap with the first xfade_s of i+1)
    xfade_s = xfade_ms / 1000.0
    global_offset = 0.0
    all_word_boundaries: list[dict] = []

    for idx, wbs in enumerate(per_sentence_boundaries):
        # The per-sentence boundaries start at t=0 relative to the raw clip.
        # We kept trim_lead_ms of silence at the front, so the first word
        # now starts at trim_lead_ms within the trimmed clip.
        lead_s = trim_lead_ms / 1000.0
        for wb in wbs:
            all_word_boundaries.append({
                "word":  wb["word"],
                "start": wb["start"] + global_offset + lead_s,
                "end":   wb["end"]   + global_offset + lead_s,
            })
        global_offset += clip_durations[idx]
        if idx < len(clip_durations) - 1:
            global_offset -= xfade_s   # crossfade overlap

    # ── 4. Crossfade-concat all clips into one file ──────────────────────────
    merged_mp3 = os.path.join("outputs", "voice_merged.mp3")
    _crossfade_concat(trimmed_clips, merged_mp3, xfade_ms=xfade_ms)

    # ── 5. Trim tail to last spoken word + 200 ms ────────────────────────────
    tail_room_s = 0.2
    if all_word_boundaries:
        last_word_end = all_word_boundaries[-1]["end"]
        final_duration = last_word_end + tail_room_s
    else:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", merged_mp3],
            capture_output=True, text=True
        )
        final_duration = float(probe.stdout.strip() or 30)

    mp3_path = os.path.join("outputs", "voice.mp3")
    tail_cmd = [
        "ffmpeg", "-y", "-i", merged_mp3,
        "-t", f"{final_duration:.3f}",
        "-ar", "44100", "-ac", "1",
        mp3_path
    ]
    r = subprocess.run(tail_cmd, capture_output=True)
    if r.returncode != 0:
        shutil.copy(merged_mp3, mp3_path)

    # ── 6. Verify ────────────────────────────────────────────────────────────
    probe = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp3_path],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip() or 0)
    logger.info(
        f"Voice generated: {duration:.2f}s | {len(sentences)} clips "
        f"| {len(all_word_boundaries)} word boundaries"
    )
    if duration < 2.0:
        logger.warning("Voice duration suspiciously short (<2s)")

    # ── 7. Cleanup tmp ───────────────────────────────────────────────────────
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

    return mp3_path, all_word_boundaries
