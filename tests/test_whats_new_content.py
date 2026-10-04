"""What's New content model: loading, ordering, aggregation, copy limits and the release-gate contract."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from exilelens.app.updates.version import ExileLensVersion
from exilelens.whats_new import content, trigger

ROOT = Path(__file__).resolve().parents[1]
V = ExileLensVersion.parse


def _hl(ident: str, introduced: str, priority: int = 10, *, title: str = "", text: str = "A short sentence.", link=None) -> dict:
    return {"id": ident, "title": title or ident.replace("-", " ").title(), "text": text, "introduced": introduced,
            "priority": priority, "link": link}


def _minor(ident: str, introduced: str, text: str = "A small fix.") -> dict:
    return {"id": ident, "text": text, "introduced": introduced}


def _rel(version: str, previous: str | None, *, highlights=(), minor=(), limitations=(), action=None, released="2026-10-04") -> dict:
    return {"version": version, "released": released, "previous": previous, "highlights": list(highlights),
            "minor": list(minor), "limitations": list(limitations), "action": action}


def _catalog(*releases: dict) -> content.Catalog:
    return content.parse_document({"schema": 1, "releases": list(releases)})


@pytest.fixture
def history() -> content.Catalog:
    return _catalog(
        _rel("0.7.0", "0.6.0", highlights=[_hl("alpha", "0.7.0", 1), _hl("beta", "0.7.0", 2)], minor=[_minor("m1", "0.7.0")]),
        _rel("0.8.0", "0.7.0", highlights=[_hl("gamma", "0.8.0", 1), _hl("alpha", "0.7.0", 1, text="Updated wording.")],
             minor=[_minor("m2", "0.8.0"), _minor("m1", "0.7.0")], limitations=[_minor("lim", "0.8.0", "Beta only.")]),
        _rel("0.9.0", "0.8.0", highlights=[_hl(f"h{i}", "0.9.0", i) for i in range(1, 6)],
             minor=[_minor(f"x{i}", "0.9.0") for i in range(1, 8)]),
    )


# ------------------------------------------------------------------------------------------------ the packaged file
def test_packaged_file_loads_and_has_real_0_7_0b1_content() -> None:
    catalog = content.load_catalog()
    assert catalog is not None
    release = catalog.get(V("0.7.0b1"))
    assert release is not None and release.previous == V("0.6.0")
    assert 1 <= len(release.highlights) <= 4 and len(release.minor) <= 6
    assert content.lint_catalog(catalog, V("0.7.0b1")) == []


def test_every_packaged_link_is_an_allowlisted_destination() -> None:
    catalog = content.load_catalog()
    destinations = {h.link.destination for r in catalog.releases for h in r.highlights if h.link}
    assert destinations <= set(content.DESTINATIONS)


@pytest.mark.parametrize("payload", ["", "not json", "[]", '{"schema": 2, "releases": []}', '{"schema": 1, "releases": 5}'])
def test_malformed_or_missing_data_fails_closed(tmp_path: Path, payload: str) -> None:
    target = tmp_path / "whats_new.json"
    target.write_text(payload, encoding="utf-8")
    assert content.load_catalog(target) is None
    assert content.load_catalog(tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(version="soon"),
        lambda r: r.update(released="yesterday"),
        lambda r: r["highlights"][0].update(introduced="1"),
        lambda r: r["highlights"][0].update(link={"label": "x", "destination": "https://example.com"}),
        lambda r: r["highlights"][0].update(id="Bad Id"),
        lambda r: r["highlights"][0].update(text=""),
    ],
)
def test_structural_errors_are_rejected(mutate) -> None:
    release = _rel("0.7.0", None, highlights=[_hl("alpha", "0.7.0")])
    mutate(release)
    with pytest.raises(content.ContentError):
        _catalog(release)


def test_duplicate_release_versions_are_rejected() -> None:
    with pytest.raises(content.ContentError):
        _catalog(_rel("0.7.0", None), _rel("0.7.0", None))


# ------------------------------------------------------------------------------------------------ versions
def test_versions_sort_numerically_and_a_final_outranks_its_betas() -> None:
    order = sorted(V(v) for v in ("0.10.0", "0.9.0", "0.7.0", "0.7.0b2", "0.7.0b10", "0.7.0b1"))
    assert [str(v) for v in order] == ["0.7.0b1", "0.7.0b2", "0.7.0b10", "0.7.0", "0.9.0", "0.10.0"]
    catalog = _catalog(_rel("0.7.0b1", None), _rel("0.7.0", "0.7.0b1"), _rel("0.7.0b2", "0.7.0b1"))
    assert [str(r.version) for r in catalog.releases] == ["0.7.0", "0.7.0b2", "0.7.0b1"]


def test_github_url_is_the_exact_tag_of_the_installed_version() -> None:
    assert content.github_release_url(V("0.7.0b1")) == "https://github.com/arewoz/ExileLens/releases/tag/v0.7.0b1"
    assert content.github_release_url("0.7.0").endswith("/releases/tag/v0.7.0")


# ------------------------------------------------------------------------------------------------ titles and meta
def test_pre_release_and_stable_titles_and_meta(history) -> None:
    beta = _catalog(_rel("0.7.0b1", "0.6.0", highlights=[_hl("a", "0.7.0b1")]))
    summary = content.automatic_summary(beta, V("0.7.0b1"), V("0.6.0"))
    assert summary.title == "What's new in ExileLens 0.7.0b1"
    assert summary.meta == "Pre-release build · Updated from 0.6.0 · No action needed"
    stable = content.automatic_summary(history, V("0.7.0"), V("0.6.0"))
    assert stable.title == "What's new in ExileLens 0.7.0"
    assert stable.meta == "Updated from 0.6.0 · No action needed"


def test_legacy_profile_never_claims_where_it_updated_from(history) -> None:
    summary = content.automatic_summary(history, V("0.7.0"), None)
    assert summary.meta == "No action needed" and "Updated from" not in summary.meta
    beta = _catalog(_rel("0.7.0b1", "0.6.0", highlights=[_hl("a", "0.7.0b1")]))
    assert content.automatic_summary(beta, V("0.7.0b1"), None).meta == "Pre-release build · No action needed"


def test_manual_reopen_shows_the_release_date_not_an_update(history) -> None:
    beta = _catalog(_rel("0.7.0b1", "0.6.0", highlights=[_hl("a", "0.7.0b1")], released="2026-10-04"))
    summary = content.manual_summary(beta, V("0.7.0b1"))
    assert summary.meta == "Released 4 Oct 2026 · Pre-release build" and summary.kind == "manual"
    assert content.manual_summary(history, V("0.8.0")).meta == "Released 4 Oct 2026"
    assert content.manual_summary(history, V("0.7.5")) is None and content.manual_summary(None, V("0.7.0")) is None


def test_action_note_changes_the_meta_line() -> None:
    catalog = _catalog(_rel("0.8.0", "0.7.0", highlights=[_hl("a", "0.8.0")], action={"text": "Set Shift + C again.", "link": None}))
    summary = content.automatic_summary(catalog, V("0.8.0"), V("0.7.0"))
    assert summary.meta == "Updated from 0.7.0 · One thing to check" and summary.action.text == "Set Shift + C again."


# ------------------------------------------------------------------------------------------------ aggregation
def test_single_step_upgrade_is_the_installed_release_only(history) -> None:
    summary = content.automatic_summary(history, V("0.8.0"), V("0.7.0"))
    assert summary.kind == "release" and summary.title == "What's new in ExileLens 0.8.0"
    assert [h.id for h in summary.highlights] == ["gamma"]          # alpha arrived in 0.7.0: already seen
    assert summary.minor == ("A small fix.",) and summary.limitations == ("Beta only.",)
    assert all(h.since == "" for h in summary.highlights)


def test_skipped_releases_collapse_into_one_cumulative_summary(history) -> None:
    summary = content.automatic_summary(history, V("0.8.0"), V("0.6.0"))
    assert summary.kind == "since" and summary.title == "What's new since ExileLens 0.6.0"
    assert summary.meta == "Updated from 0.6.0 to 0.8.0 · No action needed"
    ids = [h.id for h in summary.highlights]
    assert ids == ["gamma", "alpha", "beta"]                          # by priority, then the newer arrival; no duplicate alpha
    assert [h.since for h in summary.highlights] == ["0.8.0", "0.7.0", "0.7.0"]
    assert next(h for h in summary.highlights if h.id == "alpha").text == "Updated wording."   # the newest wording wins
    assert summary.github_url.endswith("/tag/v0.8.0")


def test_cumulative_summary_caps_highlights_and_smaller_items(history) -> None:
    summary = content.automatic_summary(history, V("0.9.0"), V("0.6.0"))
    assert len(summary.highlights) == content.MAX_HIGHLIGHTS and len(summary.minor) == content.MAX_MINOR
    assert [h.id for h in summary.highlights] == ["h1", "gamma", "alpha", "h2"]
    single = content.automatic_summary(history, V("0.9.0"), V("0.8.0"))
    assert [h.id for h in single.highlights] == ["h1", "h2", "h3", "h4"] and len(single.minor) == 6


def test_only_items_newer_than_the_last_seen_version_are_cumulative(history) -> None:
    summary = content.automatic_summary(history, V("0.9.0"), V("0.7.0"))
    ids = {h.id for h in summary.highlights}
    assert "alpha" not in ids and "beta" not in ids and "gamma" in ids
    assert all(V(h.since) > V("0.7.0") for h in summary.highlights)


def test_insufficient_history_shows_the_installed_release_with_a_skipped_note(history) -> None:
    summary = content.automatic_summary(history, V("0.9.0"), V("0.5.0"))
    assert summary.kind == "release" and summary.title == "What's new in ExileLens 0.9.0"
    assert summary.note == content.SKIPPED_NOTE and "Updated from" not in summary.meta
    # A history that reaches back to the last seen version has no gap, and no note.
    assert content.automatic_summary(history, V("0.9.0"), V("0.6.0")).note == ""


def test_same_version_downgrade_and_missing_entry_have_no_automatic_summary(history) -> None:
    assert content.automatic_summary(history, V("0.8.0"), V("0.8.0")) is None
    assert content.automatic_summary(history, V("0.7.0"), V("0.8.0")) is None
    assert content.automatic_summary(history, V("0.8.1"), V("0.6.0")) is None
    assert content.automatic_summary(None, V("0.8.0"), None) is None


def test_beta_to_final_does_not_repeat_what_the_beta_showed() -> None:
    catalog = _catalog(
        _rel("0.7.0b1", "0.6.0", highlights=[_hl("a", "0.7.0b1")]),
        _rel("0.7.0", "0.7.0b1", highlights=[_hl("a", "0.7.0b1"), _hl("b", "0.7.0", 2)]),
    )
    assert [h.id for h in content.automatic_summary(catalog, V("0.7.0"), V("0.7.0b1")).highlights] == ["b"]
    assert [h.id for h in content.automatic_summary(catalog, V("0.7.0"), V("0.6.0")).highlights] == ["b", "a"]


def test_a_release_with_nothing_new_since_last_seen_still_shows_its_own_notes() -> None:
    catalog = _catalog(_rel("0.7.0", "0.7.0b1", highlights=[_hl("a", "0.7.0b1")]))
    summary = content.automatic_summary(catalog, V("0.7.0"), V("0.7.0b1"))
    assert [h.id for h in summary.highlights] == ["a"]


# ------------------------------------------------------------------------------------------------ persistence and trigger rules
def test_settings_field_round_trips_and_defaults_empty() -> None:
    from exilelens.app.settings import AppSettings

    assert AppSettings().last_seen_release_notes_version == ""
    data = AppSettings(last_seen_release_notes_version="0.7.0b1").to_dict()
    assert AppSettings.from_dict(data).last_seen_release_notes_version == "0.7.0b1"
    assert AppSettings.from_dict({}).last_seen_release_notes_version == ""


def test_fresh_install_records_the_running_version_silently(history) -> None:
    from exilelens.app.settings import AppSettings

    fresh = AppSettings()
    assert trigger.record_fresh_install(fresh, V("0.8.0"), loaded_from_disk=False)
    assert fresh.last_seen_release_notes_version == "0.8.0"
    assert trigger.evaluate(fresh, V("0.8.0"), history) is None


def test_existing_profile_without_a_stored_version_gets_the_installed_notes_once(history) -> None:
    from exilelens.app.settings import AppSettings

    legacy = AppSettings.from_dict({"schema_version": 24, "pob_path": "x", "build_path": "y"})
    assert not trigger.record_fresh_install(legacy, V("0.8.0"), loaded_from_disk=True)
    summary = trigger.evaluate(legacy, V("0.8.0"), history)
    assert summary is not None and summary.title == "What's new in ExileLens 0.8.0" and "Updated from" not in summary.meta


def test_unreadable_profile_is_treated_like_a_fresh_one(history) -> None:
    from exilelens.app.settings import AppSettings

    settings = AppSettings()
    assert trigger.record_fresh_install(settings, V("0.8.0"), loaded_from_disk=True, load_error=True)
    assert trigger.evaluate(settings, V("0.8.0"), history) is None


def test_upgrade_same_version_and_downgrade(history) -> None:
    from exilelens.app.settings import AppSettings

    assert trigger.evaluate(AppSettings(last_seen_release_notes_version="0.7.0"), V("0.8.0"), history) is not None
    assert trigger.evaluate(AppSettings(last_seen_release_notes_version="0.8.0"), V("0.8.0"), history) is None
    assert trigger.evaluate(AppSettings(last_seen_release_notes_version="0.9.0"), V("0.8.0"), history) is None
    assert trigger.evaluate(AppSettings(last_seen_release_notes_version="0.7.0"), V("0.8.0"), None) is None


def test_mark_seen_persists_once_and_never_lowers(history) -> None:
    from exilelens.app.settings import AppSettings

    saved: list[str] = []
    settings = AppSettings(last_seen_release_notes_version="0.7.0")
    assert trigger.mark_seen(settings, V("0.8.0"), lambda s: saved.append(s.last_seen_release_notes_version))
    assert saved == ["0.8.0"]
    assert not trigger.mark_seen(settings, V("0.8.0"), lambda s: saved.append("again"))
    assert not trigger.mark_seen(settings, V("0.7.0"), lambda s: saved.append("lower"))
    assert saved == ["0.8.0"] and settings.last_seen_release_notes_version == "0.8.0"


def test_a_failed_write_does_not_raise() -> None:
    from exilelens.app.settings import AppSettings

    def broken(_settings) -> None:
        raise OSError("disk full")

    assert trigger.mark_seen(AppSettings(), V("0.8.0"), broken) is False


# ------------------------------------------------------------------------------------------------ status gate
@pytest.mark.parametrize(
    ("state", "expected"),
    [("ready", trigger.SHOW), ("attention", trigger.SHOW), ("connecting", trigger.WAIT), ("setup", trigger.DEFER),
     ("pob-missing", trigger.DEFER), ("disconnected", trigger.DEFER), ("build-failed", trigger.DEFER)],
)
def test_status_gate(state, expected, monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.syspath_prepend(str(ROOT))
    import ui_visual_qa as qa

    from exilelens.ui import status_model

    monkeypatch.setattr(status_model._health, "derive_health", lambda controller, settings: qa.health_for(state))
    status = status_model.derive_status(SimpleNamespace(active_build_status=lambda: None, build_info=None), SimpleNamespace())
    assert trigger.gate(status) == expected
    assert trigger.gate(None) == trigger.WAIT


def test_loading_build_waits() -> None:
    from exilelens.ui import health, status_model

    loading = health.HealthItem("build", "Build", "Spark · loading", "neutral")
    app = health.HealthItem("app", "ExileLens", "0.7.0b1", "ok")
    pob = health.HealthItem("pob", "Path of Building", "Connected", "ok")
    hotkey = health.HealthItem("hotkey", "Item check hotkey", "Shift + C · active", "ok")
    market = health.HealthItem("market", "Market", "Live", "neutral")
    status = status_model.AppStatus("loading", "Loading…", "neutral", "x", "", 0, health.AppHealth(app, pob, loading, hotkey, market, None))
    assert trigger.gate(status) == trigger.WAIT


# ------------------------------------------------------------------------------------------------ release-gate rules
CANDIDATE = V("0.7.0b1")


def _lint(release: dict, **extra) -> list[str]:
    return content.lint_catalog(_catalog(release), V(release["version"]))


def test_lint_requires_an_entry_for_the_candidate(history) -> None:
    assert content.lint_catalog(history, V("0.8.5")) == ["no entry for 0.8.5"]


def test_lint_enforces_the_structural_limits() -> None:
    too_many = _rel("0.7.0b1", None, highlights=[_hl(f"h{i}", "0.7.0b1") for i in range(5)],
                    minor=[_minor(f"m{i}", "0.7.0b1") for i in range(7)],
                    limitations=[_minor(f"l{i}", "0.7.0b1") for i in range(4)])
    problems = " ".join(_lint(too_many))
    assert "5 highlights" in problems and "7 smaller" in problems and "4 limitations" in problems


def test_lint_rejects_overlong_copy_duplicate_ids_and_future_introductions() -> None:
    release = _rel("0.7.0b1", None, highlights=[_hl("a", "0.7.0b1", title="T" * 80, text="x" * 300), _hl("a", "0.7.0b1")],
                   minor=[_minor("m", "0.8.0")])
    problems = " ".join(_lint(release))
    assert "80 characters" in problems and "300 characters" in problems
    assert "already used" in problems and "newer than its release" in problems


def test_lint_rejects_nonsense_version_relations() -> None:
    assert any("previous" in p for p in _lint(_rel("0.7.0b1", "0.7.0b1", highlights=[_hl("a", "0.7.0b1")])))
    assert any("not plausible" in p for p in _lint(_rel("0.7.0b1", None, released="2099-01-01")))


@pytest.mark.parametrize(
    "text",
    ["Part of R2 work", "Fixes M5.5 rollout", "See CORE-04 notes", "Shows EL-PRC-001 in the overlay", "Commit a1b2c3d4 fixed it",
     "Moved out of status_model.py", "Renamed ItemCheckService internals"],
)
def test_lint_blocks_obvious_internal_wording(text) -> None:
    release = _rel("0.7.0b1", None, highlights=[_hl("a", "0.7.0b1", text=text)])
    assert _lint(release), text


@pytest.mark.parametrize(
    "text",
    ["Manifest checks run before every update.", "The sync now repairs a stale cache.", "Defaced items are handled.",
     "ExileLens remembers your Path of Building folder.", "Works with PoB 2 and Windows 11 in 2026.", "Version 1234567 of nothing."],
)
def test_lint_does_not_police_ordinary_words(text) -> None:
    assert _lint(_rel("0.7.0b1", None, highlights=[_hl("a", "0.7.0b1", text=text)])) == []


# ------------------------------------------------------------------------------------------------ the real release gate
def _gate_root(tmp_path: Path) -> Path:
    from exilelens.ops.release_gate import REQUIRED_PACKAGING

    for relative in (*REQUIRED_PACKAGING, "pyproject.toml"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def _gate_result(root: Path):
    from exilelens.ops.release_gate import evaluate_release_gate

    report = evaluate_release_gate(root=root, allow_dirty=True)
    return next(item for item in (*report.blockers, *report.warnings, *report.passed) if item.name == "whats_new")


def test_release_gate_passes_with_the_packaged_content(tmp_path) -> None:
    from exilelens.ops.models import GateVerdict

    assert _gate_result(_gate_root(tmp_path)).status is GateVerdict.PASS


def test_release_gate_blocks_a_missing_or_wrong_entry_and_leakage(tmp_path) -> None:
    from exilelens import __version__
    from exilelens.ops.models import GateVerdict

    root = _gate_root(tmp_path)
    path = root / "src" / "exilelens" / "whats_new" / "whats_new.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["releases"][0]["version"] = "0.1.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = _gate_result(root)
    assert result.status is GateVerdict.BLOCKED and f"no entry for {__version__}" in result.detail
    data["releases"][0]["version"] = __version__
    data["releases"][0]["highlights"][0]["text"] = "Part of R2 and EL-UPD-004."
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _gate_result(root).status is GateVerdict.BLOCKED
    path.write_text("{broken", encoding="utf-8")
    assert _gate_result(root).status is GateVerdict.BLOCKED
    path.unlink()
    assert _gate_result(root).status is GateVerdict.BLOCKED


# ------------------------------------------------------------------------------------------------ packaging
def test_pyinstaller_spec_ships_the_content_file_next_to_the_module() -> None:
    spec = (ROOT / "packaging" / "exilelens-gui.spec").read_text(encoding="utf-8")
    assert "whats_new.json" in spec and '"exilelens/whats_new"' in spec and "whats_new_data" in spec.split("datas=")[1].split("\n")[0]
    assert content.content_path() == ROOT / "src" / "exilelens" / "whats_new" / "whats_new.json"


def test_content_path_follows_the_frozen_module_location() -> None:
    # Frozen builds place the file at <bundle>/exilelens/whats_new/ and import the module from there as well.
    assert content.content_path().parent.name == "whats_new" and content.content_path().parent.parent.name == "exilelens"


def test_binary_report_flag_reports_a_loadable_entry_for_its_own_version(tmp_path: Path) -> None:
    """The same flag the release gate runs against the packaged exe; here against the source entry point."""
    import subprocess
    import sys

    report_path = tmp_path / "report.json"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "src" / "exilelens" / "app" / "main.py"), "--exilelens-whats-new-report", str(report_path)],
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, timeout=120, check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert completed.returncode == 0 and report["loaded"] and report["has_entry"] and report["problems"] == []
    assert report["frozen"] is False


def test_packaged_release_gate_check_is_only_required_for_a_built_artifact(tmp_path: Path) -> None:
    from exilelens.ops.models import GateVerdict
    from exilelens.ops.release_gate import _packaged_whats_new

    assert _packaged_whats_new(tmp_path).status is GateVerdict.PASS
    assert _packaged_whats_new(tmp_path, required=True).status is GateVerdict.BLOCKED
