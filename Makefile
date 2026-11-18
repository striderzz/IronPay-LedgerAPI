.PHONY: up down logs migrate lint fmt test

up:            ## start api, postgres and redis
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api

migrate:       ## apply migrations inside the api container
	docker compose exec api alembic upgrade head

lint:
	ruff check . && ruff format --check .

fmt:
	ruff format . && ruff check --fix .

test: lint     ## needs postgres and redis running (make up)
	alembic upgrade head
	pytest --cov=app --cov-report=term-missing
