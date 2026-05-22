"""
TubeBuddy API: create A/B tests for thumbnails and titles.

NOTE: TubeBuddy's API is available to Legend plan subscribers.
API docs: https://www.tubebuddy.com/api
Auth: API key passed as ?auth_key= query parameter.
"""
import logging
from typing import Any

import httpx

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tubebuddy.com/api"


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json"}


def _params() -> dict[str, str]:
    return {"auth_key": config.TUBEBUDDY_API_KEY}


@with_retry(max_attempts=3)
def create_thumbnail_ab_test(
    video_id: str,
    thumbnail_ids: list[str],
    rotation_hours: int = 48,
) -> dict[str, Any]:
    """
    Create a thumbnail A/B test for the given video.
    thumbnail_ids: list of Drive/YouTube thumbnail IDs (A, B, C).
    Returns the TubeBuddy test response.
    """
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would create thumbnail A/B test for video %s", video_id)
        return {"test_id": "dry-run-test-id", "status": "created"}

    payload = {
        "video_id": video_id,
        "test_type": "thumbnail",
        "variants": [
            {"label": label, "thumbnail_id": tid}
            for label, tid in zip(["A", "B", "C"], thumbnail_ids)
        ],
        "rotation_hours": rotation_hours,
    }
    resp = httpx.post(
        f"{BASE_URL}/abtest/create",
        params=_params(),
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    logger.info("Thumbnail A/B test created for video %s: %s", video_id, result)
    return result


@with_retry(max_attempts=3)
def create_title_ab_test(
    video_id: str,
    titles: list[str],
    rotation_hours: int = 72,
) -> dict[str, Any]:
    """
    Create a title A/B test for the given video.
    titles: [title_a, title_b, title_c]
    """
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would create title A/B test for video %s", video_id)
        return {"test_id": "dry-run-title-test-id", "status": "created"}

    payload = {
        "video_id": video_id,
        "test_type": "title",
        "variants": [
            {"label": label, "title": title}
            for label, title in zip(["A", "B", "C"], titles)
        ],
        "rotation_hours": rotation_hours,
    }
    resp = httpx.post(
        f"{BASE_URL}/abtest/create",
        params=_params(),
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    logger.info("Title A/B test created for video %s: %s", video_id, result)
    return result


@with_retry(max_attempts=3)
def get_ab_test_results(video_id: str) -> list[dict[str, Any]]:
    """Return all active A/B test results for a video."""
    resp = httpx.get(
        f"{BASE_URL}/abtest/results",
        params={**_params(), "video_id": video_id},
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


@with_retry(max_attempts=3)
def end_ab_test(test_id: str, winning_variant: str) -> dict[str, Any]:
    """End an A/B test and declare a winner."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would end test %s, winner=%s", test_id, winning_variant)
        return {"status": "ended"}

    resp = httpx.post(
        f"{BASE_URL}/abtest/end",
        params=_params(),
        headers=_headers(),
        json={"test_id": test_id, "winner": winning_variant},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
