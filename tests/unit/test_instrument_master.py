"""Session kinds and identifier namespaces without a database."""

from __future__ import annotations

from quant_platform.data.models import (
    ALLOWED_CORPORATE_ACTION_TYPES,
    ALLOWED_IDENTIFIER_NAMESPACES,
    session_kind_is_open,
)


def test_open_session_kinds() -> None:
    assert session_kind_is_open("open") is True
    assert session_kind_is_open("half_session") is True
    assert session_kind_is_open("holiday") is False
    assert session_kind_is_open("exceptional_close") is False


def test_allowed_identifier_namespaces() -> None:
    assert ALLOWED_IDENTIFIER_NAMESPACES == {
        "isin",
        "figi",
        "cusip",
        "local_symbol",
        "vendor_symbol",
    }


def test_allowed_corporate_action_types() -> None:
    assert ALLOWED_CORPORATE_ACTION_TYPES == {
        "split",
        "reverse_split",
        "dividend",
        "symbol_change",
        "delisting",
    }
