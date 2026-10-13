"""Generated-filter preflight: every exact BaseType a generated filter can contain, checked against the native ground-base registry.

The union is collected over profiles x builds x themes (rule identity can vary with each), validated ONCE, and reported by status and by
evidence source. The invariant is the whole point: EVERY emitted `BaseType == "X"` has X in NATIVE_FILTER_GROUND_BASES.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from exilelens.filters import native_bases as nb

_QUOTED = re.compile(r'"([^"]+)"')


def collect_job(args) -> dict:
    """One (build, profile, theme) generation -> {name: [(row, rule name)]} plus the generator's exclusions (picklable, process-pool safe)."""
    from exilelens.filters.intel_generate import generate
    build_key, needs, level, theme = args
    result = generate(needs, level, theme, intel=True)
    names: dict[str, set] = defaultdict(set)
    for rule in result.rules:
        for line in rule.lines:
            if line.strip().startswith("BaseType"):
                for name in _QUOTED.findall(line):
                    names[name].add((rule.row, rule.name.split(" [")[0]))
    return {"build": build_key, "level": level, "theme": theme, "valid": result.valid, "errors": list(result.errors),
            "names": {k: sorted(v) for k, v in names.items()}, "excluded": [list(e) for e in result.excluded_bases],
            "violations": nb.base_type_violations(result.text)}


def evaluate(jobs: list[dict]) -> dict:
    """Union of every job's names, classified once."""
    union: dict[str, set] = defaultdict(set)
    for job in jobs:
        for name, rows in job["names"].items():
            union[name].update(tuple(r) for r in rows)
    registry = nb.load_registry()
    by_status: Counter = Counter()
    by_source: Counter = Counter()
    by_confidence: Counter = Counter()
    rejected: dict[str, dict] = {}
    for name in sorted(union):
        entry = registry.get(name)
        status = entry.status.value if entry else nb.Status.UNKNOWN.value
        by_status[status] += 1
        if entry is not None and entry.ground_valid:
            by_source[entry.source] += 1
            by_confidence[entry.confidence] += 1
        else:
            rejected[name] = {"status": status, "reason": nb.rejection_reason(name), "rules": sorted(map(list, union[name]))[:6]}
    excluded = sorted({tuple(e) for job in jobs for e in job["excluded"]})
    return {
        "combinations": len(jobs),
        "builds": sorted({j["build"] for j in jobs}), "profiles": sorted({j["level"] for j in jobs}), "themes": sorted({j["theme"] for j in jobs}),
        "unique_emitted_base_types": len(union),
        "verified_valid": by_status.get("GROUND_FILTER_VALID", 0),
        "by_status": dict(by_status), "evidence_source": dict(by_source), "confidence": dict(by_confidence),
        "ambiguous": by_status.get("AMBIGUOUS", 0), "unknown": by_status.get("UNKNOWN", 0),
        "rejected_synthetic": by_status.get("POB_SYNTHETIC", 0),
        "rejected": rejected,
        "emitted_names": sorted(union),
        "excluded_by_generator": [list(e) for e in excluded],
        "generation_failures": [{"build": j["build"], "level": j["level"], "theme": j["theme"], "errors": j["errors"][:3]}
                                for j in jobs if not j["valid"]],
        "text_violations": sum(len(j["violations"]) for j in jobs),
        "all_emitted_ground_valid": not rejected and all(j["valid"] for j in jobs) and not any(j["violations"] for j in jobs),
    }


def registry_audit() -> dict:
    """The audited PoB catalog by status, every non-valid / non-default entry spelled out, and the game names the PoB catalog lacks."""
    from collections import defaultdict as _dd
    from exilelens.filters.verified_bases import load_pob_bases
    registry = nb.load_registry()
    pob = load_pob_bases()
    evidence = json.loads(nb.EVIDENCE_FILE.read_text(encoding="utf-8"))["items"]
    by_status: dict[str, list[str]] = _dd(list)
    for name in sorted(pob):
        by_status[registry[name].status.value].append(name)
    pob_valid = by_status.get("GROUND_FILTER_VALID", [])
    detail = {}
    for name in sorted(pob):
        entry = registry[name]
        if not entry.ground_valid or entry.scope != "any":
            detail[name] = {"status": entry.status.value, "pob_class": entry.pob_class, "scope": entry.scope, "confidence": entry.confidence,
                            "source": entry.source, "note": entry.note, **({"game_name": entry.real_name} if entry.real_name else {})}
    game_only = sorted(n for n, ev in evidence.items() if ev.get("listed") and n not in pob and ev.get("class") not in
                       ("Stackable Currency", "Incubators", "Omen", "Augment"))
    return {
        "pob_bases_audited": len(pob),
        "by_status": {k: len(v) for k, v in sorted(by_status.items())},
        "ground_valid_scope": {"any": sum(1 for n in pob_valid if registry[n].scope == "any"),
                               "unique_only": sum(1 for n in pob_valid if registry[n].scope == "unique_only")},
        "not_default_entries": detail,
        "runeforged_runemastered": {"pob_names": sum(1 for n in pob if n.startswith(("Runeforged ", "Runemastered "))),
                                    "ground_valid": sum(1 for n in pob if n.startswith(("Runeforged ", "Runemastered ")) and registry[n].ground_valid)},
        "game_names_missing_from_pob_catalog (listed on PoE2DB, not generated; the SAFETY catch-all covers them)": game_only,
        "specials_audited": {n: registry[n].status.value for n in sorted(registry) if n not in pob},
    }
