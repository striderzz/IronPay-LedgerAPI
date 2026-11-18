FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/striderzz/IronPay-LedgerAPI" \
      org.opencontainers.image.description="IronPay LedgerAPI: payments API with a double-entry ledger" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts

RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
