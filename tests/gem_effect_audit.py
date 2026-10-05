"""AMMO-01 validation: a data-derived audit of every multi-effect gem in the PoB runtime ExileLens uses.

Nothing here lists skill names. The inventory comes from the bridge's read-only ``describe_gem_effects`` (PoB's loaded
gem/skill data), the oracle is PoB itself (every selectable effect of every audited gem is calculated in several real
build contexts through the effect catalog), and the classification uses only PoB flags and PoB's own outputs:

* ``declared_no_damage``  every stat set of the effect carries ``base_deal_no_damage``;
* ``damage_flagged``      a stat set carries a damage-bearing base flag (hit / dot / attack / spell / minion);
* ``ammo_load``           ``CrossbowAmmoSkill`` skill type and declared no damage;
* offense                 the largest of CombinedDPS / TotalDPS / TotalDot / FullDotDPS PoB reports for the effect.

Classes (see ``classify_family``):

A  safe with the current resolver (an ammo family the settle step pairs, or no effect declared non-damaging)
B  correctly rejected by the truthfulness gate (declared non-damaging, PoB offense ~0, no unique damaging sibling to pair)
C  potentially vulnerable: declared non-damaging, PoB offense > 0, and the runtime would still treat it as a damage target
D  needs dedicated mechanics: declared non-damaging beside several damage-capable siblings (a redirect would be a guess)
E  intentionally measurable despite the flag: declared non-damaging yet damage-flagged with PoB offense > 0
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from exilelens.items.primary_metric import OffenseKind, resolve_primary_metric

ROOT = Path(__file__).resolve().parents[1]
EPS = 0.5
OFFENSE_FIELDS = ("CombinedDPS", "TotalDPS", "TotalDot", "FullDotDPS")
DAMAGE_FLAGS = frozenset({"hit", "dot", "attack", "spell", "minion"})

#: Real corpus builds that give the audit materially different weapon / caster contexts. Each already exists in the
#: repository; the audit only appends gem groups to their active skill set in memory.
AUDIT_CONTEXTS: tuple[tuple[str, str], ...] = (
    ("crossbow", "fixtures/builds/public_corpus/ammo01_permafrost_bolts_witchhunter.xml"),
    ("bow+quiver", "fixtures/builds/public_corpus/core04_bow_quiver.xml"),
    ("two-hand mace", "fixtures/builds/public_corpus/core04_melee_weapon.xml"),
    ("one-hand mace+shield", "fixtures/builds/public_corpus/core04_onehand_weapon.xml"),
    ("staff caster", "fixtures/builds/core04_player_ring.xml"),
    ("focus caster", "fixtures/builds/public_corpus/core04_mixed_hit_ailment.xml"),
)


# ----------------------------------------------------------------------------------------------- effect predicates


def declared_no_damage(effect: Mapping[str, Any]) -> bool:
    sets = effect.get("stat_sets") or []
    return bool(sets) and all(bool(s.get("base_deal_no_damage")) for s in sets)


def damage_flagged(effect: Mapping[str, Any]) -> bool:
    return any(flag in DAMAGE_FLAGS for s in effect.get("stat_sets") or [] for flag in s.get("base_flags") or [])


def is_ammo_load(effect: Mapping[str, Any]) -> bool:
    return "CrossbowAmmoSkill" in (effect.get("skill_types") or []) and declared_no_damage(effect)


def is_fired_candidate(effect: Mapping[str, Any]) -> bool:
    types = effect.get("skill_types") or []
    return "CrossbowSkill" in types and "CrossbowAmmoSkill" not in types


def offense_of(output: Mapping[str, Any] | None) -> float:
    return max((float((output or {}).get(field) or 0.0) for field in OFFENSE_FIELDS), default=0.0)


# --------------------------------------------------------------------------------------------------- ammo inventory


def ammo_gems(gems: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Every gem granting a ``CrossbowAmmoSkill`` effect, straight from the PoB data (no name list)."""
    return [g for g in gems if any("CrossbowAmmoSkill" in (e.get("skill_types") or []) for e in g.get("effects") or [])]


