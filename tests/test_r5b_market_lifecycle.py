"""R5-B: post-paint market enrichment in the real EvaluationController, with injected providers only.

Deterministic: the worker hook (`_market_spawn`) collects jobs and the tests decide when each one completes, so no test sleeps or races.
The controller is constructed for real (offscreen Qt); no PoB engine exists in it, and the engine/scheduler are rigged to explode if market
work ever touches them.
"""

from __future__ import annotations

import inspect
import json
import sys
import threading

import pytest

from exilelens.price_check import market_policy
from exilelens.price_check.market_evidence import EvidenceStatus
from exilelens.price_check.market_evidence_service import MarketEvidenceService
from exilelens.price_check.market_policy import MarketAccessDecision, MarketAccessState
from tests.market_support import RING_ITEM, make_client, make_provider, scenario_transport

pytestmark = pytest.mark.itemcheck

LEAGUE = "Synthetic League"
ITEM_A = RING_ITEM.read_text(encoding="utf-8") + "Note: ~b/o 35 exalted\n"
ITEM_B = ITEM_A.replace("40% increased Cast Speed", "20% increased Cast Speed")
AVAILABLE = MarketAccessDecision(MarketAccessState.AVAILABLE, True, "test")


class Explodes:
    """Stands in for the PoB engine / scheduler: any use fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"market enrichment touched the PoB path: {name}")


@pytest.fixture
def controller(monkeypatch, tmp_path):
    if sys.platform != "win32":
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings

    settings = AppSettings()
    settings.market_league = LEAGUE
    settings.market_league_mode = "PINNED"
    ctl = EvaluationController(settings)
    ctl._test_app = app
    ctl._market_jobs = []
    ctl._market_spawn = ctl._market_jobs.append
    ctl._engine = Explodes()
    ctl._scheduler = Explodes()
    emitted: list = []
    ctl.market_evidence_updated.connect(lambda rid, result: emitted.append((rid, result)))
    ctl._emitted = emitted
    yield ctl
    ctl._engine = None
    ctl.shutdown()


def _opt_in(ctl, *, authorized: bool):
    ctl.settings.market_prices_enabled = True
    ctl.settings.market_consent_version = market_policy.MARKET_CONSENT_VERSION
    market_policy.LIVE_TRADE2_AUTHORIZED = authorized


@pytest.fixture(autouse=True)
def _restore_policy_constant():
    original = market_policy.LIVE_TRADE2_AUTHORIZED
    yield
    market_policy.LIVE_TRADE2_AUTHORIZED = original


def _paint(ctl, item=ITEM_A, request_id=1, content_hash="hash-a"):
    """What the controller holds right after TERMINAL_PAINT for this item."""
    result = {
        "raw_input": {"raw_text": item, "content_hash": content_hash},
        "request_meta": {"request_id": request_id, "presentation_generation": ctl.presentation_generation, "content_hash": content_hash},
        "recommendation": {"verdict": "UPGRADE"},
        "evaluation_outcome": {"verdict": "UPGRADE"},
    }
    ctl._last_result = result
    return result


def _fake_service(ctl, transport=None, provider=None):
    transport = transport or scenario_transport("strong")
    ctl._market_service = MarketEvidenceService(
        access_fn=lambda: AVAILABLE,
        provider_factory=(lambda: provider) if provider is not None else (lambda: make_provider(make_client(transport))),
        wall_clock=lambda: 5000.0,
    )
    return transport


def _run_next(ctl):
    ctl._market_jobs.pop(0)()


# ------------------------------------------------------------------------------------------------------- market OFF


def test_market_off_is_inert(controller):
    result = _paint(controller)
    controller._maybe_schedule_market_evidence(1, result)
    assert controller._market_jobs == [] and controller._market_active is None
    assert controller._market_service is None, "the service is not even created"
    assert "market_evidence" not in controller._last_result and controller._emitted == []
    assert controller.market_evidence_diagnostics()["access_state"] == "DISABLED_BY_USER"


def test_consent_that_is_not_current_counts_as_off(controller):
    controller.settings.market_prices_enabled = True
    controller.settings.market_consent_version = market_policy.MARKET_CONSENT_VERSION + 5
    controller._maybe_schedule_market_evidence(1, _paint(controller))
    assert controller._market_jobs == [] and controller._market_service is None


def test_no_network_build_is_inert(controller, monkeypatch):
    from exilelens import security_audit

    monkeypatch.setenv("EXILELENS_AUDIT_VARIANT", "no_network")
    security_audit.variant.cache_clear()
    try:
        _opt_in(controller, authorized=True)
        controller._maybe_schedule_market_evidence(1, _paint(controller))
        assert controller._market_jobs == [] and controller._market_service is None
    finally:
        monkeypatch.delenv("EXILELENS_AUDIT_VARIANT")
        security_audit.variant.cache_clear()


# ------------------------------------------------------------------------------- opted in but provider policy-blocked


def test_policy_blocked_production_path_is_typed_inline_and_makes_no_request(controller):
    _opt_in(controller, authorized=False)
    result = _paint(controller)
    before = dict(result)
    controller._maybe_schedule_market_evidence(1, result)
    assert controller._market_jobs == [], "answered from the access decision alone: no thread, no I/O"
    evidence = controller._last_result["market_evidence"]
    assert (evidence["status"], evidence["reason_code"]) == ("UNAVAILABLE", "PROVIDER_NOT_AUTHORIZED")
    assert evidence["price"] is None and evidence["headline"] is None
    assert controller._market_service._provider is None, "the live provider stack was never constructed"
    assert {k: v for k, v in controller._last_result.items() if k != "market_evidence"} == before
    assert [rid for rid, _ in controller._emitted] == [1]


# ----------------------------------------------------------------------------------------- opted in, synthetic success


def test_terminal_paint_comes_before_enrichment_and_enrichment_updates_the_same_item(controller):
    _opt_in(controller, authorized=True)
    transport = _fake_service(controller)
    result = _paint(controller)
    controller._maybe_schedule_market_evidence(1, result)
    # Scheduled, not run: the painted result is complete and unchanged, and nothing market-related has happened yet.
    assert len(controller._market_jobs) == 1 and transport.requests == []
    assert "market_evidence" not in controller._last_result and controller._market_active is not None
    assert controller.market_evidence_diagnostics()["pending"] is True
    _run_next(controller)
    updated = controller._last_result
    assert updated["market_evidence"]["status"] == "AVAILABLE" and updated["market_evidence"]["headline"] == "STRONG_COMPARABLE_SET"
    assert updated["market_evidence"]["listed_price"]["amount"] == 35.0 and updated["market_evidence"]["listed_vs_market"] == "WITHIN"
    assert updated["recommendation"] == {"verdict": "UPGRADE"} and updated["evaluation_outcome"] == {"verdict": "UPGRADE"}
    assert [rid for rid, _ in controller._emitted] == [1] and controller._market_active is None


def test_the_finish_path_schedules_enrichment_only_after_the_terminal_paint():
    from exilelens.app.controller import EvaluationController

    source = inspect.getsource(EvaluationController._deliver_evaluation_result)
    emit = source.index("self.evaluation_finished.emit(request_id, result)")
    terminal = source.index("ItemCheckPhase.TERMINAL_PAINT")
    market = source.index("self._maybe_schedule_market_evidence(")
    assert emit < terminal < market
    # And scheduling is wrapped so it can never raise into the finish path.
    assert "except Exception" in inspect.getsource(EvaluationController._maybe_schedule_market_evidence)


def test_enrichment_performs_no_pob_work(controller):
    """`_engine` and `_scheduler` explode on any access: a full schedule -> run -> apply cycle must not touch them."""
    _opt_in(controller, authorized=True)
    _fake_service(controller)
    controller._maybe_schedule_market_evidence(1, _paint(controller))
    _run_next(controller)
    assert controller._last_result["market_evidence"]["status"] == "AVAILABLE"


# ------------------------------------------------------------------------------------- stale / cancellation rules


def test_a_stale_item_a_result_cannot_overwrite_item_b(controller):
    _opt_in(controller, authorized=True)
    _fake_service(controller)
    controller._maybe_schedule_market_evidence(1, _paint(controller, ITEM_A, 1, "hash-a"))
    # The user copies B: a new Item Check begins (cancelling A's enrichment) and B paints.
    controller._cancel_market_evidence_work()
    b = _paint(controller, ITEM_B, 2, "hash-b")
    _run_next(controller)  # A's lookup finishes late
    assert "market_evidence" not in controller._last_result and controller._last_result is b
    controller._maybe_schedule_market_evidence(2, b)
    _run_next(controller)
    assert controller._last_result["raw_input"]["content_hash"] == "hash-b" and "market_evidence" in controller._last_result


def test_a_slow_provider_still_running_while_a_newer_item_paints_is_discarded(controller):
    release = threading.Event()
    started = threading.Event()

    class Slow:
        def lookup(self, request):
            started.set()
            release.wait(10)
            return make_provider(make_client(scenario_transport("strong"))).lookup(request)

    _opt_in(controller, authorized=True)
    _fake_service(controller, provider=Slow())
    controller._maybe_schedule_market_evidence(1, _paint(controller, ITEM_A, 1, "hash-a"))
    job = controller._market_jobs.pop(0)
    worker = threading.Thread(target=job)
    worker.start()
    assert started.wait(5)
    # B arrives and paints while A's provider call is still in flight.
    controller._cancel_market_evidence_work()
    b = _paint(controller, ITEM_B, 2, "hash-b")
    release.set()
    worker.join(10)
    controller._test_app.processEvents()
    assert controller._last_result is b and "market_evidence" not in b and controller._emitted == []


@pytest.mark.parametrize(
    "change",
    [
        lambda c: setattr(c, "_baseline_generation", c._baseline_generation + 1),
        lambda c: c.invalidate_presentation(),
        lambda c: setattr(c.settings, "market_league", "Another League"),
        lambda c: setattr(c.settings, "market_prices_enabled", False),
        lambda c: setattr(c.settings, "market_consent_version", 0),
    ],
    ids=["baseline", "presentation", "league", "disabled", "consent"],
)
def test_relevant_identity_changes_discard_the_result(controller, change):
    _opt_in(controller, authorized=True)
    _fake_service(controller)
    controller._maybe_schedule_market_evidence(1, _paint(controller))
    change(controller)
    _run_next(controller)
    assert "market_evidence" not in controller._last_result and controller._emitted == []


def test_a_different_last_result_is_never_enriched(controller):
    _opt_in(controller, authorized=True)
    _fake_service(controller)
    controller._maybe_schedule_market_evidence(1, _paint(controller, ITEM_A, 1, "hash-a"))
    _paint(controller, ITEM_B, 1, "hash-b")  # same request id and generations, different candidate
    _run_next(controller)
    assert "market_evidence" not in controller._last_result


def test_a_newer_schedule_obsoletes_the_pending_one(controller):
    _opt_in(controller, authorized=True)
    _fake_service(controller)
    controller._maybe_schedule_market_evidence(1, _paint(controller, ITEM_A, 1, "hash-a"))
    controller._maybe_schedule_market_evidence(2, _paint(controller, ITEM_B, 2, "hash-b"))
    _run_next(controller)  # job for A
    assert "market_evidence" not in controller._last_result
    _run_next(controller)  # job for B
    assert "market_evidence" in controller._last_result


# ------------------------------------------------------------------------------------------------- failures never leak


def test_a_throwing_provider_becomes_typed_evidence_and_never_reaches_item_check(controller):
    class Boom:
        def lookup(self, request):
            raise RuntimeError("synthetic provider bug")

    _opt_in(controller, authorized=True)
    _fake_service(controller, provider=Boom())
    result = _paint(controller)
    controller._maybe_schedule_market_evidence(1, result)
    _run_next(controller)
    evidence = controller._last_result["market_evidence"]
    assert evidence["status"] == "UNAVAILABLE" and evidence["price"] is None
    assert controller._last_result["recommendation"] == {"verdict": "UPGRADE"}


def test_a_broken_service_is_contained_by_the_job_runner(controller):
    class Broken:
        def evidence_for(self, *args, **kwargs):
            raise RuntimeError("synthetic service bug")

        def diagnostics(self):
            return {}

    _opt_in(controller, authorized=True)
    controller._market_service = Broken()
    controller._maybe_schedule_market_evidence(1, _paint(controller))
    _run_next(controller)
    assert controller._last_result["market_evidence"]["reason_code"] == "PROVIDER_ERROR"


def test_scheduling_failures_never_raise(controller):
    _opt_in(controller, authorized=True)
    controller._market_spawn = lambda job: (_ for _ in ()).throw(RuntimeError("cannot start thread"))
    _fake_service(controller)
    controller._maybe_schedule_market_evidence(1, _paint(controller))  # must not raise
    assert controller._market_active is None


def test_rate_limited_and_unavailable_providers_are_typed(controller):
    from tests.market_support import FakeTransport, error_response

    _opt_in(controller, authorized=True)
    _fake_service(controller, FakeTransport(lambda r: error_response("rate_limited_429")))
    controller._maybe_schedule_market_evidence(1, _paint(controller))
    _run_next(controller)
    assert controller._last_result["market_evidence"]["status"] == "RATE_LIMITED"
    assert controller.market_evidence_diagnostics()["rate_limited"] is True


# --------------------------------------------------------------------------------------------------------- diagnostics


def test_controller_diagnostics_hold_operational_state_only(controller):
    _opt_in(controller, authorized=True)
    _fake_service(controller)
    controller._maybe_schedule_market_evidence(1, _paint(controller))
    _run_next(controller)
    diag = controller.market_evidence_diagnostics()
    assert set(diag) == {"access_state", "network_permitted", "provider_id", "last_status", "last_reason_code", "freshness", "rate_limited",
                         "cache_entries", "provider_lookups", "pending"}
    blob = json.dumps(diag)
    for private in ("Arcane Loop", "Synthetic", "Seller", "syn0", "35"):
        assert private not in blob
    assert diag["last_status"] == EvidenceStatus.AVAILABLE.value and diag["pending"] is False
