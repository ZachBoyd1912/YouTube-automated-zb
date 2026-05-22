"""
Send Whisper transcript to DeepSeek (via OpenRouter) to identify cut ranges.
Returns a validated list of [start, end] second ranges to remove from the video.
"""
import logging
from typing import Any

from shared.llm_client import forced_tool_call

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a video editor's assistant. You receive a transcript with word-level timestamps \
and must identify time ranges to cut to produce a clean, tight edit.

Cut the following:
1. Filler words/phrases: "um", "uh", "like", "you know", "basically", "sort of", "kind of", \
"right?", isolated "so" used as filler, "actually" used as filler
2. Silences longer than 1.5 seconds between words
3. False starts (speaker begins a sentence, stops, restarts)
4. Obvious tangents or off-topic digressions (>10 seconds that don't advance the topic)

Rules:
- Cuts must not overlap
- Start must be less than end
- Include at least 0.05 seconds of buffer around filler words
- Do not cut actual content or explanations
- Return an empty cuts array [] if the recording is already clean
"""

CUT_TOOL = {
    "name": "identify_cuts",
    "description": "Return the list of time ranges to cut from the video",
    "input_schema": {
        "type": "object",
        "properties": {
            "cuts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["start", "end"],
                },
            }
        },
        "required": ["cuts"],
    },
}


def _format_transcript(transcript: dict[str, Any]) -> str:
    words = transcript.get("words", [])
    if not words:
        segments = transcript.get("segments", [])
        return "\n".join(
            f"[{s['start']:.2f}-{s['end']:.2f}] {s['text'].strip()}"
            for s in segments
        )
    lines: list[str] = []
    batch: list[str] = []
    line_start: float | None = None
    for w in words:
        if line_start is None:
            line_start = w["start"]
        batch.append(f"{w['word']}({w['start']:.2f})")
        if len(batch) >= 15:
            lines.append(f"[{line_start:.2f}] " + " ".join(batch))
            batch = []
            line_start = None
    if batch and line_start is not None:
        lines.append(f"[{line_start:.2f}] " + " ".join(batch))
    return "\n".join(lines)


def _validate_cuts(cuts: list[dict], video_duration: float) -> list[dict]:
    valid = [c for c in cuts if c.get("start", 0) < c.get("end", 0)]
    valid = [c for c in valid if c["end"] <= video_duration + 1.0]
    valid.sort(key=lambda c: c["start"])
    merged: list[dict] = []
    for cut in valid:
        if merged and cut["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], cut["end"])
        else:
            merged.append({"start": cut["start"], "end": cut["end"]})
    return merged


def analyze_cuts(transcript: dict[str, Any], video_duration: float) -> list[dict]:
    """Return validated cut ranges from the transcript."""
    user_prompt = (
        f"Video duration: {video_duration:.1f} seconds\n\n"
        f"Transcript:\n{_format_transcript(transcript)}"
    )
    result = forced_tool_call(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        tool=CUT_TOOL,
        max_tokens=2048,
    )
    cuts = _validate_cuts(result.get("cuts", []), video_duration)
    total_cut = sum(c["end"] - c["start"] for c in cuts)
    logger.info("Identified %d cut ranges (%.1f seconds total)", len(cuts), total_cut)
    return cuts
