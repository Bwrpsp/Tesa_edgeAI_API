import csv
import io
from pathlib import Path
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import settings
from app.database import get_db
from app.models import Team, ImageDispatch, Submission, SystemSetting, utc_now
from app.security import verify_admin_key, generate_team_token, hash_token
from app.storage import storage_manager

router = APIRouter(prefix="/api/v1/admin", tags=["Admin API"], dependencies=[Depends(verify_admin_key)])


class ModeUpdate(BaseModel):
    mode: Literal["train", "test", "all", "paused"] = Field(..., description="Global competition mode")


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    test_quota_limit: Optional[int] = Field(None, ge=0)
    custom_token: Optional[str] = Field(None, description="Optional custom pre-generated token")


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    custom_token: Optional[str] = Field(None, description="New token to assign to this team")
    test_quota_limit: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class BatchTeamCreate(BaseModel):
    team_names: List[str]
    test_quota_limit: Optional[int] = Field(None, ge=0)


class TeamImportItem(BaseModel):
    name: str = Field(..., description="Team Name or ID")
    token: Optional[str] = Field(None, description="Pre-generated secret token/key")
    test_quota_limit: Optional[int] = Field(None, ge=0)


class BatchImportRequest(BaseModel):
    teams: List[TeamImportItem]
    default_quota: Optional[int] = Field(None, ge=0)


class QuotaUpdate(BaseModel):
    test_quota_limit: int = Field(..., ge=0)


@router.get("/mode")
async def get_mode(db: AsyncSession = Depends(get_db)):
    """Get the current server competition mode."""
    stmt = select(SystemSetting).where(SystemSetting.key == "global_mode")
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    current_mode = setting.value if setting else settings.DEFAULT_GLOBAL_MODE
    return {"global_mode": current_mode}


@router.post("/mode")
async def set_mode(payload: ModeUpdate, db: AsyncSession = Depends(get_db)):
    """Switch global competition mode ('train', 'test', 'all', or 'paused')."""
    stmt = select(SystemSetting).where(SystemSetting.key == "global_mode")
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    if not setting:
        setting = SystemSetting(key="global_mode", value=payload.mode)
        db.add(setting)
    else:
        setting.value = payload.mode
        setting.updated_at = utc_now()
    await db.commit()
    return {"status": "success", "global_mode": payload.mode}


@router.post("/teams")
async def create_team(payload: TeamCreate, db: AsyncSession = Depends(get_db)):
    """Create a single team (with either custom or auto-generated token)."""
    # Check if name exists
    existing_stmt = select(Team).where(Team.name == payload.name.strip())
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Team with name '{payload.name}' already exists."
        )

    raw_token = payload.custom_token.strip() if payload.custom_token and payload.custom_token.strip() else generate_team_token()
    token_h = hash_token(raw_token)

    # Check if token hash collision
    token_collision = (await db.execute(select(Team).where(Team.token_hash == token_h))).scalar_one_or_none()
    if token_collision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another team is already using this secret token. Tokens must be unique."
        )

    prefix = raw_token[:10] + "..." if len(raw_token) > 10 else raw_token
    quota = payload.test_quota_limit if payload.test_quota_limit is not None else settings.DEFAULT_TEST_QUOTA

    team = Team(
        name=payload.name.strip(),
        token_hash=token_h,
        token_prefix=prefix,
        test_quota_limit=quota
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)

    return {
        "status": "success",
        "team_id": team.id,
        "name": team.name,
        "token": raw_token,
        "token_prefix": prefix,
        "test_quota_limit": team.test_quota_limit
    }


@router.post("/teams/import")
async def import_teams(payload: BatchImportRequest, db: AsyncSession = Depends(get_db)):
    """
    Import or update a list of teams with custom pre-generated keys.
    If team name exists, updates its token and quota.
    If not, creates a new team.
    """
    results = []
    default_quota = payload.default_quota if payload.default_quota is not None else settings.DEFAULT_TEST_QUOTA

    for item in payload.teams:
        clean_name = item.name.strip()
        if not clean_name:
            continue

        raw_token = item.token.strip() if item.token and item.token.strip() else generate_team_token()
        token_h = hash_token(raw_token)
        prefix = raw_token[:10] + "..." if len(raw_token) > 10 else raw_token
        quota = item.test_quota_limit if item.test_quota_limit is not None else default_quota

        existing = (await db.execute(select(Team).where(Team.name == clean_name))).scalar_one_or_none()
        if existing:
            existing.token_hash = token_h
            existing.token_prefix = prefix
            if item.test_quota_limit is not None:
                existing.test_quota_limit = quota
            results.append({
                "team_id": existing.id,
                "name": clean_name,
                "action": "updated",
                "token": raw_token,
                "token_prefix": prefix,
                "quota": existing.test_quota_limit
            })
        else:
            team = Team(
                name=clean_name,
                token_hash=token_h,
                token_prefix=prefix,
                test_quota_limit=quota
            )
            db.add(team)
            results.append({
                "team_id": team.id,
                "name": clean_name,
                "action": "created",
                "token": raw_token,
                "token_prefix": prefix,
                "quota": quota
            })

    await db.commit()
    return {"total": len(results), "teams": results}


