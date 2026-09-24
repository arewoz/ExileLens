"""Build-time security audit variant gates (no effect unless a variant is embedded)."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

_MARKER_NAME = "security_audit_variant.txt"


@lru_cache(maxsize=1)
def variant() -> str:
    env = os.environ.get("EXILELENS_AUDIT_VARIANT", "").strip().lower()
    if env:
        return env
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", ""))
    else:
        base = Path(__file__).resolve().parents[2]
    marker = base / _MARKER_NAME
    if marker.is_file():
        return marker.read_text(encoding="utf-8").strip().lower()
    return ""


def keyboard_hooks_disabled() -> bool:
    return variant() in {"no_hooks", "minimal"}


def send_input_disabled() -> bool:
    return variant() in {"no_sendinput", "minimal"}


def overlay_disabled() -> bool:
    return variant() in {"no_overlay", "minimal"}


def network_disabled() -> bool:
    return variant() in {"no_network", "minimal"}
