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
discrepancy remains (`Life`, ~44 points / ~2.5%). Investigated and ruled out:
`PassiveSpecClass:BuildAllDependsAndPaths()` (the function that recomputes
`alternateClassStartNodes`/`intuitiveLeapLikeNodes` from every equipped jewel's
`jewelData`, and which `SetSelItemId` never calls) was called explicitly, unconditionally,
as a direct experiment — made no measurable difference, so it is not the (or not the
only) missing piece, and was not kept (real tree-wide cost, no proven benefit). Root
cause for this specific residual remains only partially understood. This socket is
excluded from jewel-socket discovery (`jewel_socket_is_connectivity_risky` now checks
both `intuitiveLeapLike` and `alternateClassStart`) rather than risking the small wrong
value — `excluded_connectivity_risky_socket_count` reports it. `core04_skill_native_dot.xml`'s
"From Nothing" socket (previously excluded as a precaution in the initial M1.3 slice
because PoB did not recognize it via either flag) is now correctly INCLUDED and restores
correctly, since the underlying repair fix covers it regardless of whether the flag-based
exclusion recognizes the item.

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
ExileLens redundancy; multi-second latency on larger-socket builds (up to 19 allocated
sockets on `core04_skill_native_dot.xml`) remains a known, honestly-reported boundary,
not resolved in this slice.

## Tested engine revision

`97cb973f8a114d32010bc1a4195c170628771714`
