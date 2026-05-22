import logging
from datetime import date
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from shared import config
from shared.error_handler import with_retry

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


def _get_service():
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _date_key(d: date | str) -> str:
    return str(d) if isinstance(d, str) else d.isoformat()


@with_retry()
def get_pipeline_row(for_date: date | str) -> dict[str, Any] | None:
    """Return the pipeline row for a given date, or None if not found."""
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"{config.PIPELINE_SHEET_NAME}!A:U",
        )
        .execute()
    )
    rows = result.get("values", [])
    if not rows:
        return None

    headers = rows[0]
    target = _date_key(for_date)
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        row_dict = dict(zip(headers, padded))
        if row_dict.get("date") == target:
            return row_dict
    return None


@with_retry()
def get_recent_topics(n: int = 10) -> list[str]:
    """Return the last n topic strings from the pipeline sheet (newest first)."""
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"{config.PIPELINE_SHEET_NAME}!A:B",
        )
        .execute()
    )
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    # rows[0] is headers; topic is column B (index 1)
    topics = [r[1] for r in rows[1:] if len(r) > 1 and r[1]]
    return topics[-n:][::-1]


@with_retry()
def write_pipeline_row(row_data: dict[str, Any]) -> None:
    """Append or update a pipeline row. Matches on date column."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would write Sheets row: %s", row_data)
        return

    service = _get_service()
    for_date = _date_key(row_data.get("date", ""))

    # Check if row for this date already exists
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"{config.PIPELINE_SHEET_NAME}!A:A",
        )
        .execute()
    )
    dates = [r[0] if r else "" for r in result.get("values", [])]

    ordered = [str(row_data.get(col, "")) for col in config.PIPELINE_COLUMNS]

    if for_date in dates:
        row_num = dates.index(for_date) + 1  # 1-indexed
        range_name = f"{config.PIPELINE_SHEET_NAME}!A{row_num}"
        service.spreadsheets().values().update(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": [ordered]},
        ).execute()
        logger.info("Updated Sheets row %d for date %s", row_num, for_date)
    else:
        service.spreadsheets().values().append(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"{config.PIPELINE_SHEET_NAME}!A:A",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [ordered]},
        ).execute()
        logger.info("Appended new Sheets row for date %s", for_date)


@with_retry()
def update_pipeline_fields(for_date: date | str, fields: dict[str, Any]) -> None:
    """Update specific fields in an existing pipeline row."""
    existing = get_pipeline_row(for_date)
    if existing is None:
        raise ValueError(f"No pipeline row found for date {for_date}")
    existing.update(fields)
    existing["date"] = _date_key(for_date)
    write_pipeline_row(existing)


@with_retry()
def write_analytics_row(row_data: dict[str, Any]) -> None:
    """Append a row to the analytics tab."""
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would write analytics row: %s", row_data)
        return

    service = _get_service()
    values = [list(row_data.values())]
    service.spreadsheets().values().append(
        spreadsheetId=config.GOOGLE_SHEETS_ID,
        range=f"{config.ANALYTICS_SHEET_NAME}!A:A",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()
    logger.info("Appended analytics row")


@with_retry()
def get_all_published_video_ids() -> list[tuple[str, str]]:
    """Return list of (date, youtube_id) for all rows with a youtube_id."""
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"{config.PIPELINE_SHEET_NAME}!A:N",
        )
        .execute()
    )
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    headers = rows[0]
    out = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        d = dict(zip(headers, padded))
        if d.get("youtube_id"):
            out.append((d["date"], d["youtube_id"]))
    return out
