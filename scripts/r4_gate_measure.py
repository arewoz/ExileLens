"""R4 1.0 reliability gate: Build Intelligence coverage + performance baseline over the public corpus (real PoB).

Part A (per manifest build): one cold `analyze_build` (global stage only), then the Build Intelligence evidence the gate
cares about: Fix First, strongest offensive / defensive response, multi-impact, insufficient-evidence states, lane
coverage, restore (engine fingerprint unchanged), purity (rescore is identical and makes no PoB call), staleness, and the
standing measurement rule (no per-point / normalised value anywhere in the output). Cold and same-cache repeat time and
PoB recalculation counts are recorded for every build.
Part B (cache correctness, two builds): equip a modified item in the live build, re-analyse with the SAME cache, then
reload the original and confirm the original analysis is reproduced.
Part C (Shift+C Item Check latency, three builds): first check after load, then warm checks; worker calls by method.

Nothing is optimised here and nothing is added to the product: the numbers are the baseline later R5/R6 work is checked
against. Timings are machine-dependent; run nothing else concurrently.

Output: artifacts/r4_gate_measure.json (untracked).  usage: r4_gate_measure.py [--out PATH] [--skip-itemcheck] [build_id ...]   (exit 1 when the Build Intelligence gate blocks)
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from exilelens.analysis.cache import ProbeCache  # noqa: E402
from exilelens.analysis.identity import AnalysisBaseline  # noqa: E402
from exilelens.analysis.pipeline import analyze_build, rescore_analysis  # noqa: E402
from exilelens.analysis.priorities import is_priorities_stale  # noqa: E402
from exilelens.analysis.probes import clone_item_with_mods  # noqa: E402
from exilelens.config import PobConfig, detect_common_pob_installation, detect_pob_identity  # noqa: E402
from exilelens.engine import Engine  # noqa: E402
from exilelens.items.evaluation import evaluate_item  # noqa: E402
from tests.corpus_coverage.gate import evaluate_build_intel_gate, render_gate  # noqa: E402

CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
FIXTURE_DIRS = (CORPUS, ROOT / "fixtures" / "builds")
LANES = ("offense", "ehp", "max_hit", "mobility")
# The measurement rule: tested increments differ, so no per-point / normalised / cross-increment value may exist.
FORBIDDEN_KEYS = ("per_point", "per_unit", "marginal_value", "normalized", "normalised", "score_delta", "value_per", "weight")
CACHE_CHECK = {  # build -> (slot, lines appended to that slot's equipped item)
    "core04_bow_quiver": ("Ring 1", ["+60% to Chaos Resistance", "+15% to Lightning Resistance"]),
    "corpus02g_strength_oracle_brutus": ("Ring 1", ["+30% to Lightning Resistance"]),
}
ITEM_CHECK_BUILDS = {  # build -> equipped slot cloned with +100 maximum Life as the Item Check candidate
    "core04_player_ring": "Ring 1",
    "core04_melee_weapon": "Amulet",
    "corpus02e_spell_totem_titan": "Amulet",
}
WARM_RUNS = 8


class CallCounter:
    def __init__(self, engine: Engine) -> None:
        self.calls: Counter[str] = Counter()
        original = engine._call

        def counted(method, params=None):
            self.calls[method] += 1
            return original(method, params)

        engine._call = counted  # type: ignore[method-assign]

    def total(self) -> int:
        return sum(self.calls.values())


def _walk_keys(value, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            lowered = str(key).lower()
            if any(bad in lowered for bad in FORBIDDEN_KEYS):
                found.add(str(key))
            _walk_keys(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _walk_keys(inner, found)


def _lane_order_ok(rows: list[dict]) -> bool:
    values = [float(row.get("response_percent") or 0) for row in rows]
    return values == sorted(values, reverse=True) and all(row.get("tested_change") for row in rows) and all(abs(v) > 0.05 for v in values)


def _fix_first_text(rows: list[dict]) -> list[str]:
    return [str(row.get("title") or row.get("label") or row.get("headline") or row)[:80] for row in rows]


def _build_entry(engine: Engine, counter: CallCounter, name: str) -> dict:
    path = str((CORPUS / f"{name}.xml").resolve())
    entry: dict = {"id": name}
    try:
        engine.invalidate_build()
        cache = ProbeCache()
        started = time.perf_counter()
        calls_before = counter.total()
        cold = analyze_build(engine, build_path=path, slot_filter="__none__", cache=cache)
        cold_s = time.perf_counter() - started
        worker_calls_cold = counter.total() - calls_before
        fingerprint_after = engine.get_metrics()["fingerprint_hash"]

        started = time.perf_counter()
        repeat = analyze_build(engine, build_path=path, slot_filter="__none__", cache=cache)
        repeat_s = time.perf_counter() - started

        priorities = cold["build_priorities"]
        strongest = cold.get("strongest_responses") or {}
        before_calls = counter.total()
        rescored = rescore_analysis({**cold, "slots": []}, "MAPPING")
        rescore_calls = counter.total() - before_calls
        baseline = cold["baseline"]
        same = AnalysisBaseline(**{k: baseline[k] for k in AnalysisBaseline.__dataclass_fields__})
        newer = AnalysisBaseline(**{**same.to_dict(), "generation": same.generation + 1})
        forbidden: set[str] = set()
        _walk_keys(priorities, forbidden)
        _walk_keys(strongest, forbidden)
        lane_rows = {lane: list(priorities.get(lane) or []) for lane in LANES}
        entry.update(
            ok=True,
            cold_s=round(cold_s, 2), repeat_s=round(repeat_s, 2),
            pob_recalcs_cold=cold["performance"]["pob_recalcs"], pob_recalcs_repeat=repeat["performance"]["pob_recalcs"],
            worker_calls_cold=worker_calls_cold,
            fix_first=_fix_first_text(priorities.get("fix_first") or []),
            lanes={lane: [f"{r.get('label')}: {r.get('tested_change')} {float(r.get('response_percent') or 0):+.1f}%" for r in rows[:1]]
                   for lane, rows in lane_rows.items()},
            lane_row_counts={lane: len(rows) for lane, rows in lane_rows.items()},
            multi_axis=len(priorities.get("multi_axis") or []),
            strongest_status={key: (value or {}).get("status") for key, value in strongest.items() if isinstance(value, dict)},
            lanes_without_response=list((priorities.get("coverage") or {}).get("lanes_without_response") or []),
            not_established=list((priorities.get("coverage") or {}).get("not_established") or []),
            no_signal_count=len((priorities.get("coverage") or {}).get("no_signal") or []),
            offense_limited_confidence=bool(priorities.get("offense_limited_confidence")),
            invariants={
                "restore_fingerprint_unchanged": fingerprint_after == cold["baseline"]["fingerprint"],
                "lanes_sorted_and_labelled": all(_lane_order_ok(rows) for rows in lane_rows.values()),
                "rescore_priorities_identical": rescored["build_priorities"] == priorities,
                "rescore_made_no_pob_call": rescore_calls == 0,
                "not_stale_on_same_baseline": not is_priorities_stale(priorities, same),
                "stale_after_generation_change": is_priorities_stale(priorities, newer),
                "no_per_point_or_normalised_fields": not forbidden,
                "repeat_priorities_identical": repeat["build_priorities"] == priorities,
            },
            forbidden_keys=sorted(forbidden),
        )
    except Exception as exc:  # noqa: BLE001 - recorded as a gate failure, not hidden
        entry.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    return entry


def _cache_check(engine: Engine, name: str, slot: str, lines: list[str]) -> dict:
    path = str((CORPUS / f"{name}.xml").resolve())
    try:
        engine.invalidate_build()
        cache = ProbeCache()
        original = analyze_build(engine, build_path=path, slot_filter="__none__", cache=cache)
        equipment = {row["slot"]: row for row in (engine.get_equipment().get("equipment") or []) if row.get("slot")}
        raw = str((equipment.get(slot) or {}).get("raw") or "")
        engine.apply_live_equipment([{"slot": slot, "item_raw": clone_item_with_mods(raw, lines)}])
        changed = analyze_build(engine, build_path=path, slot_filter="__none__", cache=cache, generation=1)
        engine.invalidate_build()
        restored = analyze_build(engine, build_path=path, slot_filter="__none__", cache=cache)
        return {
            "id": name, "ok": True, "slot": slot,
            "fingerprint_changed_by_equip": original["baseline"]["fingerprint"] != changed["baseline"]["fingerprint"],
            "analysis_changed_by_equip": original["build_priorities"] != changed["build_priorities"],
            "changed_run_recalcs": changed["performance"]["pob_recalcs"],
            "fingerprint_restored_after_reload": original["baseline"]["fingerprint"] == restored["baseline"]["fingerprint"],
            "analysis_reproduced_after_reload": original["build_priorities"] == restored["build_priorities"],
            "reload_run_recalcs": restored["performance"]["pob_recalcs"],
            "original_run_recalcs": original["performance"]["pob_recalcs"],
        }
    except Exception as exc:  # noqa: BLE001
        return {"id": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _fixture(name: str) -> Path:
    return next(directory / f"{name}.xml" for directory in FIXTURE_DIRS if (directory / f"{name}.xml").is_file())


def _item_check(engine: Engine, counter: CallCounter, name: str, slot: str) -> dict:
    fixture = _fixture(name)
    path = str(fixture.resolve())
    from xml.etree import ElementTree

    root = ElementTree.parse(fixture).getroot()
    items = root.find("Items")
    raw = {i.get("id"): (i.text or "").strip() for i in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(e for e in items.findall("ItemSet") if e.get("id") == active)
    item_id = next(e.get("itemId") for e in item_set.findall("Slot") if e.get("name") == slot)
    candidate = raw[item_id] + "\n+100 to maximum Life\n"
    try:
        engine.invalidate_build()
        started = time.perf_counter()
        first = evaluate_item(candidate, engine, build_path=path, context="MAP")
        first_s = time.perf_counter() - started
        times, calls_one = [], None
        for index in range(WARM_RUNS):
            before = counter.calls.copy()
            started = time.perf_counter()
            result = evaluate_item(candidate, engine, build_path=path, context="MAP")
            times.append((time.perf_counter() - started) * 1000)
            if index == 0:
                calls_one = dict(counter.calls - before)
        times_sorted = sorted(times)
        return {
            "id": name, "ok": True, "slot": slot,
            "first_check_after_load_ms": round(first_s * 1000), "warm_median_ms": round(statistics.median(times)),
            "warm_p90_ms": round(times_sorted[min(len(times_sorted) - 1, int(0.9 * len(times_sorted)))]),
            "warm_min_ms": round(times_sorted[0]), "warm_max_ms": round(times_sorted[-1]),
            "candidate_frames": len(result["slot_comparisons"]), "worker_calls_per_warm_check": calls_one,
            "quality": result["slot_comparisons"][0]["evaluation_outcome"]["evaluation_quality"],
            "first_check_quality": first["slot_comparisons"][0]["evaluation_outcome"]["evaluation_quality"],
        }
    except Exception as exc:  # noqa: BLE001
        return {"id": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _save(out: dict, out_path: Path) -> None:
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")


def main() -> int:
    args = sys.argv[1:]
    out_path = ROOT / "artifacts" / "r4_gate_measure.json"
    if args[:1] == ["--out"]:
        out_path, args = ROOT / args[1], args[2:]
    skip_item_check = "--skip-itemcheck" in args
    names = [a for a in args if not a.startswith("--")]
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["fixtures"]
    names = names or [Path(f["file"]).stem for f in manifest]
    pob = detect_common_pob_installation()
    identity = detect_pob_identity(pob)
    out: dict = {"pob": {"version": identity.version, "layout": str(getattr(identity, "layout", ""))}, "builds": [], "cache": [], "item_check": []}
    with Engine(PobConfig(pob), use_subprocess=True) as engine:
        counter = CallCounter(engine)
        for name in names:
            entry = _build_entry(engine, counter, name)
            out["builds"].append(entry)
            print(name, entry.get("ok"), entry.get("cold_s"), entry.get("pob_recalcs_cold"), entry.get("repeat_s"), entry.get("pob_recalcs_repeat"),
                  entry.get("error", ""), flush=True)
            _save(out, out_path)  # partial results survive a later failure
        for name, (slot, lines) in CACHE_CHECK.items():
            check = _cache_check(engine, name, slot, lines)
            out["cache"].append(check)
            print("cache", check, flush=True)
        if not skip_item_check:
            for name, slot in ITEM_CHECK_BUILDS.items():
                check = _item_check(engine, counter, name, slot)
                out["item_check"].append(check)
                print("item check", check, flush=True)
    _save(out, out_path)
    print("wrote", out_path)
    gate = evaluate_build_intel_gate(out)
    print(render_gate(gate).replace("(coverage)", "(build intelligence)"))
    return 0 if gate.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
