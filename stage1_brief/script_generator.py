"""
Calls DeepSeek (via OpenRouter) to select the best topic and write a full 4-minute script.
Uses forced tool calling for structured JSON output, then validates the result.
"""
import logging
from typing import Any

from shared import config
from shared.llm_client import forced_tool_call

logger = logging.getLogger(__name__)

TOOL = {
    "name": "generate_video_brief",
    "description": (
        "Generate a complete YouTube video brief for the AI-tools-for-small-businesses channel."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The specific topic for this video",
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
                "description": "Ordered screen-recording shots, each starting with an action verb.",
            },
            "title_a": {"type": "string", "description": "Curiosity-based title (max 70 chars)"},
            "title_b": {"type": "string", "description": "SEO keyword-focused title (max 70 chars)"},
            "title_c": {"type": "string", "description": "Bold claim / outcome title (max 70 chars)"},
            "thumbnail_brief": {
                "type": "string",
                "description": "Visual direction for DALL-E: image, colours, layout, text overlay area",
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
1. Hook (0:00–0:20): Bold claim, surprising stat, or direct question naming the viewer's problem
2. Problem (0:20–0:50): Expand on the pain point — why this matters right now
3. Solution walkthrough (0:50–3:20): Step-by-step screen recording walkthrough
4. CTA (3:20–4:00): Single clear call-to-action (subscribe + link in description)

Shot list rules:
- One shot per line, action verb first (e.g. "Open ChatGPT and paste the prompt...")
- Match the script exactly — every section has corresponding shots
- Include what to show on screen at every step

Title rules (ALL under 70 characters):
- title_a: curiosity ("The AI tool Irish businesses are quietly using")
- title_b: SEO keyword ("ChatGPT for small business: write emails in 5 min")
- title_c: bold outcome ("I saved 3 hours/week with this one ChatGPT trick")

Hard target: 550–650 words for the script. Do not pad or truncate beyond this range.
"""


def _build_user_prompt(candidates: list[dict[str, Any]], recent_topics: list[str]) -> str:
    candidate_text = "\n".join(
        f"- {c['title']} (engagement={c['engagement_score']}, views_7d={c['views_7d']})"
        for c in candidates
    )
    recent_text = "\n".join(f"- {t}" for t in recent_topics) if recent_topics else "None yet"
    return (
        f"Trending topics in the 'AI tools for small businesses' niche ({len(candidates)} candidates):\n"
        f"{candidate_text}\n\n"
        f"Recently published topics (DO NOT repeat these):\n{recent_text}\n\n"
        "Pick the single best topic and write the complete video brief."
    )


def _validate(brief: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    word_count = len(brief.get("script", "").split())
    if not (config.SCRIPT_WORD_COUNT_MIN <= word_count <= config.SCRIPT_WORD_COUNT_MAX):
        errors.append(
            f"Script is {word_count} words — must be "
            f"{config.SCRIPT_WORD_COUNT_MIN}–{config.SCRIPT_WORD_COUNT_MAX}"
        )
    for key in ("title_a", "title_b", "title_c"):
        if len(brief.get(key, "")) > config.TITLE_MAX_CHARS:
            errors.append(f"{key} exceeds {config.TITLE_MAX_CHARS} chars")
    if not brief.get("shot_list"):
        errors.append("shot_list is empty")
    verbs = {
        "open", "show", "navigate", "click", "type", "paste", "record", "display",
        "zoom", "highlight", "scroll", "switch", "copy", "go", "select", "demo",
        "launch", "point", "save", "export", "upload", "pull", "enter",
    }
    for i, shot in enumerate(brief.get("shot_list", [])):
        first = shot.strip().split()[0].lower().rstrip(",") if shot.strip() else ""
        if first not in verbs:
            errors.append(f"shot_list[{i}] must start with an action verb: {shot!r}")
            break
    return errors


def generate_brief(
    candidates: list[dict[str, Any]],
    recent_topics: list[str],
) -> dict[str, Any]:
    """Generate a validated video brief, retrying up to 3 times if validation fails."""
    user_prompt = _build_user_prompt(candidates, recent_topics)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(3):
        brief = forced_tool_call(
            system=SYSTEM_PROMPT,
            user="",  # messages_override used instead
            tool=TOOL,
            messages_override=messages,
        )
        errors = _validate(brief)
        if not errors:
            logger.info("Script validated on attempt %d", attempt + 1)
            return brief

        logger.warning("Validation failed (attempt %d): %s", attempt + 1, errors)
        error_list = "\n".join(f"- {e}" for e in errors)
        messages = messages + [
            {"role": "assistant", "content": f"[Generated brief with {len(errors)} issue(s)]"},
            {
                "role": "user",
                "content": (
                    f"The brief has these issues:\n{error_list}\n\n"
                    "Please regenerate the complete brief, fixing all issues."
                ),
            },
        ]

    raise ValueError(f"Script failed validation after 3 attempts. Last errors: {errors}")
