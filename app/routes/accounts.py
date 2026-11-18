"""Wallets, balances and entry history."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Account, LedgerEntry, User
from app.schemas import AccountCreate, AccountOut, EntriesPage, EntryOut
from app.services.ledger import balance

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _out(session: Session, account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        handle=account.handle,
        kind=account.kind,
        currency=account.currency,
        status=account.status,
        balance_minor=balance(session, account.id),
    )


def _get(session: Session, account_id: uuid.UUID) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    return account


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountCreate, session: Session = Depends(get_session)) -> AccountOut:
    if session.get(User, body.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    account = Account(id=uuid.uuid4(), user_id=body.user_id, handle=body.handle, kind="wallet")
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "handle already taken") from None
    session.refresh(account)
    return _out(session, account)


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: uuid.UUID, session: Session = Depends(get_session)) -> AccountOut:
    return _out(session, _get(session, account_id))


@router.get("/{account_id}/entries", response_model=EntriesPage)
def list_entries(
    account_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, description="Cursor from the previous page"),
    session: Session = Depends(get_session),
) -> EntriesPage:
    """Newest first, keyset pagination on the entry id (stable under concurrent inserts,
    and fast at any depth because it seeks the (account_id, id) index)."""
    _get(session, account_id)
    stmt = select(LedgerEntry).where(LedgerEntry.account_id == account_id)
    if before_id is not None:
        stmt = stmt.where(LedgerEntry.id < before_id)
    rows = session.execute(stmt.order_by(LedgerEntry.id.desc()).limit(limit + 1)).scalars().all()
    items = [EntryOut.model_validate(r) for r in rows[:limit]]
    next_cursor = items[-1].id if len(rows) > limit else None
    return EntriesPage(items=items, next_cursor=next_cursor)
