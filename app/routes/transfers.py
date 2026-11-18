"""Deposits and transfers. Each request is one database transaction."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Account, Transfer
from app.schemas import DepositIn, TransferIn, TransferOut
from app.services import ledger

router = APIRouter(tags=["transfers"])


def _respond(transfer: Transfer) -> JSONResponse:
    """201 for a completed transfer; 422 for a rejected one (it is still recorded)."""
    code = status.HTTP_201_CREATED if transfer.status == "completed" else 422
    body = jsonable_encoder(TransferOut.model_validate(transfer))
    return JSONResponse(body, status_code=code)


def _post(session: Session, **kwargs) -> JSONResponse:
    try:
        transfer = ledger.post_transfer(session, **kwargs)
        session.commit()
    except ledger.AccountNotFound:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found") from None
    except ledger.InvalidTransfer as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from None
    session.refresh(transfer)
    return _respond(transfer)


@router.post(
    "/deposits",
    response_model=TransferOut,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"description": "Account not found"}},
)
def create_deposit(body: DepositIn, session: Session = Depends(get_session)) -> JSONResponse:
    """Move money from the system funding account into a wallet."""
    return _post(
        session,
        from_account_id=ledger.funding_account(session).id,
        to_account_id=body.to_account_id,
        amount_minor=body.amount_minor,
        kind="deposit",
    )


@router.post(
    "/transfers",
    response_model=TransferOut,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"description": "Rejected (for example insufficient funds)"}},
)
def create_transfer(body: TransferIn, session: Session = Depends(get_session)) -> JSONResponse:
    receiver = session.execute(
        select(Account).where(Account.handle == body.to_handle)
    ).scalar_one_or_none()
    if receiver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "receiver handle not found")
    return _post(
        session,
        from_account_id=body.from_account_id,
        to_account_id=receiver.id,
        amount_minor=body.amount_minor,
        note=body.note,
    )


@router.get("/transfers/{transfer_id}", response_model=TransferOut)
def get_transfer(transfer_id: uuid.UUID, session: Session = Depends(get_session)) -> Transfer:
    transfer = session.get(Transfer, transfer_id)
    if transfer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transfer not found")
    return transfer
