import io
import logging
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

FOLDER_MIME = "application/vnd.google-apps.folder"


def _get_service():
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


@with_retry()
def _get_or_create_folder(name: str, parent_id: str) -> str:
    """Return the folder ID for name under parent_id, creating it if needed."""
    service = _get_service()
    query = (
        f"name='{name}' and mimeType='{FOLDER_MIME}' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    result = service.files().list(q=query, fields="files(id,name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    folder = (
        service.files()
        .create(
            body={
                "name": name,
                "mimeType": FOLDER_MIME,
                "parents": [parent_id],
            },
            fields="id",
        )
        .execute()
    )
    logger.info("Created Drive folder %r (id=%s)", name, folder["id"])
    return folder["id"]


def get_folder_id(folder_name: str) -> str:
    """Get the ID of a top-level folder under the pipeline root."""
    return _get_or_create_folder(folder_name, config.GOOGLE_DRIVE_ROOT_FOLDER_ID)


def get_dated_folder_id(folder_name: str, date_str: str) -> str:
    """Get (or create) /pipeline-root/folder_name/date_str/ and return its ID."""
    parent_id = get_folder_id(folder_name)
    return _get_or_create_folder(date_str, parent_id)


@with_retry()
def upload_file(local_path: str | Path, folder_id: str, filename: str | None = None) -> tuple[str, str]:
    """Upload a file to Drive. Returns (file_id, web_view_link)."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would upload %s to folder %s", local_path, folder_id)
        return "dry-run-file-id", "https://drive.google.com/dry-run"

    service = _get_service()
    path = Path(local_path)
    name = filename or path.name
    mime_map = {
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".srt": "text/plain",
        ".pdf": "application/pdf",
    }
    mime_type = mime_map.get(path.suffix.lower(), "application/octet-stream")

    media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
    file_meta = {"name": name, "parents": [folder_id]}
    uploaded = (
        service.files()
        .create(body=file_meta, media_body=media, fields="id,webViewLink")
        .execute()
    )
    logger.info("Uploaded %s → Drive id=%s", name, uploaded["id"])
    return uploaded["id"], uploaded.get("webViewLink", "")


@with_retry()
def download_file(file_id: str, local_path: str | Path) -> Path:
    """Download a Drive file to local_path. Returns the Path."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would download file %s to %s", file_id, local_path)
        return Path(local_path)

    service = _get_service()
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    request = service.files().get_media(fileId=file_id)
    with open(path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    logger.info("Downloaded Drive file %s → %s", file_id, path)
    return path


@with_retry()
def get_file_metadata(file_id: str) -> dict:
    """Return name, size, mimeType for a Drive file."""
    service = _get_service()
    return (
        service.files()
        .get(fileId=file_id, fields="id,name,size,mimeType,webViewLink")
        .execute()
    )


@with_retry()
def get_folder_web_link(folder_id: str) -> str:
    service = _get_service()
    result = service.files().get(fileId=folder_id, fields="webViewLink").execute()
    return result.get("webViewLink", f"https://drive.google.com/drive/folders/{folder_id}")
