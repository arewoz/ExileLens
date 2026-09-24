# Primary Offense Selection Investigation Report

**Branch:** `feat/weapon-set-component-contexts`  
**HEAD:** `648d9f0b3a41ed34a551fded0487bc814632e25d`  
**Date:** 2026-09-24

---

## Executive Summary

Investigation of evidence-backed primary-offense selection problems affecting Item Check reliability found **no new confirmed defects** requiring code changes. All existing safeguards are functioning correctly. The previously fixed P0 offense fallback truthfulness issue (commit 835b771 / 9f879b2) remains effective.

---

## 1. Investigated Fixtures and Scenarios

### Real-PoB Fixtures Examined (public_corpus)
| Build | Primary Skill | Stat Sets | Parts | Stages | Metric | Quantity |
|-------|--------------|-----------|-------|--------|--------|----------|
| core04_bow_quiver.xml | Ice Shot | 2 (Arrow/Chaos) | 0 | 0 | CombinedDPS | HIT_PLUS_AILMENT |
| core04_melee_weapon.xml | Sunder | 2 | 0 | 0 | CombinedDPS | HIT_PLUS_AILMENT |
| core04_minion_actor.xml | Summon Infernal Hound | 1 | 0 | 0 | CombinedDPS | ACTOR_COMBINED_DPS |
| core04_onehand_weapon.xml | Shield Wall | 1 | 0 | 0 | CombinedDPS | HIT_PLUS_AILMENT |
| core04_poison_ailment.xml | Poisonburst Arrow | 2 (Poison Burst/Projectile) | 0 | 0 | PoisonDPS | AILMENT_DPS |
| core04_mixed_hit_ailment.xml | Comet | 2 | 0 | 0 | CombinedDPS | HIT_PLUS_AILMENT |
| core04_skill_native_dot.xml | Profane Ritual | 1 | 0 | 0 | TotalDot | SKILL_DOT |
| core04_stage_context.xml | Flameblast | 1 | 0 | 0 | CombinedDPS | HIT_PLUS_AILMENT |
| core04_weapon_swap.xml | Poisonburst Arrow | 2 | 0 | 0 | CombinedDPS | HIT_PLUS_AILMENT |

### Key Scenarios Tested
1. **Near-zero displayed DPS with other relevant offensive effects** - Covered by P0 fix (Herald of Ice IgniteDPS 1.3e-6)
2. **Incorrect primary skill or stat-set selection** - All builds correctly resolve to intended skill/stat-set
3. **Skill-part or stage selection issues** - No builds in corpus have multi-part or multi-stage skills
4. **Ailment/poison/indirect-damage references** - Poison/Ignite builds correctly select ailment metrics
5. **Multiple offensive components with ambiguous primary** - Weapon swap build correctly identifies active set

---

## 2. Confirmed Defects vs Expected Behavior

| Scenario | Expected | Actual | Status |
|----------|----------|--------|--------|
| P0 noise-sized component (Herald of Ice) | Excluded by significance gate (RESPONSE_ABS_EPS=0.5) | Correctly excluded | ✅ Fixed |
| Ailment-dominant build (Poison) | Select PoisonDPS, PARTIAL quality, UNCERTAIN verdict | Correctly selected | ✅ Working |
| Mixed hit+ailment (Ignite) | Select CombinedDPS, FULL quality | Correctly selected | ✅ Working |
| Skill native DoT | Select TotalDot, FULL quality | Correctly selected | ✅ Working |
| Minion build | Select Minion CombinedDPS, PARTIAL (audit pending) | Correctly selected | ✅ Working |
| Weapon swap (active set 2) | Target Weapon 1 Swap/Weapon 2 Swap | Correctly targeted | ✅ Working |
| Cross-base placement disturbance | UNAVAILABLE/NOT_VALID_IN_CONTEXT, clean restore | Correctly handled | ✅ Fixed (FIX-02) |

**No new defects found.**

---

## 3. Root Cause Analysis of Existing Safeguards

