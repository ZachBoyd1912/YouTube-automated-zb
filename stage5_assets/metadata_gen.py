"""
Generate YouTube metadata (description, tags, chapters, A/B plan) via Claude API.
"""
import logging
from typing import Any

import anthropic

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

METADATA_TOOL = {
    "name": "generate_youtube_metadata",
    "description": "Generate all YouTube metadata for a video",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": f"Full YouTube description, {config.DESCRIPTION_WORD_COUNT_MIN}–{config.DESCRIPTION_WORD_COUNT_MAX} words, keyword-rich, with timestamps section",
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
                "description": "Video chapters matching the script structure",
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
- First 2 lines must be compelling (shown in search results before the "more" fold)
- Naturally include primary keyword in first sentence
- Include a timestamps section at the end (00:00 Intro, etc.)
- End with a subscribe CTA
- Use British/Irish English spelling (organise, behaviour, colour)

Tags rules:
- Mix of exact-match (3–5 words) and broad keywords
- Include location tags: "ireland", "uk small business", "irish entrepreneur"
- Include tool-specific tags when relevant
- No spaces within a tag that is itself a phrase — use the tag as a unit

Chapters:
- Match the actual script sections (Hook → Problem → Solution → CTA)
- 00:00 must always be first
"""


@with_retry(max_attempts=3)
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
        f"Topic: {topic}\n\n"
        f"Script:\n{script}\n\n"
        f"Shot list:\n{shot_list}\n\n"
        f"Title variants:\n"
        f"  A (curiosity): {titles['title_a']}\n"
        f"  B (SEO): {titles['title_b']}\n"
        f"  C (bold claim): {titles['title_c']}"
        f"{segments_text}"
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[METADATA_TOOL],
        tool_choice={"type": "tool", "name": "generate_youtube_metadata"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "generate_youtube_metadata":
            meta = block.input
            word_count = len(meta["description"].split())
            logger.info(
                "Metadata generated: %d-word description, %d tags, %d chapters",
                word_count, len(meta["tags"]), len(meta["chapters"]),
            )
            return meta

    raise ValueError("Claude did not return generate_youtube_metadata tool call")
