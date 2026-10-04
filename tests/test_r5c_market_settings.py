"""R5-C: capability gating, consent, Settings row, Diagnostics row and the in-place UI update path. Fake availability only; no network."""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

import pytest

from exilelens.app.settings import AppSettings
from exilelens.price_check import market_policy as mp
from exilelens.ui import health

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.itemcheck
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _policy_constant():
    original = mp.LIVE_TRADE2_AUTHORIZED
    yield
    mp.LIVE_TRADE2_AUTHORIZED = original
    mp.register_settings_reader(None)


def _authorize():
    mp.LIVE_TRADE2_AUTHORIZED = True  # "the provider could serve prices": a test double for capability, never a network switch


# ------------------------------------------------------------------------------------------- the capability model


def test_current_production_state_is_provider_unavailable():
    capability = mp.market_capability(AppSettings())
    assert (capability.provider_available, capability.user_enabled, capability.consent_current, capability.can_enable, capability.active) == (
        False, False, False, False, False,
    )
    assert capability.access_state is mp.MarketAccessState.DISABLED_BY_USER


def test_capability_is_derived_from_the_central_policy_not_a_copy_of_its_constant():
    settings = AppSettings()
    assert mp.market_capability(settings).provider_available is False
    _authorize()
    capability = mp.market_capability(settings)
    assert capability.provider_available and capability.can_enable and not capability.active and not capability.user_enabled
    settings.market_prices_enabled = True
    settings.market_consent_version = mp.MARKET_CONSENT_VERSION
    assert mp.market_capability(settings).active


def test_a_no_network_build_has_no_capability(monkeypatch):
    from exilelens import security_audit

    _authorize()
    monkeypatch.setenv("EXILELENS_AUDIT_VARIANT", "no_network")
    security_audit.variant.cache_clear()
    try:
        assert mp.market_capability(AppSettings()).provider_available is False
    finally:
        monkeypatch.delenv("EXILELENS_AUDIT_VARIANT")
        security_audit.variant.cache_clear()


def test_blocked_capability_cannot_be_enabled():
    settings = AppSettings()
    assert mp.set_market_prices_enabled(settings, True) is False
    assert settings.market_prices_enabled is False and settings.market_consent_version == 0


def test_enabling_records_exactly_the_current_consent_version_and_disabling_forgets_it():
    settings = AppSettings()
    _authorize()
    assert mp.set_market_prices_enabled(settings, True) is True
    assert settings.market_prices_enabled is True and settings.market_consent_version == mp.MARKET_CONSENT_VERSION
    assert mp.market_capability(settings).active
    assert mp.set_market_prices_enabled(settings, False) is True
    assert (settings.market_prices_enabled, settings.market_consent_version) == (False, 0)


def test_a_stale_consent_version_behaves_as_off():
    settings = AppSettings()
    _authorize()
    settings.market_prices_enabled = True
    settings.market_consent_version = mp.MARKET_CONSENT_VERSION - 1
    capability = mp.market_capability(settings)
    assert capability.user_enabled and not capability.consent_current and not capability.active
    assert capability.access_state is mp.MarketAccessState.DISABLED_BY_USER


def test_default_settings_are_off_and_no_other_consent_is_coupled():
    settings = AppSettings()
    assert settings.market_prices_enabled is False and settings.market_consent_version == 0
    _authorize()
    mp.set_market_prices_enabled(settings, True)
    import dataclasses

    others = {f.name: getattr(settings, f.name) for f in dataclasses.fields(settings)
              if ("telemetry" in f.name or "patreon" in f.name or "usage" in f.name or "error_report" in f.name)}
    assert others == {f.name: getattr(AppSettings(), f.name) for f in dataclasses.fields(AppSettings()) if f.name in others}


# --------------------------------------------------------------------------------------------- controller behaviour


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from exilelens.app.controller import EvaluationController

    ctl = EvaluationController(AppSettings())
    yield ctl
    ctl.shutdown()


def test_controller_refuses_enable_while_blocked_and_saves_nothing(controller, monkeypatch):
    saved = []
    monkeypatch.setattr("exilelens.app.controller.save_settings", lambda s: saved.append(True))
    assert controller.set_market_prices_enabled(True) is False
    assert controller.settings.market_prices_enabled is False and saved == []


