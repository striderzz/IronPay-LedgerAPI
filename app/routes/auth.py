"""Registration, login (JWT access tokens) and the current user."""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.deps import current_user
from app.models import User
from app.problems import ProblemError
from app.ratelimit import enforce
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, session: Session = Depends(get_session)) -> User:
    user = User(
        id=uuid.uuid4(), email=body.email.lower(), password_hash=hash_password(body.password)
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ProblemError(409, "email already registered") from None
    audit.record(
        session,
        actor_id=user.id,
        action="user.register",
        entity_type="user",
        entity_id=str(user.id),
    )
    session.commit()
    return user


@router.post("/token", response_model=TokenOut)
def token(body: LoginIn, request: Request, session: Session = Depends(get_session)) -> TokenOut:
    """Exchange email and password for a short-lived access token.
    Rate limited per client IP to slow down password guessing."""
    s = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    enforce("login", client_ip, rate=s.login_rate_per_sec, burst=s.login_burst)

    user = session.execute(
        select(User).where(User.email == body.email.lower())
    ).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else None)
    audit.record(
        session,
        actor_id=user.id if ok else None,
        action="auth.login" if ok else "auth.login_failed",
        entity_type="user",
        entity_id=str(user.id) if user else "unknown",
    )
    session.commit()
    if not ok:
        raise ProblemError(401, "wrong email or password", headers={"WWW-Authenticate": "Bearer"})
    return TokenOut(
        access_token=create_access_token(user.id),
        expires_in=s.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
