.PHONY: lint format format-check typecheck test test-fast test-postgres check-db migrate compose-config quality

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src

test:
	uv run pytest

test-fast:
	uv run pytest -m "not postgres"

test-postgres:
	uv run pytest -m postgres

check-db:
	uv run python scripts/check-db.py

migrate:
	uv run alembic upgrade head

compose-config:
	docker compose config

quality: lint format-check typecheck test-fast compose-config
