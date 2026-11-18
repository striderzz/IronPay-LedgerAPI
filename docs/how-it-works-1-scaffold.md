# How it works: scaffold (Phase 1)

- **App:** `app/main.py` builds the FastAPI app, mounts `/health` and exposes Prometheus metrics at `/metrics` through `prometheus-fastapi-instrumentator`.
- **Config:** `app/config.py` reads `DATABASE_URL`, `REDIS_URL` and `LOG_LEVEL` from the environment or `.env` with pydantic-settings.
- **Database:** `app/db.py` creates one SQLAlchemy engine (psycopg 3 driver, `pool_pre_ping`) and a session per request. Alembic (`migrations/`) owns the schema; `env.py` takes the URL from the same settings.
- **Health:** `/health` runs `SELECT 1` on PostgreSQL and `PING` on Redis. PostgreSQL down returns `503`; Redis down is reported but still `200`, because Redis only backs rate limiting (fail open) and the event stream, while money correctness lives in PostgreSQL.
- **Local stack:** `docker compose up` starts PostgreSQL 16, Redis 7 and the API. The API container runs `alembic upgrade head` before `uvicorn`.
- **Tests:** unit tests run anywhere. Integration tests need real PostgreSQL and Redis; locally they skip when the services are missing, and in CI `REQUIRE_INTEGRATION=1` makes a missing service a failure instead of a skip.
- **CI:** GitHub Actions runs ruff (lint and format check), Alembic migrations and pytest with coverage against PostgreSQL and Redis service containers, and builds the Docker image in a second job.
