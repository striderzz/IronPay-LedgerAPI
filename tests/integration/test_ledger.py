"""Ledger rules against real PostgreSQL."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import LedgerEntry, Transfer
from app.services.checker import run_checks
from app.services.ledger import InvalidTransfer, balance, post_transfer

pytestmark = pytest.mark.integration


def test_deposit_credits_wallet_and_debits_funding(session, make_wallet):
    a = make_wallet("asha", deposit_minor=10_000)
    assert balance(session, a) == 10_000
    report = run_checks(session)
    assert report["ok"], report
    assert report["totals"]["drift_minor"] == 0


def test_transfer_writes_one_balanced_pair(session, make_wallet):
    a = make_wallet("asha", deposit_minor=10_000)
    b = make_wallet("riya")
    t = post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=2_500)
    session.commit()

    assert t.status == "completed"
    entries = (
        session.execute(select(LedgerEntry).where(LedgerEntry.transfer_id == t.id)).scalars().all()
    )
    assert sorted((e.direction, e.amount_minor) for e in entries) == [
        ("credit", 2_500),
        ("debit", 2_500),
    ]
    assert balance(session, a) == 7_500
    assert balance(session, b) == 2_500
    assert run_checks(session)["ok"]


def test_insufficient_funds_is_recorded_without_entries(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)
    b = make_wallet("riya")
    t = post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=1_001)
    session.commit()

    assert (t.status, t.reject_reason) == ("rejected", "insufficient_funds")
    assert (
        session.execute(select(LedgerEntry).where(LedgerEntry.transfer_id == t.id)).first() is None
    )
    assert balance(session, a) == 1_000
    assert run_checks(session)["ok"]


def test_frozen_account_rejects(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)
    b = make_wallet("riya")
    session.execute(text("UPDATE accounts SET status = 'frozen' WHERE id = :id"), {"id": b})
    session.commit()
    t = post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=100)
    assert t.reject_reason == "account_frozen"


@pytest.mark.parametrize("amount", [0, -5])
def test_non_positive_amount_is_invalid(session, make_wallet, amount):
    a = make_wallet("asha", deposit_minor=1_000)
    b = make_wallet("riya")
    with pytest.raises(InvalidTransfer):
        post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=amount)


def test_same_account_is_invalid(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)
    with pytest.raises(InvalidTransfer):
        post_transfer(session, from_account_id=a, to_account_id=a, amount_minor=10)


def test_ledger_entries_are_append_only(session, make_wallet):
    make_wallet("asha", deposit_minor=1_000)
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("UPDATE ledger_entries SET amount_minor = 1"))
    session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("DELETE FROM ledger_entries"))
    session.rollback()


def test_check_constraints_block_bad_rows(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)
    t = session.execute(select(Transfer)).scalars().first()
    with pytest.raises(DBAPIError):
        session.execute(
            text(
                "INSERT INTO ledger_entries (transfer_id, account_id, direction, amount_minor) "
                "VALUES (:t, :a, 'debit', -1)"
            ),
            {"t": t.id, "a": a},
        )
    session.rollback()


def test_checker_detects_an_unbalanced_entry(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)
    b = make_wallet("riya")
    t = post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=100)
    session.commit()
    # Simulate a bug: remove the credit side by writing around the ledger helper.
    session.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER ledger_entries_append_only"))
    session.execute(
        text("DELETE FROM ledger_entries WHERE transfer_id = :t AND direction = 'credit'"),
        {"t": t.id},
    )
    report = run_checks(session)
    session.rollback()  # undo the DELETE and the trigger change
    assert not report["ok"]
    assert report["violations"]["debits_equal_credits"] == 1
    assert report["violations"]["completed_transfer_entries"] == 1
