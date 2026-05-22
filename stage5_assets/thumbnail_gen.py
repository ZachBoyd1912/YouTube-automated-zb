"""
Generate 3 thumbnail variants via DALL-E 3, resize to 1280×720, upload to Drive.
"""
import io
import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from PIL import Image

from shared import config, drive_client
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

VARIANT_SUFFIXES = [
    (
        "a",
        "High contrast YouTube thumbnail style: bold bright colours, large readable text overlay "
        "area in upper third, vibrant accent colour (red or yellow), eye-catching composition, "
        "photorealistic, 16:9 aspect ratio.",
    ),
    (
        "b",
        "Dark-toned YouTube thumbnail style: deep navy or charcoal background, glowing accent "
        "elements (cyan or orange), modern tech aesthetic, bold composition, text overlay space "
        "on left side, 16:9 aspect ratio.",
    ),
    (
        "c",
        "Clean minimal YouTube thumbnail style: white or light background, single bold focal "
        "element centred, simple colour palette (2 colours max), lots of breathing room, "
        "modern flat design, 16:9 aspect ratio.",
    ),
]


@with_retry(max_attempts=3)
def _generate_one(prompt: str, suffix: str) -> bytes:
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    full_prompt = f"{prompt}\n\n{suffix}"
    response = client.images.generate(
        model="dall-e-3",
        prompt=full_prompt,
        size="1792x1024",
        quality="hd",
        n=1,
        response_format="url",
    )
    image_url = response.data[0].url
    img_resp = httpx.get(image_url, timeout=60)
    img_resp.raise_for_status()
    return img_resp.content


def _resize_to_720p(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    img = img.resize((1280, 720), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_thumbnails(
    thumbnail_brief: str,
    date_str: str,
) -> list[tuple[str, str]]:
    """
    Generate 3 thumbnail variants, upload them to Drive.
    Returns list of (file_id, web_link) for variants A, B, C.
    """
    folder_id = drive_client.get_dated_folder_id(config.DRIVE_THUMBNAILS_FOLDER, date_str)
    results: list[tuple[str, str]] = []

    for variant_key, suffix in VARIANT_SUFFIXES:
        logger.info("Generating thumbnail variant %s", variant_key.upper())
        raw_bytes = _generate_one(thumbnail_brief, suffix)
        resized = _resize_to_720p(raw_bytes)

        tmp = tempfile.NamedTemporaryFile(
            suffix=f"_thumb_{variant_key}.png", delete=False
        )
        tmp.write(resized)
        tmp.close()
        tmp_path = Path(tmp.name)

        filename = f"thumbnail_{date_str}_{variant_key}.png"
        file_id, link = drive_client.upload_file(tmp_path, folder_id, filename)
        tmp_path.unlink(missing_ok=True)

        results.append((file_id, link))
        logger.info("Thumbnail %s uploaded → %s", variant_key.upper(), link)

    return results
