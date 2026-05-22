"""
Stage 2 — WhatsApp Brief to Zach
Formats the daily video brief and sends it via Twilio WhatsApp.
"""
import logging
from datetime import date
from typing import Any

from shared import config, drive_client, sheets_client, whatsapp_client
from shared.error_handler import stage_handler

logger = logging.getLogger(__name__)

MESSAGE_TEMPLATE = """\
🎬 *Today's Video Brief*

📌 *Topic:* {topic}
🎯 *Angle:* {angle}
⏱ *Est. recording time:* {estimated_duration} minutes

---
📝 *SCRIPT:*

{script}

---
🎥 *SHOT LIST:*

{shot_list}

---
📁 Upload your raw .mp4 to:
{drive_link}
"""


@stage_handler("Stage 2 — WhatsApp Brief")
def send_brief(row: dict[str, Any] | None = None, for_date: str | None = None) -> str:
    """
    Send today's video brief to Zach via WhatsApp.

    Args:
        row: Pre-loaded pipeline row dict (from Stage 1, if chaining in-process).
        for_date: ISO date string to look up in Sheets (used when called independently).

    Returns:
        Twilio message SID.
    """
    if row is None:
        target_date = for_date or date.today().isoformat()
        row = sheets_client.get_pipeline_row(target_date)
        if row is None:
            raise ValueError(f"No pipeline row found for date {target_date}")

    today_str = row.get("date", date.today().isoformat())

    # Ensure the dated upload folder exists and get its link
    folder_id = drive_client.get_dated_folder_id(config.DRIVE_UPLOADS_FOLDER, today_str)
    drive_link = drive_client.get_folder_web_link(folder_id)

    message = MESSAGE_TEMPLATE.format(
        topic=row["topic"],
        angle=row["angle"],
        estimated_duration=row.get("estimated_duration", "4"),
        script=row["script"],
        shot_list=row["shot_list"],
        drive_link=drive_link,
    )

    sid = whatsapp_client.send_whatsapp(message)
    logger.info("Brief sent to Zach, SID=%s", sid)
    return sid


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    send_brief(for_date=target)
