"""Transactional outbox: events are rows written in the business transaction.

The relay worker (worker/outbox_relay.py) publishes them to a Redis Stream later.
Delivery is at-least-once, so every event carries an `event_id` for consumer dedup.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

STREAM = "ironpay.events"


def add(
    session: Session, *, event_type: str, aggregate_id: uuid.UUID, payload: dict[str, Any]
) -> None:
    session.execute(
        text(
            "INSERT INTO outbox_events (event_type, aggregate_id, payload) "
            "VALUES (:t, :a, CAST(:p AS jsonb))"
        ),
        {"t": event_type, "a": aggregate_id, "p": json.dumps(payload)},
    )
