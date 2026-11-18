"""Transactional outbox and the relay worker, against real PostgreSQL and Redis."""

import json
import threading
import uuid

import pytest
import redis
from sqlalchemy import text

from app.db import SessionLocal
from app.redis_client import redis_client
from app.services import outbox
from app.services.ledger import post_transfer
from worker.outbox_relay import relay_once

pytestmark = pytest.mark.integration
STREAM = "test.events"


def _events(session) -> list:
    return session.execute(
        text("SELECT event_type, payload, published_at FROM outbox_events ORDER BY id")
    ).all()


def test_each_transfer_writes_one_event_in_its_transaction(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)  # deposit.completed
    b = make_wallet("riya")
    post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=400)
    post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=5_000)
    session.commit()

    types = [e.event_type for e in _events(session)]
    assert types == ["deposit.completed", "transfer.completed", "transfer.rejected"]
    assert _events(session)[2].payload["reject_reason"] == "insufficient_funds"


def test_rolled_back_transfer_leaves_no_event(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)
    b = make_wallet("riya")
    session.execute(text("TRUNCATE outbox_events"))
    session.commit()
    post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=100)
    session.rollback()
    assert _events(session) == []


def test_relay_publishes_in_order_and_marks_rows(session, make_wallet):
    a = make_wallet("asha", deposit_minor=1_000)
    b = make_wallet("riya")
    post_transfer(session, from_account_id=a, to_account_id=b, amount_minor=100)
    session.commit()

    assert relay_once(session, redis_client, stream=STREAM) == 2
    assert relay_once(session, redis_client, stream=STREAM) == 0  # nothing left

    entries = redis_client.xrange(STREAM)
    assert [fields["event_type"] for _, fields in entries] == [
        "deposit.completed",
        "transfer.completed",
    ]
    assert json.loads(entries[1][1]["payload"])["amount_minor"] == 100
    assert all(e.published_at is not None for e in _events(session))


def test_parallel_relays_never_publish_a_row_twice(clean_db):
    """SKIP LOCKED: two relays split the rows between them instead of both taking them."""
    with SessionLocal() as s:
        for _ in range(300):
            outbox.add(s, event_type="test.event", aggregate_id=uuid.uuid4(), payload={})
        s.commit()

    def drain() -> None:
        with SessionLocal() as s:
            while relay_once(s, redis_client, stream=STREAM, batch_size=25):
                pass

    threads = [threading.Thread(target=drain) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = [fields["event_id"] for _, fields in redis_client.xrange(STREAM)]
    assert len(ids) == 300
    assert len(set(ids)) == 300


def test_redis_failure_keeps_rows_for_retry(session, make_wallet):
    make_wallet("asha", deposit_minor=1_000)

    class Down:
        def xadd(self, *args, **kwargs):
            raise redis.ConnectionError("down")

    assert relay_once(session, Down(), stream=STREAM) == 0
    row = session.execute(
        text("SELECT attempts, last_error, published_at FROM outbox_events")
    ).one()
    assert row.attempts == 1 and "ConnectionError" in row.last_error and row.published_at is None

    assert relay_once(session, redis_client, stream=STREAM) == 1  # recovers on the next poll
