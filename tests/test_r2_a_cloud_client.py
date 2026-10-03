"""R2 Package A: opt-in usage statistics and error reports (desktop side).

All state lives in tmp_path; the real %LOCALAPPDATA% is never touched and no real network is used.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.app.settings import AppSettings
from exilelens.cloud import consent, contract, errors, hooks, telemetry, transparency
from exilelens.cloud.endpoint import normalize_base_url
from exilelens.cloud.service import CloudServices, effective_consent
from exilelens.cloud.sink import Sink
from exilelens.cloud.store import CategoryStore
from exilelens.cloud.transport import Backoff, CloudHttp, PostResult

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "cloud" / "contract" / "fixtures.json").read_text(encoding="utf-8"))
BASE_URL = "https://api.example.test"


class Clock:
    def __init__(self, now: float = 1_790_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeHttp:
    """Scripted stand-in for CloudHttp; records every request."""

    def __init__(self, results=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.results = list(results or [])

    def post_json(self, path, body, headers=None):
        self.calls.append((path, body))
        if self.results:
            return self.results.pop(0)
        return PostResult(status=202, body={"ok": True})

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]


def make_services(tmp_path: Path, *, usage=False, errors_on=False, url=BASE_URL, http=None, clock=None):
    settings = AppSettings(
        send_usage_stats=usage,
        send_error_reports=errors_on,
        privacy_consent_version=consent.current_consent_version(),
    )
    http = http or FakeHttp()
    clock = clock or Clock()
    cloud = CloudServices(
        settings,
        clock=clock,
        base_url=lambda: url,
        http_factory=lambda _url: http,
        root=tmp_path / "cloud",
        first_flush_delay=0,
        flush_interval=1800,
    )
    return cloud, settings, http, clock


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


# ----------------------------------------------------------------------------- contract parity


def test_contract_copies_are_identical() -> None:
    canonical = (ROOT / "cloud" / "schema" / "events.v1.json").read_bytes()
    packaged = (ROOT / "src" / "exilelens" / "cloud" / "events.v1.json").read_bytes()
    assert canonical == packaged


@pytest.mark.parametrize("kind", ["usage", "errors"])
def test_python_validator_matches_golden_fixtures(kind: str) -> None:
    now = contract.hour_to_epoch(FIXTURES["now"][:13] + ":00Z") + 1800
    for case in FIXTURES[kind]:
        result = contract.validate_batch(kind, case["body"], now)
        expect = case["expect"]
        assert result.batch == expect["batch"], case["name"]
        assert result.accepted == expect["accepted"], case["name"]
        assert result.rejected == expect["rejected"], case["name"]


def test_synthetic_examples_are_contract_valid() -> None:
    now = contract.hour_to_epoch("2026-01-01T12:00Z") + 600
    for kind, key in (("usage", "events"), ("errors", "reports")):
        example = transparency.example_batch(kind)
        for index, item in enumerate(example[key]):
            if kind == "usage":
                contract.validate_event(item["name"], item["t"], item["props"], now)
            else:
                contract.validate_report(item, now)


# ----------------------------------------------------------------------------- defaults and independence


def test_defaults_are_off_and_unreadable_values_stay_off() -> None:
    fresh = AppSettings()
    assert fresh.send_usage_stats is False and fresh.send_error_reports is False
    assert AppSettings.from_dict({}).send_usage_stats is False
    assert AppSettings.from_dict({"send_usage_stats": "true", "send_error_reports": 1}).send_usage_stats is False
    assert AppSettings.from_dict({"send_usage_stats": "true", "send_error_reports": 1}).send_error_reports is False


def test_stale_consent_version_counts_as_off() -> None:
    settings = AppSettings(send_usage_stats=True, send_error_reports=True, privacy_consent_version=0)
    assert not effective_consent(settings, "usage") and not effective_consent(settings, "errors")
    settings.privacy_consent_version = consent.current_consent_version()
    assert effective_consent(settings, "usage") and effective_consent(settings, "errors")


def test_off_creates_no_files_no_ids_and_no_requests(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    for _ in range(50):
        cloud.usage.item_check("sidegrade", "high", "full", "lt_500ms")
    cloud.errors.capture("EL-WRK-002", RuntimeError, None)
    cloud.tick(clock.now + 10_000)
    cloud.stop()
    assert http.calls == []
    assert tree(tmp_path) == []
    assert not cloud.usage.active and not cloud.errors.active


def test_no_endpoint_means_nothing_is_collected_even_when_opted_in(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True, errors_on=True, url=None)
    cloud.start()
    cloud.report_startup()
    cloud.usage.item_check("sidegrade", "high", "full", "lt_500ms")
    cloud.tick(clock.now + 10_000)
    cloud.stop()
    assert http.calls == [] and tree(tmp_path) == []
    assert not cloud.configured()


def test_only_usage_on_sends_only_usage(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.errors.capture("EL-WRK-002", TimeoutError, None)
    cloud.tick(clock.now + 5)
    assert http.paths() == ["/v1/telemetry/batch"]
    assert "analytics_id" in http.calls[0][1] and "diagnostic_id" not in http.calls[0][1]
    assert not (tmp_path / "cloud" / "errors").exists()


def test_only_errors_on_sends_only_errors(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, errors_on=True)
    cloud.start()
    cloud.report_startup()
    cloud.usage.item_check("sidegrade", "high", "full", "lt_500ms")
    cloud.errors.capture("EL-WRK-002", TimeoutError, None)
    cloud.tick(clock.now + 5)
    assert http.paths() == ["/v1/errors/batch"]
    assert "diagnostic_id" in http.calls[0][1] and "analytics_id" not in http.calls[0][1]
    assert not (tmp_path / "cloud" / "telemetry").exists()


def test_the_two_ids_are_independent_random_uuids(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True, errors_on=True)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.errors.capture("EL-WRK-002", TimeoutError, None)
    cloud.tick(clock.now + 5)
    ids = {path: body.get("analytics_id") or body.get("diagnostic_id") for path, body in http.calls}
    assert set(ids) == {"/v1/telemetry/batch", "/v1/errors/batch"}
    assert ids["/v1/telemetry/batch"] != ids["/v1/errors/batch"]
    assert all(contract._compile(contract.schema()["types"]["uuid"]["regex"]).fullmatch(v) for v in ids.values())


# ----------------------------------------------------------------------------- opt-out / purge


def test_opt_out_purges_queue_and_id_immediately_and_reopt_in_creates_new_identity(tmp_path: Path) -> None:
    forgets: list = []
    http = FakeHttp([PostResult(status=503, retry_after=3600)])
    cloud, settings, http, clock = make_services(tmp_path, usage=True, http=http)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.tick(clock.now + 5)  # fails with 503: the batch stays queued on disk
    first_id = CategoryStore(tmp_path / "cloud" / "telemetry").read_id()
    assert first_id and (tmp_path / "cloud" / "telemetry" / "queue.jsonl").exists()

    consent.set_consent(settings, usage=False, cloud=cloud, save=lambda _s: None)
    assert not cloud.usage.active
    assert not (tmp_path / "cloud" / "telemetry").exists()
    # best-effort server forget happens on a background thread; give it a moment
    import time

    deadline = time.time() + 3
    while time.time() < deadline and "/v1/telemetry/forget" not in http.paths():
        time.sleep(0.02)
    forget = [body for path, body in http.calls if path == "/v1/telemetry/forget"]
    assert forget and forget[0]["analytics_id"] == first_id

    consent.set_consent(settings, usage=True, cloud=cloud, save=lambda _s: None)
    cloud.usage.app_started(launch="normal", previous_session="clean", pob_configured=True)
    cloud.tick(clock.now + 10_000)
    second_id = CategoryStore(tmp_path / "cloud" / "telemetry").read_id()
    assert second_id and second_id != first_id
    assert forgets == []


def test_opt_out_of_one_category_leaves_the_other_untouched(tmp_path: Path) -> None:
    cloud, settings, http, clock = make_services(tmp_path, usage=True, errors_on=True, http=FakeHttp([PostResult(status=503)] * 2))
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.errors.capture("EL-WRK-002", TimeoutError, None)
    cloud.tick(clock.now + 5)
    assert (tmp_path / "cloud" / "errors" / "queue.jsonl").exists()
    consent.set_consent(settings, usage=False, cloud=cloud, save=lambda _s: None)
    assert not (tmp_path / "cloud" / "telemetry").exists()
    assert (tmp_path / "cloud" / "errors" / "queue.jsonl").exists()
    assert cloud.errors.active


def test_request_in_flight_during_opt_out_cannot_requeue_or_persist(tmp_path: Path) -> None:
    clock = Clock()

    class RacingHttp(FakeHttp):
        def post_json(self, path, body, headers=None):
            sink.purge()  # the user opts out while the request is on the wire
            return PostResult(status=503, retry_after=60)

    store = CategoryStore(tmp_path / "telemetry")
    sink = Sink("usage", store, RacingHttp(), {"version": "0.7.0", "channel": "stable", "packaged": True, "os": "win11"}, clock=clock, first_flush_delay=0)
    sink.add({"name": "app_started", "t": telemetry.hour_string(clock.now), "props": {"launch": "normal", "previous_session": "clean", "pob_configured": True}})
    sink.flush(clock.now + 1)
    assert sink.pending_count() == 0
    assert not store.root.exists()


def test_settings_reset_semantics_turn_both_off(tmp_path: Path) -> None:
    from dataclasses import fields

    cloud, settings, _h, _c = make_services(tmp_path, usage=True, errors_on=True)
    cloud.start()
    defaults = AppSettings()
    for item in fields(AppSettings):
        setattr(settings, item.name, getattr(defaults, item.name))
    cloud.apply_consent()
    assert not cloud.usage.active and not cloud.errors.active
    assert tree(tmp_path / "cloud") == []


# ----------------------------------------------------------------------------- queue bounds / TTL / backoff


def _valid_event(clock) -> dict:
    return {"name": "app_started", "t": telemetry.hour_string(clock.now), "props": {"launch": "normal", "previous_session": "clean", "pob_configured": True}}


def test_queue_is_bounded_in_memory_and_on_disk(tmp_path: Path) -> None:
    clock = Clock()
    store = CategoryStore(tmp_path / "telemetry")
    sink = Sink("usage", store, FakeHttp([PostResult(status=0, code="network")] * 50), {"version": "0.7.0", "channel": "stable", "packaged": True, "os": "win11"}, clock=clock, first_flush_delay=0)
    limits = contract.limits()
    for _ in range(2000):
        sink.add(_valid_event(clock))
    assert sink.pending_count() <= limits["client_queue_max_events"]
    sink.persist()
    assert store.queue_path.stat().st_size <= limits["client_queue_max_bytes"]
    assert len(store.load_queue(clock.now)) <= limits["client_queue_max_events"]


def test_expired_queue_entries_are_dropped_on_load(tmp_path: Path) -> None:
    clock = Clock()
    store = CategoryStore(tmp_path / "telemetry")
    ttl = contract.limits()["client_queue_ttl_hours"] * 3600
    store.save_queue([{"q": clock.now - ttl - 10, "item": _valid_event(clock)}, {"q": clock.now - 5, "item": _valid_event(clock)}])
    loaded = store.load_queue(clock.now)
    assert len(loaded) == 1 and loaded[0]["q"] == clock.now - 5


def test_corrupt_queue_file_is_ignored(tmp_path: Path) -> None:
    store = CategoryStore(tmp_path / "telemetry")
    store.root.mkdir(parents=True)
    store.queue_path.write_text('not json\n{"q": 1}\n{"q": "x", "item": 3}\n', encoding="utf-8")
    assert store.load_queue(1_790_000_000.0) == []


def test_service_unavailable_backs_off_and_never_hammers(tmp_path: Path) -> None:
    http = FakeHttp([PostResult(status=503, retry_after=3600)] * 10)
    cloud, _s, http, clock = make_services(tmp_path, usage=True, http=http)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    t0 = clock.now
    cloud.tick(t0 + 5)
    assert len(http.calls) == 1
    for step in range(1, 100):  # keep ticking every 30 s for ~50 minutes
        cloud.tick(t0 + 5 + step * 30)
    assert len(http.calls) == 1  # Retry-After (1 h) honoured
    cloud.tick(t0 + 5 + 3700)
    assert len(http.calls) == 2


def test_exponential_backoff_with_cap_and_jitter() -> None:
    backoff = Backoff(rng=lambda: 0.5)
    delays = [backoff.failure(0.0) for _ in range(12)]
    assert delays[0] == pytest.approx(60.0) and delays[1] == pytest.approx(120.0)
    assert max(delays) <= 6 * 3600 * 1.2
    assert backoff.failure(0.0, retry_after=10 * 3600) >= 10 * 3600


def test_quota_exhaustion_429_keeps_bounded_queue_and_retries_later(tmp_path: Path) -> None:
    http = FakeHttp([PostResult(status=429, code="daily_cap", retry_after=7200), PostResult(status=202)])
    cloud, _s, http, clock = make_services(tmp_path, usage=True, http=http)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.tick(clock.now + 5)
    assert cloud.usage.sink.pending_count() >= 1
    cloud.tick(clock.now + 5 + 3600)
    assert len(http.calls) == 1
    cloud.tick(clock.now + 5 + 7300)
    assert len(http.calls) == 2 and cloud.usage.sink.pending_count() == 0


def test_poison_batch_is_dropped_not_retried(tmp_path: Path) -> None:
    http = FakeHttp([PostResult(status=400, code="invalid_envelope")])
    cloud, _s, http, clock = make_services(tmp_path, usage=True, http=http)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.tick(clock.now + 5)
    assert cloud.usage.sink.pending_count() == 0
    cloud.tick(clock.now + 100_000)
    assert len(http.calls) == 1


def test_unsupported_client_disables_the_category_until_restart(tmp_path: Path) -> None:
    http = FakeHttp([PostResult(status=410, code="client_unsupported")])
    cloud, _s, http, clock = make_services(tmp_path, usage=True, http=http)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.tick(clock.now + 5)
    cloud.usage.app_started(launch="normal", previous_session="clean", pob_configured=True)
    cloud.tick(clock.now + 100_000)
    assert len(http.calls) == 1 and cloud.usage.sink.status()["disabled"] == "client_unsupported"


def test_network_failure_is_a_retry_not_a_crash() -> None:
    def broken(request, timeout):
        raise OSError("unreachable")

    result = CloudHttp("https://x.test", opener=broken).post_json("/v1/telemetry/batch", {"a": 1})
    assert result.status == 0 and result.action.value == "retry"


# ----------------------------------------------------------------------------- shutdown / hot path


def test_stop_never_touches_the_network_and_persists_a_bounded_queue(tmp_path: Path, monkeypatch) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.usage.item_check("sidegrade", "high", "full", "lt_500ms")

    def forbidden(*_a, **_k):
        raise AssertionError("network used during shutdown")

    monkeypatch.setattr(socket, "socket", forbidden)
    cloud.stop()
    assert http.calls == []
    queued = CategoryStore(tmp_path / "cloud" / "telemetry").load_queue(clock.now)
    assert {row["item"]["name"] for row in queued} == {"app_started", "item_checks_summary"}


def test_counting_an_item_check_does_no_io(tmp_path: Path, monkeypatch) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True)
    cloud.start(pob_configured=True)
    before = tree(tmp_path)

    def forbidden(*_a, **_k):
        raise AssertionError("I/O on the item check path")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    for _ in range(5000):
        cloud.usage.item_check("sidegrade", "high", "full", "lt_500ms")
    assert http.calls == [] and tree(tmp_path) == before
    assert cloud.usage.pending_counters() == 5000


def test_wiring_connects_every_slot_queued_never_directly() -> None:
    source = (ROOT / "src" / "exilelens" / "cloud" / "wiring.py").read_text(encoding="utf-8")
    connects = [line for line in source.splitlines() if ".connect(" in line]
    assert connects and all("_QUEUED" in line for line in connects)


def test_item_check_summary_aggregates_instead_of_one_event_per_check(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True)
    cloud.start(pob_configured=True)
    for _ in range(40):
        cloud.usage.item_check("sidegrade", "high", "full", "lt_500ms")
    for _ in range(3):
        cloud.usage.item_check("unsupported", "none", "unsupported", "lt_1s")
    cloud.tick(clock.now + 5)
    events = http.calls[0][1]["events"]
    summaries = [e for e in events if e["name"] == "item_checks_summary"]
    assert len(summaries) == 1
    totals = {(b["verdict"]): b["n"] for b in summaries[0]["props"]["buckets"]}
    assert totals == {"sidegrade": 40, "unsupported": 3}
    assert "t" in summaries[0] and summaries[0]["t"].endswith(":00Z")


# ----------------------------------------------------------------------------- content boundary


def test_item_check_categories_contain_only_enums_never_item_data() -> None:
    result = {
        "raw_input": {"text": "Rarity: Rare\nDoom Bringer\nItem Class: Rings", "content_hash": "abc"},
        "item_name": "Doom Bringer",
        "recommendation": {
            "evaluation_outcome": {"verdict": "MINOR_UPGRADE", "evaluation_quality": "FULL", "price": 12, "build": "Spark Stormweaver"},
            "pob_slot": "Ring 1",
        },
        "decision": {"confidence": "HIGH", "confidence_reasons": ["clipboard text"]},
    }
    timing = SimpleNamespace(request_id=7, clipboard_received_ms=100.0, ui_updated_ms=350.0, evaluation_started_ms=0, evaluation_finished_ms=0)
    categories = telemetry.item_check_categories(result, timing, 7)
    assert categories == ("minor_upgrade", "high", "full", "lt_500ms")
    assert telemetry.item_check_categories(result, timing, 8) is None  # another request's timing is never reused


@pytest.mark.parametrize("raw,expected", [("POTENTIAL_UPGRADE", "uncertain"), ("UNSUPPORTED", "unsupported"), ("whatever", "not_evaluated")])
def test_verdict_mapping_is_closed(raw: str, expected: str) -> None:
    result = {"recommendation": {"evaluation_outcome": {"verdict": raw, "evaluation_quality": "FULL"}}, "decision": {}}
    timing = SimpleNamespace(request_id=1, clipboard_received_ms=1.0, ui_updated_ms=2.0, evaluation_started_ms=0, evaluation_finished_ms=0)
    assert telemetry.item_check_categories(result, timing, 1)[0] == expected


def test_analysis_categories_are_health_only_never_measured_values() -> None:
    payload = {
        "actionable": {
            "coverage": {"level": "PARTIAL", "established": 7, "relevant": 9, "summary": "7 / 9"},
            "build_health": [{"key": "res", "state": "NEARLY_CAPPED", "reason": "Fire 72%"}, {"key": "x", "state": "OPPORTUNITY"}],
            "response_curves": [{"stat": "Cast Speed", "value": 12.5}] * 5,
            "current_focus": {"kind": "ISSUE", "text": "Cold resistance 40%"},
            "ladders": {"life": [1, 2]},
        },
        "build_priorities": {"top": "Spark"},
    }
    fields = telemetry.analysis_categories(payload, 7.0)
    assert fields == {
        "outcome": "ok", "coverage": "partial", "curve_count": 3, "hard_issue_present": True,
        "health": "nearly_capped", "duration": "lt_15s",
    }
    assert telemetry.analysis_categories({}, 0.5)["outcome"] == "no_signal"


def test_nothing_queued_by_any_producer_can_hold_forbidden_content(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True, errors_on=True)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    cloud.usage.item_check("sidegrade", "high", "full", "lt_500ms")
    cloud.usage.analyze_build({"outcome": "ok", "coverage": "high", "curve_count": 1, "hard_issue_present": False, "health": "opportunity", "duration": "lt_5s"})
    # Hostile attempts: free text and unknown properties are dropped, never repaired.
    assert not cloud.usage._emit("app_started", {"launch": "normal", "previous_session": "clean", "pob_configured": True, "item_text": "Rarity: Rare"})
    assert not cloud.usage._emit("custom_event", {"x": "C:\\Users\\me\\build.xml"})
    assert not cloud.usage.sink.add({"name": "app_started", "t": "now", "props": {}})
    cloud.errors.capture("EL-WRK-002", TimeoutError, None)
    cloud.tick(clock.now + 5)
    text = json.dumps([body for _p, body in http.calls])
    for forbidden in ("Rarity", "C:\\\\", "build.xml", "item_text", "clipboard", "Users"):
        assert forbidden not in text


# ----------------------------------------------------------------------------- error reports


def _boom() -> None:
    secret = "C:\\Users\\Arek\\Desktop\\mybuild.xml Doom Bringer Rarity: Rare"
    raise RuntimeError(f"cannot read {secret}")


def test_report_is_built_from_objects_without_message_paths_or_filenames() -> None:
    try:
        _boom()
    except RuntimeError as exc:
        report = errors.build_report("EL-BLD-002", type(exc), exc.__traceback__, now=1_790_000_000.0)
    text = json.dumps(report)
    for forbidden in ("Users", "Arek", "mybuild", "Doom Bringer", "Rarity", ".py", "C:", "cannot read", "secret"):
        assert forbidden not in text
    assert report["exception_type"] == "RuntimeError"
    assert report["component"] == "BLD" and report["error_code"] == "EL-BLD-002"
    assert report["frames"] and all(set(f) <= {"module", "function", "line"} for f in report["frames"])
    assert any(f["module"].startswith("lib.") or f["module"].startswith("stdlib.") or f["module"].startswith("tests") or f["module"].startswith("test_") for f in report["frames"])
    contract.validate_report(report, 1_790_000_000.0 + 60)


def test_frames_from_other_packages_collapse_to_module_only() -> None:
    frame = errors._frame_for("PySide6.QtCore", "some_function", 42)
    assert frame == {"module": "lib.PySide6"}
    assert errors._frame_for("json.decoder", "raw_decode", 10) == {"module": "stdlib.json"}
    own = errors._frame_for("exilelens.app.engine", "PobWorker.call.<locals>.inner", 412)
    assert own == {"module": "exilelens.app.engine", "function": "PobWorker.call.locals.inner", "line": 412}


def test_unknown_exception_types_are_reported_as_other() -> None:
    class Weird(Exception):
        pass

    assert errors.exception_type_name(Weird) == "other"
    assert errors.exception_type_name(TimeoutError) == "TimeoutError"
    assert errors.exception_type_name(None) == "Failure"
    assert errors.exception_type_name(json.JSONDecodeError) == "json.decoder.JSONDecodeError"


def test_identical_errors_are_aggregated_and_daily_distinct_cap_applies(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, errors_on=True)
    cloud.start()
    for _ in range(25):
        cloud.errors.capture("EL-WRK-002", TimeoutError, None)
    for index in range(40):
        cloud.errors.capture(f"EL-CHK-{index + 1:03d}", ValueError, None)
    cloud.tick(clock.now + 5)
    reports = http.calls[0][1]["reports"]
    assert len(reports) == errors.DAILY_DISTINCT_REPORT_LIMIT
    timeout = [r for r in reports if r["error_code"] == "EL-WRK-002"]
    assert len(timeout) == 1 and timeout[0]["count"] == 25


def test_unexpected_session_end_is_reported_as_such_not_as_a_crash(tmp_path: Path) -> None:
    cloud, _s, http, clock = make_services(tmp_path, usage=True, errors_on=True)
    cloud.start(pob_configured=True)
    cloud.report_startup()
    assert cloud.previous_session == "first_run"
    # No stop(): simulates power loss / Task Manager / native crash.
    again, _s2, http2, clock2 = make_services(tmp_path, usage=True, errors_on=True)
    again.start(pob_configured=True)
    again.report_startup()
    assert again.previous_session == "unexpected"
    again.tick(clock2.now + 5)
    started = [e for body in (b for p, b in http2.calls if p.endswith("telemetry/batch")) for e in body["events"] if e["name"] == "app_started"]
    assert started and started[0]["props"]["previous_session"] == "unexpected"
    reports = [r for p, b in http2.calls if p.endswith("errors/batch") for r in b["reports"]]
    assert [r["error_code"] for r in reports] == ["EL-APP-100"] and reports[0]["exception_type"] == "UnexpectedSessionEnd"
    # A clean stop is recognised as clean next time.
    again.stop()
    third, *_ = make_services(tmp_path, usage=True, errors_on=True)
    third.start(pob_configured=True)
    assert third.previous_session == "clean"


def test_registered_error_code_exists_for_unexpected_session_end() -> None:
    from exilelens.error_catalog.registry import get_error_definition

    assert get_error_definition(errors.UNEXPECTED_SESSION_END_CODE) is not None


def test_recording_a_structured_error_forwards_only_when_registered_and_opted_in(tmp_path: Path) -> None:
    from exilelens.error_catalog.integration import record_exception
    from exilelens.error_catalog.session import ErrorContextStore

    cloud, _s, http, clock = make_services(tmp_path, errors_on=True)
    cloud.start()
    hooks.register(cloud)
    try:
        try:
            raise ValueError("path C:\\secret\\thing")
        except ValueError as exc:
            record_exception(ErrorContextStore(), exc, subsystem="build", stage="load")
        cloud.tick(clock.now + 5)
    finally:
        hooks.register(None)
    text = json.dumps(http.calls)
    assert "secret" not in text and "thing" not in text
    assert http.calls and http.calls[0][1]["reports"][0]["exception_type"] == "ValueError"


def test_uncertain_and_unsupported_outcomes_are_not_errors(tmp_path: Path) -> None:
    from exilelens.error_catalog.integration import record_evaluation_outcome
    from exilelens.error_catalog.session import ErrorContextStore

    cloud, _s, http, clock = make_services(tmp_path, errors_on=True)
    cloud.start()
    hooks.register(cloud)
    try:
        record_evaluation_outcome(ErrorContextStore(), {"recommendation": {"evaluation_outcome": {"verdict": "UNSUPPORTED", "reason_code": "OFFENSE_UNSUPPORTED"}}})
        cloud.tick(clock.now + 5)
    finally:
        hooks.register(None)
    assert http.calls == []


# ----------------------------------------------------------------------------- endpoint


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        ("", {}, None),
        ("http://api.example.test", {}, None),
        ("https://api.example.test/", {}, "https://api.example.test"),
        ("https://api.example.test/v1", {}, None),
        ("https://user:pw@api.example.test", {}, None),
        ("https://exilelens.acct.workers.dev", {}, None),
        ("https://exilelens.acct.workers.dev", {"allow_workers_dev": True}, "https://exilelens.acct.workers.dev"),
        ("http://127.0.0.1:8787", {}, None),
        ("http://127.0.0.1:8787", {"allow_local": True}, "http://127.0.0.1:8787"),
        ("ftp://api.example.test", {}, None),
    ],
)
def test_endpoint_normalisation_is_strict(value, kwargs, expected) -> None:
    assert normalize_base_url(value, **kwargs) == expected


def test_packaged_builds_ignore_the_env_override_and_ship_unconfigured(monkeypatch) -> None:
    from exilelens.cloud import endpoint

    monkeypatch.setenv(endpoint.ENV_OVERRIDE, "https://evil.example.test")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert endpoint.cloud_base_url() is None
    assert endpoint.release_config_url() is None  # committed release_config.json is empty
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert endpoint.cloud_base_url() == "https://evil.example.test"


def test_network_kill_switch_disables_cloud(monkeypatch) -> None:
    from exilelens.cloud import endpoint

    monkeypatch.setenv(endpoint.ENV_OVERRIDE, "https://api.example.test")
    monkeypatch.setattr("exilelens.security_audit.network_disabled", lambda: True)
    assert endpoint.cloud_base_url() is None


# ----------------------------------------------------------------------------- transparency / UI


def test_transparency_model_is_generated_from_the_contract(tmp_path: Path) -> None:
    cloud, *_ = make_services(tmp_path, usage=True, errors_on=True)
    model = transparency.describe(cloud)
    usage = next(c for c in model["categories"] if c["key"] == "usage")
    assert {e["name"] for e in usage["events"]} == set(contract.schema()["usage"]["events"])
    assert model["never_collected"] == contract.schema()["never_collected"]
    json.loads(usage["example"])


def test_consent_card_logic(tmp_path: Path) -> None:
    cloud, settings, *_ = make_services(tmp_path)
    fresh = AppSettings()
    assert consent.should_show_card(fresh, cloud, onboarding_pending=False)
    assert not consent.should_show_card(fresh, cloud, onboarding_pending=True)
    unconfigured, *_ = make_services(tmp_path, url=None)
    assert not consent.should_show_card(fresh, unconfigured, onboarding_pending=False)
    consent.dismiss_card(fresh, save=lambda _s: None)
    assert not consent.should_show_card(fresh, cloud, onboarding_pending=False)
    assert fresh.send_usage_stats is False and fresh.send_error_reports is False


def test_privacy_panel_and_consent_card_drive_the_services(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.privacy_panel import ConsentCard, PrivacyPanel

    app = QApplication.instance() or QApplication([])
    cloud, settings, http, clock = make_services(tmp_path)
    monkeypatch.setattr("exilelens.app.settings.save_settings", lambda _s: None)
    panel = PrivacyPanel(settings, cloud)
    assert not panel.errors_box.isChecked() and not panel.usage_box.isChecked()
    panel.usage_box.setChecked(True)
    assert settings.send_usage_stats is True and settings.send_error_reports is False and cloud.usage.active and not cloud.errors.active
    panel.usage_box.setChecked(False)
    assert not cloud.usage.active and not (tmp_path / "cloud" / "telemetry").exists()
    card = ConsentCard(settings, cloud)
    assert not card.usage_box.isChecked() and not card.errors_box.isChecked()
    card.errors_box.setChecked(True)
    card.save_button.click()
    assert settings.send_error_reports is True and settings.send_usage_stats is False and settings.privacy_card_resolved
    assert cloud.errors.active and not cloud.usage.active
    assert app is not None


def test_privacy_panel_is_disabled_when_the_build_has_no_endpoint(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.privacy_panel import PrivacyPanel

    app = QApplication.instance() or QApplication([])
    cloud, settings, *_ = make_services(tmp_path, url=None)
    panel = PrivacyPanel(settings, cloud)
    assert not panel.usage_box.isEnabled() and not panel.errors_box.isEnabled()
    assert app is not None

# ----------------------------------------------------------------------------- release gate


def test_release_gate_cloud_config(tmp_path: Path) -> None:
    from exilelens.ops import release_gate

    root = tmp_path
    (root / "src" / "exilelens" / "cloud").mkdir(parents=True)
    (root / "cloud" / "schema").mkdir(parents=True)
    contract_bytes = (ROOT / "cloud" / "schema" / "events.v1.json").read_bytes()
    (root / "cloud" / "schema" / "events.v1.json").write_bytes(contract_bytes)
    (root / "src" / "exilelens" / "cloud" / "events.v1.json").write_bytes(contract_bytes)
    config = root / "src" / "exilelens" / "cloud" / "release_config.json"

    assert release_gate._cloud_config(root).status.value == "PASS"  # absent = cloud off
    config.write_text('{"schema": 1, "api_base_url": ""}', encoding="utf-8")
    assert release_gate._cloud_config(root).status.value == "PASS"
    config.write_text('{"schema": 1, "api_base_url": "https://api.example.test"}', encoding="utf-8")
    assert release_gate._cloud_config(root).status.value == "PASS"
    for bad in ("https://exilelens.acct.workers.dev", "http://api.example.test", "https://api.example.test/v1"):
        config.write_text(json.dumps({"schema": 1, "api_base_url": bad}), encoding="utf-8")
        assert release_gate._cloud_config(root).status.value == "BLOCKED", bad
    config.write_text("not json", encoding="utf-8")
    assert release_gate._cloud_config(root).status.value == "BLOCKED"
    config.unlink()
    (root / "src" / "exilelens" / "cloud" / "events.v1.json").write_bytes(contract_bytes + b" ")
    assert release_gate._cloud_config(root).status.value == "BLOCKED"
