# AMMO-01 — crossbow ammo "Load" effects are never the measured offense

## The failure

A tester copied a newly crafted crossbow and pressed Shift+C against a Witchhunter build whose main skill is the
**Permafrost Bolts** gem. The item was a much stronger weapon (in-game tooltip damage, +4 projectile skill levels, large
flat elemental damage, 5% of damage as extra elemental damage), yet ExileLens reported SIDEGRADE with
`CombinedDPS 332.5892380189 -> 332.5892380189` and a high-confidence `MEASURED_ZERO`.

Nothing was wrong with the replacement. The baseline slot held the previously equipped crossbow, the candidate was the
item PoB calculated in `Weapon 1`, and the build restored cleanly. The wrong thing was **which PoB effect was measured**.

## Root cause

A crossbow ammo gem grants two PoB effects: the fired skill (`PermafrostBoltsPlayer`, stat set "Projectile") and the
reload action (`PermafrostBoltsAmmoPlayer`, "Load Permafrost Bolts", stat set "Ammunition"). The gem declares
`grantedEffectDisplayOrder = { 1, 0 }`, so PoB lists them as `[fired, load]` and a saved `mainActiveSkill="2"` selects
the **load** action. This is trivially saved by accident (it is the second entry of the main-skill dropdown), and it was
the state of the tester's build.

The load effect carries `base_deal_no_damage` and PoB treats it as the parameter carrier of its fired sibling
(`calcCrossbowAmmoStats` copies its bolt count, reload speed and cost onto the fired skill). PoB still computes a number
for it: what the supports add to the action itself (Cold Attunement, Elemental Armament, ...). That number never reads the
weapon (weapon damage, weapon attack speed, local mods), and its speed is `1 / castTime 0.8 = 1.25` whatever the weapon is.
Only global modifiers move it, which is why the sockets-counted comparison showed 332.59 -> 357.33 (a rune's "5% of
damage as extra elemental") while the sockets-ignored comparison collapsed to exactly 332.5892380189 on both sides.

ExileLens read `CombinedDPS` of that effect with HIGH confidence, so the weapon-blind figure became a measured zero.

| | CombinedDPS baseline | candidate | verdict |
| --- | --- | --- | --- |
| load action (as saved; sockets ignored) | 332.589 | 332.589 | `NO_CHANGE` / SIDEGRADE (false) |
| fired Permafrost Bolts (sockets ignored) | 2570.10 | 3270.42 | `OFFENSE_UPGRADE` |

(Recomputed on PoB 0.23.1; the tests pin relations, not these figures.)

It affects every crossbow ammo gem. The first version of this document said 15; the machine inventory in the follow-up
validation below found **17** (the initial hand search missed Armour Piercing Rounds and the basic Crossbow Shot gem,
whose load effect is "Unload"). All 17 pair one load effect with one fired sibling the same way.

## Fix

* `runtime/lua/bridge.lua` — `settle_main_effect()` runs after a fresh build load and after a loadout / item-set switch.
  If the main group's selected effect is a crossbow ammo load action (`SkillType.CrossbowAmmoSkill` **and**
  `base_deal_no_damage`), the main effect is resolved to the fired sibling of the **same gem instance** using PoB's own
  pairing rule (`CrossbowSkill` and not `CrossbowAmmoSkill`). Anything ambiguous is left alone. Only the in-memory build
  changes (never the file), snapshots and restores start from the settled state, and the redirect is exposed on the main
  skill identity as `effect_redirect` (reason, from/to skill id, name and stat set). Identities also carry
  `ammo_load_effect`.
