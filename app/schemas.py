"""Pydantic request and response models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

HANDLE_PATTERN = r"^[a-z0-9._-]{3,32}@ironpay$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# One transfer or deposit is capped at 1,00,000 rupees (paise).
MAX_AMOUNT_MINOR = 10_000_000


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the token expires")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str


class AccountCreate(BaseModel):
    handle: str = Field(pattern=HANDLE_PATTERN, examples=["asha@ironpay"])


class AccountOut(BaseModel):
    id: uuid.UUID
    handle: str
    kind: str
    currency: str
    status: str
    balance_minor: int


class DepositIn(BaseModel):
    to_account_id: uuid.UUID
    amount_minor: int = Field(gt=0, le=MAX_AMOUNT_MINOR, examples=[100000])


class TransferIn(BaseModel):
    from_account_id: uuid.UUID
    to_handle: str = Field(pattern=HANDLE_PATTERN, examples=["riya@ironpay"])
    amount_minor: int = Field(gt=0, le=MAX_AMOUNT_MINOR, examples=[25000])
    note: str | None = Field(default=None, max_length=140)


class TransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount_minor: int
    kind: str
    status: str
    reject_reason: str | None
    note: str | None
    created_at: datetime


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transfer_id: uuid.UUID
    direction: str
    amount_minor: int
    created_at: datetime


class EntriesPage(BaseModel):
    items: list[EntryOut]
    next_cursor: int | None = Field(
        description="Pass as before_id to get the next (older) page; null on the last page."
    )
