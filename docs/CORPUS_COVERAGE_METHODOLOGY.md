# M1.1 Corpus Coverage Matrix — methodology

This document explains the measurement system added for M1.1 Build Corpus Expansion
(foundation/audit slice). It does not add product features, does not change Item
Check scoring/evaluation behavior, and does not fabricate corpus cases. It answers,
as truthfully as the underlying corpus allows:

> What percentage and which categories of real PoE2 builds can ExileLens evaluate
> correctly and safely?

For the current answer, see the generated
[`docs/corpus_coverage/COVERAGE_REPORT.md`](corpus_coverage/COVERAGE_REPORT.md) —
regenerate it with `python scripts/generate_corpus_coverage_report.py` after adding
a fixture, test, or registry entry.

## What already existed (do not re-derive this by re-reading the whole repo)

- **Build Corpus**: `fixtures/builds/public_corpus/manifest.json`, a strict 3-entry,
  7-field manifest (`id, file, class, ascendancy, primary_skill, actor, purpose`),
  enforced by `tests/integration/test_public_build_corpus.py` (`build_corpus` marker).
  A 4th build fixture, `fixtures/builds/core04_player_ring.xml` (Sorceress/Stormweaver,
  Spark, with a "Pinpoint Critical" crit-support gem equipped), exists but is **not**
  in the manifest — it's used by the strategic suite via a hardcoded path.
- **Strategic real-PoB suite**: `tests/integration/test_public_real_pob.py`
  (`real_pob` marker) — 7 hand-written scenarios that call
  `exilelens.items.evaluation.evaluate_item` against the real PoB2 engine and assert
  an actual `EvaluationOutcome`/`PublicVerdict`.
- **Policy safety-net suite**: `tests/test_core_04_adversarial_item_check.py`
  (`itemcheck` marker, no engine) — deterministic, worker-shaped unit tests of the
  verdict/quality contract itself (guardrails, resistance-cap state machine,
  malformed-metric handling, slot selection/mapping, identity/fingerprinting).
- **Existing truthfulness vocabulary** (`src/exilelens/items/evaluation_outcome.py`):
  `EvaluationQuality` (`FULL/PARTIAL/UNSUPPORTED/FAILED`) and `PublicVerdict`
  (directional verdicts, plus `UNCERTAIN`, `UNSUPPORTED`, `NOT_EVALUATED`). These are
  the product's own semantics and this coverage system reuses them rather than
  inventing a competing vocabulary.
- **Existing hand-written coverage doc**:
  `docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md` — a static, human-maintained
  COVERED/PARTIAL/NOT COVERED/UNSUPPORTED BY PRODUCT/NOT APPLICABLE matrix over
  *product policy boundaries* (slots, outcome states, threshold/trade-off policy,
  transaction/identity/perf invariants). It is **not superseded** by this system —
  it documents policy-boundary coverage in depth; this system documents
  build-archetype coverage and turns both into one generated, gradeable baseline.

There was, before this task, no per-fixture archetype/mechanic tagging, no
generated report, and no test-grading vocabulary (`PASS`/`WRONG_RESULT`/etc.)
anywhere in the repository. All of that is new in this slice.

## What this task added

```
tests/corpus_coverage/
  taxonomy.py    # vocabulary: Archetype, EvaluationDepth, ExpectedResult, CoverageResult
  registry.py    # CoverageCase entries — hand-curated pointers at REAL fixtures/tests
  junit.py        # minimal stdlib JUnit XML reader (pytest's own --junitxml output)
  report.py      # pure grading + markdown/JSON rendering (no subprocess/engine calls)
tests/test_corpus_coverage_report.py   # regression tests for the grading logic + registry drift guards
scripts/generate_corpus_coverage_report.py  # CLI: runs the 3 targeted suites, writes the report
docs/corpus_coverage/COVERAGE_REPORT.md      # generated — do not hand-edit
docs/corpus_coverage/coverage_report.json    # generated — machine-readable, same data
```

### Taxonomy

**Archetype** (`tests/corpus_coverage/taxonomy.py`) is the fixed, 18-category list
from the M1.1 task brief: `ascendancy, melee, ranged_attack, spell, crit, dot,
ailment, minion, proxy_totem, trigger, stat_stacker, attribute_stacker,
mana_scaling, es_scaling, life_scaling, weapon_swap, unique_interaction,
unusual_skill_part`. A category with zero registry entries is reported as **NO
COVERAGE** — it is never silently omitted or backfilled with an invented case.

