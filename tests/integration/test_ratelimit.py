"""Redis token bucket: 429 with Retry-After, and fail-open when Redis is down."""

import pytest
import redis

from app import ratelimit
from app.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def tight_limits(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "transfer_burst", 3)
    monkeypatch.setattr(s, "transfer_rate_per_sec", 0.01)
    return s


def test_money_endpoints_are_limited_per_user(api_user, tight_limits):
    asha = api_user("asha")
    a = asha.wallet()
    codes = [
        asha.post("/deposits", {"to_account_id": a, "amount_minor": 1}).status_code
        for _ in range(5)
    ]
    assert codes == [201, 201, 201, 429, 429]

    r = asha.post("/deposits", {"to_account_id": a, "amount_minor": 1})
    assert r.headers["content-type"] == "application/problem+json"
    assert int(r.headers["retry-after"]) >= 1

    # another user has their own bucket
    riya = api_user("riya")
    assert (
        riya.post("/deposits", {"to_account_id": riya.wallet(), "amount_minor": 1}).status_code
        == 201
    )


def test_login_is_limited_per_ip(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "login_burst", 2)
    monkeypatch.setattr(s, "login_rate_per_sec", 0.01)
    body = {"email": "nobody@example.com", "password": "whatever-1"}
    codes = [client.post("/auth/token", json=body).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


def test_empty_bucket_reports_when_to_retry(clean_db):
    allowed, retry_after = ratelimit.take_token("t", "refill-slow", rate=0.5, burst=1)
    assert allowed
    allowed, retry_after = ratelimit.take_token("t", "refill-slow", rate=0.5, burst=1)
    assert not allowed and 0 < retry_after <= 2


def test_fails_open_when_redis_is_down(api_user, tight_limits, monkeypatch):
    asha = api_user("asha")
    a = asha.wallet()

    def broken(*args, **kwargs):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(ratelimit, "_script", broken)
    codes = [
        asha.post("/deposits", {"to_account_id": a, "amount_minor": 1}).status_code
        for _ in range(6)
    ]
    assert codes == [201] * 6
