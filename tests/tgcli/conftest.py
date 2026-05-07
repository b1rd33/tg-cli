"""Shared pytest fixtures for tests/tgcli."""
from __future__ import annotations

import pytest

from tgcli.safety import OUTBOUND_WRITE_LIMITER


@pytest.fixture(autouse=True)
def _reset_outbound_write_limiter():
    """Reset the process-global write rate limiter between tests.

    OUTBOUND_WRITE_LIMITER is a singleton; without this fixture, accumulated
    events from earlier tests can trip the 20/min cap mid-suite.
    """
    OUTBOUND_WRITE_LIMITER.events.clear()
    yield
    OUTBOUND_WRITE_LIMITER.events.clear()