def test_changing_the_setting_obsoletes_pending_evidence_and_drops_attached_evidence(controller, monkeypatch):
    monkeypatch.setattr("exilelens.app.controller.save_settings", lambda s: None)
    _authorize()
    emitted = []
    controller.market_evidence_updated.connect(lambda rid, result: emitted.append(result))
    controller._market_active = {"job_id": 7, "parent_request_id": 1}
    controller._market_accepted = {"last_status": "AVAILABLE"}
    controller._last_result = {"raw_input": {"content_hash": "h"}, "request_meta": {"request_id": 1}, "market_evidence": {"status": "AVAILABLE"}}
    assert controller.set_market_prices_enabled(True) is True
    assert controller._market_active is None and controller._market_accepted == {}
    assert "market_evidence" not in controller._last_result and len(emitted) == 1 and "market_evidence" not in emitted[0]
    assert controller.settings.market_consent_version == mp.MARKET_CONSENT_VERSION


def test_opening_settings_state_starts_no_network_and_builds_no_service(controller):
    assert controller.market_capability().provider_available is False
    controller.market_evidence_diagnostics()
    assert controller._market_service is None


# ------------------------------------------------------------------------------------------------- Settings page UI

pytestmark_win = pytest.mark.skipif(sys.platform != "win32", reason="the dashboard harness uses Windows-only capture helpers")


def _make_harness(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "scripts"))
    monkeypatch.syspath_prepend(str(_ROOT))
    qa = importlib.import_module("ui_visual_qa")
    states = importlib.import_module("qa_states")
    instance = qa.Harness(tmp_path)
    instance.states = states.STATE_REGISTRY
    return instance


@pytest.fixture
def blocked_harness(tmp_path, monkeypatch):
    original = os.environ.get("LOCALAPPDATA")
    h = _make_harness(tmp_path, monkeypatch)
    h.states["settings-top"](h)
    yield h
    h.controller.shutdown()
    h.window.close()
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original


@pytest.fixture
def available_harness(tmp_path, monkeypatch):
    original = os.environ.get("LOCALAPPDATA")
    _authorize()  # before the page is built: row visibility is decided from capability at build time
    h = _make_harness(tmp_path, monkeypatch)
    h.states["settings-top"](h)
    monkeypatch.setattr("exilelens.app.controller.save_settings", lambda s: None)
    yield h
    h.controller.shutdown()
    h.window.close()
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original


@pytestmark_win
def test_blocked_production_settings_do_not_advertise_market_prices(blocked_harness):
    page = blocked_harness.window._settings_page
    assert page._market_prices_row.isHidden() and page._market_league_row.isHidden()
    assert not page._market_prices.isEnabled() and not page._market_prices.isChecked()
    page._confirm_market_consent = lambda: True  # even a confirmed toggle cannot enable it
    page._on_market_prices_toggled(True)
    assert blocked_harness.settings.market_prices_enabled is False and not page._market_prices.isChecked()


@pytestmark_win
def test_available_capability_shows_a_quiet_off_by_default_row_with_the_data_statement(available_harness):
    from exilelens.ui.dashboard_pages import MARKET_PRICES_COPY

    page = available_harness.window._settings_page
    assert not page._market_prices_row.isHidden() and page._market_prices.isEnabled()
    assert not page._market_prices.isChecked() and available_harness.settings.market_prices_enabled is False
    assert MARKET_PRICES_COPY == (
        "Market prices sends the item's searchable properties and your selected league to the market provider to find comparable "
        "listings. It does not send your PoB build, character, account or item history."
    )
    for banned in ("AI", "smart", "unlock", "enhance", "insight", "powered", "experience"):
        assert banned.lower() not in MARKET_PRICES_COPY.lower()


@pytestmark_win
def test_consent_flow_declined_confirmed_and_disabled(available_harness):
    page = available_harness.window._settings_page
    settings = available_harness.settings
    asked = []
    page._confirm_market_consent = lambda: asked.append(True) or False
    page._market_prices.setChecked(True)  # the user flips the switch, then declines the confirmation
    assert asked == [True] and settings.market_prices_enabled is False and not page._market_prices.isChecked()
    page._confirm_market_consent = lambda: True
    page._market_prices.setChecked(True)
    assert settings.market_prices_enabled is True and settings.market_consent_version == mp.MARKET_CONSENT_VERSION
    assert page._market_prices.isChecked() and page._league_status.text().startswith("Market prices on")
    page._market_prices.setChecked(False)
    assert settings.market_prices_enabled is False and settings.market_consent_version == 0


@pytestmark_win
def test_merely_opening_settings_never_asks_for_consent_or_touches_the_setting(available_harness):
    page = available_harness.window._settings_page
    page._confirm_market_consent = lambda: pytest.fail("consent must only be requested by the user's own switch")
    for _ in range(10):
        available_harness.app.processEvents()
    assert available_harness.settings.market_prices_enabled is False


# --------------------------------------------------------------------------------------------------- Diagnostics row


def _controller_stub(**diag):
    return types.SimpleNamespace(market_evidence_diagnostics=lambda: diag)


