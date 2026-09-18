# CORE-04 Item Check adversarial coverage matrix

This matrix describes the current public Item Check product at `origin/main`, not a
feature roadmap. Statuses mean the following:

| Status | Meaning |
| --- | --- |
| `COVERED` | A deterministic CORE-04 regression or current production contract exercises the behavior. |
| `PARTIAL` | The production behavior exists, but the public repository lacks a real-PoB fixture/corpus case needed to validate it end-to-end. |
| `NOT COVERED` | A supported behavior has no adequate public regression. |
| `UNSUPPORTED BY PRODUCT` | The product deliberately rejects or cannot truthfully model the behavior. |
| `NOT APPLICABLE` | The category does not use that dimension. |

## Evidence and scope

The public integration base contains the Item Check production contracts, but was
published without tracked `tests/`, `fixtures/`, or Build Corpus files.
`pyproject.toml` still documents the canonical `pytest -m build_corpus` marker, so
strategic real-PoB and corpus rows cannot be represented as passing public tests yet.
CORE-04 adds deterministic, worker-shaped adversarial cases in
`tests/test_core_04_adversarial_item_check.py`.
They test semantic policy and malformed-output safety without claiming a live PoB
validation that is not available in this repository.

## Slots and categories

| Production category / legal PoB slot | Status | Current coverage / risk note |
| --- | --- | --- |
| Helmet / `Helmet` | COVERED | Canonical slot mapping. |
| Body armour / `Body Armour` | COVERED | Canonical slot mapping. |
| Gloves / `Gloves` | COVERED | Canonical slot mapping. |
| Boots / `Boots` | COVERED | Canonical slot mapping. |
| Belt / `Belt` | COVERED | Canonical slot mapping. |
| Amulet / `Amulet` | COVERED | Canonical slot mapping. |
| Rings / `Ring 1`, `Ring 2` | COVERED | Winner, tie-break, FULL vs PARTIAL/UNSUPPORTED ordering. |
| One-hand weapon / `Weapon 1` | COVERED | Canonical mapping; live replacement/restore is PARTIAL. |
| Two-hand weapon / `Weapon 1` | COVERED | Same current PoB slot as one-hand; live 2H compatibility is PARTIAL. |
| Bow / `Weapon 1` | COVERED | Canonical mapping; bow/quiver end-to-end fixture is PARTIAL. |
| Shield / `Weapon 2` | COVERED | Maps to `OFFHAND_1`; live replacement/restore is PARTIAL. |
| Focus / `Weapon 2` | COVERED | Maps to `OFFHAND_1`; live replacement/restore is PARTIAL. |
| Quiver / `Weapon 2` | COVERED | Maps to `OFFHAND_1`; bow/quiver live fixture is PARTIAL. |
| Weapon 2 weapon / `Weapon 2` | COVERED | Maps to `WEAPON_2`, avoiding offhand conflation. |
| Weapon-set swap / `Weapon 2 Swap` | PARTIAL | Identity contains loadout/item-set state; no public real-PoB fixture. |
| Empty supported slot | COVERED | Empty is distinct from an unknown baseline; live apply/restore is PARTIAL. |
| Jewel / flask | UNSUPPORTED BY PRODUCT | Terminal `ITEM_UNSUPPORTED`, not scored as equipment. |

## Outcome and measurement states

| Dimension | Positive / downgrade / neutral | PARTIAL | UNSUPPORTED | Failure / malformed | Gap |
| --- | --- | --- | --- | --- | --- |
| Public verdict | COVERED | COVERED: cannot become directional | COVERED: cannot win a valid slot | COVERED: `NOT_EVALUATED` | Real-PoB assertions are PARTIAL. |
| Slot ranking | COVERED: rings and stable tie | COVERED | COVERED | COVERED: explicit restore failure | Multi-slot live transaction is PARTIAL. |
| Primary offense | COVERED: score boundaries and trade-off | COVERED | COVERED | COVERED: non-numeric, NaN, infinity, bool fail closed | Skill-derived real output is PARTIAL. |
| EHP / max hit | COVERED: cross-axis trade-off | PARTIAL | NOT APPLICABLE | COVERED through shared malformed-score gate | Real-PoB fixture absent. |
| Known zero | COVERED | NOT APPLICABLE | NOT APPLICABLE | NOT APPLICABLE | Legitimate zero remains `available`. |
| Missing / unavailable | COVERED: score contributes no synthetic value | COVERED | NOT APPLICABLE | COVERED: malformed is not reclassified as zero | All raw metric kinds are not individually enumerated. |
| Resistance | COVERED: below cap, cap reached/lost, capped, buffer loss, missing | PARTIAL | NOT APPLICABLE | COVERED through numeric ingestion | Multi-resistance live fixture absent. |
| Requirements / resource sustain | COVERED by existing threshold/guardrail contract | PARTIAL | UNSUPPORTED BY PRODUCT when bridge omits required fields | COVERED through malformed gate | No public real-PoB requirement fixture. |

## Build dimensions

