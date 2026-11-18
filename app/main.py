"""FastAPI application."""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.routes import accounts, auth, health, transfers

app = FastAPI(
    title="IronPay LedgerAPI",
    version="0.2.0",
    description="UPI-style payments API with a double-entry ledger in PostgreSQL.",
)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transfers.router)

# Request rate, latency and error metrics at /metrics for Prometheus.
Instrumentator().instrument(app).expose(app, include_in_schema=False)