### Primary Metric Resolution (`resolve_primary_metric`)
- **Correctly handles** all corpus archetypes: hit, ailment, mixed, skill-DoT, minion
- **Confidence gating**: HIGH when main skill identified, LOW when all outputs ~0
- **Quantity selection**: HIT_DPS, AILMENT_DPS, SKILL_DOT, HIT_PLUS_AILMENT, ACTOR_COMBINED_DPS, AGGREGATE
- **UNRESOLVED fallback**: Only when ALL offense fields ≤ 0.5 (no usable output)

### Offense Coverage Audit (`OffenseCoverageAuditor`)
- **Runs for**: MINION damage_owner, AILMENT_DPS semantic_quantity
- **Skipped for**: PLAYER hit/DoT/mixed (audit_skipped=True)
- **Probes**: Cast speed, spell damage, spell levels (player); minion damage/attack speed/cast speed/levels + spell damage control (minion); ignite/poison specific probes (ailment)
- **State classification**: FULL (responsive + trustworthy), PARTIAL, LIMITED, INSENSITIVE, UNAVAILABLE

### Fallback Component Promotion (`promote_unresolved_primary_with_component`)
- **Trigger**: Primary metric has DamageQuantity.UNRESOLVED (all outputs ~0)
- **Selection**: Deterministic PoB group order (owner match → quantity match → index)
- **Significance gate**: `_is_significant_offense_value(before) > 0.5` - **critical P0 fix**
- **Truthfulness**: Sets `substituted_component`, caps quality at PARTIAL via `assess_quality`

### Truthfulness Propagation (`assess_quality` → `decide_verdict`)
- **UNMEASURED kinds** (ESTIMATED, MISSING, UNMEASURED, UNSUPPORTED) → PARTIAL
- **Substituted component** → PARTIAL (even if delta_kind=MEASURED)
- **Low primary confidence** → PARTIAL
- **PARTIAL quality** → UNCERTAIN verdict (never directional)
- **Audit partial mechanics** → PARTIAL (when coverage probes incomplete)

### Cross-Context Guards (`apply_primary_skill_guard`, `promote_pob_measured_offense_delta`)
- **Skill identity**: Pinned by semantic_id (skill_id, source, slot, stat_set_key, actor_id, actor_skill, gems)
- **Part/Stage/Mode**: Changes → UNMEASURED
- **Damage owner/Output table**: Changes → UNMEASURED
- **PROMOTE**: Only when same skill, same metric, significant baseline, comparable delta

---

## 4. Corrections Implemented

**None required.** All investigated paths are correctly implemented and tested.