def test_diagnostics_row_states():
    off = AppSettings()
    item = health._market_item(off, _controller_stub())
    assert (item.value, item.status) == ("Provider unavailable", health.NEUTRAL) and not item.action

    _authorize()
    assert health._market_item(off, _controller_stub()).value == "Off"
    on = AppSettings()
    mp.set_market_prices_enabled(on, True)
    assert health._market_item(on, _controller_stub()).value == "Ready"
    assert health._market_item(on, _controller_stub(freshness="CURRENT", last_status="AVAILABLE")).detail == "Last listings: current."
    assert health._market_item(on, _controller_stub(pending=True)).value == "Looking up…"
    assert health._market_item(on, _controller_stub(rate_limited=True)).value == "Rate limited"
    assert health._market_item(on, _controller_stub(last_status="UNAVAILABLE")).value == "Unavailable"
    for state in ("Provider unavailable", "Off", "Ready", "Looking up…", "Rate limited", "Unavailable"):
        assert state  # exhaustive list is the documented set


def test_diagnostics_row_never_reads_as_an_error_or_leaks_details():
    import re

    _authorize()
    on = AppSettings()
    mp.set_market_prices_enabled(on, True)
    for diag in ({}, {"pending": True}, {"rate_limited": True}, {"last_status": "UNAVAILABLE"}, {"freshness": "STALE", "last_status": "AVAILABLE"}):
        item = health._market_item(on, _controller_stub(**diag))
        assert item.status == health.NEUTRAL and not item.action
        assert not re.search(r"[A-Z]+_[A-Z_]+|http|query|seller", f"{item.value} {item.detail}")


def test_no_network_build_reads_off_not_unavailable(monkeypatch):
    from exilelens import security_audit

    monkeypatch.setenv("EXILELENS_AUDIT_VARIANT", "no_network")
    security_audit.variant.cache_clear()
    try:
        assert health._market_item(AppSettings(), _controller_stub()).value == "Off"
    finally:
        monkeypatch.delenv("EXILELENS_AUDIT_VARIANT")
        security_audit.variant.cache_clear()


# ------------------------------------------------------------------------ async UI update (production handler wiring)


class _Overlay:
    def __init__(self):
        self.updates = []

    def update_result_in_place(self, request_id, result):
        self.updates.append((request_id, result))


def _app(overlay, generation=3, enabled=True):
    controller = types.SimpleNamespace(presentation_generation=generation)
    return types.SimpleNamespace(settings=types.SimpleNamespace(overlay_enabled=enabled), overlay=overlay, controller=controller)


def _handler():
    from exilelens.app.main import ExileLensApp

    return ExileLensApp._on_market_evidence_updated


def test_the_update_handler_rerenders_the_current_overlay_in_place_only():
    overlay = _Overlay()
    result = {"request_meta": {"presentation_generation": 3}, "market_evidence": {"status": "AVAILABLE"}}
    _handler()(_app(overlay), 5, result)
    assert overlay.updates == [(5, result)]


def test_a_stale_generation_or_disabled_overlay_never_renders():
    overlay = _Overlay()
    _handler()(_app(overlay), 5, {"request_meta": {"presentation_generation": 2}})
    _handler()(_app(overlay, enabled=False), 5, {"request_meta": {"presentation_generation": 3}})
    _handler()(_app(None), 5, {"request_meta": {"presentation_generation": 3}})
    assert overlay.updates == []


def test_pinned_windows_and_history_are_not_touched_by_the_handler():
    import inspect

    source = inspect.getsource(_handler())
    assert ".refresh_pinned_results(" not in source and "_history" not in source and ".record(" not in source


def test_policy_blocked_production_result_renders_no_market_section():
    """In production the controller can only attach UNAVAILABLE/PROVIDER_NOT_AUTHORIZED (opt-in is impossible); it must paint nothing."""
    from exilelens.items.compact_tooltip import apply_compact_tooltip
    from exilelens.items.market_presentation import market_view
    from exilelens.items.more_info import build_more_info
    from exilelens.price_check.market_evidence import EvidenceStatus, status_evidence

    evidence = status_evidence(EvidenceStatus.UNAVAILABLE, "PROVIDER_NOT_AUTHORIZED").to_dict()
    model = {"item_name": "x", "evaluation_outcome": {"evaluation_quality": "FULL", "final_score": 60.0, "verdict": "SIDEGRADE",
                                                         "verdict_label": "SIDEGRADE", "verdict_class": "neutral", "quality_label": "",
                                                         "verdict_reason": "x", "guardrails_applied": [], "critical_tradeoffs": [],
                                                         "resistances": [], "all_deltas": []},
             "rows": [], "why_reasons": [], "market": market_view(evidence, None)}
    apply_compact_tooltip(model)
    assert model["market_lines"] == [] and "market" not in build_more_info(model)["section_ids"]
