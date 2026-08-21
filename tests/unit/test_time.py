"""UTC clock invariants."""

from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path

from hypothesis import given
from hypothesis import settings as hy_settings
from hypothesis import strategies as st

from quant_platform.core.time import utc_now


def test_utc_now_is_timezone_aware_utc() -> None:
    ts = utc_now()
    assert ts.tzinfo is not None
    assert ts.utcoffset() == timedelta(0)
    assert ts.tzinfo is UTC


@hy_settings(max_examples=20)
@given(st.integers(min_value=1, max_value=10))
def test_utc_now_repeated_calls_stay_aware_utc(n: int) -> None:
    stamps = [utc_now() for _ in range(n)]
    for ts in stamps:
        assert ts.tzinfo is UTC
    assert stamps[-1] >= stamps[0]


def test_src_does_not_call_naive_datetime_now() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "datetime.now()" in text:
            offenders.append(str(path.relative_to(src.parent.parent)))
    assert offenders == []
