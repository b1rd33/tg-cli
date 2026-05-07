"""Phase 9 — typed --confirm <id>.

The riskiest design point in the platform: confirms must compare against the
RESOLVED id (post-resolver), not the raw user selector. An agent that thinks
it's deleting in chat A but whose selector resolves to chat B must hit a
clean rejection here, not silent destruction in the wrong chat.
"""
from __future__ import annotations

import argparse

import pytest

from tgcli.safety import BadArgs, require_typed_confirm


def _args(confirm=None):
    return argparse.Namespace(confirm=confirm)


def test_typed_confirm_rejects_when_unset():
    with pytest.raises(BadArgs, match="--confirm"):
        require_typed_confirm(_args(), expected=123, slot="chat_id")


def test_typed_confirm_rejects_mismatched_value():
    """The riskiest case: agent typed --confirm with the raw selector but
    the resolver returned a different id. Must reject."""
    with pytest.raises(BadArgs, match="must equal.*chat_id"):
        require_typed_confirm(_args(confirm="Hamid"), expected=289840388, slot="chat_id")


def test_typed_confirm_accepts_string_match_against_int():
    require_typed_confirm(_args(confirm="289840388"), expected=289840388, slot="chat_id")


def test_typed_confirm_accepts_int_match_against_int():
    """argparse type=str stores strings, but unit tests can pass ints directly."""
    require_typed_confirm(_args(confirm=289840388), expected=289840388, slot="chat_id")


def test_typed_confirm_rejects_substring_match():
    """Truncated id 28984 does not pass against 289840388."""
    with pytest.raises(BadArgs):
        require_typed_confirm(_args(confirm="28984"), expected=289840388, slot="chat_id")


def test_typed_confirm_rejects_negative_id_mismatch():
    with pytest.raises(BadArgs):
        require_typed_confirm(_args(confirm="-100123"), expected=-1003957621025, slot="chat_id")


def test_typed_confirm_accepts_negative_id_match():
    require_typed_confirm(_args(confirm="-1003957621025"), expected=-1003957621025, slot="chat_id")


def test_typed_confirm_strips_whitespace():
    """Defensive: agents pipelining JSON values may introduce whitespace."""
    require_typed_confirm(_args(confirm="  123  "), expected=123, slot="chat_id")


def test_typed_confirm_rejects_hex_form():
    """Hex form does not match decimal id (string compare, by design)."""
    with pytest.raises(BadArgs):
        require_typed_confirm(_args(confirm="0x113ee0"), expected=289840388, slot="chat_id")
