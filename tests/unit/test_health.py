"""Health endpoint: typed, stable, no external services."""

from __future__ import annotations

from fastapi.testclient import TestClient

from quant_platform import __version__
from quant_platform.api.app import HealthResponse, create_app
from quant_platform.core.config import AppMode, Settings


def test_health_ok_in_research_mode(research_settings: Settings) -> None:
    client = TestClient(create_app(research_settings))
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "quant_platform",
        "version": __version__,
        "mode": "research",
    }
    parsed = HealthResponse.model_validate(body)
    assert parsed.mode is AppMode.RESEARCH
    assert parsed.status == "ok"


def test_health_schema_is_stable(research_settings: Settings) -> None:
    client = TestClient(create_app(research_settings))
    body = client.get("/health").json()
    assert set(body) == {"status", "service", "version", "mode"}