@router.post("/teams/batch")
async def batch_create_teams(payload: BatchTeamCreate, db: AsyncSession = Depends(get_db)):
    """Batch generate multiple teams with auto-generated tokens."""
    results = []
    quota = payload.test_quota_limit if payload.test_quota_limit is not None else settings.DEFAULT_TEST_QUOTA

    for name in payload.team_names:
        clean_name = name.strip()
        if not clean_name:
            continue

        existing_stmt = select(Team).where(Team.name == clean_name)
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing:
            results.append({"name": clean_name, "status": "skipped", "reason": "Already exists"})
            continue

        raw_token = generate_team_token()
        token_h = hash_token(raw_token)
        prefix = raw_token[:10] + "..."

        team = Team(
            name=clean_name,
            token_hash=token_h,
            token_prefix=prefix,
            test_quota_limit=quota
        )
        db.add(team)
        results.append({
            "name": clean_name,
            "status": "created",
            "token": raw_token,
            "token_prefix": prefix,
            "test_quota_limit": quota
        })

    await db.commit()
    return {"total": len(results), "teams": results}


@router.get("/teams")
async def list_teams(db: AsyncSession = Depends(get_db)):
    """List all registered teams."""
    stmt = select(Team).order_by(Team.created_at.asc())
    teams = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "token_prefix": t.token_prefix,
            "test_quota_limit": t.test_quota_limit,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }
        for t in teams
    ]


@router.post("/teams/{team_id}/edit")
async def edit_team(team_id: str, payload: TeamUpdate, db: AsyncSession = Depends(get_db)):
    """Edit any property of a team: change name, overwrite token/key, update quota, toggle active."""
    stmt = select(Team).where(Team.id == team_id)
    team = (await db.execute(stmt)).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    if payload.name and payload.name.strip() != team.name:
        clean_name = payload.name.strip()
        name_check = (await db.execute(select(Team).where(Team.name == clean_name, Team.id != team_id))).scalar_one_or_none()
        if name_check:
            raise HTTPException(status_code=409, detail=f"Another team is already named '{clean_name}'.")
        team.name = clean_name

    if payload.custom_token and payload.custom_token.strip():
        new_token = payload.custom_token.strip()
        new_h = hash_token(new_token)
        token_check = (await db.execute(select(Team).where(Team.token_hash == new_h, Team.id != team_id))).scalar_one_or_none()
        if token_check:
            raise HTTPException(status_code=409, detail="Another team is already using this secret token.")
        team.token_hash = new_h
        team.token_prefix = new_token[:10] + "..." if len(new_token) > 10 else new_token

    if payload.test_quota_limit is not None:
        team.test_quota_limit = payload.test_quota_limit

    if payload.is_active is not None:
        team.is_active = payload.is_active

    await db.commit()
    await db.refresh(team)

    return {
        "status": "success",
        "team_id": team.id,
        "name": team.name,
        "token_prefix": team.token_prefix,
        "test_quota_limit": team.test_quota_limit,
        "is_active": team.is_active
    }


@router.post("/teams/{team_id}/quota")
async def update_team_quota(team_id: str, payload: QuotaUpdate, db: AsyncSession = Depends(get_db)):
    """Update a specific team's test quota limit."""
    stmt = select(Team).where(Team.id == team_id)
    team = (await db.execute(stmt)).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    team.test_quota_limit = payload.test_quota_limit
    await db.commit()
    return {"status": "success", "team_id": team.id, "new_quota": team.test_quota_limit}


