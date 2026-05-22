"""
Generate a plain-English WhatsApp analytics report for Zach via Claude API.
"""
import logging
from typing import Any

import anthropic

from shared import config, whatsapp_client
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are writing a weekly performance summary for Zach, who runs a faceless YouTube channel \
about AI tools for small businesses. He is non-technical — write in plain, friendly English \
like you're texting a smart friend.

Keep the report concise and actionable. No marketing fluff. No jargon.
Format for WhatsApp (use *bold* for key numbers, use emoji sparingly, keep it under 500 words).
"""

REPORT_TOOL = {
    "name": "generate_weekly_report",
    "description": "Generate Zach's weekly YouTube performance WhatsApp report",
    "input_schema": {
        "type": "object",
        "properties": {
            "report_text": {
                "type": "string",
                "description": (
                    "The complete WhatsApp message. Include: "
                    "best performing video this week, "
                    "which thumbnail/title style won, "
                    "3 specific actionable recommendations for next week, "
                    "suggested topic direction. Under 500 words."
                ),
            },
            "top_video_id": {
                "type": "string",
                "description": "YouTube ID of the best performing video",
            },
            "recommended_topic_direction": {
                "type": "string",
                "description": "One-sentence topic direction for next week's Stage 1 context",
            },
        },
        "required": ["report_text", "top_video_id", "recommended_topic_direction"],
    },
}


@with_retry(max_attempts=3)
def generate_report(
    analytics_data: list[dict[str, Any]],
    ab_resolutions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate and return the report dict (report_text, top_video_id, recommended_topic_direction)."""
    if not analytics_data:
        return {
            "report_text": "📊 No analytics data available yet — looks like the channel is just getting started!",
            "top_video_id": "",
            "recommended_topic_direction": "Continue with planned content strategy",
        }

    # Summarise for Claude
    video_summaries = []
    for v in sorted(analytics_data, key=lambda x: x.get("views", 0), reverse=True):
        ab_res = next((r for r in ab_resolutions if r.get("video_id") == v.get("video_id")), {})
        video_summaries.append(
            f"Video {v.get('video_id', 'unknown')} (published {v.get('date', '?')}):\n"
            f"  Views: {v.get('views', 0):,}\n"
            f"  Avg view duration: {v.get('avg_view_duration', 0):.0f}s\n"
            f"  Watch minutes: {v.get('watch_minutes', 0):,.0f}\n"
            f"  Subs gained: {v.get('subscribers_gained', 0)}\n"
            f"  Best CTR variant: {v.get('best_ctr_variant', 'N/A')} "
            f"({v.get('best_ctr', 0)*100:.1f}%)\n"
            f"  Thumbnail winner: {ab_res.get('thumbnail_winner', 'pending')}\n"
            f"  Title winner: {ab_res.get('title_winner', 'pending')}"
        )

    analytics_text = "\n\n".join(video_summaries)
    user_prompt = f"Weekly analytics data (last 30 days):\n\n{analytics_text}"

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[REPORT_TOOL],
        tool_choice={"type": "tool", "name": "generate_weekly_report"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "generate_weekly_report":
            return block.input

    raise ValueError("Claude did not return generate_weekly_report tool call")


def send_report(analytics_data: list[dict[str, Any]], ab_resolutions: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate report and send it to Zach's WhatsApp. Returns the report dict."""
    report = generate_report(analytics_data, ab_resolutions)
    whatsapp_client.send_whatsapp(report["report_text"])
    logger.info("Weekly report sent to Zach")
    return report
