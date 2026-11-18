.PHONY: up down logs events migrate seed check-ledger lint fmt test

up:            ## start api, postgres and redis
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api relay

events:        ## last 10 events on the Redis Stream
	docker compose exec redis redis-cli XREVRANGE ironpay.events + - COUNT 10

migrate:       ## apply migrations inside the api container
	docker compose exec api alembic upgrade head

seed:          ## demo users and funded wallets
	docker compose exec api python -m scripts.seed

check-ledger:  ## ledger invariant check; exits 1 on drift
	docker compose exec api python -m scripts.check_ledger

lint:
	ruff check . && ruff format --check .

fmt:
	ruff format . && ruff check --fix .

test: lint     ## needs postgres and redis running (make up)
	alembic upgrade head
	pytest --cov=app --cov-report=term-missing
