"""Wallets, balances and entry history. Every query is scoped to the caller's user id,
so another user's account id returns 404 (its existence is not revealed)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.models import Account, LedgerEntry, User
from app.problems import ProblemError
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


def owned_account(session: Session, account_id: uuid.UUID, user: User) -> Account:
    account = session.execute(
        select(Account).where(Account.id == account_id, Account.user_id == user.id)
    ).scalar_one_or_none()
    if account is None:
        raise ProblemError(404, "account not found")
    return account


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountCreate,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> AccountOut:
    account = Account(id=uuid.uuid4(), user_id=user.id, handle=body.handle, kind="wallet")
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProblemError(409, "handle already taken") from None
    session.refresh(account)
    return _out(session, account)


@router.get("", response_model=list[AccountOut])
def list_accounts(
    session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list[AccountOut]:
    rows = session.execute(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at)
    ).scalars()
    return [_out(session, a) for a in rows]


@router.get("/{account_id}", response_model=AccountOut)
def get_account(
    account_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> AccountOut:
    return _out(session, owned_account(session, account_id, user))


@router.get("/{account_id}/entries", response_model=EntriesPage)
def list_entries(
    account_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, description="Cursor from the previous page"),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> EntriesPage:
    """Newest first, keyset pagination on the entry id (stable under concurrent inserts,
    and fast at any depth because it seeks the (account_id, id) index)."""
    owned_account(session, account_id, user)
    stmt = select(LedgerEntry).where(LedgerEntry.account_id == account_id)
    if before_id is not None:
        stmt = stmt.where(LedgerEntry.id < before_id)
    rows = session.execute(stmt.order_by(LedgerEntry.id.desc()).limit(limit + 1)).scalars().all()
    items = [EntryOut.model_validate(r) for r in rows[:limit]]
    next_cursor = items[-1].id if len(rows) > limit else None
    return EntriesPage(items=items, next_cursor=next_cursor)
