.PHONY: lint format format-check typecheck test test-fast test-postgres check-db migrate compose-config quality policy-regression normalization-regression architecture-check research-release-check research-status research-evidence-bundle verify-research-evidence-bundle

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

normalization-regression:
	uv run python scripts/run-normalization-regression.py

architecture-check:
	uv run pytest tests/unit/test_architecture_boundaries.py tests/unit/test_config.py tests/integration/test_local_infra.py

research-release-check:
	uv run python scripts/research-release-check.py

research-status:
	uv run python scripts/research-status.py

research-evidence-bundle:
	uv run python scripts/build-research-evidence-bundle.py \
		--fixture-dir tests/fixtures/e2e_research_bundle \
		--output-dir /tmp/research-evidence-bundle \
		--deterministic-id

verify-research-evidence-bundle:
	uv run python scripts/verify-research-evidence-bundle.py \
		--bundle-dir /tmp/research-evidence-bundle

quality: lint format-check typecheck test-fast compose-config