def ammo_mapping(gem: Mapping[str, Any]) -> dict[str, Any]:
    """The deterministic load -> fired mapping of one ammo gem, or a precise reason it is not deterministic."""
    effects = list(gem.get("effects") or [])
    loads = [e for e in effects if is_ammo_load(e)]
    fired = [e for e in effects if is_fired_candidate(e)]
    row: dict[str, Any] = {
        "gem_id": gem.get("gem_id"),
        "name": gem.get("name"),
        "effect_ids": [e.get("id") for e in effects],
        "load_effect": loads[0]["id"] if len(loads) == 1 else None,
        "load_index": loads[0]["index"] if len(loads) == 1 else None,
        "fired_effect": fired[0]["id"] if len(fired) == 1 else None,
        "fired_index": fired[0]["index"] if len(fired) == 1 else None,
        "load_stat_sets": [s.get("label") for s in loads[0].get("stat_sets", [])] if len(loads) == 1 else [],
        "fired_stat_sets": [s.get("label") for s in fired[0].get("stat_sets", [])] if len(fired) == 1 else [],
        "fired_parts": fired[0].get("part_count") if len(fired) == 1 else None,
        "fired_damage_flags": sorted(
            {f for s in fired[0].get("stat_sets", []) for f in s.get("base_flags", [])}
        ) if len(fired) == 1 else [],
    }
    reasons = []
    if len(loads) != 1:
        reasons.append(f"{len(loads)} load effects")
    if len(fired) != 1:
        reasons.append(f"{len(fired)} fired candidates")
    pairing = [e.get("ammo_pairing") or {} for e in loads]
    if loads and (pairing[0].get("status") != "OK" or pairing[0].get("fired_index") != row["fired_index"]):
        reasons.append(f"bridge pairing {pairing[0].get('status')}")
    row["status"] = "DETERMINISTIC" if not reasons else "NOT_DETERMINISTIC"
    row["reasons"] = reasons
    return row


# -------------------------------------------------------------------------------------------- real-PoB oracle build


def active_skill_set_span(xml_text: str) -> tuple[int, int, int]:
    """(insert_at, existing_group_count, active_set_id) for the active skill set of a PoB build."""
    active = re.search(r'<Skills\b[^>]*\bactiveSkillSet="(\d+)"', xml_text)
    set_id = int(active.group(1)) if active else 1
    start = re.search(rf'<SkillSet\b[^>]*\bid="{set_id}"[^>]*>', xml_text)
    if start is None:
        raise ValueError("build has no active SkillSet to extend")
    end = xml_text.index("</SkillSet>", start.end())
    return end, len(re.findall(r"<Skill\b", xml_text[start.end():end])), set_id


def gem_group_xml(gem: Mapping[str, Any], *, selector: int = 1, level: int = 10) -> str:
    gem_name = str(gem["name"]).replace("&", "&amp;").replace('"', "&quot;")
    return (
        f'<Skill includeInFullDPS="false" enabled="true" mainActiveSkillCalcs="{selector}" mainActiveSkill="{selector}" label="">'
        f'<Gem gemId="{gem["gem_id"]}" variantId="{gem["variant_id"]}" corruptLevel="0" enabled="true" enableGlobal1="true" '
        f'corrupted="false" nameSpec="{gem_name}" count="1" quality="0" level="{level}" enableGlobal2="true" '
        f'skillId="{gem["granted_effect_id"]}" statSetIndex="nil" statSetIndexCalcs="nil"/></Skill>'
    )


def inject_gem_groups(xml_text: str, groups: Iterable[str], *, replace: bool = False) -> tuple[str, int]:
    """Append ``groups`` to the active skill set (``replace`` drops the set's existing groups first).

    Returns (xml, number of groups that existed before the insert, 0 when replaced)."""
    insert_at, existing, set_id = active_skill_set_span(xml_text)
    block = "\n".join(groups)
    if replace:
        opening = re.search(r'<SkillSet\b[^>]*\bid="%d"[^>]*>' % set_id, xml_text)
        assert opening is not None
        return xml_text[: opening.end()] + "\n" + block + "\n" + xml_text[insert_at:], 0
    return xml_text[:insert_at] + block + "\n" + xml_text[insert_at:], existing


