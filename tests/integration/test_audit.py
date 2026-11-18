"""Audit log rows and request ids."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def _audit(session) -> list:
    return session.execute(
        text("SELECT action, entity_type, request_id, ip, details FROM audit_log ORDER BY id")
    ).all()


def test_actions_are_audited_with_the_request_id(api_user, session):
    asha = api_user("asha")  # user.register, auth.login
    a = asha.wallet()  # account.create
    r = asha.client.post(
        "/deposits",
        json={"to_account_id": a, "amount_minor": 500},
        headers={**asha.headers, "Idempotency-Key": "k1", "X-Request-ID": "req-abc-123"},
    )
    assert r.headers["x-request-id"] == "req-abc-123"

    rows = _audit(session)
    assert [r.action for r in rows] == [
        "user.register",
        "auth.login",
        "account.create",
        "deposit.create",
    ]
    deposit = rows[-1]
    assert deposit.request_id == "req-abc-123"
    assert deposit.details["amount_minor"] == 500 and deposit.ip


def test_failed_login_is_audited(client, session):
    client.post("/auth/token", json={"email": "ghost@example.com", "password": "x" * 10})
    assert [r.action for r in _audit(session)] == ["auth.login_failed"]


def test_request_id_is_generated_when_missing(client):
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) == 36


def test_audit_log_is_append_only(api_user, session):
    api_user("asha")
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("UPDATE audit_log SET action = 'x'"))
    session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("DELETE FROM audit_log"))
    session.rollback()
