"""
Upload videos to YouTube via Data API v3 with scheduled publishing and playlist assignment.
"""
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytz
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from shared import config, drive_client
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

DUBLIN_TZ = pytz.timezone(config.TIMEZONE)


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


def _next_weekday(weekday: int, hour: int, from_dt: datetime | None = None) -> str:
    """Return ISO 8601 UTC string for the next occurrence of weekday at hour (Dublin time)."""
    base = from_dt or datetime.now(DUBLIN_TZ)
    days_ahead = weekday - base.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    target = base.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    return target.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chapters_to_description_suffix(chapters: list[dict]) -> str:
    """Convert chapter list to timestamp lines for description."""
    return "\n".join(f"{c['time']} {c['title']}" for c in chapters)


@with_retry(max_attempts=3)
def _get_or_create_playlist(service, playlist_name: str) -> str:
    """Return the ID of the named playlist, creating it if it doesn't exist."""
    result = service.playlists().list(
        part="snippet",
        mine=True,
        maxResults=50,
    ).execute()

    for item in result.get("items", []):
        if item["snippet"]["title"] == playlist_name:
            return item["id"]

    playlist = service.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": playlist_name,
                "description": f"All videos about {playlist_name}",
            },
            "status": {"privacyStatus": "public"},
        },
    ).execute()
    logger.info("Created YouTube playlist %r (id=%s)", playlist_name, playlist["id"])
    return playlist["id"]


@with_retry(max_attempts=3)
def upload_main_video(
    video_local_path: Path,
    title: str,
    description: str,
    tags: list[str],
    chapters: list[dict],
    schedule_dt: str | None = None,
) -> str:
    """
    Upload the main video. Returns the YouTube video ID.
    schedule_dt: ISO 8601 UTC string for scheduled publish, or None to publish immediately.
    """
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would upload main video: %s", title)
        return "dry-run-video-id"

    service = _get_service()

    chapter_text = _chapters_to_description_suffix(chapters)
    full_description = f"{description}\n\n──────────────────\n{chapter_text}"

    publish_at = schedule_dt or _next_weekday(config.PUBLISH_WEEKDAY, config.PUBLISH_HOUR)

    body = {
        "snippet": {
            "title": title,
            "description": full_description,
            "tags": tags,
            "categoryId": config.YOUTUBE_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_local_path), mimetype="video/mp4", resumable=True, chunksize=50 * 1024 * 1024)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    logger.info("Uploaded main video %r → id=%s, scheduled=%s", title, video_id, publish_at)

    # Assign to playlist
    playlist_id = _get_or_create_playlist(service, config.YOUTUBE_PLAYLIST_NAME)
    service.playlistItems().insert(
        part="snippet",
        body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
    ).execute()
    logger.info("Added video to playlist %r", config.YOUTUBE_PLAYLIST_NAME)

    return video_id


@with_retry(max_attempts=3)
def set_thumbnail(video_id: str, thumbnail_local_path: Path) -> None:
    """Set the video thumbnail."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would set thumbnail for video %s", video_id)
        return

    service = _get_service()
    service.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(thumbnail_local_path), mimetype="image/png"),
    ).execute()
    logger.info("Set thumbnail for video %s", video_id)


@with_retry(max_attempts=3)
def upload_short(
    short_local_path: Path,
    main_title: str,
    schedule_dt: str | None = None,
) -> str:
    """Upload a YouTube Short. Returns the video ID."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would upload Short: %s", main_title)
        return "dry-run-shorts-id"

    service = _get_service()
    shorts_title = main_title[:60] + " #shorts" if len(main_title) > 60 else main_title + " #shorts"
    publish_at = schedule_dt or _next_weekday(config.SHORTS_PUBLISH_WEEKDAY, config.SHORTS_PUBLISH_HOUR)

    body = {
        "snippet": {
            "title": shorts_title,
            "description": f"Quick tip: {main_title}\n\n#shorts #aitools #smallbusiness #ireland",
            "tags": ["shorts", "ai tools", "small business", "ireland", "uk business"],
            "categoryId": config.YOUTUBE_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(short_local_path), mimetype="video/mp4", resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()

    shorts_id = response["id"]
    logger.info("Uploaded Short %r → id=%s, scheduled=%s", shorts_title, shorts_id, publish_at)
    return shorts_id
