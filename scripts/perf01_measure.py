"""PERF-01 runtime-responsiveness measurement harness (real PoB, real Qt UI objects).

Measures the three workflows PERF-01 is about, against the INSTALLED PoB runtime (leave POB2_PATH unset):

  startup   one fresh process per run: the real ``ExileLensApp.run()`` startup sequence (settings, QApplication,
            controller/overlay/dashboard/tray composition, async engine boot, startup build load) with a UI-thread
            stall monitor. Reports stage timestamps and every event-loop stall >= --stall-ms.
  session   one process: boot the engine, load a build, run Shift+C-equivalent Item Checks through the real
            ``EvaluationController.submit_clipboard_text`` -> overlay path, then switch builds and check again.
            Reports build-switch UI-thread stalls and per-stage Item Check timings (UI vs PoB compute).

The hotkey/clipboard capture (SendInput + clipboard poll) needs a live game window and is not exercised here.
Everything runs in an isolated LOCALAPPDATA, registers no global hotkey and writes nothing to the real profile.

Usage:
  python scripts/perf01_measure.py startup --build core04_player_ring --runs 5 --out artifacts/perf01/startup.json
  python scripts/perf01_measure.py session --builds core04_player_ring,corpus02e_spell_totem_titan --runs 8 \
         --out artifacts/perf01/session.json [--qpa windows|offscreen]
  python scripts/perf01_measure.py report artifacts/perf01/session.json

Timings are machine-dependent; run nothing else concurrently.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("PERF01_TREE") or Path(__file__).resolve().parents[1]).resolve()
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"

# build id -> equipped slot cloned with +100 maximum Life as the Item Check candidate (same corpus as r4_gate_measure)
CANDIDATE_SLOT = {
    "core04_player_ring": "Ring 1",
    "core04_melee_weapon": "Amulet",
    "corpus02e_spell_totem_titan": "Amulet",
    "core04_bow_quiver": "Ring 1",
    "core04_minion_actor": "Ring 1",
    "core04_poison_ailment": "Ring 1",
    "corpus02b_varashta_djinn": "Ring 1",
    "corpus02g_strength_oracle_brutus": "Ring 1",
}


def _build_path(name: str) -> Path:
    for base in (CORPUS, ROOT / "fixtures" / "builds"):
        candidate = base / f"{name}.xml"
        if candidate.is_file():
            return candidate
    raise SystemExit(f"unknown build fixture: {name}")


def _candidate_text(build: Path, slot: str) -> str:
    from xml.etree import ElementTree

    root = ElementTree.parse(build).getroot()
    items = root.find("Items")
    raw = {i.get("id"): (i.text or "").strip() for i in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(e for e in items.findall("ItemSet") if e.get("id") == active)
    item_id = next(e.get("itemId") for e in item_set.findall("Slot") if e.get("name") == slot)
    return raw[item_id] + "\n+100 to maximum Life\n"


# --------------------------------------------------------------------------------------------------------------------
# instrumentation


class Recorder:
    """Timestamped span log (ms since t0). Thread-safe: worker-thread spans are recorded with their thread name."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.spans: list[dict[str, Any]] = []
        self.marks: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.phase = "init"

    def now(self) -> float:
        return (time.perf_counter() - self.t0) * 1000.0

    def mark(self, label: str, **extra: Any) -> float:
        t = self.now()
        with self._lock:
            self.marks.append({"label": label, "t": round(t, 2), **extra})
        return t

    def span(self, label: str, start: float, end: float) -> None:
        with self._lock:
            self.spans.append(
                {
                    "label": label,
                    "start": round(start, 2),
                    "dur": round(end - start, 2),
                    "thread": threading.current_thread().name,
                    "phase": self.phase,
                }
            )


def wrap(rec: Recorder, owner: Any, name: str, label: str | None = None) -> None:
    """Replace ``owner.name`` with a timing wrapper that records one span per call."""
    original = getattr(owner, name, None)
    if original is None:  # an API the tree under test does not have (A/B against an older tree)
        return
    span_label = label or f"{type(owner).__name__ if not isinstance(owner, type) else owner.__name__}.{name}"

    def timed(*args: Any, **kwargs: Any):
        start = rec.now()
        try:
            return original(*args, **kwargs)
        finally:
            rec.span(span_label, start, rec.now())

    timed.__name__ = getattr(original, "__name__", name)
    setattr(owner, name, timed)


