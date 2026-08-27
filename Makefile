.PHONY: lint format format-check typecheck test test-fast test-postgres check-db migrate compose-config quality policy-regression architecture-check research-release-check research-status

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

policy-regression:
	uv run python scripts/run-policy-regression-matrix.py

architecture-check:
	uv run pytest tests/unit/test_architecture_boundaries.py tests/unit/test_config.py tests/integration/test_local_infra.py

research-release-check:
	uv run python scripts/research-release-check.py

research-status:
	uv run python scripts/research-status.py

quality: lint format-check typecheck test-fast compose-config
