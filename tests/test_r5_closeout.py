"""R5 closeout: the dormant legacy Refine hotkey must not grab Ctrl+Shift+R, and the shipped market claims must be truthful."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.itemcheck
ROOT = Path(__file__).resolve().parents[1]


def test_the_legacy_refine_hotkey_is_never_started_at_startup():
    from exilelens.app import main

    source = inspect.getsource(main)
    assert "refine_price_hotkey.start(" not in source


def test_ops_compatibility_market_note_says_live_trade_is_policy_blocked():
    note = json.loads((ROOT / "ops" / "compatibility.json").read_text(encoding="utf-8"))["market"]["notes"]
    assert "POLICY-BLOCKED" in note


def test_shipped_package_readme_does_not_promise_live_market_pricing():
    text = (ROOT / "packaging" / "README.txt").read_text(encoding="utf-8")
    assert "may contact the official\nPath of Exile trade site" not in text.replace("\r\n", "\n")
    assert "Live market prices are not available" in text
