# PoB-native damage policy

**Permanent rule: PoB computes; ExileLens compares.** Damage comparisons come
directly from the loaded Path of Building calculation. ExileLens selects the
right PoB owner, skill, stat set, part, calculation state and output field;
equips a candidate; recalculates in PoB; compares the *same* semantic field;
and explains the scope. It does not supply missing combat DPS.

For the bounded discovery and presentation of separate native PoB skill
outputs, see [PoB-native metric discovery](POB_NATIVE_METRIC_DISCOVERY.md).

P1-A (player versus minion/actor), P1-B (hit, skill DoT and ailment
quantities), and P1-C (stat set, skill part/mode and calculation state) remain
the required **PoB-reading** and comparison guards. Their semantic identity
must be stable baseline → candidate. Percent and absolute deltas between two
PoB values, defensive scoring, unit conversions, and presentation formatting
are allowed. None is an independent damage simulation.

## Source hierarchy and provenance

| Provenance | What may be compared | Preconditions | Product claim |
| --- | --- | --- | --- |
| `POB_FULL_BUILD` | PoB `FullDPS`/`FullDotDPS` | Nonzero/populated value, groups explicitly included in the *loaded* PoB, known aggregate meaning, and identical membership/count/state baseline → candidate. ExileLens never enables groups. | “PoB-configured Full DPS”, not guaranteed practical rotation DPS. |
| `POB_PRIMARY_SKILL` | Selected PoB skill/actor/stat-set quantity, e.g. `TotalDPS`, `TotalDot`, `IgniteDPS`, `PoisonDPS`, `Minion.CombinedDPS` | Same owner, skill, semantic quantity, stat set/part/state and field on both sides. | “Selected primary skill”, never automatic “full build DPS”. |
| `POB_COMPONENT` | Separately named PoB-calculated components | Each component has its own identity and before/after PoB value. | Multiple individual comparisons; no invented total. |
| `UNAVAILABLE` | No authoritative quantity for the requested scope | Missing, unresolved or incomparable PoB output. | PARTIAL/UNCERTAIN; no damage percentage for that scope. |

The internal primary metric diagnostics expose provenance together with
metric source/owner, selected skill, actor, stat set, part/mode, field,
semantic quantity, confidence and damage reference. `POB_COMPONENT` is a
separate presentation capability, not a license to add component DPS.

`FullDPS=0` with no included groups means **not configured**, not zero build
damage. A raw FullDPS number by itself, especially one supplied without
matching group metadata, does not authorize aggregate selection. The
inclusion/count fingerprint must survive the item swap; if it changes, the
aggregate delta is unmeasured. FullDPS may be compared only as PoB's
configured aggregate, with the configuration clearly labeled. If it is not
configured, compare the selected primary skill and any available native
components, and say full-build damage was not measured. No silent mutation
of PoB group flags is permitted.
The current resolver selects a populated FullDPS automatically when the
loaded PoB explicitly includes at least two groups, or when an explicit
full-aggregate scope is requested with at least one included group. This
means *configured PoB sum*, not a validated practical rotation; candidate
membership and count are guarded before any damage verdict.

## Partial comparisons and user-facing copy

The primary-skill comparison is useful even on a multi-skill build, but it
does not establish overall damage. On a complex build without a usable PoB
aggregate, separately track **component correctness** and **full-build
composition**: the first can pass while the second remains partial. Missing
composition is not a neutral result: **unknown != SIDEGRADE**. Keep existing
uncertainty/unsupported protection; never invent score 50 or a total DPS.

The compact presentation should identify whether it is comparing PoB Full
DPS, a selected skill, or only components. More Info should explain the
exact PoB reference and, for primary-skill results, state that it is not
full-build DPS. Suitable wording:

- FULL: “PoB-configured Full DPS: 2.41m → 2.78m (+15.4%).”
- PRIMARY: “Vile Effusion: 35.4k → 42.1k (+18.9%). Comparing selected PoB skill, not total build damage.”
- PARTIAL: “Spark +4.1%; Comet +31.2%; crit chance −3.4%. Overall triggered DPS unavailable from this PoB configuration.”

These examples are copy patterns, not calculated results or new scoring
formulas. Useful diagnostic reason codes include `FULL_DPS_NOT_CONFIGURED`,
`TRIGGER_RATE_NOT_AVAILABLE_FROM_POB`, `PRACTICAL_STAGE_NOT_DEFINED`,
`STACK_COUNT_NOT_DEFINED`, and `PROPAGATION_NOT_MODELED_BY_POB`. Present them
in plain language. A future UX may offer instructions or a status indicator
for configuring Full DPS *in PoB*; ExileLens must not set the flags for users.

