"""
Stage 1 — Topic Research & Script Generation
Orchestrates: NexLev research → Claude script → Google Sheets write
"""
import logging
from datetime import date
from typing import Any

from shared import config, sheets_client
from shared.error_handler import stage_handler
from stage1_brief import topic_researcher, script_generator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@stage_handler("Stage 1 — Script Generation")
def run() -> dict[str, Any]:
    today = date.today().isoformat()
    logger.info("Stage 1 starting for date %s", today)

    # Avoid repeating recent topics
    recent_topics = sheets_client.get_recent_topics(n=10)
    logger.info("Recent topics: %s", recent_topics)

    # Pull trending candidates from NexLev
    candidates = topic_researcher.get_candidate_topics(recent_topics)
    if not candidates:
        raise RuntimeError("NexLev returned no candidate topics")

    # Generate brief via Claude
    brief = script_generator.generate_brief(candidates, recent_topics)

    # Build the Sheets row
    row: dict[str, Any] = {
        "date": today,
        "topic": brief["topic"],
        "angle": brief["angle"],
        "script": brief["script"],
        "shot_list": "\n".join(f"{i+1}. {s}" for i, s in enumerate(brief["shot_list"])),
        "title_a": brief["title_a"],
        "title_b": brief["title_b"],
        "title_c": brief["title_c"],
        "thumbnail_brief": brief["thumbnail_brief"],
        "estimated_duration": brief["estimated_duration"],
        "status": "draft",
    }

    sheets_client.write_pipeline_row(row)
    logger.info("Stage 1 complete — topic: %s", brief["topic"])
    return row


if __name__ == "__main__":
    result = run()
    print("\n=== Stage 1 Output ===")
    for k, v in result.items():
        print(f"\n[{k.upper()}]\n{v}")
