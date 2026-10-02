"""R1.5 validation: one real-PoB pass over representative public-corpus builds.

Part A (product output): current focus, action plan, ladders, response curves, packages, health and coverage per build,
with the curve cost (cold and repeat) and the proof that the actionable layer itself makes no PoB call.
Part B (controlled before/after): equip a modified copy of an equipped item in the loaded build (PoB live equipment),
re-analyse, and record What Changed.
Part C (Item Check): warm checks without an analysis and with the cached R1.5 analysis; worker calls made by the context.

Output: artifacts/r1_5_validation.json (not tracked).
usage: r1_5_validation.py [--out PATH] [--skip-changes] [--skip-item-check] [build_id ...]
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

from exilelens.analysis.actionable import build_actionable, curve_text, diff_actionable  # noqa: E402
from exilelens.analysis.cache import ProbeCache  # noqa: E402
from exilelens.analysis.identity import AnalysisBaseline  # noqa: E402
from exilelens.analysis.pipeline import analyze_build, rescore_analysis  # noqa: E402
from exilelens.analysis.probes import clone_item_with_mods  # noqa: E402
from exilelens.config import PobConfig, detect_common_pob_installation  # noqa: E402
from exilelens.engine import Engine  # noqa: E402
from exilelens.items.build_context import build_item_context, compact_lines, intelligence_status, snapshot_intelligence  # noqa: E402
from exilelens.items.evaluation import evaluate_item  # noqa: E402

CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
SELECTED = {
    "corpus02h_eldritch_battery_shaman": "spell, Energy Shield, Kalandra's Touch carrier case",
    "core04_melee_weapon": "melee attack",
    "core04_bow_quiver": "bow / ranged, below-cap resistances",
    "corpus02g_strength_oracle_brutus": "crit, attribute-relevant (Strength)",
    "core04_poison_ailment": "ailment (poison), non-crit",
    "core04_minion_actor": "minion",
    "corpus02e_spell_totem_titan": "totem, Kalandra's Touch carrier case",
    "corpus02_giants_blood_shield": "Life, armour / shield",
    "recovery02a_es_regen_invoker": "Energy Shield",
    "life01_blood_mage_ember_fusillade": "Blood Mage, pinned resistances",
    "corpus02d2_voltaic_barrier": "Virtuous Barrier, non-damage main skill",
}
# build -> (slot, lines appended to that slot's equipped item, what the change is meant to do)
CHANGES = {
    "core04_bow_quiver": ("Ring 1", ["+60% to Chaos Resistance", "+15% to Lightning Resistance"], "fix both resistance deficits"),
    "corpus02g_strength_oracle_brutus": ("Ring 1", ["+30% to Lightning Resistance"], "fix the critical resistance, leave Chaos"),
    "corpus02h_eldritch_battery_shaman": ("Ring 2", ["+150 to maximum Energy Shield", "+3 to Level of all Spell Skills"], "add strong offensive and defensive stats"),
}
ITEM_CHECK_BUILD = "core04_bow_quiver"
ITEM = "Rarity: RARE\nWard Loop\nSapphire Ring\nLevelReq: 60\nImplicits: 1\n+25% to Cold Resistance\n+40% to Chaos Resistance\n+60 to maximum Energy Shield\n"
RUNS = 8


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


def _summary(result: dict) -> dict:
    actionable = result["actionable"]
    return {
        "focus": [actionable["current_focus"]["title"], actionable["current_focus"]["headline"], actionable["current_focus"]["detail"]],
        "actions": [f"{a['number']}. {a['title']} — {a['detail']}" for a in actionable["action_plan"]],
        "best": actionable["best_response"],
        "ladders": {key: [f"{row['position']}. {row['tested_change']} {row['response_percent']:+.1f}%" for row in rows] for key, rows in actionable["ladders"].items()},
        "curves": [f"{c['label']} ({c['axis_label']}): {c.get('tested_change')} {c.get('first_percent')} | next {curve_text(c)} | ratio {c.get('ratio')}"
                   for c in actionable["response_curves"]],
        "packages": {p["title"]: [f"{s['tested_change']} · {s['evidence']}" for s in p["stats"]] for p in actionable["stat_packages"]},
        "health": [f"{row['title']}: {row['state']} — {row['reason']}" for row in actionable["build_health"]],
        "breakpoints": [f"{row['title']}: {row['status']} — {row['text']}" for row in actionable["breakpoints"]],
        "coverage": actionable["coverage"],
    }


def _product(engine: Engine, counter: CallCounter, name: str, why: str) -> dict:
    path = str((CORPUS / f"{name}.xml").resolve())
    entry: dict = {"id": name, "selected_for": why}
    started = time.perf_counter()
    try:
        cache = ProbeCache()
        result = analyze_build(engine, build_path=path, slot_filter="__none__", cache=cache)
        curves = result.get("response_curves") or {}
        before = counter.total()
        rederived = build_actionable(result)
        pure_calls = counter.total() - before
        repeat = analyze_build(engine, build_path=path, slot_filter="__none__", cache=cache)
        before = counter.total()
        rescored = rescore_analysis({**result, "slots": []}, "MAPPING")
        entry.update(
            ok=True,
            seconds=round(time.perf_counter() - started, 1),
            pob_recalcs_cold=result["performance"]["pob_recalcs"],
            curve_recalcs_cold=curves.get("new_recalcs"),
            pob_recalcs_repeat=repeat["performance"]["pob_recalcs"],
            curve_recalcs_repeat=(repeat.get("response_curves") or {}).get("new_recalcs"),
            actionable_pob_calls=pure_calls,
            actionable_stable={k: v for k, v in rederived.items() if k != "changes"} == {k: v for k, v in result["actionable"].items() if k != "changes"},
            rescore_pob_calls=counter.total() - before,
            profile_identical={k: v for k, v in rescored["actionable"].items()} == {k: v for k, v in result["actionable"].items()},
            **_summary(result),
        )
    except Exception as exc:  # noqa: BLE001 - recorded, not hidden
        entry.update(ok=False, error=f"{type(exc).__name__}: {exc}", seconds=round(time.perf_counter() - started, 1))
    return entry


def _controlled_change(engine: Engine, name: str, slot: str, lines: list[str], intent: str) -> dict:
    path = str((CORPUS / f"{name}.xml").resolve())
    before = analyze_build(engine, build_path=path, slot_filter="__none__")
    equipment = {row["slot"]: row for row in (engine.get_equipment().get("equipment") or []) if row.get("slot")}
    raw = str((equipment.get(slot) or {}).get("raw") or "")
    if not raw.strip():
        return {"id": name, "ok": False, "error": f"no item in {slot}"}
    engine.apply_live_equipment([{"slot": slot, "item_raw": clone_item_with_mods(raw, lines)}])
    after = analyze_build(engine, build_path=path, slot_filter="__none__", generation=1)
    changes = diff_actionable(before["actionable"], after["actionable"])
    other = analyze_build(engine, build_path=str((CORPUS / "core04_melee_weapon.xml").resolve()), slot_filter="__none__")
    return {
        "id": name, "ok": True, "intent": intent, "slot": slot, "added": lines,
        "fingerprint_changed": before["baseline"]["fingerprint"] != after["baseline"]["fingerprint"],
        "before_actions": [a["title"] for a in before["actionable"]["action_plan"]],
        "after_actions": [a["title"] for a in after["actionable"]["action_plan"]],
        "before_focus": before["actionable"]["current_focus"]["headline"],
        "after_focus": after["actionable"]["current_focus"]["headline"],
        "changes": [item["text"] for item in changes["items"]],
        "comparable": changes["comparable"],
        "other_build_comparable": diff_actionable(after["actionable"], other["actionable"])["comparable"],
    }


def _item_check(engine: Engine, counter: CallCounter) -> dict:
    path = str((CORPUS / f"{ITEM_CHECK_BUILD}.xml").resolve())
    engine.invalidate_build()
    engine.ensure_build_ready(path, context="MAP")
    for _ in range(2):
        evaluate_item(ITEM, engine, build_path=path, context="MAP")

    def check(snapshot, baseline):
        started = time.perf_counter()
        result = evaluate_item(ITEM, engine, build_path=path, context="MAP")
        eval_ms = (time.perf_counter() - started) * 1000
        fingerprint = result["recommendation"]["baseline"]["fingerprint_hash"]
        current = AnalysisBaseline(**{**(baseline or {"build_path": path, "build_name": "", "loadout": "", "item_set": "", "context": "MAP",
                                                       "profile": "BALANCED", "generation": 0}), "fingerprint": fingerprint})
        before = counter.total()
        started = time.perf_counter()
        status = intelligence_status(snapshot, current)
        context = build_item_context(result, snapshot, status=status)
        outcome = result["recommendation"]["evaluation_outcome"]
        return {"eval_ms": eval_ms, "context_ms": (time.perf_counter() - started) * 1000, "context_calls": counter.total() - before, "status": status,
                "verdict": outcome.get("verdict"), "score": outcome.get("final_score"),
                "lines": [line["text"] for line in compact_lines(context, str(result["recommendation"]["pob_slot"]))]}

    no_analysis = [check(None, None) for _ in range(RUNS)]
    before_calls = counter.calls.copy()
    analysis = analyze_build(engine, build_path=path)
    analysis_calls = counter.calls - before_calls
    snapshot = snapshot_intelligence(analysis)
    before_calls = counter.calls.copy()
    cached = [check(snapshot, analysis["baseline"]) for _ in range(RUNS)]
    stale = check(snapshot, {**analysis["baseline"], "generation": analysis["baseline"]["generation"] + 1})
    during = counter.calls - before_calls
    return {
        "build": ITEM_CHECK_BUILD,
        "analyze_build": {"pob_recalcs": analysis["performance"]["pob_recalcs"], "curve_recalcs": analysis["response_curves"]["new_recalcs"],
                          "worker_calls": sum(analysis_calls.values())},
        "no_analysis": {"median_eval_ms": round(statistics.median(r["eval_ms"] for r in no_analysis), 1), "status": no_analysis[-1]["status"],
                        "context_calls": sum(r["context_calls"] for r in no_analysis), "lines": no_analysis[-1]["lines"],
                        "verdict": no_analysis[-1]["verdict"], "score": no_analysis[-1]["score"]},
        "cached": {"median_eval_ms": round(statistics.median(r["eval_ms"] for r in cached), 1), "status": cached[-1]["status"],
                   "context_calls": sum(r["context_calls"] for r in cached), "context_ms": round(statistics.median(r["context_ms"] for r in cached), 3),
                   "lines": cached[-1]["lines"], "verdict": cached[-1]["verdict"], "score": cached[-1]["score"]},
        "stale": {"status": stale["status"], "lines": stale["lines"]},
        "worker_methods_during_cached_checks": dict(during),
    }


def main() -> None:
    args = sys.argv[1:]
    out_path = ROOT / "artifacts" / "r1_5_validation.json"
    if args[:1] == ["--out"]:
        out_path, args = ROOT / args[1], args[2:]
    names = [a for a in args if not a.startswith("--")] or list(SELECTED)
    out: dict = {"builds": [], "changes": [], "item_check": {}}
    with Engine(PobConfig(detect_common_pob_installation()), use_subprocess=True) as engine:
        counter = CallCounter(engine)
        for name in names:
            entry = _product(engine, counter, name, SELECTED.get(name, ""))
            out["builds"].append(entry)
            print(name, entry.get("ok"), entry.get("pob_recalcs_cold"), entry.get("curve_recalcs_cold"), entry.get("pob_recalcs_repeat"),
                  (entry.get("focus") or ["", ""])[1], entry.get("error", ""), flush=True)
        if "--skip-changes" not in args:
            for name, (slot, lines, intent) in CHANGES.items():
                engine.invalidate_build()
                change = _controlled_change(engine, name, slot, lines, intent)
                out["changes"].append(change)
                print("change", name, change.get("ok"), change.get("changes"), flush=True)
        if "--skip-item-check" not in args:
            out["item_check"] = _item_check(engine, counter)
            print("item check", out["item_check"]["no_analysis"]["median_eval_ms"], out["item_check"]["cached"]["median_eval_ms"],
                  out["item_check"]["cached"]["context_calls"], out["item_check"]["cached"]["lines"], flush=True)
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("wrote", out_path)


if __name__ == "__main__":
    main()
