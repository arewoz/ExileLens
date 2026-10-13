"""Profile monotonicity contract (FILTER-08D).

Contract: for one build, a stricter profile never shows an item that a looser profile hides:

    Relaxed  ⊇  Recommended  ⊇  Strict  ⊇  Very Strict  ⊇  Uber Strict          (visible sets, exact over the item space)

Profile system V2: Endgame is no longer a profile, so nothing is outside the chain. The chain is exact (box algebra over the whole item
space), not sampled. EXCEPTIONS lists documented, intended inversions as {(looser, stricter, looser_rule, stricter_rule): reason}; it is
empty. An inversion that is not listed is a contract violation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from exilelens.filters import rule_ir as ri
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_generate import generate

CHAIN = ("Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict")
INDEPENDENT: tuple[str, ...] = ()
EXCEPTIONS: dict[tuple[str, str, str, str], str] = {}


@dataclass(frozen=True)
class Inversion:
    build: str
    looser: str
    stricter: str
    looser_rule: str
    stricter_rule: str
    bases: int
    example: str
    documented: bool


def inversions(build: str, needs: BuildNeedsSnapshot, *, rules: Mapping[str, list] | None = None) -> tuple[list[Inversion], dict[str, int]]:
    """Exact inversions for one build plus how many base-weighted regions each step narrows."""
    rules = rules or {p: generate(needs, p).rules for p in CHAIN}
    found: list[Inversion] = []
    narrowed: Counter[str] = Counter()
    for looser, stricter in zip(CHAIN, CHAIN[1:]):
        for diff in ri.compare(rules[looser], rules[stricter]).diffs:
            if diff.category != "VISIBILITY":
                continue
            if diff.a_hidden and not diff.b_hidden:
                key = (looser, stricter, diff.a_rule, diff.b_rule)
                found.append(Inversion(build, looser, stricter, diff.a_rule, diff.b_rule, diff.bases,
                                       f"{diff.example.name} [{diff.example.rarity} i{diff.example.item_level}]", key in EXCEPTIONS))
            else:
                narrowed[f"{looser}->{stricter}"] += diff.bases
    return found, dict(narrowed)


def contract_report(snapshots: Mapping[str, BuildNeedsSnapshot]) -> dict[str, object]:
    violations: list[Inversion] = []
    documented: list[Inversion] = []
    narrowed: Counter[str] = Counter()
    for name, needs in snapshots.items():
        found, steps = inversions(name, needs)
        narrowed.update(steps)
        for inversion in found:
            (documented if inversion.documented else violations).append(inversion)
    return {"chain": list(CHAIN), "independent": list(INDEPENDENT), "builds": len(snapshots), "violations": len(violations),
            "documented_exceptions": len(documented), "narrowing_base_regions": dict(narrowed),
            "examples": [i.__dict__ for i in violations[:20]]}
