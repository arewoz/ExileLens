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

CORE-04A supplies sanitized, repository-relative real-PoB fixtures and a deterministic
Build Corpus. The strategic public gate is `pytest -m real_pob`; the corpus gate is
`pytest -m build_corpus`. CORE-04 adds deterministic worker-shaped adversarial cases
in `tests/test_core_04_adversarial_item_check.py`, complementing those end-to-end
fixtures with exact malformed-output and policy-boundary assertions.

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
| One-hand weapon / `Weapon 1`, `Weapon 2` | COVERED | Public fixture (`core04_onehand_weapon.xml`, Shield Wall/one-hand mace + tower shield) validates live replacement, restore, and the `AMBIGUOUS_WEAPON_LAYOUT` multi-slot case (below). |
| Two-hand weapon / `Weapon 1` | COVERED | Public melee fixture (`core04_melee_weapon.xml`, Sunder/two-handed mace) validates single-slot resolution, live replacement, and restore for a real two-handed weapon. |
| Ambiguous weapon-slot layout (`AMBIGUOUS_WEAPON_LAYOUT`) | COVERED | A one-hand weapon candidate legal in both `Weapon 1` and `Weapon 2` (dual-wield-capable layout) is evaluated in both slots under the same generic batched-transaction/ranking/guardrail path as Ring 1/Ring 2 — no weapon-specific slot-picking logic exists or is needed. The slot that would remove a shield the main skill depends on is correctly forced to `NOT_VIABLE` by the existing `MAIN_SKILL_INVALID` guardrail, never a confident directional verdict; best-slot ranking never surfaces it. |
| Bow / `Weapon 1` | COVERED | Public bow/quiver fixture retains the player skill and validates the quiver replacement path. |
| Shield / `Weapon 2` | COVERED | Maps to `OFFHAND_1`; live replacement/restore is PARTIAL. |
| Focus / `Weapon 2` | COVERED | Maps to `OFFHAND_1`; live replacement/restore is PARTIAL. |
| Quiver / `Weapon 2` | COVERED | Maps to `OFFHAND_1`; public bow/quiver gate covers replacement and restore. |
| Weapon 2 weapon / `Weapon 2` | COVERED | Maps to `WEAPON_2`, avoiding offhand conflation. |
| Weapon-set swap / `Weapon 2 Swap` | PARTIAL | Identity contains loadout/item-set state; no public real-PoB fixture. |
| Empty supported slot | COVERED | Empty is distinct from an unknown baseline; live apply/restore is PARTIAL. |
| Jewel / flask | UNSUPPORTED BY PRODUCT | Terminal `ITEM_UNSUPPORTED`, not scored as equipment. |

## Outcome and measurement states

