"""
Pull YouTube Analytics API data for the last 30 days per published video.
Also pulls TubeBuddy A/B test results.
"""
import logging
from datetime import date, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from shared import config
from shared.error_handler import with_retry
from stage6_upload import tubebuddy_ab

logger = logging.getLogger(__name__)

ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def _get_analytics_service():
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=ANALYTICS_SCOPES,
    )
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


@with_retry(max_attempts=3)
def pull_video_analytics(video_id: str) -> dict[str, Any]:
    """Return 30-day analytics metrics for a single video."""
    service = _get_analytics_service()
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=30)).isoformat()

    result = service.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
        dimensions="video",
        filters=f"video=={video_id}",
    ).execute()

    rows = result.get("rows", [])
    if not rows:
        return {"video_id": video_id, "views": 0, "watch_minutes": 0,
                "avg_view_duration": 0, "subscribers_gained": 0}

    row = rows[0]
    return {
        "video_id": video_id,
        "views": int(row[1]),
        "watch_minutes": float(row[2]),
        "avg_view_duration": float(row[3]),
        "subscribers_gained": int(row[4]),
    }


@with_retry(max_attempts=3)
def pull_ab_test_results(video_id: str) -> list[dict[str, Any]]:
    """Pull TubeBuddy A/B test CTR data for a video."""
    try:
        return tubebuddy_ab.get_ab_test_results(video_id)
    except Exception as exc:
        logger.warning("TubeBuddy A/B results unavailable for %s: %s", video_id, exc)
        return []


def pull_all_analytics(video_ids: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """
    Pull analytics for a list of (date, video_id) tuples.
    Returns list of analytics dicts enriched with date and AB test data.
    """
    results: list[dict[str, Any]] = []
    for video_date, video_id in video_ids:
        try:
            analytics = pull_video_analytics(video_id)
            ab_results = pull_ab_test_results(video_id)
            analytics["date"] = video_date
            analytics["ab_results"] = ab_results
            # Compute best CTR variant from AB results
            if ab_results:
                best = max(ab_results, key=lambda r: r.get("ctr", 0), default=None)
                analytics["best_ctr_variant"] = best.get("variant") if best else None
                analytics["best_ctr"] = best.get("ctr", 0.0) if best else 0.0
            results.append(analytics)
            logger.info("Pulled analytics for %s: %d views", video_id, analytics["views"])
        except Exception as exc:
            logger.error("Failed to pull analytics for %s: %s", video_id, exc)

    return results
