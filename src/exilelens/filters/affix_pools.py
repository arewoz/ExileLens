"""Verified affix-pool eligibility for filter generation (FILTER-08B).

Reads the pinned PoB2 export produced by ``tools/export_poe2_affix_pools.py``.
A pool answers "can this base roll this stat family, and from which item
level?". It does NOT say an unidentified item has the stat: the native filter
cannot observe that, so callers must describe pool hits as opportunities.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from exilelens.filters.verified_bases import load_base_properties

POOLS_FILE = Path(__file__).with_name("data") / "poe2_affix_pools.json"

# Same normalisation as the exporter so base implicit lines match the same family patterns.
_NUMBER = re.compile(r"[-+]?\(?[-+]?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?\)?")


@dataclass(frozen=True)
class FamilyPool:
    """One stat family on one base: required item levels of its eligible tiers."""
    family: str
    probe_id: str
    relation: str  # DIRECT or NARROWED (see exporter)
    levels: tuple[int, ...]
    groups: int

    @property
    def first_level(self) -> int:
        return self.levels[0]

    @property
    def top_level(self) -> int:
        return self.levels[-1]

    def tiers_at(self, item_level: int) -> int:
        return sum(1 for level in self.levels if level <= item_level)


@lru_cache(maxsize=1)
def _payload() -> dict:
    payload = json.loads(POOLS_FILE.read_text(encoding="utf-8"))
    if not payload.get("pob_commit") or len(payload.get("base_pool", {})) < 1000:
        raise ValueError("PoB2 affix-pool snapshot is incomplete")
    source = json.loads((Path(__file__).with_name("data") / "poe2_bases.json").read_text(encoding="utf-8"))
    if payload["pob_commit"] != source["pob_commit"] or set(payload["base_pool"]) != set(source["bases"]):
        raise ValueError("PoB2 affix pools do not match the verified base snapshot")
    return payload


def snapshot_info() -> dict:
    payload = _payload()
    return {"pob_version": payload["pob_version"], "pob_commit": payload["pob_commit"]}


def family_definitions() -> dict[str, dict]:
    return _payload()["families"]


def family_probe(family: str) -> str:
    return family_definitions()[family]["probe_id"]


def base_tags(base: str) -> tuple[str, ...]:
    payload = _payload()
    return tuple(payload["pools"][payload["base_pool"][base]]["tags"])


@lru_cache(maxsize=None)
def pools_for(base: str) -> dict[str, FamilyPool]:
    """Every family the base can roll, keyed by family id. Unknown bases fail closed (empty)."""
    payload = _payload()
    signature = payload["base_pool"].get(base)
    if signature is None:
        return {}
    definitions = payload["families"]
    return {
        family: FamilyPool(family, definitions[family]["probe_id"], definitions[family]["relation"],
                           tuple(entry["levels"]), int(entry["groups"]))
        for family, entry in payload["pools"][signature]["families"].items()
    }


def eligible_pool(base: str, family: str, item_level: int | None = None) -> FamilyPool | None:
    pool = pools_for(base).get(family)
    if pool is None or (item_level is not None and pool.first_level > item_level):
        return None
    return pool


def implicit_families(base: str) -> tuple[str, ...]:
    """Families granted by the base's own (verified) implicit text. These are always present."""
    properties = load_base_properties().get(base)
    if not properties or not properties.get("implicit"):
        return ()
    families = []
    for line in str(properties["implicit"]).replace("\\n", "\n").split("\n"):
        text = _NUMBER.sub("#", re.sub(r"\{[^}]*\}", "", line)).strip()
        for family, patterns in _implicit_patterns().items():
            if any(p.match(text) for p in patterns):
                families.append(family)
    return tuple(dict.fromkeys(families))


@lru_cache(maxsize=1)
def _implicit_patterns() -> dict[str, tuple[re.Pattern, ...]]:
    # Mirrors the exporter's DIRECT family patterns; imported lazily so runtime has no tools/ dependency.
    from exilelens.filters import _family_patterns
    return {family: tuple(re.compile(p) for p in patterns) for family, patterns in _family_patterns.PATTERNS.items()}


@lru_cache(maxsize=None)
def universal_families(pob_class: str) -> frozenset[str]:
    """Families every base of a PoB class can roll; they carry no base-specific information."""
    names = [name for name, record in load_base_properties().items() if record["class"] == pob_class]
    if not names:
        return frozenset()
    sets = [set(pools_for(name)) for name in names]
    return frozenset(set.intersection(*sets))


def class_families(pob_class: str) -> frozenset[str]:
    names = [name for name, record in load_base_properties().items() if record["class"] == pob_class]
    return frozenset(set().union(*(set(pools_for(name)) for name in names))) if names else frozenset()
