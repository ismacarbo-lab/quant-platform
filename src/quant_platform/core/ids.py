"""Correlation identifiers for run/trace logging."""

from uuid import uuid4


def new_run_id() -> str:
    """Return a new opaque run/correlation id (UUID4)."""
    return str(uuid4())
