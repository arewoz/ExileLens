# PoB2 Engine Contract (Phase 1)

Stable product-facing API implemented by the persistent worker (`runtime/lua/bridge.lua`) and exposed through `poe2value.engine.Engine`.

## Lifecycle

| Method | Description |
|---|---|
| `ping()` | Worker health check |
| `load_build(path, context=MAP)` | Load XML via real PoB headless engine |
| `unload_build()` | Clear loaded build state |
| `shutdown()` | Tear down worker |

## Inspection

| Method | Returns |
|---|---|
| `get_build_info()` | class, ascendancy, main skill, passive counts |
| `get_equipment()` | slot inventory with item raw text |
| `get_metrics(context?)` | raw PoB metrics + normalized product metrics + fingerprint |

## Evaluation

```python
evaluate_candidate(slot: str, item_raw: str, context: str | None = None)
```

Returns:

- `baseline` — metrics, equipment, fingerprint before change
- `candidate` — metrics after temporary equip, `item_present` proof flag
- `restored` — post-restore metrics/equipment
- `delta` — normalized metric deltas
- `restore.pass` — boolean gate

## Contexts

| Context | PoB config overrides |
|---|---|
| `MAP` | `enemyIsBoss=None`, level 82, mapping resist profile |
| `BOSS` | `enemyIsBoss=Boss`, level 84, boss resist profile |

Contexts are **in-memory only**. Saved build files are never modified.

## Normalized metrics

Product layer maps raw PoB fields via `poe2value.metrics.normalize_metrics`:

- `offense.primary_dps` ← `CombinedDPS` (fallback `FullDPS`, `AverageDamage`)
- `defense.ehp` ← `TotalEHP`
- plus structured life/resist/resource fields

Raw PoB fields are always included in worker responses under `metrics` / `raw`.

## Fingerprint

Deterministic components hashed by Python (`fingerprint_hash`):

- equipped item raw text per slot
- allocated tree node ids
- evaluation context config inputs
- main skill label / socket group index
- build name + source path

Used only for restore safety, not DRM.

Application `load_build` goes through `EvaluationController` so loadout, numeric item-set id, tree set, fingerprints, and generation stay canonical. Direct `Engine.load_build` remains valid for CLI/tests.

## Error codes

`POB_PATH_INVALID`, `POB_BOOT_FAILED`, `UNSUPPORTED_POB_REVISION`, `BUILD_NOT_FOUND`, `BUILD_PARSE_FAILED`, `NO_BUILD_LOADED`, `ITEM_PARSE_FAILED`, `ITEM_INCOMPATIBLE`, `ITEM_UNSUPPORTED`, `SLOT_INVALID`, `SLOT_RESOLUTION_FAILED`, `SLOT_RESOLUTION_AMBIGUOUS`, `NO_COMPATIBLE_SLOT`, `NOT_POE2_ITEM`, `EVALUATION_INVALID_BUILD_STATE`, `PRIMARY_METRIC_UNRESOLVED`, `CALC_FAILED`, `RESTORE_FAILED`, `WORKER_UNHEALTHY`

## Product slot mapping (Phase 2)

| Product slot | PoB slot | Notes |
|---|---|---|
| `HELMET` | `Helmet` | |
| `BODY_ARMOUR` | `Body Armour` | |
| `GLOVES` | `Gloves` | |
| `BOOTS` | `Boots` | |
| `BELT` | `Belt` | |
| `AMULET` | `Amulet` | |
| `RING_1` | `Ring 1` | |
| `RING_2` | `Ring 2` | |
| `WEAPON_1` | `Weapon 1` | Main hand / 2H |
| `WEAPON_2` | `Weapon 2` | Dual-wield second weapon |
| `OFFHAND_1` | `Weapon 2` | Shield / Focus / Quiver. Logical "currently-active offhand": the M1.1 `active_weapon_slot` bridge translation (`runtime/lua/bridge.lua`) transparently resolves this to the physical `Weapon 2 Swap` slot whenever the build's active item set has `useSecondWeaponSet=true`, so product code never needs a distinct "active second weapon set" offhand concept — see M1.2 offhand-support coverage (`docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md`). |
| `OFFHAND_2` | `Weapon 2 Swap` | **Confirmed unreachable from live data (re-verified M1.2).** Declared only for `product_slot_to_pob`'s enum completeness; `EVALUABLE_SLOTS` in `runtime/lua/bridge.lua` never reports `"Weapon 2 Swap"` as a compatible slot, so `pob_slot_to_product` can never produce `OFFHAND_2` from a real engine response, even during an active second weapon set (see `src/poe2value/items/slots.py`'s in-code comment). Do not build new logic on this branch. |