class StallMonitor:
    """Event-loop heartbeat: a QTimer every ``interval_ms``; gaps >= ``threshold_ms`` are UI-thread stalls."""

    def __init__(self, rec: Recorder, interval_ms: int = 4, threshold_ms: float = 40.0) -> None:
        from PySide6.QtCore import QTimer

        self.rec = rec
        self.threshold = threshold_ms
        self.interval = interval_ms
        self.stalls: list[dict[str, Any]] = []
        self.ticks = 0
        self._last = time.perf_counter()
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._last = time.perf_counter()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        now = time.perf_counter()
        gap = (now - self._last) * 1000.0
        self._last = now
        self.ticks += 1
        if gap - self.interval >= self.threshold:
            self.stalls.append(
                {"end": round(self.rec.now(), 2), "gap_ms": round(gap, 1), "phase": self.rec.phase}
            )

    def summary(self) -> dict[str, Any]:
        gaps = [s["gap_ms"] for s in self.stalls]
        return {
            "threshold_ms": self.threshold,
            "count": len(gaps),
            "max_ms": max(gaps) if gaps else 0.0,
            "total_ms": round(sum(gaps), 1),
            "stalls": self.stalls,
        }


def _isolated_profile(build_path: str) -> str:
    """Seed an isolated LOCALAPPDATA with a completed-onboarding profile that points at ``build_path``."""
    root = tempfile.mkdtemp(prefix="perf01-localappdata-")
    os.environ["LOCALAPPDATA"] = root
    from exilelens.app.settings import ONBOARDING_VERSION, AppSettings, save_settings

    settings = AppSettings()
    settings.build_path = build_path
    settings.onboarding_version_completed = ONBOARDING_VERSION
    settings.privacy_card_resolved = True
    settings.show_hotkey_hints = False
    save_settings(settings)
    return root


def _quiet_patches() -> None:
    """No global hotkey, no single-instance lock, no update network: nothing outside this process is touched."""
    from exilelens.app.main import ExileLensApp
    from exilelens.app.single_instance import InstanceLock
    from exilelens.app.update_check import UpdateService
    from exilelens.app.price_check_hotkey import PriceCheckHotkeyController

    import exilelens.app.main as main_module

    main_module.acquire_single_instance_lock = lambda: InstanceLock(acquired=True, reason="perf01")
    ExileLensApp._start_instance_server = lambda self: None  # type: ignore[method-assign]
    UpdateService.start_automatic = lambda self: False  # type: ignore[method-assign]
    UpdateService.begin_session = lambda self: None  # type: ignore[method-assign]
    PriceCheckHotkeyController.start = lambda self: True  # type: ignore[method-assign]
    PriceCheckHotkeyController.stop = lambda self: None  # type: ignore[method-assign]


def _instrument_engine_calls(rec: Recorder, engine: Any) -> dict[str, list[float]]:
    """Per-PoB-method wall time (ms) for every worker round trip, whichever thread issues it."""
    calls: dict[str, list[float]] = {}
    original = engine._call
    lock = threading.Lock()

    def counted(method, params=None):
        start = rec.now()
        try:
            return original(method, params)
        finally:
            end = rec.now()
            with lock:
                calls.setdefault(str(method), []).append(round(end - start, 2))
            rec.span(f"pob:{method}", start, end)

    engine._call = counted
    return calls


# --------------------------------------------------------------------------------------------------------------------
# startup mode (one fresh process per run)


