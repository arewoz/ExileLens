"""Support bundle export for Diagnostics 2.0."""

from __future__ import annotations

import json
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from exilelens.app.logging_setup import log_path
from exilelens.diagnostics.constants import (
    MAX_BUNDLE_BYTES,
    MAX_EXPORTED_EVENTS,
    MAX_LOG_TAIL_BYTES,
    SUPPORT_BUNDLE_SCHEMA_VERSION,
)
from exilelens.diagnostics.events import event_buffer, verbose_mode_active
from exilelens.diagnostics.sanitize import sanitize_log_lines, sanitize_text
from exilelens.diagnostics.summary import build_extended_summary


class SupportBundleError(RuntimeError):
    pass


def _read_log_tail() -> list[str]:
    path = log_path()
    if not path.is_file():
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) > MAX_LOG_TAIL_BYTES:
        data = data[-MAX_LOG_TAIL_BYTES:]
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    return sanitize_log_lines(text.splitlines())


def build_support_bundle_bytes(
    controller: Any,
    settings: Any,
    *,
    update_service: Any | None = None,
    reproduction_notes: str = "",
) -> bytes:
    summary = build_extended_summary(controller, settings, update_service=update_service)
    events = event_buffer().export_records(
        include_verbose=verbose_mode_active(settings),
        limit=MAX_EXPORTED_EVENTS,
    )
    notes = sanitize_text(reproduction_notes, max_len=2000)
    log_lines = _read_log_tail()

    manifest = {
        "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
        "generated_at_epoch": time.time(),
        "files": [
            {"name": "summary.json", "kind": "extended_diagnostic_summary"},
            {"name": "events.json", "kind": "diagnostic_event_history"},
            {"name": "reproduction.txt", "kind": "user_reproduction_notes"},
            {"name": "application.log.tail.txt", "kind": "sanitized_log_tail"},
        ],
    }

    with tempfile.SpooledTemporaryFile(max_size=MAX_BUNDLE_BYTES + 1) as handle:
        with zipfile.ZipFile(handle, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("summary.json", json.dumps(summary, indent=2, sort_keys=True))
            archive.writestr("events.json", json.dumps(events, indent=2))
            archive.writestr("reproduction.txt", notes or "")
            archive.writestr("application.log.tail.txt", "\n".join(log_lines))
        handle.seek(0)
        payload = handle.read()
    if len(payload) > MAX_BUNDLE_BYTES:
        raise SupportBundleError("Support bundle exceeds the maximum allowed size.")
    return payload


def write_support_bundle(
    destination: Path,
    controller: Any,
    settings: Any,
    *,
    update_service: Any | None = None,
    reproduction_notes: str = "",
) -> Path:
    payload = build_support_bundle_bytes(
        controller,
        settings,
        update_service=update_service,
        reproduction_notes=reproduction_notes,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination
