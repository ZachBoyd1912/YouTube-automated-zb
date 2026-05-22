"""
FastAPI server — Make.com calls these HTTP endpoints to trigger each pipeline stage.
All endpoints require an Authorization: Bearer <API_SECRET_KEY> header.
"""
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube Pipeline API", version="1.0.0")


# ─── Auth ────────────────────────────────────────────────────────────────────

def verify_token(authorization: str = Header(...)) -> None:
    expected = f"Bearer {config.API_SECRET_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ─── Request / Response models ────────────────────────────────────────────────

class Stage1Request(BaseModel):
    date: str | None = None  # ISO date, defaults to today


class Stage2Request(BaseModel):
    date: str | None = None


class Stage4Request(BaseModel):
    file_id: str        # Google Drive file ID of the raw .mp4
    date: str | None = None


class Stage5Request(BaseModel):
    date: str | None = None
    edited_video_local_path: str | None = None
    # transcript and srt_path are omitted here — Stage 5 is usually called
    # independently via webhook, not chained in-process via HTTP


class Stage6Request(BaseModel):
    date: str | None = None
    # stage5_result injected via Sheets lookup when called via HTTP


class Stage7Request(BaseModel):
    pass  # No parameters needed — runs on all published videos


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/stage1")
def stage1(req: Stage1Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """Run Stage 1: Topic research → script generation → write to Sheets."""
    from stage1_brief.run_stage1 import run  # noqa: PLC0415
    try:
        result = run()
        return {"status": "ok", "data": result}
    except Exception as exc:
        logger.exception("Stage 1 failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@app.post("/stage2")
def stage2(req: Stage2Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """Run Stage 2: Send WhatsApp brief to Zach."""
    from stage2_whatsapp.send_brief import send_brief  # noqa: PLC0415
    try:
        sid = send_brief(for_date=req.date)
        return {"status": "ok", "data": {"whatsapp_sid": sid}}
    except Exception as exc:
        logger.exception("Stage 2 failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@app.post("/stage1_and_2")
def stage1_and_2(req: Stage1Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """Run Stage 1 then Stage 2 in sequence (used by the daily brief Make.com scenario)."""
    from stage1_brief.run_stage1 import run as run_stage1  # noqa: PLC0415
    from stage2_whatsapp.send_brief import send_brief  # noqa: PLC0415
    try:
        row = run_stage1()
        sid = send_brief(row=row)
        return {"status": "ok", "data": {"row": row, "whatsapp_sid": sid}}
    except Exception as exc:
        logger.exception("Stage 1+2 failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@app.post("/stage4")
def stage4(req: Stage4Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """Run Stage 4: Auto-edit pipeline (triggered by Drive file upload)."""
    from stage4_edit.run_stage4 import run  # noqa: PLC0415
    try:
        result = run(file_id=req.file_id, date_str=req.date)
        # Return serialisable subset (transcript is large)
        return {"status": "ok", "data": {
            "date": result["date"],
            "drive_edited": result["drive_edited"],
            "edited_file_id": result["edited_file_id"],
            "duration_original": result["duration_original"],
            "cuts_applied": result["cuts_applied"],
            "srt_path": result["srt_path"],
        }}
    except Exception as exc:
        logger.exception("Stage 4 failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@app.post("/stage5")
def stage5(req: Stage5Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """Run Stage 5: Asset generation (thumbnails, metadata, shorts)."""
    from stage5_assets.run_stage5 import run  # noqa: PLC0415
    try:
        result = run(
            date_str=req.date,
            edited_video_local_path=req.edited_video_local_path,
        )
        return {"status": "ok", "data": result}
    except Exception as exc:
        logger.exception("Stage 5 failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@app.post("/stage6")
def stage6(req: Stage6Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """Run Stage 6: Upload to YouTube and schedule."""
    from stage6_upload.run_stage6 import run  # noqa: PLC0415
    try:
        result = run(date_str=req.date)
        return {"status": "ok", "data": result}
    except Exception as exc:
        logger.exception("Stage 6 failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})


@app.post("/stage7")
def stage7(_req: Stage7Request, _: None = Depends(verify_token)) -> dict[str, Any]:
    """Run Stage 7: Weekly analytics pull, A/B resolution, WhatsApp report."""
    from stage7_analytics.run_stage7 import run  # noqa: PLC0415
    try:
        result = run()
        return {"status": "ok", "data": result.get("summary", {})}
    except Exception as exc:
        logger.exception("Stage 7 failed")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})
