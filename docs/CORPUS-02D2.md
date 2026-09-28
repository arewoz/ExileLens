# CORPUS-02D2 — Voltaic Barrier

Branch `test/corpus-02d2-voltaic-barrier`, based on `origin/main` at `ea2b3ae`
(CORPUS-02D1, PR #48). Supported PoB 0.23.1.

**Result.** The exact community-reported build (`pobb.in/1PuQGhYCY9Fv`) was retrieved,
sanitized and committed. No ExileLens defect specific to Voltaic Barrier or weapon-set
interaction was confirmed. Two things are true and both are now proven with real-PoB
tests:

- **As PoB saved it** (`mainSocketGroup="3"`), the build's own main skill is
  **Virtuous Barrier** — a pure reservation/buff skill with zero calculated offense.
  Every weapon Item Check on this exact save state is correctly PARTIAL/UNCERTAIN,
  never a false verdict. This is a genuine PoB build-state characteristic — the
  player's last main-skill selection — not a defect.
- **With PoB's main skill re-pinned to Voltaic Barrier** — the skill the report
  names, a real weapon-scaling attack skill — Item Check is **FULL and correctly
  measured**, verified against independent fresh PoB reloads, deterministic across
  repeated evaluations, and restores exactly across this build's 47 weapon-set-
  conditional passive tree allocations (more than the existing weapon-swap fixture
  exercises).

Community regression matrix row 12: `MISSING_FIXTURE` → `COVERED`.

## 1. Acquiring the build

`docs/COMMUNITY_REGRESSION_MATRIX.md` row 12 and `docs/POB2_ENGINE_CONTRACT.md`
documented that no exact export of this report existed locally. The pobb.in link's
raw export endpoint (`https://pobb.in/1PuQGhYCY9Fv/raw`) returned a base64 string
(url-safe alphabet) of zlib-deflated PathOfBuilding2 XML — the same encoding PoB
itself uses for import/export codes. Decoding it (`base64.b64decode` with `-`/`_`
translated to `+`/`/`, then `zlib.decompress`) produced a valid, well-formed
`<PathOfBuilding2>` document that loads cleanly in the supported local PoB revision:
class Mercenary, ascendancy Gemling Legionnaire, level 91, two weapon sets
(`useSecondWeaponSet="false"`), 13 skill socket groups, 139 allocated passive nodes
including 47 weapon-set-conditional (`alloc_mode` 1/2) allocations. This is the exact
reported build; no substitute was used.

## 2. Investigation

### 2.1 Main-skill selection (the actual root of "everything is uncertain")

PoB's own `mainSocketGroup="3"` points at socket group 3, which carries the gem
"Virtuous Barrier" — a Gemling Legionnaire ascendancy-granted skill
(`skills["VirtuousBarrierPlayer"]` in PoB's `Data/Skills/other.lua`):
`skillTypes = { Buff, HasReservation, OngoingSkill, Persistent, ReserveInAllSets }`,
no `Attack`/`Damage` type at all. Loading the exact build reports
`CombinedDPS = 0`, `TotalDPS = 0` for this skill — genuinely, correctly zero. This is
not a calculation gap; the skill deals no damage.

**This is almost certainly the actual symptom behind the report.** A player's PoB
save records whichever socket group they last had selected as "main" in PoB's own
UI. If that happened to be a defensive buff (as it is in this exact export) rather
than the skill they actually wanted evaluated, every weapon Item Check will
correctly, truthfully decline to give a confident offense verdict — which looks,
from the outside, exactly like "everything is uncertain for my Voltaic Barrier
build". ExileLens reads whatever main skill PoB's save records; it has never
overridden a player's own PoB selection, and does not start doing so here.

Confirmed on the as-exported build with real Item Check:

- A crossbow upgrade candidate for the active weapon: `PARTIAL`/`UNCERTAIN` (a
  measured-zero substituted secondary component — "Crossbow Shot", a default/filler
  skill setup elsewhere in the build's gem list — stands in, correctly labelled,
  never presented as Virtuous Barrier's own damage).
- A life-focused ring candidate: `PARTIAL` overall, but `DEFENSE` is `MEASURED`/
  `POSITIVE` — the safe fallback machinery does not discard every axis just because
  offense is unmeasurable.
- Restore passes in every case.

### 2.2 Voltaic Barrier's actual calculated effect

Voltaic Barrier (`skills["VoltaicBarrierPlayer"]`, socket group 9 in this build) is a
real weapon-scaling attack skill: `skillTypes = { Attack, Area, Wall, Lightning,
UsableWhileMoving, Totemable }`, `active_skill_base_physical_damage_%_to_convert_to_lightning
= 100`, usable with any equipped weapon type including Crossbow (its `weaponTypes`
table lists every weapon class). With `mainSocketGroup` re-pinned to this group (an
edited copy of the same authentic build), PoB reports `CombinedDPS = TotalDPS =
2191.06` for the build's equipped crossbow — a real, non-zero, correctly-scaling
number.

Voltaic Barrier also has a hidden "inbuilt trigger", `VoltaicBarrierTriggeredChainLightningPlayer`
("Projectiles you fire through the wall become energised, discharge lightning on
Hit"). It is not a separate PoB socket group (no `<Skill>` entry exists for it) and
requires a cross-skill interaction (a *different* skill's projectile passing through
the barrier) that PoB does not model — the same class of "prohibited combat
derivation" (cross-skill trigger timing) `docs/POB_NATIVE_DAMAGE_POLICY.md` already
rules out. PoB's number for Voltaic Barrier is its own periodic wall damage only.
This is a genuine PoB calculation scope limitation, not something ExileLens can or
should approximate.

### 2.3 Candidate equipment substitution, active vs. inactive weapon sets

With Voltaic Barrier as main skill, a crossbow candidate submitted for "Weapon 1"
(the active physical slot, `useSecondWeaponSet="false"`) is measured correctly:
`FULL` / `MEANINGFUL_UPGRADE`, matching an independent fresh PoB reload exactly.

The build's inactive "Weapon 1 Swap" holds a different weapon (a two-handed mace,
Marohi Erqi). Submitting that exact item text as a candidate resolves **only**
against the active physical slot ("Weapon 1") — `compatible_slots` never offers
"Weapon 1 Swap". This matches `runtime/lua/bridge.lua`'s documented design
(`active_weapon_slot`, and the physical-slot helpers used only by the separate,
read-only Slice 3/4D contextual-diagnostic machinery, never by ordinary Item Check):
ordinary Item Check evaluates only the currently active loadout, by design, the same
scope every other weapon-swap fixture in this corpus already exercises.

**This is not a truthfulness defect.** The result correctly, honestly names
"Rampart Raptor" (the crossbow actually in "Weapon 1") as the item being replaced —
never silently or incorrectly claiming to replace the inactive mace. A player who
pastes an item they already own in their swap set, without saying so, gets an
honest, literal answer to "what if I equipped this now": nothing is misrepresented,
even though it does not (yet) offer a candidate check against the swap slot
specifically. This is a real, existing scope boundary, consistent with every other
weapon-swap regression already in the corpus (`docs/COMMUNITY_REGRESSION_MATRIX.md`
rows 1–2), not something introduced or found broken by this investigation.

### 2.4 Weapon-set-conditional passives and restore integrity

This build allocates 47 weapon-set-conditional passive nodes (`weapon_set_alloc`,
`alloc_mode` 1 or 2) — substantially more than `core04_weapon_swap.xml`. Two
consecutive Item Check evaluations produce identical results, and the restored build
equals an independent fresh reload exactly (every numeric field compared, none
differ) after a candidate transaction, including `TotalEHP` and `CombinedDPS`. No
leak, no drift, no stale conditional-passive state.

### 2.5 Baseline vs. candidate calculation contexts, evaluation quality

Every measured comparison above used the `MAP` context (the product default); no
context-specific behavior was implicated. `evaluation_quality`/`verdict` classification
was correct and consistent in every case checked: `FULL`/directional when PoB
measures real offense, `PARTIAL`/`UNCERTAIN` when it does not, and the specific
substituted-component labelling (never a bare, unexplained refusal) when a fallback
applies.

### 2.6 A related, unrelated finding (explicitly out of scope here)

While probing candidate substitution across both ring slots on the as-exported
(zero-offense) build, a substituted secondary component ("Crossbow Shot") was
measured for the Ring 1 candidate but reported fully `UNAVAILABLE` for the otherwise
identical Ring 2 candidate. Root cause: Ring 2's current item ("Corruption Spiral")
supplies a small, incidental "Adds Fire damage to Attacks" roll; removing it during
the Ring 2 candidate's own transaction drops Crossbow Shot's already-negligible
ignite chance to *exactly* zero (rather than a small nonzero fraction), which flips
`resolve_primary_metric`'s classification for that secondary skill from
`CombinedDPS`/`HIT_PLUS_AILMENT` to `TotalDPS`/`HIT_DPS` — a real semantic-field
change, which the existing CORE-01 offense-fallback-truthfulness guard (correctly,
by its own design) treats as "this component's identity changed, do not reuse it".

This is a genuine, narrow behavior of the pre-existing fallback-substitution system
(unrelated to Voltaic Barrier, weapon sets, or this report), triggered only when the
selected main skill has zero offense of its own and a substituted component's own
incidental, insignificant ailment chance crosses exactly to zero. It never produces a
false verdict (the safe outcome is simply a worse-but-still-truthful "unavailable"
rather than the better-but-still-truthful "measured-zero" fallback). It is preserved
untouched and not fixed here, consistent with staying in scope and preserving the
existing CORE-01 truthfulness guard; it is noted for a future, separately-scoped
ticket.

## 3. Implementation

**No production code was changed.** No confirmed defect specific to Voltaic Barrier
or weapon-set interaction was found; both investigated states (as-exported and
Voltaic-Barrier-as-main) already produce correct, truthful, and — where PoB provides
the information — fully measured results. This mirrors the outcome the CORPUS-02D1
follow-up review reached for its own four risk areas: investigation and regression
coverage without a required code change is itself a legitimate, reportable outcome
under this corpus's own methodology.

Two documentation-only corrections were made to reflect the newly available fixture:

- `docs/COMMUNITY_REGRESSION_MATRIX.md` row 12: `MISSING_FIXTURE` → `COVERED`.
- `tests/integration/test_contextual_diagnostic_real_pob.py`: the module comment
  claiming no exact community fixture exists was stale; corrected to point at the
  new fixture and explain why that separate diagnostic-chain test still uses
  `core04_weapon_swap.xml` (its own scope needs two *materially different* weapon
  sets; this build's Voltaic Barrier never crosses weapon sets at all).

## 4. Real-build verification

**Fixture:** `fixtures/builds/public_corpus/corpus02d2_voltaic_barrier.xml`
(manifest id `CORPUS02D2-VOLTAIC-BARRIER`), the exact retrieved build, sanitized per
`docs/BUILD_CORPUS_SOURCES.md`: 19 `Unique ID:` lines removed, the 101-line cached
`<PlayerStat>` block removed (display-only, never read back by PoB or ExileLens),
and the identifying `<Import lastLeague="..." lastRealm="..."
lastCharacterHash="...">` replaced with the minimal `<Import exportParty="false"/>`
every other corpus fixture uses. Nothing else changed. A fresh engine load before
and after sanitization produced identical `main_skill_identity`, `CombinedDPS`,
`TotalDPS` and `TotalEHP`. It passes the existing public-safety regression
(`test_selected_fixture_contains_no_private_path_or_identity_markers`).

An edited copy re-pinning `mainSocketGroup` to 9 (Voltaic Barrier) is used for the
Voltaic-Barrier-as-main cases — the same authentic build, same pattern
CORPUS-02D1 used for its "Arrow" stat-set variant, not a substitute build.

| Test | Result |
| --- | --- |
| As-exported main skill has no offense; weapon check truthfully uncertain | PARTIAL/UNCERTAIN, never a false verdict |
| As-exported: a defensive candidate still measures DEFENSE | PARTIAL overall, DEFENSE MEASURED/POSITIVE |
| Voltaic-Barrier-main: crossbow upgrade | FULL/MEANINGFUL_UPGRADE, matches fresh reload |
| Voltaic-Barrier-main: crossbow downgrade + amulet life upgrade | Both FULL, correct direction, match fresh reload |
| Repeated evaluation + restore (47 weapon-set-conditional nodes) | Identical repeats; restored == fresh reload exactly |
| Candidate targets only the active slot, truthfully labelled | `compatible_slots == {"Weapon 1"}`; FULL; baseline item correctly named |

All 6 real-PoB tests pass (`tests/integration/test_corpus02d2_voltaic_barrier.py`).

## 5. Functional coverage

New registry cases (`tests/corpus_coverage/registry.py`, `CORPUS_02D2_CASES`):

| Case | Functional measurement |
| --- | --- |
| VOLTAIC-BARRIER-AS-EXPORTED-UNCERTAIN | EXPECTED_UNCERTAINTY |
| VOLTAIC-BARRIER-AS-EXPORTED-DEFENSE-MEASURED | EXPECTED_UNCERTAINTY |
| VOLTAIC-BARRIER-MAIN-WEAPON-UPGRADE-FRESH-LOAD | FULLY_MEASURED |
| VOLTAIC-BARRIER-DOWNGRADE-AND-AMULET-UPGRADE | FULLY_MEASURED |
| VOLTAIC-BARRIER-REPEATED-EVALUATION-WEAPON-SET-PASSIVES | FULLY_MEASURED |
| VOLTAIC-BARRIER-CANDIDATE-ACTIVE-SLOT-SCOPE | FULLY_MEASURED |

Plus one identity case (`CORPUS02D2-VOLTAIC-BARRIER-IDENTITY`, not classified —
identity depth). 4 of 6 verdict-level cases are fully measured; the other 2 are the
correct, expected uncertainty on the as-exported zero-offense main skill — neither
counted as functional coverage, consistent with the CORPUS-02D1 methodology
(`docs/CORPUS_COVERAGE_METHODOLOGY.md`).

**Generated report (this branch):** headline **125/125 (100%)** supported (was
118/118 on `origin/main`); functional coverage **14/18 (78%)** fully measured (was
10/12) — the 4 new fully-measured cases are exactly the Voltaic-Barrier-as-main
cases above, and the 2 new expected-uncertain cases are exactly the as-exported
ones. 61 verdict-level cases outside this mechanic family remain explicitly
unclassified, unchanged.

## 6. Test results

- **Focused unit tests:** `tests/test_corpus_coverage_report.py` (22, including the
  functional-measurement drift guard against the new cases) and the manifest/safety
  tests for the new fixture — all passed.
- **Default unit suite** (`itemcheck and not integration`): 390 passed (unchanged
  from `origin/main`'s baseline; no production code touched).
- **Real-PoB gate:** run once via `scripts/generate_corpus_coverage_report.py` after
  implementation. Every suite passed, including the 6 new CORPUS-02D2 tests
  alongside every existing corpus suite (build_corpus 45; public_real_pob 26;
  weapon-set contexts 8; contextual placement 3; contextual diagnostics 2; effect
  enumeration 5; CORPUS-02A 6; CORPUS-02B 7; CORPUS-02C 37; CORPUS-02D1 7;
  CORPUS-02D2 6; policy units 51+11+33+16). Headline: 125/125 supported.

## 7. Remaining limitations

1. **Ordinary Item Check does not offer the inactive weapon-swap slot as a candidate
   target.** Confirmed truthful (never misrepresents which item it replaces) but a
   real scope boundary: a player checking an item they already own in their swap set
   gets an honest answer about their *active* slot, not the swap slot specifically.
   This is the existing, documented design of every weapon-swap fixture in this
   corpus, not something this investigation changed.
2. **Voltaic Barrier's "energised projectile" chain-lightning combo is not
   measured** — it requires a cross-skill trigger interaction PoB itself does not
   calculate (a genuine PoB scope limitation, not an ExileLens gap); PoB's number is
   the barrier's own periodic damage only.
3. **The as-exported build's main skill has no offense.** No amount of ExileLens
   work changes this: PoB correctly reports zero damage for a reservation/buff skill,
   and Item Check correctly, truthfully declines a confident verdict. This is
   inherent to the retrieved export, not fixable.
4. **A narrow, pre-existing fallback-substitution behavior** (§2.6) was observed but
   left untouched as out of scope: unrelated to Voltaic Barrier or weapon sets,
   never produces a false verdict, and touching it risks the CORE-01 truthfulness
   guard this task was told to preserve.
5. **No independent second Voltaic Barrier build** exists in the corpus to
   cross-check the mechanic against a different gear/tree shape; this is the only
   authentic build available for it.
