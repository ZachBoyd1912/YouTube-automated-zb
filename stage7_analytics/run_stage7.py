"""
Stage 7 — Analytics & Optimisation (Sunday 09:00)
Orchestrates: pull analytics → resolve A/B tests → generate report → update Sheets
"""
import json
import logging
from datetime import date
from typing import Any

from shared import sheets_client
from shared.error_handler import stage_handler
from stage7_analytics import analytics_puller, ab_resolver, report_generator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@stage_handler("Stage 7 — Analytics")
def run() -> dict[str, Any]:
    logger.info("Stage 7 starting — Sunday analytics run")

    # Get all published video IDs from Sheets
    video_ids = sheets_client.get_all_published_video_ids()
    if not video_ids:
        logger.info("No published videos yet — Stage 7 done")
        return {"message": "No published videos to analyse"}

    logger.info("Analysing %d videos", len(video_ids))

    # Pull analytics
    analytics_data = analytics_puller.pull_all_analytics(video_ids)

    # Resolve A/B tests with clear winners
    ab_resolutions = ab_resolver.resolve_ab_tests(analytics_data)
    winners = [r for r in ab_resolutions if r.get("thumbnail_winner") or r.get("title_winner")]
    logger.info("Resolved %d A/B tests with winners", len(winners))

    # Generate and send report
    report = report_generator.send_report(analytics_data, ab_resolutions)

    # Save analytics summary to Sheets weekly tab
    summary = {
        "week_ending": date.today().isoformat(),
        "videos_analysed": len(analytics_data),
        "total_views": sum(v.get("views", 0) for v in analytics_data),
        "total_watch_minutes": sum(v.get("watch_minutes", 0) for v in analytics_data),
        "ab_tests_resolved": len(winners),
        "top_video_id": report.get("top_video_id", ""),
        "recommended_direction": report.get("recommended_topic_direction", ""),
    }
    sheets_client.write_analytics_row(summary)

    logger.info("Stage 7 complete")
    return {
        "analytics_data": analytics_data,
        "ab_resolutions": ab_resolutions,
        "report": report,
        "summary": summary,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = run()
    print(f"\nAnalysed {result.get('summary', {}).get('videos_analysed', 0)} videos")
    print(f"Report sent. Top video: {result.get('report', {}).get('top_video_id', 'N/A')}")
