"""FastAPI application."""

import logging

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app import problems
from app.config import get_settings
from app.routes import accounts, auth, health, transfers

log = logging.getLogger(__name__)

app = FastAPI(
    title="IronPay LedgerAPI",
    version="0.3.0",
    description="UPI-style payments API with a double-entry ledger in PostgreSQL.",
)
problems.install(app)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transfers.router)

# Request rate, latency and error metrics at /metrics for Prometheus.
Instrumentator().instrument(app).expose(app, include_in_schema=False)

if get_settings().jwt_secret == "dev-only-change-me":
    log.warning("JWT_SECRET is the development default; set a long random value in .env")
