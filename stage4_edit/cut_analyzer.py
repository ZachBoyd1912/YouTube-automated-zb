"""
Send Whisper transcript to Claude to identify filler words, silences, and tangents.
Returns a validated list of [start, end] second ranges to CUT from the video.
"""
import json
import logging
from typing import Any

import anthropic

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a video editor's assistant. You receive a transcript with word-level timestamps \
and must identify ranges to cut to produce a clean, tight edit.

Cut the following:
1. Filler words/phrases: "um", "uh", "like", "you know", "basically", "sort of", "kind of", \
"right?", isolated "so" used as filler, "actually" used as filler
2. Silences longer than 1.5 seconds between words
3. False starts (speaker begins a sentence, stops, restarts)
4. Obvious tangents or off-topic digressions (>10 seconds that don't advance the topic)

Return ONLY a JSON array of objects with "start" and "end" keys (float seconds).
Example: [{"start": 2.1, "end": 2.8}, {"start": 15.3, "end": 17.0}]

Rules:
- Cuts must not overlap
- Start must be less than end
- Include at least 0.05 seconds of buffer around filler words
- Do not cut content that is part of the actual explanation or walkthrough
- Return an empty array [] if the recording is already clean
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


def _format_transcript_for_claude(transcript: dict[str, Any]) -> str:
    """Format word-level transcript into a compact, readable string."""
    words = transcript.get("words", [])
    if not words:
        # Fall back to segment-level if word-level unavailable
        segments = transcript.get("segments", [])
        return "\n".join(
            f"[{s['start']:.2f}-{s['end']:.2f}] {s['text'].strip()}"
            for s in segments
        )
    lines = []
    current_line: list[str] = []
    line_start: float | None = None
    for w in words:
        if line_start is None:
            line_start = w["start"]
        current_line.append(f"{w['word']}({w['start']:.2f})")
        if len(current_line) >= 15:
            lines.append(f"[{line_start:.2f}] " + " ".join(current_line))
            current_line = []
            line_start = None
    if current_line and line_start is not None:
        lines.append(f"[{line_start:.2f}] " + " ".join(current_line))
    return "\n".join(lines)


def _validate_cuts(cuts: list[dict], video_duration: float) -> list[dict]:
    """Sort cuts, remove invalid entries, merge overlapping ranges."""
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


@with_retry(max_attempts=3)
def analyze_cuts(transcript: dict[str, Any], video_duration: float) -> list[dict]:
    """Return validated cut ranges [{start, end}] from the Whisper transcript."""
    formatted = _format_transcript_for_claude(transcript)
    user_prompt = (
        f"Video duration: {video_duration:.1f} seconds\n\n"
        f"Transcript with timestamps:\n{formatted}"
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[CUT_TOOL],
        tool_choice={"type": "tool", "name": "identify_cuts"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    cuts_raw: list[dict] = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "identify_cuts":
            cuts_raw = block.input.get("cuts", [])
            break

    cuts = _validate_cuts(cuts_raw, video_duration)
    logger.info("Identified %d cut ranges (%.1f seconds total)", len(cuts),
                sum(c["end"] - c["start"] for c in cuts))
    return cuts