Archetype tags must be justified by the case's actual mechanics, not by the fixture's class or
ascendancy name alone. In particular `ascendancy` is assigned only when an ascendancy-granted
skill or mechanic is what the case measures (for example the CORPUS-02B Djinn cases, whose
primary damage is the Disciple of Varashta's granted Water Djinn). A fixture that merely *has*
an ascendancy, such as the Gemling Legionnaire builds, does not earn the tag.

**EvaluationDepth** distinguishes *how much* a coverage case actually proves:
- `IDENTITY_ONLY` — PoB loads the build and attributes class/ascendancy/skill/actor
  correctly. No `EvaluationOutcome`/verdict is asserted.
- `VERDICT` — the case calls `evaluate_item` (or the real worker) and asserts an
  actual quality/verdict/impact.
- `POLICY_UNIT` — a deterministic, worker-shaped unit test of outcome policy; no
  real build, not archetype-specific (the CORE-04 adversarial suite).

This matters because "3 build fixtures pass" is a much weaker claim than "3 build
fixtures produce a correct, verdict-level Item Check result" — the report keeps
these visibly separate (see the two tables under "Build/verdict-level cases" and
"Policy safety-net" in the generated report).

### Grading: PASS / EXPECTED_UNCERTAIN / UNSUPPORTED / WRONG_UNCERTAIN / WRONG_RESULT

Every `CoverageCase` in the registry declares an `ExpectedResult` — what its author
already asserts is the *correct, truthful* outcome (this is read directly off the
existing test's own assertions, not guessed):

- `CONFIDENT` — a directional/full-quality outcome is correct here.
- `UNCERTAIN` — `PARTIAL`/`UNCERTAIN`/`NOT_EVALUATED` is the correct, safe outcome.
- `UNSUPPORTED` — `PublicVerdict.UNSUPPORTED` is the correct, safe outcome.

`tests/corpus_coverage/report.py::grade_case` then combines that declaration with
the real pytest outcome (from JUnit XML) into one of:

| Grade | Meaning |
| --- | --- |
| `PASS` | Expected `CONFIDENT`, test passed. |
| `EXPECTED_UNCERTAIN` | Expected `UNCERTAIN`, test passed — the product correctly declined to give a directional answer. |
| `UNSUPPORTED` | Expected `UNSUPPORTED`, test passed — the product correctly, explicitly refused to model the mechanic. |
| `WRONG_UNCERTAIN` | Expected `CONFIDENT`, test failed, and the failure text contains a safe-degradation marker (`UNCERTAIN`/`UNSUPPORTED`/`PARTIAL`/`NOT_EVALUATED`/`FAILED`) — the product likely under-answered rather than answered wrongly. Safe but regressed. |
| `WRONG_RESULT` | Expected `CONFIDENT`, test failed, no safe-degradation marker found — treated as "confident but incorrect" until proven otherwise. **This is the high-risk bucket the report calls out explicitly.** |
| `NOT_RUN` | No matching JUnit outcome (engine unavailable, suite not run, or all variants skipped). Never counted toward the headline metric either way. |

**Truthfulness invariant, enforced in code** (`report.py::_grade_for_failure`): if a
case's author declared `UNCERTAIN`/`UNSUPPORTED` as the *correct* outcome and the
test then fails, that is graded `WRONG_RESULT` (the worst bucket), never softened —
a case that was supposed to be a safe non-answer and isn't is not a minor issue.
This mirrors the product's own guardrail policy: fail closed, never open.

`SUPPORTED_RESULTS = {PASS, EXPECTED_UNCERTAIN, UNSUPPORTED}` is what counts toward
"supported real-build coverage" — an explicit, correct `UNCERTAIN`/`UNSUPPORTED` is
success (truthful), not failure. `WRONG_*` and `NOT_RUN` never count.

### Functional coverage (CORPUS-02D1)

The headline metric deliberately counts a correct refusal (`EXPECTED_UNCERTAIN`,
`UNSUPPORTED`) as supported. That methodology is unchanged. It cannot say how much
of a mechanic ExileLens actually measures, so the report adds a separate
**functional coverage** section. A verdict-level `CoverageCase` may declare
`functional=FunctionalMeasurement...`:

| Measurement | Meaning |
| --- | --- |
| `FULLY_MEASURED` | The test asserts a FULL-quality evaluation of the mechanic. The only value that counts as functional coverage. |
| `PARTIALLY_MEASURED` | PoB measured the change, but the asserted evaluation is PARTIAL because ExileLens lacks evidence it could have. |
| `EXPECTED_UNCERTAINTY` | The asserted PARTIAL/UNCERTAIN outcome is correct: the specific information is genuinely insufficient. |
| `UNSUPPORTED_MECHANIC` | The test asserts an explicit UNSUPPORTED refusal. |

A declared case whose test fails is `NOT_ESTABLISHED`. Identity and policy cases are not verdict-level and are not
classified. Since R4 every verdict-level case is either a `MECHANIC` case (classified as above) or a `STATE_INTEGRITY`
case (see "R4 additions"); an unclassified verdict case is a test failure, not a count. `test_declared_functional_measurement_matches_what_the_test_asserts`
checks every declaration against the quality the test body actually asserts.

### Registry, not manifest, carries the taxonomy

Archetype/mechanic tags are **not** added as a new field to
`fixtures/builds/public_corpus/manifest.json`. That manifest has a tight, tested
contract (`test_manifest_is_small_complete_and_repository_relative` asserts the
exact key set and exact 3-entry list) and this task's mandate is the smallest
change that creates a durable foundation — not touching that invariant. Instead,
`tests/corpus_coverage/registry.py` is a separate, additive layer that *points at*
existing manifest ids and existing pytest node names. Three drift guards in
`tests/test_corpus_coverage_report.py` keep it honest:
- every registered `test_file` must exist,
- every registered `manifest_id` must exist in the real manifest,
- every real manifest fixture must have at least one registered case (so a newly
  added corpus fixture can't silently go untagged).

If manifest tagging is wanted later, extending the manifest schema with an
optional `tags` field is a natural follow-up — deliberately not done here to keep
this slice's blast radius small.

### Why the percentage in the report is not "% of real builds ExileLens supports"

The report's headline number is **coverage of executed registry cases** (see the
generated report for the current count), not a statistically meaningful share of the
real PoE2 build population. The repository does not currently contain:
- a sampled/weighted inventory of real builds by popularity or archetype,
- per-mechanic pass/fail data beyond the build fixtures + adversarial unit suite,
- any corpus case at all for 10 of the 18 required archetype categories.

Per the M1.1 brief, this is reported honestly as "not computable without arbitrary
assumptions" rather than papered over with an invented percentage. The structure
(taxonomy + registry + grading + report) is what M1.1's later slices should feed
real corpus growth into, so the metric becomes meaningful as coverage grows.

## How to extend this

1. Add a real build fixture or regression test as usual (see
   `docs/BUILD_CORPUS_SOURCES.md` for fixture provenance/sanitization rules).
2. Add one `CoverageCase` in `tests/corpus_coverage/registry.py` pointing at it,
   with the correct `archetypes`, `depth`, and `expected` result.
3. Run `python scripts/generate_corpus_coverage_report.py` (requires a local PoB2
   install for `build_corpus`/`real_pob` cases; pass `--skip-engine` to grade only
   the policy-unit suite when none is available).
4. Commit the regenerated `docs/corpus_coverage/COVERAGE_REPORT.md` and
   `coverage_report.json` alongside the fixture/test/registry change.

Do not add a `CoverageCase` for a fixture or test that does not exist yet, and do
not invent a fixture merely to fill an empty archetype cell — an empty cell is a
correct, reportable answer.

## R4 additions (1.0 reliability gate)

R4 turned this report into a gate. See `docs/R4-1.0-RELIABILITY-GATE.md` for the findings and the gate definition; the
mechanics are:

- **`CaseRole`** (`taxonomy.py`). A verdict-level case is a `MECHANIC` case (declares `functional`) or a `STATE_INTEGRITY`
  case: loadout, restore, isolation and enumeration plumbing (weapon-set component contexts, effect-level enumeration,
  restore recovery, transaction shape, jewel socket safety). Integrity cases assert no measurement quality, so they are reported
  in their own table and are neither functional coverage nor a gap. A failing integrity case still blocks the gate.
- **`UncertaintyAudit`** (`taxonomy.py`) with `audit_note` and `blocks_1_0` on every case whose correct answer is a refusal
  (expected `UNCERTAIN`/`UNSUPPORTED`) or that is `PARTIALLY_MEASURED`: `CORRECT_UNCERTAINTY` (stays), `FIXABLE_MEASUREMENT_GAP`
  (documented limitation with its effort) or `COPY_OR_DIAGNOSTIC`. The report prints the audit table.
- **Archetype status** is derived from what the cases establish, never from a count: FUNCTIONALLY MEASURED needs a passing
  FULLY_MEASURED verdict case; PARTIAL / EXPECTED UNCERTAINTY describe refusals only; REPRESENTED means identity/policy/integrity
  only; RELEASE GAP means no case.
- **Failing tests outside the registry** are reported and block the gate. Before R4 the headline read 100% beside two failing
  corpus-gate tests because only registered cases were graded. **Skipped tests** in the executed suites are listed (a skip is no evidence).
- **The report records the PoB runtime** (version and layout). Numbers are runtime-specific: the installed PoB Community PoE2 release
  (what users run, auto-detected) and a development git checkout of the same head give different PoB output for some cases, and the
  committed report is the installed-release one. Leave `POB2_PATH` unset when regenerating.
- **`tests/corpus_coverage/gate.py`** holds the machine-checkable rules (`evaluate_gate`) and the Build Intelligence rules
  (`evaluate_build_intel_gate`, over the JSON `scripts/r4_gate_measure.py` writes). Both are engine-free and unit-tested; the
  registry itself is tested to satisfy the gate when every case passes. `python scripts/generate_corpus_coverage_report.py --check-gate`
  exits non-zero when the coverage gate blocks.
- A drift guard fails when a real-PoB integration test file is not wired into the generator's `SUITES`, and the build-corpus privacy scan now
  covers every XML in the corpus directory, with a guard that the directory and the manifest agree.
