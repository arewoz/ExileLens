"""Coverage taxonomy for the M1.1 Corpus Coverage Matrix.

This module defines vocabulary only — no test logic and no product logic. It is
imported by `registry.py` (what coverage actually exists) and `report.py` (how to
grade and present it).

Grading reuses the product's own truthfulness semantics wherever they already exist
(`exilelens.items.evaluation_outcome.EvaluationQuality` / `PublicVerdict`) rather than
inventing competing terminology. The five-way `CoverageResult` below is a *grading*
layer on top of those existing enums: it answers "did this coverage case behave the
way its author declared it should", not "what verdict did the product return".
"""

from __future__ import annotations

from enum import Enum


class Archetype(str, Enum):
    """Real-build categories the M1 roadmap wants measurable visibility into.

    This list is fixed by the M1.1 task brief. A category with zero corpus cases is
    a real, reportable gap — it is not filled with invented fixtures.
    """

    ASCENDANCY = "ascendancy"
    MELEE = "melee"
    RANGED_ATTACK = "ranged_attack"
    SPELL = "spell"
    CRIT = "crit"
    DOT = "dot"
    AILMENT = "ailment"
    MINION = "minion"
    PROXY_TOTEM = "proxy_totem"
    TRIGGER = "trigger"
    STAT_STACKER = "stat_stacker"
    ATTRIBUTE_STACKER = "attribute_stacker"
    MANA_SCALING = "mana_scaling"
    ES_SCALING = "es_scaling"
    LIFE_SCALING = "life_scaling"
    WEAPON_SWAP = "weapon_swap"
    UNIQUE_INTERACTION = "unique_interaction"
    UNUSUAL_SKILL_PART = "unusual_skill_part"


class EvaluationDepth(str, Enum):
    """How deeply a coverage case exercises Item Check."""

    # Confirms PoB loads the build and identifies class/ascendancy/skill/actor
    # correctly. Does not assert an EvaluationOutcome/PublicVerdict.
    IDENTITY_ONLY = "IDENTITY_ONLY"
    # Calls `evaluate_item` (or drives the real PoB worker) and asserts an actual
    # EvaluationOutcome/PublicVerdict/quality.
    VERDICT = "VERDICT"
    # Deterministic, worker-shaped unit test of outcome policy (no real PoB, no
    # build fixture) — e.g. guardrails, resistance-cap state machine, malformed
    # metric handling. Exercises the safety net, not a build archetype.
    POLICY_UNIT = "POLICY_UNIT"


class ExpectedResult(str, Enum):
    """What a coverage case's author declared the correct, truthful outcome to be."""

    # A confident, directional/full-quality outcome is the correct answer here.
    CONFIDENT = "CONFIDENT"
    # PARTIAL/UNCERTAIN/NOT_EVALUATED is the correct, safe outcome for this case.
    UNCERTAIN = "UNCERTAIN"
    # PublicVerdict.UNSUPPORTED/EvaluationQuality.UNSUPPORTED is the correct,
    # safe outcome for this case (PoB cannot model the semantic axis at all).
    UNSUPPORTED = "UNSUPPORTED"


class CoverageResult(str, Enum):
    """The grade the report assigns to each executed coverage case.

    PASS               - expected CONFIDENT, actual test outcome passed.
    EXPECTED_UNCERTAIN - expected UNCERTAIN, actual test outcome passed (product
                          correctly declined to give a directional answer).
    UNSUPPORTED        - expected UNSUPPORTED, actual test outcome passed (product
                          correctly and explicitly refused to model the mechanic).
    WRONG_UNCERTAIN    - expected CONFIDENT, actual test outcome failed, and the
                          failure looks like the product under-answered (returned
                          UNCERTAIN/UNSUPPORTED/NOT_EVALUATED instead of a directional
                          verdict). Safe but regressed; not the P0 risk.
    WRONG_RESULT       - expected CONFIDENT, actual test outcome failed, and nothing
                          indicates a safe under-answer. Treated as "confident but
                          incorrect" until proven otherwise: the truthfulness
                          invariant means we fail closed to the worse bucket, never
                          the better one, when a failure can't be explained.
    NOT_RUN            - the case could not be executed in this environment (e.g. no
                          local PoB2 install). Never counted as evidence either way.
    """

    PASS = "PASS"
    EXPECTED_UNCERTAIN = "EXPECTED_UNCERTAIN"
    UNSUPPORTED = "UNSUPPORTED"
    WRONG_UNCERTAIN = "WRONG_UNCERTAIN"
    WRONG_RESULT = "WRONG_RESULT"
    NOT_RUN = "NOT_RUN"


# Grades that count as "supported real-build coverage" for the headline product
# metric. WRONG_* and NOT_RUN never count, by design (see CoverageResult docstring
# and docs/CORPUS_COVERAGE_METHODOLOGY.md).
SUPPORTED_RESULTS = frozenset(
    {CoverageResult.PASS, CoverageResult.EXPECTED_UNCERTAIN, CoverageResult.UNSUPPORTED}
)

# Grades that represent a truthfulness/safety risk worth surfacing prominently.
HIGH_RISK_RESULTS = frozenset({CoverageResult.WRONG_RESULT})
