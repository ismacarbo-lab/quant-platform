"""Infrastructure constraints that do not require a running database."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_exposes_postgres_on_localhost_only() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "127.0.0.1:5432:5432" in text
    assert "0.0.0.0" not in text


def test_env_example_has_no_live_mode_and_uses_postgres() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "APP_MODE=research" in text
    assert "APP_MODE=live" not in text
    assert "postgresql+psycopg://" in text
    url_lines = [line for line in text.splitlines() if line.startswith("DATABASE_URL=")]
    assert url_lines
    assert "sqlite" not in url_lines[0].lower()
