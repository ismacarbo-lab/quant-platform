.PHONY: lint format format-check typecheck test test-fast test-postgres check-db migrate compose-config quality policy-regression normalization-regression data-contract-conformance data-contract-conformance-regression data-contract-schema-export data-contract-schema-compatibility contract-payload-intake contract-payload-intake-regression architecture-check research-release-check research-status research-evidence-bundle verify-research-evidence-bundle normalization-status fetch-data backtest-all paper-run paper-replay dashboard-install dashboard-typecheck dashboard-build dashboard-dev app

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

data-contract-conformance:
	uv run python scripts/run-data-contract-conformance.py --json

data-contract-conformance-regression:
	uv run python scripts/run-data-contract-conformance-regression.py

data-contract-schema-export:
	uv run python scripts/export-data-contract-schemas.py --json

data-contract-schema-compatibility:
	uv run python scripts/check-data-contract-schema-compatibility.py

contract-payload-intake:
	uv run python scripts/run-contract-payload-intake.py --json

contract-payload-intake-regression:
	uv run python scripts/run-contract-payload-intake-regression.py

normalization-status:
	uv run python scripts/normalization-status.py

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

# --- Paper-trading pivot (ADR 0005) -----------------------------------------

# Download real daily data (Yahoo Finance) into the PIT store. Incremental.
fetch-data:
	uv run python scripts/fetch-market-data.py --include-crypto

# Backtest every registered strategy with costs + walk-forward and rank them.
backtest-all:
	uv run python scripts/run-strategy-backtest.py

# Daily paper run (fictional money). Requires APP_MODE=paper.
paper-run:
	APP_MODE=paper uv run python scripts/paper-run.py --fetch

# Build a simulated track record from a past date (replayed sessions).
# Usage: make paper-replay FROM=2024-01-02
paper-replay:
	APP_MODE=paper uv run python scripts/paper-run.py --replay-from $(FROM)

dashboard-install:
	cd dashboard && npm install --no-audit --no-fund

dashboard-typecheck:
	cd dashboard && npm run typecheck

dashboard-build:
	cd dashboard && npm run build

# Vite dev server with API proxy (run `make app` in another terminal).
dashboard-dev:
	cd dashboard && npm run dev

# API + built dashboard on http://127.0.0.1:8000 (paper mode).
app:
	APP_MODE=paper uv run uvicorn quant_platform.api.app:app --host 127.0.0.1 --port 8000

quality: lint format-check typecheck test-fast compose-config
