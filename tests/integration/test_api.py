"""HTTP flow: register, log in, open wallets, deposit, transfer, read history."""

import uuid

import pytest

pytestmark = pytest.mark.integration


def test_full_transfer_flow(api_user):
    asha, riya = api_user("asha"), api_user("riya")
    a = asha.wallet()
    riya.wallet()

    r = asha.post("/deposits", {"to_account_id": a, "amount_minor": 100_000})
    assert r.status_code == 201 and r.json()["kind"] == "deposit"

    r = asha.post(
        "/transfers",
        {
            "from_account_id": a,
            "to_handle": "riya@ironpay",
            "amount_minor": 25_000,
            "note": "dinner",
        },
    )
    assert r.status_code == 201
    assert r.json()["status"] == "completed"
    transfer_id = r.json()["id"]

    assert asha.get(f"/accounts/{a}").json()["balance_minor"] == 75_000
    assert asha.get(f"/transfers/{transfer_id}").json()["note"] == "dinner"
    # the receiver can see the transfer too
    assert riya.get(f"/transfers/{transfer_id}").status_code == 200
    assert [w["balance_minor"] for w in riya.get("/accounts").json()] == [25_000]


def test_insufficient_funds_is_a_422_problem_with_the_recorded_transfer(api_user):
    asha = api_user("asha")
    a = asha.wallet()
    api_user("riya").wallet()

    r = asha.post(
        "/transfers", {"from_account_id": a, "to_handle": "riya@ironpay", "amount_minor": 1}
    )

    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"] == "/problems/insufficient-funds"
    assert body["transfer"]["status"] == "rejected"
    assert body["transfer"]["reject_reason"] == "insufficient_funds"


def test_entries_keyset_pagination(api_user):
    asha = api_user("asha")
    a = asha.wallet()
    for _ in range(5):
        asha.post("/deposits", {"to_account_id": a, "amount_minor": 100})

    page1 = asha.get(f"/accounts/{a}/entries", params={"limit": 2}).json()
    page2 = asha.get(
        f"/accounts/{a}/entries", params={"limit": 2, "before_id": page1["next_cursor"]}
    ).json()
    page3 = asha.get(
        f"/accounts/{a}/entries", params={"limit": 2, "before_id": page2["next_cursor"]}
    ).json()

    ids = [e["id"] for p in (page1, page2, page3) for e in p["items"]]
    assert len(ids) == 5 and ids == sorted(ids, reverse=True)
    assert page3["next_cursor"] is None


def test_errors_are_problem_details(api_user, client):
    asha = api_user("asha")
    a = asha.wallet()
    missing = str(uuid.uuid4())

    r = asha.get(f"/accounts/{missing}")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["title"] == "Not Found" and r.json()["instance"] == f"/accounts/{missing}"

    assert asha.post("/deposits", {"to_account_id": missing, "amount_minor": 1}).status_code == 404
    r = asha.post(
        "/transfers", {"from_account_id": a, "to_handle": "nobody@ironpay", "amount_minor": 1}
    )
    assert r.status_code == 404
    # the system funding account is not a valid receiver
    r = asha.post(
        "/transfers", {"from_account_id": a, "to_handle": "funding@ironpay", "amount_minor": 1}
    )
    assert r.status_code == 404

    r = asha.post("/deposits", {"to_account_id": a, "amount_minor": 0})
    assert r.status_code == 422 and r.json()["errors"][0]["loc"] == ["body", "amount_minor"]

    dup = client.post("/auth/register", json={"email": "asha@example.com", "password": "pass-1234"})
    assert dup.status_code == 409
    assert (
        asha.client.post(
            "/accounts", json={"handle": "asha@ironpay"}, headers=asha.headers
        ).status_code
        == 409
    )
