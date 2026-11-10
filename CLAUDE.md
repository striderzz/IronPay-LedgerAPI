# CLAUDE.md: Ironbank build guide

This file tells Claude (Claude Code) how to build this project. Read **README.md** first: it is the design spec. This file is the build plan.

## Goal

A UPI-style payments API: accounts and a double-entry ledger in PostgreSQL, idempotent transfers, Redis rate limiting, an XGBoost fraud score on every transfer (model tracked in MLflow), payment events streamed through Redpanda into DuckDB with dbt models, and a k6 load test.

## Tech stack

Python 3.11 (pip + requirements.txt), FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL 16, Redis, Redpanda (Kafka API) with confluent-kafka, XGBoost, scikit-learn, MLflow, DuckDB, dbt-duckdb, k6, Docker Compose, GitHub Actions. LLM layer: anthropic and openai Python SDKs, python-dotenv, pydantic-settings.

## Build order (phases)

1. Scaffold: FastAPI app, Postgres + Alembic, docker compose, pytest, CI.
2. Provider layer `llm/`: Claude (anthropic SDK), OpenAI (openai SDK), custom OpenAI-compatible endpoint; `.env` + Settings page (or env vars / GitHub secrets where there is no UI) with masked keys and Test connection; per-call token/cost log; monthly budget cap; fake provider for tests.
3. Accounts, ledger and `POST /transfers` with balanced debit/credit entries and row locking; tests for balances and concurrency.
4. Idempotency keys (Postgres table + Redis cache) and Redis rate limiting; retry test showing zero duplicates.
5. Fraud model: notebook trained on a public fraud dataset (e.g. PaySim), logged to MLflow, loaded by the API; high-risk transfers held for review.
6. Publish payment events to Redpanda; consumer loads them into DuckDB; dbt models (daily settlement, failure rate, fraud flags) with tests.
7. AI features: Claude fraud explainer (structured JSON verdict from score + SHAP + history) and 'Ask your ledger' (tool use writes read-only SQL over DuckDB, validated SELECT-only on approved tables); compare Claude / OpenAI / custom on 50 labelled held transfers.
8. k6 load test; save results; screenshots; README numbers; demo GIF.

## Working rules for Claude

- Keep the scope at the level in README.md: this is a portfolio project for a master's graduate with about a year of experience. Do not add components the README does not list. The owner must be able to explain every line in an interview.
- Build **one phase at a time**, in order. Each phase must run end to end before the next starts.
- After each phase, update the **Roadmap checklist in README.md** and commit with a clear message.
- **Never invent results.** Every number in README.md (accuracy, latency, throughput, cost) must come from a run in this repo. Save the raw output in `docs/results/`.
- **Screenshots:** when a phase produces something visible (UI, dashboard, Grafana, MLflow, test or load-test report), capture real screenshots into `docs/screenshots/` and embed them in README.md. Never mock them up.
- Keep secrets out of git: `.env` (gitignored) plus a committed `.env.example`.
- Never commit datasets or large model files. Write download scripts and gitignore the data folders.
- Python 3.11+. Dependencies live in a pinned `requirements.txt` (runtime) and `requirements-dev.txt` (pytest, ruff). Setup is `pip install -r requirements.txt`. Use `ruff` for lint/format, type hints, and `pytest` for tests.
- **LLM rules:**
  - Every LLM call goes through the `llm/` provider layer: Claude through the official `anthropic` SDK; OpenAI through the official `openai` SDK; a "custom" provider through the `openai` SDK with a user-supplied `base_url`, API key and model name (for Gemini, Groq, DeepSeek, OpenRouter, Ollama and others).
  - Keys come from `.env` (with a committed `.env.example`) or from the app's Settings page. Settings are saved to a gitignored `settings.local.json`, keys are masked in the UI and never logged, and the page has a "Test connection" button.
  - Defaults are `claude-opus-5-5` for main reasoning steps and `claude-haiku-5-5` for bulk steps. Both are configurable per feature.
  - Log tokens and cost for every call, and enforce a monthly budget cap (`LLM_MONTHLY_BUDGET_USD`).
  - Check `stop_reason` (including `refusal`) before reading a response. Use structured outputs for JSON. Put stable prompts first and use prompt caching. Run offline evals with the Message Batches API.
  - Tests use a fake provider, so CI never spends money or needs keys.
- `docker compose up` must bring up the demo locally.
- Add a GitHub Actions workflow (lint + tests) in Phase 1 and keep it green.
- Prefer small, readable modules. Add a short "How it works" note to `docs/` after each phase.

## Definition of done

- One-command local demo (`docker compose up` or the documented command)
- README has the architecture diagram, setup steps, real screenshots, a demo GIF and measured results
- CI is green and tests cover the core logic

## Status

Only `README.md` and this file exist so far. Start at **Phase 1**.
