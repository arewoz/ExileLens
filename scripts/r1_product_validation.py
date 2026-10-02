"""R1 product validation: one real-PoB pass over representative public-corpus builds.

Part A (product output): run the existing analyze_build() once per build and record what a player would read --
strongest measured responses, FIX FIRST, lanes, coverage wording -- plus the proof that deriving them costs no PoB call.
Part B (Item Check journeys): warm Item Check without a prior analysis (journey A) and with a cached one (journey B),
the explanation context each produces, its cost, and the PoB calls it makes (expected: none).

Not a measurement re-validation (that is M5.4/M5.5). Output: artifacts/r1_product_validation.json (not tracked).
usage: r1_product_validation.py [--out PATH] [--skip-journeys] [build_id ...]
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

from exilelens.analysis.cache import ProbeCache  # noqa: E402
from exilelens.analysis.identity import AnalysisBaseline  # noqa: E402
from exilelens.analysis.pipeline import analyze_build, rescore_analysis  # noqa: E402
from exilelens.analysis.strongest import entry_keys, format_entry, strongest_responses  # noqa: E402
from exilelens.analysis.view import build_analysis_view  # noqa: E402
from exilelens.config import PobConfig, detect_common_pob_installation  # noqa: E402
from exilelens.engine import Engine  # noqa: E402
from exilelens.items.build_context import (  # noqa: E402
    build_item_context,
    compact_lines,
    detail_lines,
    intelligence_status,
    snapshot_intelligence,
)
from exilelens.items.evaluation import evaluate_item  # noqa: E402

CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
ITEMS = ROOT / "fixtures" / "items"

# id -> why it is in the representative set.
SELECTED = {
    "corpus02h_eldritch_battery_shaman": "spell, Energy Shield, Kalandra's Touch carrier case",
    "core04_melee_weapon": "melee attack",
    "core04_bow_quiver": "bow / ranged, below-cap resistance",
    "corpus02g_strength_oracle_brutus": "crit, attribute-sensitive (Strength)",
    "core04_poison_ailment": "ailment (poison)",
    "core04_minion_actor": "minion",
    "corpus02e_spell_totem_titan": "totem, Kalandra's Touch carrier case",
    "corpus02_giants_blood_shield": "Life, armour / shield",
    "recovery02a_es_regen_invoker": "Energy Shield, multi-impact",
    "corpus02g_dex_int_acolyte_hand_of_wisdom": "attribute-sensitive (Dex / Int)",
    "life01_blood_mage_ember_fusillade": "Blood Mage, pinned resistances",
    "corpus02d2_voltaic_barrier": "Virtuous Barrier, non-damage main skill",
}
PROFILE_CHECK = {"corpus02h_eldritch_battery_shaman", "core04_minion_actor", "corpus02g_strength_oracle_brutus"}
JOURNEY_BUILDS = ("corpus02h_eldritch_battery_shaman", "core04_bow_quiver", "corpus02g_strength_oracle_brutus")
JOURNEY_ITEMS = ("core04_offense_ring.txt", "core04_defense_ring.txt")
CASTER_RING = (
    "Rarity: RARE\nGale Band\nSapphire Ring\nLevelReq: 60\nImplicits: 1\n+25% to Cold Resistance\n"
    "+2 to Level of all Spell Skills\n24% increased Cast Speed\n+60 to maximum Life\n+20 to Intelligence\n"
)
RUNS = 10


class CallCounter:
    """Counts every request ExileLens sends to the PoB worker (the one RPC entry point)."""

    def __init__(self, engine: Engine) -> None:
        self.calls: Counter[str] = Counter()
        original = engine._call

        def counted(method, params=None):
            self.calls[method] += 1
            return original(method, params)

        engine._call = counted  # type: ignore[method-assign]

    def total(self) -> int:
        return sum(self.calls.values())


def _median_ms(samples: list[float]) -> float:
    return round(statistics.median(samples), 1)


def _product_output(engine: Engine, counter: CallCounter, name: str, why: str) -> dict:
    started = time.perf_counter()
    entry: dict = {"id": name, "selected_for": why}
    try:
        result = analyze_build(engine, build_path=str((CORPUS / f"{name}.xml").resolve()), slot_filter="__none__")
        before = counter.total()
        rederived = strongest_responses(result["build_priorities"])
        view = build_analysis_view(result)
        derived_calls = counter.total() - before
        strongest = result["strongest_responses"]
        entry.update(
            ok=True,
            seconds=round(time.perf_counter() - started, 1),
            pob_recalcs=result["performance"]["pob_recalcs"],
            main_skill=view["build"]["main_skill"],
            strongest={key: format_entry(strongest[key]) for key in entry_keys()},
            strongest_status={key: strongest[key]["status"] for key in entry_keys()},
            tied={key: strongest[key].get("tied_with") for key in entry_keys() if strongest[key].get("tied_with")},
            limited_confidence=bool(strongest["damage"].get("limited_confidence")),
            tiles=[f"{tile['caption']}: {tile['value']} | {tile['change']}" for tile in view["tiles"]],
            fix_first=[f"{row['title']} - {row['detail']} ({row['urgency']})" for row in view["fix_first"]],
            lanes={lane["title"]: [f"{row['change']} {row['response']} {row['also']}".strip() for row in lane["rows"]] for lane in view["lanes"]},
            coverage=view["coverage"],
            details=view["details"],
            derivation_pob_calls=derived_calls,
            derivation_stable=rederived == strongest,
        )
        if name in PROFILE_CHECK:
            entry["profile_identical"] = rescore_analysis(result, "MAPPING")["strongest_responses"] == strongest
    except Exception as exc:  # noqa: BLE001 - recorded, not hidden
        entry.update(ok=False, error=f"{type(exc).__name__}: {exc}", seconds=round(time.perf_counter() - started, 1))
    return entry


def _check(engine: Engine, counter: CallCounter, path: str, raw: str, snapshot, analysis_baseline: dict | None) -> dict:
    """One Item Check plus its explanation context; returns timings and what the context cost."""
    started = time.perf_counter()
    result = evaluate_item(raw, engine, build_path=path, context="MAP")
    eval_ms = (time.perf_counter() - started) * 1000
    fingerprint = str(((result.get("recommendation") or {}).get("baseline") or {}).get("fingerprint_hash") or "")
    current = AnalysisBaseline(**{**(analysis_baseline or {"build_path": path, "build_name": "", "loadout": "", "item_set": "",
                                                           "context": "MAP", "profile": "BALANCED", "generation": 0}), "fingerprint": fingerprint})
    before = counter.total()
    started = time.perf_counter()
    status = intelligence_status(snapshot, current)
    context = build_item_context(result, snapshot, status=status)
    context_ms = (time.perf_counter() - started) * 1000
    slot = str((result.get("recommendation") or {}).get("pob_slot") or "")
    outcome = (result.get("recommendation") or {}).get("evaluation_outcome") or {}
    return {
        "eval_ms": eval_ms, "context_ms": context_ms, "context_pob_calls": counter.total() - before, "status": status,
        "fingerprint": fingerprint, "slot": slot, "verdict": outcome.get("verdict"), "final_score": outcome.get("final_score"),
        "compact": [line["text"] for line in compact_lines(context, slot)], "detail": detail_lines(context, slot),
    }


def _journeys(engine: Engine, counter: CallCounter, name: str) -> dict:
    path = str((CORPUS / f"{name}.xml").resolve())
    items = {item: (ITEMS / item).read_text(encoding="utf-8") for item in JOURNEY_ITEMS}
    items["caster_ring"] = CASTER_RING
    out: dict = {"id": name, "items": {}}
    engine.ensure_build_ready(path, context="MAP")
    for raw in items.values():  # warm PoB and the item caches
        evaluate_item(raw, engine, build_path=path, context="MAP")

    journey_a = {item: [_check(engine, counter, path, raw, None, None) for _ in range(RUNS)] for item, raw in items.items()}

    cache = ProbeCache()
    before, started = counter.total(), time.perf_counter()
    analysis = analyze_build(engine, build_path=path, cache=cache)
    out["analyze_build"] = {"seconds": round(time.perf_counter() - started, 1), "pob_recalcs": analysis["performance"]["pob_recalcs"],
                            "worker_calls": counter.total() - before}
    snapshot = snapshot_intelligence(analysis)

    before = counter.calls.copy()
    journey_b = {item: [_check(engine, counter, path, raw, snapshot, analysis["baseline"]) for _ in range(RUNS)] for item, raw in items.items()}
    during_b = counter.calls - before

    started = time.perf_counter()
    repeat = analyze_build(engine, build_path=path, cache=cache)
    out["analyze_build_repeat"] = {"seconds": round(time.perf_counter() - started, 1), "pob_recalcs": repeat["performance"]["pob_recalcs"],
                                   "cache": repeat["performance"]["cache"],
                                   "same_strongest": repeat["strongest_responses"] == analysis["strongest_responses"]}
    out["analysis_fingerprint"] = analysis["baseline"]["fingerprint"]
    out["journey_b_worker_methods"] = dict(during_b)
    for item in items:
        a, b = journey_a[item], journey_b[item]
        out["items"][item] = {
            "journey_a": {"median_eval_ms": _median_ms([r["eval_ms"] for r in a]), "status": a[-1]["status"], "verdict": a[-1]["verdict"],
                          "final_score": a[-1]["final_score"], "context_ms": round(statistics.median(r["context_ms"] for r in a), 3),
                          "context_pob_calls": sum(r["context_pob_calls"] for r in a), "compact": a[-1]["compact"], "detail": a[-1]["detail"]},
            "journey_b": {"median_eval_ms": _median_ms([r["eval_ms"] for r in b]), "status": b[-1]["status"], "verdict": b[-1]["verdict"],
                          "final_score": b[-1]["final_score"], "context_ms": round(statistics.median(r["context_ms"] for r in b), 3),
                          "context_pob_calls": sum(r["context_pob_calls"] for r in b), "compact": b[-1]["compact"], "detail": b[-1]["detail"]},
            "fingerprint_matches_analysis": b[-1]["fingerprint"] == analysis["baseline"]["fingerprint"],
            "verdict_and_score_unchanged": (a[-1]["verdict"], a[-1]["final_score"]) == (b[-1]["verdict"], b[-1]["final_score"]),
        }
    return out


def main() -> None:
    args = sys.argv[1:]
    out_path = ROOT / "artifacts" / "r1_product_validation.json"
    if args[:1] == ["--out"]:
        out_path, args = ROOT / args[1], args[2:]
    skip_journeys = "--skip-journeys" in args
    names = [arg for arg in args if not arg.startswith("--")] or list(SELECTED)
    out: dict = {"builds": [], "journeys": []}
    with Engine(PobConfig(detect_common_pob_installation()), use_subprocess=True) as engine:
        counter = CallCounter(engine)
        for name in names:
            entry = _product_output(engine, counter, name, SELECTED.get(name, ""))
            out["builds"].append(entry)
            print(name, entry.get("ok"), entry.get("seconds"), entry.get("pob_recalcs"), entry.get("strongest", {}).get("damage"), flush=True)
        if not skip_journeys:
            for name in JOURNEY_BUILDS:
                journey = _journeys(engine, counter, name)
                out["journeys"].append(journey)
                for item, row in journey["items"].items():
                    print(name, item, "A", row["journey_a"]["median_eval_ms"], "B", row["journey_b"]["median_eval_ms"],
                          row["journey_b"]["status"], row["journey_b"]["context_pob_calls"], flush=True)
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("wrote", out_path)


if __name__ == "__main__":
    main()
