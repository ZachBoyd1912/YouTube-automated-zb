"""
Finds trending topic candidates using the YouTube Data API v3.
Searches for recent high-performing videos in the AI tools / small business niche,
pulls their statistics, and returns normalised candidate dicts for the script generator.

NexLev is used as an optional enrichment layer if NEXLEV_API_KEY is set.
If not set (the common case), YouTube Data API is the sole source — no functionality lost.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

# Search queries cycled through to get diverse candidates
SEARCH_QUERIES = [
    "AI tools small business 2024",
    "ChatGPT for business tutorial",
    "AI automation small business ireland uk",
    "artificial intelligence business productivity",
    "AI tools save time business owner",
]

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def _get_service():
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
def _search_videos(service, query: str, published_after: str) -> list[dict]:
    result = service.search().list(
        q=query,
        type="video",
        order="viewCount",
        publishedAfter=published_after,
        maxResults=10,
        relevanceLanguage="en",
        videoDuration="medium",   # 4–20 min — matches Zach's format
    ).execute()
    return result.get("items", [])


@with_retry(max_attempts=3)
def _get_video_stats(service, video_ids: list[str]) -> dict[str, dict]:
    """Return {video_id: {viewCount, likeCount, commentCount}} for a batch of IDs."""
    if not video_ids:
        return {}
    result = service.videos().list(
        part="statistics,snippet",
        id=",".join(video_ids),
    ).execute()
    return {
        item["id"]: {
            "views": int(item["statistics"].get("viewCount", 0)),
            "likes": int(item["statistics"].get("likeCount", 0)),
            "title": item["snippet"]["title"],
            "description": item["snippet"].get("description", "")[:200],
            "channel": item["snippet"]["channelTitle"],
        }
        for item in result.get("items", [])
    }


def get_candidate_topics(recent_topics: list[str]) -> list[dict[str, Any]]:
    """
    Pull trending video data from YouTube and return normalised candidate topic dicts.
    Each dict has: title, angle_hint, views_7d, engagement_score, channel_count, rpm_estimate.
    """
    service = _get_service()

    # Look back 30 days for recent performers
    published_after = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    seen_ids: set[str] = set()
    all_items: list[dict] = []

    for query in SEARCH_QUERIES:
        try:
            items = _search_videos(service, query, published_after)
            for item in items:
                vid_id = item["id"].get("videoId")
                if vid_id and vid_id not in seen_ids:
                    seen_ids.add(vid_id)
                    all_items.append(item)
        except Exception as exc:
            logger.warning("YouTube search failed for query %r: %s", query, exc)

    if not all_items:
        raise RuntimeError("YouTube Data API returned no results — check API quota and credentials")

    # Fetch statistics in one batch call
    video_ids = [item["id"]["videoId"] for item in all_items if item["id"].get("videoId")]
    stats = _get_video_stats(service, video_ids)

    # Normalise into candidate dicts
    candidates = _normalise(stats)
    candidates = _deduplicate(candidates, recent_topics)
    candidates.sort(key=lambda c: c["engagement_score"], reverse=True)

    logger.info("Got %d candidate topics from YouTube Data API", len(candidates))
    return candidates[:12]


def _normalise(stats: dict[str, dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for vid_id, data in stats.items():
        views = data["views"]
        likes = data["likes"]
        # Simple engagement score: likes as % of views, weighted by view count
        engagement = (likes / max(views, 1)) * min(views / 1000, 10)
        out.append({
            "title": data["title"],
            "angle_hint": data["description"],
            "views_7d": views,
            "engagement_score": round(engagement, 3),
            "channel_count": 1,
            "rpm_estimate": 0,
            "source_channel": data["channel"],
        })
    return out


def _deduplicate(candidates: list[dict], recent_topics: list[str]) -> list[dict]:
    recent_lower = {t.lower() for t in recent_topics}
    return [
        c for c in candidates
        if not any(_overlap(c["title"].lower(), r) for r in recent_lower)
    ]


def _overlap(a: str, b: str) -> bool:
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) > 0.6