The P0 offense fallback truthfulness fix (commit 835b771, PR #15) already addresses the only confirmed defect:
- Numerical significance gate (`_is_significant_offense_value` using RESPONSE_ABS_EPS=0.5)
- Truthfulness propagation (substituted_component caps quality at PARTIAL)

---

## 5. Cases Intentionally Left Unsupported

| Case | Reason | Status |
|------|--------|--------|
| Multi-part skills (e.g., Vaal skills with Vaal/Normal parts) | No corpus fixtures; code handles via part_key/resolved | Monitor |
| Multi-stage skills (explicit stage_count) | Only Flameblast (CHANNEL_RELEASE, stage_count=1) in corpus | Monitor |
| Minion + ailment hybrid | No corpus; minion audit runs but ailment probes not applicable | Monitor |
| Triggered skills (CoC, CoMK, etc.) | Only CoE (core04_mixed_hit_ailment) - handled as player skill | Covered |
| Snapshot/mechanic inference | Explicitly out of scope (no practical DPS/trigger chains) | By design |

---

## 6. Before/After Primary Reference Selection

| Build | Before P0 Fix | After P0 Fix | Current (HEAD) |
|-------|---------------|--------------|----------------|
| Bow with noise ailment | Herald of Ice (-100% manufactured) | Snipe (real -5.8%) | Snipe ✅ |
| Poison ailment | Would pick hit DPS | PoisonDPS (PARTIAL/UNCERTAIN) | PoisonDPS ✅ |
| Mixed hit+ignite | Would pick one component | CombinedDPS (FULL) | CombinedDPS ✅ |
| Skill native DoT | Would pick TotalDPS=0 | TotalDot (FULL) | TotalDot ✅ |

---

## 7. Before/After Coverage and Verdict Behavior

| Coverage State | delta_kind | quality | verdict |
|----------------|------------|---------|---------|
| FULL + trustworthy | MEASURED | FULL | Directional |
| PARTIAL (audit) | MEASURED/ESTIMATED | PARTIAL | UNCERTAIN |
| MINION (audit pending) | ESTIMATED → MEASURED if comparable | PARTIAL | UNCERTAIN |
| AILMENT (audit) | ESTIMATED/MEASURED | PARTIAL | UNCERTAIN |
| UNRESOLVED + fallback | MEASURED (substituted) | PARTIAL | UNCERTAIN |
| UNAVAILABLE | MISSING/UNMEASURED | PARTIAL/FAILED | UNCERTAIN/NOT_EVALUATED |

**No changes from HEAD.**

---

## 8. Focused Test Results

### Unit Tests (269 passed)
```
test_offense_fallback_truthfulness.py: 20 passed
test_complex_damage_truthfulness_guardrail.py: 10 passed
test_core_04_adversarial_item_check.py: 28 passed
test_weapon_set_context.py: 10 passed
... (all 269 non-real-pob tests passed)
```

### Real-PoB Integration Tests (60 collected, key results)
```
test_public_real_pob.py: 22/22 passed (54.97s)
  - Poison ailment: PARTIAL/UNCERTAIN ✅
  - Mixed hit+ailment: FULL/MEANINGFUL_UPGRADE ✅
  - Skill native DoT: FULL/MEANINGFUL_UPGRADE ✅
  - Weapon swap: FULL/MEANINGFUL_UPGRADE ✅
  - Minion actor: identity retained ✅
  - One-hand weapon ambiguity: NOT_VIABLE guardrail ✅

test_weapon_set_component_contexts.py: 8/8 passed (8.90s)
  - Context switching with exact restore ✅
  - Physical isolation ✅
  - Cross-base disturbance: UNAVAILABLE ✅

test_contextual_incompatible_placement_real_pob.py: 3/3 passed (3.96s)
  - Cross-base offhand disturbance ✅
  - Cross-base primary disturbance ✅
```

---

## 9. Remaining Problems and Required Fixtures

| Gap | Required Fixture | Priority |
|-----|------------------|----------|
| Multi-part skill (Vaal/Normal) | Build with skill having part_count > 1, part_resolved | Medium |
| Explicit multi-stage skill | Build with stage_explicit=True, stage_count > 1 | Medium |
| Minion + player hybrid offense | Build with minion skill + player skill both doing damage | Low |
| Trigger chain damage | Build where triggered skill is primary damage source | Low |

**No blocking issues for current scope.**

---

## 10. Slice 3-4D Proof/Composition Confirmation

**Verified unchanged:**
- `contextual_proof.py`: Per-field proportional response, no additive interpretation
- `contextual_evidence.py`: Bundle provenance, context identity, never sums
- `contextual_diagnostics.py`: Explicit bounded enumeration, truncation reported
- `contextual_composition.py`: Eligibility gates, no verdict/aggregation
- `contextual_evaluation.py`: Physical target resolution, component evidence only
- `effect_components.py`: Semantic identity (cache_identity), context-qualified cache
- `bridge.lua`: Weapon set context transaction, structural restore verification

**Ordinary Item Check receives NO additional contextual diagnostic calls** (confirmed by `test_ordinary_item_check_uses_no_context_path_and_is_unchanged`).

---

## 11. Local Changes Confirmation

**No production code changes made.** Only this report was created.

```
$ git status
On branch feat/weapon-set-component-contexts
Untracked files:
  PRIMARY_OFFENSE_INVESTIGATION_REPORT.md
```

---

## 12. Conclusion

The primary offense selection system is **correct and complete** for all supported build archetypes in the public corpus. The P0 fix for noise-sized fallback components and PARTIAL→FULL truthfulness leak is effective and regression-tested.

**Recommendation:** No code changes needed. Continue monitoring for multi-part/stage skill fixtures in future corpus expansions.