@router.post("/teams/{team_id}/toggle-active")
async def toggle_team_active(team_id: str, db: AsyncSession = Depends(get_db)):
    """Toggle a team between active and deactivated."""
    stmt = select(Team).where(Team.id == team_id)
    team = (await db.execute(stmt)).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    team.is_active = not team.is_active
    await db.commit()
    return {"status": "success", "team_id": team.id, "is_active": team.is_active}


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a team and its associated records."""
    stmt = select(Team).where(Team.id == team_id)
    team = (await db.execute(stmt)).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    await db.delete(team)
    await db.commit()
    return {"status": "success", "message": f"Team '{team.name}' deleted."}


@router.get("/stats")
async def get_all_team_stats(db: AsyncSession = Depends(get_db)):
    """Summary overview of all teams: dispatches, submissions, remaining quota, average latency."""
    teams_stmt = select(Team).order_by(Team.name.asc())
    teams = (await db.execute(teams_stmt)).scalars().all()

    stats_list = []
    for t in teams:
        tr_req = (await db.execute(
            select(func.count(ImageDispatch.id)).where(ImageDispatch.team_id == t.id, ImageDispatch.mode == "train")
        )).scalar() or 0
        tr_sub = (await db.execute(
            select(func.count(Submission.id)).where(Submission.team_id == t.id, Submission.mode == "train")
        )).scalar() or 0

        te_req = (await db.execute(
            select(func.count(ImageDispatch.id)).where(ImageDispatch.team_id == t.id, ImageDispatch.mode == "test")
        )).scalar() or 0
        te_sub = (await db.execute(
            select(func.count(Submission.id)).where(Submission.team_id == t.id, Submission.mode == "test")
        )).scalar() or 0

        avg_dur = (await db.execute(
            select(func.avg(Submission.duration_seconds)).where(Submission.team_id == t.id)
        )).scalar()

        stats_list.append({
            "team_id": t.id,
            "team_name": t.name,
            "token_prefix": t.token_prefix,
            "is_active": t.is_active,
            "train_dispatches": tr_req,
            "train_submissions": tr_sub,
            "test_quota_limit": t.test_quota_limit,
            "test_dispatches": te_req,
            "test_submissions": te_sub,
            "test_remaining": max(0, t.test_quota_limit - te_req),
            "avg_duration_sec": round(avg_dur, 2) if avg_dur is not None else None
        })

    return stats_list


async def generate_mode_csv(db: AsyncSession, mode: str) -> str:
    """Generate a detailed CSV log of all submissions for the given mode."""
    stmt = (
        select(Submission, Team, ImageDispatch)
        .join(Team, Submission.team_id == Team.id)
        .outerjoin(ImageDispatch, Submission.dispatch_id == ImageDispatch.id)
        .where(Submission.mode == mode)
        .order_by(Team.name.asc(), Submission.received_at.asc())
    )
    result = await db.execute(stmt)
    records = result.all()

    # Pass 1: Determine the latest submission per (team, img_name) and per team overall
    latest_per_img = {}
    latest_per_team = {}
    for sub, team, dispatch in records:
        img_name = dispatch.file_name if dispatch and dispatch.file_name else "unknown"
        if (not img_name or img_name == "unknown") and isinstance(sub.json_payload, dict):
            img_name = sub.json_payload.get("image_name", "unknown")

        key_img = (team.id, img_name)
        if key_img not in latest_per_img or sub.received_at > latest_per_img[key_img]:
            latest_per_img[key_img] = sub.received_at

        if team.id not in latest_per_team or sub.received_at > latest_per_team[team.id]:
            latest_per_team[team.id] = sub.received_at

    # Pass 2: Output CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "team_id",
        "team_name",
        "img_id",
        "img_name",
        "time_stamp_get_pic",
        "time_stamp_return_",
        "duration_seconds",
        "file_path",
        "is_final",
        "is_team_latest",
        "payload_sha256"
    ])

    for sub, team, dispatch in records:
        img_name = dispatch.file_name if dispatch and dispatch.file_name else "unknown"
        if (not img_name or img_name == "unknown") and isinstance(sub.json_payload, dict):
            img_name = sub.json_payload.get("image_name", "unknown")

        safe_team = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in team.name)
        team_folder = storage_manager.local_submission_dir / mode / safe_team
        matched_files = list(team_folder.glob(f"{sub.img_id}_*.json")) if team_folder.exists() else []
        if matched_files:
            file_rel = f"submissions/{mode}/{safe_team}/{matched_files[0].name}"
        else:
            file_rel = f"submissions/{mode}/{safe_team}/{sub.img_id}.json"

        time_get = ""
        if dispatch:
            dt = dispatch.finished_send_at or dispatch.dispatched_at
            if dt:
                time_get = dt.isoformat()

        time_return = sub.received_at.isoformat() if sub.received_at else ""
        is_final = (sub.received_at == latest_per_img.get((team.id, img_name)))
        is_team_latest = (sub.received_at == latest_per_team.get(team.id))

        writer.writerow([
            team.id,
            team.name,
            sub.img_id,
            img_name,
            time_get,
            time_return,
            sub.duration_seconds if sub.duration_seconds is not None else "",
            file_rel,
            is_final,
            is_team_latest,
            sub.payload_sha256 or ""
        ])

    return output.getvalue()


@router.get("/export/csv")
async def export_mode_csv(
    mode: Literal["train", "test"] = Query("test", description="Mode to export: 'train' or 'test'"),
    db: AsyncSession = Depends(get_db)
):
    """Download standalone manifest CSV for train or test mode."""
    csv_content = await generate_mode_csv(db, mode)
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{mode}_manifest.csv"'}
    )


@router.get("/export")
async def export_all_submissions(db: AsyncSession = Depends(get_db)):
    """Download all submitted predictions packaged in a zip archive with train and test CSV manifests."""
    train_csv = await generate_mode_csv(db, "train")
    test_csv = await generate_mode_csv(db, "test")
    zip_stream = storage_manager.build_export_zip(train_csv=train_csv, test_csv=test_csv)
    return StreamingResponse(
        zip_stream,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": 'attachment; filename="topgun_submissions_export.zip"'}
    )
