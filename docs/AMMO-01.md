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

It affects every crossbow ammo gem — all 15 pair a `...AmmoPlayer` load effect with a fired sibling the same way.

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
  measured offense. This is deliberately *not* keyed on `base_deal_no_damage` alone: other effects carry that flag and
  PoB legitimately measures their damage (the Siege Ballista's Artillery effect in CORPUS-02F).
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

## Residual

* The effect catalog (`list_calculable_effects`, used by the contextual evaluation and the "same group" alternatives of
  the no-offense diagnostic) still lists the load action as a calculable effect with PoB's weapon-blind number. Selecting
  it there explicitly is a separate surface from Item Check.
