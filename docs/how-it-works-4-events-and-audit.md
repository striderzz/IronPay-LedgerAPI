# How it works: events and audit (Phase 4)

## Transactional outbox

`post_transfer` inserts a row into `outbox_events` (`transfer.completed`, `transfer.rejected`, `deposit.completed`, ...) in the same transaction as the transfer and its entries. A committed transfer always has its event; a rolled-back one never does. Publishing to Redis directly from the request would lose the event if the process died between `COMMIT` and the publish.

## Relay worker (`worker/outbox_relay.py`)

A separate process (`relay` service in Docker Compose) polls in a loop. Each batch is one transaction:

1. `SELECT ... WHERE published_at IS NULL ORDER BY id LIMIT n FOR UPDATE SKIP LOCKED`
2. `XADD ironpay.events` for each row (event id, type, aggregate id, JSON payload, time)
3. `UPDATE ... SET published_at = now()` for the published rows, then `COMMIT`

- **SKIP LOCKED** lets several relays run at once: each takes rows the others have not locked, so no row is published twice by two relays. A test runs three relays over 300 events and gets exactly 300 unique events on the stream.
- **At-least-once:** if the relay dies after `XADD` but before `COMMIT`, the rows are published again. Consumers deduplicate on `event_id`.
- **Redis down:** the batch stops at the first failed publish, records `attempts` and `last_error` on that row, and keeps the rest unpublished in order; the next poll retries.
- A partial index on unpublished rows keeps the poll cheap as the table grows.

## Audit log

`audit_log` records actor, action, entity, request id, client IP and JSON details for `user.register`, `auth.login`, `auth.login_failed`, `account.create`, `transfer.create` and `deposit.create`. Rows are written in the business transaction, and a trigger rejects `UPDATE` and `DELETE`.

## JSON logs and request ids

`RequestContextMiddleware` takes `X-Request-ID` from the request (or generates a UUID), puts it in a context variable, returns it in the response header and writes one JSON access-log line per request (method, path, status, duration). Every log line and audit row carries the same request id, so one request can be traced from the access log to its audit rows.