Phase 2 engine methods:

| Method | Description |
|---|---|
| `parse_item(item_raw)` | PoB parse + compatible slots for loaded build |
| `resolve_compatible_slots(item_raw)` | Slot resolution only |

## Phase 5A probes

Marginal stat probes reuse `evaluate_candidate`: append a real modifier line to a cloned equipped item, recalc, restore, verify fingerprint. Build XML is never written.

Product analysis methods (Python, not extra Lua verbs): `analyze_build`, `analyze_slot`, Search Intent export.

## Phase 5A.5 tree

| Method | Description |
|---|---|
| `get_tree_snapshot` | Graph metadata, allocation, tree set (no XML write) |
| `evaluate_tree_path(node_ids)` | Undo snapshot → `AllocNode` complete path → recalc → `RestoreUndoState` → fingerprint |

Tree probes are in-memory only. Restore failure marks the worker unhealthy.

Python: `get_frontier_nodes`, `get_targets_within_cost`, `rank_next_passive_points`, `rank_targets`. CLI: `tree-info`, `next-passive`, `tree-targets`, `evaluate-node`.

## Jewels (M1.3)

Unlike every other supported category, a Jewel socket is not a fixed equipment slot: PoB
creates one `ItemSlotControl` per allocated passive-tree jewel-socket node (name
`"Jewel <nodeId>"`, PoB's `ItemsTab.lua`), and the jewel-to-socket assignment itself
lives on the tree spec, `spec.jewels[nodeId] = itemId` (`0`/absent = empty), not on
`itemsTab.activeItemSet` like ordinary equipment. Both `evaluate_item_slots` and the
underlying `tx_begin`/`tx_measure`/`tx_finish` transaction machinery already work on
these slot names unchanged (`slot:SetSelItemId` branches internally on whether the slot
has a `nodeId`), so no separate jewel transaction verb was needed — the two real gaps
were (1) `resolve_compatible_slots_for_item` never enumerated jewel-socket names (they
are dynamic and per-build, so cannot be a static table like `EVALUABLE_SLOTS`), and (2)
`tx_begin` never tracked/restored jewel-socket slots (added in M1.3).

Compatible-socket discovery reuses PoB's own `ItemsTabClass:IsItemValidForSlot`
(sinister sockets, ascendancy-embedded sockets, cluster-jewel size rules) against every
ALLOCATED socket (`slot.inactive` gates this — an unallocated socket is never a valid
placement target), occupied or empty alike.

### Correctness fix: `slot.inactive` was never actually being computed (P1.1b)

The paragraph above describes the *intended* gate. Until P1.1b it did not work: PoB
only ever computes `slot.inactive` inside `ItemsTabClass:UpdateSockets`
(`spec.allocNodes[nodeId] == nil -> slot.inactive = true`), and PoB itself calls that
function only from `ItemsTab:Draw` (a GUI render method, never reached headless — no
render loop) and one narrow `CalcSetup.lua` branch gated on `SetGrantedPassiveNodes`
returning true (an item granting extra passive nodes — not an ordinary calc pass).
`ItemSlotControl` never initializes `.inactive` in its constructor, so headless it
stayed Lua-`nil` (falsy) for every socket-type tree node no prior call happened to
touch — `not slot.inactive` then read as "active" for every Socket-type node PoB's
`ItemsTab:Init` creates across the WHOLE passive tree (`build.latestTree.nodes`, a
fixed pool for a given tree — ~19 nodes on the public corpus's shared tree), not just
the ones the loaded spec actually allocates.

Proven order/state-dependent, not deterministic: on the public corpus,
`core04_melee_weapon.xml`'s `.inactive` happened to be correctly computed for its run
(5 active, matching `spec.allocNodes` ground truth exactly), while
`core04_skill_native_dot.xml`'s was never computed at all (0 of 19 marked inactive) —
its true allocated count is 4 (`Jewel 7960/21984/26196/61419`), all occupied, not the
"19 allocated, 15 empty" this contract and `CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md`
previously (incorrectly) documented. Real-engine impact for that build: 19 sockets
evaluated per candidate (5.3s) before the fix, 4 (2.2s) after — a ~59% time reduction
that is a *side effect* of no longer evaluating sockets that were never legal in the
first place, not a new optimization.

**Fix:** `allocated_jewel_socket_slots()` (`runtime/lua/bridge.lua`) now calls
`it:UpdateSockets()` explicitly before reading `.inactive`, removing the
accidental/order-dependent reliance on the two GUI/calc-pass call sites above. Cheap
(one pass over `ItemsTab.sockets` keyed against `spec.allocNodes`; no recalculation)
and idempotent. Verified: unallocated Socket-type nodes are excluded; the connectivity
and Split Personality remediation below is unaffected (re-run clean); restore remains
exact; ranking only ever sees the corrected legal set
(`tests/integration/test_jewel_real_pob.py`).

### Inter-slot verification: two paths

A jewel-socket batch cannot always use the cheap, frame-skipped structural check
equipment batches use between slots (`tx_assert_reverted_structural`): a Timeless Jewel
can change which tree-granted skill groups exist on removal, which that check — by
design, to avoid a recalculation — cannot see. `tx_assert_reverted_jewel_batch` tries the
cheap check first and only pays for one confirming recalculation
(`tx_assert_reverted_full`) when it looks suspicious, so an ordinary jewel batch costs
exactly what an equivalent equipment batch would.

### Restore-safety: root cause, fix, and one residual case (M1.3 remediation slice)

The 3 fixtures originally reported as "stateful/accumulating main skills" (stage-based,
DoT-averaging, minion-actor) were re-investigated and found to share ONE root cause,
unrelated to their skill archetypes:

**Root cause.** A connectivity-affecting jewel — PoE's "Intuitive Leap"-like mechanic
(`item.jewelData.intuitiveLeapLike`, "Passives in Radius can be Allocated without being
connected", e.g. "From Nothing") or its "alternate start" cousin
(`item.jewelData.alternateClassStart`, "Can Allocate Passive Skills from the
&lt;Class&gt;'s starting point", e.g. "Split Personality") — makes other passives'
allocation validity depend on the jewel's presence. `ItemSlotClass:SetSelItemId` (the
swap-and-restore primitive the jewel transaction is built on) has no symmetric
"reallocate on restore" step the way PoB's own `ItemsTabClass:DeleteItem` has a
"deallocate on removal" step. A candidate frame that briefly displaces such a jewel
therefore left the true baseline's dependent passives (and, for `hashOverrides`-driven
node-data rewrites and mastery selections, their data) unrestored even after the SAME
jewel was put back — a genuinely wrong restored metric, not a false-positive comparison.

**A separate bug found while root-causing this:** `tx_finish`'s (and
`tx_assert_reverted_full`'s) `RESTORE_FAILED` error details had `baseline_value`/
`restored_value` swapped (`metrics_equal(restored_metrics, ctx.true_baseline_metrics,
...)` returns `(ok, key, a[key], b[key])` with `a`=restored, `b`=baseline, and the
assignment had them backwards). Pre-existing, predates M1.3; never visibly wrong before
because production equipment restores never actually mismatched. This bug is why the
M1.3 initial slice's diagnosis had baseline and restored inverted for these fixtures.

**Fix.** `repair_tree_allocation` (`runtime/lua/bridge.lua`) runs after every slot
revert (inter-slot and final) and repairs `spec.allocNodes`/`node.alloc`,
`spec.hashOverrides` (re-applying `PassiveSpecClass:ReplaceNode`, the same call PoB's
own load path uses when replaying `hashOverrides`), and `spec.masterySelections` to
exactly match a raw snapshot of the true baseline captured once in `tx_begin` — the
same data structures `DeleteItem` mutates, applied in reverse, not a synthetic metric
correction. Verified against a clean reload, not just internal consistency: the
restored primary metric now matches an independent `get_metrics` read of the untouched
build to within float tolerance.

**Result:** `core04_mixed_hit_ailment.xml` ("From Nothing") and `core04_minion_actor.xml`
("From Nothing") now restore correctly — full multi-socket batch evaluation, zero
RESTORE_FAILED, primary metric matches clean reload exactly.

**One residual, not-locally-fixed case:** `core04_stage_context.xml`'s "Split
Personality"-style socket (`jewelData.alternateClassStart`) restores its PRIMARY offense
metric (CombinedDPS) correctly after the fix above, but a small secondary-metric
discrepancy remains (`Life`, ~44 points / ~2.5%). `core04_skill_native_dot.xml`'s
"From Nothing" socket (previously excluded as a precaution because PoB did not recognize
it via either jewel-data flag) is now correctly INCLUDED and restores correctly, since
the underlying repair fix covers it regardless of whether the flag-based exclusion
recognizes the item — confirming the fix mechanism itself is sound; the Split Personality
residual is a narrower, separate issue.

**Precise differential evidence (M1.3 second remediation slice).** A per-node diagnostic
(temporary, not shipped) compared every one of the 155 allocated tree nodes across
(A) a clean reload, (B) mid-transaction with the candidate in the socket, and (D) after
restore. 88 of 155 nodes show a `pathDist` difference (a pure path-finding/UI distance
field — `PassiveSpec.lua`'s `BuildNodePathsToRootNodes` output, not itself a stat
input). Exactly **4 nodes** (`21336`, `23091`, `52199`, `58789`) show a genuine
`node.connectedToStart` flip from `true` (clean reload) to `false` (after restore) —
this field is `PassiveSpec.lua`'s per-node record of "is there a path from this
allocated node to any start node (including an `alternateClassStartNodes` entry)",
recomputed by `BuildAllDependsAndPaths` and consumed to build the `rootList` for
`BuildNodePathsToRootNodes`. None of the 4 flipped nodes carry a `Condition:ConnectedTo`
mod themselves (`has_connected_mod = false` for all 4; their own `sd` text — Evasion/ES,
Fire Damage, Exposure Effect, Ailment/Stun Threshold — has no direct Life relevance),
so they are evidence of a REAL, precise divergence, not the (or not the sole) mechanism
producing the `Life` delta specifically.

**Experiments performed (each measured, none kept unless it changed the result):**
1. `BuildAllDependsAndPaths()` called unconditionally after every repair (not gated on
   `changed`) — no measurable effect on `Life` (still 1792 vs true 1748). Ruled out.
2. `node.connectedToStart` repaired to the true baseline's exact per-node snapshot
   (captured as a plain-value copy in `tx_begin`, not a live node reference — the first
   attempt at this reused `true_alloc_snapshot`'s node REFERENCES, which mutate in place
   and are therefore not a real point-in-time snapshot; the corrected version captures
   `node.connectedToStart` as a plain boolean at `tx_begin` time) — no measurable effect
   on `Life` (still 1792 vs true 1748, confirmed against an explicitly-verified fresh
   reload via `invalidate_build()` to rule out stale-build contamination between test
   runs). Ruled out.
3. `spec.hashOverrides`/`spec.masterySelections` repair (already part of the production
   fix) — confirmed present and matching true baseline exactly (`missing=`, `extra=`
   both empty in the diagnostic dump) before either of the above experiments ran, so
   neither was the gap either.

**Conclusion:** the exact downstream calculation path from "4 nodes' `connectedToStart`
diverges" to "Life is 44 points high" was not identified within this slice's time budget
despite precise, node-level differential evidence and 2 targeted, measured, ruled-out
repair experiments. This is now a narrow, well-bounded unknown (4 specific nodes, one
specific PoB-internal field, in one specific real-corpus jewel mechanic), not a vague
"still off" case. Given the primary offense metric is already correct and only this one
narrow secondary-metric path remains open, further invasive PoB lifecycle emulation
(e.g. replaying whatever PoB's own UI jewel-removal/re-equip flow does beyond
`SetSelItemId` that neither of the above experiments reproduced) was judged not
justified without a new, evidence-backed hypothesis — continuing to guess at additional
repair calls without one would trade a known, safely-excluded gap for speculative,
unverified state mutation. The exclusion remains in place. This socket stays excluded
from jewel-socket discovery (`jewel_socket_is_connectivity_risky` now checks both
`intuitiveLeapLike` and `alternateClassStart`) rather than risking the small wrong
value — `excluded_connectivity_risky_socket_count` reports it.

## Jewel evaluation performance (M1.3 Part B)

Profiling (`EXILELENS_TOOLTIP_PERF=1`, Lua-side per-stage breakdown) found native
component discovery (`skill_report`, triggered for multi-skill builds via
`should_discover_components`) was the dominant cost of jewel evaluation — roughly
70-80% of total wall time on `core04_melee_weapon.xml` (5 sockets) and
`core04_bow_quiver.xml` (9 sockets) — because jewel batches were not requesting the
PERF-06 in-batch optimization equipment batches already get (`in_batch` was explicitly
`false` for jewel batches in the initial M1.3 slice, out of caution about a DIFFERENT,
now-resolved concern: whether the cheap structural inter-slot check could read stale
calc-derived state left by native discovery's own skipped trailing recalc).
`tx_assert_reverted_jewel_batch`'s fallback (`tx_assert_reverted_full`) always
recalculates before reading anything, so that staleness risk does not apply to it the
way it did to the plain structural check — re-enabling `in_batch=true` for jewel
batches was safe. Measured effect: `core04_melee_weapon.xml` (5 sockets) ~3.3s → ~2.0s
(~38% faster); `core04_bow_quiver.xml` (9 sockets) ~5.4s → ~3.7s (~31% faster);
`native_discovery_ms` dropped from 804/2151ms to ~2/1ms. Remaining cost is PoB's own
per-socket recalculation (one settle pass per candidate placement, ~130-260ms/socket on
these fixtures) — an inherent, measured PoB cost on real builds, not an avoidable
ExileLens redundancy.

### Second remediation slice: recalculation trace and two further hoisted-work fixes

**Recalculation trace for an N-socket batch** (unchanged in shape by this slice, already
minimal): 1 baseline settle (`tx_begin`) → for each of N sockets: apply candidate,
1 candidate settle (`tx_measure`), revert (no recalc unless the cheap inter-slot check
looks suspicious, which is rare — see the Timeless Jewel note above) → 1 final restore
settle (`tx_finish`). Total: **N+2 recalculations** (7 for 5 sockets, 11 for 9 sockets,
both measured exactly via `recalc_frames` before and after this slice's changes — the
COUNT did not change, confirming no redundant recalculation was hiding at that level;
the two fixes below are Lua-side CPU work around each recalculation, not extra PoB
engine passes). A candidate is never restored-then-recalculated only to be immediately
overwritten by the next candidate: the revert between socket A and socket B does not
recalculate, so the transition from "A reverted" to "B's candidate" happens inside B's
own single `tx_measure` recalculation, not two.

**Two further redundant-work sources found and fixed** (both CPU-bound Lua work
surrounding each recalculation, not the recalculation itself):

1. **Full fingerprint tree-walk on every inter-slot check.** `M.fingerprint_components()`
   builds a full per-node payload (`node_payload()`) for EVERY node in the passive tree
   (thousands, not just the ~155-19 allocated ones) to produce fields (`nodes`, `edges`,
   `jewels`, `mastery`, ...) that are part of the CLIENT-facing fingerprint contract
   (returned once per transaction in the baseline/restored payload) but were ALSO being
   rebuilt on every one of a jewel batch's up-to-`N-1` inter-slot checks
   (`tx_assert_reverted_structural`/`_full`/`_jewel_batch`), even though those checks
   only ever read the `.equipment` sub-field. A new `equipment_snapshot()` builds only
   that dict (~20-190 slot reads, not a tree walk); the 3 inter-slot check functions
   now call it instead of the full fingerprint. The one-time baseline/restored
   fingerprint payloads (`tx_begin`, `tx_finish`) are unchanged — the detailed snapshot
   is a real product contract, not restore-verification machinery, and was already only
   built once per transaction either way.
2. **Candidate item re-parsed/re-added per socket.** `set_item` created a brand-new
   `Item` object (`ParseRaw` + `AddItem`, ~28ms/socket measured) for the SAME candidate
   raw text on every socket. `set_item` now accepts an optional per-transaction
   `item_cache` (raw text -> item id); a jewel batch parses/adds the candidate ONCE and
   reuses the same item id for every socket (`SetSelItemId` still re-validates
   `IsItemValidForSlot` per socket via `Populate()`, so per-socket compatibility is
   still checked every time, not skipped). Equipment transactions and single-slot jewel
   calls pass no cache and are unaffected.

**Correctness re-verified after both fixes:** the exact same known-correct
`core04_melee_weapon.xml` result (recommendation socket, verdict, per-socket verdicts,
`OFFENSE` magnitude percentages, restore pass) was re-asserted unchanged; repeated
evaluation stability, the 3 previously-failing fixtures' restore correctness, and empty-
socket handling were all re-verified green after these changes.

**Measurement caveat (reported honestly rather than omitted or gamed):** this second
slice's own timing measurements were taken while the development machine was under
confirmed heavy EXTERNAL load (`Get-CimInstance Win32_Processor` reported 73-87% CPU
load throughout, with no ExileLens/PoB/Lua processes found competing — i.e. load from
other work on the shared machine, not from this investigation), roughly doubling every
`recalc()` frame's wall-clock cost compared to the clean measurements taken earlier in
the same overall M1.3 effort. Wall-clock numbers taken during this load spike (5 sockets
4.2-6.5s, 9 sockets 7.2-11.0s) are therefore NOT representative and are not used as the
final performance verdict; `recalc_frames` (the load-independent recalculation COUNT)
confirms no new recalculation was introduced, and `candidate_set_item_ms` dropping from
~140ms to consistently well under that (even under the load spike) confirms the item-
cache fix is real. The best available clean baseline remains the native-discovery-fix
numbers above (~2.0s / ~3.7s), which the two additional fixes in this slice can only
further reduce, not regress — but a clean, confirmed absolute number reflecting ALL
three fixes together could not be captured within this slice's time budget once the load
spike began. Both the "acceptable" (5≤1.5s, 9≤2.5s) and "strong" (5≤1.2s, 9≤2.0s)
performance targets remain UNMET on the best clean evidence available (~2.0s already
exceeds the 1.5s acceptable boundary before the two additional fixes are even
counted), so performance stays a bounded, honestly-reported gap rather than a claimed
pass.

## Weapon-set component contexts (Slice 3, internal)

Slice 2 identifies *which* PoB effect to measure (`ComponentReference`).
Slice 3 qualifies *under which weapon set* it is measured
(`CalculationContext`: `weapon_set` 1/2 plus the active skill-set id for
cache identity; the skill set itself is never switched). Effect semantic
identity stays context-independent: the same effect in set 1 and set 2 is
the same semantic effect, but two disjoint cache observations
(`ContextualComponentReference`, composition -- never a `semantic_id`
suffix).

The local PoB revision exposes no `weaponSetEnvs`/`usingSkillSet` API. The
weapon set is the active item set's `useSecondWeaponSet` boolean; its
calculation effects (Condition:WeaponSet1/2, weapon-slot inclusion with
`" Swap"` stripping, `group.slotEnabled` gating, weapon-set-tagged
jewel/passive mods) all flow through a full recalc. The bridge reproduces
PoB's own switch (ItemsTab weaponSwap buttons: flag + build-dirty + main
socket group re-pin to the first group on the newly active set, minus UI
undo history) and owns the whole transaction: snapshot, switch, recalc,
verify activation (fail closed), resolve the exact reference, read
PoB-native metrics, restore, recalc, verify exact restoration
(`RESTORE_FAILED` + unhealthy worker on any mismatch, same as Slice 2).

Logical active slots (`Weapon 1`/`Weapon 2` via `active_weapon_slot`)
remain the only product-facing weapon API and are completely unchanged.
Slice 3 adds an INTERNAL exact-physical path (`set_item_physical`,
bypassing `active_weapon_slot`) addressing `Weapon 1`, `Weapon 2`,
`Weapon 1 Swap`, `Weapon 2 Swap` directly. `ProductSlot.OFFHAND_2` is
still unreachable legacy enum completeness and is not repurposed.

New worker methods (all explicit/lazy; ordinary Item Check never calls
them and pays zero extra frames):

| Method | Description |
|---|---|
| `read_effect_metrics(reference, weapon_set=1\|2)` | One component under one weapon set; `UNAVAILABLE`/`NOT_VALID_IN_CONTEXT` where PoB has no valid calculation, never a synthetic zero |
| `evaluate_effect_candidate(reference, weapon_set, physical_slot, item_raw)` | Baseline + candidate + same-component delta for one component with a candidate in one exact physical slot; proves the opposite set byte-identical and restores everything exactly |
| `get_weapon_set_context()` | Current weapon-set context plus the four physical weapon raws (diagnostic) |

`fingerprint_components`, the semantic restore comparator (full and
structural), `build_info`, and the evaluation context identity all carry
`weapon_set` + `active_skill_set_id`, so a set-1 observation can never be
reused as set-2 (and vice versa) from any ExileLens cache. Contextual
deltas are component evidence only: they never become public
`MEANINGFUL_UPGRADE` verdicts and no cross-set composition, trigger-rate,
projectile, rotation, or practical-DPS inference exists.

## Contextual proof layer (Slice 4A, internal, evidence only)

`src/poe2value/items/contextual_proof.py` is a small deterministic domain
layer on top of Slice 3 measurements. It lifts `evaluate_effect_candidate`
results into `ContextualMeasurement` inputs (qualified reference, physical
target, baseline/candidate outputs, provenance) and classifies their
relationship into exactly one of `COMMON_RESPONSE`, `DIVERGENT_RESPONSE`,
`INSUFFICIENT_EVIDENCE`, or `NOT_COMPARABLE`, returned as an inspectable
`ContextualProof` dict for later slices. Every measurement carries
provenance (`candidate_fingerprint` from
`evaluation_identity.candidate_fingerprint`, plus `source_revision` and
`build_generation` from the evaluating engine); the classifier requires
unanimous provenance where present, fails closed with `PROVENANCE_MISMATCH`
on any disagreement, and refuses unbound inputs with
`CANDIDATE_PROVENANCE_UNPROVEN` -- a proof can never compare component A
measured for candidate X with component B measured for candidate Y. The
common-response check compares each shared significant field's own
after/before ratios independently within 5% relative spread (no averaging
of unlike PoB quantities; the representative factor is derived only after
every per-field condition holds), refuses ratios on baselines at or below
the pipeline-wide 0.5 response epsilon, never converts unavailable data to
zero, and treats uniform no-change as insufficient rather than a match.
`COMMON_RESPONSE` is explicitly approximate (`exact: false`, machine
readable alongside `scope: OBSERVED_RESPONSE_CONSISTENCY`): empirically
similar within tolerance, never an exact common factor, never causation,
and never authorization to add component values across weapon sets. This
layer is not imported by evaluation, ranking, or verdict code and does not
influence any public Item Check result.

## Evidence orchestration (Slice 4B, internal, no product consumer)

`src/poe2value/items/contextual_evidence.py` collects one candidate's
Slice 3 physical-candidate measurements across caller-supplied contextual
observations and feeds them to the Slice 4A classifier, returning an
evidence bundle (candidate/source provenance, per-observation identity,
status, baseline/candidate outputs, deltas, unavailable list, proof with
scope/exactness, frame totals). Provenance comes only from real context:
`candidate_fingerprint` of the exact evaluated text plus the engine's
loaded revision token, source identity, and build generation; missing or
drifting provenance fails closed, restore failures propagate and stop
collection, and observations are never summed across contexts. Component
references are explicit caller input -- automatic semantic grouping into
gameplay interactions is unsupported and reported as such. No whole-build
composition exists yet and no public verdict consumes this evidence.

## Composition eligibility (Slice 4C, internal, no product consumer)

`src/poe2value/items/contextual_composition.py` answers only whether a
Slice 4B evidence bundle is comparable, complete, and internally
consistent enough to be eligible for later guarded interpretation:
`ELIGIBLE` / `NOT_ELIGIBLE` / `INSUFFICIENT_EVIDENCE`, with structured
reasons. Source identity was promoted into required proof unanimity
(candidate fingerprint, source identity, revision, generation must all
agree). Eligibility additionally requires a `COMMON_RESPONSE` proof,
every required observation measured with verified restore, and a
complete required set derived from real per-context effect-catalog
enumeration (`derive_required_scope`, no truncation). The existing
`OffenseCoverageAuditor` was not sufficient for this: it validates
primary-metric responsiveness, not component-set completeness. Unproven
coverage, subsets, unavailable/divergent/near-zero evidence, and restore
failures yield `INSUFFICIENT_EVIDENCE` (`COVERAGE_UNPROVEN`,
`SUBSET_INCOMPLETE`) or `NOT_ELIGIBLE`, never eligibility. No metric is
summed, averaged, or projected; eligibility is scope-bounded (never
whole-build) and never a product verdict.

## Tested engine revision

`97cb973f8a114d32010bc1a4195c170628771714`
