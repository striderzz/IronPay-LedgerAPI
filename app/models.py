"""SQLAlchemy tables (the schema itself is created by the Alembic migrations).

Money is always an integer number of paise (`amount_minor`, BIGINT). Balances are never
stored: a wallet's balance is the sum of its ledger entries (credits minus debits).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SYSTEM_FUNDING_HANDLE = "funding@ironpay"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    handle: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)  # wallet | system
    currency: Mapped[str] = mapped_column(String(3), server_default="INR")
    status: Mapped[str] = mapped_column(Text, server_default="active")  # active | frozen
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    from_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    to_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text)  # transfer | deposit
    status: Mapped[str] = mapped_column(Text)  # completed | rejected
    reject_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    transfer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transfers.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    direction: Mapped[str] = mapped_column(Text)  # debit | credit
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
