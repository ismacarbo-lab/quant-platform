"""Infrastructure constraints that do not require a running database."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_exposes_postgres_on_localhost_only() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "127.0.0.1:5434:5432" in text
    assert "0.0.0.0" not in text


def test_env_example_has_no_live_mode_and_uses_postgres() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "APP_MODE=research" in text
    assert "APP_MODE=live" not in text
    assert "postgresql+psycopg://" in text
    url_lines = [line for line in text.splitlines() if line.startswith("DATABASE_URL=")]
    assert url_lines
    assert "sqlite" not in url_lines[0].lower()


def test_env_is_gitignored_and_example_is_tracked() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = {
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert ".env" in lines
    assert ".env.*" in lines
    assert "!.env.example" in lines
    assert (ROOT / ".env.example").is_file()


def test_ci_workflow_does_not_require_github_secrets() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "secrets." not in workflow
    assert "APP_MODE: research" in workflow
    assert 'pytest -m "not postgres"' in workflow
    assert "pytest -m postgres" in workflow
    assert "alembic upgrade head" in workflow
    assert "run-policy-regression-matrix.py" in workflow
    assert "run-normalization-regression.py" in workflow
    assert "research-release-check.py" in workflow
    assert "test_architecture_boundaries.py" in workflow
    assert "--skip-db" in workflow
    assert "--skip-compose" in workflow
    assert "--skip-regression" in workflow


def test_makefile_has_release_targets() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "research-release-check" in text
    assert "policy-regression" in text
    assert "normalization-regression" in text
    assert "architecture-check" in text
    assert "quality: lint format-check typecheck test-fast compose-config" in text


def test_scripts_do_not_print_database_url() -> None:
    for path in sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "print(settings.database_url)" not in lowered
        assert 'print(os.environ["database_url"])' not in lowered
        assert "print(os.environ['database_url'])" not in lowered


def test_alembic_ini_uses_postgres_not_sqlite() -> None:
    text = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert "postgresql" in text
    assert "sqlite" not in text.lower()
