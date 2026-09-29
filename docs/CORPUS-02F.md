# CORPUS-02F - Mortar Cannon and Ballista

Goal: measure Item Check on authentic Mortar Cannon and Siege Ballista builds, find out what PoB's
`TotalDPS` / `CombinedDPS` mean for them, and fix what ExileLens got wrong without inventing any damage model.

## 1. Result

| | Before | After |
| --- | --- | --- |
| Registered cases (all executed, all supported) | 139/139 | **152/152** |
| Classified verdict cases fully measured | 22/28 (79%) | **28/37 (76%)** |
| Verdict cases not yet classified | 61 | 63 |

The percentage fell slightly because the new cases include honest partial results (below) that are classified but not
"fully measured". Registered pass rate (a correct refusal counts as supported) and functional coverage stay separate;
neither is a share of real PoE2 players.

New classified cases: 6 `FULLY_MEASURED` (Mortar offense up/down, cooldown recovery, defence-only, offense/defence
trade-off; Ballista weapon offense, Ballista defence ring), 1 `PARTIALLY_MEASURED` (ignite-only change), 2
`EXPECTED_UNCERTAINTY` (changed totem count on Mortar and on Ballista). Newly covered archetypes: Mortar Cannon
(cooldown-limited per-use attack fired by a totem) and Siege Ballista (`proxy_totem`, `ranged_attack`).

## 2. Builds and provenance

- `corpus02f_mortar_cannon_warbringer.xml`: Warrior/Warbringer, level 100, poe.ninja ladder character. Saved main group
  Mortar Cannon + Cluster Grenade; selected effect Cluster Grenade (unmodified). Of 16 Mortar builds examined, this and
  one other match the "26-29k TotalDPS / 91-105k CombinedDPS" pair noted in CORPUS-02E; both show the same behaviour.
- `corpus02f_ballista_warbringer.xml`: Warrior/Warbringer, level 97, dedicated Siege Ballista group (group 9). Its saved
  main skill is Explosive Grenade. Of the 27 Siege Ballista characters, this was the one with a meaningful calculation
  (others: 0-5k). **Test-only change**: the tests copy the build and set `mainSocketGroup` 7 -> 9 and that group's
  `mainActiveSkill`/`mainActiveSkillCalcs` 1 -> 2. The committed file is unmodified.

Sanitization (19 `Unique ID:` lines and the `<PlayerStat>` cache removed) and SHA-256s are in
`docs/BUILD_CORPUS_SOURCES.md`; both pass the public safety regression.

## 3. What PoB calculates

**Mortar Cannon.** The Mortar Cannon effect is the totem-summoning effect and deals no damage. The damaging effect is
Cluster Grenade, a `base_skill_show_average_damage_instead_of_dps` skill with a cooldown (6.67 s / 5.13 s):

- `CombinedDPS` = `AverageDamage` = damage **per use** (CalcOffence: for such skills `CombinedDPS` is `AverageDamage`, and
  ailment damage is only added to the `WithIgniteDPS` variants). It is not a rate.
- `TotalDPS` = `AverageDamage` x `Speed` (0.15-0.195 uses/s, cooldown-limited) x PoB's skill DPS multiplier (1.65 on both
  builds). It is the per-second rate, for **one** totem. So `TotalDPS` is *lower* than `CombinedDPS`; the roughly 4x gap
  is uses-per-second, not projectile count. Projectile count (4) is not multiplied in by ExileLens.
- `IgniteDPS` (a per-second stream, ~20% of the hit rate on the tested build) is a separate output.
- The number of totems (`ActiveTotemLimit` 4 on the summoning effect) is separate and is not in `TotalDPS`.

**Ballista.** Siege Ballista's own effect deals 0 damage and carries `ActiveTotemLimit`; the group's second effect,
Artillery, is a plain per-second skill (`TotalDPS = AverageDamage x Speed`, `CombinedDPS = TotalDPS`), again for one
ballista. A weapon with "+2 to maximum number of Summoned Ballista Totems" moves the summoning effect's limit 4 -> 2 and
leaves Artillery's damage exactly unchanged.

## 4. Defects found and fixes

1. **Per-use damage compared as a rate (production defect).** The per-use signature (`bridge.lua per_hit_combined_signature`
   and `resolve_primary_metric`) required `TotalDPS > CombinedDPS`, true only for fast skills. Cooldown-limited skills
   (Speed < 1) were scored on the per-use `CombinedDPS`, so cooldown recovery, and any attack-speed change, were invisible
   or misread (a +20% cooldown recovery ring gave an unchanged score; a ring trade could read as a downgrade while the
   real rate rose). Fix: the signature is `CombinedDPS == AverageDamage` and `TotalDPS` differs from it; the resolver then
   scores PoB's `TotalDPS`. Side effect, verified: `core04_melee_weapon` (Sunder, Speed 0.81) is also per-use; a jewel there
   that lowers attack speed no longer reads as a clear upgrade (`test_jewel_real_pob` expectation updated, with reason).
2. **Ignite dropped from the scored quantity.** With the rate scored, a per-use skill's ignite stream is not in `TotalDPS`.
   No new number is composed. If PoB's hit + DoT direction differs from the hit direction (or the hit is unchanged while
   DoT moves) the result is `PARTIAL` with `PER_USE_DOT_NOT_MEASURED`. Ignite chance doubling `IgniteDPS` with unchanged hit
   rate was FULL/SIDEGRADE before.
3. **Totem count change reported as measured.** A weapon removing `+2` ballista totems was FULL/SIDEGRADE. The bridge now
   exposes `GroupTotemLimit` (PoB's own `ActiveTotemLimit` of the main group's calculated totem skill, from `GlobalCache`,
   no extra recalculation); a change between baseline and candidate is `PARTIAL` with `TOTEM_LIMIT_CHANGED`. No damage is
   multiplied by the totem count.

## 5. Verification

`tests/integration/test_corpus02f_mortar_ballista.py` (14 tests). Every measured candidate is compared against a fresh PoB
load of the same build with the candidate saved in its slot (`TotalDPS`, `CombinedDPS`, `Speed`, `Life`, `TotalEHP`,
`IgniteDPS`, `GroupTotemLimit` equal to 1e-6). Existing real-PoB integration suites (206 tests) pass; the only expectation
changed is the Sunder jewel case above.

## 6. Not covered

- Ignite/DoT of a per-use skill is not scored as a rate (PoB provides no single rate figure for it); such changes are
  `PARTIAL`, not wrong.
- Total damage of a changed totem count is not measured (PoB reports one totem).
- Ballista coverage is one build with a test-selected effect; the saved-main Ballista case does not exist in the sampled
  ladder. Mortar and Ballista are not claimed as general totem/grenade coverage.
- The 1.65 DPS multiplier's source was not traced further; ExileLens uses PoB's value as reported.
