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
) -> EvaluationContextIdentity:
    components = dict(fingerprint_components or {})
    skill = {
        key: components.get(key)
        for key in (
            "main_skill",
            "main_socket_group",
            "main_skill_id",
            "main_skill_name",
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
        worker_generation=int(worker_generation),
        ignore_socketed_mods=bool(ignore_socketed_mods),
    )
