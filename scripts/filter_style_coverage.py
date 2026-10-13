"""Themed-visibility coverage over the generated legal corpus.

    python scripts/filter_style_coverage.py [--out artifacts/filter_style_coverage] [--name coverage] [--legal 4000] [--workers 10]

For every profile x build mode x context (campaign AreaLevel 30, maps AreaLevel 82) every corpus item state is evaluated against the generated
rules; see exilelens.filters.style_coverage for the outcomes. Themes: styling coverage over representative states in all eight themes.
Exit code 1 when any visible item is left unstyled (or a known item is treated as unknown).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import os
sys.path.insert(0, os.environ.get("FILTER_SRC") or str(ROOT / "src"))   # FILTER_SRC: measure another source tree (the before state)

CONTEXTS = {"campaign": 30, "maps": 82}
REPRESENTATIVE_THEME = "Void Gold"


def _items(legal: int):
    from exilelens.filters import profile_report as pr
    return pr.corpus(legal=legal)


def _job(args):
    build_key, level, theme, legal, themes_only = args
    from exilelens.filters import profile_report as pr
    from exilelens.filters import style_coverage as sc
    from exilelens.filters.intel_generate import generate
    from exilelens.filters.profile_oracle import UNKNOWN_ROW, classify
    needs = pr.load_builds(ROOT)[build_key]
    result = generate(needs, level, theme, intel=True)
    items = _items(legal)
    out = {}
    for context, area in CONTEXTS.items():
        scoped = [replace(i, area_level=area) for i in items]
        known = [classify(i, level).rows not in ((), (UNKNOWN_ROW,)) for i in scoped]
        verdicts = sc.evaluate(result.rules, scoped, known)
        summary = sc.summarise(scoped, verdicts)
        summary["visible_decisions"] = {}
        out[context] = summary
        if themes_only:
            out[context] = {"unstyled_visible_fallthrough": summary["unstyled_visible_fallthrough"],
                            "known_in_unknown_safety": summary["known_in_unknown_safety"],
                            "visibility": [("H" if v.outcome == sc.EXPLICIT_HIDE else "V") for v in verdicts]}
    return build_key, level, theme, out, len(result.rules), result.valid


def _rare_job(args):
    """Dedicated Rare-equipment audit: every ground equipment base x item level {70, 82} x unidentified tier {0, 1, 2, 3, 5}."""
    build_key, level = args
    from exilelens.filters import profile_report as pr
    from exilelens.filters import style_coverage as sc
    from exilelens.filters.intel_generate import generate
    from exilelens.filters.opportunity import ROLE_BY_CLASS
    from exilelens.filters.preview import PreviewItem
    from exilelens.filters.verified_bases import load_base_properties, native_class
    result = generate(pr.load_builds(ROOT)[build_key], level, REPRESENTATIVE_THEME, intel=True)
    bases = [(b, native_class(b)) for b in sorted(load_base_properties()) if native_class(b) in ROLE_BY_CLASS]
    out = {}
    for context, area in CONTEXTS.items():
        items = [PreviewItem(f"{b} audit", "rare audit", cls, b, "Rare", item_level=max(ilvl, int(load_base_properties()[b]["required_level"])),
                             area_level=area, unidentified_item_tier=unid)
                 for b, cls in bases for ilvl in (70, 82) for unid in (0, 1, 2, 3, 5)]
        verdicts = sc.evaluate(result.rules, items, [True] * len(items))
        summary = sc.summarise(items, verdicts)
        out[context] = {"states": len(items), "outcomes": summary["outcomes"], "by_state": summary["by_state"],
                        "unstyled_visible_fallthrough": summary["unstyled_visible_fallthrough"],
                        "known_in_unknown_safety": summary["known_in_unknown_safety"]}
    return build_key, level, out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "filter_style_coverage"))
    parser.add_argument("--name", default="coverage")
    parser.add_argument("--legal", type=int, default=4000)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    from exilelens.filters import profile_policy as pp
    from exilelens.filters.profiles import FilterThemeName
    builds = ("no_build", "spark")
    jobs = [(b, lv, REPRESENTATIVE_THEME, args.legal, False) for b in builds for lv in pp.LEVELS]
    theme_jobs = [("no_build", "Recommended", t.value, args.legal, True) for t in FilterThemeName]
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(_job, jobs + theme_jobs))
        rare_results = list(pool.map(_rare_job, [(b, lv) for b in builds for lv in pp.LEVELS]))
    rare = {f"{b}|{lv}|{ctx}": v for b, lv, out in rare_results for ctx, v in out.items()}
    main_results, theme_results = results[:len(jobs)], results[len(jobs):]
    matrix, total_unstyled, total_known_unknown, states = {}, 0, 0, 0
    for build, level, theme, out, rules, valid in main_results:
        for context, summary in out.items():
            matrix[f"{build}|{level}|{context}"] = {**summary, "rules": rules, "valid": valid}
            total_unstyled += summary["unstyled_visible_fallthrough"]
            total_known_unknown += summary["known_in_unknown_safety"]
            states += summary["states"]
    # theme invariance: identical visibility and zero unstyled in every theme
    themes = {}
    reference = None
    for build, level, theme, out, rules, valid in theme_results:
        vis = {c: s["visibility"] for c, s in out.items()}
        reference = reference or vis
        themes[theme] = {"unstyled_visible_fallthrough": sum(s["unstyled_visible_fallthrough"] for s in out.values()),
                         "known_in_unknown_safety": sum(s["known_in_unknown_safety"] for s in out.values()),
                         "visibility_identical_to_first_theme": vis == reference, "valid": valid}
    report = {
        "corpus_item_states": states // (len(builds) * len(pp.LEVELS) * len(CONTEXTS)),
        "evaluations": states, "builds": list(builds), "profiles": list(pp.LEVELS), "contexts": CONTEXTS,
        "unstyled_visible_fallthrough": total_unstyled, "known_in_unknown_safety": total_known_unknown,
        "by_config": matrix, "rare_equipment_audit": rare,
        "rare_equipment_states": sum(v["states"] for v in rare.values()),
        "rare_equipment_unstyled": sum(v["unstyled_visible_fallthrough"] + v["known_in_unknown_safety"] for v in rare.values()),
        "themes": themes,
        "themes_unstyled": sum(t["unstyled_visible_fallthrough"] for t in themes.values()),
        "themes_visibility_identical": all(t["visibility_identical_to_first_theme"] for t in themes.values()),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.name}.json").write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("by_config", "rare_equipment_audit", "themes")}, indent=1))
    clean = (total_unstyled == 0 and total_known_unknown == 0 and report["themes_unstyled"] == 0 and report["rare_equipment_unstyled"] == 0)
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