## Prohibited combat derivations

Do not independently calculate trigger frequency, expected triggers per
second, ailment stack equilibrium, expected active poisons, persistent/cloud
overlap, pack size, propagation effectiveness, player rotation, practical
uptime/release stage, simultaneously hit enemy count, boss uptime or a
map-clear multiplier. Do not import wiki/game formulas to manufacture an
otherwise unavailable DPS. PoB may be used if the *loaded build* directly
exposes the relevant quantity. Never label an ExileLens-derived composite
as PoB DPS.

### Corpus V1 under this contract

The historical Corpus V1 baseline and expectations remain frozen. For C11,
C12, C14, C15, C17, C19 and C21, every loaded fixture has
`FullDPS=FullDotDPS=0` in MAP and BOSS because no relevant groups are
included. Manually enabling FullDPS for research did not prove event rate,
active stacks, propagation, overlap or rotation.

| Build | Best native PoB reference | Full aggregate in frozen fixture? | Other directly calculated components | Unavailable build relation; intended display |
| --- | --- | --- | --- | --- |
| C11 | Flameblast configured-stage `IgniteDPS` | No | Flameblast hit; Oil group inspected | Practical release/setup unknown. Label configured Flameblast state; overall practical damage PARTIAL. |
| C12 | Selected triggered Comet PoB output | No | Spark, Arc, Comet, crit chance | Effective CoC event rate/concurrency not established. Show components; overall triggered DPS PARTIAL. |
| C14 | Vine Arrow Impact `PoisonDPS` | No | Vine hit, Toxic Growth, Poisonburst | Active vines/spores, overlap and stacks unknown. Show native components; build damage PARTIAL. |
| C15 | Gas Grenade Impact `PoisonDPS` | No | Gas hit, crossbow attacks | Cloud lifecycle, stacks, detonation timing unknown. Show native components; build damage PARTIAL. |
| C17 | Supporting Fire `Minion.CombinedDPS` | No | Other serialized minion outputs | Rotation and some named skills absent from frozen XML. Show minion-owned component; overall UNSUPPORTED/PARTIAL. |
| C19 | Essence Drain skill-native `TotalDot` | No | Contagion DoT, Vile Effusion when individually inspected | Propagation and Effigy concurrency unknown. Name each PoB component; full-build damage PARTIAL. |
| C21 | Selected triggered Comet PoB output | No | Freezing Shards, separate hand-cast Comet | Ailment-event rate/concurrency not established. Show components; overall triggered DPS PARTIAL. |

The “best reference” column identifies a *native component*, not a newly
validated whole-build metric or an instruction to promote Corpus V1 cases to
PASS. C11's implicit practical stage remains a limitation even though PoB's
configured-stage calculation is valid. The corpus health target remains
80 PASS / 30 EXPECTED_UNCERTAIN / 6 UNSUPPORTED, with zero confident-wrong,
wrong-uncertain and corruption states; 32 adversarial mutations must pass.

## Current code audit and roadmap reset

Production contains the P1-A/B/C PoB output selection and semantic guards,
PoB candidate recalculation, PoB-value deltas and defensive/value scoring.
The normalized legacy `primary_dps` field previously fell back to raw
FullDPS without checking group configuration; it is not the authoritative
primary resolver and must not imply unconfigured full-build damage. No
production trigger-frequency, poison-equilibrium, cloud, propagation,
rotation, practical-stage or uptime combat simulator was found. The
component/trigger/gameplay model slices in
`BUILD_DAMAGE_COMPOSITION_AUDIT.md` were **audit-only/planned-only**, not
production. They are cancelled as implementation proposals; the audit is
retained as evidence about what PoB does *not* establish.

Future damage work, in order:

1. Improve discovery and provenance of native PoB outputs, including stable FullDPS inclusion/count diagnostics.
2. Present multiple native PoB components without summing them, with explicit PRIMARY versus FULL scope.
3. Improve PARTIAL explanations and optional guidance for configuring Full DPS in PoB.

Do **not** begin P1-D Trigger Composition or a replacement gameplay model.
Any future capability must continue to use PoB's calculation and compare
only like-for-like native outputs.
