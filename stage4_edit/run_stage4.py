"""
Stage 4 — Auto-Edit
Orchestrates: download → transcribe → analyze cuts → edit → upload
"""
import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from shared import config, drive_client, sheets_client
from shared.error_handler import stage_handler
from stage4_edit import transcriber, cut_analyzer, video_editor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@stage_handler("Stage 4 — Auto-Edit")
def run(file_id: str, date_str: str | None = None) -> dict[str, Any]:
    """
    Args:
        file_id: Google Drive file ID of the raw .mp4 upload.
        date_str: ISO date string (YYYY-MM-DD). Defaults to today.
    """
    today = date_str or date.today().isoformat()
    logger.info("Stage 4 starting for date %s, file_id=%s", today, file_id)

    # Step 1: Transcribe
    transcript, video_path = transcriber.transcribe_video(file_id, today)
    duration = video_editor.get_video_duration(video_path)
    logger.info("Video duration: %.1f seconds", duration)

    # Step 2: Identify cuts
    cuts = cut_analyzer.analyze_cuts(transcript, duration)

    # Step 3: Generate SRT captions
    tmp_dir = video_path.parent
    srt_path = tmp_dir / f"captions_{today}.srt"
    video_editor.generate_srt(transcript, srt_path, cuts)

    # Step 4: Apply cuts + audio filters + captions
    edited_content_path = tmp_dir / f"edited_content_{today}.mp4"
    video_editor.apply_cuts_and_filters(video_path, edited_content_path, cuts, srt_path)

    # Step 5: Add intro + outro
    final_path = tmp_dir / f"final_{today}.mp4"
    video_editor.prepend_intro_append_outro(edited_content_path, final_path)

    # Step 6: Upload to Drive
    edited_folder_id = drive_client.get_dated_folder_id(config.DRIVE_EDITED_FOLDER, today)
    edited_file_id, edited_link = drive_client.upload_file(final_path, edited_folder_id)

    # Also upload the SRT for reference
    drive_client.upload_file(srt_path, edited_folder_id)

    # Update Sheets
    sheets_client.update_pipeline_fields(today, {
        "drive_edited": edited_link,
        "status": "edited",
    })

    logger.info("Stage 4 complete — edited file: %s", edited_link)

    # Cleanup temp files (keep the final in case caller needs it)
    for p in [video_path, tmp_dir / f"audio_{today}.mp3", edited_content_path]:
        p.unlink(missing_ok=True)

    return {
        "date": today,
        "drive_edited": edited_link,
        "edited_file_id": edited_file_id,
        "duration_original": duration,
        "cuts_applied": len(cuts),
        "transcript": transcript,
        "srt_path": str(srt_path),
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python -m stage4_edit.run_stage4 <drive_file_id> [date]")
        sys.exit(1)
    result = run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"\nEdited video: {result['drive_edited']}")
    print(f"Cuts applied: {result['cuts_applied']}")