def measure_gem_effects(
    engine: Any, build_path: Path, gems: list[Mapping[str, Any]], scratch_dir: Path, *, level: int = 10,
) -> list[dict[str, Any]]:
    """Calculate every selectable effect of every gem in the build context ``build_path`` (one group per gem)."""
    text = build_path.read_text(encoding="utf-8")
    xml, existing = inject_gem_groups(text, (gem_group_xml(g, level=level) for g in gems))
    scratch = Path(scratch_dir) / f"audit_{build_path.stem}.xml"
    scratch.write_text(xml, encoding="utf-8")
    try:
        engine.load_build(scratch)
        rows: list[dict[str, Any]] = []
        for offset, gem in enumerate(gems):
            group = existing + 1 + offset
            catalog = engine.list_calculable_effects(indices=[group], max_effects=8)
            for effect in catalog.get("effects") or []:
                reference = effect.get("reference") or {}
                rows.append({
                    "gem_id": gem["gem_id"],
                    "gem": gem["name"],
                    "group": group,
                    "effect_id": reference.get("effect_id"),
                    "selector": reference.get("effect_selector"),
                    "status": effect.get("status"),
                    "damage_target": reference.get("damage_target", True),
                    "damage_target_reason": reference.get("damage_target_reason", ""),
                    "output": {k: (effect.get("output") or {}).get(k) for k in (*OFFENSE_FIELDS, "Speed")},
                })
        return rows
    finally:
        scratch.unlink(missing_ok=True)


# ----------------------------------------------------------------------------------------------------- classification


def gate_state(row: Mapping[str, Any]) -> str:
    """What the primary-metric resolver does if this effect were the saved main effect with PoB's output for it."""
    identity = {
        "skill_id": row["effect_id"], "skill_name": row["effect_id"], "index": 1, "damage_owner": "PLAYER",
        "output_table": "mainOutput", "damage_target": row.get("damage_target", True),
        "damage_target_reason": row.get("damage_target_reason", ""),
    }
    metrics = {k: (v or 0.0) for k, v in (row.get("output") or {}).items()}
    selection = resolve_primary_metric({"main_skill_identity": identity}, metrics)
    if selection.selected == OffenseKind.UNRESOLVED:
        return "UNRESOLVED"
    return f"MEASURED_{selection.confidence.value.upper()}"


def classify_family(gem: Mapping[str, Any], rows_by_context: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, Any]:
    """One audit row for a multi-effect gem; evidence is PoB flags plus PoB's own output in every audited context."""
    effects = {e["id"]: e for e in gem.get("effects") or []}
    best: dict[str, float] = defaultdict(float)
    best_row: dict[str, Mapping[str, Any]] = {}
    selectable: set[str] = set()
    for context_rows in rows_by_context.values():
        for row in context_rows:
            if row["gem_id"] != gem["gem_id"] or row["effect_id"] not in effects:
                continue
            selectable.add(row["effect_id"])
            value = offense_of(row.get("output"))
            if value >= best[row["effect_id"]]:
                best[row["effect_id"]] = value
                best_row[row["effect_id"]] = row
    non_damaging = [eid for eid in selectable if declared_no_damage(effects[eid])]
    damaging = [
        eid for eid in selectable
        if eid not in non_damaging and (damage_flagged(effects[eid]) or best[eid] > EPS)
    ]
    out: dict[str, Any] = {
        "gem": gem["name"],
        "gem_id": gem["gem_id"],
        "effects": [
            {
                "id": eid,
                "selectable": eid in selectable,
                "declared_no_damage": declared_no_damage(effects[eid]),
                "damage_flagged": damage_flagged(effects[eid]),
                "ammo_load": is_ammo_load(effects[eid]),
                "max_offense": round(best.get(eid, 0.0), 3),
                "gate": gate_state(best_row[eid]) if eid in best_row else None,
                "damage_target": best_row[eid].get("damage_target", True) if eid in best_row else None,
            }
            for eid in effects
        ],
        "non_damaging": sorted(non_damaging),
        "damaging_siblings": sorted(damaging),
    }
    ammo = [eid for eid in non_damaging if is_ammo_load(effects[eid])]
    others = [eid for eid in non_damaging if eid not in ammo]
    verdicts: list[tuple[str, str]] = []
    for eid in ammo:
        status = (effects[eid].get("ammo_pairing") or {}).get("status")
        verdicts.append(("A" if status == "OK" else "D", f"ammo load; bridge pairing {status}"))
    for eid in others:
        offense = best[eid]
        gate = gate_state(best_row[eid])
        # Counterfactual: what the gate would do if the bridge had not flagged the effect as a non-target.
        unguarded = gate_state({**best_row[eid], "damage_target": True, "damage_target_reason": ""})
        guard_only = offense > EPS and gate == "UNRESOLVED" and unguarded != "UNRESOLVED"
        if offense > EPS and damage_flagged(effects[eid]):
            verdicts.append(("E", "declared non-damaging but damage-flagged and PoB measures offense"))
        elif offense > EPS and gate != "UNRESOLVED":
            verdicts.append(("C", f"PoB offense {offense:.1f} on a declared non-damaging effect; gate {gate}"))
        elif len(damaging) >= 2:
            verdicts.append(("D", f"{len(damaging)} damage-capable siblings: no unique target to pair with"))
        else:
            note = "declared non-damaging; PoB offense ~0" if not guard_only else (
                f"declared non-damaging; PoB reports offense {offense:.1f} (weapon-dependent phantom) that only the "
                "damage-target guard refuses"
            )
            verdicts.append(("B", note + ("; unique damage-capable sibling exists" if len(damaging) == 1 else "")))
        if guard_only:
            out.setdefault("guard_only", []).append(eid)
    if not verdicts:
        verdicts.append(("A", "no selectable effect is declared non-damaging"))
    order = {"C": 0, "E": 1, "D": 2, "B": 3, "A": 4}
    letter = min((v[0] for v in verdicts), key=order.__getitem__)
    out["class"] = letter
    out["evidence"] = sorted({v[1] for v in verdicts if v[0] == letter})
    out["ammo_family"] = bool(ammo)
    return out


