# CORPUS-02E - proxy/totem coverage (Spell Totem)

Goal: turn the empty `proxy_totem` archetype into real, measured Item Check coverage on an
authentic build, without adding refusals as coverage and without a separate damage model.

## 1. Result

| | Before | After |
| --- | --- | --- |
| Registered cases (all executed, all supported) | 131/131 | **139/139** |
| Classified verdict cases fully measured | 16/22 (73%) | **22/28 (79%)** |
| Verdict cases not yet classified | 61 | 61 |
| `proxy_totem` archetype | NO COVERAGE | 8 cases, 6 FULLY_MEASURED |

The headline pass rate (a correct refusal counts as supported) stays separate from functional
coverage (only FULL-quality evaluations count). All 8 new cases pass; the 6 verdict cases are
classified `FULLY_MEASURED`. No case is `PARTIALLY_MEASURED`, `EXPECTED_UNCERTAINTY` or
`UNSUPPORTED_MECHANIC`: on this build nothing had to be refused, so no correct refusal is
counted as coverage.

**No production defect was found.** The unchanged pipeline already returns correct FULL verdicts
for this build; the work is the fixture, the verification against fresh PoB loads, and the
registry. No engine, bridge or scoring code changed.

## 2. The build and its provenance

`fixtures/builds/public_corpus/corpus02e_spell_totem_titan.xml`: Warrior / Titan, level 100, a public
poe.ninja ladder character (Runes of Aldur, 2026-09-29). Full provenance, the sanitization performed
(19 `Unique ID:` lines and the 102-line `<PlayerStat>` cache removed, nothing else) and the SHA-256
are in `docs/BUILD_CORPUS_SOURCES.md`. No account or character identifier is stored.

How it was found (never by build name): the main socket group of the public ladder characters of the
Warrior ascendancies was read from each character's PoB export, keeping totem, ballista and mortar
main skills. Other candidates found the same way, not fixtured: two Warbringer builds whose main skill
is Mortar Cannon (`TotalDPS` 26-29k, `CombinedDPS` 91-105k). A search for characters that merely
*use* Siege Ballista (27 characters) found none with it as the main skill; it is a secondary skill
there. The Spell Totem build was chosen because the totem, not the player, casts the damaging spell,
which is the proxy mechanic, and because its main group is genuinely the totem group.

Loaded in the supported PoB 0.23.1: class, ascendancy, main socket group 5 (Spell Totem, Grim
Pillars, Bitter Dead, plus supports) and the selected effect (Grim Pillars) are what PoB saved.

## 3. Mechanics audit (what PoB measures)

All of this was measured on the real build, not assumed.

| Question | Finding |
| --- | --- |
| Skill ownership | The selected effect is Grim Pillars, owner PLAYER, calculation mode DIRECT. PoB models the totem's spell on the player's main output. There is no separate totem actor and ExileLens has none (`DamageOwner.TOTEM` exists but PoB never produces it). |
| Meta skill and second spell | Spell Totem and Bitter Dead are calculated effects with zero damage of their own; only the selected effect is scored. |
| Which field | `TotalDPS` = per-cast damage x the totem's cast rate. `CombinedDPS` equals the per-cast damage here, so it is not the damage rate. ExileLens already selects `TotalDPS` (`HIT_DPS`); a regression test pins `TotalDPS = CombinedDPS x Speed`. |
| Item effects on totem damage | Spell skill levels raise damage (`+2` levels: +34% DPS; `-2`: -24%). Increased spell damage raises it. Verified against fresh loads. |
| Attack/cast speed | The player's Cast Speed reaches the totem's cast rate: `Speed` 3.286 -> 3.500 and DPS scales by exactly the same ratio; per-cast damage is unchanged. |
| Defence on the actual player | Life, Energy Shield, resistances and EHP are the player's; an ES-only item leaves the totem's damage and cast rate exactly unchanged and improves defence only. |
| Trade-offs | Offense +15% with Cold Resistance below the cap: RES_CAP_LOST guardrail, TRADEOFF pattern, `MINOR_DOWNGRADE`. Existing policy, unchanged. |
| Baseline/candidate contexts, restore, repeats | Identical results for repeated and interleaved evaluations; fingerprint and equipment return to baseline. |

Outside what PoB's `TotalDPS` says (not modelled by ExileLens, not invented):
- **Totem count, placement time and totem life.** `TotalDPS` is one totem's damage rate. The number of
  totems that can exist and how quickly they are placed are not in this figure.
- **Whether the totem survives, is in range, or is refreshed.** PoB does not calculate uptime.
- **Player DPS versus totem DPS.** They are different quantities. This build has no player-cast damage
  in its main group, so nothing here asserts they are interchangeable.

## 4. Verification against fresh PoB loads

`tests/integration/test_corpus02e_spell_totem.py` (7 tests). Candidates are hand-written rare
amulets in the equipped amulet's own shape (same implicits and shape, changed modifiers). For each,
the same build is saved with the candidate equipped in its slot and reloaded in a fresh PoB session;
`TotalDPS`, `Speed`, Energy Shield, Life, EHP and Cold Resistance must match the Item Check's measured
candidate to 1e-6.

| Case | Candidate change | Result |
| --- | --- | --- |
| Offense upgrade | +5 -> +7 spell skill levels | FULL, MEANINGFUL_UPGRADE (+34% DPS) |
| Offense downgrade | +5 -> +3 spell skill levels | FULL, MEANINGFUL_DOWNGRADE (-24% DPS) |
| Defence only | +100 Energy Shield | FULL, MINOR_UPGRADE; DPS and Speed exactly unchanged |
| Cast speed | +20% cast speed, other offense unchanged | FULL, MEANINGFUL_UPGRADE; DPS follows Speed exactly |
| Trade-off | +15% DPS, Cold Resistance 75 -> 64, EHP -4.7% | FULL, TRADEOFF, RES_CAP_LOST, MINOR_DOWNGRADE |
| Repeats and restore | interleaved evaluations | identical; fingerprint and equipment restored |

Plus an identity case pinning the selected effect, the zero-damage meta skill and the
`TotalDPS = CombinedDPS x Speed` semantics.

## 5. Not covered here

- Weapon candidates on this build: the equipped wand carries the `+3 spell levels` rune implicit and a
  Spellslinger grant, and hand-written wand candidates would mostly measure the hand-written item. Not
  claimed.
- Ballista and Mortar mains (found, not fixtured). They would need their own audit; Mortar's
  `TotalDPS`/`CombinedDPS` differ by about 4x (projectile count).
- Totem count and placement (above): outside PoB's `TotalDPS`.
- Stat-stacker and ES-scaling archetypes: out of scope for this milestone.

## 6. Files

- `fixtures/builds/public_corpus/corpus02e_spell_totem_titan.xml`, manifest entry `CORPUS02E-SPELL-TOTEM`
  (the manifest test now expects 14 scenarios).
- `tests/integration/test_corpus02e_spell_totem.py`, registry `CORPUS_02E_CASES` + identity case,
  suite added to `scripts/generate_corpus_coverage_report.py`, regenerated coverage report.
