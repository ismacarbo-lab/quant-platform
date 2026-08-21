"""Corporate actions are stored, not applied."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.data.reference_csv import (
    load_corporate_actions_csv,
    load_exchanges_csv,
)
from quant_platform.data.repository import (
    create_corporate_action,
    create_exchange,
    list_corporate_actions,
    upsert_instrument,
)
from quant_platform.data.validation import DataValidationError

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def test_corporate_actions_are_stored_not_transformed(db_session: Session) -> None:
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session, symbol=_unique("FICT"), asset_class="equity", exchange_id=venue.id
    )
    split = create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 6, 10, tzinfo=UTC),
        available_time=datetime(2024, 6, 1, 20, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("4"),
        note="fictional",
    )
    assert split.action_type == "split"
    known_before_announcement = list_corporate_actions(
        db_session,
        instrument_id=instrument.id,
        as_of=datetime(2024, 5, 31, tzinfo=UTC),
    )
    assert known_before_announcement == []
    known_after_announcement = list_corporate_actions(
        db_session,
        instrument_id=instrument.id,
        as_of=datetime(2024, 6, 2, tzinfo=UTC),
    )
    assert [row.id for row in known_after_announcement] == [split.id]


def test_invalid_corporate_action_type_is_rejected(db_session: Session) -> None:
    instrument = upsert_instrument(
        db_session, symbol=_unique("BAD"), asset_class="equity"
    )
    with pytest.raises(DataValidationError, match="unsupported corporate action"):
        create_corporate_action(
            db_session,
            instrument_id=instrument.id,
            action_type="merger",
            effective_time=datetime(2024, 6, 10, tzinfo=UTC),
            available_time=datetime(2024, 6, 1, tzinfo=UTC),
        )


def test_corporate_actions_csv_fixture(db_session: Session) -> None:
    assert load_exchanges_csv(db_session, FIXTURES / "exchanges.csv") == 2
    assert (
        load_corporate_actions_csv(db_session, FIXTURES / "corporate_actions.csv") == 3
    )
    instrument = upsert_instrument(
        db_session,
        symbol="FICT",
        asset_class="equity",
        exchange="XNYS",
        currency="USD",
    )
    types = {
        row.action_type
        for row in list_corporate_actions(db_session, instrument_id=instrument.id)
    }
    assert types == {"split", "dividend", "symbol_change"}
