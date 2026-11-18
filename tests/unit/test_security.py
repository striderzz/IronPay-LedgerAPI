import uuid

import pytest

from app.security import (
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.idempotency import request_hash


def test_token_round_trip():
    uid = uuid.uuid4()
    assert decode_access_token(create_access_token(uid)) == uid


def test_expired_token_is_invalid():
    with pytest.raises(InvalidToken):
        decode_access_token(create_access_token(uuid.uuid4(), minutes=-1))


def test_tampered_token_is_invalid():
    token = create_access_token(uuid.uuid4())
    head, payload, sig = token.split(".")
    with pytest.raises(InvalidToken):
        decode_access_token(f"{head}.{payload}.{sig[:-2]}xx")


def test_password_hash_verifies_and_is_salted():
    h1, h2 = hash_password("correct horse"), hash_password("correct horse")
    assert h1 != h2 and h1.startswith("$argon2")
    assert verify_password("correct horse", h1)
    assert not verify_password("wrong", h1)
    assert not verify_password("anything", None)


def test_request_hash_ignores_key_order_but_not_values():
    a = request_hash("POST", "/transfers", {"x": 1, "y": 2})
    b = request_hash("POST", "/transfers", {"y": 2, "x": 1})
    c = request_hash("POST", "/transfers", {"x": 1, "y": 3})
    d = request_hash("POST", "/deposits", {"x": 1, "y": 2})
    assert a == b
    assert len({a, c, d}) == 3
