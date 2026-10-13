"""Deterministic BaseType collision corpus (FILTER-09).

A collision is an ordered pair (inner, outer) of distinct pinned base names where `inner` is a case-insensitive substring of `outer`.
Under the native partial form `BaseType "inner"` the filter also matches `outer`; under `BaseType == "inner"` it does not.
Built from the pinned catalog only (verified equipment bases plus the pinned special currency names); no prefix is special-cased:
`Runeforged` / `Runemastered` are simply the two largest families that the enumeration finds.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from exilelens.filters.verified_bases import PINNED_SPECIAL_BASES, load_base_properties, native_class


@dataclass(frozen=True)
class Collision:
    inner: str
    outer: str
    kind: str          # prefix | suffix | infix
    family: str        # the extra text of a prefix collision ("Runeforged"), else "(suffix)" / "(infix)"


@lru_cache(maxsize=1)
def catalog_names() -> tuple[str, ...]:
    return tuple(sorted(set(load_base_properties()) | set(PINNED_SPECIAL_BASES)))


@lru_cache(maxsize=1)
def collisions() -> tuple[Collision, ...]:
    names = catalog_names()
    folded = [(n.casefold(), n) for n in names]
    out = []
    for inner_f, inner in folded:
        for outer_f, outer in folded:
            if inner == outer or inner_f == outer_f or inner_f not in outer_f:
                continue
            at = outer_f.index(inner_f)
            if at == 0:
                kind, family = "prefix", "(suffix text)"
            elif at + len(inner_f) == len(outer_f):
                kind, family = "suffix", outer[:at].strip()
            else:
                kind, family = "infix", "(infix)"
            out.append(Collision(inner, outer, kind, family))
    return tuple(out)


def summary() -> dict:
    items = collisions()
    families = Counter(c.family for c in items if c.kind == "suffix")
    outer_classes = Counter(native_class(c.outer) or "(special)" for c in items)
    return {"pairs": len(items), "distinct_inner": len({c.inner for c in items}), "distinct_outer": len({c.outer for c in items}),
            "by_kind": dict(Counter(c.kind for c in items)), "top_families": dict(families.most_common(8)),
            "outer_native_classes": dict(outer_classes.most_common(12))}
