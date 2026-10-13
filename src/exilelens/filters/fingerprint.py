"""Build Fingerprint Extractor for FILTER-01.

Extracts a complete build fingerprint from a loaded PoB2 build
for use in filter generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import Dict, List, Optional, Any

from exilelens.engine import Engine
from exilelens.filters.profiles import (
    BuildFingerprint,
    EquippedItemSummary,
    BlockerSummary,
    RepairVectorSummary,
    ThresholdEventSummary,
    ProductSlot,
    DefenseLayer,
)
from exilelens.items.potential import UpgradePotentialAnalyzer
from exilelens.items.blocker_solver import analyze_blockers, build_repair_vector


class BuildFingerprintExtractor:
    """Extracts build fingerprint from loaded PoB2 build."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.potential_analyzer = UpgradePotentialAnalyzer(engine)

    def extract(self, *, context: str = "MAP", build_path: str | None = None) -> BuildFingerprint:
        """Extract complete build fingerprint."""
        # Ensure build is loaded
        if build_path:
            self.engine.ensure_build_ready(build_path, context=context)

        # 1. Basic identity
        info_payload = self.engine.get_build_info()
        info = info_payload.get("build", info_payload)

        # 2. Equipment
        equipment_data = self.engine.get_equipment()
        equipped = self._parse_equipment(equipment_data)

        # 3. Metrics
        metrics = self.engine.get_metrics(context=context)
        metric_groups = metrics.get("normalized", {})
        normalized = {
            "offense_primary_dps": metric_groups.get("offense", {}).get("primary_dps", 0),
            "defense_ehp": metric_groups.get("defense", {}).get("ehp", 0),
            "life": metric_groups.get("defense", {}).get("life", 0),
            "energy_shield": metric_groups.get("defense", {}).get("energy_shield", 0),
            "mana": metric_groups.get("resources", {}).get("mana", 0),
            "movement_speed": metric_groups.get("resources", {}).get("movement_speed_mod", 0),
        }
        normalized.update({f"{key}_res": value for key, value in metric_groups.get("defense", {}).get("resists", {}).items()})
        raw = metrics.get("raw", {})

        # 4. Defense layer inference
        defense = metric_groups.get("defense", {})
        defense_layer = DefenseLayer.from_totals(
            defense.get("energy_shield", 0), defense.get("armour", 0), defense.get("evasion", 0), 0)

        # 5. Resistance caps
        resist_caps = self._extract_resist_caps(raw, normalized)

        # 6. Upgrade potential / blockers (sample each slot)
        blockers, repair_vector = [], RepairVectorSummary(repairs=[])

        # 7. Offense coverage
        offense_coverage = self._extract_offense_coverage(raw, normalized)

        # 8. Thresholds
        thresholds = self._extract_thresholds(normalized, resist_caps)

        # 9. Source revision
        source_revision = self._get_source_revision()

        return BuildFingerprint(
            build_name=Path(info.get("build_name") or build_path or "Unknown").stem,
            class_name=info.get("class_name") or info.get("class", "Unknown"),
            ascendancy=info.get("ascendancy", "Unknown"),
            main_skill=(info_payload.get("fingerprint") or {}).get("main_skill_name") or info.get("main_skill") or "Unknown",
            main_skill_gem=(info_payload.get("fingerprint") or {}).get("main_skill_name") or info.get("main_skill_gem", "Unknown"),
            equipped=equipped,
            offense_primary_dps=normalized.get("offense_primary_dps", 0.0),
            defense_ehp=normalized.get("defense_ehp", 0.0),
            life=normalized.get("life", 0.0),
            energy_shield=normalized.get("energy_shield", 0.0),
            mana=normalized.get("mana", 0.0),
            fire_res=normalized.get("fire_res", 0),
            cold_res=normalized.get("cold_res", 0),
            lightning_res=normalized.get("lightning_res", 0),
            chaos_res=normalized.get("chaos_res", 0),
            movement_speed=normalized.get("movement_speed", 0.0),
            resist_caps=resist_caps,
            blockers=blockers,
            repair_vector=repair_vector,
            offense_coverage=offense_coverage,
            thresholds=thresholds,
            source_revision=source_revision,
            generated_at=datetime.now(),
            defense_layer=defense_layer,
        )

    def _parse_equipment(self, equipment_data: Dict[str, Any]) -> Dict[ProductSlot, EquippedItemSummary]:
        """Parse equipment data into slot summaries."""
        slot_map = {
            "Helmet": ProductSlot.HELMET,
            "Body Armour": ProductSlot.BODY_ARMOUR,
            "Gloves": ProductSlot.GLOVES,
            "Boots": ProductSlot.BOOTS,
            "Belt": ProductSlot.BELT,
            "Amulet": ProductSlot.AMULET,
            "Ring 1": ProductSlot.RING_1,
            "Ring 2": ProductSlot.RING_2,
            "Weapon 1": ProductSlot.WEAPON_1,
            "Weapon 2": ProductSlot.WEAPON_2,
        }

        equipped = {}
        equipment = equipment_data.get("equipment")
        if isinstance(equipment, list):
            slot_items = ((item.get("physical_slot", ""), item) for item in equipment if item.get("equipped"))
        else:
            slots = equipment_data.get("slots", {})
            slot_items = ((name, data.get("item")) for name, data in slots.items()) if isinstance(slots, dict) else ()
        for pob_slot, item in slot_items:
            if pob_slot not in slot_map:
                continue
            slot = slot_map[pob_slot]
            if not item:
                continue
            raw = item.get("raw") or item.get("raw_text") or ""
            level = re.search(r"(?m)^Item Level:\s*(\d+)", raw)
            quality = re.search(r"(?m)^Quality:\s*\+?(\d+)", raw)

            equipped[slot] = EquippedItemSummary(
                slot=slot,
                base_type=item.get("base_type") or item.get("base_name", ""),
                item_class=item.get("item_class") or item.get("type", ""),
                rarity=item.get("rarity", ""),
                item_level=item.get("item_level") or (int(level.group(1)) if level else 0),
                quality=item.get("quality") or (int(quality.group(1)) if quality else 0),
                base_armour=item.get("base_armour", 0.0),
                base_evasion=item.get("base_evasion", 0.0),
                base_energy_shield=item.get("base_energy_shield", 0.0),
                base_ward=item.get("base_ward", 0.0),
                implicit_mods=item.get("implicit_mods", []),
                explicit_mods=item.get("explicit_mods", []),
            )

        return equipped

    def _infer_defense_layer(self, equipped: Dict[ProductSlot, EquippedItemSummary]) -> DefenseLayer:
        """Infer primary defense layer from equipped gear."""
        es_total = sum(item.base_energy_shield for item in equipped.values())
        ar_total = sum(item.base_armour for item in equipped.values())
        ev_total = sum(item.base_evasion for item in equipped.values())
        ward_total = sum(item.base_ward for item in equipped.values())

        return DefenseLayer.from_totals(es_total, ar_total, ev_total, ward_total)

    def _extract_resist_caps(self, raw: Dict, normalized: Dict) -> Dict[str, str]:
        """Extract resistance cap states."""
        resists = {}
        for element in ["fire", "cold", "lightning", "chaos"]:
            key = f"{element}_res"
            cap_state_key = f"{element}_res_state"

            # Try to get cap state from normalized
            if cap_state_key in normalized:
                resists[element] = str(normalized[cap_state_key])
            elif key in normalized:
                # Infer from value
                value = normalized[key]
                max_res = 75 if element != "chaos" else 75
                if value >= max_res:
                    resists[element] = "CAPPED"
                elif value >= max_res - 10:
                    resists[element] = "NEAR_CAP"
                else:
                    resists[element] = "BELOW_CAP"
            else:
                resists[element] = "UNKNOWN"

        return resists

    def _analyze_blockers(self, context: str) -> tuple[List[BlockerSummary], RepairVectorSummary]:
        """Analyze blockers across equipped slots."""
        all_blockers = []
        all_repairs = []

        sample_slots = [
            ProductSlot.WEAPON_1,
            ProductSlot.BODY_ARMOUR,
            ProductSlot.HELMET,
            ProductSlot.GLOVES,
            ProductSlot.BOOTS,
            ProductSlot.AMULET,
            ProductSlot.RING_1,
        ]

        for slot in sample_slots:
            try:
                equipment = self.engine.get_equipment()
                slot_map = {
                    ProductSlot.WEAPON_1: "Weapon 1",
                    ProductSlot.BODY_ARMOUR: "Body Armour",
                    ProductSlot.HELMET: "Helmet",
                    ProductSlot.GLOVES: "Gloves",
                    ProductSlot.BOOTS: "Boots",
                    ProductSlot.AMULET: "Amulet",
                    ProductSlot.RING_1: "Ring 1",
                }
                pob_slot = slot_map.get(slot)
                if not pob_slot:
                    continue

                slot_data = equipment.get("slots", {}).get(pob_slot, {})
                item = slot_data.get("item")
                if not item:
                    continue

                item_raw = item.get("raw_text", "")
                if not item_raw:
                    continue

                result = self.engine.evaluate_candidate(slot.value, item_raw, context=context)
                recommendation = result.get("recommendation", {})

                baseline_raw = ((recommendation.get("baseline") or {}).get("metrics")) or {}
                candidate_raw = ((recommendation.get("candidate") or {}).get("metrics")) or {}

                blockers = analyze_blockers(recommendation, baseline_raw, candidate_raw)
                repair_vector = build_repair_vector(blockers, catalog=self.potential_analyzer.catalog)

                for blocker in blockers:
                    all_blockers.append(BlockerSummary(
                        blocker_type=blocker.blocker_type,
                        metric=blocker.metric,
                        label=blocker.label,
                        severity=blocker.severity,
                        repairable=blocker.repairable,
                        repair_target=blocker.repair_target,
                        probe_id=blocker.probe_id,
                    ))

                for repair in repair_vector.repairs:
                    all_repairs.append(repair)

            except Exception:
                continue

        return all_blockers, RepairVectorSummary(repairs=all_repairs)

    def _extract_offense_coverage(self, raw: Dict, normalized: Dict) -> Dict[str, str]:
        """Extract offense coverage from metrics."""
        coverage = {}
        # Check which offense metrics are available
        offense_metrics = [
            "offense_primary_dps", "combined_dps", "total_dps", "hit_dps", "dot_dps",
            "cast_speed", "attack_speed", "crit_chance", "crit_multi",
            "spell_damage", "physical_damage", "lightning_damage", "fire_damage", "cold_damage",
        ]

        for metric in offense_metrics:
            if metric in normalized:
                coverage[metric] = "SUPPORTED"
            else:
                coverage[metric] = "UNSUPPORTED"

        return coverage

    def _extract_thresholds(self, normalized: Dict, resist_caps: Dict[str, str]) -> List[ThresholdEventSummary]:
        """Extract threshold events from normalized metrics."""
        thresholds = []

        # Resistance cap thresholds
        for element, state in resist_caps.items():
            if state == "CAPPED":
                thresholds.append(ThresholdEventSummary(
                    code="RES_CAP_REACHED",
                    metric=f"{element}_res",
                    before=None,
                    after=normalized.get(f"{element}_res"),
                    threshold=75,
                    direction="POSITIVE",
                    severity="NONE",
                    is_build_fix=False,
                    is_hard_break=False,
                ))
            elif state == "BELOW_CAP":
                thresholds.append(ThresholdEventSummary(
                    code="BELOW_CAP_UNCHANGED",
                    metric=f"{element}_res",
                    before=None,
                    after=normalized.get(f"{element}_res"),
                    threshold=75,
                    direction="NEGATIVE",
                    severity="SOFT",
                    is_build_fix=False,
                    is_hard_break=False,
                ))

        return thresholds

    def _get_source_revision(self) -> str:
        """Get source revision from engine."""
        loaded_rev = self.engine.loaded_revision
        if loaded_rev:
            return loaded_rev.token
        return "unknown"
