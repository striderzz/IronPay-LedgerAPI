"""Deposits and transfers.

Each request is one database transaction that holds the idempotency key, the account
row locks, the transfer and its ledger entries. A retry with the same Idempotency-Key
replays the stored response instead of moving money again.
"""

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user, money_rate_limit
from app.models import Account, Transfer, User
from app.problems import PROBLEM_JSON, ProblemError
from app.routes.accounts import owned_account
from app.schemas import DepositIn, TransferIn, TransferOut
from app.services import audit, idempotency, ledger

router = APIRouter(tags=["transfers"])

IdempotencyKey = Header(
    alias="Idempotency-Key",
    min_length=1,
    max_length=255,
    description="Unique per logical request (a UUID works). Retries must reuse it.",
)

REJECTION_TITLES = {
    "insufficient_funds": "Insufficient funds",
    "account_frozen": "Account frozen",
}


def _render(transfer: Transfer) -> tuple[int, dict, str]:
    """201 with the transfer, or a 422 problem that still carries the recorded transfer."""
    body = jsonable_encoder(TransferOut.model_validate(transfer))
    if transfer.status == "completed":
        return 201, body, "application/json"
    reason = transfer.reject_reason or "rejected"
    problem = {
        "type": f"/problems/{reason.replace('_', '-')}",
        "title": REJECTION_TITLES.get(reason, "Transfer rejected"),
        "status": 422,
        "detail": f"transfer {transfer.id} was rejected: {reason}",
        "transfer": body,
    }
    return 422, problem, PROBLEM_JSON


def _idempotent(
    request: Request,
    session: Session,
    user: User,
    key: str,
    body: dict,
    action: Callable[[], Transfer],
) -> JSONResponse:
    req_hash = idempotency.request_hash(request.method, request.url.path, body)
    try:
        stored = idempotency.begin(session, user.id, key, req_hash)
    except idempotency.KeyReused:
        session.rollback()
        raise ProblemError(
            422,
            "this Idempotency-Key was already used with a different request body",
            title="Idempotency key reused",
            type_="/problems/idempotency-key-reused",
        ) from None
    if stored is not None:
        session.commit()
        media = PROBLEM_JSON if stored.status >= 400 else "application/json"
        return JSONResponse(
            stored.body,
            status_code=stored.status,
            media_type=media,
            headers={"Idempotent-Replayed": "true"},
        )

    try:
        transfer = action()
    except ledger.AccountNotFound:
        session.rollback()  # also releases the key, so a corrected retry can use it
        raise ProblemError(404, "account not found") from None
    except ledger.InvalidTransfer as exc:
        session.rollback()
        raise ProblemError(422, str(exc)) from None

    session.refresh(transfer)  # load server defaults such as created_at
    code, payload, media = _render(transfer)
    idempotency.finish(session, user.id, key, code, payload)
    audit.record(
        session,
        actor_id=user.id,
        action=f"{transfer.kind}.create",
        entity_type="transfer",
        entity_id=str(transfer.id),
        details={
            "status": transfer.status,
            "amount_minor": transfer.amount_minor,
            "reject_reason": transfer.reject_reason,
        },
    )
    session.commit()
    return JSONResponse(payload, status_code=code, media_type=media)


@router.post(
    "/deposits",
    response_model=TransferOut,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"description": "Wallet not found"}, 429: {"description": "Rate limited"}},
)
def create_deposit(
    body: DepositIn,
    request: Request,
    idempotency_key: str = IdempotencyKey,
    session: Session = Depends(get_session),
    user: User = Depends(money_rate_limit),
) -> JSONResponse:
    """Move money from the system funding account into one of your wallets."""
    wallet = owned_account(session, body.to_account_id, user)
    return _idempotent(
        request,
        session,
        user,
        idempotency_key,
        body.model_dump(mode="json"),
        lambda: ledger.deposit(session, to_account_id=wallet.id, amount_minor=body.amount_minor),
    )


@router.post(
    "/transfers",
    response_model=TransferOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Wallet or receiver handle not found"},
        422: {"description": "Rejected (insufficient funds, frozen account, key reused)"},
        429: {"description": "Rate limited"},
    },
)
def create_transfer(
    body: TransferIn,
    request: Request,
    idempotency_key: str = IdempotencyKey,
    session: Session = Depends(get_session),
    user: User = Depends(money_rate_limit),
) -> JSONResponse:
    sender = owned_account(session, body.from_account_id, user)
    receiver = session.execute(
        select(Account).where(Account.handle == body.to_handle, Account.kind == "wallet")
    ).scalar_one_or_none()
    if receiver is None:
        raise ProblemError(404, "receiver handle not found")
    return _idempotent(
        request,
        session,
        user,
        idempotency_key,
        body.model_dump(mode="json"),
        lambda: ledger.post_transfer(
            session,
            from_account_id=sender.id,
            to_account_id=receiver.id,
            amount_minor=body.amount_minor,
            note=body.note,
        ),
    )


@router.get("/transfers/{transfer_id}", response_model=TransferOut)
def get_transfer(
    transfer_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> Transfer:
    """Visible to the owner of either side of the transfer."""
    mine = select(Account.id).where(Account.user_id == user.id)
    transfer = session.execute(
        select(Transfer).where(
            Transfer.id == transfer_id,
            or_(Transfer.from_account_id.in_(mine), Transfer.to_account_id.in_(mine)),
        )
    ).scalar_one_or_none()
    if transfer is None:
        raise ProblemError(404, "transfer not found")
    return transfer
