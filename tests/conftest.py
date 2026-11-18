"""Shared fixtures.

Integration tests need real PostgreSQL and Redis. Locally they are skipped when the
services are not reachable; in CI `REQUIRE_INTEGRATION=1` turns a skip into a failure,
so a broken service container can never hide behind a skipped test.
"""

import os

import pytest
import redis
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import engine
from app.redis_client import redis_client


def _services_problem() -> str | None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        return f"PostgreSQL not reachable: {exc.__class__.__name__}"
    try:
        redis_client.ping()
    except redis.RedisError as exc:
        return f"Redis not reachable: {exc.__class__.__name__}"
    return None


@pytest.fixture(scope="session")
def services() -> None:
    problem = _services_problem()
    if problem:
        if os.getenv("REQUIRE_INTEGRATION") == "1":
            pytest.fail(problem)
        pytest.skip(problem)


@pytest.fixture
def clean_db(services) -> None:
    """Empty every table except the system funding account. TRUNCATE does not fire the
    append-only row triggers, so tests can reset the ledger between runs."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ledger_entries, transfers"))
        conn.execute(text("DELETE FROM accounts WHERE kind = 'wallet'"))
        conn.execute(text("DELETE FROM users"))


@pytest.fixture
def session(clean_db):
    from app.db import SessionLocal

    with SessionLocal() as s:
        yield s


@pytest.fixture
def make_wallet(clean_db):
    """Create a user plus a wallet and return the wallet's id."""
    import uuid

    from app.db import SessionLocal
    from app.models import Account, User

    def _make(name: str, deposit_minor: int = 0) -> uuid.UUID:
        from app.services.ledger import deposit

        with SessionLocal() as s:
            user = User(id=uuid.uuid4(), email=f"{name}@example.com", password_hash="x")
            s.add(user)
            s.flush()
            account = Account(
                id=uuid.uuid4(), user_id=user.id, handle=f"{name}@ironpay", kind="wallet"
            )
            s.add(account)
            s.flush()
            if deposit_minor:
                deposit(s, to_account_id=account.id, amount_minor=deposit_minor)
            s.commit()
            return account.id

    return _make


@pytest.fixture
def client(clean_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
