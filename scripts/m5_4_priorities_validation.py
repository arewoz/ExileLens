"""M5.4 harness: run the existing analyze_build() once per selected public-corpus build and dump the raw results.

Reuses fixtures/builds/public_corpus (+ manifest.json), Engine, analyze_build and rescore_analysis. Slots are skipped
(slot_filter matches nothing) because Build Priorities derive only from the global probe stage. Diagnosis only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exilelens.analysis.pipeline import analyze_build, rescore_analysis  # noqa: E402
from exilelens.config import PobConfig, detect_common_pob_installation  # noqa: E402
from exilelens.engine import Engine  # noqa: E402

CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
SELECTED = [
    "core04_bow_quiver", "core04_melee_weapon", "core04_minion_actor", "core04_mixed_hit_ailment", "core04_poison_ailment",
    "core04_skill_native_dot", "core04_stage_context", "corpus02_giants_blood_shield", "corpus02b_varashta_djinn",
    "corpus02c_stonefist_martial_artist", "corpus02d2_voltaic_barrier", "corpus02e_spell_totem_titan",
    "corpus02f_ballista_warbringer", "corpus02g_dex_int_acolyte_hand_of_wisdom", "corpus02g_strength_oracle_brutus",
    "corpus02h_eldritch_battery_shaman", "life01_blood_mage_ember_fusillade", "recovery02a_es_regen_invoker",
]
PROFILE_CHECK = {"core04_bow_quiver", "corpus02g_dex_int_acolyte_hand_of_wisdom", "life01_blood_mage_ember_fusillade", "core04_minion_actor"}


def main() -> None:
    # usage: m5_4_priorities_validation.py [--out PATH] [build_id ...]
    args = sys.argv[1:]
    out_path = ROOT / "artifacts" / "m5_4_priorities_validation.json"
    if args[:1] == ["--out"]:
        out_path, args = ROOT / args[1], args[2:]
    selected = args or SELECTED
    manifest = {Path(f["file"]).stem: f for f in json.loads((CORPUS / "manifest.json").read_text())["fixtures"]}
    pob = detect_common_pob_installation()
    out = {"builds": []}
    with Engine(PobConfig(pob), use_subprocess=True) as engine:
        for name in selected:
            started = time.perf_counter()
            entry = {"id": name, "manifest": manifest.get(name, {})}
            try:
                result = analyze_build(engine, build_path=str((CORPUS / f"{name}.xml").resolve()), slot_filter="__none__")
                entry.update(
                    ok=True,
                    seconds=round(time.perf_counter() - started, 1),
                    pob_recalcs=result["performance"]["pob_recalcs"],
                    audit={k: result["audit"].get(k) for k in ("primary_field", "primary_confidence", "defense", "offense", "utility")},
                    resistances={k: {"current": v.get("current"), "cap": v.get("cap"), "missing": v.get("missing"), "state": v.get("state")} for k, v in (result["audit"].get("resistances") or {}).items()},
                    needs=result["needs"],
                    fingerprint=result["build_fingerprint"],
                    probe_statuses={p.get("probe_id"): p.get("status") for p in result["global_probes"] if not p.get("nonlinear_sample") and not p.get("breakpoint_exact") and p.get("status") != "curve"},
                    priorities=result["build_priorities"],
                    sensitivity=[{k: s.get(k) for k in ("probe_id", "label", "status", "applied", "own_resistance_delta", "confidence", "probe", "response", "breakpoints")} for s in result["build_sensitivity"]["signals"]],
                )
                if name in PROFILE_CHECK:
                    entry["profile_identical"] = rescore_analysis(result, "MAPPING")["build_priorities"] == result["build_priorities"]
            except Exception as exc:  # noqa: BLE001 - recorded as a technical failure, not hidden
                entry.update(ok=False, error=f"{type(exc).__name__}: {exc}", seconds=round(time.perf_counter() - started, 1))
            out["builds"].append(entry)
            print(name, entry.get("ok"), entry.get("seconds"), entry.get("pob_recalcs"), flush=True)
    target = out_path
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("wrote", target)


if __name__ == "__main__":
    main()
