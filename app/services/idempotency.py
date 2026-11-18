"""Idempotency keys, stored in PostgreSQL inside the same transaction as the transfer.

- New key: the caller processes the request, then `finish` stores the response.
- Same key, same body: `begin` returns the stored response to replay.
- Same key, different body: `begin` raises `KeyReused` (the API answers 422).

Two requests with the same key at the same moment: the second INSERT waits on the
primary key until the first transaction commits, then sees the stored response. If
the first rolls back, the second becomes the new owner of the key.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings


class KeyReused(Exception):
    """The key was already used for a different request."""


@dataclass
class StoredResponse:
    status: int
    body: Any


def request_hash(method: str, path: str, body: dict) -> str:
    canonical = json.dumps(
        {"method": method, "path": path, "body": body},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def begin(session: Session, user_id: uuid.UUID, key: str, req_hash: str) -> StoredResponse | None:
    inserted = session.execute(
        text(
            "INSERT INTO idempotency_keys (user_id, key, request_hash) "
            "VALUES (:u, :k, :h) ON CONFLICT (user_id, key) DO NOTHING RETURNING key"
        ),
        {"u": user_id, "k": key, "h": req_hash},
    ).first()
    if inserted:
        return None

    row = session.execute(
        text(
            "SELECT request_hash, response_status, response_body, "
            "       created_at < now() - make_interval(hours => :ttl) AS expired "
            "FROM idempotency_keys WHERE user_id = :u AND key = :k FOR UPDATE"
        ),
        {"u": user_id, "k": key, "ttl": get_settings().idempotency_ttl_hours},
    ).one()
    if row.expired:
        # An expired key starts over as a new request.
        session.execute(
            text(
                "UPDATE idempotency_keys SET request_hash = :h, response_status = NULL, "
                "response_body = NULL, created_at = now() WHERE user_id = :u AND key = :k"
            ),
            {"u": user_id, "k": key, "h": req_hash},
        )
        return None
    if row.request_hash != req_hash:
        raise KeyReused(key)
    return StoredResponse(status=row.response_status, body=row.response_body)


def finish(session: Session, user_id: uuid.UUID, key: str, status: int, body: Any) -> None:
    session.execute(
        text(
            "UPDATE idempotency_keys SET response_status = :s, response_body = CAST(:b AS jsonb) "
            "WHERE user_id = :u AND key = :k"
        ),
        {"u": user_id, "k": key, "s": status, "b": json.dumps(body)},
    )
