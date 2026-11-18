"""Request dependencies: the authenticated user and per-user rate limits."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import User
from app.problems import ProblemError
from app.ratelimit import enforce
from app.security import InvalidToken, decode_access_token

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    if creds is None:
        raise ProblemError(401, "missing bearer token", headers=_UNAUTHORIZED)
    try:
        user_id = decode_access_token(creds.credentials)
    except InvalidToken:
        raise ProblemError(401, "invalid or expired token", headers=_UNAUTHORIZED) from None
    user = session.get(User, user_id)
    if user is None:
        raise ProblemError(401, "invalid or expired token", headers=_UNAUTHORIZED)
    return user


def money_rate_limit(user: User = Depends(current_user)) -> User:
    """Per-user token bucket for endpoints that move money."""
    s = get_settings()
    enforce("money", str(user.id), rate=s.transfer_rate_per_sec, burst=s.transfer_burst)
    return user
