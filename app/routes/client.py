import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import settings
from app.database import get_db, AsyncSessionLocal
from app.models import Team, ImageDispatch, Submission, SystemSetting, utc_now
from app.security import get_current_team
from app.storage import storage_manager

router = APIRouter(prefix="/api/v1", tags=["Client API"])


class SubmissionPayload(BaseModel):
    img_id: str = Field(..., description="The img_id received in X-Image-ID header during image download")
    predictions: Any = Field(..., description="Any valid JSON object or list representing model predictions")


async def get_system_mode(db: AsyncSession) -> str:
    """Read the active global competition mode."""
    stmt = select(SystemSetting).where(SystemSetting.key == "global_mode")
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    return setting.value if setting else settings.DEFAULT_GLOBAL_MODE


@router.get("/image")
async def get_image(
    mode: Optional[Literal["train", "test"]] = Query(
        None,
        description="Optional mode: 'train' or 'test'. If omitted, automatically adopts current server mode."
    ),
    team: Team = Depends(get_current_team),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch an image for evaluation.
    Returns binary image stream with 'X-Image-ID' in the response header.
    Accurately records the timestamp when transmission finishes.
    """
    global_mode = await get_system_mode(db)
    if global_mode == "paused":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The competition server is currently paused by admin."
        )

    # Auto-resolve mode if client did not specify
    if not mode:
        if global_mode == "test":
            mode = "test"
        else:
            mode = "train"

    if global_mode == "train" and mode == "test":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test mode is not currently enabled. Global mode is set to 'train' only."
        )
    elif global_mode == "test" and mode == "train":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Train mode is concluded. Global mode is set to 'test' only."
        )

    # In test mode, enforce quota
    if mode == "test":
        count_stmt = select(func.count(ImageDispatch.id)).where(
            ImageDispatch.team_id == team.id,
            ImageDispatch.mode == "test"
        )
        count_res = await db.execute(count_stmt)
        dispatched_count = count_res.scalar() or 0

        if dispatched_count >= team.test_quota_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Test quota exceeded! Your team has used {dispatched_count}/{team.test_quota_limit} test attempts."
            )

    # 1. Pick an image
    file_name, file_path, content_type = storage_manager.get_image_info(mode)
    img_id = f"img_{uuid.uuid4().hex[:16]}"
    dispatch_id = str(uuid.uuid4())

    # 2. Record initial dispatch
    dispatch = ImageDispatch(
        id=dispatch_id,
        team_id=team.id,
        img_id=img_id,
        file_name=file_name,
        mode=mode,
        dispatched_at=utc_now()
    )
    db.add(dispatch)
    await db.commit()

    # 3. Stream generator that hooks into completion
    async def stream_and_record():
        try:
            async for chunk in storage_manager.stream_file_chunks(file_path):
                yield chunk
        finally:
            # Generator finishes when socket closes or all chunks are delivered
            finished_at = utc_now()
            try:
                async with AsyncSessionLocal() as session:
                    stmt = select(ImageDispatch).where(ImageDispatch.id == dispatch_id)
                    res = await session.execute(stmt)
                    row = res.scalar_one_or_none()
                    if row:
                        row.finished_send_at = finished_at
                        await session.commit()
            except Exception as e:
                print(f"[Error] Failed to log dispatch completion timestamp: {e}")

    headers = {
        "X-Image-ID": img_id,
        "X-Image-Name": file_name,
        "X-Mode": mode,
        "Content-Disposition": f'inline; filename="{file_name}"',
        "Access-Control-Expose-Headers": "X-Image-ID, X-Image-Name, X-Mode, Content-Disposition"
    }

    return StreamingResponse(
        stream_and_record(),
        media_type=content_type,
        headers=headers
    )


@router.post("/submit")
async def submit_prediction(
    request: Request,
    team: Team = Depends(get_current_team),
    db: AsyncSession = Depends(get_db),
    x_image_id: Optional[str] = Header(None, alias="X-Image-ID")
):
    """
    Submit prediction JSON for a previously downloaded image.
    Accepts single-image ground_truth format or standard {img_id, predictions}.
    Records receipt timestamp, calculates exact round-trip latency, and guarantees zero data loss.
    """
    arrival_time = utc_now()

    try:
        raw_payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON format in request body."
        )

    # 1. Resolve img_id from payload, header, or image_name
    img_id = None
    if isinstance(raw_payload, dict):
        img_id = raw_payload.get("img_id")
        if not img_id and "predictions" in raw_payload and isinstance(raw_payload["predictions"], dict):
            img_id = raw_payload["predictions"].get("img_id")
    elif isinstance(raw_payload, list) and len(raw_payload) > 0 and isinstance(raw_payload[0], dict):
        img_id = raw_payload[0].get("img_id")

    if not img_id and x_image_id:
        img_id = x_image_id.strip()

    # Look up dispatch record
    dispatch = None
    if img_id:
        stmt = (
            select(ImageDispatch)
            .where(
                ImageDispatch.team_id == team.id,
                ImageDispatch.img_id == img_id
            )
            .order_by(ImageDispatch.dispatched_at.desc())
        )
        res = await db.execute(stmt)
        dispatch = res.scalar_one_or_none()
    else:
        # Fallback: check if image_name is provided in the JSON (e.g. {"image_name": "Parchment_test.jpg", ...})
        img_name = None
        if isinstance(raw_payload, dict):
            img_name = raw_payload.get("image_name")
        elif isinstance(raw_payload, list) and len(raw_payload) > 0 and isinstance(raw_payload[0], dict):
            img_name = raw_payload[0].get("image_name")

        if img_name:
            stmt = (
                select(ImageDispatch)
                .where(
                    ImageDispatch.team_id == team.id,
                    ImageDispatch.file_name == img_name
                )
                .order_by(ImageDispatch.dispatched_at.desc())
            )
            res = await db.execute(stmt)
            dispatch = res.scalar_one_or_none()
            if dispatch:
                img_id = dispatch.img_id

    if not dispatch or not img_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not match submission to an image request. Provide 'img_id' in body or via 'X-Image-ID' header."
        )

    # 2. Prevent duplicate submissions for the same image
    existing_stmt = select(Submission).where(
        Submission.team_id == team.id,
        Submission.img_id == img_id
    )
    existing_res = await db.execute(existing_stmt)
    if existing_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A submission for img_id '{img_id}' has already been accepted."
        )

    # 3. Calculate latency from when image finished sending
    baseline_time = dispatch.finished_send_at or dispatch.dispatched_at
    if baseline_time and baseline_time.tzinfo is None:
        baseline_time = baseline_time.replace(tzinfo=timezone.utc)
    duration_seconds = (arrival_time - baseline_time).total_seconds() if baseline_time else 0.0

    if settings.MAX_SUBMISSION_WINDOW_SECONDS > 0:
        if duration_seconds > settings.MAX_SUBMISSION_WINDOW_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail=f"Submission rejected: took {duration_seconds:.1f}s, maximum allowed is {settings.MAX_SUBMISSION_WINDOW_SECONDS}s."
            )

    # 4. Hash payload for immutability check
    serialized_payload = json.dumps(raw_payload, sort_keys=True)
    payload_hash = hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()

    # 5. Persist to storage (Local file + S3 backup)
    timestamp_tag = arrival_time.strftime("%Y%m%d_%H%M%S_%f")
    storage_path = await storage_manager.save_submission(
        mode=dispatch.mode,
        team_name=team.name,
        img_id=img_id,
        timestamp_str=timestamp_tag,
        payload=raw_payload
    )

    # 6. Save directly to DB JSONB column (guarantees zero data loss)
    submission = Submission(
        team_id=team.id,
        dispatch_id=dispatch.id,
        img_id=img_id,
        mode=dispatch.mode,
        received_at=arrival_time,
        duration_seconds=round(duration_seconds, 4),
        json_payload=raw_payload,
        payload_sha256=payload_hash,
        s3_backup_path=storage_path
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    return {
        "status": "success",
        "message": "Submission recorded successfully",
        "img_id": img_id,
        "image_name": dispatch.file_name,
        "mode": dispatch.mode,
        "duration_seconds": round(duration_seconds, 3),
        "received_at": arrival_time.isoformat()
    }


@router.get("/stats")
async def get_team_stats(
    team: Team = Depends(get_current_team),
    db: AsyncSession = Depends(get_db)
):
    """
    Get transmission and submission statistics for the authenticated team.
    """
    # Train mode counts
    train_req_stmt = select(func.count(ImageDispatch.id)).where(
        ImageDispatch.team_id == team.id,
        ImageDispatch.mode == "train"
    )
    train_sub_stmt = select(func.count(Submission.id)).where(
        Submission.team_id == team.id,
        Submission.mode == "train"
    )

    # Test mode counts
    test_req_stmt = select(func.count(ImageDispatch.id)).where(
        ImageDispatch.team_id == team.id,
        ImageDispatch.mode == "test"
    )
    test_sub_stmt = select(func.count(Submission.id)).where(
        Submission.team_id == team.id,
        Submission.mode == "test"
    )

    train_requests = (await db.execute(train_req_stmt)).scalar() or 0
    train_submissions = (await db.execute(train_sub_stmt)).scalar() or 0
    test_requests = (await db.execute(test_req_stmt)).scalar() or 0
    test_submissions = (await db.execute(test_sub_stmt)).scalar() or 0

    remaining_test_attempts = max(0, team.test_quota_limit - test_requests)

    return {
        "team_name": team.name,
        "team_id": team.id,
        "train_mode": {
            "images_requested": train_requests,
            "submissions_received": train_submissions
        },
        "test_mode": {
            "quota_limit": team.test_quota_limit,
            "images_requested": test_requests,
            "submissions_received": test_submissions,
            "remaining_attempts": remaining_test_attempts
        }
    }