def run_startup_once(build: str, stall_ms: float) -> dict[str, Any]:
    t_proc = time.perf_counter()
    rec = Recorder()
    from PySide6.QtCore import QTimer

    build_path = str(_build_path(build))
    _isolated_profile(build_path)
    import exilelens.app.controller as controller_module
    from exilelens.app.main import ExileLensApp
    from exilelens.engine import Engine

    _quiet_patches()
    rec.mark("imports_done", since_proc_ms=round((time.perf_counter() - t_proc) * 1000, 1))
    stalls: list[StallMonitor] = []
    result: dict[str, Any] = {"build": build}

    for name in ("_compose_primary_ui", "_show_tray", "_wire_signals", "_start_engine", "_on_engine_ready"):
        wrap(rec, ExileLensApp, name, f"app.{name}")
    wrap(rec, controller_module.EvaluationController, "load_build", "ctrl.load_build")
    wrap(rec, controller_module.EvaluationController, "_capture_ready_baseline", "ctrl._capture_ready_baseline")
    for optional in ("load_build_async", "_apply_baseline_capture", "_settle_baseline_job", "_begin_build_load"):
        if hasattr(controller_module.EvaluationController, optional):
            wrap(rec, controller_module.EvaluationController, optional, f"ctrl.{optional}")
    wrap(rec, controller_module.EvaluationController, "_on_engine_boot_result", "ctrl._on_engine_boot_result")
    wrap(rec, controller_module.EvaluationController, "start_engine_async", "ctrl.start_engine_async")
    wrap(rec, Engine, "start", "engine.start")
    wrap(rec, Engine, "load_build", "engine.load_build")

    shell = ExileLensApp()
    rec.mark("app_constructed")
    original_start_engine = ExileLensApp._start_engine
    calls_holder: dict[str, Any] = {}

    def _first_tick_start_engine(self):  # runs as the first event-loop task
        rec.mark("event_loop_first_task")
        monitor = StallMonitor(rec, threshold_ms=stall_ms)
        monitor.start()
        stalls.append(monitor)
        rec.phase = "engine_boot"
        original_start_engine(self)

    ExileLensApp._start_engine = _first_tick_start_engine  # type: ignore[method-assign]

    original_ready = ExileLensApp._on_engine_ready

    def _ready(self):
        rec.mark("engine_ready")
        rec.phase = "startup_build_load"
        engine = getattr(self.controller, "_engine", None)
        if engine is not None and "engine" not in calls_holder:
            calls_holder["engine"] = _instrument_engine_calls(rec, engine)
        done = {"marked": False}

        def _finish() -> None:
            rec.mark("finished")
            stalls[0].stop()
            from PySide6.QtWidgets import QApplication

            QApplication.instance().quit()

        def _on_changed(info) -> None:
            if done["marked"] or str(getattr(info.state, "value", info.state)) != "READY":
                return
            done["marked"] = True
            rec.mark("build_ready", state="READY")
            rec.phase = "idle"
            QTimer.singleShot(400, _finish)

        self.controller.build_changed.connect(_on_changed)
        original_ready(self)
        rec.mark("engine_ready_handler_returned", state=str(self.controller.build_info.state.value))

    ExileLensApp._on_engine_ready = _ready  # type: ignore[method-assign]
    rec.mark("run_begin")
    exit_code = shell.run()
    result["exit_code"] = exit_code
    result["total_ms"] = round(rec.now(), 1)
    result["since_proc_ms"] = round((time.perf_counter() - t_proc) * 1000, 1)
    result["marks"] = rec.marks
    result["spans"] = rec.spans
    result["stalls"] = stalls[0].summary() if stalls else {}
    result["pob_calls"] = {k: [round(x, 1) for x in v] for k, v in calls_holder.get("engine", {}).items()}
    try:
        shell.shutdown()
    except Exception:  # noqa: BLE001
        pass
    return result


