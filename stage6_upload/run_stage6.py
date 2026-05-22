"""
Stage 6 — Upload & Schedule
Orchestrates: download edited video → upload to YouTube → set thumbnail →
create A/B tests → cross-post → update Sheets
"""
import json
import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from shared import config, drive_client, sheets_client
from shared.error_handler import stage_handler
from stage6_upload import youtube_uploader, tubebuddy_ab, buffer_poster

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@stage_handler("Stage 6 — Upload & Schedule")
def run(
    date_str: str | None = None,
    stage5_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Args:
        date_str: ISO date for the pipeline row.
        stage5_result: Output dict from Stage 5 (if chaining in-process).
    """
    today = date_str or date.today().isoformat()
    logger.info("Stage 6 starting for date %s", today)

    row = sheets_client.get_pipeline_row(today)
    if row is None:
        raise ValueError(f"No pipeline row for date {today}")

    s5 = stage5_result or {}
    description: str = s5.get("description", "")
    tags: list[str] = s5.get("tags", [])
    chapters: list[dict] = s5.get("chapters", [])
    ab_test_plan: dict = s5.get("ab_test_plan", {})
    thumbnail_ids: list[str] = s5.get("thumbnail_ids", [])
    shorts_file_id: str = s5.get("shorts_file_id", row.get("shorts_id", ""))

    if not description:
        raise ValueError("No description available — run Stage 5 first or pass stage5_result")

    tmp_dir = Path(tempfile.mkdtemp(prefix="yt-stage6-"))

    # Download edited video from Drive
    edited_drive_link = row.get("drive_edited", "")
    if not edited_drive_link:
        raise ValueError("drive_edited not set in Sheets row — run Stage 4 first")

    # Get file ID from Drive link (links are .../file/d/<ID>/view or similar)
    edited_file_id = _extract_file_id(edited_drive_link)
    video_path = tmp_dir / f"edited_{today}.mp4"
    drive_client.download_file(edited_file_id, video_path)

    # Determine which title to launch first
    launch_title_key = ab_test_plan.get("launch_title", "title_a")
    launch_title = row.get(launch_title_key, row.get("title_a", ""))

    # Upload main video
    video_id = youtube_uploader.upload_main_video(
        video_local_path=video_path,
        title=launch_title,
        description=description,
        tags=tags,
        chapters=chapters,
    )

    # Download and set thumbnail variant A
    if thumbnail_ids:
        thumb_path = tmp_dir / "thumb_a.png"
        drive_client.download_file(thumbnail_ids[0], thumb_path)
        youtube_uploader.set_thumbnail(video_id, thumb_path)

    # Create A/B tests
    if len(thumbnail_ids) >= 3 and not config.DRY_RUN:
        tubebuddy_ab.create_thumbnail_ab_test(video_id, thumbnail_ids[:3])
    tubebuddy_ab.create_title_ab_test(
        video_id,
        [row.get("title_a", ""), row.get("title_b", ""), row.get("title_c", "")],
    )

    # Upload Short (if available)
    shorts_id = ""
    if shorts_file_id:
        short_path = tmp_dir / f"short_{today}.mp4"
        drive_client.download_file(shorts_file_id, short_path)
        shorts_id = youtube_uploader.upload_short(short_path, launch_title)

    # Cross-post to LinkedIn and Instagram
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    buffer_poster.post_to_linkedin(yt_url, row["topic"], description)
    if shorts_id:
        shorts_url = f"https://www.youtube.com/shorts/{shorts_id}"
        buffer_poster.post_to_instagram(shorts_url, row["topic"])

    # Update Sheets
    sheets_client.update_pipeline_fields(today, {
        "youtube_id": video_id,
        "shorts_id": shorts_id,
        "status": "published",
    })

    # Cleanup
    for p in tmp_dir.iterdir():
        p.unlink(missing_ok=True)
    tmp_dir.rmdir()

    logger.info("Stage 6 complete — YouTube ID: %s", video_id)
    return {
        "date": today,
        "youtube_id": video_id,
        "shorts_id": shorts_id,
        "youtube_url": yt_url,
    }


def _extract_file_id(drive_link: str) -> str:
    """Extract Drive file ID from a web view link."""
    import re
    match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", drive_link)
    if match:
        return match.group(1)
    # If it's already just an ID (from upload_file returning file_id directly)
    if len(drive_link) > 20 and "/" not in drive_link:
        return drive_link
    raise ValueError(f"Cannot extract file ID from Drive link: {drive_link}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    result = run(date_str=target)
    print(f"\nYouTube URL: {result['youtube_url']}")
