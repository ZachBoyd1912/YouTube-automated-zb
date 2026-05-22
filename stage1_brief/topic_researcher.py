"""
Calls the NexLev API to find trending topics in the AI-tools-for-small-businesses niche.

NexLev REST API base: https://app.nexlev.io/api
Auth: Bearer token via NEXLEV_API_KEY

NOTE: Verify the exact endpoint paths against NexLev's official API docs if any
      calls return 404. The paths below are inferred from NexLev's MCP tool names.
"""
import logging
from typing import Any

import httpx

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)


class NexLevClient:
    def __init__(self) -> None:
        self.base_url = config.NEXLEV_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {config.NEXLEV_API_KEY}",
            "Content-Type": "application/json",
        }

    @with_retry()
    def search_videos(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        resp = httpx.get(
            f"{self.base_url}/videos/search",
            params={"q": query, "limit": limit},
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", data) if isinstance(data, dict) else data

    @with_retry()
    def get_niche_overview(self, niche: str) -> dict[str, Any]:
        resp = httpx.get(
            f"{self.base_url}/niche/overview",
            params={"niche": niche},
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @with_retry()
    def get_trending_topics(self, niche: str, limit: int = 10) -> list[dict[str, Any]]:
        """Pull the top trending video topics for a niche (last 7 days)."""
        resp = httpx.get(
            f"{self.base_url}/niche/trending",
            params={"niche": niche, "days": 7, "limit": limit},
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("topics", data.get("results", data)) if isinstance(data, dict) else data


def get_candidate_topics(recent_topics: list[str]) -> list[dict[str, Any]]:
    """
    Pull NexLev data for the target niche and return a list of candidate topic dicts.
    Each dict has: title, angle_hint, views_7d, engagement_score, channel_count.
    """
    client = NexLevClient()
    niche = config.NEXLEV_NICHE

    # Broad trending search
    try:
        trending = client.get_trending_topics(niche, limit=15)
    except Exception:
        logger.warning("NexLev trending endpoint failed, falling back to video search")
        trending = []

    # Keyword search for recent high-performing videos
    try:
        search_results = client.search_videos(niche, limit=20)
    except Exception as exc:
        logger.error("NexLev video search failed: %s", exc)
        search_results = []

    # Niche overview for context (RPM, sub-niche data)
    try:
        overview = client.get_niche_overview(niche)
    except Exception as exc:
        logger.warning("NexLev niche overview failed: %s", exc)
        overview = {}

    candidates = _normalise_results(trending, search_results, overview)
    candidates = _deduplicate(candidates, recent_topics)
    logger.info("Got %d candidate topics after deduplication", len(candidates))
    return candidates[:12]


def _normalise_results(
    trending: list[dict],
    search_results: list[dict],
    overview: dict,
) -> list[dict[str, Any]]:
    """Normalise mixed NexLev response shapes into a consistent list."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def add(item: dict) -> None:
        title = (
            item.get("title")
            or item.get("video_title")
            or item.get("name")
            or item.get("topic")
            or ""
        ).strip()
        if not title or title.lower() in seen:
            return
        seen.add(title.lower())
        out.append({
            "title": title,
            "angle_hint": item.get("angle") or item.get("description") or "",
            "views_7d": item.get("views_7d") or item.get("views") or 0,
            "engagement_score": item.get("engagement_score") or item.get("outlier_score") or 0,
            "channel_count": item.get("channel_count") or 0,
            "rpm_estimate": item.get("rpm") or overview.get("avg_rpm") or 0,
        })

    for item in trending:
        add(item)
    for item in search_results:
        add(item)

    return out


def _deduplicate(candidates: list[dict], recent_topics: list[str]) -> list[dict]:
    """Remove topics too similar to recently published ones."""
    recent_lower = {t.lower() for t in recent_topics}
    return [
        c for c in candidates
        if not any(
            _topic_overlap(c["title"].lower(), r) for r in recent_lower
        )
    ]


def _topic_overlap(a: str, b: str) -> bool:
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    return overlap > 0.6
