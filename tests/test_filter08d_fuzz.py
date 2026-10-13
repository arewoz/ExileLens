"""FILTER-08D: generated legal corpus + property/fuzz harness (small, deterministic slices of the full run).

Run with:  python -m pytest tests/test_filter08d_fuzz.py -m ""
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from exilelens.filters import benchmark08b as bm, fuzz_harness as fh, legal_corpus as lc
from exilelens.filters.legal_corpus import Legality

ROOT = Path(__file__).resolve().parents[1]
NEEDS = ROOT / "tests" / "fixtures" / "filter_needs" / "filter08e"


@pytest.fixture(scope="module")
def bases():
    if not NEEDS.exists():
        pytest.skip("08C needs snapshots not present")
    return bm.load_snapshots(NEEDS)


def test_corpus_is_independent_of_filter_logic():
    """The generator must not import rules, profiles, tiers, the opportunity model or the simulator."""
    tree = ast.parse(inspect.getsource(lc))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = ("rules", "profiles", "priorities", "opportunity", "decision", "intel_generate", "generator", "benchmark08b")
    assert not [m for m in imported if any(m.endswith("." + f) or m.endswith(f) for f in forbidden)], imported
    assert imported <= {"__future__", "collections", "dataclasses", "enum", "typing", "random",
                        "exilelens.filters.preview", "exilelens.filters.verified_bases"}


def test_corpus_scale_and_legality_classes():
    census = lc.census()
    assert census["total"] >= 100_000
    assert {"LEGAL", "INVALID", "AMBIGUOUS / NOT ESTABLISHED"} <= set(census["by_legality"])
    assert census["by_legality"]["INVALID"] > 0 and census["by_legality"]["LEGAL"] > census["by_legality"]["INVALID"]


def test_corpus_legality_rules():
    base = "Plated Greaves"
    assert lc.classify_equipment(base, "Magic", 82, 0, 0)[0] == Legality.LEGAL
    assert lc.classify_equipment(base, "Magic", 101, 0, 0)[0] == Legality.INVALID
    assert lc.classify_equipment(base, "Magic", 82, -1, 0)[0] == Legality.INVALID
    assert lc.classify_equipment(base, "Magic", 82, 0, 2)[0] == Legality.INVALID       # tier only on unidentified Rare
    assert lc.classify_equipment(base, "Rare", 82, 0, 3)[0] == Legality.AMBIGUOUS
    assert lc.classify_equipment(base, "Normal", 82, 25, 0)[0] == Legality.AMBIGUOUS
    assert lc.classify_equipment("No Such Base", "Magic", 82, 0, 0)[0] == Legality.INVALID
    required = int(lc.load_base_properties()[base]["required_level"])
    assert lc.classify_equipment(base, "Magic", required - 1, 0, 0)[0] == Legality.INVALID


def test_corpus_is_deterministic():
    assert [c.id for c in lc.sample(500, 7)] == [c.id for c in lc.sample(500, 7)]
    assert [c.id for c in lc.sample(500, 7)] != [c.id for c in lc.sample(500, 8)]


def test_protected_items_are_never_hidden(bases):
    corpus = [c for c in lc.sample(300, 3) if c.protected] or [c for c in lc.special_cases() if c.protected]
    ev = fh.Evaluator([c.item for c in corpus])
    for name in list(bases)[:3]:
        variant = fh.Variant(name, bases[name], "real", None)
        assert fh.check_B(ev, variant, corpus) == []


def test_fuzz_slice_has_no_violations(bases):
    corpus = lc.sample(500, 2)
    report, _ev, variants = fh.run(bases, corpus, seed=2, per_base=1, variant_limit=4, sweep_items=60)
    assert report.generations > 0 and report.decisions > 0
    assert report.summary()["violations"] == {}, report.violations[:3]
    assert {v.kind for v in variants} <= {"real", "degraded", "random", "unmeasured"}


def test_fuzz_is_reproducible(bases):
    corpus = lc.sample(200, 4)
    a, *_ = fh.run(bases, corpus, seed=5, per_base=1, variant_limit=2, sweep_items=30)
    b, *_ = fh.run(bases, corpus, seed=5, per_base=1, variant_limit=2, sweep_items=30)
    assert a.summary() == b.summary()


def test_degraded_variants_lose_knowledge_not_gain_it(bases):
    variants = fh.make_variants(bases, 1, 1)
    degraded = [v for v in variants if v.kind == "degraded"]
    assert degraded
    for v in degraded[:10]:
        assert v.parent is not None
        assert len(v.needs.signals) <= len(v.parent.signals)
        assert not v.needs.evidence_complete or v.needs.signals == v.parent.signals


def test_regression_fixtures_replay_clean():
    """Every persisted minimised failure must stay fixed."""
    directory = fh.REGRESSION_DIR
    paths = sorted(directory.glob("*.json")) if directory.exists() else []
    assert paths, "no regression fixtures present"
    for path in paths:
        variant, violation, case = fh.load_regression(path)
        assert not fh.violates(variant, violation, case), f"{path.name} regressed"


def test_invariant_checks_can_fail():
    """A harness that cannot fail proves nothing: a hide of a protected item must be reported by invariant B."""
    corpus = [c for c in lc.special_cases() if c.protected][:1]

    class AlwaysHide:
        def hidden(self, needs, profile):
            return [True] * len(corpus)

    variant = fh.Variant("synthetic", None, "real", None)
    found = fh.check_B(AlwaysHide(), variant, corpus, profiles=("Recommended",))
    assert found and found[0].invariant == "B"


def test_legacy_08b_measurements_are_incomplete_and_never_narrow():
    """The 08B stored measurements predate the Armour/Evasion probes: they may promote but must not hide beyond the no-knowledge floor."""
    legacy_dir = ROOT / "tests" / "fixtures" / "filter_needs" / "filter08b"
    if not legacy_dir.exists():
        pytest.skip("08B snapshots not present")
    legacy = bm.load_snapshots(legacy_dir)
    assert legacy and not any(n.evidence_complete for n in legacy.values())
    corpus = lc.sample(400, 6)
    ev = fh.Evaluator([c.item for c in corpus])
    for name in list(legacy)[:4]:
        variant = fh.Variant(name, legacy[name], "degraded", legacy[name])
        assert fh.check_E(ev, variant, corpus) == [], name
