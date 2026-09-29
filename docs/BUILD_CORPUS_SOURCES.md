# Public Build Corpus and real-PoB validation assets

## Purpose

This repository includes a deliberately small, deterministic regression corpus for
the Item Check engine. It validates that a supported local Path of Building 2 runtime
can load representative player, minion, and staged-skill builds from fixtures checked
into this repository. The strategic suite additionally validates ring replacement,
ring trade-off handling, an explicit empty slot, bow/quiver behavior, restore recovery,
and one batched candidate evaluation.

The corpus is a regression gate, not a build downloader or a live market tool. It does
not need network access, a game login, or any data outside this checkout and the local
PoB2 runtime.

## Fixture inventory

| Fixture | Coverage |
| --- | --- |
| `fixtures/builds/core04_player_ring.xml` | Player Spark context; Ring 1/Ring 2 replacement, trade-off, empty Ring 2 mutation, restore recovery, and batching. Its equipped two-handed Voltaic Staff (empty offhand) plus its own pooled Focus item are also (M1.2) the corpus's invalid-offhand-combination case: a Focus candidate against a two-handed-weapon build is correctly refused, never forced into an illegal slot. |
| `fixtures/builds/public_corpus/core04_bow_quiver.xml` | Player Ice Shot with a bow/quiver equipment layout. |
| `fixtures/builds/public_corpus/core04_minion_actor.xml` | Summon Infernal Hound with minion-owned primary output. |
| `fixtures/builds/public_corpus/core04_stage_context.xml` | Flameblast channel-release stage context. |
| `fixtures/builds/public_corpus/core04_melee_weapon.xml` | Warrior/Warbringer Sunder with a two-handed mace; melee weapon replacement semantics. |
| `fixtures/builds/public_corpus/core04_onehand_weapon.xml` | Warrior/Titan Shield Wall with a one-hand mace + tower shield; one-hand weapon replacement, including the `AMBIGUOUS_WEAPON_LAYOUT` multi-slot case, and (M1.2) real Shield candidate replacement. |
| `fixtures/builds/public_corpus/core04_poison_ailment.xml` | Huntress/Ritualist Poisonburst Arrow; ailment-dominant (poison) primary offense selection. |
| `fixtures/builds/public_corpus/core04_mixed_hit_ailment.xml` | Witch/Infernalist Comet (Cast on Elemental Ailment); mixed hit+ignite (~59%/41%) `CombinedDPS` offense selection. The candidate in this fixture's test is the build's own equipped Focus (Weapon 2) -- this is also this corpus's real-PoB evidence for Focus offhand support (M1.2), promoted from already-proven behavior rather than re-fixtured. |
| `fixtures/builds/public_corpus/core04_weapon_swap.xml` | Huntress/Ritualist Poisonburst Arrow with an active `useSecondWeaponSet="true"` item set; active-second-weapon-set identity, baseline, and candidate-substitution correctness (M1.1, weapon half) and (M1.2) offhand-half candidate substitution: a Quiver candidate against the ACTIVE `Weapon 2 Swap` item, proving the same `active_weapon_slot` bridge translation covers the offhand case with no separate mapper. Originally surfaced a confirmed Item Check candidate-substitution defect for this configuration, since fixed — see `docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md` risk register. |
| `fixtures/builds/public_corpus/core04_skill_native_dot.xml` | Monk/Acolyte of Chayula "Profane Ritual" (triggered by Cast on Minion Death); zero hit DPS, zero named-ailment DPS — skill-native-DoT (`DamageQuantity.SKILL_DOT`, PoB's own `TotalDot`) primary offense selection. |
| `fixtures/builds/public_corpus/corpus02_giants_blood_shield.xml` | Mercenary/Gemling Legionnaire Supercharged Slam wielding a two-hand mace *and* a tower shield (Giant's Blood keystone); the shield is Chernobog's Pillar (fire damage per block chance, which also makes the build ignite). CORPUS-02A: regression for the community `get_tree_snapshot` worker failure (its tree contains the non-ASCII passive "The Mórrigan's Guidance"), two-hand candidates PoB keeps beside the shield, a two-hander PoB does not (shield cleared and disclosed), and a unique-shield replacement whose damage semantics change (truthfully UNCERTAIN). See `docs/CORPUS-02A.md`. |
| `fixtures/builds/public_corpus/corpus02b_varashta_djinn.xml` | Sorceress/Disciple of Varashta, level 100, with all three ascendancy-granted Djinns (Navira, the Last Mirage as main skill; Ruzhan and Kelari as additional socket groups) plus skeletal minions, a spectre and wolves. CORPUS-02B: minion-owned verdicts on an ascendancy-granted actor, complete Djinn damage components in the advanced view, and the Command-as-main-skill UNCERTAIN variant. A public ladder build, **not** the community Djinn report's build. See `docs/CORPUS-02B.md`. |
| `fixtures/builds/public_corpus/corpus02c_stonefist_martial_artist.xml` | Monk/Martial Artist (level 100) Twister with **Way of the Stonefist** allocated; its export already carries the equipped gloves transformed ("Runeforged Fists of Stone" with transformed modifiers). CORPUS-02C: ordinary glove candidates are transformed in memory into the Fists of Stone item the character equips and measured by PoB (exact or across the independently rolled transformed range), the exported gloves are never transformed twice, and other slots stay measured. See `docs/CORPUS-02C.md`. |
| `fixtures/builds/public_corpus/corpus02e_spell_totem_titan.xml` | Warrior/Titan (level 100) whose selected socket group is the **Spell Totem** meta skill; the totem casts Grim Pillars. CORPUS-02E: the first proxy/totem build. PoB calculates the totem's per-cast damage and cast rate on the player's main output (`TotalDPS` = per-cast damage x cast rate; `CombinedDPS` is the per-cast damage), and player defences separately. Candidate amulets get FULL verdicts checked against fresh PoB loads. See `docs/CORPUS-02E.md`. |
| `fixtures/builds/public_corpus/corpus02f_mortar_cannon_warbringer.xml` | Warrior/Warbringer (level 100) whose main group is **Mortar Cannon** + Cluster Grenade; the selected effect is Cluster Grenade, a per-use (show average) attack limited by its cooldown. CORPUS-02F: PoB's `CombinedDPS` is the per-use average, `TotalDPS` the per-second rate for one totem, and the totem limit is a separate output. See `docs/CORPUS-02F.md`. |
| `fixtures/builds/public_corpus/corpus02f_ballista_warbringer.xml` | Warrior/Warbringer (level 97) whose saved main skill is Explosive Grenade, with a dedicated **Siege Ballista** group (socket group 9) whose second effect, Artillery, is the ballista's damage. CORPUS-02F: the tests select that effect on a temporary copy; the committed file keeps the saved selection. See `docs/CORPUS-02F.md`. |
| `fixtures/builds/public_corpus/corpus02g_strength_oracle_brutus.xml` | Druid/Oracle (level 99, Chaos Inoculation) dual wielding Brutus' Lead Sprinkler ("Added Attack Fire Damage per 25 Strength") with about 1,900 Strength; main skill Molten Blast. CORPUS-02G: the Strength stacker. See `docs/CORPUS-02G.md`. |
| `fixtures/builds/public_corpus/corpus02g_dex_int_acolyte_hand_of_wisdom.xml` | Monk/Acolyte of Chayula (level 98) with Astramentis and Hand of Wisdom and Action (attack speed per 20 Dexterity, added lightning damage per 20 Intelligence); main skill Fragments of the Past. CORPUS-02G: the Dexterity/Intelligence stacker. See `docs/CORPUS-02G.md`. |
| `fixtures/items/core04_*.txt` | Deterministic ring candidates used by the strategic suite. |

`fixtures/builds/public_corpus/manifest.json` is the authoritative corpus manifest
(18 scenarios: 9 from M1.1, plus the CORPUS-02A Giant's Blood, CORPUS-02B Varashta Djinn, CORPUS-02C Stonefist, CORPUS-02D2 Voltaic Barrier, CORPUS-02E Spell Totem, CORPUS-02F Mortar Cannon and Ballista, and CORPUS-02G Strength and Dexterity/Intelligence stacker builds). It contains repository-relative paths and expected semantic
identity, not captured output snapshots.

## Provenance and sanitization

The `core04_bow_quiver`, `core04_minion_actor`, `core04_stage_context`, and
`core04_player_ring` fixtures were selected from a prior local development validation
corpus as calculation inputs only.

`core04_melee_weapon.xml`, `core04_onehand_weapon.xml`, `core04_poison_ailment.xml`,
`core04_mixed_hit_ailment.xml`, `core04_weapon_swap.xml`, and
`core04_skill_native_dot.xml` (added for M1.1) were each captured from a real,
publicly listed character build on poe.ninja (Runes of Aldur league) via poe.ninja's
own `.../api/builds/.../character?...` endpoint, which returns the same
`pathOfBuildingExport` string as the page's "Import Code for Path of Building" field
— the same export a player would paste into PoB themselves. **Fetch the JSON API
directly rather than hand-copying the on-page import-code text field**: an earlier
hand-copy of this ~13,000-character string (before this endpoint was identified)
silently corrupted two words inside unrelated item mod text — caught and fixed during
the one-hand-weapon slice by re-fetching and byte-comparing against the committed
fixture. `core04_poison_ailment.xml` and `core04_mixed_hit_ailment.xml` were each
found by querying poe.ninja's per-character API directly for dozens of candidate
accounts across several ascendancies and comparing their raw `PlayerStat`
`TotalDPS`/`PoisonDPS`/`IgniteDPS`/`BleedDPS` values (and, for the latter,
`<ItemSet useSecondWeaponSet="...">` to exclude active-weapon-swap builds) — never by
guessing a promising build from its name or popularity. `core04_weapon_swap.xml` is
the exact `useSecondWeaponSet="true"` character found and deliberately excluded
during that search, refetched and reused for the M1.1 weapon-swap slice specifically
because its two weapon sets are materially different (a spear+shield primary set vs.
a bow+quiver active/swap set matching its actual arrow skill) rather than
near-equivalent. `core04_skill_native_dot.xml` was found the same way: by querying
poe.ninja per-character data across several DoT-flavored ascendancies (Witch/Blood
Mage was scanned and rejected — its cached stats stay hit-focused, `TotalDot` always
0) until a character with `TotalDPS == 0`, `TotalDot > 0`, and no named-ailment field
was found (Monk/Acolyte of Chayula, "Profane Ritual"), then re-verified fresh against
the real local engine before use — never selected from the skill's name or community
reputation. These six fixtures had poe.ninja's cached `<PlayerStat>` display block
removed before publication (not part of the PoB build definition; the engine
recomputes all stats fresh on load regardless). No account name, character name, or
profile identifier is present in the PoB import code itself or in any checked-in
fixture.

**Correction (CORPUS-02A cleanup).** This section previously also stated that every
per-item `Unique ID: <hash>` line (GGG-generated identifiers tied to a real player's
specific item drops) had been removed. That was not true: all nine `core04_*.xml`
files in `fixtures/builds/public_corpus/` still carried them (220 lines in total,
20-28 per fixture). They were removed in the CORPUS-02A cleanup commit by deleting
only those lines, with no other byte changed. A real-engine before/after comparison
of all nine fixtures showed identical PoB metrics, main-skill identity,
class/ascendancy, allocated passives, jewels, and equipped items (item text minus
the removed line). Only the equipment-derived fingerprint hash changes, because it
covers raw item text. No code reads `Unique ID`. The public safety regression now
rejects any fixture containing a `Unique ID:` line
(`test_selected_fixture_contains_no_private_path_or_identity_markers`).
`core04_player_ring.xml` never had them.

`corpus02_giants_blood_shield.xml` (CORPUS-02A) is a community-supplied export: a Reddit tester reported that
ExileLens failed on their public poe.ninja PoE2 character, and the maintainer supplied a sanitized PoB2 XML
export of it. The committed fixture is byte-identical to that supplied file (SHA-256
`664f7d7db5c704906a4eab97ca17913e125d8685dc62ed458fd1eeef125ef1b9`, LF line endings). It was re-screened before
commit: no `Unique ID:` lines, no `<PlayerStat>` block, no account/character name or profile link (only the
standard passive-tree `<URL>` every corpus fixture keeps), and it passes the public safety regression. The
character's live online state may have changed since the export and is intentionally not used; every figure
in its tests is recomputed by a local PoB2 engine from this file. The account/character identifiers from the
original report are not recorded in the repository.

`corpus02b_varashta_djinn.xml` (CORPUS-02B) comes from the predecessor development repository's Build Corpus V1
(case C08, acquired 2026-09-12). It is a representative, mature public character from the poe.ninja Runes of Aldur
ladder (PoE2 0.5.5 Forbidden Rites, level 100, not rank 1), captured through poe.ninja's browser-visible "Copy PoB code"
surface; that repository deliberately did not retain the character permalink. Before commit it was re-sanitized with this
corpus's rules. 19 `Unique ID:` lines and poe.ninja's 100-line `<PlayerStat>` cache were removed; they had survived the
earlier acquisition despite its documentation. Nothing else changed, and the build definition is untouched. It passes
the public safety regression and contains no account/character name, notes, or links other than the standard
passive-tree `<URL>`. It is **not** the build from the community report of Djinn builds being UNCERTAIN (that export
was never obtained). It is used only as real evidence of how Item Check handles the same mechanic.

`corpus02c_stonefist_martial_artist.xml` (CORPUS-02C) comes from the same predecessor Build Corpus V1 (case C01,
acquired 2026-09-12): a representative level-100 public character from the poe.ninja Runes of Aldur ladder (PoE2 0.5.5
Forbidden Rites), captured through poe.ninja's "Copy PoB code" surface, with no character permalink retained. It was
re-sanitized with this corpus's rules before commit. 21 `Unique ID:` lines and poe.ninja's 108-line `<PlayerStat>`
cache were removed, and nothing else changed. It passes the public safety regression. It was selected because it
allocates Way of the Stonefist (passive node 39595), found by scanning every available real fixture for that node,
not by build name.

`corpus02e_spell_totem_titan.xml` (CORPUS-02E) was found on 2026-09-29 by reading the main socket group of the
public Runes of Aldur ladder characters of the Warrior ascendancies through poe.ninja's own per-character API
(the `pathOfBuildingExport` string), keeping those whose main group is a totem, ballista or mortar skill. It is a
mature level-100 Titan; poe.ninja's "Copy PoB code" export was used unchanged apart from sanitization, and no
character permalink, account or character name was retained anywhere in the repository. Sanitization removed 19
`Unique ID:` lines and poe.ninja's 102-line `<PlayerStat>` cache (121 lines in total) and changed nothing else. A
real-engine comparison of the raw export and the committed fixture gave identical `TotalDPS`, `CombinedDPS`, Life,
Energy Shield, EHP and Speed. Committed SHA-256:
`6a7a3dc85c0e09c84de1cd929e66a50f5a2e0f7518da66e752decf42925ea9fb` (LF line endings). It passes the public safety
regression and contains only the standard passive-tree `<URL>`. Its selected effect (Grim Pillars, socket group 5,
effect 2) is the state PoB saved, not a selection made by ExileLens.

`corpus02f_mortar_cannon_warbringer.xml` and `corpus02f_ballista_warbringer.xml` (CORPUS-02F) were found on
2026-09-29 through poe.ninja's own build search for the Runes of Aldur ladder (skill filters Mortar Cannon and
Siege Ballista) and its per-character API (the `pathOfBuildingExport` string); the Mortar Cannon build was
selected from Warbringer characters whose saved main group is Mortar Cannon, the Ballista build from the 27
characters carrying Siege Ballista (none had it as the saved main skill). poe.ninja's "Copy PoB code" export was
used unchanged apart from sanitization, and no character permalink, account or character name was retained anywhere
in the repository. Sanitization removed the 19 `Unique ID:` lines and poe.ninja's `<PlayerStat>` cache (107 lines
for the Mortar build, 108 for the Ballista build) and changed nothing else. Both contain only the standard
passive-tree `<URL>` and an empty `<Notes>`. Committed SHA-256 (LF line endings): Mortar
`8b4f540b1e6bbacbd2551246d4c7c3176a1fde0474a41d7d68f017de15fadad2`, Ballista
`c46e5e3fb3afd7738a3403f4412af3f54dd2175be0402a421fc546946fe80ef0`. The Mortar build's selected effect is the state PoB
saved. The Ballista build's saved main skill is Explosive Grenade: the tests select the Siege Ballista group's
Artillery effect on a temporary copy (`mainSocketGroup` 7 -> 9 and that group's `mainActiveSkill` /
`mainActiveSkillCalcs` 1 -> 2) and nothing else is changed; the committed file is unmodified.

`corpus02g_strength_oracle_brutus.xml` and `corpus02g_dex_int_acolyte_hand_of_wisdom.xml` (CORPUS-02G) were found on
2026-09-29 through poe.ninja's own build search for the Runes of Aldur ladder (unique item filters Brutus' Lead
Sprinkler and Pillar of the Caged God; PoB's own unique-item data names the per-Strength/Dexterity/Intelligence mods)
and its per-character API (the `pathOfBuildingExport` string). Candidate builds were ranked by PoB's response to +100
of each attribute on their own equipped amulet, never by name. The export was used unchanged apart from sanitization;
no character permalink, account or character name was retained. Sanitization removed the `Unique ID:` lines (31 and
26) and poe.ninja's `<PlayerStat>` cache (109 and 105 lines) and changed nothing else; both contain only the standard
passive-tree `<URL>` and an empty `<Notes>`. Committed SHA-256 (LF line endings): Strength build
`343fc6c6da4903b800917eb008b62b2f5fb8e4e302a1987f956b20e5eb51c361`, Dexterity/Intelligence build
`d67801f86e08e49657306a454d9e16b696acf55fdd846c887e14fd7c701ea5be`. Both saved main skills are used unchanged.

### Snapshot evidence vs. fresh real-engine evidence

poe.ninja's per-character API response contains two independent things: the
`pathOfBuildingExport` string (the actual build — gear, tree, gems — used to
materialize a fixture) and a `<PlayerStat>` block inside that same export, which is
poe.ninja's own **cached display snapshot** of that character's stats, last computed
by poe.ninja's own server-side PoB instance at some point before the fetch. This
snapshot is stripped from every poe.ninja-sourced fixture during sanitization (see
above). It is display-only: PoB writes `<PlayerStat>` when saving a build but does
not read it back on load, and ExileLens never reads it at all. The four fixtures
inherited from the earlier local validation corpus (`core04_player_ring.xml`,
`core04_bow_quiver.xml`, `core04_minion_actor.xml`, `core04_stage_context.xml`)
still contain the `<PlayerStat>` cache that local PoB wrote when they were saved. It
holds computed numbers only, no identifiers, and was deliberately left in place.

**Every DPS/offense figure that appears in this repository's docs, test docstrings,
and registry descriptions is a fresh, live recalculation** performed by loading the
sanitized fixture into a real local PoB2 engine and reading its output — never
poe.ninja's cached `<PlayerStat>` numbers. During discovery, the raw snapshot numbers
were used only to *find* promising candidate builds (e.g. "does this account's
cached `PoisonDPS` look ailment-dominant?"); every number that then made it into a
fixture, test, or doc was re-verified against a live engine load before being
written down.

For `core04_poison_ailment.xml`, poe.ninja's cached snapshot reported `PoisonDPS =
992,159`; loading the same (sanitized, otherwise byte-identical) fixture fresh into a
local PoB2 engine reports `PoisonDPS = 793,727` — about 20% lower, and the
per-component ratios are not uniform (hit `TotalDPS` is *higher* in the fresh
recompute, `IgniteDPS` is lower). A single scaling/version-drift factor would move
every component the same way; this doesn't, which points to a genuine state
difference (e.g. poe.ninja's cached snapshot reflecting the character's gear/tree at
a slightly different fetch cycle than the exported PoB code) rather than an engine
or calculation defect. This is expected and out of ExileLens's control either way:
poe.ninja's own snapshot cache is not something this repository reads or depends on,
and the fixture's documented numbers are the reproducible, live-recomputed ones any
future engine run against this exact file should reproduce.

All fixtures were screened before publication for filenames and text containing local
paths, home-directory references, account or character metadata, emails, credentials,
session/cookie/authentication fields, private links, and per-item `Unique ID:` lines.

The selected XML files have no retained account or character attributes. Empty
`itemPbURL` attributes are retained because they are part of the PoB fixture format;
they contain no URLs. Item display names are ordinary in-game fixture text and are not
account identifiers. No player profiles, account names, character names, IDs tied to a
real account, tokens, cookies, diagnostics, local caches, or source-machine metadata
are stored.

The public safety regression scans every selected text fixture for these categories.
It is intentionally conservative: a fixture that cannot pass the scan should be
excluded or re-sanitized rather than worked around in a test.

## Commands

Set `POB2_PATH` to a supported local Path of Building 2 installation. The path is an
environment input only and is never committed or written by the tests.

```powershell
$env:POB2_PATH = '<path-to-supported-PoB2>'
python -m pytest -m real_pob
python -m pytest -m build_corpus
```

`real_pob` runs the strategic suite. `build_corpus` runs static manifest/safety checks
and real-worker loading for the checked-in corpus. If no supported runtime is found,
worker tests are reported as **SKIPPED** with a message explaining how to configure
`POB2_PATH`; they do not become passing tests. A configured but invalid or unsupported
runtime is a test error.

## Updating the corpus

Corpus generation is intentionally not part of the regular test command. A future
update may use external/public sources during curation, but the resulting regression
fixtures must be materialized here, sanitized, documented, and runnable without the
generation environment. Do not add live account, market, or API acquisition to this
gate.

## Coverage reporting

`docs/CORPUS_COVERAGE_METHODOLOGY.md` and the generated
`docs/corpus_coverage/COVERAGE_REPORT.md` turn this corpus (plus the strategic and
adversarial suites) into a graded build-archetype coverage matrix — what percentage
and which categories of real builds this corpus currently proves Item Check handles
correctly and safely. Regenerate it with
`python scripts/generate_corpus_coverage_report.py` whenever a fixture, test, or
`tests/corpus_coverage/registry.py` entry changes.
