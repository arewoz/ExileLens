"""Semantic references for independently calculable PoB active effects.

Selectors are deliberately operational metadata.  ``semantic_id`` and
``cache_identity`` never depend on display-list position.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


MAX_EFFECTS = 8

#: Weapon-set calculation contexts supported by Slice 3. Arbitrary future
#: contexts are deliberately not modeled.
VALID_WEAPON_SETS = (1, 2)
MAX_WEAPON_CONTEXTS = 2


def _hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ComponentReference:
    """One PoB-native calculation component inside a socket group."""

    semantic_id: str
    group_id: str
    effect_id: str
    source_gem_id: str = ""
    source_gem_index: int | None = None
    owner: str = "PLAYER"
    stat_set_key: str = ""
    part_key: str = ""
    stage_count: int | None = None
    calculation_mode: str = "DIRECT"
    output_table: str = "mainOutput"
    group_selector: int | None = None
    effect_selector: int | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComponentReference":
        required = ("semantic_id", "group_id", "effect_id")
        if any(not isinstance(value.get(key), str) or not value.get(key) for key in required):
            raise ValueError("effect reference is missing semantic identity")
        stage = value.get("stage_count")
        if stage is not None and (isinstance(stage, bool) or not isinstance(stage, (int, float))):
            raise ValueError("effect reference has invalid stage_count")
        source_index = value.get("source_gem_index")
        if source_index is not None and (
            isinstance(source_index, bool)
            or not isinstance(source_index, (int, float))
            or int(source_index) < 1
        ):
            raise ValueError("effect reference has invalid source_gem_index")
        return cls(
            semantic_id=str(value["semantic_id"]),
            group_id=str(value["group_id"]),
            effect_id=str(value["effect_id"]),
            source_gem_id=str(value.get("source_gem_id") or ""),
            source_gem_index=int(source_index) if source_index is not None else None,
            owner=str(value.get("owner") or "PLAYER"),
            stat_set_key=str(value.get("stat_set_key") or ""),
            part_key=str(value.get("part_key") or ""),
            stage_count=int(stage) if stage is not None else None,
            calculation_mode=str(value.get("calculation_mode") or "DIRECT"),
            output_table=str(value.get("output_table") or "mainOutput"),
            group_selector=int(value["group_selector"]) if value.get("group_selector") is not None else None,
            effect_selector=int(value["effect_selector"]) if value.get("effect_selector") is not None else None,
        )

    @property
    def cache_identity(self) -> str:
        """Effect-qualified cache token; selectors are intentionally excluded."""
        return _hash(
            {
                "semantic_id": self.semantic_id,
                "group_id": self.group_id,
                "effect_id": self.effect_id,
                "source_gem_id": self.source_gem_id,
                "source_gem_index": self.source_gem_index,
                "owner": self.owner,
                "stat_set_key": self.stat_set_key,
                "part_key": self.part_key,
                "stage_count": self.stage_count,
                "calculation_mode": self.calculation_mode,
                "output_table": self.output_table,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "cache_identity": self.cache_identity}


@dataclass(frozen=True)
class CalculationContext:
    """The PoB calculation environment qualifying one component observation.

    Slice 3 models only the weapon set (1 or 2). The active skill-set id is
    carried as context identity so a cached observation can never be reused
    across skill sets, even though Slice 3 evaluates only the currently
    active skill set. This type never becomes part of ``EffectIdentity``.
    """

    weapon_set: int = 1
    active_skill_set_id: str = ""

    def __post_init__(self) -> None:
        if int(self.weapon_set) not in VALID_WEAPON_SETS:
            raise ValueError("calculation context weapon_set must be 1 or 2")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CalculationContext":
        try:
            weapon_set = int(value.get("weapon_set", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("calculation context has invalid weapon_set") from exc
        if weapon_set not in VALID_WEAPON_SETS:
            raise ValueError("calculation context weapon_set must be 1 or 2")
        skill_set = value.get("active_skill_set_id", "")
        return cls(weapon_set=weapon_set, active_skill_set_id=str(skill_set or ""))

    @property
    def token(self) -> str:
        return _hash({"weapon_set": self.weapon_set, "active_skill_set_id": self.active_skill_set_id})

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "token": self.token}


@dataclass(frozen=True)
class ContextualComponentReference:
    """A :class:`ComponentReference` qualified by its calculation context.

    Composition, not a ``semantic_id`` suffix: the same PoB effect in set 1
    and set 2 remains the same semantic effect but yields two different
    calculation observations with disjoint cache identities.
    """

    component: ComponentReference
    context: CalculationContext

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextualComponentReference":
        if not isinstance(value, Mapping):
            raise ValueError("contextual reference must be a mapping")
        component_raw = value.get("component", value.get("reference", value))
        context_raw = value.get("context", {})
        if not isinstance(component_raw, Mapping) or not isinstance(context_raw, Mapping):
            raise ValueError("contextual reference is missing component/context identity")
        return cls(
            component=ComponentReference.from_dict(component_raw),
            context=CalculationContext.from_dict(context_raw),
        )

    @property
    def cache_identity(self) -> str:
        return _hash(
            {
                "component": self.component.cache_identity,
                "context": self.context.token,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.to_dict(),
            "context": self.context.to_dict(),
            "cache_identity": self.cache_identity,
        }


def normalize_effect_catalog(payload: Mapping[str, Any], *, maximum: int = MAX_EFFECTS) -> dict[str, Any]:
    """Validate and bound a bridge catalog without manufacturing missing rows."""
    limit = max(1, min(int(maximum), MAX_EFFECTS))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    malformed = 0
    for raw in list(payload.get("effects") or [])[:limit]:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("reference"), Mapping):
            malformed += 1
            continue
        try:
            reference = ComponentReference.from_dict(raw["reference"])
        except (TypeError, ValueError):
            malformed += 1
            continue
        if reference.semantic_id in seen:
            malformed += 1
            continue
        seen.add(reference.semantic_id)
        rows.append({**dict(raw), "reference": reference.to_dict()})
    total = int(payload.get("total_effects") or len(list(payload.get("effects") or [])))
    return {
        **dict(payload),
        "effects": rows,
        "max_effects": limit,
        "total_effects": total,
        "truncated": bool(payload.get("truncated") or total > limit),
        "malformed_count": malformed,
    }


def normalize_context_catalog(payload: Mapping[str, Any], *, maximum: int = MAX_EFFECTS) -> dict[str, Any]:
    """Validate a bounded explicit component-context matrix (Slice 3 diagnostic).

    Rows carry ``reference`` (ComponentReference), ``context``
    (CalculationContext), ``status`` and ``metrics``. At most ``maximum``
    effects by ``MAX_WEAPON_CONTEXTS`` contexts are kept; anything beyond is
    reported via truncation metadata, never silently evaluated.
    """
    limit = max(1, min(int(maximum), MAX_EFFECTS))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    malformed = 0
    for raw in list(payload.get("contexts") or payload.get("component_contexts") or [])[
        : limit * MAX_WEAPON_CONTEXTS
    ]:
        if not isinstance(raw, Mapping):
            malformed += 1
            continue
        try:
            qualified = ContextualComponentReference.from_dict(raw)
        except (TypeError, ValueError):
            malformed += 1
            continue
        key = qualified.cache_identity
        if key in seen:
            malformed += 1
            continue
        seen.add(key)
        rows.append({**dict(raw), "cache_identity": key})
    total = int(payload.get("total_contexts") or len(list(payload.get("contexts") or [])))
    return {
        **dict(payload),
        "contexts": rows,
        "max_effects": limit,
        "max_weapon_contexts": MAX_WEAPON_CONTEXTS,
        "total_contexts": total,
        "truncated": bool(payload.get("truncated") or total > limit * MAX_WEAPON_CONTEXTS),
        "malformed_count": malformed,
    }
