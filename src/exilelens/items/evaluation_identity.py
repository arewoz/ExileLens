"""Canonical identities for Item Check inputs and evaluation state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_candidate_text(raw_text: str) -> str:
    """Normalize formatting that cannot change PoB's item semantics.

    Line order and internal whitespace are preserved because both can be meaningful
    to PoB's item parser. Line endings, trailing whitespace and surrounding blank
    lines are presentation noise.
    """

    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def candidate_fingerprint(raw_text: str) -> str:
    return hashlib.sha256(canonical_candidate_text(raw_text).encode("utf-8")).hexdigest()


def context_component_fingerprint(value: Any) -> str:
    return _stable_hash(value) if value not in (None, "", {}, []) else ""


@dataclass(frozen=True)
class EvaluationContextIdentity:
    source_identity: str = ""
    source_revision: str = ""
    build_generation: int = 0
    baseline_fingerprint: str = ""
    equipment_fingerprint: str = ""
    tree_fingerprint: str = ""
    skill_context_fingerprint: str = ""
    configuration_fingerprint: str = ""
    loadout: str = ""
    item_set: str = ""
    calculation_context: str = "MAP"
    #: Slice 3: the PoB weapon set (1 or 2) this identity was observed under.
    #: Folded in so a set-1 observation can never serve a set-2 request.
    weapon_set: int = 1
    #: Active PoB skill-set id. Slice 3 evaluates only the currently active
    #: skill set, but the id participates in identity so a cached result can
    #: never cross skill sets either.
    active_skill_set_id: str = ""
    worker_generation: int = 0
    #: Folded in so a cached result computed with the opposite setting can never be
    #: served: this setting changes the measured baseline/candidate metrics, not
    #: only presentation, so it must vary the identity like any other input that
    #: changes what got measured.
    ignore_socketed_mods: bool = False

    @property
    def token(self) -> str:
        return _stable_hash(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "token": self.token}


@dataclass(frozen=True)
class EvaluationIdentity:
    context_identity: str
    candidate_fingerprint: str
    slot_context: tuple[str, ...] = ()

    @property
    def token(self) -> str:
        return _stable_hash(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "slot_context": list(self.slot_context), "token": self.token}


def identity_from_state(
    *,
    source_identity: str,
    source_revision: str,
    build_generation: int,
    baseline_fingerprint: str,
    equipment_fingerprint: str,
    tree_fingerprint: str,
    fingerprint_components: Mapping[str, Any] | None,
    loadout: str,
    item_set: str,
    calculation_context: str,
    worker_generation: int,
    ignore_socketed_mods: bool = False,
    weapon_set: int | None = None,
    active_skill_set_id: str | None = None,
) -> EvaluationContextIdentity:
    components = dict(fingerprint_components or {})
    raw_weapon_set = weapon_set if weapon_set is not None else components.get("weapon_set", 1)
    try:
        resolved_weapon_set = int(raw_weapon_set)
    except (TypeError, ValueError):
        resolved_weapon_set = 1
    if resolved_weapon_set not in (1, 2):
        resolved_weapon_set = 1
    if active_skill_set_id is not None:
        resolved_skill_set = str(active_skill_set_id or "")
    else:
        resolved_skill_set = str(components.get("active_skill_set_id") or "")
    skill = {
        key: components.get(key)
        for key in (
            "main_skill",
            "main_socket_group",
            "main_skill_id",
            "main_skill_name",
            "main_effect_semantic_id",
            "main_effect_group_id",
            "main_effect_source_gem_id",
            "main_stat_set",
            "main_stat_set_key",
            "main_part_index",
            "main_part_name",
            "main_part_key",
            "main_stage_count",
            "main_calculation_mode",
            "main_actor_id",
            "main_actor_skill",
            "main_damage_owner",
            "main_output_table",
        )
    }
    configuration = {
        "context": calculation_context,
        "config": components.get("config") or {},
        "weapon_set_alloc": components.get("weapon_set_alloc") or {},
        "hash_overrides": components.get("hash_overrides") or {},
    }
    return EvaluationContextIdentity(
        source_identity=source_identity,
        source_revision=source_revision,
        build_generation=int(build_generation),
        baseline_fingerprint=baseline_fingerprint,
        equipment_fingerprint=equipment_fingerprint,
        tree_fingerprint=tree_fingerprint,
        skill_context_fingerprint=context_component_fingerprint(skill),
        configuration_fingerprint=context_component_fingerprint(configuration),
        loadout=loadout,
        item_set=item_set,
        calculation_context=calculation_context,
        weapon_set=resolved_weapon_set,
        active_skill_set_id=resolved_skill_set,
        worker_generation=int(worker_generation),
        ignore_socketed_mods=bool(ignore_socketed_mods),
    )