def classify_all(gems: list[Mapping[str, Any]], rows_by_context: Mapping[str, list[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    return [classify_family(g, rows_by_context) for g in gems]


def render_markdown(table: list[Mapping[str, Any]], contexts: Iterable[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for row in table:
        counts[row["class"]] += 1
    lines = [
        "| Class | Gem | Declared non-damaging selectable effect(s) | Damage-capable sibling(s) | Max PoB offense on the non-damaging effect | Evidence |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for row in sorted(table, key=lambda r: (r["class"], r["gem"])):
        if not row["non_damaging"] and row["class"] == "A":
            continue
        by_id = {e["id"]: e for e in row["effects"]}
        peak = max((by_id[eid]["max_offense"] for eid in row["non_damaging"]), default=0.0)
        lines.append(
            f"| {row['class']} | {row['gem']} | {', '.join(row['non_damaging'])} | "
            f"{', '.join(row['damaging_siblings']) or '-'} | {peak:g} | {'; '.join(row['evidence'])} |"
        )
    summary = ", ".join(f"{k}: {counts[k]}" for k in sorted(counts))
    return f"Contexts: {', '.join(contexts)}. Families: {len(table)} ({summary}).\n\n" + "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------ ammo family live validation

#: Controlled weapon perturbations of the tester's crossbow. Each edits ONE mod line to a deliberately strong value; PoB
#: decides which ammo skills respond (never assumed here).
PERTURBATIONS: tuple[tuple[str, str, str], ...] = (
    ("flat-elemental", "Adds 1 to 202 Lightning Damage", "Adds 1000 to 2000 Lightning Damage"),
    ("attack-speed", "5% increased Attack Speed", "60% increased Attack Speed"),
    ("skill-level", "+4 to Level of all Projectile Skills", "+12 to Level of all Projectile Skills"),
)


def perturbed_candidates(candidate_text: str) -> list[tuple[str, str]]:
    """One candidate per perturbation, plus ``all`` with every perturbation applied together."""
    out = []
    combined = candidate_text
    for name, old, new in PERTURBATIONS:
        if candidate_text.count(old) != 1:
            raise ValueError(f"candidate no longer contains exactly one {old!r}")
        out.append((name, candidate_text.replace(old, new)))
        combined = combined.replace(old, new)
    out.append(("all", combined))
    return out


def ammo_family_build(base_text: str, gem: Mapping[str, Any], selector: int) -> tuple[str, int]:
    """The base build with its active skill set reduced to ONE group holding ``gem`` (``selector`` saved), as the main group.

    Gear, tree and configuration are untouched. The unrelated skill groups are dropped on purpose: every PoB frame
    recalculates every group, which made each calculation ~10x slower than the ammo skill under test needs."""
    xml, existing = inject_gem_groups(base_text, [gem_group_xml(gem, selector=selector)], replace=True)
    main_group = existing + 1
    xml, count = re.subn(r'(<Build\s[^>]*?mainSocketGroup=")\d+(")', rf"\g<1>{main_group}\2", xml, count=1)
    if count != 1:
        raise ValueError("build has no mainSocketGroup attribute")
    return xml, main_group


def _pct(before: float, after: float) -> float | None:
    return None if not before else (after - before) / before * 100.0


def weapon_sensitivity_matrix(
    engine: Any,
    evaluate_item: Any,
    ammo_gem_list: list[Mapping[str, Any]],
    base_build: Path,
    candidate_text: str,
    scratch_dir: Path,
) -> list[dict[str, Any]]:
    """One row per ammo gem. ExileLens is run end to end once, with every perturbation applied together, on the build that
    saves the LOAD action. PoB itself is the oracle: the same build with the FIRED effect saved in the file, read directly
    for each perturbation separately and for the combination. Nothing is computed here."""
    base_text = base_build.read_text(encoding="utf-8")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    perturbed = perturbed_candidates(candidate_text)
    combined_name, combined_text = perturbed[-1]
    rows: list[dict[str, Any]] = []
    for index, gem in enumerate(ammo_gem_list):
        mapping = ammo_mapping(gem)
        saved_xml, _ = ammo_family_build(base_text, gem, selector=mapping["load_index"])
        gold_xml, _ = ammo_family_build(base_text, gem, selector=mapping["fired_index"])
        saved_path = scratch_dir / f"ammo_saved_{index}.xml"
        gold_path = scratch_dir / f"ammo_gold_{index}.xml"
        saved_path.write_text(saved_xml, encoding="utf-8")
        gold_path.write_text(gold_xml, encoding="utf-8")
        result = evaluate_item(combined_text, engine, build_path=str(saved_path))
        row = next(r for r in result["slot_comparisons"] if r["pob_slot"] == "Weapon 1")
        engine.load_build(gold_path)
        pob_before = dict(engine.get_metrics()["raw"])
        pob_after = {
            name: dict(engine.evaluate_item_slots(["Weapon 1"], text)["slots"][0]["candidate"]["metrics"])
            for name, text in perturbed
        }
        ex_before, ex_after = row["baseline"]["metrics"], row["candidate"]["metrics"]
        gold_after = pob_after[combined_name]
        rows.append({
            "gem": gem["name"], "load": mapping["load_effect"], "fired": mapping["fired_effect"],
            "primary_skill": row["candidate"]["primary_skill"]["skill_id"],
            "pob_before": pob_before.get("CombinedDPS"),
            "pob_delta_pct": {
                name: _pct(pob_before.get("CombinedDPS") or 0.0, metrics.get("CombinedDPS") or 0.0)
                for name, metrics in pob_after.items()
            },
            "exilelens_before": ex_before.get("CombinedDPS"), "exilelens_after": ex_after.get("CombinedDPS"),
            "exilelens_delta_pct": row["delta"]["offense"]["primary_dps"].get("percent_delta"),
            "delta_kind": row["metric_profile"]["primary_offense"]["delta_kind"],
            "verdict": row["verdict"],
            "fields_equal": all(
                abs((ex_before.get(f) or 0.0) - (pob_before.get(f) or 0.0)) <= 1e-9 * max(1.0, abs(pob_before.get(f) or 0.0))
                and abs((ex_after.get(f) or 0.0) - (gold_after.get(f) or 0.0)) <= 1e-9 * max(1.0, abs(gold_after.get(f) or 0.0))
                for f in ("CombinedDPS", "TotalDPS", "AverageDamage", "Speed")
            ),
        })
    return rows
