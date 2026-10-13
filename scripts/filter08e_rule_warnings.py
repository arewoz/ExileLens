"""FILTER-08E: structural decomposition of the rule-IR warnings (shadowed / duplicate / redundant) over every public build x profile.

    python scripts/filter08e_rule_warnings.py [--needs artifacts/filter08e/needs] [--out artifacts/filter08e/rule_warning_decomposition.json]

Every warning is assigned exactly one structural cause, from the rule's own name/category and the rules that cover it. Nothing is removed
here: only the verified optimiser removes rules, and only with a proven-equivalence result (duplicates and fully shadowed rules)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exilelens.filters import benchmark08b as bm, rule_ir as ri  # noqa: E402
from exilelens.filters.intel_generate import generate  # noqa: E402

SLOT_PAIR = re.compile(r"(WEAPON|OFFHAND|RING)_([12])(?=_|$)")

CAUSES = {
    "ARCHITECTURE_DUPLICATION": "the generator emits one rule per slot; WEAPON_2 / OFFHAND_2 / RING_2 repeat the _1 rule when both slots resolve to the "
                                "same classes and bases (the _1 rule is then reported redundant because the _2 copy follows it)",
    "INTENTIONAL_SPECIALIZATION": "a build-independent trade-candidate rule is covered by earlier, more specific build / unidentified-tier rules; "
                                  "specific-before-general ordering is the design",
    "STYLE_DUPLICATION": "adjacent rules end in the same visible effect (the theme gives neighbouring tiers / categories the same style), so the "
                         "earlier rule is redundant for visibility but is kept for its own provenance text",
    "TIER_STYLE_COLLAPSE": "a tier rule whose bases would fall through to the next tier's rule with an identical effect in this profile",
    "LEGACY_FALLBACK": "a rule kept for the build-independent (legacy) path that a measured build also covers",
    "MOST_VISIBLE_ROW": "profile system V2: an item takes the MOST VISIBLE state of the matrix rows it belongs to, so a row's rule can be fully "
                        "covered by an earlier, more visible row (a Rare craft base that is also an unidentified tier 5 rare, a LOW craft "
                        "base the build lane already shows)",
    "UNEXPLAINED": "no structural cause matched",
}


def cause(finding, rules_by_name) -> str:
    name = finding.rule
    if finding.kind in ("DUPLICATE", "REDUNDANT") and SLOT_PAIR.search(name):
        return "ARCHITECTURE_DUPLICATION"
    if finding.kind == "SHADOWED" and finding.category == "TRADE_BASES":
        return "INTENTIONAL_SPECIALIZATION"
    if finding.kind == "SHADOWED" and SLOT_PAIR.search(name):
        return "ARCHITECTURE_DUPLICATION"
    if finding.kind == "REDUNDANT" and finding.category in ("CRAFTING_BASES", "TRADE_BASES", "TRADE_HERO", "TRADE_SPECIAL") \
            or finding.category.startswith("CURRENCY_"):
        return "STYLE_DUPLICATION"
    if finding.kind == "REDUNDANT" and finding.category.startswith("BUILD"):
        return "TIER_STYLE_COLLAPSE"
    if finding.kind in ("SHADOWED", "DUPLICATE", "REDUNDANT") and finding.category in (
            "CRAFT_OPPORTUNITY", "GENERIC_EQUIPMENT", "TRADE_BASES", "HIGH_VALUE_UNID", "PROTECTIVE", "HIDDEN_CLUTTER"):
        return "MOST_VISIBLE_ROW"
    if finding.kind == "SHADOWED" and finding.category.startswith("BUILD"):
        return "INTENTIONAL_SPECIALIZATION"
    return "UNEXPLAINED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--needs", default=str(ROOT / "artifacts" / "filter08c" / "needs"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "filter08e" / "rule_warning_decomposition.json"))
    args = parser.parse_args()
    snapshots = bm.load_snapshots(Path(args.needs))
    totals: Counter = Counter()
    by_kind: dict[str, Counter] = defaultdict(Counter)
    by_profile: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, str] = {}
    removable = Counter()
    for label, needs in snapshots.items():
        for profile in bm.PROFILES:
            result = generate(needs, profile)
            by_name = {r.name: r for r in result.rules}
            report = ri.analyse(result.rules)
            for finding in report.findings:
                if finding.kind not in ("SHADOWED", "DUPLICATE", "REDUNDANT"):
                    continue
                c = cause(finding, by_name)
                totals[c] += 1
                by_kind[finding.kind][c] += 1
                by_profile[profile][c] += 1
                examples.setdefault(f"{finding.kind}/{c}", f"{label} {profile}: {finding.rule} — {finding.detail}")
                if finding.kind in ("SHADOWED", "DUPLICATE"):
                    removable[c] += 1
    payload = {"builds": len(snapshots), "filters": len(snapshots) * len(bm.PROFILES), "causes": CAUSES, "total_by_cause": dict(totals),
               "by_kind": {k: dict(v) for k, v in by_kind.items()}, "by_profile": {k: dict(v) for k, v in by_profile.items()},
               "removable_with_proof (shadowed + duplicate; the optimiser removes exactly these)": dict(removable), "examples": examples,
               "unexplained": totals.get("UNEXPLAINED", 0), "total_warnings": sum(totals.values()),
               "policy": "REDUNDANT rules are kept: removing them is semantically neutral for visibility and style but changes the matched rule "
                         "and therefore the explanation shown for an item. Explainability outranks file size."}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("total_warnings", "total_by_cause", "by_kind", "unexplained")}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
