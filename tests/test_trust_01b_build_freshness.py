"""TRUST-01B: PoB build freshness -- strong states vs the soft old-file advisory."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from exilelens.app.build_freshness import (
    CURRENT,
    DISK_CHANGED,
    OLD_FILE,
    SOFT_STALE_AGE_DAYS,
    UNKNOWN,
    USING_LAST_GOOD,
    age_text,
    assess_build_freshness,
)
from exilelens.app.build_revision import BuildFileRevision, read_build_revision
from exilelens.items.compact_tooltip import MAX_NOTES, apply_compact_tooltip

pytestmark = pytest.mark.itemcheck

NOW = 1_800_000_000.0
DAY = 86400.0


def _rev(age_days: float, *, size: int = 10, now: float = NOW) -> BuildFileRevision:
    return BuildFileRevision(path="b.xml", mtime_ns=int((now - age_days * DAY) * 1e9), size=size)


def _assess(current, loaded=None, **kwargs):
    return assess_build_freshness(
        has_build=True, loaded_revision=loaded or current, current_revision=current, now=NOW, **kwargs
    )


def test_recent_and_six_day_old_files_are_current() -> None:
    assert _assess(_rev(0.1))["state"] == CURRENT
    assert _assess(_rev(6.9))["state"] == CURRENT


def test_seven_day_old_file_is_only_an_advisory() -> None:
    assert SOFT_STALE_AGE_DAYS == 7
    fresh = _assess(_rev(9))
    assert fresh["state"] == OLD_FILE and fresh["severity"] == "info"
    assert fresh["note"] == "⚠ PoB build may be outdated · last modified 9 days ago"
    assert fresh["detail"] == "File last modified 9 days ago."
    assert "character" not in (fresh["note"] + fresh["detail"] + fresh["title"]).lower()
    assert _assess(_rev(7.0))["state"] == OLD_FILE


def test_future_zero_and_missing_timestamps_are_never_stale() -> None:
    assert _assess(_rev(-3))["state"] == CURRENT
    zero = BuildFileRevision(path="b.xml", mtime_ns=0, size=1)
    assert _assess(zero)["state"] == CURRENT
    missing = assess_build_freshness(has_build=True, loaded_revision=None, current_revision=None, now=NOW)
    assert missing["state"] == UNKNOWN
    assert assess_build_freshness(has_build=False, loaded_revision=None, current_revision=None, now=NOW)["state"] == UNKNOWN


def test_disk_change_outranks_old_file_and_failed_reload_outranks_disk_change() -> None:
    loaded = _rev(30, size=10)
    changed = _rev(30, size=11)
    assert _assess(changed, loaded)["state"] == DISK_CHANGED
    kept = _assess(changed, loaded, reload_failed_kept_previous=True, loaded_at=NOW)
    assert kept["state"] == USING_LAST_GOOD and kept["severity"] == "critical"
    assert "previous" in kept["detail"].lower()
    assert _assess(loaded, loaded)["state"] == OLD_FILE  # reloaded successfully: strong state gone, file still old


def test_age_copy_is_coarse() -> None:
    assert [age_text(s) for s in (60, DAY, 3 * DAY + 5, 24 * DAY)] == ["today", "1 day ago", "3 days ago", "24 days ago"]


# --------------------------------------------------------------- controller


def _controller(tmp_path, monkeypatch):
    from tests.test_stale_build_reload_controller import _ready_controller

    return _ready_controller(tmp_path, monkeypatch)


def test_controller_reports_changed_then_clears_after_successful_reload(tmp_path, monkeypatch) -> None:
    from tests.test_stale_build_reload_controller import _item, _write_build

    controller, _engine, build, _submitted = _controller(tmp_path, monkeypatch)
    try:
        assert controller.build_freshness()["state"] == CURRENT
        _write_build(build, "changed-on-disk-with-new-size")
        assert controller.build_freshness()["state"] == DISK_CHANGED
        controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(1, 1))
        assert controller.build_freshness()["state"] == CURRENT
    finally:
        controller.shutdown()


def test_controller_failed_reload_reports_using_last_good_until_a_good_reload(tmp_path, monkeypatch) -> None:
    from tests.test_stale_build_reload_controller import _item, _write_build

    controller, engine, build, _submitted = _controller(tmp_path, monkeypatch)
    try:
        changed = _write_build(build, "worker-rejected-new-build")
        engine.reject_sha = changed.sha256
        controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(1, 1))
        assert controller.build_freshness()["state"] == USING_LAST_GOOD
        engine.reject_sha = ""
        controller.reload_build()
        assert controller.build_freshness()["state"] == CURRENT
    finally:
        controller.shutdown()


def test_old_file_note_is_surfaced_once_per_session_but_state_stays(tmp_path, monkeypatch) -> None:
    controller, _engine, build, _submitted = _controller(tmp_path, monkeypatch)
    try:
        old = time.time() - 9 * DAY
        os.utime(build, (old, old))
        controller._build_file_revision = read_build_revision(build)
        first = controller._item_check_build_freshness()
        second = controller._item_check_build_freshness()
        assert first["state"] == second["state"] == OLD_FILE
        assert first["note"] and second["note"] == ""
        assert controller.build_freshness()["note"]  # Overview keeps the advisory
    finally:
        controller.shutdown()


# --------------------------------------------------------------- presentation


def _model(freshness, guardrails=(), notes_quality="FULL"):
    return {
        "item_name": "Test",
        "rows": [],
        "build_freshness": freshness,
        "evaluation_outcome": {
            "verdict": "MEANINGFUL_UPGRADE",
            "verdict_label": "MEANINGFUL UPGRADE",
            "final_score": 70.0,
            "evaluation_quality": notes_quality,
            "all_deltas": [],
            "primary_deltas": [],
            "resistances": [],
            "guardrails_applied": list(guardrails),
        },
    }


def test_old_file_note_does_not_change_verdict_score_or_quality() -> None:
    plain, noted = _model({}), _model(_assess(_rev(9)))
    apply_compact_tooltip(plain)
    apply_compact_tooltip(noted)
    assert noted["critical_notes"] == ["⚠ PoB build may be outdated · last modified 9 days ago"]
    assert plain["critical_notes"] == []
    assert noted["evaluation_outcome"] == plain["evaluation_outcome"]
    assert noted["verdict_headline"] == plain["verdict_headline"] and noted["score_value"] == plain["score_value"]
    info = noted["more_info"]
    source = next(s for s in info["sections"] if s["id"] == "build_source")
    assert source["lines"][0] == "PoB build file was last modified 9 days ago."
    assert all(s["id"] != "build_source" for s in plain["more_info"]["sections"])


def test_critical_item_warnings_outrank_the_freshness_note() -> None:
    model = _model(_assess(_rev(9)), notes_quality="PARTIAL")
    model["evaluation_outcome"]["quality_label"] = "Partial evaluation"
    model["evaluation_outcome"]["evaluation_quality_reasons"] = [{"code": "X", "detail": "something was not measured"}]
    model["rows"] = [
        {"key": "fire_res", "label": "Fire Res", "cap_state": "CAP_LOST", "percent_delta": -5.0, "absolute_delta": -5.0},
    ]
    apply_compact_tooltip(model)
    assert len(model["critical_notes"]) == MAX_NOTES
    assert not any("outdated" in note for note in model["critical_notes"])


# --------------------------------------------------------------- overview


def test_overview_shows_old_file_warning_and_stays_quiet_when_current() -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.components import StatusValue
    from exilelens.ui.overview_page import OverviewPage

    QApplication.instance() or QApplication([])
    notice = StatusValue("", "neutral")
    notice.setVisible(False)
    fake = SimpleNamespace(_notice=notice, controller=SimpleNamespace(build_freshness=lambda: _assess(_rev(9))))
    OverviewPage._apply_freshness_notice(fake, SimpleNamespace())
    assert not notice.isHidden()
    assert "may be outdated" in notice._label.text() and "9 days ago" in notice._label.text()

    quiet = StatusValue("", "neutral")
    quiet.setVisible(False)
    fake = SimpleNamespace(_notice=quiet, controller=SimpleNamespace(build_freshness=lambda: _assess(_rev(1))))
    OverviewPage._apply_freshness_notice(fake, SimpleNamespace())
    assert quiet.isHidden()
