"""State builders for ``ui_visual_qa.py``. Each takes the harness and leaves the window in that state."""

from __future__ import annotations


def _overview(state: str, **kw):
    def build(h):
        h.set_state(state, **kw)
        h.window.navigate("overview")
    return build


def _page(page: str, state: str = "ready"):
    def build(h):
        h.set_state(state)
        h.window.navigate(page)
    return build


def _settings(section: str | None, *, state: str = "ready", update=None, patreon=None, advanced: bool = False, consent: bool = False):
    def build(h):
        h.set_state(state)
        h.patreon("not_connected")
        h.update("unchecked", "")
        if update:
            h.update(*update[:2], **(update[2] if len(update) > 2 else {}))
        if patreon:
            h.patreon(patreon[0], **(patreon[1] if len(patreon) > 1 else {}))
        h.window.navigate("settings")
        h.window._settings_page._advanced.set_expanded(advanced)
        h.scroll_settings(section)
    return build


def _analysis(kind: str):
    def build(h):
        h.set_state("ready")
        page = h.window._analysis
        controller = h.controller
        if kind != "empty":
            from tests.test_r1_analyze_build_ui import realistic_analysis

            result = realistic_analysis()
            controller.last_analysis = lambda: result  # type: ignore[method-assign]
            controller.analysis_finished.emit(result)
            if kind == "stale":
                controller.analysis_stale.emit()
            elif kind == "running":
                controller.build_analysis_started.emit(2)
            elif kind == "error":
                controller.build_analysis_started.emit(2)
                controller.analysis_error.emit("Path of Building did not finish the analysis")
        h.window.navigate("build_analysis")
        h.app.processEvents()
        page.scroll.verticalScrollBar().setValue(0)
    return build


import time as _time

_GRACE_UNTIL = int(_time.mktime((2026, 10, 10, 12, 0, 0, 0, 0, -1)))

STATE_REGISTRY = {
    "overview-consent": lambda h: (h.set_state("setup"), h.consent_card(True), h.window.navigate("overview")),
    "settings-general": _settings(None),
    "settings-privacy": _settings("Privacy"),
    "settings-updates-ahead": _settings("Updates", update=("ahead", "0.6.0")),
    "settings-updates-current": _settings("Updates", update=("current", "0.7.0b1")),
    "settings-updates-available": _settings("Updates", update=("available", "0.7.0")),
    "settings-updates-downloading": _settings("Updates", update=("available", "0.7.0", {"download": "downloading", "percent": 42})),
    "settings-updates-ready": _settings("Updates", update=("available", "0.7.0", {"download": "ready"})),
    "settings-updates-failed": _settings("Updates", update=("failed", "")),
    "settings-patreon-not-linked": _settings("Updates"),
    "settings-patreon-linking": _settings("Updates", patreon=("linking",)),
    "settings-patreon-active": _settings("Updates", update=("ahead", "0.6.0"), patreon=("active",)),
    "settings-patreon-not-eligible": _settings("Updates", patreon=("not_eligible",)),
    "settings-patreon-grace": _settings("Updates", patreon=("offline_grace", {"expires_at": _GRACE_UNTIL})),
    "settings-patreon-expired": _settings("Updates", patreon=("expired",)),
    "settings-patreon-reconnect": _settings("Updates", patreon=("reconnect_required",)),
    "settings-patreon-unavailable": _settings("Updates", patreon=("service_unavailable",)),
    "settings-advanced": _settings("Advanced", advanced=True),
    "settings-reset": _settings("__bottom__"),
    "overview-ready": _overview("ready"),
    "overview-setup": _overview("setup"),
    "overview-pob-missing": _overview("pob-missing"),
    "overview-connecting": _overview("connecting"),
    "overview-disconnected": _overview("disconnected"),
    "overview-attention": _overview("attention"),
    "overview-build-failed": _overview("build-failed"),
    "settings-top": _page("settings"),
    "diagnostics-healthy": _page("diagnostics", "ready"),
    "diagnostics-degraded": _page("diagnostics", "disconnected"),
    "analyze-empty": _analysis("empty"),
    "analyze-results": _analysis("results"),
    "analyze-stale": _analysis("stale"),
    "analyze-running": _analysis("running"),
    "analyze-error": _analysis("error"),
}
