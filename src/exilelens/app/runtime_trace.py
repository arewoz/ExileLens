"""Optional clipboard/eval boundary tracing. Off unless POE2VALUE_TRACE=1."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

_ENABLED = os.environ.get("POE2VALUE_TRACE", "").strip() in {"1", "true", "TRUE", "yes"}


def trace(event: str, **fields: Any) -> None:
    if not _ENABLED:
        return
    payload = {"event": event, **fields}
    sys.stderr.write(json.dumps(payload, default=str) + "\n")
    sys.stderr.flush()


def tracing_enabled() -> bool:
    return _ENABLED