| Dimension | Positive / downgrade / neutral | PARTIAL | UNSUPPORTED | Failure / malformed | Gap |
| --- | --- | --- | --- | --- | --- |
| Public verdict | COVERED | COVERED: cannot become directional | COVERED: cannot win a valid slot | COVERED: `NOT_EVALUATED` | Public ring fixture covers measured offense, defense, trade-off, and empty-slot behavior. |
| Slot ranking | COVERED: rings and stable tie | COVERED | COVERED | COVERED: explicit restore failure | Public ring fixture covers a two-slot transaction; broader multi-slot classes remain PARTIAL. |
| Primary offense | COVERED: score boundaries and trade-off | COVERED | COVERED | COVERED: non-numeric, NaN, infinity, bool fail closed | Ailment-dominant real skill-derived output is COVERED (`core04_poison_ailment.xml`); mixed hit+ailment (`DamageQuantity.HIT_PLUS_AILMENT`, `CombinedDPS` already ≥ the dominant single component) has no public fixture yet — PARTIAL. |
| EHP / max hit | COVERED: cross-axis trade-off | PARTIAL | NOT APPLICABLE | COVERED through shared malformed-score gate | Public ring fixture covers a measured defense improvement; broader real-build boundary coverage is PARTIAL. |
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
| Player actor | COVERED | Public ring and bow/quiver fixtures retain the player skill identity. |
| Verified minion actor | COVERED | Public corpus verifies minion actor identity. |
| Stage, stat set, skill part | COVERED | Public corpus verifies channel-release stage context; stat-set and skill-part variants remain PARTIAL. |
| Loadout / weapon set | PARTIAL — CONFIRMED DEFECT in candidate substitution | `core04_weapon_swap.xml` (a real Huntress/Ritualist Poisonburst Arrow build with `useSecondWeaponSet="true"`) proves build load, active-item-set identity, skill identity, and **baseline** offense correctly reflect the active second weapon set (COVERED — `WEAPON-SWAP-BASELINE-REFLECTS-ACTIVE-SET`). It also proves, via a real-PoB regression, that Item Check's **candidate substitution** always writes into the primary `Weapon 1`/`Weapon 2` PoB slots and never into `Weapon 1 Swap`/`Weapon 2 Swap` — so for any build whose active set is the second weapon set, a candidate targeting that active slot produces a confident but completely disconnected `FULL`/`SIDEGRADE` (0% measured change) regardless of the candidate's actual stats. This is pinned as `test_weapon_swap_candidate_substitution_ignores_the_active_slot` (`xfail(strict=True)`, M1.1) rather than registered as coverage — see risk register. Root cause: architectural (PoB's `itemsTab` exposes four independent weapon-slot objects; `bridge.lua` has no `useSecondWeaponSet`-aware redirection; `ProductSlot.OFFHAND_2`'s `"Weapon 2 Swap"` mapping in `slots.py` is dormant/uncalled). Not fixed this slice. |
| Offense quantity selection (hit vs skill-DoT vs ailment) | PARTIAL | `resolve_primary_metric`'s ailment-dominant branch (`DamageQuantity.AILMENT_DPS`, PoisonDPS/IgniteDPS/BleedDPS selected directly over hit DPS) is COVERED by `core04_poison_ailment.xml` — a real Huntress/Ritualist Poisonburst Arrow build where PoB's own PoisonDPS is ~89% of CombinedDPS. A real candidate ("increased Damage with Poison") that produced a reproducible zero-delta at every tested magnitude was investigated and attributed to PoB's own calculation for this stat set (Bursting Plague-detonated poison), not an ExileLens defect — ExileLens never derives a damage number independently (`docs/POB_NATIVE_DAMAGE_POLICY.md`). The mixed hit+ailment branch (`DamageQuantity.HIT_PLUS_AILMENT`, `CombinedDPS` selected over either isolated component) is now also COVERED by `core04_mixed_hit_ailment.xml` — a real Witch/Infernalist Comet build with a ~59%/41% hit/ignite split, where the fixture proves `CombinedDPS == TotalDPS + IgniteDPS` exactly (no double counting) in both baseline and candidate, and a genuine FULL-quality confident verdict (unlike the ailment-dominant case, which stays truthfully PARTIAL/UNCERTAIN). The skill-native-DoT branch (`DamageQuantity.SKILL_DOT`, `TotalDot`/`FullDotDPS`, no separate ailment field at all) remains unfixtured. |

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
| One item, one batched PoB transaction | COVERED | Public real-PoB gate counts one `evaluate_item_slots` call for a two-ring Item Check. |
| Restore after successful/failing slot evaluation | COVERED | Public real-PoB gate proves a corrupt restore is followed by a clean valid evaluation. |
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
| P1 | Public real-PoB fixtures and Build Corpus were absent when CORE-04 was first authored. | Resolved by CORE-04A: repository-relative strategic fixtures and both public gates are now available. |
| P2 | Display-threshold, recovery, stat-set, skill-part, and broad multi-slot explanations lack fixture-level boundary tests. | Deferred as bounded public-fixture coverage; no new mechanics proposed. |
| P2 | `resolve_primary_metric`'s DoT/ailment offense-quantity selection (`OffenseKind.DOT_DPS`, `DamageQuantity.AILMENT_DPS`/`SKILL_DOT`/`HIT_PLUS_AILMENT`) had zero coverage at any level (no unit test, no real-PoB fixture) despite being documented product policy (`docs/POB_NATIVE_DAMAGE_POLICY.md` P1-B). | Mostly resolved by M1.1: `core04_poison_ailment.xml` proves the ailment-dominant branch (correct field selection, correctly measured offense change, truthful PARTIAL/UNCERTAIN classification); `core04_mixed_hit_ailment.xml` proves the mixed hit+ailment branch (correct `CombinedDPS` selection, no double counting, correct FULL/MEANINGFUL_UPGRADE). Only the skill-native-DoT branch (`DamageQuantity.SKILL_DOT`, a skill with its own `TotalDot`/`FullDotDPS` and no separate named ailment field) remains deferred. |
| P0 | **CONFIRMED, ACTIVE DEFECT (M1.1 weapon-swap slice).** For any build whose active item set has `useSecondWeaponSet="true"`, Item Check's candidate substitution writes into the PRIMARY `Weapon 1`/`Weapon 2` PoB slots — never the active `Weapon 1 Swap`/`Weapon 2 Swap` slots the player is actually using. A candidate cloned from the build's TRUE equipped weapon, with a `+500% increased Physical Damage` mod added, produces **exactly zero** measured offense change (real PoB run, `core04_weapon_swap.xml`): a confident `FULL`/`SIDEGRADE` result totally disconnected from the candidate's actual stats. Baseline identity/offense are unaffected (proven correct by a separate, real, PASSING regression) — only candidate substitution is broken. | **Not fixed.** Root cause is architectural: PoB's `itemsTab` holds four independent weapon-slot objects and `bridge.lua`'s `tx_begin`/slot resolution has no `useSecondWeaponSet`-aware redirection between them; `src/poe2value/items/slots.py`'s `ProductSlot.OFFHAND_2 → "Weapon 2 Swap"` mapping exists but has no caller anywhere and no corresponding entry in `bridge.lua`'s `EVALUABLE_SLOTS`, suggesting a prior, unfinished attempt at this exact feature. Pinned as `tests/integration/test_public_real_pob.py::test_weapon_swap_candidate_substitution_ignores_the_active_slot` (`xfail(strict=True)`) — deliberately NOT registered as passing coverage. Proposed remediation: a dedicated slice to (a) have `bridge.lua` detect the active item set's `useSecondWeaponSet` and redirect `"Weapon 1"`/`"Weapon 2"` slot reads/writes to the swap slots when active, (b) extend `EVALUABLE_SLOTS` accordingly, (c) wire up the already-declared but dormant `ProductSlot.OFFHAND_2` mapping end to end, (d) flip the `xfail` to a real assertion once fixed. |

Exact deferred items:

1. Add deterministic public coverage for display thresholds, recovery, stat-set/skill-part variants, and broader mixed-slot transactions.
2. Add worker-level transaction instrumentation only if the existing public batching and corrupt-restore recovery gates cease to cover a future worker change.
3. Add a public fixture for the skill-native-DoT branch (`DamageQuantity.SKILL_DOT`, e.g. a Bleed/Essence-Drain-style build with no separate "ailment" field). The mixed hit+ailment branch (`DamageQuantity.HIT_PLUS_AILMENT`) is now covered by `core04_mixed_hit_ailment.xml` (M1.1). The `useSecondWeaponSet="true"` Huntress/Ritualist Poisonburst Arrow character previously set aside during the DoT/ailment slice was reused for the M1.1 weapon-swap slice as `core04_weapon_swap.xml` — it turned out to be exactly the fixture needed to surface the P0 candidate-substitution defect above.
4. Fix the P0 weapon-swap candidate-substitution defect (see risk register) — dedicated remediation slice, out of scope for corpus-coverage work.
