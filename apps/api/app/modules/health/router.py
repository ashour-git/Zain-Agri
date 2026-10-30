"""Health endpoints.

/health        liveness  — process is up, must never touch the database.
/health/ready  readiness — dependencies (PostgreSQL) are reachable.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.infrastructure.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("")
async def liveness(settings: SettingsDep) -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


@router.get("/ready")
async def readiness(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness_check_failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unreachable"}

    return {"status": "ok", "database": "ok", "environment": settings.environment}
