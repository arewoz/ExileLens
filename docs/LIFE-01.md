# LIFE-01 — authentic Life-driven offense coverage

## Fixture and provenance

`fixtures/builds/public_corpus/life01_blood_mage_ember_fusillade.xml` is the decoded export (R4 removed only the per-item GGG `Unique ID:` lines and the importing character's hash; PoB's metrics, equipment and skill identity are unchanged) from [pobb.in/duLtV2Cf4TfL](https://pobb.in/duLtV2Cf4TfL), published as “PoE2 0.4 Early Endgame Blood Mage” by Upto64Bit. The saved build is a level-91 Witch/Blood Mage. Its selected PLAYER main skill is Ember Fusillade; its 0.4 tree allocates Gore Spike (node 52703).

## PoB authority and measured proof

The installed PoB2 v0.23.1 parser maps “per current Life” to `LifeUnreserved` (`Modules/ModParser.lua:1599`); `Data/ModCache.lua:1041` assigns Gore Spike's modifier to `CritMultiplier`; `Modules/CalcOffence.lua:3813-3861` consumes that modifier in output critical damage.

Using the existing Original Sin in Ring 2 plus only `+100 to maximum Life`, PoB reports:

| Axis | Baseline | Candidate |
| --- | ---: | ---: |
| Life / LifeUnreserved | 7,436 / 7,436 | 7,613 / 7,613 |
| CritMultiplier | 7.17 | 7.21 |
| Ember Fusillade CombinedDPS | 471,504.00 | 483,690.68 (+2.585%) |
| TotalEHP | 13,015.81 | 13,293.02 |

This is an authoritative PoB output comparison; ExileLens adds no Life or damage formula.

## ExileLens result

Before production changes, normal Item Check returned `FULL` and `MEANINGFUL_UPGRADE`, with measured positive OFFENSE and DEFENSE. No production fix was required. The regression asserts the same outcome and transaction restore (equipment, fingerprint, and metrics).

`life_scaling` now describes this Blood Mage/Gore Spike offense case, not ordinary Spark merely because Life changes defence.

Life costs, recovery, leech, recoup, recharge, regeneration, and overflow uptime remain separate work: this fixture proves the full-current-Life state calculated by PoB, not those mechanics' combat uptime.
