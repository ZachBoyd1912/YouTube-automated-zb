import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Required environment variable {key!r} is not set")
    return val


# API Keys
OPENROUTER_API_KEY: str = _require("OPENROUTER_API_KEY")
OPENAI_API_KEY: str = _require("OPENAI_API_KEY")   # DALL-E 3 only
GROQ_API_KEY: str = _require("GROQ_API_KEY")        # Whisper transcription
NEXLEV_API_KEY: str = _require("NEXLEV_API_KEY")
TUBEBUDDY_API_KEY: str = _require("TUBEBUDDY_API_KEY")
TWILIO_ACCOUNT_SID: str = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN: str = _require("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM: str = _require("TWILIO_WHATSAPP_FROM")
ZACH_WHATSAPP_NUMBER: str = _require("ZACH_WHATSAPP_NUMBER")
BUFFER_ACCESS_TOKEN: str = os.getenv("BUFFER_ACCESS_TOKEN", "")
API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "change-this-to-a-random-secret")

# Google
GOOGLE_CLIENT_ID: str = _require("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET: str = _require("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN: str = _require("GOOGLE_REFRESH_TOKEN")
GOOGLE_DRIVE_ROOT_FOLDER_ID: str = _require("GOOGLE_DRIVE_ROOT_FOLDER_ID")
GOOGLE_SHEETS_ID: str = _require("GOOGLE_SHEETS_ID")

# LLM (DeepSeek via OpenRouter)
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek/deepseek-chat:free")

# NexLev
NEXLEV_BASE_URL: str = os.getenv("NEXLEV_BASE_URL", "https://app.nexlev.io/api")
NEXLEV_NICHE: str = "AI tools for small businesses"

# Google Drive folder names (children of GOOGLE_DRIVE_ROOT_FOLDER_ID)
DRIVE_UPLOADS_FOLDER = "uploads"
DRIVE_EDITED_FOLDER = "edited"
DRIVE_THUMBNAILS_FOLDER = "thumbnails"
DRIVE_SHORTS_FOLDER = "shorts"
DRIVE_BRIEFS_FOLDER = "briefs"
DRIVE_ASSETS_FOLDER = "assets"

# Google Sheets tab names
PIPELINE_SHEET_NAME = "pipeline"
ANALYTICS_SHEET_NAME = "analytics"

# Column order in the pipeline sheet (must match the actual sheet headers)
PIPELINE_COLUMNS = [
    "date",
    "topic",
    "angle",
    "script",
    "shot_list",
    "title_a",
    "title_b",
    "title_c",
    "thumbnail_brief",
    "estimated_duration",
    "drive_raw",
    "drive_edited",
    "drive_thumbnails",
    "youtube_id",
    "shorts_id",
    "status",
    "ab_winner_thumb",
    "ab_winner_title",
    "views_7d",
    "ctr",
    "avg_view_duration",
]

# YouTube publishing schedule
YOUTUBE_PLAYLIST_NAME = "AI Tools for Business"
YOUTUBE_CATEGORY_ID = "28"  # Science & Technology
PUBLISH_WEEKDAY = 3  # Thursday (0=Monday)
PUBLISH_HOUR = 17
SHORTS_PUBLISH_WEEKDAY = 4  # Friday
SHORTS_PUBLISH_HOUR = 12
TIMEZONE = "Europe/Dublin"

# Video editing thresholds
SILENCE_THRESHOLD_SECONDS = 1.5
FILLER_WORDS = [
    "um", "uh", "like", "you know", "basically",
    "sort of", "kind of", "right", "so", "actually",
]

# Script validation
SCRIPT_WORD_COUNT_MIN = 550
SCRIPT_WORD_COUNT_MAX = 650
TITLE_MAX_CHARS = 70
DESCRIPTION_WORD_COUNT_MIN = 300
DESCRIPTION_WORD_COUNT_MAX = 400
SEO_TAG_COUNT = 15

# Shorts clip
SHORTS_MIN_DURATION_SECONDS = 45
SHORTS_MAX_DURATION_SECONDS = 60

# Testing
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"
