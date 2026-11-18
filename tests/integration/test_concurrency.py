"""Concurrency guarantees, tested with real parallel PostgreSQL connections."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.services.checker import run_checks
from app.services.ledger import balance, post_transfer

pytestmark = pytest.mark.integration


@pytest.fixture
def wide_sessions():
    """A separate pool big enough that every worker holds its own connection."""
    engine = create_engine(get_settings().database_url, pool_size=60, max_overflow=0)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def _run_parallel(n: int, fn) -> list:
    barrier = threading.Barrier(n)

    def worker(i: int):
        barrier.wait()  # release every thread at the same moment
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def test_double_spend_exactly_ten_succeed(make_wallet, wide_sessions, session):
    """100 rupees in the wallet, 50 parallel transfers of 10 rupees: exactly 10 succeed."""
    sender = make_wallet("asha", deposit_minor=10_000)
    receiver = make_wallet("riya")

    def transfer(_: int) -> str:
        with wide_sessions() as s:
            t = post_transfer(s, from_account_id=sender, to_account_id=receiver, amount_minor=1_000)
            s.commit()
            return t.status

    statuses = _run_parallel(50, transfer)

    assert statuses.count("completed") == 10
    assert statuses.count("rejected") == 40
    assert balance(session, sender) == 0
    assert balance(session, receiver) == 10_000
    report = run_checks(session)
    assert report["ok"], report
    assert report["totals"]["drift_minor"] == 0


def test_opposite_direction_transfers_do_not_deadlock(make_wallet, wide_sessions, session):
    """A to B and B to A at the same time. Locks are taken in id order, so no deadlock."""
    a = make_wallet("asha", deposit_minor=50_000)
    b = make_wallet("riya", deposit_minor=50_000)

    def transfer(i: int) -> str:
        src, dst = (a, b) if i % 2 == 0 else (b, a)
        with wide_sessions() as s:
            t = post_transfer(s, from_account_id=src, to_account_id=dst, amount_minor=100)
            s.commit()
            return t.status

    statuses = _run_parallel(40, transfer)  # a deadlock would raise and fail the test

    assert statuses == ["completed"] * 40
    assert balance(session, a) + balance(session, b) == 100_000
    assert run_checks(session)["ok"]
