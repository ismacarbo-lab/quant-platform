"""Dashboard API without PostgreSQL: catalog, jobs, mode guards."""

from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient

from quant_platform.api.app import create_app
from quant_platform.api.jobs import JobRegistry
from quant_platform.core.config import Settings


def _client(mode: str = "research") -> TestClient:
    settings = Settings(_env_file=None, app_mode=mode, dashboard_dist_dir="")
    return TestClient(create_app(settings))


def test_health_still_works_and_reports_mode() -> None:
    client = _client("paper")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "paper"


def test_strategies_catalog() -> None:
    client = _client()
    response = client.get("/api/strategies")
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["strategies"]]
    assert "trend_following" in names and "buy_and_hold" in names
    detail = client.get("/api/strategies/dual_momentum")
    assert detail.status_code == 200
    assert detail.json()["is_benchmark"] is False
    assert client.get("/api/strategies/nope").status_code == 404


def test_paper_mutations_require_paper_mode() -> None:
    client = _client("research")
    run = client.post("/api/paper/run", json={})
    assert run.status_code == 409
    create = client.post(
        "/api/paper/accounts", json={"name": "x", "strategy_name": "buy_and_hold"}
    )
    assert create.status_code == 409


def test_backtest_run_validates_strategy_names() -> None:
    client = _client()
    response = client.post("/api/backtests/run", json={"strategies": ["nope"]})
    assert response.status_code == 404
    bad_params = client.post(
        "/api/backtests/run",
        json={"strategies": ["trend_following", "dual_momentum"], "params": {"a": 1}},
    )
    assert bad_params.status_code == 400


def test_job_registry_runs_in_background_and_records_failures() -> None:
    registry = JobRegistry(max_jobs=3)
    ok = registry.submit("demo", lambda: {"value": 1})
    failing = registry.submit(
        "demo", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    deadline = time.time() + 5
    while time.time() < deadline and any(
        job.status in ("queued", "running") for job in (ok, failing)
    ):
        time.sleep(0.01)
    assert ok.status == "succeeded"
    assert ok.result == {"value": 1}
    assert failing.status == "failed"
    assert failing.error is not None and "boom" in failing.error
    assert registry.get(ok.id) is ok
    assert len(registry.recent()) == 2
    assert registry.running() == []


def test_jobs_endpoints() -> None:
    client = _client()
    assert client.get("/api/jobs").json() == {"jobs": []}
    assert client.get("/api/jobs/missing").status_code == 404


def test_app_import_does_not_load_vendor_sdk() -> None:
    _client()
    assert "yfinance" not in sys.modules
