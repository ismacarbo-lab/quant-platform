"""PIT-visible corporate actions for normalization. Does not rewrite silver."""

from __future__ import annotations

from sqlalchemy.orm import Session

from quant_platform.research.datasets import get_visible_corporate_actions
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarsDatasetRequest,
)


def load_visible_corporate_actions(
    session: Session,
    request: DailyBarsDatasetRequest,
) -> tuple[CorporateActionDatasetRow, ...]:
    """Load stored actions knowable at ``as_of``. Window is not restricted.

    ``get_corporate_actions_for_dataset`` still exists for in-window exports.
    Normalization needs later effective times so historical bars can be
    restated. Future ``available_time`` values stay excluded.
    """
    return get_visible_corporate_actions(session, request)
