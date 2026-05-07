"""Phase 8 — rapid-send detection."""
from __future__ import annotations

import time

from tgcli.safety import RapidSendWatcher


def test_rapid_send_quiet_under_threshold():
    w = RapidSendWatcher(threshold=5, window_seconds=60)
    for _ in range(4):
        assert w.check_and_warn() is None


def test_rapid_send_warns_at_threshold():
    w = RapidSendWatcher(threshold=3, window_seconds=60)
    w.check_and_warn()
    w.check_and_warn()
    msg = w.check_and_warn()
    assert msg is not None
    assert "rapid send" in msg.lower()


def test_rapid_send_resets_after_window():
    w = RapidSendWatcher(threshold=2, window_seconds=0.05)
    w.check_and_warn()
    w.check_and_warn()
    assert w.check_and_warn() is not None
    time.sleep(0.06)
    assert w.check_and_warn() is None
