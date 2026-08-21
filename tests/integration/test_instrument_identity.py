"""Instrument natural key and local identifiers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_platform.data.models import Instrument
from quant_platform.data.repository import (
    insert_instrument_identifier,
    list_instrument_identifiers,
    upsert_instrument,
)

pytestmark = pytest.mark.postgres


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def test_same_symbol_different_exchanges_are_distinct(db_session: Session) -> None:
    symbol = _unique("AAPL")
    nyse = upsert_instrument(
        db_session, symbol=symbol, asset_class="equity", exchange="XNYS", currency="USD"
    )
    nasdaq = upsert_instrument(
        db_session, symbol=symbol, asset_class="equity", exchange="XNAS", currency="USD"
    )
    assert nyse.id != nasdaq.id
    crypto = upsert_instrument(
        db_session, symbol=symbol, asset_class="crypto", exchange="XNAS", currency="USD"
    )
    assert crypto.id != nasdaq.id


def test_duplicate_natural_key_is_rejected(db_session: Session) -> None:
    symbol = _unique("DUP")
    upsert_instrument(
        db_session, symbol=symbol, asset_class="equity", exchange="XNYS", currency="USD"
    )
    db_session.flush()
    db_session.add(
        Instrument(symbol=symbol, asset_class="equity", exchange="XNYS", currency="USD")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_null_exchange_collides_under_nulls_not_distinct(db_session: Session) -> None:
    symbol = _unique("NUL")
    first = upsert_instrument(
        db_session, symbol=symbol, asset_class="equity", exchange=None, currency=None
    )
    again = upsert_instrument(
        db_session, symbol=symbol, asset_class="equity", exchange=None, currency=None
    )
    assert first.id == again.id


def test_instrument_identifiers_round_trip(db_session: Session) -> None:
    instrument = upsert_instrument(
        db_session, symbol=_unique("ID"), asset_class="equity", exchange="XNYS"
    )
    insert_instrument_identifier(
        db_session,
        instrument_id=instrument.id,
        namespace="local_symbol",
        value=instrument.symbol,
    )
    insert_instrument_identifier(
        db_session,
        instrument_id=instrument.id,
        namespace="figi_placeholder",
        value="BBG_TEST_ONLY",
    )
    found = list_instrument_identifiers(db_session, instrument_id=instrument.id)
    assert {row.namespace for row in found} == {"local_symbol", "figi_placeholder"}
