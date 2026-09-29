# CORPUS-02G - attribute stacking

Goal: real Item Check behaviour on builds whose damage and defence depend on accumulated Strength, Dexterity and
Intelligence, without assuming any universal attribute-to-damage rate.

## 1. Result

| | Before (CORPUS-02F) | After |
| --- | --- | --- |
| Registered cases (all executed, all supported) | 152/152 | **164/164** |
| Classified verdict cases fully measured | 28/37 (76%) | **37/46 (80%)** |
| Verdict cases not yet classified | 63 | 64 |
| `attribute_stacker` archetype | NO COVERAGE | 13 cases, 9 FULLY_MEASURED |

Pass rate and functional coverage stay separate and describe this corpus, not real PoE2 players. One production defect
was found and fixed (section 4). Nothing was added as coverage that is merely a correct refusal.

## 2. Builds and provenance

Found by ranking real ladder builds on PoB's own response to +100 of each attribute added to their equipped amulet
(never by build name), starting from PoB's unique-item data for "per N Strength/Dexterity/Intelligence" mods.

- `corpus02g_strength_oracle_brutus.xml`: Druid/Oracle, level 99, Chaos Inoculation. Dual wields Brutus' Lead Sprinkler
  ("5 to 10 Added Attack Fire Damage per 25 Strength"); PoB Strength about 1,939, main skill Molten Blast (3.4M
  CombinedDPS). +100 Strength: +19% damage. Other Sprinkler builds sampled showed +10% to +19%.
- `corpus02g_dex_int_acolyte_hand_of_wisdom.xml`: Monk/Acolyte of Chayula, level 98. Astramentis (all attributes) and Hand
  of Wisdom and Action ("1% increased Attack Speed per 20 Dexterity", "Adds 1 to 12 Lightning Damage to Attacks per 20
  Intelligence"); Str/Dex/Int 525/444/1477, main skill Fragments of the Past (110k). +100 Dexterity: +12%, +100
  Intelligence: +8%.

Sanitization and SHA-256s: `docs/BUILD_CORPUS_SOURCES.md`. Saved main skills are used unchanged.

## 3. Mechanics audit (measured in PoB)

| Question | Finding |
| --- | --- |
| Direct and derived attribute effects | Strength raises the Sprinkler's added fire per 25 Strength, and (via % increased Strength) Energy Shield and EHP; Dexterity gives attack speed per 20, Intelligence added lightning per 20; Life falls with lost Strength on the Dex/Int build. All come from one PoB calculation; ExileLens compares PoB's numbers only. |
| Rate | No universal rate: +100 Strength was worth +19%, +10% or 0% on different builds, and 0% on most non-stacking builds sampled (Mortar, Totem, Djinn, Stonefist). |
| Thresholds / nonlinearity | Damage rises in steps: on the Strength build three more Strength (+7 -> +10 on the amulet) crossing a per-25 boundary is worth about 5x the neighbouring three (+50k vs +10k CombinedDPS). Verified against fresh loads. |
| Smaller bonus, better result | An amulet with no flat Strength change but 70% increased Strength gave +62% damage; an amulet with +106 more flat Strength gave +20%. |
| Offense vs defence | A Strength gain that costs Cold Resistance below the cap is FULL, TRADEOFF, RES_CAP_LOST, never an upgrade. Fewer attributes plus 150 more Energy Shield still lowers both damage and EHP on the Dex/Int build. |
| Unmet requirements | PoB still applies an item whose Strength/Dexterity/Intelligence requirement is unmet (it only warns), so calculated numbers alone cannot show it. PoB reports the highest requirement as `ReqStr`/`ReqDex`/`ReqInt` (items and gems). |

Not modelled by PoB or ExileLens (not invented): the Sprinkler's "5% chance to Trigger Molten Shower per 25 Strength" (the
triggered damage is a separate skill; its chance changes nothing in the main skill's output, and the sampled group's own
Molten Shower damage is about 10-40% of the main skill's); PoB's Molten Shower groups are not part of the score.

## 4. Defect found and fixed

**The attribute requirement guardrail never ran on real PoB output.** `requirement_gates.attribute_requirement_warnings`
read `Str`/`StrReq`/`MissingStr`, but the bridge exported none of them, so `ATTRIBUTE_REQUIREMENT_LOST` could only fire in
synthetic unit tests. Fixes: the bridge now copies PoB's `Str`, `Dex`, `Int`, `ReqStr`, `ReqDex`, `ReqInt`; the gate reads
`Req<Attr>`; and a shortfall the build already had (same or larger than after the swap) is no longer reported as caused by
the candidate. Effects, both verified: the Strength build's amulet with -1700 Strength is NOT_VIABLE / ATTRIBUTE_REQUIREMENT_LOST;
and on the existing `core04_minion_actor` build a ring that costs 20 Dexterity (52 -> 32, below a 45 requirement) is now
NOT_VIABLE where it was previously SIDEGRADE (`test_corpus02b_minion_djinn` updated with that reason).

No metric-selection or scoring change was needed: the scored field is CombinedDPS / TotalDPS as before.

## 5. Verification

`tests/integration/test_corpus02g_attribute_stacking.py` (12 tests) checks every measured candidate against a fresh PoB load
(`TotalDPS`, `CombinedDPS`, `Speed`, `Life`, `EnergyShield`, `TotalEHP`, `Str`, `Dex`, `Int`, `ReqStr` to 1e-6);
`tests/test_corpus02g_requirement_gates.py` covers the gate's field names and the pre-existing-shortfall rule. The full
real-PoB suite (224 tests) passes.

## 6. Not covered

- The requirement case uses an extreme synthetic candidate (-1700 Strength); no authentic candidate reaches the
  requirement on these attribute-rich builds. Unmet requirement on gems is reported by PoB as the same maximum, so the
  source (item or gem) is not distinguished.
- Only Strength (Druid/Oracle) and Dexterity/Intelligence (Monk) stackers were tested; "universal stat-stacker support"
  is not claimed. The triggered Molten Shower and any other triggered effect scaled by attributes are unmeasured.
- Item Check evaluates amulet candidates here; weapon-swap and dual-wield candidates of the Sprinkler were probed (rolls of
  the per-25 line are measured) but not added as regression cases.
