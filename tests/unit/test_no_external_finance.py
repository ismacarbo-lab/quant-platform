"""The foundation must start without financial vendors or brokers."""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_platform.api.app import create_app
from quant_platform.core.config import Settings
from quant_platform.storage.database import create_db_engine

FORBIDDEN_IMPORT_ROOTS = (
    "ccxt",
    "yfinance",
    "alpaca",
    "ib_insync",
    "ibapi",
    "polygon",
    "binance",
    "kucoin",
    "metaapi",
    "oanda",
    "fxcmpy",
    "tvdatafeed",
    "pandas_ta",
    "backtrader",
    "vectorbt",
    "zipline",
    "quantconnect",
)


def test_create_app_without_vendor_env(
    monkeypatch: pytest.MonkeyPatch, research_settings: Settings
) -> None:
    for key in list(os.environ):
        upper = key.upper()
        if any(
            token in upper
            for token in ("API_KEY", "TOKEN", "BROKER", "SECRET", "POLYGON", "ALPACA")
        ):
            monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app(research_settings))
    assert client.get("/health").status_code == 200


def test_financial_sdks_are_not_imported(research_settings: Settings) -> None:
    create_app(research_settings)
    loaded = set(sys.modules)
    for name in FORBIDDEN_IMPORT_ROOTS:
        assert name not in loaded
        assert not any(mod == name or mod.startswith(f"{name}.") for mod in loaded)


def test_src_does_not_import_financial_sdks() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module.split(".", 1)[0]]
            else:
                continue
            for module in modules:
                if module in FORBIDDEN_IMPORT_ROOTS:
                    offenders.append(f"{path}:{module}")
    assert offenders == []


def test_engine_dialect_is_postgresql(research_settings: Settings) -> None:
    engine = create_db_engine(research_settings)
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.url.get_backend_name() == "postgresql"
    finally:
        engine.dispose()
