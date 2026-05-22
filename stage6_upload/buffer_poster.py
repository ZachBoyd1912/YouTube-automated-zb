"""
Buffer API: queue cross-posts to LinkedIn and Instagram.
Month 2 feature — stub returns early if BUFFER_ACCESS_TOKEN is not set.

Buffer API docs: https://buffer.com/developers/api
"""
import logging
from typing import Any

import httpx

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bufferapp.com/1"


@with_retry(max_attempts=3)
def _get_profiles() -> list[dict[str, Any]]:
    resp = httpx.get(
        f"{BASE_URL}/profiles.json",
        params={"access_token": config.BUFFER_ACCESS_TOKEN},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _find_profile_id(profiles: list[dict], service: str) -> str | None:
    for p in profiles:
        if p.get("service") == service:
            return p["id"]
    return None


@with_retry(max_attempts=3)
def _queue_update(profile_id: str, text: str, media: dict | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profile_ids[]": profile_id,
        "text": text,
        "access_token": config.BUFFER_ACCESS_TOKEN,
        "scheduled_at": "next",
    }
    if media:
        payload["media[link]"] = media.get("link", "")
        payload["media[description]"] = media.get("description", "")

    resp = httpx.post(f"{BASE_URL}/updates/create.json", data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def post_to_linkedin(youtube_url: str, topic: str, description: str) -> dict[str, Any]:
    """Queue a LinkedIn post linking to the YouTube video."""
    if not config.BUFFER_ACCESS_TOKEN:
        logger.info("BUFFER_ACCESS_TOKEN not set — skipping LinkedIn post (Month 2 feature)")
        return {"skipped": True}

    profiles = _get_profiles()
    profile_id = _find_profile_id(profiles, "linkedin")
    if not profile_id:
        logger.warning("No LinkedIn profile found in Buffer account")
        return {"skipped": True}

    teaser = f"🎬 New video: {topic}\n\n{description[:200]}...\n\nWatch now 👇\n{youtube_url}"
    result = _queue_update(profile_id, teaser, media={"link": youtube_url})
    logger.info("LinkedIn post queued in Buffer")
    return result


def post_to_instagram(shorts_url: str, topic: str) -> dict[str, Any]:
    """Queue an Instagram Reel post for the Shorts clip."""
    if not config.BUFFER_ACCESS_TOKEN:
        logger.info("BUFFER_ACCESS_TOKEN not set — skipping Instagram post (Month 2 feature)")
        return {"skipped": True}

    profiles = _get_profiles()
    profile_id = _find_profile_id(profiles, "instagram")
    if not profile_id:
        logger.warning("No Instagram profile found in Buffer account")
        return {"skipped": True}

    caption = (
        f"Quick tip for small business owners 👇\n\n{topic}\n\n"
        "#aitools #smallbusiness #ireland #ukbusiness #entrepreneur #businesstips"
    )
    result = _queue_update(profile_id, caption, media={"link": shorts_url})
    logger.info("Instagram post queued in Buffer")
    return result
