"""
Generate YouTube metadata (description, tags, chapters, A/B plan) via DeepSeek on OpenRouter.
"""
import logging
from typing import Any

from shared import config
from shared.llm_client import forced_tool_call

logger = logging.getLogger(__name__)

METADATA_TOOL = {
    "name": "generate_youtube_metadata",
    "description": "Generate all YouTube metadata for a video",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": (
                    f"Full YouTube description, {config.DESCRIPTION_WORD_COUNT_MIN}–"
                    f"{config.DESCRIPTION_WORD_COUNT_MAX} words, keyword-rich, "
                    "with timestamps section at the end"
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Exactly {config.SEO_TAG_COUNT} SEO tags",
            },
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "time": {"type": "string", "description": "MM:SS format"},
                        "title": {"type": "string"},
                    },
                    "required": ["time", "title"],
                },
            },
            "ab_test_plan": {
                "type": "object",
                "properties": {
                    "launch_title": {
                        "type": "string",
                        "enum": ["title_a", "title_b", "title_c"],
                        "description": "Which title variant to go live with first",
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["launch_title", "reasoning"],
            },
        },
        "required": ["description", "tags", "chapters", "ab_test_plan"],
    },
}

SYSTEM_PROMPT = """\
You are a YouTube SEO specialist for a channel about AI tools for Irish and UK small businesses.

Description rules:
- 300–400 words
- First 2 lines must be compelling (shown before the "more" fold)
- Naturally include primary keyword in first sentence
- Include a timestamps section at the end (00:00 Intro, etc.)
- End with a subscribe CTA
- Use British/Irish English spelling (organise, behaviour, colour)

Tags: mix of exact-match phrases and broad keywords; include location tags \
("ireland", "uk small business", "irish entrepreneur").

Chapters: match actual script sections (Hook → Problem → Solution → CTA). \
First chapter must always be "00:00".
"""


def generate_metadata(
    topic: str,
    script: str,
    shot_list: str,
    titles: dict[str, str],
    whisper_segments: list[dict] | None = None,
) -> dict[str, Any]:
    """Generate description, tags, chapters, and A/B test plan."""
    segments_text = ""
    if whisper_segments:
        segments_text = "\n\nActual recording timestamps (from Whisper):\n" + "\n".join(
            f"{s['start']:.0f}s – {s.get('text', '').strip()[:60]}"
            for s in (whisper_segments[:20] if len(whisper_segments) > 20 else whisper_segments)
        )

    user_prompt = (
        f"Topic: {topic}\n\nScript:\n{script}\n\nShot list:\n{shot_list}\n\n"
        f"Title variants:\n"
        f"  A (curiosity): {titles['title_a']}\n"
        f"  B (SEO): {titles['title_b']}\n"
        f"  C (bold claim): {titles['title_c']}"
        f"{segments_text}"
    )

    meta = forced_tool_call(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        tool=METADATA_TOOL,
        max_tokens=2048,
    )
    logger.info(
        "Metadata generated: %d-word description, %d tags, %d chapters",
        len(meta["description"].split()), len(meta["tags"]), len(meta["chapters"]),
    )
    return meta
