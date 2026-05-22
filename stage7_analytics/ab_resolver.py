"""
Check A/B tests and declare winners when criteria are met.
Criteria: ≥500 impressions AND ≥1% CTR advantage for one variant.
"""
import logging
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from shared import config, sheets_client
from shared.error_handler import with_retry
from stage6_upload import tubebuddy_ab

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
]

MIN_IMPRESSIONS = 500
MIN_CTR_ADVANTAGE = 0.01  # 1 percentage point


def _get_youtube_service():
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=YOUTUBE_SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


@with_retry(max_attempts=3)
def _set_permanent_thumbnail(video_id: str, thumbnail_local_path: str) -> None:
    """Set the winning thumbnail as permanent via YouTube Data API."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would set permanent thumbnail for %s", video_id)
        return
    from googleapiclient.http import MediaFileUpload  # noqa: PLC0415
    service = _get_youtube_service()
    service.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(thumbnail_local_path, mimetype="image/png"),
    ).execute()
    logger.info("Set permanent thumbnail for video %s", video_id)


def _find_winner(ab_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Return the winning variant dict if criteria met, else None.
    Each result dict: {variant, impressions, ctr, ...}
    """
    eligible = [r for r in ab_results if r.get("impressions", 0) >= MIN_IMPRESSIONS]
    if len(eligible) < 2:
        return None

    sorted_by_ctr = sorted(eligible, key=lambda r: r.get("ctr", 0.0), reverse=True)
    best = sorted_by_ctr[0]
    second = sorted_by_ctr[1]
    ctr_advantage = best.get("ctr", 0.0) - second.get("ctr", 0.0)

    if ctr_advantage >= MIN_CTR_ADVANTAGE:
        return best
    return None


def resolve_ab_tests(analytics_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    For each video with active A/B tests, declare a winner if criteria met.
    Returns list of resolution results.
    """
    resolutions: list[dict[str, Any]] = []

    for video_analytics in analytics_data:
        video_id = video_analytics.get("video_id")
        video_date = video_analytics.get("date")
        ab_results = video_analytics.get("ab_results", [])

        if not ab_results or not video_id:
            continue

        # Split thumbnail and title tests
        thumb_results = [r for r in ab_results if r.get("test_type") == "thumbnail"]
        title_results = [r for r in ab_results if r.get("test_type") == "title"]

        resolution = {"video_id": video_id, "date": video_date}

        # Resolve thumbnail test
        if thumb_results:
            winner = _find_winner(thumb_results)
            if winner:
                test_id = winner.get("test_id")
                winning_variant = winner.get("variant", "A")
                logger.info("Thumbnail winner for %s: variant %s (CTR=%.2f%%)",
                            video_id, winning_variant, winner.get("ctr", 0) * 100)
                tubebuddy_ab.end_ab_test(test_id, winning_variant)
                sheets_client.update_pipeline_fields(video_date, {
                    "ab_winner_thumb": winning_variant,
                })
                resolution["thumbnail_winner"] = winning_variant
            else:
                resolution["thumbnail_winner"] = None
                logger.info("No thumbnail winner yet for %s (not enough data)", video_id)

        # Resolve title test
        if title_results:
            winner = _find_winner(title_results)
            if winner:
                test_id = winner.get("test_id")
                winning_variant = winner.get("variant", "A")
                logger.info("Title winner for %s: variant %s", video_id, winning_variant)
                tubebuddy_ab.end_ab_test(test_id, winning_variant)
                sheets_client.update_pipeline_fields(video_date, {
                    "ab_winner_title": winning_variant,
                })
                resolution["title_winner"] = winning_variant
            else:
                resolution["title_winner"] = None

        resolutions.append(resolution)

    return resolutions
