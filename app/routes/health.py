"""Liveness and dependency checks."""

import redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.redis_client import redis_client

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> JSONResponse:
    """PostgreSQL is required (503 when down). Redis is reported but optional,
    because the rate limiter fails open and correctness lives in PostgreSQL."""
    checks: dict[str, str] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except SQLAlchemyError:
        checks["postgres"] = "down"
    try:
        redis_client.ping()
        checks["redis"] = "ok"
    except redis.RedisError:
        checks["redis"] = "down"
    healthy = checks["postgres"] == "ok"
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
