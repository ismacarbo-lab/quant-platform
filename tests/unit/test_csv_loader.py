"""Local CSV loader tests. No network."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest

from quant_platform.data.csv_loader import (
    CsvLoadError,
    ErrorMode,
    load_daily_bars_csv,
    parse_csv_file,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "daily_bars_sample.csv"


def test_loads_sample_fixture() -> None:
    rows = load_daily_bars_csv(FIXTURE)
    assert len(rows) == 3
    assert {row.symbol for row in rows} == {"FIXT", "DEMO"}
    first = rows[0]
    assert first.observation_time.tzinfo is UTC
    assert first.available_time.tzinfo is UTC
    assert first.available_time > first.observation_time
    assert first.observation_time.day == 2


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CsvLoadError, match="not found"):
        load_daily_bars_csv(tmp_path / "missing.csv")


def test_rejects_lookahead_row(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "symbol,date,open,high,low,close,volume,available_time\n"
        "X,2024-01-02,1,1,1,1,1,2024-01-02T00:00:00Z\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvLoadError, match="row 2"):
        load_daily_bars_csv(path)


def test_rejects_naive_available_time(tmp_path: Path) -> None:
    path = tmp_path / "naive.csv"
    path.write_text(
        "symbol,date,open,high,low,close,volume,available_time\n"
        "X,2024-01-02,1,2,1,1,1,2024-01-03T00:00:00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvLoadError, match="timezone"):
        load_daily_bars_csv(path)


def test_rejects_invalid_ohlc(tmp_path: Path) -> None:
    path = tmp_path / "ohlc.csv"
    path.write_text(
        "symbol,date,open,high,low,close,volume,available_time\n"
        "X,2024-01-02,10,8,9,10,1,2024-01-03T00:00:00Z\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvLoadError, match="high must be >= low"):
        load_daily_bars_csv(path)


def test_collect_errors_continues_after_invalid_row(tmp_path: Path) -> None:
    mixed = Path(__file__).resolve().parents[1] / "fixtures" / "daily_bars_mixed.csv"
    accepted, rejected = parse_csv_file(mixed, error_mode=ErrorMode.COLLECT_ERRORS)
    assert len(accepted) == 2
    assert len(rejected) == 1
    assert rejected[0].record_index == 1
    assert rejected[0].error_code == "invalid_ohlc"


def test_fail_fast_parse_raises_on_first_invalid_row() -> None:
    mixed = Path(__file__).resolve().parents[1] / "fixtures" / "daily_bars_mixed.csv"
    with pytest.raises(CsvLoadError, match="row 3"):
        parse_csv_file(mixed, error_mode=ErrorMode.FAIL_FAST)
