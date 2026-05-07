"""Phase 8 — --full flag disables human-mode truncation."""

from __future__ import annotations

from tgcli.commands.messages import _show_human


def test_show_human_truncates_long_text_by_default(capsys, monkeypatch):
    monkeypatch.delenv("TG_FULL", raising=False)
    data = {
        "chat": {"chat_id": 1, "title": "T"},
        "order": "newest_first",
        "messages": [
            {
                "date": "2026-05-08T10:00:00",
                "is_outgoing": False,
                "text": "x" * 500,
                "media_type": None,
            }
        ],
    }
    _show_human(data)
    out = capsys.readouterr().out
    # Truncated body: indicator present and total line shorter than full text.
    assert "…" in out or "..." in out
    assert ("x" * 500) not in out


def test_show_human_full_env_disables_truncation(capsys, monkeypatch):
    monkeypatch.setenv("TG_FULL", "1")
    data = {
        "chat": {"chat_id": 1, "title": "T"},
        "order": "newest_first",
        "messages": [
            {
                "date": "2026-05-08T10:00:00",
                "is_outgoing": False,
                "text": "x" * 500,
                "media_type": None,
            }
        ],
    }
    _show_human(data)
    out = capsys.readouterr().out
    assert ("x" * 500) in out
