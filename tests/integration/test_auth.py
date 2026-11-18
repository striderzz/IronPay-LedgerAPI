"""JWT auth and ownership checks."""

import pytest

from app.security import create_access_token

pytestmark = pytest.mark.integration


def test_login_and_me(api_user):
    asha = api_user("asha")
    r = asha.get("/auth/me")
    assert r.status_code == 200 and r.json()["email"] == "asha@example.com"


def test_wrong_password_and_unknown_email_get_the_same_401(client, api_user):
    api_user("asha")
    wrong = client.post("/auth/token", json={"email": "asha@example.com", "password": "nope-nope"})
    unknown = client.post(
        "/auth/token", json={"email": "ghost@example.com", "password": "nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic abc"}],
)
def test_protected_routes_need_a_valid_token(client, headers):
    r = client.get("/accounts", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_expired_token_is_rejected(client, api_user):
    asha = api_user("asha")
    expired = create_access_token(asha.user_id, minutes=-1)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_other_users_wallet_is_invisible(api_user):
    asha, riya = api_user("asha"), api_user("riya")
    a = asha.wallet()
    r_wallet = riya.wallet()
    asha.post("/deposits", {"to_account_id": a, "amount_minor": 10_000})

    # riya can neither read asha's wallet nor spend from it nor fund it
    assert riya.get(f"/accounts/{a}").status_code == 404
    assert riya.get(f"/accounts/{a}/entries").status_code == 404
    r = riya.post(
        "/transfers", {"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 1}
    )
    assert r.status_code == 404
    assert riya.post("/deposits", {"to_account_id": a, "amount_minor": 1}).status_code == 404
    assert asha.get(f"/accounts/{a}").json()["balance_minor"] == 10_000
    assert [w["id"] for w in riya.get("/accounts").json()] == [r_wallet]