* `items/primary_metric.py` — if a load action is still the selected effect (no unambiguous sibling), the primary metric
  is `UNRESOLVED` / low confidence ("deals no damage; PoB's figures for it do not measure the fired skill") instead of a
  measured offense. The redirect itself is ammo-only (it needs PoB's own load/fired pairing); the *refusal* is the
  generic damage-target rule below.
* `items/diagnostics.py` — the export now shows `effect_redirect` / `ammo_load_effect` in the skill identities and a
  `replacement_slot_state` block: for the replacement slot, the item in the baseline calculation and in the candidate
  calculation (name, item id, text hash only) and whether the candidate item was actually a different item in the calc.

Direct candidate-vs-equipped PoB evaluation is untouched: no damage is derived outside PoB, there is no second scoring
path, and no truthfulness or supportability gate was relaxed.

## Regression coverage

* `fixtures/builds/public_corpus/ammo01_permafrost_bolts_witchhunter.xml` — the tester's public Maxroll export, sanitized
  per `docs/BUILD_CORPUS_SOURCES.md`, saved effect left as the tester had it. Manifest id
  `AMMO01-PERMAFROST-BOLTS-WITCHHUNTER`.
* `tests/integration/test_ammo01_permafrost_bolts_weapon.py` (real PoB): the saved load selection resolves to the fired
  effect and is disclosed; the tester's crossbow is measured on the fired skill in both frames, really replaces
  `Weapon 1`, is not a `MEASURED_ZERO`, with sockets ignored and counted; the redirected result equals a temporary copy of
  the build that selects the fired effect in the file itself (independent gold standard); the build fingerprint and
  metrics are restored.
* `tests/test_ammo01_ammo_load_effect.py` (no PoB): the unresolved-load guard, its specificity, and the diagnostics block.

## Why the corpus did not catch it

No fixture had a crossbow ammo skill, and every existing real-PoB weapon case used a main effect that does read the
weapon. The checks that exist on a comparison (semantic identity, metric identity, restore, fingerprints) all passed
because both frames measured the *same* wrong effect consistently; "unchanged" is only suspicious when the effect is known
not to deal damage, which is exactly the PoB semantic this fix encodes.

## Follow-up validation (broad semantic pass)

Evidence: `docs/AMMO-01-GEM-EFFECT-AUDIT.md` (generated by `scripts/audit_gem_effects.py` from the local PoB runtime; no
skill-name list anywhere). Read-only bridge method `describe_gem_effects` exposes PoB's loaded gem/skill data.

**Ammo family.** 17 gems grant a `CrossbowAmmoSkill` effect; all 17 map deterministically (one load, one fired candidate,
fired = effect 1, load = effect 2). Every mapping is checked live against the real resolver (load saved -> fired effect
measured and disclosed; fired saved -> no redirect), scoped to the same gem instance (two ammo gems in one group never
cross), and against PoB itself for weapon sensitivity: ExileLens equals PoB with the fired effect selected for all 17, and
every perturbation (flat elemental damage, local attack speed, +skill levels) moved every skill. Unusual structure that the
contract covers without extra fixtures: ten fired effects have two stat sets (stat set identity is preserved), Plasma Blast
carries `channelRelease`, Requiem's load stat set is "Compose Requiem", and Crossbow Shot's "Unload" is a hidden effect with
no display-order entry.

**Non-ammo multi-effect gems (96 audited with the ammo gems, 6 real build contexts).** Classes A 44 / B 49 / D 3 / C 0 / E 0.
Only the 17 ammo load actions and one non-ammo effect reported weapon-dependent offense for a declared non-damaging effect:

* **Hollow Form** (`MetaHollowFormPlayer`: `Attack`, `Melee`, `Meta`, `base_deal_no_damage`, no damage flag) reports 52 or
  215 CombinedDPS depending on the equipped weapon (zero with a crossbow, bow or caster build). It has no fired sibling to
  redirect to (it is a meta host), so it is refused, not redirected.
* Three families (Ancestral Cry, Apocalypse, Pounce) have a declared non-damaging effect beside several damage-capable
  siblings. Nothing can be paired deterministically, so no redirect exists; PoB reports no offense for the non-damaging
  effect, so the existing no-offense diagnostic already applies (class D = needs dedicated mechanics if a future resolver
  is wanted).
* The Siege Ballista placement effect (`SiegeBallistaPlayer`) is declared non-damaging and reports no offense; CORPUS-02F
  measures its fired projectile effect ("Artillery"), which is a damage target. An earlier note in this file called that
  Artillery effect itself `base_deal_no_damage`; it is the *placement* sibling that carries the flag.

**Damage-target rule (single source: the bridge).** An effect is *not* a damage target when it is an ammo load action, or
when PoB's data declares `base_deal_no_damage` for its selected stat set and the stat set has no damage-bearing flag (hit,
dot, attack, spell, minion) and no minion actor is selected. It is published on identities and on every effect reference
(`damage_target`, `damage_target_reason`: `AMMO_LOAD_DEALS_NO_DAMAGE` / `DECLARES_NO_DAMAGE`). `base_deal_no_damage` alone is
never enough: a damage flag keeps an effect measurable. The primary-metric resolver refuses (`UNRESOLVED`, low confidence)
only when a non-target effect has a *nonzero* PoB figure; a genuine zero keeps its existing no-offense meaning.

Stronger invariant, as far as current metadata supports it: *a primary offense is high-confidence only if the selected
effect is a damage target*. That is what the rule enforces today. It cannot be stated positively ("this effect is
damage-bearing") because PoB data has no such capability bit; the audit test is the tripwire that a PoB update which
introduces a new phantom fails loudly instead of shipping a confident wrong answer.

**`list_calculable_effects` contract.** The catalog consumers are the main-skill no-offense diagnostic (same-group
alternatives), the contextual diagnostic / evidence chain (explicit caller-supplied references) and native component
discovery. `calculable` keeps meaning "PoB produced numbers"; it was never "a legitimate damage target". Rather than
changing it, every row's `reference` now carries `damage_target` / `damage_target_reason`. Code that *chooses* a damage
effect honors it: same-group alternatives skip non-targets, native discovery refuses through the resolver, and
`require_damage_target(reference)` (raises `NotADamageTarget`) is the one call any future effect-selection feature must make.
The contextual diagnostic / evidence chain is deliberately exempt: it measures every effect of a build to judge
completeness against the full catalog (a non-damage effect is a legitimate observation there), so it carries the flag on each
observation instead of refusing. Plain reads of a non-target effect remain possible for diagnostics and carry the flag.

**State boundaries.** The resolver runs after a fresh build load and after loadout / item-set switches (the only
transitions that can change the selected effect). Redirects are keyed to the PoB group table, so they never leak across
builds, revisions or loadouts, and restore returns to the settled state. Only the *main* group is settled: PoB's own
FullDPS ignores the load action of other groups (verified), and native discovery refuses a load effect through the same
rule. Known cosmetic gap: the `full_dps_skills` display list names such a group's selected effect ("Load ...").

## Residual

* `full_dps_skills` (display names only) still names a non-main FullDPS group by its saved effect.
* Class D families (a declared non-damaging effect beside several damage-capable siblings) would need dedicated mechanics
  to be redirected; today they are refused/diagnosed, not guessed.
