"""
Calls Claude API to select the best topic and write a full 4-minute script.
Uses tool_choice to force structured JSON output then validates it.
"""
import json
import logging
from typing import Any

import anthropic

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

TOOL_SCHEMA = {
    "name": "generate_video_brief",
    "description": (
        "Generate a complete YouTube video brief for the AI-tools-for-small-businesses channel."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The specific topic for this video (e.g. 'How to use ChatGPT to write client emails in under 5 minutes')",
            },
            "angle": {
                "type": "string",
                "description": "The unique angle or hook that makes this video worth watching",
            },
            "script": {
                "type": "string",
                "description": (
                    "Full word-for-word script (550–650 words). "
                    "Structure: Hook (0:00–0:20) | Problem (0:20–0:50) | "
                    "Solution walkthrough (0:50–3:20) | CTA (3:20–4:00)"
                ),
            },
            "shot_list": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of screen-recording shots. Each starts with an action verb.",
            },
            "title_a": {
                "type": "string",
                "description": "Curiosity-based title (max 70 chars)",
            },
            "title_b": {
                "type": "string",
                "description": "SEO keyword-focused title (max 70 chars)",
            },
            "title_c": {
                "type": "string",
                "description": "Bold claim / outcome-focused title (max 70 chars)",
            },
            "thumbnail_brief": {
                "type": "string",
                "description": "Visual direction for DALL-E: describe the image, colours, layout, and text overlay",
            },
            "estimated_duration": {
                "type": "integer",
                "description": "Estimated recording time in minutes",
            },
        },
        "required": [
            "topic", "angle", "script", "shot_list",
            "title_a", "title_b", "title_c",
            "thumbnail_brief", "estimated_duration",
        ],
    },
}

SYSTEM_PROMPT = """\
You are an expert YouTube scriptwriter specialising in practical AI and tech tutorials for \
Irish and UK small business owners. Your audience is non-technical SMB owners aged 35–55 \
who want simple, actionable tools they can use this week.

Channel style:
- Friendly, direct, no fluff — like advice from a knowledgeable friend
- Screen-recorded, faceless format (no presenter on camera)
- 3–6 minute videos, natural conversational pace
- Real tools, real workflows, real examples (don't invent fake scenarios)
- Irish/UK context where relevant (mention pricing in GBP/EUR, reference local businesses)

Script structure (4 minutes / ~600 words):
1. Hook (0:00–0:20): Bold claim, surprising stat, or direct question that names the viewer's problem
2. Problem (0:20–0:50): Expand on the pain point — why this matters right now
3. Solution walkthrough (0:50–3:20): Step-by-step screen recording walkthrough
4. CTA (3:20–4:00): Single clear call-to-action (subscribe + link in description)

Shot list rules:
- One shot per line, action verb first (e.g. "Open ChatGPT and paste the prompt...")
- Match the script exactly — every script section has corresponding shots
- Include what to show on screen at every step

Title rules:
- All three titles under 70 characters
- title_a: curiosity ("The AI tool Irish businesses are quietly using")
- title_b: SEO keyword ("ChatGPT for small business: write emails in 5 min")
- title_c: bold outcome ("I saved 3 hours/week with this one ChatGPT trick")

Do not pad the script — 550–650 words is the hard target.
"""


def _build_user_prompt(
    candidates: list[dict[str, Any]],
    recent_topics: list[str],
) -> str:
    candidate_text = "\n".join(
        f"- {c['title']} (engagement_score={c['engagement_score']}, views_7d={c['views_7d']})"
        for c in candidates
    )
    recent_text = "\n".join(f"- {t}" for t in recent_topics) if recent_topics else "None yet"

    return f"""\
Below are {len(candidates)} trending topics in the "AI tools for small businesses" niche \
(from NexLev analytics):

{candidate_text}

Recently published topics (DO NOT repeat these):
{recent_text}

Pick the single best topic to make a video about today. Consider:
1. High engagement potential (NexLev score)
2. Practical value for Irish/UK SMB owners
3. Something you can demonstrate step-by-step in a 4-minute screen recording
4. Not already covered in recent videos

Then write the complete video brief using the generate_video_brief tool.\
"""


def _validate(brief: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings (empty = pass)."""
    errors: list[str] = []
    word_count = len(brief.get("script", "").split())
    if not (config.SCRIPT_WORD_COUNT_MIN <= word_count <= config.SCRIPT_WORD_COUNT_MAX):
        errors.append(
            f"Script word count is {word_count} — must be {config.SCRIPT_WORD_COUNT_MIN}–{config.SCRIPT_WORD_COUNT_MAX}"
        )
    for key in ("title_a", "title_b", "title_c"):
        title = brief.get(key, "")
        if len(title) > config.TITLE_MAX_CHARS:
            errors.append(f"{key} is {len(title)} chars — max {config.TITLE_MAX_CHARS}")
    shot_list = brief.get("shot_list", [])
    if not shot_list:
        errors.append("shot_list is empty")
    verbs = {"open", "show", "navigate", "click", "type", "paste", "record", "display",
             "zoom", "highlight", "scroll", "switch", "copy", "go", "select", "demo",
             "launch", "point", "save", "export", "upload", "pull", "enter"}
    for i, shot in enumerate(shot_list):
        first_word = shot.strip().split()[0].lower().rstrip(",") if shot.strip() else ""
        if first_word not in verbs:
            errors.append(f"shot_list[{i}] must start with an action verb: {shot!r}")
            break  # report once, not for every item
    return errors


@with_retry(max_attempts=3)
def _call_claude(messages: list[dict], correction: str | None = None) -> dict[str, Any]:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    if correction:
        messages = messages + [
            {"role": "assistant", "content": "I'll fix those issues and regenerate the brief."},
            {"role": "user", "content": correction},
        ]
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "generate_video_brief"},
        messages=messages,
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "generate_video_brief":
            return block.input
    raise ValueError("Claude did not return a generate_video_brief tool call")


def generate_brief(
    candidates: list[dict[str, Any]],
    recent_topics: list[str],
) -> dict[str, Any]:
    """
    Generate a validated video brief. Retries up to 3 times with correction prompts
    if validation fails.
    """
    user_prompt = _build_user_prompt(candidates, recent_topics)
    messages = [{"role": "user", "content": user_prompt}]

    for attempt in range(3):
        brief = _call_claude(messages, correction=None if attempt == 0 else _build_correction(errors))
        errors = _validate(brief)
        if not errors:
            logger.info("Script generated and validated on attempt %d", attempt + 1)
            return brief
        logger.warning("Validation failed (attempt %d): %s", attempt + 1, errors)

    raise ValueError(f"Script failed validation after 3 attempts: {errors}")


def _build_correction(errors: list[str]) -> str:
    error_list = "\n".join(f"- {e}" for e in errors)
    return (
        f"The brief has the following issues that must be fixed:\n{error_list}\n\n"
        "Please regenerate the complete brief using the generate_video_brief tool, "
        "fixing all issues listed above."
    )
