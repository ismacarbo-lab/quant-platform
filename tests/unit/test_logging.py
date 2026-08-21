"""Structured logging and run_id binding."""

from __future__ import annotations

import json
import logging
from io import StringIO

from hypothesis import given
from hypothesis import settings as hy_settings
from hypothesis import strategies as st

from quant_platform.core.ids import new_run_id
from quant_platform.monitoring.logging import (
    JsonLogFormatter,
    RunIdFilter,
    bound_run_id,
    configure_logging,
    get_logger,
    get_run_id,
)


def test_new_run_id_is_non_empty_unique() -> None:
    first = new_run_id()
    second = new_run_id()
    assert first != second
    assert len(first) >= 32


@hy_settings(max_examples=15)
@given(st.integers(min_value=2, max_value=25))
def test_run_ids_are_unique_in_a_batch(n: int) -> None:
    values = {new_run_id() for _ in range(n)}
    assert len(values) == n


def test_bound_run_id_is_visible_to_get_run_id() -> None:
    assert get_run_id() is None
    with bound_run_id("run-test-1") as bound:
        assert bound == "run-test-1"
        assert get_run_id() == "run-test-1"
    assert get_run_id() is None


def test_json_log_contains_required_fields() -> None:
    configure_logging()
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RunIdFilter())
    log = get_logger("tests.logging")
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False

    with bound_run_id("corr-42"):
        log.info("foundation_boot")

    payload = json.loads(stream.getvalue())
    assert payload["timestamp"].endswith("+00:00")
    assert payload["level"] == "INFO"
    assert payload["component"] == "quant_platform.tests.logging"
    assert payload["message"] == "foundation_boot"
    assert payload["run_id"] == "corr-42"


def test_secret_like_extra_fields_are_redacted() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    log = get_logger("tests.redact")
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("should_not_leak", extra={"api_key": "should-not-appear", "token": "nope"})
    payload = json.loads(stream.getvalue())
    assert payload["api_key"] == "[redacted]"
    assert payload["token"] == "[redacted]"
    assert "should-not-appear" not in stream.getvalue()


def test_database_url_password_is_redacted_in_log_message() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    log = get_logger("tests.url")
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info(
        "connect %s",
        "postgresql+psycopg://quant:leaked-pass@127.0.0.1:5434/quant_platform",
    )
    rendered = stream.getvalue()
    assert "leaked-pass" not in rendered
    payload = json.loads(rendered)
    assert "[redacted]" in payload["message"]
