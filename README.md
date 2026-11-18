# IronPay LedgerAPI

A small UPI-style payments API with a double-entry ledger, idempotent transfers and tests that try to double-spend it.

Status: core built (phases 1 to 6). CI runs 51 tests against real PostgreSQL and Redis; load-tested with k6 on GitHub Actions. Numbers below come from those runs.

[![CI](https://github.com/striderzz/IronPay-LedgerAPI/actions/workflows/ci.yml/badge.svg)](https://github.com/striderzz/IronPay-LedgerAPI/actions/workflows/ci.yml)

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white) ![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2-D71F00?logo=sqlalchemy&logoColor=white) ![Redis](https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white) ![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white) ![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white) ![k6](https://img.shields.io/badge/k6-7D64FF?logo=k6&logoColor=white) ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white) ![License: MIT](https://img.shields.io/badge/License-MIT-yellow)

---

## Why this exists

A payments backend has two jobs that are easy to get wrong: never lose or create money, and never apply the same payment twice. Mobile clients retry when the network drops, two requests can debit the same wallet in the same millisecond, and a crash can land between "money moved" and "event sent". Most CRUD tutorials store a `balance` column and update it in place, which fails all three cases. IronPay is a small API that handles them the way fintech teams do: an append-only double-entry ledger, idempotency keys, row locks, and an outbox table, with tests that attack each guarantee directly.

## What it does

- **Accounts and wallets** with UPI-style handles (`hasan@ironpay`), owned by a user, in a single currency (INR, stored as integer paise)
- **Double-entry ledger**: every transfer and deposit writes one debit and one credit entry of the same amount; balances are always computed from entries, never edited
- **Idempotent transfers**: `POST /transfers` takes an `Idempotency-Key` header; a retry with the same key and body returns the original response, a reused key with a different body is rejected
- **Concurrency safety**: account rows are locked with `SELECT ... FOR UPDATE` in a fixed order, so parallel transfers cannot overdraw a wallet or deadlock each other
- **JWT auth and Redis rate limiting**: users only see and move money from their own accounts; a token bucket per user (and per IP on login) returns `429` with `Retry-After`
- **Outbox and audit log**: each money movement writes an event row and an audit row in the same database transaction; a relay worker publishes events to a Redis Stream
- **OpenAPI docs** at `/docs`, with request and error examples (errors follow RFC 9457 problem details)
- **Tests that try to break it**: pytest unit and integration tests, a concurrent double-spend test, a ledger invariant checker, and k6 load tests

## Architecture

```mermaid
flowchart LR
    Client["Client or k6"] --> API["FastAPI app"]
    API --> Auth["JWT auth"]
    API --> RL["Rate limiter (Redis token bucket)"]
    API --> Svc["Transfer service"]
    Svc --> Idem["Idempotency check"]
    Svc --> Lock["Row locks: SELECT FOR UPDATE"]
    Idem --> PG[("PostgreSQL")]
    Lock --> PG
    Svc -->|"entries, outbox, audit in one transaction"| PG
    Relay["Outbox relay worker"] -->|"poll with SKIP LOCKED"| PG
    Relay -->|XADD| Stream[("Redis Stream: ironpay.events")]
    Stream --> Consumers["Downstream consumers"]
    Checker["Ledger invariant checker"] --> PG
```

A request first passes JWT auth and the Redis rate limiter. For a transfer, the service opens one PostgreSQL transaction: it records the idempotency key, locks both account rows in id order, computes the sender's balance from ledger entries, and writes the transfer, two ledger entries, an outbox event and an audit row. Either all of that commits or none of it does. A separate relay worker reads unpublished outbox rows and pushes them to a Redis Stream, so a crash never leaves a payment without its event. The invariant checker reads the ledger after tests and load runs and confirms that money was neither created nor lost.

## How it works

### Ledger model

Every account (user wallets and one system funding account) has entries in `ledger_entries`. An entry has a direction (`debit` or `credit`) and a positive amount in paise. A wallet's balance is `sum(credits) - sum(debits)` over its entries. Deposits move money from the system funding account into a wallet, so money is never created out of nothing: across all accounts, total debits always equal total credits. Entries are append-only. A correction is a new pair of entries, never an `UPDATE`. Amounts are `BIGINT` paise to avoid floating point rounding.

### Transfers and concurrency

A transfer runs inside one transaction at `READ COMMITTED`. The service locks both account rows with `SELECT ... FOR UPDATE`, always in ascending id order, so two opposite transfers (A to B and B to A) cannot deadlock. While holding the lock it sums the sender's entries and checks the balance. A second request on the same wallet waits for the lock and then sees the committed entries of the first, so it cannot spend the same money. Pessimistic locking was chosen over optimistic versioning because wallets see frequent contention and retries under optimistic locking waste work; the trade-off is written up in [INFO.md](INFO.md).

### Idempotency

The client sends `Idempotency-Key: <uuid>` on `POST /transfers` and on deposits. The key is stored per user with a SHA-256 hash of the request body, inside the same transaction as the transfer, together with the final response. Three cases:

- New key: process the transfer and store the response
- Same key, same body: return the stored response with the original status code (no new entries)
- Same key, different body: return `422` so a client bug cannot silently reuse a key

If two requests with the same key arrive at once, the second one blocks on the unique index until the first commits, then replays its response. Business rejections such as insufficient funds are stored too, so a retry gets the same answer. Keys expire after 24 hours.

### Auth and rate limiting

Users register and get a short-lived JWT access token (HS256, 15 minutes) from `POST /auth/token`. Passwords are hashed with Argon2. Every account and transfer query is scoped to the token's user id, so guessing another account's id returns `404`. Rate limiting is a token bucket in Redis, implemented as a small Lua script so the read-and-decrement is atomic. If Redis is down the limiter fails open and logs a warning, because rate limiting protects capacity while correctness is guaranteed by PostgreSQL.

### Outbox and audit log

The transfer transaction also inserts a `transfer.completed` or `transfer.rejected` row into `outbox_events`. The relay worker selects unpublished rows with `FOR UPDATE SKIP LOCKED`, publishes them to a Redis Stream with `XADD`, and marks them published. Delivery is at-least-once, so each event carries an `event_id` that consumers use to drop duplicates. The `audit_log` table records who did what (actor, action, entity, request id, IP) and is append-only: a trigger rejects `UPDATE` and `DELETE`.

### Testing strategy

Unit tests cover pure logic (balance math, request hashing, token bucket refill). Integration tests run against real PostgreSQL and Redis containers, never mocks, because the guarantees live in the database. The concurrent double-spend test funds a wallet with 100 rupees, fires 50 parallel transfers of 10 rupees from separate connections, and asserts that exactly 10 succeed, the wallet ends at zero, and the ledger checker reports no drift. k6 scripts measure latency at a fixed arrival rate, ramp up to find the error point, and replay the same idempotency keys to confirm zero duplicate transfers.

## Tech stack

| Layer | Tools | Why |
|---|---|---|
| API | FastAPI, Pydantic v2 | Typed request validation, dependency injection for auth and DB sessions, OpenAPI docs generated from the code |
| Database | PostgreSQL 16 | ACID transactions, row-level locks, `SKIP LOCKED`, constraints and triggers for invariants |
| Data access | SQLAlchemy 2 (sync, psycopg 3), Alembic | Explicit transactions and `with_for_update()`; versioned, reviewable migrations |
| Cache and limits | Redis 7 | Atomic Lua token bucket for rate limiting; Redis Stream as the event sink for the outbox relay |
| Auth | PyJWT, Argon2 (pwdlib) | Stateless access tokens; a memory-hard password hash |
| Testing | pytest, pytest-cov, httpx | Fixtures for real Postgres and Redis, concurrent tests, coverage report |
| Load testing | k6 | Arrival-rate scenarios and thresholds on p95 latency and error rate |
| Packaging | Docker, Docker Compose | One command starts API, worker, Postgres and Redis |
| Observability | prometheus-fastapi-instrumentator | `/metrics` for request rate, latency and errors; scraped by Prometheus in CloudShip |
| Quality and CI | ruff, GitHub Actions | Lint and format checks, tests with service containers, image build |

## Project structure

```
IronPay-LedgerAPI/
├── app/
│   ├── main.py              # FastAPI app, routers, error handlers
│   ├── config.py            # settings from environment
│   ├── db.py                # engine and session factory
│   ├── models.py            # SQLAlchemy tables
│   ├── schemas.py           # Pydantic request and response models
│   ├── security.py          # JWT and password hashing
│   ├── ratelimit.py         # Redis token bucket (Lua)
│   ├── routes/              # auth, accounts, transfers, health
│   └── services/            # ledger, transfers, idempotency, outbox, audit
├── worker/
│   └── outbox_relay.py      # publishes outbox rows to a Redis Stream
├── migrations/              # Alembic versions
├── scripts/
│   ├── seed.py              # demo users and wallets
│   └── check_ledger.py      # ledger invariant checker
├── tests/
│   ├── unit/
│   └── integration/         # includes test_double_spend.py
├── loadtest/                # k6 scripts
├── docs/
│   ├── results/             # raw k6, coverage and checker output
│   └── screenshots/
├── .github/workflows/ci.yml
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── alembic.ini
├── pyproject.toml           # ruff and pytest config
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Getting started

**Prerequisites:** Docker with Compose v2. For running tests outside Docker: Python 3.11+. Optional: k6 for local load tests, and `make` (on Windows, use Git Bash or run the `docker compose` commands from the Makefile directly).

```bash
git clone https://github.com/striderzz/IronPay-LedgerAPI.git
cd IronPay-LedgerAPI
cp .env.example .env          # set JWT_SECRET; the other defaults work locally

make up                       # api (runs migrations on start), relay, postgres, redis
make seed                     # demo users asha@example.com / riya@example.com with funded wallets
```

Open http://localhost:8000/docs for the interactive API docs.

```bash
make test                     # ruff + pytest (unit and integration) with coverage
make check-ledger             # ledger invariant check, exits 1 on any drift
make events                   # last 10 events on the ironpay.events Redis Stream
```

Log in and send a transfer (amounts are paise: 25000 = 250 rupees):

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/token -H "Content-Type: application/json" \
  -d '{"email": "asha@example.com", "password": "demo-password-123"}' | jq -r .access_token)
FROM=$(curl -s localhost:8000/accounts -H "Authorization: Bearer $TOKEN" | jq -r '.[0].id')

curl -X POST localhost:8000/transfers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d "{\"from_account_id\": \"$FROM\", \"to_handle\": \"riya@ironpay\", \"amount_minor\": 25000, \"note\": \"dinner\"}"
```

Sending the same request again with the same `Idempotency-Key` returns the first response with `Idempotent-Replayed: true` and moves no money.

**Load tests:** the k6 scripts are in `loadtest/`. The `Load test` workflow (Actions tab, Run workflow) starts PostgreSQL, Redis, the API with 4 uvicorn workers and the relay on one runner, then runs a constant-rate test, a retry storm and a step test, and uploads the raw k6 output.

## Results

Measured on 18 Nov 2026 in [this GitHub Actions run](https://github.com/striderzz/IronPay-LedgerAPI/actions/runs/44235971697): one `ubuntu-latest` runner (4 vCPU, 15 GiB) running the API (uvicorn, 4 workers), PostgreSQL 16, Redis 7 and k6 together, so k6 and the database compete with the API for the same CPUs. Raw output: [docs/results/load-2026-11-18/](docs/results/load-2026-11-18/). Latency on shared runners varies between runs: in an earlier run the same 100/s test had p95 16 ms and the API saturated at 200/s, so treat these as one honest sample, not a guarantee.

| Metric | Value | How it is measured |
|---|---|---|
| p50 latency, `POST /transfers` | 10.6 ms | k6 `constant-arrival-rate`, 100 transfers/s for 60 s (6,001 requests) between 200 funded wallets |
| p95 latency, `POST /transfers` | 51.0 ms (p99 137.6 ms) | Same run; 0% errors |
| Max transfers/sec before errors | 200 | Step test, 30 s per rate (100, 120 ... 200, 250): highest rate with achieved throughput at least 95% of target, errors under 1% and p95 under 500 ms. At 250/s throughput fell to 176/s and p95 rose to 2.1 s |
| Balance drift after N concurrent transfers | 0 | `check_ledger` after the double-spend test (50 parallel transfers, exactly 10 succeed) and after all load runs (debits = credits) |
| Duplicate transfers under retry storm | 0 | 1,201 logical transfers sent 5 times each with the same Idempotency-Key (6,005 requests, 3 sequential plus 2 parallel): 1,201 transfers created |
| Test coverage | 97% | `pytest --cov=app` in CI: 51 tests, unit plus integration against real PostgreSQL and Redis ([output](docs/results/ci-tests-coverage.txt)) |

## Screenshots

| Swagger UI | CI run (tests, image build and push to GHCR) |
|---|---|
| ![Swagger UI](docs/screenshots/swagger-ui.png) | ![CI run](docs/screenshots/ci-run.png) |

## Roadmap

- [x] Phase 1: scaffold (FastAPI app, config, PostgreSQL + Alembic, Docker Compose, health check, Prometheus `/metrics`, pytest, ruff, GitHub Actions CI)
- [x] Phase 2: ledger core (users, accounts and handles, deposits, double-entry transfers with row locks, derived balances, entry history, double-spend test, invariant checker)
- [x] Phase 3: API safety (JWT auth and ownership checks, Idempotency-Key on transfers and deposits, Redis rate limiting, problem details errors)
- [x] Phase 4: events and audit (outbox table, relay worker to Redis Stream, append-only audit log, JSON logs with request id)
- [x] Phase 5: load and results (k6 scenarios, invariant check after load, coverage, numbers in README from docs/results/)
- [x] Phase 6: polish (OpenAPI examples, screenshots, image push to GHCR on main, how-it-works notes in docs/)

## Stretch goals

- **Kafka publishing**: swap the relay's Redis Stream publisher for Kafka (Redpanda in Compose), keyed by account id so events for one account stay ordered
- **Fraud score before approval**: call [FraudSight](https://github.com/striderzz/FraudSight-MLOps) for a score before committing a transfer; high scores move the transfer to a `held` state for review, with a short timeout and a rule-based fallback if FraudSight is down
- **Ledger analytics**: export entries to Parquet and build DuckDB + dbt models for daily settlement totals and rejection rates
- **Reversals**: `POST /transfers/{id}/reversal` that writes compensating entries instead of editing history
- **Optimistic locking variant**: a version-column implementation behind a flag, benchmarked against `FOR UPDATE` with the same k6 scripts
- **Fault injection**: opt-in fault toggles (slow queries, Redis outage) for incident drills

## Docs

- [INFO.md](INFO.md): high-level overview, system design (architecture, data model) and workflow diagrams.
- [INTERVIEW.md](INTERVIEW.md): 30-second and 2-minute pitches, interview questions with answers, resume bullets.

## Related projects

- [CloudShip DevOps](https://github.com/striderzz/CloudShip-DevOps): deploys IronPay to AWS
- [FraudSight MLOps](https://github.com/striderzz/FraudSight-MLOps): can score IronPay transfers for fraud (stretch goal)

## Author

Hasan · [GitHub](https://github.com/striderzz) · [LinkedIn](https://www.linkedin.com/in/hasan-m-4b1bba315) · [Portfolio](https://striderzz.github.io/portfolio-website)

## License

MIT
