"""
Generate a plain-English WhatsApp analytics report for Zach via DeepSeek on OpenRouter.
"""
import logging
from typing import Any

from shared import whatsapp_client
from shared.llm_client import forced_tool_call

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
                    "Complete WhatsApp message. Include: best video this week, "
                    "which thumbnail/title style won, 3 specific actionable recommendations, "
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


def generate_report(
    analytics_data: list[dict[str, Any]],
    ab_resolutions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate and return the report dict."""
    if not analytics_data:
        return {
            "report_text": "📊 No analytics data yet — channel is just getting started!",
            "top_video_id": "",
            "recommended_topic_direction": "Continue with planned content strategy",
        }

    video_summaries = []
    for v in sorted(analytics_data, key=lambda x: x.get("views", 0), reverse=True):
        ab_res = next((r for r in ab_resolutions if r.get("video_id") == v.get("video_id")), {})
        video_summaries.append(
            f"Video {v.get('video_id')} (published {v.get('date')}):\n"
            f"  Views: {v.get('views', 0):,} | "
            f"Avg duration: {v.get('avg_view_duration', 0):.0f}s | "
            f"Subs: {v.get('subscribers_gained', 0)} | "
            f"Best CTR variant: {v.get('best_ctr_variant', 'N/A')} "
            f"({v.get('best_ctr', 0)*100:.1f}%) | "
            f"Thumb winner: {ab_res.get('thumbnail_winner', 'pending')} | "
            f"Title winner: {ab_res.get('title_winner', 'pending')}"
        )

    user_prompt = "Weekly analytics (last 30 days):\n\n" + "\n\n".join(video_summaries)
    report = forced_tool_call(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        tool=REPORT_TOOL,
        max_tokens=1024,
    )
    return report


def send_report(
    analytics_data: list[dict[str, Any]],
    ab_resolutions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate report and send it to Zach's WhatsApp."""
    report = generate_report(analytics_data, ab_resolutions)
    whatsapp_client.send_whatsapp(report["report_text"])
    logger.info("Weekly report sent to Zach")
    return report
