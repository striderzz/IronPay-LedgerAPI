"""Outbox relay: publishes unpublished outbox rows to a Redis Stream.

Each batch runs in one transaction:
1. SELECT unpublished rows in id order with FOR UPDATE SKIP LOCKED, so several relay
   processes can run at once without publishing the same row twice.
2. XADD each event to the stream.
3. Mark the published rows and COMMIT.

If the process dies after XADD but before COMMIT, the rows are published again on the
next run. That is at-least-once delivery: consumers drop duplicates by `event_id`.
If Redis is down, the batch stops at the first failure, the failed row's attempt count
and error are recorded, and the rows stay unpublished for the next poll.

Usage: python -m worker.outbox_relay
"""

import json
import logging
import signal
import time

import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.logging_setup import configure_logging
from app.redis_client import redis_client
from app.services.outbox import STREAM

log = logging.getLogger("ironpay.relay")

SELECT_BATCH = text(
    """
    SELECT id, event_id, event_type, aggregate_id, payload, created_at
    FROM outbox_events
    WHERE published_at IS NULL
    ORDER BY id
    LIMIT :n
    FOR UPDATE SKIP LOCKED
    """
)


def relay_once(
    session: Session, client: redis.Redis, *, stream: str = STREAM, batch_size: int = 100
) -> int:
    """Publish one batch. Returns how many events were published."""
    rows = session.execute(SELECT_BATCH, {"n": batch_size}).all()
    published: list[int] = []
    for row in rows:
        try:
            client.xadd(
                stream,
                {
                    "event_id": str(row.event_id),
                    "event_type": row.event_type,
                    "aggregate_id": str(row.aggregate_id),
                    "payload": json.dumps(row.payload),
                    "created_at": row.created_at.isoformat(),
                },
                maxlen=100_000,
                approximate=True,
            )
        except redis.RedisError as exc:
            session.execute(
                text(
                    "UPDATE outbox_events SET attempts = attempts + 1, last_error = :e "
                    "WHERE id = :id"
                ),
                {"e": f"{exc.__class__.__name__}: {exc}"[:500], "id": row.id},
            )
            log.warning("publish failed, will retry", extra={"fields": {"outbox_id": row.id}})
            break  # keep order: later rows wait for this one
        published.append(row.id)
    if published:
        session.execute(
            text(
                "UPDATE outbox_events SET published_at = now(), attempts = attempts + 1 "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": published},
        )
    session.commit()
    return len(published)


def main() -> None:
    configure_logging(get_settings().log_level)
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("outbox relay started", extra={"fields": {"stream": STREAM}})
    while not stop:
        try:
            with SessionLocal() as session:
                n = relay_once(session, redis_client)
        except Exception:  # keep the loop alive through transient DB errors
            log.exception("relay batch failed")
            n = 0
        if n:
            log.info("published", extra={"fields": {"count": n}})
        else:
            time.sleep(0.5)
    log.info("outbox relay stopped")


if __name__ == "__main__":
    main()
