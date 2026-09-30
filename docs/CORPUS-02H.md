# CORPUS-02H - Energy Shield scaling

Goal: cover a build where Energy Shield does more than add defence: it changes another pool and, through it, damage.
The mechanic had to be supported by PoB before a build was accepted.

## 1. Result

| | Before (CORPUS-02G) | After |
| --- | --- | --- |
| Registered cases (all executed, all supported) | 164/164 | **173/173** |
| Classified verdict cases fully measured | 37/46 (80%) | **45/54 (83%)** |
| Verdict cases not yet classified | 64 | 64 |
| `es_scaling` archetype | NO COVERAGE | 9 cases, 8 FULLY_MEASURED |

Pass rate and functional coverage describe this corpus, not real PoE2 players. **No production defect was found in the
measurement path**; one scoring-policy observation is recorded in section 5. No engine, bridge or scoring code changed.

## 2. Which mechanic, and how it was chosen

Ordinary high-Energy-Shield builds do not scale offense: on every real build already in the corpus (including a 12,000 Energy
Shield Chaos Inoculation build), +500 maximum Energy Shield changed damage by exactly 0%. Those were rejected as
"ES-scaling" builds. PoB's passive data shows the mechanics that do connect Energy Shield to something else; the supported
one used here is the **Eldritch Battery** keystone ("Convert 100% of maximum Energy Shield to maximum Mana", "Mana Costs are
Doubled"). Builds with the keystone were found through poe.ninja's key-passive filter and ranked by PoB's own response to
+500 maximum Energy Shield (damage +2.6% to +20.2%).

`corpus02h_eldritch_battery_shaman.xml`: Druid/Shaman, level 100, poe.ninja ladder character; main skill Spark cast by a Spell
Totem (2.56M TotalDPS); Rathpith Globe: "6% increased Damage per 100 maximum Mana", "+3% Critical Hit Chance per 100 maximum
Mana"; helmet enchant "+1 maximum Mana per 2 Item Energy Shield on Equipped Helmet". Sanitization and SHA-256:
`docs/BUILD_CORPUS_SOURCES.md`. The saved main skill is used unchanged.

## 3. What PoB calculates

| Question | Finding |
| --- | --- |
| Where does Energy Shield go | PoB reports `EnergyShield` 0 and `Mana` 13,316: every point of Energy Shield, with its modifiers, is in the Mana pool. An item's Energy Shield never appears as an Energy Shield change. |
| Offense | Damage scales with Mana through the weapon's per-100-Mana modifiers: +200 flat Energy Shield on the helmet: Mana +16%, TotalDPS +37%, EHP +16%. Verified against fresh loads; ExileLens invents no Energy-Shield-to-damage rule and compares PoB's numbers only. |
| Independent vs dependent effects | Flat maximum Mana (no conversion) has the same effect through the same pool: +1,000 Mana on the helmet gave TotalDPS +43% with Energy Shield still 0. Life is a separate pool: swapping the helmet's increased Energy Shield for +300 Life raised Life 18% but cut damage 18% and EHP 8%. |
| Slot dependence | The same flat +200 Energy Shield added over three times as much Mana on the helmet (multiplied by the helmet's increased Energy Shield and its per-item-ES Mana enchant) as on the amulet. |
| Trade-offs | More Energy Shield with the Chaos Resistance cap lost: FULL, RES_CAP_LOST, never an upgrade. |
| Resource costs | With Mana Costs doubled the skill's Mana cost per second (15,332) is far above Mana regeneration (2,029) on this build; PoB reports it and it rises slightly with more Mana. ExileLens does not evaluate sustained casting (a Spell Totem build); it reports PoB's numbers. |

## 4. Verification

`tests/integration/test_corpus02h_energy_shield_mana.py` (9 tests): every measured candidate is compared with a fresh PoB load
of the same build with the candidate saved in its slot (`TotalDPS`, `Speed`, `Life`, `EnergyShield`, `Mana`, `ManaUnreserved`,
`ManaPerSecondCost`, `ManaRegenRecovery`, `TotalEHP`, `ChaosResist` to 1e-6). The Energy Shield output staying at exactly 0 while
Mana, damage and EHP move is asserted. The 02F/02G real-PoB suites are unaffected (no code changed).

## 5. Observation: a life gain turned a clear loss into SIDEGRADE (resolved by SCORING-01a)

Replacing the helmet's increased Energy Shield with +300 Life measures -17.9% damage and -8.3% EHP (both FULL, both
significant). At the time of CORPUS-02H the verdict was SIDEGRADE: the +18% Life Regen Recovery axis (37 -> 44 per second, +6.8/s,
about 0.37% of max Life per second) made the impact a TRADEOFF, and the policy scored any cross-axis conflict as the canonical
sidegrade, discarding the raw score of 6.9. The regression therefore asserted the measured numbers and only that the verdict was not
an upgrade. SCORING-01a (`docs/SCORING-01A.md`) makes recovery material only when it is also a real part of the Life pool, so this case
is now decided by the ordinary score (MEANINGFUL DOWNGRADE). The real-PoB assertion is tightened in SCORING-01b.

## 6. Not covered

- Only the Eldritch Battery mechanic. Other Energy-Shield-coupled mechanics that PoB models were not tested: crit chance per item
  Energy Shield on armour, Energy Shield added to Armour, ailment threshold from Energy Shield, Energy Shield recharge/recoup.
  Ordinary Energy Shield (no keystone) is covered only as defence by earlier corpus builds.
- The build's combat uptime, Mana sustain over time, and Spell Totem count are not measured (PoB reports one totem's damage; the
  `GroupTotemLimit` check from CORPUS-02F applies, and a totem-count mod did not change PoB's limit here).
- The saved amulet/helmet candidates are hand-written; no market items were used.
