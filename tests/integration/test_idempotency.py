"""Idempotency-Key behaviour on transfers and deposits."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.models import Transfer
from app.services.checker import run_checks

pytestmark = pytest.mark.integration


@pytest.fixture
def funded(api_user):
    asha = api_user("asha")
    a = asha.wallet()
    api_user("riya").wallet()
    asha.post("/deposits", {"to_account_id": a, "amount_minor": 10_000})
    return asha, a


def _transfers(session) -> int:
    return session.execute(
        select(func.count()).select_from(Transfer).where(Transfer.kind == "transfer")
    ).scalar_one()


def test_retry_with_same_key_replays_the_stored_response(funded, session):
    asha, a = funded
    body = {"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 1_000}

    first = asha.post("/transfers", body, key="key-1")
    second = asha.post("/transfers", body, key="key-1")

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["idempotent-replayed"] == "true"
    assert _transfers(session) == 1
    assert asha.get(f"/accounts/{a}").json()["balance_minor"] == 9_000


def test_rejections_are_replayed_too(funded, session):
    asha, a = funded
    body = {"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 99_999}
    first = asha.post("/transfers", body, key="big")
    second = asha.post("/transfers", body, key="big")
    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()
    assert _transfers(session) == 1  # one rejected transfer recorded, not two


def test_same_key_with_different_body_is_422(funded, session):
    asha, a = funded
    asha.post(
        "/transfers",
        {"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 100},
        key="k",
    )
    r = asha.post(
        "/transfers",
        {"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 200},
        key="k",
    )
    assert r.status_code == 422
    assert r.json()["type"] == "/problems/idempotency-key-reused"
    assert _transfers(session) == 1


def test_keys_are_scoped_per_user(funded, api_user):
    asha, a = funded
    sam = api_user("sam")
    s = sam.wallet()
    assert (
        asha.post("/deposits", {"to_account_id": a, "amount_minor": 5}, key="shared").status_code
        == 201
    )
    assert (
        sam.post("/deposits", {"to_account_id": s, "amount_minor": 5}, key="shared").status_code
        == 201
    )


def test_missing_key_is_rejected(funded):
    asha, a = funded
    r = asha.client.post(
        "/transfers",
        json={"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 1},
        headers=asha.headers,
    )
    assert r.status_code == 422


def test_concurrent_requests_with_one_key_create_one_transfer(funded, session, monkeypatch):
    """20 identical requests race with the same key: one transfer, 20 identical answers."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "transfer_burst", 100)  # isolate from rate limiting
    asha, a = funded
    body = {"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 500}
    barrier = threading.Barrier(20)

    def send(_):
        barrier.wait()
        return asha.post("/transfers", body, key="race")

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(send, range(20)))

    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert _transfers(session) == 1
    assert asha.get(f"/accounts/{a}").json()["balance_minor"] == 9_500
    assert run_checks(session)["ok"]
