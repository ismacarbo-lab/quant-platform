"""Dashboard read endpoints against the local PostgreSQL. Requires PostgreSQL."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from quant_platform.api.app import create_app
from quant_platform.core.config import Settings

pytestmark = pytest.mark.postgres


@pytest.fixture
def client(postgres_engine: Engine) -> TestClient:
    del postgres_engine
    settings = Settings(_env_file=None, app_mode="paper", dashboard_dist_dir="")
    return TestClient(create_app(settings))


def test_status_reports_database(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["reachable"] is True
    assert payload["live_trading"] == "disabled"
    assert payload["real_money"] is False
    assert "paper_trading_simulated" in payload["capabilities"]["enabled"]
    assert "DATABASE_URL" not in response.text
    assert "postgresql+psycopg://" not in response.text


def test_universe_and_backtests_and_paper_lists(client: TestClient) -> None:
    universe = client.get("/api/market/universe")
    assert universe.status_code == 200
    symbols = [item["symbol"] for item in universe.json()["instruments"]]
    assert "SPY" in symbols
    ranking = client.get("/api/backtests/ranking")
    assert ranking.status_code == 200
    assert isinstance(ranking.json()["ranking"], list)
    listing = client.get("/api/backtests?limit=5")
    assert listing.status_code == 200
    accounts = client.get("/api/paper/accounts")
    assert accounts.status_code == 200
    assert accounts.json()["paper_enabled"] is True
    assert client.get("/api/paper/accounts/does-not-exist").status_code == 404
    assert client.get("/api/market/bars/NOPE-NOT-THERE").status_code == 404
