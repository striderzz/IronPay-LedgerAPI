"""FastAPI application."""

import logging

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app import problems
from app.config import get_settings
from app.logging_setup import RequestContextMiddleware, configure_logging
from app.routes import accounts, auth, health, transfers

configure_logging(get_settings().log_level)
log = logging.getLogger(__name__)

DESCRIPTION = """
UPI-style payments API with a **double-entry ledger** in PostgreSQL.

- Amounts are integer **paise** (`amount_minor`): `25000` is 250 rupees.
- Authenticate with `POST /auth/token`, then send `Authorization: Bearer <token>`.
- `POST /transfers` and `POST /deposits` need an **`Idempotency-Key`** header; a retry
  with the same key replays the first response instead of moving money twice.
- Errors are RFC 9457 `application/problem+json`.
"""

TAGS = [
    {"name": "auth", "description": "Register, log in for a 15-minute JWT, read the current user."},
    {
        "name": "accounts",
        "description": "Your wallets, balances (derived from entries) and history.",
    },
    {"name": "transfers", "description": "Deposits and transfers; idempotent and rate limited."},
    {"name": "health", "description": "PostgreSQL and Redis checks."},
]

app = FastAPI(
    title="IronPay LedgerAPI",
    version="0.6.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
)
problems.install(app)
app.add_middleware(RequestContextMiddleware)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transfers.router)

# Request rate, latency and error metrics at /metrics for Prometheus.
Instrumentator().instrument(app).expose(app, include_in_schema=False)

if get_settings().jwt_secret == "dev-only-change-me":
    log.warning("JWT_SECRET is the development default; set a long random value in .env")
