"""
Extract the best 45–60s Shorts clip: identify window via Claude, crop to 9:16, add captions.
"""
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import anthropic

from shared import config, drive_client
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

SHORTS_TOOL = {
    "name": "identify_shorts_window",
    "description": "Identify the best 45–60 second clip from the transcript for a YouTube Short",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_seconds": {"type": "number", "description": "Start time of the clip in seconds"},
            "end_seconds": {"type": "number", "description": "End time of the clip in seconds"},
            "reasoning": {"type": "string", "description": "Why this is the best segment"},
        },
        "required": ["start_seconds", "end_seconds"],
    },
}

SYSTEM_PROMPT = """\
You are selecting a 45–60 second clip from a YouTube tutorial transcript to repurpose as a \
YouTube Short. Choose the window with:
1. A strong hook in the first 3 seconds (question, bold claim, or surprising statement)
2. A complete, self-contained tip or demonstration that delivers clear value
3. High energy and momentum — the speaker sounds confident and engaged
4. Minimal filler, pauses, or context that requires the full video to understand
The clip must be 45–60 seconds long (end_seconds - start_seconds = 45–60).
"""


@with_retry(max_attempts=3)
def _identify_window(transcript: dict[str, Any]) -> tuple[float, float]:
    """Ask Claude to identify the best Shorts window. Returns (start, end) in seconds."""
    segments = transcript.get("segments", [])
    transcript_text = "\n".join(
        f"[{s['start']:.1f}s] {s.get('text', '').strip()}"
        for s in segments
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        tools=[SHORTS_TOOL],
        tool_choice={"type": "tool", "name": "identify_shorts_window"},
        messages=[{"role": "user", "content": f"Transcript:\n{transcript_text}"}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "identify_shorts_window":
            start = float(block.input["start_seconds"])
            end = float(block.input["end_seconds"])
            duration = end - start
            if not (config.SHORTS_MIN_DURATION_SECONDS <= duration <= config.SHORTS_MAX_DURATION_SECONDS):
                # Clamp to valid range
                if duration < config.SHORTS_MIN_DURATION_SECONDS:
                    end = start + config.SHORTS_MIN_DURATION_SECONDS
                else:
                    end = start + config.SHORTS_MAX_DURATION_SECONDS
            logger.info("Shorts window: %.1f–%.1f (%.0fs)", start, end, end - start)
            return start, end

    raise ValueError("Claude did not return identify_shorts_window tool call")


def _extract_and_crop(video_path: Path, start: float, end: float, output_path: Path) -> Path:
    """Extract clip, crop to 9:16 (1080×1920), rescale."""
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", "crop=ih*9/16:ih,scale=1080:1920",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg Shorts crop failed:\n{result.stderr}")
    return output_path


def _add_captions(clip_path: Path, srt_path: Path, start_offset: float, output_path: Path) -> Path:
    """Burn in captions, offsetting SRT timestamps by -start_offset."""
    # Rewrite SRT with adjusted timestamps
    adjusted_srt = clip_path.parent / "shorts_captions.srt"
    _shift_srt(srt_path, adjusted_srt, -start_offset)

    srt_escaped = str(adjusted_srt).replace(":", "\\:").replace("'", "\\'")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-vf", (
            f"subtitles='{srt_escaped}':"
            "force_style='FontSize=28,PrimaryColour=&Hffffff,OutlineColour=&H000000,"
            "BackColour=&H80000000,Bold=1,Outline=2,Alignment=2'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg Shorts caption failed:\n{result.stderr}")
    adjusted_srt.unlink(missing_ok=True)
    return output_path


def _shift_srt(src: Path, dst: Path, shift: float) -> None:
    """Shift all SRT timestamps by `shift` seconds (negative removes offset)."""
    import re
    pattern = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})")

    def time_to_s(t: str) -> float:
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    def s_to_time(s: float) -> str:
        s = max(0.0, s)
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        ms = int((s % 1) * 1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    text = src.read_text(encoding="utf-8")

    def replace_time(m: re.Match) -> str:
        return s_to_time(time_to_s(m.group(1)) + shift)

    dst.write_text(pattern.sub(replace_time, text), encoding="utf-8")


def create_short(
    edited_video_path: Path,
    transcript: dict[str, Any],
    srt_path: Path | None,
    date_str: str,
) -> tuple[str, str]:
    """
    Create a vertical Shorts clip from the edited video.
    Returns (drive_file_id, drive_link).
    """
    start, end = _identify_window(transcript)
    tmp_dir = edited_video_path.parent

    cropped_path = tmp_dir / f"shorts_raw_{date_str}.mp4"
    _extract_and_crop(edited_video_path, start, end, cropped_path)

    if srt_path and srt_path.exists():
        final_path = tmp_dir / f"shorts_final_{date_str}.mp4"
        _add_captions(cropped_path, srt_path, start, final_path)
        cropped_path.unlink(missing_ok=True)
    else:
        final_path = cropped_path

    folder_id = drive_client.get_dated_folder_id(config.DRIVE_SHORTS_FOLDER, date_str)
    file_id, link = drive_client.upload_file(
        final_path, folder_id, f"short_{date_str}.mp4"
    )
    final_path.unlink(missing_ok=True)
    logger.info("Shorts clip uploaded → %s", link)
    return file_id, link