| Dimension | Status | Evidence / current boundary |
| --- | --- | --- |
| Offense | COVERED | Direct metric profile, quality gate, score bands, trade-off policy. |
| Defense | COVERED | EHP/max-hit axis is independent from offense in `ItemImpact`. |
| Recovery | PARTIAL | Current raw recovery comparison is modeled; no public adversarial fixture. |
| Utility / movement | PARTIAL | Current movement policy is modeled; no public threshold fixture. |
| Resistances | COVERED | State-machine boundaries and missing state. |
| Requirements | PARTIAL | Current guardrail contract is present; no public bridge fixture. |
| Gem level / local weapon stats / sockets / runes / enchantments | PARTIAL | Candidate fingerprint distinguishes meaningful text; no public parser/PoB fixture corpus. |
| Player actor | PARTIAL | Context identity retains actor/skill components; no public real-PoB fixture. |
| Verified minion actor | PARTIAL | Product has minion provenance/coverage paths; no public fixture. |
| Stage, stat set, skill part | PARTIAL | Primary-skill guard detects semantic changes; no public fixture. |
| Loadout / weapon set | PARTIAL | Context identity includes loadout/item set; no public transaction fixture. |

## Threshold and trade-off policy

| Policy boundary | Status | Covered exact behavior |
| --- | --- | --- |
| Public score bands | COVERED | Just below and at `60`, `53`, `47`, and `40`; the implementation intentionally uses `>` below the neutral/downgrade boundaries. |
| Display thresholds | PARTIAL | Constants are inspectable, but display-only boundaries need public UI/fixture coverage. |
| Resistance effective cap | COVERED | Below-cap improvement, reaches cap, cap loss, stays capped, and overcap-buffer loss. |
| Material resistance deficit | PARTIAL | Current guardrail constant is documented in source; no end-to-end public fixture. |
| Offense/defense conflict | COVERED | Large offense gain plus large defense loss remains `TRADEOFF` in the multi-axis impact model. |
| Recovery or utility conflict | PARTIAL | Policy supports the axes; fixture absent. |

## Transaction, identity, and performance

| Invariant | Status | Evidence |
| --- | --- | --- |
| Candidate formatting normalization | COVERED | CRLF/trailing-space/blank-line normalization is equivalent. |
| Meaningful candidate change | COVERED | Modifier value change changes fingerprint. |
| Evaluation context identity | COVERED | Loadout, item set, worker generation, source revision, calculation context change identity. |
| Stale/cross-context cache rejection | PARTIAL | Identity is present in production; controller/cache integration test is absent publicly. |
| One item, one batched PoB transaction | PARTIAL | Production evaluates compatible slots in one `evaluate_item_slots` call; no public instrumentation fixture. |
| Restore after successful/failing slot evaluation | PARTIAL | Production fails closed and invalidates on restore mismatch; no public worker fault fixture. |
| A → B → A baseline invariance | PARTIAL | Production contract exists; no public corpus/worker fixture. |

## Adversarial corpus extension

The deterministic scenarios in `tests/test_core_04_adversarial_item_check.py` are
the public adversarial extension. Each uses the same shape emitted by the PoB worker:

| Scenario | Happy path it defeats | Expected result |
| --- | --- | --- |
| Ring 1 unsupported vs Ring 2 FULL | Highest scalar rating can otherwise mask unsupported evidence | FULL Ring 2 is selected. |
| Valid FULL downgrade vs unsupported ring | Unsupported must not become a recommendation merely because it has a high score | FULL comparison is selected. |
| Non-numeric / NaN / infinity / bool metric | Numeric coercion can throw before the truthfulness gate | `FAILED` + `NOT_EVALUATED`. |
| Known zero vs missing primary offense | `None` and zero can silently collapse during scoring | Zero remains available; missing contributes no score. |
| Resistance cap transitions | Raw resistance changes alone can misstate cap semantics | Explicit cap-state classification. |
| Large offense gain with large defense loss | Weighted aggregate can hide an opposing dimension | `TRADEOFF` impact pattern. |
| Empty vs unknown slot | Empty can be guessed from missing baseline data | Only explicit unequipped state is empty. |

## Risk register and deferrals

| Priority | Finding | Disposition |
| --- | --- | --- |
| P0 | Malformed numeric worker output could throw while building a metric profile, before `EvaluationOutcome` could fail closed. | Fixed: finite numeric ingestion in metrics/resistance/threshold handling; scored malformed values produce `FAILED`/`NOT_EVALUATED` regression coverage. |
| P1 | The public integration base has no real-PoB fixtures or Build Corpus despite documented markers. | Deferred as repository-test-data availability, not product behavior. It blocks a claim of strategic real-PoB or corpus PASS. |
| P2 | Display-threshold, recovery, minion/stage/stat-set/skill-part explanations lack public fixture-level boundary tests. | Deferred pending public deterministic fixtures; no new mechanics proposed. |

Exact deferred items:

1. Publish sanitized real-PoB fixtures for ring winner, empty slot, bow/quiver or weapon/offhand, skill/actor, and fault/recovery paths.
2. Publish the sanitized current Build Corpus and its canonical invocation, then run it once on this branch and `origin/main` when failures need classification.
3. Add worker-level transaction instrumentation to assert one batched candidate evaluation and baseline restoration across mixed slot failures.
