"""
Extract the best 45–60s Shorts clip: identify window via DeepSeek, crop to 9:16, add captions.
"""
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from shared import config, drive_client
from shared.llm_client import forced_tool_call

logger = logging.getLogger(__name__)

SHORTS_TOOL = {
    "name": "identify_shorts_window",
    "description": "Identify the best 45–60 second clip for a YouTube Short",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_seconds": {"type": "number"},
            "end_seconds": {"type": "number"},
            "reasoning": {"type": "string"},
        },
        "required": ["start_seconds", "end_seconds"],
    },
}

SYSTEM_PROMPT = """\
You are selecting a 45–60 second clip from a tutorial transcript for a YouTube Short.
Choose the window with:
1. A strong hook in the first 3 seconds (question, bold claim, or surprising statement)
2. A complete, self-contained tip that delivers clear value on its own
3. High energy — speaker sounds confident and engaged
4. Minimal filler or context that requires the full video to understand
The clip MUST be 45–60 seconds (end_seconds - start_seconds between 45 and 60).
"""


def _identify_window(transcript: dict[str, Any]) -> tuple[float, float]:
    segments = transcript.get("segments", [])
    transcript_text = "\n".join(
        f"[{s['start']:.1f}s] {s.get('text', '').strip()}"
        for s in segments
    )
    result = forced_tool_call(
        system=SYSTEM_PROMPT,
        user=f"Transcript:\n{transcript_text}",
        tool=SHORTS_TOOL,
        max_tokens=512,
    )
    start = float(result["start_seconds"])
    end = float(result["end_seconds"])
    duration = end - start
    if duration < config.SHORTS_MIN_DURATION_SECONDS:
        end = start + config.SHORTS_MIN_DURATION_SECONDS
    elif duration > config.SHORTS_MAX_DURATION_SECONDS:
        end = start + config.SHORTS_MAX_DURATION_SECONDS
    logger.info("Shorts window: %.1f–%.1f (%.0fs)", start, end, end - start)
    return start, end


def _extract_and_crop(video_path: Path, start: float, end: float, output_path: Path) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(end - start),
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


def _shift_srt(src: Path, dst: Path, shift: float) -> None:
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
    dst.write_text(pattern.sub(lambda m: s_to_time(time_to_s(m.group(1)) + shift), text), encoding="utf-8")


def _add_captions(clip_path: Path, srt_path: Path, start_offset: float, output_path: Path) -> Path:
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


def create_short(
    edited_video_path: Path,
    transcript: dict[str, Any],
    srt_path: Path | None,
    date_str: str,
) -> tuple[str, str]:
    """Create a vertical Shorts clip. Returns (drive_file_id, drive_link)."""
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
    file_id, link = drive_client.upload_file(final_path, folder_id, f"short_{date_str}.mp4")
    final_path.unlink(missing_ok=True)
    logger.info("Shorts clip uploaded → %s", link)
    return file_id, link
