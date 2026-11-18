"""User registration. Tokens and login arrive with JWT auth in Phase 3."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.schemas import RegisterIn, UserOut
from app.security import hash_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, session: Session = Depends(get_session)) -> User:
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from None
    return user
