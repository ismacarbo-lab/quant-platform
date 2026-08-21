"""Instrument natural key, exchanges, and local identifiers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_platform.data.models import Instrument
from quant_platform.data.repository import (
    create_exchange,
    create_identifier,
    list_exchanges,
    list_instrument_identifiers,
    upsert_instrument,
)
from quant_platform.data.validation import DataValidationError

pytestmark = pytest.mark.postgres


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def test_same_symbol_different_exchanges_are_distinct(db_session: Session) -> None:
    symbol = _unique("AAPL")
    nyse = create_exchange(
        db_session, code=_unique("XNYS"), timezone="America/New_York"
    )
    nasdaq = create_exchange(
        db_session, code=_unique("XNAS"), timezone="America/New_York"
    )
    listed_nyse = upsert_instrument(
        db_session,
        symbol=symbol,
        asset_class="equity",
        exchange_id=nyse.id,
        currency="USD",
    )
    listed_nasdaq = upsert_instrument(
        db_session,
        symbol=symbol,
        asset_class="equity",
        exchange_id=nasdaq.id,
        currency="USD",
    )
    assert listed_nyse.id != listed_nasdaq.id
    crypto = upsert_instrument(
        db_session,
        symbol=symbol,
        asset_class="crypto",
        exchange_id=nasdaq.id,
        currency="USD",
    )
    assert crypto.id != listed_nasdaq.id


def test_duplicate_natural_key_is_rejected(db_session: Session) -> None:
    symbol = _unique("DUP")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    upsert_instrument(
        db_session,
        symbol=symbol,
        asset_class="equity",
        exchange_id=venue.id,
        currency="USD",
    )
    db_session.flush()
    db_session.add(
        Instrument(
            symbol=symbol,
            asset_class="equity",
            exchange_id=venue.id,
            currency="USD",
        )
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


def test_unknown_exchange_code_is_rejected(db_session: Session) -> None:
    with pytest.raises(DataValidationError, match="unknown exchange"):
        upsert_instrument(
            db_session,
            symbol=_unique("UNK"),
            asset_class="equity",
            exchange="NO_SUCH_VENUE",
        )


def test_create_exchange_is_idempotent_by_code(db_session: Session) -> None:
    code = _unique("MIC")
    first = create_exchange(
        db_session, code=code, timezone="America/New_York", mic="XNYS", country="US"
    )
    second = create_exchange(db_session, code=code, timezone="UTC")
    assert first.id == second.id
    assert second.timezone == "America/New_York"
    assert {row.code for row in list_exchanges(db_session)} >= {code}


def test_instrument_identifiers_round_trip(db_session: Session) -> None:
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session, symbol=_unique("ID"), asset_class="equity", exchange_id=venue.id
    )
    create_identifier(
        db_session,
        instrument_id=instrument.id,
        namespace="local_symbol",
        value=instrument.symbol,
    )
    create_identifier(
        db_session,
        instrument_id=instrument.id,
        namespace="figi",
        value="BBG_TEST_ONLY",
    )
    found = list_instrument_identifiers(db_session, instrument_id=instrument.id)
    assert {row.namespace for row in found} == {"local_symbol", "figi"}


def test_invalid_identifier_namespace_is_rejected(db_session: Session) -> None:
    instrument = upsert_instrument(
        db_session, symbol=_unique("NS"), asset_class="equity"
    )
    with pytest.raises(DataValidationError, match="unsupported identifier"):
        create_identifier(
            db_session,
            instrument_id=instrument.id,
            namespace="figi_placeholder",
            value="nope",
        )
