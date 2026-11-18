"""HTTP flow: register, open wallets, deposit, transfer, read history."""

import uuid

import pytest

pytestmark = pytest.mark.integration


def _wallet(client, name: str) -> str:
    user = client.post(
        "/auth/register", json={"email": f"{name}@example.com", "password": "pass-1234"}
    )
    assert user.status_code == 201
    account = client.post(
        "/accounts", json={"user_id": user.json()["id"], "handle": f"{name}@ironpay"}
    )
    assert account.status_code == 201
    return account.json()["id"]


def test_full_transfer_flow(client):
    a = _wallet(client, "asha")
    _wallet(client, "riya")

    r = client.post("/deposits", json={"to_account_id": a, "amount_minor": 100_000})
    assert r.status_code == 201 and r.json()["kind"] == "deposit"

    r = client.post(
        "/transfers",
        json={
            "from_account_id": a,
            "to_handle": "riya@ironpay",
            "amount_minor": 25_000,
            "note": "dinner",
        },
    )
    assert r.status_code == 201
    assert r.json()["status"] == "completed"

    assert client.get(f"/accounts/{a}").json()["balance_minor"] == 75_000
    assert client.get(f"/transfers/{r.json()['id']}").json()["note"] == "dinner"


def test_insufficient_funds_returns_422_with_recorded_transfer(client):
    a = _wallet(client, "asha")
    _wallet(client, "riya")
    r = client.post(
        "/transfers", json={"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 1}
    )
    assert r.status_code == 422
    assert r.json()["status"] == "rejected"
    assert r.json()["reject_reason"] == "insufficient_funds"


def test_entries_keyset_pagination(client):
    a = _wallet(client, "asha")
    for _ in range(5):
        client.post("/deposits", json={"to_account_id": a, "amount_minor": 100})

    page1 = client.get(f"/accounts/{a}/entries", params={"limit": 2}).json()
    page2 = client.get(
        f"/accounts/{a}/entries", params={"limit": 2, "before_id": page1["next_cursor"]}
    ).json()
    page3 = client.get(
        f"/accounts/{a}/entries", params={"limit": 2, "before_id": page2["next_cursor"]}
    ).json()

    ids = [e["id"] for p in (page1, page2, page3) for e in p["items"]]
    assert len(ids) == 5 and ids == sorted(ids, reverse=True)
    assert page3["next_cursor"] is None


def test_errors(client):
    a = _wallet(client, "asha")
    missing = str(uuid.uuid4())
    assert client.get(f"/accounts/{missing}").status_code == 404
    assert (
        client.post("/deposits", json={"to_account_id": missing, "amount_minor": 1}).status_code
        == 404
    )
    assert (
        client.post(
            "/transfers",
            json={"from_account_id": a, "to_handle": "nobody@ironpay", "amount_minor": 1},
        ).status_code
        == 404
    )
    assert client.post("/deposits", json={"to_account_id": a, "amount_minor": 0}).status_code == 422
    dup = client.post("/auth/register", json={"email": "asha@example.com", "password": "pass-1234"})
    assert dup.status_code == 409
    taken = client.post("/accounts", json={"user_id": str(uuid.uuid4()), "handle": "asha@ironpay"})
    assert taken.status_code == 404  # unknown user is checked first
