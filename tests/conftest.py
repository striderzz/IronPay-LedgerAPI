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
def client(services):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
