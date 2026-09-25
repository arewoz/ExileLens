"""Focused offline coverage for Diagnostics 2.0."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from exilelens.diagnostics.bundle import SupportBundleError, build_support_bundle_bytes
from exilelens.diagnostics.events import (
    DiagnosticEventBuffer,
    clear_event_history,
    enable_verbose_mode,
    event_buffer,
    record_event,
)
from exilelens.diagnostics.sanitize import sanitize_text, sanitize_value
from exilelens.diagnostics.summary import build_extended_summary


SENSITIVE_USER = "ArekTester"
SENSITIVE_PATH = rf"C:\Users\{SENSITIVE_USER}\secret\build.xml"
SENSITIVE_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
SENSITIVE_CLIPBOARD = "Rarity: Rare\nSuper Secret Ring\n<Item>"
SENSITIVE_XML = '<?xml version="1.0"?><Build><Player name="ArekTester"/></Build>'


def test_sanitize_removes_paths_usernames_tokens_and_xml() -> None:
    blob = " ".join([SENSITIVE_PATH, SENSITIVE_TOKEN, SENSITIVE_CLIPBOARD, SENSITIVE_XML])
    cleaned = sanitize_text(blob)
    assert SENSITIVE_USER not in cleaned
    assert "ghp_" not in cleaned
    assert "build.xml" not in cleaned
    assert "<Build>" not in cleaned
    assert "<path>" in cleaned or "<redacted" in cleaned


def test_event_buffer_ring_limit() -> None:
    buffer = DiagnosticEventBuffer(capacity=5)
    for index in range(10):
        buffer.record("app", f"event-{index}")
    assert len(buffer.snapshot(include_verbose=True)) == 5
    assert buffer.snapshot(include_verbose=True)[0].name == "event-5"


def test_verbose_events_hidden_unless_enabled() -> None:
    clear_event_history()
    record_event("app", "normal")
    record_event("app", "verbose", verbose_only=True)
    assert len(event_buffer().snapshot(include_verbose=False)) == 1


def test_extended_summary_is_allowlisted(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings

    settings = AppSettings()
    controller = EvaluationController(settings)
    try:
        payload = build_extended_summary(controller, settings)
        assert "application" in payload
        assert "error_codes" in payload
        assert "support_session_id" in payload
        text = json.dumps(payload)
        assert SENSITIVE_USER not in text
    finally:
        controller.shutdown()


def test_support_bundle_excludes_sensitive_values(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings
    from exilelens.app.logging_setup import log_path

    settings = AppSettings()
    controller = EvaluationController(settings)
    clear_event_history()
    record_event("item_check", "evaluation_error", detail={"message": SENSITIVE_PATH})
    log_path().parent.mkdir(parents=True, exist_ok=True)
    log_path().write_text(
        f"clipboard={SENSITIVE_CLIPBOARD}\npath={SENSITIVE_PATH}\ntoken={SENSITIVE_TOKEN}\n",
        encoding="utf-8",
    )
    try:
        payload = build_support_bundle_bytes(
            controller,
            settings,
            reproduction_notes=f"notes {SENSITIVE_PATH} {SENSITIVE_TOKEN}",
        )
    finally:
        controller.shutdown()
    archive = zipfile.ZipFile(io.BytesIO(payload))
    combined = "\n".join(archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist())
    assert SENSITIVE_USER not in combined
    assert "ghp_" not in combined
    assert "Super Secret Ring" not in combined
    assert "<Build>" not in combined
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["schema_version"] >= 1


def test_support_bundle_size_guard(monkeypatch) -> None:
    from exilelens.diagnostics import bundle as bundle_module

    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_BYTES", 64)
    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings

    settings = AppSettings()
    controller = EvaluationController(settings)
    try:
        with pytest.raises(SupportBundleError):
            build_support_bundle_bytes(controller, settings, reproduction_notes="x" * 500)
    finally:
        controller.shutdown()


def test_verbose_mode_expires(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exilelens.app.settings import AppSettings
    from exilelens.diagnostics.events import verbose_mode_active

    settings = AppSettings()
    enable_verbose_mode(settings, seconds=60)
    assert verbose_mode_active(settings)
    settings.diagnostic_verbose_until = 0.0
    assert not verbose_mode_active(settings)


def test_diagnostics_summary_failure_does_not_raise(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exilelens.app.settings import AppSettings

    class BrokenController:
        settings = AppSettings()

        def engine_status(self):
            raise RuntimeError("boom")

        @property
        def build_info(self):
            raise RuntimeError("boom")

        @property
        def presentation_generation(self):
            return 0

    payload = build_extended_summary(BrokenController(), AppSettings())
    assert payload["worker"]["engine_status"] == "unknown"
