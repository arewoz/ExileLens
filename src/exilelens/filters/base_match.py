"""BaseType match contract (FILTER-09): ONE meaning from planner -> IR -> preview -> serializer -> game.

The native filter language has two string-match forms for BaseType:

    BaseType == "A" "B"     exact: the item's base type IS one of the names
    BaseType "A" "B"        partial: the item's base type CONTAINS one of the names (case-insensitive)

The partial form is a trap for a generator that lists verified base identities: 783 pinned names are substrings of other names
(`Ring` is inside `Amethyst Ring` and `Ornate Ringmail`; every `Runeforged X` contains `X`). A planner that means "this base" must
therefore say EXACT_BASE. PARTIAL_BASE_PATTERN exists for an intentional, explicit substring grouping and is never produced
implicitly: it is serialized with a marker comment so the validator can tell it apart from an accidental partial list.

`BaseCondition` is the single parser / matcher / serializer. Preview, the rule IR, the optimiser and the validator consume it; the
generator builds rules through `exact()` / `partial()`.
"""
from __future__ import annotations

import shlex
from functools import cached_property, lru_cache
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

PARTIAL_MARKER = "# PARTIAL_BASE_PATTERN"
_EXACT_OPERATORS = ("==",)
_PARTIAL_OPERATORS = ("=",)


class BaseMatch(str, Enum):
    EXACT_BASE = "EXACT_BASE"
    PARTIAL_BASE_PATTERN = "PARTIAL_BASE_PATTERN"


@dataclass(frozen=True)
class BaseCondition:
    match: BaseMatch
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.names:
            raise ValueError("a BaseType condition needs at least one name")
        for name in self.names:
            if not name or '"' in name or "\n" in name:
                raise ValueError(f"invalid BaseType name {name!r}")

    # -- serialization -------------------------------------------------------------------------------------------------------
    def serialize(self, indent: str = "\t") -> str:
        quoted = " ".join(f'"{name}"' for name in self.names)
        if self.match == BaseMatch.EXACT_BASE:
            return f"{indent}BaseType == {quoted}"
        return f"{indent}BaseType {quoted}"

    def lines(self, indent: str = "\t") -> list[str]:
        """The condition as rule lines; a partial pattern carries its marker so it can never be mistaken for an accident."""
        if self.match == BaseMatch.PARTIAL_BASE_PATTERN:
            return [f"{indent}{PARTIAL_MARKER}", self.serialize(indent)]
        return [self.serialize(indent)]

    # -- semantics (the native language) -------------------------------------------------------------------------------------
    @cached_property
    def _folded(self) -> frozenset[str]:
        return frozenset(name.casefold() for name in self.names)

    def matches(self, base_type: str) -> bool:
        item = base_type.casefold()
        if self.match == BaseMatch.EXACT_BASE:
            return item in self._folded
        return any(name in item for name in self._folded)

    # -- parsing -------------------------------------------------------------------------------------------------------------
    @staticmethod
    def parse(line: str) -> "BaseCondition | None":
        """Parse one `BaseType ...` rule line; None when the line is not a BaseType condition (cached: preview calls it per item)."""
        return _parse_cached(line)


@lru_cache(maxsize=None)
def _parse_cached(line: str) -> "BaseCondition | None":
    try:
        parts = shlex.split(line)
    except ValueError:
        return None
    if not parts or parts[0] != "BaseType":
        return None
    rest = parts[1:]
    if rest and rest[0] in _EXACT_OPERATORS:
        return BaseCondition(BaseMatch.EXACT_BASE, tuple(rest[1:]))
    if rest and rest[0] in _PARTIAL_OPERATORS:
        return BaseCondition(BaseMatch.PARTIAL_BASE_PATTERN, tuple(rest[1:]))
    if any(token in ("==", "=", "!", "!=", "!==") for token in rest):
        raise ValueError(f"unsupported BaseType operator in {line!r}")
    return BaseCondition(BaseMatch.PARTIAL_BASE_PATTERN, tuple(rest))


def exact(names) -> BaseCondition:
    return BaseCondition(BaseMatch.EXACT_BASE, tuple(names))


def partial(names) -> BaseCondition:
    return BaseCondition(BaseMatch.PARTIAL_BASE_PATTERN, tuple(names))


_legacy_partial = False


@contextmanager
def legacy_partial_emission():
    """Reproduce the pre-FILTER-09 generator (accidental partial lists) for the semantic before/after report. Never used by the product."""
    global _legacy_partial
    previous, _legacy_partial = _legacy_partial, True
    try:
        yield
    finally:
        _legacy_partial = previous


def base_line(names, indent: str = "\t") -> str:
    """Exact-identity BaseType line: the only form the planner emits for a list of verified bases."""
    if _legacy_partial:
        return partial(names).serialize(indent)
    return exact(names).serialize(indent)
