# TRUST-01A — Equipability ("Can I actually equip this?")

A candidate the loaded character cannot wear is never an ordinary upgrade. Only PoB's own numbers are used;
nothing is estimated and there is no Python equipment simulator.

## Authoritative PoB fields

| Fact | PoB source | Bridge field |
|---|---|---|
| Character level | `build.characterLevel` | `raw.CharacterLevel` (`collect_metrics`) |
| Character Str/Dex/Int (candidate equipped) | `calcsTab.mainOutput.Str/Dex/Int` | `raw.Str/Dex/Int` |
| Candidate required level | `item.requirements.level` | `item.level_req` |
| Candidate required Str/Dex/Int | `item.requirements.strMod/dexMod/intMod` (after the item's own local requirement mods, `Item:BuildModList`) | `item.req_str/req_dex/req_int` |
| Post-swap build-wide requirement | `output.ReqStr/ReqDex/ReqInt` (highest requirement over equipped items + gems) | `raw.ReqStr/ReqDex/ReqInt` |

## Two separate questions

1. **Candidate-own** (`equipability.py`): can the candidate itself be worn? Level is compared with the
   loaded character level. Each attribute is compared with the character's attribute **with the candidate
   equipped** — PoB counts the item's own attribute bonuses toward its requirement, so comparing against the
   pre-swap value would give false failures. Guardrail `EQUIP_REQUIREMENT_NOT_MET`.
2. **Post-swap build** (`requirement_gates.attribute_requirement_warnings`, unchanged): the candidate is
   legal but replacing the current item leaves another equipped item/gem below its requirement.
   Guardrail `ATTRIBUTE_REQUIREMENT_LOST`.

When the candidate's own attribute failure already explains every `ATTRIBUTE_REQUIREMENT_LOST` attribute, only
`EQUIP_REQUIREMENT_NOT_MET` is applied (one canonical blocker).

## Baseline already invalid

`ATTRIBUTE_REQUIREMENT_LOST` still fires only when the candidate *worsens* a shortfall. A baseline deficit the
candidate does not worsen is not blamed on it. A candidate-own failure is still reported even when a larger
baseline deficit hides it inside `ReqStr` (the candidate does not change the highest requirement).

## UNKNOWN semantics

Each check is `PASS` / `FAIL` / `UNKNOWN`. A requirement or available value PoB did not report is `UNKNOWN`:
never a failure, never a pass, and it does not lower evaluation quality. Overall status is `NOT_EQUIPPABLE`
(any FAIL), else `PARTIAL` (any UNKNOWN), else `EQUIPPABLE`. A requirement of 0 is a `PASS`.

## Verdict / guardrail

`EQUIP_REQUIREMENT_NOT_MET` is a not-viable guardrail in `guardrails.GUARDRAIL_RULES` (same 25-point ceiling as
`ATTRIBUTE_REQUIREMENT_LOST`). `decide_verdict()` yields `NOT_VIABLE`; no new verdict, no score-band change. The
measured DPS/EHP deltas stay in the outcome for explanation.

## Presentation

* Guardrail reason (also the Why blocker and the compact row text), most important first, at most two:
  `Requires level 78 · Character is level 74` / `Requires 155 Strength · Character has 132`
  (level, then Strength, Dexterity, Intelligence).
* Compact tooltip: headline `NOT VIABLE`, row `Can't equip` + the reason. Only `EQUIP_REQUIREMENT_NOT_MET` and
  `ATTRIBUTE_REQUIREMENT_LOST` use "Can't equip"; main-skill / sustain blockers read `Not viable`.
* More Info: a `CAN'T EQUIP` section lists every verified failed check; `outcome.equipability` carries the structured
  checks (`kind`, `status`, `required`, `available`, `source`, `detail`).
* M2.3 Why: the blocker outranks all gains (existing blocker-first path).

## Not verifiable / not covered

* Global attribute-requirement modifiers (`GlobalAttributeRequirements`, e.g. "equipment and skill gems have X%
  increased attribute requirements") are applied by PoB only in the build-wide `ReqStr/Dex/Int`, not in the item's
  own `strMod`; a candidate-own check cannot see them (can only miss a failure, never invent one).
* Gem requirements and class/ascendancy restrictions are not item-equipability checks here.
* Slot/layout legality is PoB's (`weapon_layout`, `compatible_slots`); unchanged and not reimplemented.

## Tests

`tests/test_trust_01a_equipability.py` (unit: level/attribute pass/fail at the boundary, own-bonus counting,
UNKNOWN, multiple failures, baseline-not-worsened, masked candidate failure, post-swap preserved, canonical
blocker, large gain still NOT_VIABLE, Why / tooltip / More Info copy) and
`tests/integration/test_trust01a_equipability_real_pob.py` (real PoB, level-98 public Acolyte build: item
requirements and level read from PoB, level 99 amulet and a 605-Strength plate are `NOT_VIABLE`).
