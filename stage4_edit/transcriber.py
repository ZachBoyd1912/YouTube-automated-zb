"""
Download raw .mp4 from Drive, extract audio, transcribe with Whisper API (word-level timestamps).
"""
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from shared import config, drive_client
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    """Extract mono 16kHz audio from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-ar", "16000",
        "-ac", "1",
        "-f", "mp3",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed:\n{result.stderr}")
    logger.info("Extracted audio to %s", audio_path)
    return audio_path


@with_retry(max_attempts=3)
def transcribe_audio(audio_path: Path) -> dict[str, Any]:
    """
    Send audio to Whisper API with word-level timestamps.
    Returns the full verbose_json response dict.
    """
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    with open(audio_path, "rb") as f:
        resp = httpx.post(
            url,
            headers=headers,
            data={
                "model": "whisper-1",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "word",
            },
            files={"file": (audio_path.name, f, "audio/mpeg")},
            timeout=300,
        )
    resp.raise_for_status()
    data = resp.json()
    logger.info("Transcription complete, %d words", len(data.get("words", [])))
    return data


def transcribe_video(file_id: str, date_str: str) -> tuple[dict[str, Any], Path]:
    """
    Full pipeline: download from Drive → extract audio → transcribe.

    Returns:
        (transcript_dict, local_video_path)
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="yt-pipeline-"))
    video_path = tmp_dir / f"raw_{date_str}.mp4"
    audio_path = tmp_dir / f"audio_{date_str}.mp3"

    logger.info("Downloading raw video from Drive (file_id=%s)", file_id)
    drive_client.download_file(file_id, video_path)

    extract_audio(video_path, audio_path)
    transcript = transcribe_audio(audio_path)

    return transcript, video_path
