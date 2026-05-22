"""
Stage 5 — Asset Generation
Orchestrates: thumbnails → metadata → shorts clip → update Sheets
"""
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from shared import config, sheets_client
from shared.error_handler import stage_handler
from stage5_assets import thumbnail_gen, metadata_gen, shorts_clip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@stage_handler("Stage 5 — Asset Generation")
def run(
    date_str: str | None = None,
    edited_video_local_path: str | None = None,
    transcript: dict[str, Any] | None = None,
    srt_path: str | None = None,
) -> dict[str, Any]:
    """
    Args:
        date_str: ISO date for the pipeline row.
        edited_video_local_path: Local path of edited .mp4 (from Stage 4 on same machine).
        transcript: Whisper transcript dict (from Stage 4, if in-process chaining).
        srt_path: Local path to SRT file (from Stage 4).
    """
    today = date_str or date.today().isoformat()
    logger.info("Stage 5 starting for date %s", today)

    row = sheets_client.get_pipeline_row(today)
    if row is None:
        raise ValueError(f"No pipeline row for date {today}")

    # 1. Generate thumbnails
    thumb_results = thumbnail_gen.generate_thumbnails(row["thumbnail_brief"], today)
    thumb_urls = json.dumps([link for _, link in thumb_results])
    thumb_ids = [fid for fid, _ in thumb_results]

    # 2. Generate YouTube metadata
    whisper_segments = transcript.get("segments") if transcript else None
    meta = metadata_gen.generate_metadata(
        topic=row["topic"],
        script=row["script"],
        shot_list=row["shot_list"],
        titles={"title_a": row["title_a"], "title_b": row["title_b"], "title_c": row["title_c"]},
        whisper_segments=whisper_segments,
    )

    # 3. Create Shorts clip (if edited video is available locally)
    shorts_file_id = ""
    shorts_link = ""
    if edited_video_local_path and Path(edited_video_local_path).exists():
        video_path = Path(edited_video_local_path)
        srt = Path(srt_path) if srt_path else None
        if transcript:
            shorts_file_id, shorts_link = shorts_clip.create_short(
                video_path, transcript, srt, today
            )

    # 4. Update Sheets
    sheets_client.update_pipeline_fields(today, {
        "drive_thumbnails": thumb_urls,
        "status": "assets_ready",
    })

    logger.info("Stage 5 complete")
    return {
        "date": today,
        "thumbnail_ids": thumb_ids,
        "thumbnail_urls": thumb_urls,
        "description": meta["description"],
        "tags": meta["tags"],
        "chapters": meta["chapters"],
        "ab_test_plan": meta["ab_test_plan"],
        "shorts_file_id": shorts_file_id,
        "shorts_link": shorts_link,
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    result = run(date_str=target)
    print(f"\nThumbnails: {result['thumbnail_urls']}")
    print(f"Description ({len(result['description'].split())} words):\n{result['description'][:200]}...")
