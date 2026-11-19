import hashlib
import secrets
from typing import Optional
from fastapi import HTTPException, Security, status, Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models import Team

security_scheme = HTTPBearer(auto_error=False)


def generate_team_token() -> str:
    """Generate a high-entropy random team token."""
    return f"tg_{secrets.token_hex(24)}"


def hash_token(raw_token: str) -> str:
    """Compute SHA-256 hash of a token for safe database storage."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


async def get_current_team(
    auth: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    x_team_token: Optional[str] = Header(None, alias="X-Team-Token"),
    db: AsyncSession = Depends(get_db)
) -> Team:
    """
    Authenticate a team using Bearer token or X-Team-Token header.
    Returns the active Team model or raises HTTP 401.
    """
    token = None
    if auth and auth.credentials:
        token = auth.credentials.strip()
    elif x_team_token:
        token = x_team_token.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token. Provide 'Authorization: Bearer <token>' or 'X-Team-Token' header."
        )

    token_h = hash_token(token)
    stmt = select(Team).where(Team.token_hash == token_h)
    result = await db.execute(stmt)
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unrecognized team token."
        )

    if not team.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This team token has been deactivated by administrator."
        )

    return team


async def verify_admin_key(
    auth: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")
) -> bool:
    """
    Authenticate an administrator using Bearer token or X-Admin-Key header.
    """
    key = None
    if auth and auth.credentials:
        key = auth.credentials.strip()
    elif x_admin_key:
        key = x_admin_key.strip()

    if not key or not secrets.compare_digest(key, settings.ADMIN_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Admin API Key."
        )

    return True
