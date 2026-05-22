"""
Apply cuts, audio filters, captions, and intro/outro using ffmpeg.
Outputs a render-ready .mp4.
"""
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from shared import config

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent.parent / "assets"
INTRO_PATH = ASSETS_DIR / "intro.mp4"
OUTRO_PATH = ASSETS_DIR / "outro.mp4"


def get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def generate_srt(transcript: dict[str, Any], output_path: Path, cuts: list[dict]) -> Path:
    """
    Generate an SRT caption file from the Whisper transcript,
    adjusting timestamps to account for removed cut segments.
    """
    segments = transcript.get("segments", [])
    if not segments:
        words = transcript.get("words", [])
        # Group words into ~5-second segments
        segments = _words_to_segments(words)

    lines: list[str] = []
    index = 1

    def adjusted_time(t: float) -> float:
        offset = 0.0
        for cut in cuts:
            if cut["start"] <= t:
                trimmed = min(t, cut["end"]) - cut["start"]
                offset += max(0.0, trimmed)
        return t - offset

    for seg in segments:
        start = adjusted_time(seg["start"])
        end = adjusted_time(seg["end"])
        text = seg.get("text", "").strip()
        if not text or start >= end:
            continue
        lines.append(str(index))
        lines.append(f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}")
        lines.append(text)
        lines.append("")
        index += 1

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Generated SRT with %d captions → %s", index - 1, output_path)
    return output_path


def _words_to_segments(words: list[dict]) -> list[dict]:
    segments: list[dict] = []
    batch: list[str] = []
    start = 0.0
    for w in words:
        if not batch:
            start = w["start"]
        batch.append(w["word"])
        if len(batch) >= 8 or (batch and w["end"] - start >= 4.0):
            segments.append({"start": start, "end": w["end"], "text": " ".join(batch)})
            batch = []
    if batch:
        last_end = words[-1]["end"] if words else start + 1.0
        segments.append({"start": start, "end": last_end, "text": " ".join(batch)})
    return segments


def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def apply_cuts_and_filters(
    input_path: Path,
    output_path: Path,
    cuts: list[dict],
    srt_path: Path | None = None,
) -> Path:
    """
    Apply the cut ranges, audio filters, and optional captions in one ffmpeg pass.
    Uses the complex filtergraph select/aselect approach.
    """
    duration = get_video_duration(input_path)

    # Build keep segments from cut ranges
    keep_segments = _invert_cuts(cuts, duration)
    logger.info("Keeping %d segments (total ~%.0fs after cuts)",
                len(keep_segments), sum(e - s for s, e in keep_segments))

    if len(keep_segments) == 1:
        # Simple single-segment case: just one trim
        s, e = keep_segments[0]
        filter_complex = (
            f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v];"
            f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS,"
            f"loudnorm,anlmdn=s=0.002[a]"
        )
        map_args = ["-map", "[v]", "-map", "[a]"]
    else:
        # Multi-segment concat
        v_parts = "".join(
            f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}];"
            for i, (s, e) in enumerate(keep_segments)
        )
        a_parts = "".join(
            f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}];"
            for i, (s, e) in enumerate(keep_segments)
        )
        n = len(keep_segments)
        v_inputs = "".join(f"[v{i}]" for i in range(n))
        a_inputs = "".join(f"[a{i}]" for i in range(n))
        filter_complex = (
            v_parts + a_parts +
            f"{v_inputs}concat=n={n}:v=1:a=0[vcat];"
            f"{a_inputs}concat=n={n}:v=0:a=1[acat];"
            f"[acat]loudnorm,anlmdn=s=0.002[a];"
            f"[vcat]copy[v]"
        )
        map_args = ["-map", "[v]", "-map", "[a]"]

    # Add subtitles if SRT provided
    if srt_path and srt_path.exists():
        srt_escaped = str(srt_path).replace(":", "\\:").replace("'", "\\'")
        filter_complex += f";[v]subtitles='{srt_escaped}':force_style='FontSize=22,PrimaryColour=&Hffffff,OutlineColour=&H000000,BackColour=&H80000000,Bold=1,Outline=2'[vf]"
        map_args = ["-map", "[vf]", "-map", "[a]"]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        *map_args,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    _run_ffmpeg(cmd)
    logger.info("Edited video → %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
    return output_path


def prepend_intro_append_outro(
    content_path: Path,
    output_path: Path,
) -> Path:
    """Concatenate intro + content + outro using ffmpeg concat demuxer."""
    if not INTRO_PATH.exists() or not OUTRO_PATH.exists():
        logger.warning("Intro/outro assets not found at %s — skipping", ASSETS_DIR)
        content_path.rename(output_path)
        return output_path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as flist:
        flist.write(f"file '{INTRO_PATH}'\n")
        flist.write(f"file '{content_path}'\n")
        flist.write(f"file '{OUTRO_PATH}'\n")
        flist_path = Path(flist.name)

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(flist_path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(cmd)
    flist_path.unlink(missing_ok=True)
    logger.info("Final video with intro/outro → %s", output_path)
    return output_path


def _invert_cuts(cuts: list[dict], duration: float) -> list[tuple[float, float]]:
    """Convert cut ranges into keep ranges."""
    if not cuts:
        return [(0.0, duration)]
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for cut in sorted(cuts, key=lambda c: c["start"]):
        if cursor < cut["start"]:
            keep.append((cursor, cut["start"]))
        cursor = cut["end"]
    if cursor < duration:
        keep.append((cursor, duration))
    return keep


def _run_ffmpeg(cmd: list[str]) -> None:
    logger.debug("ffmpeg: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-2000:]}")