def cmd_startup(args: argparse.Namespace) -> int:
    runs: list[dict[str, Any]] = []
    for index in range(args.runs):
        started = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "_startup_child", "--build", args.build,
             "--stall-ms", str(args.stall_ms)],
            capture_output=True, text=True, cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "QT_QPA_PLATFORM": args.qpa} if args.qpa else {**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        wall = (time.perf_counter() - started) * 1000
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("PERF01_JSON ")), None)
        if line is None:
            print(f"run {index}: FAILED rc={proc.returncode}\n{proc.stdout[-1500:]}\n{proc.stderr[-2500:]}")
            continue
        data = json.loads(line[len("PERF01_JSON "):])
        data["driver_wall_ms"] = round(wall, 1)
        runs.append(data)
        marks = {m["label"]: m["t"] for m in data["marks"]}
        print(
            f"run {index}: wall={wall:.0f}ms app_constructed={marks.get('app_constructed')} "
            f"first_task={marks.get('event_loop_first_task')} engine_ready={marks.get('engine_ready')} "
            f"build_ready={marks.get('build_ready')} max_stall={data['stalls'].get('max_ms')}ms "
            f"stalls={data['stalls'].get('count')}",
            flush=True,
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": "startup", "build": args.build, "runs": runs}, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0


# --------------------------------------------------------------------------------------------------------------------
# session mode: build load / switch + Item Check through the real controller and overlay


def _pump(app: Any, predicate, timeout_s: float) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    deadline = time.perf_counter() + timeout_s
    poll = QTimer()
    poll.setInterval(2)

    def check() -> None:
        if predicate() or time.perf_counter() > deadline:
            loop.quit()

    poll.timeout.connect(check)
    poll.start()
    loop.exec()
    poll.stop()
    return predicate()


def _drain(app: Any, ms: float) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


def run_session(args: argparse.Namespace) -> dict[str, Any]:
    builds = [b.strip() for b in args.builds.split(",") if b.strip()]
    rec = Recorder()
    first = str(_build_path(builds[0]))
    _isolated_profile(first)
    if args.qpa:
        os.environ["QT_QPA_PLATFORM"] = args.qpa
    from PySide6.QtWidgets import QApplication

    import exilelens.app.controller as controller_module
    from exilelens.app.build_state import BuildState
    from exilelens.app.main import ExileLensApp
    from exilelens.engine import Engine
    from exilelens.ui.overlay import OverlayWindow

    _quiet_patches()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    shell = ExileLensApp()
    shell._compose_primary_ui(quit_callback=lambda: None)
    shell._wire_signals()
    controller = shell.controller
    overlay = shell.overlay
    assert controller is not None and overlay is not None
    overlay.setWindowOpacity(0.0)  # realistic paint cost, invisible on the user's desktop

    C = controller_module.EvaluationController
    for name in (
        "load_build", "_capture_ready_baseline", "submit_clipboard_text", "_ensure_offense_coverage",
        "load_build_async", "_begin_build_load", "_apply_baseline_capture", "_settle_baseline_job",
        "_submit_evaluation_request", "_begin_eval_feedback", "_on_worker_finished", "_deliver_evaluation_result",
        "_maybe_schedule_upgrade_path", "_maybe_schedule_build_decomp", "_maybe_schedule_market_evidence",
        "_apply_optional_presentation_enrichment", "_store_evaluation_cache", "_item_check_build_context",
        "_item_check_build_freshness", "_persist_ready_build_cache", "_persist_build_settings",
        "_begin_reload_transaction", "_wait_for_pob_idle", "_disk_revision_changed", "_refresh_loadout_catalog",
        "_apply_loadout_selection", "_configure_worker",
    ):
        wrap(rec, C, name, f"ctrl.{name}")
    wrap(rec, controller_module._EvaluationWorker, "run_evaluation", "worker.run_evaluation")
    for name in ("run_build_decomp", "run_upgrade_path", "run_analysis", "run_baseline_load"):
        wrap(rec, controller_module._EvaluationWorker, name, f"worker.{name}")
    for name in ("show_analyzing", "show_result", "_resolve_presentation", "_render_presentation",
                 "_position_and_show", "_apply_layout_refresh", "_run_layout_refresh", "paintEvent", "show_warming"):
        wrap(rec, OverlayWindow, name, f"overlay.{name}")
    wrap(rec, ExileLensApp, "_on_eval_finished", "app._on_eval_finished")
    wrap(rec, Engine, "load_build", "engine.load_build")
    import exilelens.tree.mutations as tree_mutations

    wrap(rec, tree_mutations, "load_tree_snapshot", "tree.load_tree_snapshot")
    import exilelens.app.controller as cm

    if hasattr(cm, "load_tree_snapshot"):
        pass

    if args.no_prewarm and hasattr(C, "_schedule_prewarm"):
        C._schedule_prewarm = lambda self: None  # type: ignore[method-assign]
    monitor = StallMonitor(rec, threshold_ms=args.stall_ms)
    monitor.start()
    out: dict[str, Any] = {"qpa": os.environ.get("QT_QPA_PLATFORM", "windows"), "builds": {}, "boot": {}}

    # engine boot (off the UI thread already)
    rec.phase = "engine_boot"
    t_boot = rec.now()
    controller.start_engine_async()
    assert _pump(app, lambda: controller.engine_status() == "ready" or bool(controller.engine_error), 120), "engine boot"
    out["boot"]["engine_boot_ms"] = round(rec.now() - t_boot, 1)
    assert controller.engine is not None, controller.engine_error
    pob_calls = _instrument_engine_calls(rec, controller.engine)

    events: dict[str, Any] = {"finished": {}, "errors": {}}
    controller.evaluation_finished.connect(lambda rid, res: events["finished"].__setitem__(rid, rec.now()))
    controller.evaluation_error.connect(lambda rid, msg: events["errors"].__setitem__(rid, (rec.now(), msg)))

    seq = [100]
    anchor = (900, 500)

    def check_item(text: str, label: str, *, expect_cache: bool = False) -> dict[str, Any]:
        seq[0] += 1
        span_mark = len(rec.spans)
        calls_before = {k: len(v) for k, v in pob_calls.items()}
        rec.phase = f"item_check:{label}"
        t_submit = rec.now()
        rid = controller.submit_clipboard_text(text, copy_anchor_screen_px=anchor, clipboard_sequence=seq[0])
        t_returned = rec.now()
        done = _pump(app, lambda: rid in events["finished"] or rid in events["errors"], 90)
        t_done = events["finished"].get(rid) or (events["errors"].get(rid) or (rec.now(),))[0]
        _drain(app, 120)  # deferred layout refresh, queued paints, post-paint scheduling
        rec.phase = "idle"
        spans = rec.spans[span_mark:]

        def dur(lbl: str) -> float:
            return round(sum(s["dur"] for s in spans if s["label"] == lbl), 2)

        def first_start(lbl: str) -> float | None:
            hits = [s["start"] for s in spans if s["label"] == lbl]
            return min(hits) if hits else None

        analyzing_at = first_start("overlay.show_analyzing")
        result_at = first_start("overlay.show_result")
        worker_spans = [s for s in spans if s["label"] == "worker.run_evaluation"]
        paints = [s for s in spans if s["label"] == "overlay.paintEvent"]
        calls_after = {k: len(v) for k, v in pob_calls.items()}
        new_calls = {k: calls_after.get(k, 0) - calls_before.get(k, 0) for k in calls_after if calls_after.get(k, 0) != calls_before.get(k, 0)}
        row = {
            "label": label,
            "ok": bool(done) and rid in events["finished"],
            "error": (events["errors"].get(rid) or (None, ""))[1] if rid in events["errors"] else "",
            "cache_hit": None,
            "submit_ui_ms": round(t_returned - t_submit, 2),
            "submit_to_first_paint_ms": round(analyzing_at - t_submit, 2) if analyzing_at is not None else None,
            "ensure_offense_coverage_ms": dur("ctrl._ensure_offense_coverage"),
            "disk_revision_ms": dur("ctrl._disk_revision_changed"),
            "worker_compute_ms": round(worker_spans[0]["dur"], 2) if worker_spans else 0.0,
            "worker_start_after_submit_ms": round(worker_spans[0]["start"] - t_submit, 2) if worker_spans else None,
            "submit_to_result_signal_ms": round(t_done - t_submit, 2),
            "deliver_ms": dur("ctrl._deliver_evaluation_result"),
            "show_result_ms": dur("overlay.show_result"),
            "resolve_presentation_ms": dur("overlay._resolve_presentation"),
            "render_presentation_ms": dur("overlay._render_presentation"),
            "position_and_show_ms": dur("overlay._position_and_show"),
            "layout_refresh_calls": sum(1 for s in spans if s["label"] in {"overlay._apply_layout_refresh"}),
            "layout_refresh_ms": dur("overlay._apply_layout_refresh"),
            "paint_ms_total": round(sum(p["dur"] for p in paints), 2),
            "paint_count": len(paints),
            "post_schedule_ms": round(
                dur("ctrl._maybe_schedule_upgrade_path") + dur("ctrl._maybe_schedule_build_decomp")
                + dur("ctrl._maybe_schedule_market_evidence"), 2),
            "enrichment_ms": dur("ctrl._apply_optional_presentation_enrichment"),
            "on_worker_finished_ms": dur("ctrl._on_worker_finished"),
            "pob_calls": new_calls,
            "result_ui_after_signal_ms": round(max((p["start"] + p["dur"] for p in paints), default=t_done) - t_done, 2),
            "submit_to_result_visible_ms": round(
                (min((p["start"] + p["dur"] for p in paints if result_at is not None and p["start"] >= result_at), default=0.0)) - t_submit, 2
            ) if result_at is not None else None,
        }
        res = controller.last_result or {}
        meta = res.get("request_meta") or {}
        row["cache_hit"] = bool(meta.get("cache_hit"))
        row["worker_timeline"] = [
            {"label": s["label"], "t": round(s["start"] - t_submit, 1), "dur": s["dur"]}
            for s in spans
            if s["label"].startswith(("worker.", "pob:"))
        ]
        rec_ = (res.get("slot_comparisons") or [{}])[0].get("evaluation_outcome", {}) if res else {}
        row["quality"] = rec_.get("evaluation_quality")
        row["verdict"] = ((res.get("recommendation") or {}).get("verdict") or (res.get("decision") or {}).get("verdict"))
        row["pipeline_timings"] = res.get("timings") if isinstance(res.get("timings"), dict) else None
        return row

    previous: str | None = None
    for index, build in enumerate(builds):
        path = str(_build_path(build))
        slot = CANDIDATE_SLOT.get(build, "Ring 1")
        text = _candidate_text(Path(path), slot)
        entry: dict[str, Any] = {"build": build, "slot": slot}
        span_mark = len(rec.spans)
        stall_mark = len(monitor.stalls)
        rec.phase = f"load:{build}"
        t_load = rec.now()
        if previous is None:
            # The shipped startup path; falls back to the blocking load on a tree without the async API.
            loader = getattr(controller, "load_build_async", controller.load_build)
            loader(path, context=controller.settings.context)
        else:
            controller.change_build(path)
        t_returned = rec.now()
        entry["load_call_ui_ms"] = round(t_returned - t_load, 1)
        ok_ready = _pump(app, lambda: controller.build_info.state in {BuildState.READY, BuildState.FAILED}, 180)
        entry["load_to_ready_ms"] = round(rec.now() - t_load, 1)
        entry["ready"] = bool(ok_ready and controller.build_info.state is BuildState.READY)
        _drain(app, args.settle_ms)
        rec.phase = "idle"
        load_spans = rec.spans[span_mark:]
        entry["load_spans"] = {
            lbl: round(sum(s["dur"] for s in load_spans if s["label"] == lbl), 1)
            for lbl in sorted({s["label"] for s in load_spans})
            if sum(s["dur"] for s in load_spans if s["label"] == lbl) >= 1.0
        }
        entry["load_stalls"] = [s for s in monitor.stalls[stall_mark:]]
        entry["load_stall_max_ms"] = max((s["gap_ms"] for s in entry["load_stalls"]), default=0.0)
        previous = build
        if not entry["ready"]:
            entry["error"] = controller.build_info.error_message
            out["builds"][build] = entry
            continue
        # Item Check: first after load, then warm repeats (distinct clipboard sequence each time; the 2nd identical
        # content is a result-cache hit, so a cache-hit run is recorded explicitly and excluded from "warm").
        checks: list[dict[str, Any]] = []
        stall_mark = len(monitor.stalls)
        checks.append(check_item(text, "first"))
        for run in range(args.runs):
            controller._result_cache.invalidate()  # warm compute, not a cache hit (cache is measured separately)
            if args.gap_ms > 0:
                _drain(app, args.gap_ms)  # user think time between checks (background work may still be running)
            checks.append(check_item(text, f"warm{run}"))
        checks.append(check_item(text, "cache_hit"))
        entry["item_checks"] = checks
        entry["item_check_stalls"] = monitor.stalls[stall_mark:]
        out["builds"][build] = entry
        print(f"{build}: load={entry['load_to_ready_ms']}ms stall={entry['load_stall_max_ms']}ms "
              f"first={checks[0]['submit_to_result_signal_ms']}ms warm_med="
              f"{statistics.median(c['submit_to_result_signal_ms'] for c in checks[1:-1]):.0f}ms", flush=True)

    monitor.stop()
    out["stall_summary"] = monitor.summary()
    out["pob_call_totals"] = {k: {"n": len(v), "sum_ms": round(sum(v), 1)} for k, v in pob_calls.items()}
    try:
        shell.shutdown()
    except Exception:  # noqa: BLE001
        pass
    return out


def cmd_session(args: argparse.Namespace) -> int:
    all_runs = []
    for pass_index in range(args.passes):
        data = run_session(args)
        all_runs.append(data)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": "session", "passes": all_runs}, indent=1, default=str), encoding="utf-8")
    print("wrote", out)
    return 0


# --------------------------------------------------------------------------------------------------------------------
# report


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def cmd_report(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if data["mode"] == "startup":
        keys = ["app_constructed", "event_loop_first_task", "engine_ready", "build_ready", "finished"]
        print(f"startup build={data['build']} runs={len(data['runs'])}")
        for key in keys:
            vals = [next(m["t"] for m in r["marks"] if m["label"] == key) for r in data["runs"] if any(m["label"] == key for m in r["marks"])]
            print(f"  {key:32s} p50={_pct(vals,.5):8.0f}  p95={_pct(vals,.95):8.0f}  n={len(vals)}")
        mx = [r["stalls"].get("max_ms", 0) for r in data["runs"]]
        print(f"  {'UI stall max (ms)':32s} p50={_pct(mx,.5):8.0f}  p95={_pct(mx,.95):8.0f}")
        return 0
    for index, p in enumerate(data["passes"]):
        print(f"pass {index} qpa={p['qpa']} engine_boot={p['boot'].get('engine_boot_ms')}ms")
        for name, b in p["builds"].items():
            print(f"  {name}: load_ui={b.get('load_call_ui_ms')}ms ready={b.get('load_to_ready_ms')}ms max_stall={b.get('load_stall_max_ms')}ms")
            for lbl, ms in sorted((b.get("load_spans") or {}).items(), key=lambda kv: -kv[1])[:8]:
                print(f"      {lbl:42s} {ms:9.1f}ms")
            checks = b.get("item_checks") or []
            warm = [c for c in checks if c["label"].startswith("warm")]
            if checks:
                f = checks[0]
                print(f"    first: first_paint={f['submit_to_first_paint_ms']} coverage={f['ensure_offense_coverage_ms']} compute={f['worker_compute_ms']} "
                      f"result={f['submit_to_result_signal_ms']} show_result={f['show_result_ms']} layout={f['layout_refresh_ms']} paint={f['paint_ms_total']}")
            if warm:
                for k in ("submit_ui_ms", "submit_to_first_paint_ms", "worker_compute_ms", "submit_to_result_signal_ms",
                          "deliver_ms", "show_result_ms", "resolve_presentation_ms", "render_presentation_ms",
                          "position_and_show_ms", "layout_refresh_ms", "paint_ms_total", "post_schedule_ms", "enrichment_ms"):
                    vals = [c[k] for c in warm if c.get(k) is not None]
                    print(f"    warm {k:30s} p50={_pct(vals,.5):8.2f} p95={_pct(vals,.95):8.2f}")
            hit = next((c for c in checks if c["label"] == "cache_hit"), None)
            if hit:
                print(f"    cache_hit: result={hit['submit_to_result_signal_ms']}ms show_result={hit['show_result_ms']} cache={hit['cache_hit']}")
    return 0


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("startup")
    s.add_argument("--build", default="core04_player_ring")
    s.add_argument("--runs", type=int, default=5)
    s.add_argument("--stall-ms", type=float, default=40.0)
    s.add_argument("--qpa", default="")
    s.add_argument("--out", default="artifacts/perf01/startup.json")
    c = sub.add_parser("_startup_child")
    c.add_argument("--build", required=True)
    c.add_argument("--stall-ms", type=float, default=40.0)
    e = sub.add_parser("session")
    e.add_argument("--builds", default="core04_player_ring,core04_melee_weapon,corpus02e_spell_totem_titan")
    e.add_argument("--runs", type=int, default=8)
    e.add_argument("--passes", type=int, default=1)
    e.add_argument("--stall-ms", type=float, default=40.0)
    e.add_argument("--gap-ms", type=float, default=0.0, help="extra pause before each warm check (user think time)")
    e.add_argument("--settle-ms", type=float, default=80.0, help="pause between a build becoming ready and the first check")
    e.add_argument("--no-prewarm", action="store_true", help="disable the idle native-report prewarm (A/B)")
    e.add_argument("--qpa", default="")
    e.add_argument("--out", default="artifacts/perf01/session.json")
    r = sub.add_parser("report")
    r.add_argument("file")
    args = parser.parse_args()
    if args.cmd == "_startup_child":
        data = run_startup_once(args.build, args.stall_ms)
        sys.stdout.write("PERF01_JSON " + json.dumps(data, default=str) + "\n")
        sys.stdout.flush()
        os._exit(0)
    if args.cmd == "startup":
        return cmd_startup(args)
    if args.cmd == "session":
        return cmd_session(args)
    return cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
