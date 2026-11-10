# CLAUDE.md: Ironbank build guide

This file tells Claude (Claude Code) how to build this project. Read **README.md** first: it is the design spec. **INFO.md** holds the interview prep and diagrams. This file is the build plan.

## Goal

A small UPI-style payments API built the way fintech teams build their core: users, wallets with UPI-style handles and a system funding account; a double-entry ledger in PostgreSQL where every transfer and deposit writes one balanced debit and credit pair and balances are derived from entries; idempotent transfers via the `Idempotency-Key` header; concurrency safety with `SELECT ... FOR UPDATE` row locks taken in id order; JWT auth; Redis token bucket rate limiting; a transactional outbox with a relay worker publishing to a Redis Stream; an append-only audit log; OpenAPI docs; pytest unit and integration tests (including a concurrent double-spend test and a ledger invariant checker); k6 load tests; Docker Compose; GitHub Actions CI. Sized for one person in about 3–4 weeks.

## Tech stack

Python 3.11 (pip + requirements.txt), FastAPI, Pydantic v2 + pydantic-settings, PostgreSQL 16, SQLAlchemy 2 (sync, psycopg 3) + Alembic, Redis 7, PyJWT, Argon2 via pwdlib, pytest + pytest-cov + httpx, k6, Docker + Docker Compose, GitHub Actions, ruff.

Not in core (see Stretch goals): Kafka/Redpanda, fraud scoring, DuckDB/dbt, any LLM provider.

## Build order (phases)

1. **Scaffold**: FastAPI app, config from env, PostgreSQL + Alembic, Docker Compose (api, postgres, redis), `/health` and Prometheus `/metrics` (prometheus-fastapi-instrumentator; Endurance and Jarvis scrape it), Makefile, pytest + ruff, GitHub Actions CI (lint + tests with Postgres and Redis service containers).
2. **Ledger core**: users, accounts with handles, system funding account, deposits, `POST /transfers` writing balanced entries in one transaction, row locks in ascending id order, balances derived from entries, entry history with keyset pagination, `CHECK` constraints. Tests: balance math, opposite-direction transfers (no deadlock), concurrent double-spend test (100 rupees, 50 parallel 10-rupee transfers, exactly 10 succeed). `scripts/check_ledger.py` invariant checker.
3. **API safety**: JWT auth (register, token, current user), ownership checks on every query, `Idempotency-Key` on transfers and deposits (stored in Postgres in the same transaction, request hash, 24h expiry), Redis token bucket (Lua) per user and per IP on login, `429` with `Retry-After`, RFC 9457 problem details errors. Tests: retry returns the stored response, reused key with a different body returns 422, concurrent same-key requests create one transfer.
4. **Events and audit**: `outbox_events` written in the transfer transaction, relay worker with `FOR UPDATE SKIP LOCKED` publishing to a Redis Stream, `event_id` for consumer dedup, append-only `audit_log` (trigger blocks UPDATE/DELETE), JSON logs with request id.
5. **Load and results**: k6 scenarios (constant arrival rate for p50/p95, ramping arrival rate for max transfers/sec, retry storm for duplicates), invariant check after each run, coverage report. Save raw output to `docs/results/` and fill the README Results table from it.
6. **Polish**: OpenAPI tags and examples, real screenshots (Swagger UI, k6 summary, CI run), image build and push to GHCR on main, short how-it-works notes in `docs/`.

## Stretch goals

Only after Phase 6 is done and the README results are real:

- Kafka publishing from the outbox (Redpanda in Compose, keyed by account id)
- Call Precog (`precog-fraud-mlops`) for a fraud score before approving a transfer; `held` state, short timeout, rule-based fallback
- DuckDB + dbt analytics on ledger exports (daily settlement, rejection rates)
- Reversals through compensating entries
- Optimistic locking variant benchmarked against `FOR UPDATE`
- Opt-in fault toggles (slow queries, Redis outage) for Jarvis incident drills

## Working rules for Claude

- Keep the scope at the level in README.md: this is a portfolio project for a master's graduate with about a year of experience. Do not add components the README does not list. The owner must be able to explain every line in an interview.
- Build **one phase at a time**, in order. Each phase must run end to end before the next starts.
- After each phase, update the **Roadmap checklist in README.md** and commit with a clear message.
- **Never invent results.** Every number in README.md (latency, throughput, drift, coverage, cost) must come from a run in this repo. Save the raw output in `docs/results/`.
- **Screenshots:** when a phase produces something visible (Swagger UI, test or load-test report, CI run), capture real screenshots into `docs/screenshots/` and embed them in README.md. Never mock them up.
- Keep secrets out of git: `.env` (gitignored) plus a committed `.env.example`.
- Never commit datasets or large files. Write download scripts and gitignore the data folders.
- Python 3.11+. Dependencies live in a pinned `requirements.txt` (runtime) and `requirements-dev.txt` (pytest, ruff). Setup is `pip install -r requirements.txt`. Use `ruff` for lint/format, type hints, and `pytest` for tests.
- **Money rules:** amounts are integer paise (`BIGINT`), never floats. Ledger entries are append-only; corrections are new entries. All ledger writes go through one helper that writes both sides and takes locks in id order. Integration tests use real Postgres and Redis, not mocks.
- **LLM rules (only if a stretch goal adds an LLM call):** go through a small provider layer using the official `anthropic` SDK (`claude-opus-5-5` for hard reasoning, `claude-haiku-5-5` for bulk) with the `openai` SDK as an alternative; keys in `.env`; log tokens and cost per call; check `stop_reason` before reading a response; use prompt caching for stable prompts; tests use a fake provider so CI never spends money or needs keys.
- `docker compose up` must bring up the demo locally.
- Add a GitHub Actions workflow (lint + tests) in Phase 1 and keep it green.
- Prefer small, readable modules. Add a short "How it works" note to `docs/` after each phase.

## Definition of done

- One-command local demo (`docker compose up` or the documented command)
- README has the architecture diagram, setup steps, real screenshots and measured results
- CI is green and tests cover the core logic, including the concurrent double-spend test and the invariant checker

## Status

Only `README.md`, `INFO.md` and this file exist so far. Start at **Phase 1**.
