"""Double-entry ledger. Every money movement goes through `post_transfer`.

Rules this module enforces:
- A completed transfer writes exactly one debit and one credit of the same amount.
- Both account rows are locked with SELECT ... FOR UPDATE, always in ascending id
  order, so two opposite transfers (A to B and B to A) can never deadlock.
- The sender's balance is computed from its entries while the lock is held, so a
  concurrent transfer on the same wallet waits and then sees the committed result.
- A rejected transfer is recorded with a reason and writes no entries.

The caller owns the transaction: it commits after `post_transfer` returns.
"""

import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import SYSTEM_FUNDING_HANDLE, Account, LedgerEntry, Transfer


class LedgerError(Exception):
    """Base class for request errors raised by the ledger."""


class AccountNotFound(LedgerError):
    pass


class InvalidTransfer(LedgerError):
    pass


def balance(session: Session, account_id: uuid.UUID) -> int:
    """Credits minus debits, in paise."""
    signed = case(
        (LedgerEntry.direction == "credit", LedgerEntry.amount_minor),
        else_=-LedgerEntry.amount_minor,
    )
    stmt = select(func.coalesce(func.sum(signed), 0)).where(LedgerEntry.account_id == account_id)
    return int(session.execute(stmt).scalar_one())


def funding_account(session: Session) -> Account:
    return session.execute(
        select(Account).where(Account.handle == SYSTEM_FUNDING_HANDLE)
    ).scalar_one()


def _lock_in_id_order(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Account]:
    """Lock each account row, one statement per row, in ascending id order."""
    locked: dict[uuid.UUID, Account] = {}
    for account_id in sorted(ids):
        account = session.execute(
            select(Account).where(Account.id == account_id).with_for_update()
        ).scalar_one_or_none()
        if account is None:
            raise AccountNotFound(str(account_id))
        locked[account_id] = account
    return locked


def post_transfer(
    session: Session,
    *,
    from_account_id: uuid.UUID,
    to_account_id: uuid.UUID,
    amount_minor: int,
    kind: str = "transfer",
    note: str | None = None,
) -> Transfer:
    """Move money between two accounts inside the caller's transaction."""
    if amount_minor <= 0:
        raise InvalidTransfer("amount_minor must be positive")
    if from_account_id == to_account_id:
        raise InvalidTransfer("cannot transfer to the same account")

    accounts = _lock_in_id_order(session, [from_account_id, to_account_id])
    sender, receiver = accounts[from_account_id], accounts[to_account_id]

    reason = None
    if sender.status != "active" or receiver.status != "active":
        reason = "account_frozen"
    elif sender.kind == "wallet" and balance(session, sender.id) < amount_minor:
        reason = "insufficient_funds"

    transfer = Transfer(
        id=uuid.uuid4(),
        from_account_id=sender.id,
        to_account_id=receiver.id,
        amount_minor=amount_minor,
        kind=kind,
        status="rejected" if reason else "completed",
        reject_reason=reason,
        note=note,
    )
    session.add(transfer)
    if reason is None:
        session.add_all(
            [
                LedgerEntry(
                    transfer_id=transfer.id,
                    account_id=sender.id,
                    direction="debit",
                    amount_minor=amount_minor,
                ),
                LedgerEntry(
                    transfer_id=transfer.id,
                    account_id=receiver.id,
                    direction="credit",
                    amount_minor=amount_minor,
                ),
            ]
        )
    session.flush()
    return transfer


def deposit(session: Session, *, to_account_id: uuid.UUID, amount_minor: int) -> Transfer:
    """Fund a wallet from the system funding account."""
    return post_transfer(
        session,
        from_account_id=funding_account(session).id,
        to_account_id=to_account_id,
        amount_minor=amount_minor,
        kind="deposit",
    )
