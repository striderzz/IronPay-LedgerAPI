# How it works: API safety (Phase 3)

## Auth

- `POST /auth/register` stores an Argon2 hash (pwdlib). `POST /auth/token` checks the password and returns an HS256 JWT that expires after 15 minutes (`sub` = user id, `type` = access).
- A wrong password and an unknown email return the same `401`, and an unknown email still runs one Argon2 verify against a dummy hash, so response time does not reveal which emails exist.
- Every account and transfer query filters on the token's user id. Another user's account id returns `404`, the same as an id that does not exist.

## Idempotency (`app/services/idempotency.py`, migration `0002`)

`POST /transfers` and `POST /deposits` require an `Idempotency-Key` header. Inside the same transaction as the transfer:

1. `INSERT INTO idempotency_keys ... ON CONFLICT DO NOTHING`. If the row is new, process the request and store its status and body before `COMMIT`.
2. If the key exists with the same request hash (SHA-256 of method, path and canonical JSON body), return the stored response with `Idempotent-Replayed: true`. Business rejections (insufficient funds) are stored and replayed too.
3. If the key exists with a different hash, return `422` (`/problems/idempotency-key-reused`).

Two identical requests at the same moment: the second `INSERT` waits on the primary key `(user_id, key)` until the first commits, then replays its stored response. Errors that roll back (unknown account) also roll back the key, so a corrected retry can reuse it. Keys older than 24 hours start over.

## Rate limiting (`app/ratelimit.py`)

A token bucket per user for money endpoints and per client IP for login. The refill, check and decrement run in one Lua script, so concurrent requests cannot both take the last token, and the script uses Redis's clock. An empty bucket returns `429` with `Retry-After`. If Redis is down the limiter logs a warning and lets the request through (fail open).

## Errors (`app/problems.py`)

Every error is RFC 9457 `application/problem+json` with `type`, `title`, `status`, `detail` and `instance`. Validation errors add an `errors` list. A rejected transfer returns `422` with `type` such as `/problems/insufficient-funds` and the recorded transfer in a `transfer` field.

## Tests

- Retry with the same key returns the identical response and creates one transfer.
- Same key with a different body returns 422.
- 20 parallel requests with one key create exactly one transfer and return the same id.
- Ownership: another user cannot read, fund or spend from a wallet.
- Bucket exhaustion returns 429 with `Retry-After`, buckets are per user, and requests still pass when the Redis script call fails.
