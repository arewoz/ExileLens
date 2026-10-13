"""Native ground-base registry: which names may appear in a native `BaseType == "..."` condition.

The two universes are different things and must never be confused:

  POB_INTERNAL_ITEM_BASES      PoB2's `itemBases` table (the pinned `poe2_bases.json`). It exists to CALCULATE: PoB synthesises bases
                               (`Energy Blade One Handed`, `Shrine Sceptre (Purity of Fire)`), carries game objects that never lie on the
                               ground (Fishing Rod, incursion limbs) and developer items. Presence there says nothing about the filter.
  NATIVE_FILTER_GROUND_BASES   names the game's own filter parser accepts AND an item can actually carry on the ground.

Only the second may be serialized. The registry (`data/poe2_native_ground_bases.json`) is the single source for it. It is built offline by
`scripts/filter_native_registry.py` from committed evidence (`data/poe2_native_base_evidence.json`: the PoE2DB item-class listings and per-item
pages, i.e. the game's BaseItemTypes) plus the pinned PoB2 catalog; PoB2 alone never establishes validity. Anything the evidence does not
settle is AMBIGUOUS / UNKNOWN and fails closed: it is not in the ground set, so it can neither be generated nor serialized.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

REGISTRY_FILE = Path(__file__).with_name("data") / "poe2_native_ground_bases.json"
EVIDENCE_FILE = Path(__file__).with_name("data") / "poe2_native_base_evidence.json"


class Status(str, Enum):
    GROUND_FILTER_VALID = "GROUND_FILTER_VALID"
    POB_SYNTHETIC = "POB_SYNTHETIC"
    NON_GROUND_GAME_OBJECT = "NON_GROUND_GAME_OBJECT"
    SPECIAL_OBJECT_NOT_FILTERABLE_AS_BASE = "SPECIAL_OBJECT_NOT_FILTERABLE_AS_BASE"
    AMBIGUOUS = "AMBIGUOUS"
    STALE_OBSOLETE = "STALE_OBSOLETE"
    UNKNOWN = "UNKNOWN"


# PoB-only names: PoB builds them in code (ImportTab.lua / Item.lua) or splits one game base into variants. The real game name is given.
POB_SYNTHETIC = {
    "Energy Blade One Handed": ("Energy Blade", "PoB synthesises it in Item.lua / ImportTab.lua for Energy Blade calculations; the game's "
                                "base is `Energy Blade` (a skill-spawned weapon, not_for_sale) and PoE2DB has no such page"),
    "Energy Blade Two Handed": ("Energy Blade", "same as `Energy Blade One Handed`"),
    "Shrine Sceptre (Purity of Cold)": ("Shrine Sceptre", "PoB splits the one game base `Shrine Sceptre` by granted skill; the game name "
                                                         "carries no parenthesis"),
    "Shrine Sceptre (Purity of Fire)": ("Shrine Sceptre", "same as `Shrine Sceptre (Purity of Cold)`"),
    "Shrine Sceptre (Purity of Lighting)": ("Shrine Sceptre", "same as `Shrine Sceptre (Purity of Cold)`"),
}

# Names the repository once declared (community filter text) that are no longer in the game; kept in the registry so they stay STALE_OBSOLETE
# instead of silently becoming UNKNOWN.
HISTORICAL_SPECIAL_NAMES = ("Alchemy Shard",)

# Real game BaseItemTypes (the parser accepts the name) that no item carries on the ground, or that are developer objects.
NON_GROUND = {
    "Energy Blade": "skill-spawned weapon of the Energy Blade buff, tagged not_for_sale; never drops",
    "Ethereal Blade": "tagged not_for_sale; no unique or drop source found in the item pages",
    "Keyblade": "developer item (metadata `TwoHandSwordDev`), tagged not_for_sale",
    "Fishing Rod": "fishing tool of class `Fishing Rods` (not_for_sale); not an equipment drop and not a generated-filter class",
}
NON_GROUND_CLASS_PREFIXES = ("Transcendent ",)   # incursion limbs: class `Transcendent Arm` / `Transcendent Leg`, unique-generation only

# not_for_sale bases that exist because a UNIQUE uses them: they can only be seen as Rarity Unique. Valid names, scope `unique_only`.
UNIQUE_ONLY_TAGS = ("demigods",)
UNIQUE_ONLY_CLASSES = ("Jewels",)


@dataclass(frozen=True)
class Entry:
    name: str
    status: Status
    native_class: str | None        # the Class condition value the item carries in game (None if not ground-valid)
    pob_class: str | None
    scope: str                      # "any" | "unique_only" | ""
    confidence: str                 # "high" | "medium" | "low"
    source: str
    drop_level: int | None
    note: str
    real_name: str | None = None    # for POB_SYNTHETIC: the game's own name

    @property
    def ground_valid(self) -> bool:
        return self.status is Status.GROUND_FILTER_VALID


def _entry_from_json(name: str, raw: dict) -> Entry:
    return Entry(name, Status(raw["status"]), raw.get("class"), raw.get("pob_class"), raw.get("scope", ""), raw["confidence"], raw["source"],
                 raw.get("drop_level"), raw.get("note", ""), raw.get("real_name"))


@lru_cache(maxsize=1)
def registry_meta() -> dict:
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if k != "entries"}


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Entry]:
    """Fail closed: an unreadable or malformed registry means no name is ground-valid (generation then refuses), never 'everything is'."""
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, dict) or not data.get("registry_version") or not data.get("pob_commit"):
        raise ValueError("native ground-base registry is incomplete")
    out = {name: _entry_from_json(name, raw) for name, raw in entries.items()}
    bad = [n for n, e in out.items() if e.ground_valid and not e.native_class]
    if bad:
        raise ValueError(f"ground-valid registry entries without a native class: {bad[:5]}")
    return out


@lru_cache(maxsize=1)
def ground_bases() -> frozenset[str]:
    return frozenset(name for name, e in load_registry().items() if e.ground_valid)


def entry_of(name: str) -> Entry | None:
    return load_registry().get(name)


def is_ground_base(name: str) -> bool:
    return name in ground_bases()


def status_of(name: str) -> Status:
    entry = load_registry().get(name)
    return entry.status if entry else Status.UNKNOWN


def rejection_reason(name: str) -> str:
    """Human-readable cause of a rejected name, for diagnostics."""
    entry = load_registry().get(name)
    if entry is None:
        return "UNKNOWN: not in the native ground-base registry (never established as a game base)"
    detail = f"{entry.status.value}: {entry.note}" if entry.note else entry.status.value
    if entry.real_name:
        detail += f" [game name: {entry.real_name}]"
    return detail


def partition_base_types(names, native_class: str | None = None) -> tuple[list[str], list[tuple[str, str]]]:
    """Split a BaseType list into (verified-valid, [(rejected name, reason)]), keeping the input order.

    With `native_class` a ground-valid name of another native class is rejected too: the rule's Class would never match it."""
    valid: list[str] = []
    rejected: list[tuple[str, str]] = []
    for name in names:
        entry = load_registry().get(name)
        if entry is not None and entry.ground_valid:
            if native_class is not None and entry.native_class != native_class:
                rejected.append((name, f"native class is {entry.native_class!r}, not {native_class!r}"))
            else:
                valid.append(name)
        else:
            rejected.append((name, rejection_reason(name)))
    return valid, rejected


# statuses for which no item on the ground can carry the name: leaving it out of a grouped rule cannot change what the rule matches
_PROVABLY_ABSENT = frozenset({Status.POB_SYNTHETIC, Status.NON_GROUND_GAME_OBJECT, Status.STALE_OBSOLETE,
                              Status.SPECIAL_OBJECT_NOT_FILTERABLE_AS_BASE})


def partition_for_emission(names) -> tuple[list[str], list[tuple[str, str]]]:
    """Names to write into ONE grouped BaseType rule: (valid names in input order, [(excluded name, reason)]).

    Exclusion is only allowed where it provably keeps the rule's meaning (the name cannot be on a ground item). A name the registry cannot
    establish at all (AMBIGUOUS / UNKNOWN) may be a real item, so dropping it could silently hide or mis-style it: that blocks generation."""
    valid: list[str] = []
    excluded: list[tuple[str, str]] = []
    unsafe: list[dict] = []
    for name in names:
        entry = load_registry().get(name)
        if entry is not None and entry.ground_valid:
            valid.append(name)
        elif entry is not None and entry.status in _PROVABLY_ABSENT:
            excluded.append((name, rejection_reason(name)))
        else:
            unsafe.append({"name": name, "line": 0, "rule": "(grouped BaseType rule)", "reason": rejection_reason(name)})
    if unsafe:
        raise NativeBaseTypeBlocked(unsafe)
    if not valid:
        raise NativeBaseTypeBlocked([{"name": ex[0], "line": 0, "rule": "(grouped BaseType rule)",
                                      "reason": "every name of the rule is excluded; " + ex[1]} for ex in excluded[:1]])
    return valid, excluded


class NativeBaseTypeBlocked(ValueError):
    """Generation would write a BaseType the native parser may reject (or one with no ground identity)."""

    def __init__(self, violations: list[dict]):
        self.violations = violations
        first = violations[0]
        lines = ["FILTER GENERATION BLOCKED", "Invalid native BaseType:", f"  {first['name']}", "", "Source:",
                 f"  {first['reason']}", "", "Rule:", f"  {first['rule'] or '(unnamed)'} (line {first['line']})"]
        if len(violations) > 1:
            lines += ["", f"{len(violations) - 1} further invalid BaseType value(s): " + ", ".join(v["name"] for v in violations[1:6])]
        super().__init__("\n".join(lines))


_QUOTED = re.compile(r'"([^"\n]+)"')
_BLOCK = ("Show", "Hide", "Minimal")


def base_type_violations(filter_text: str, *, registry: dict[str, Entry] | None = None) -> list[dict]:
    """Every BaseType value of a filter text that is not a ground-valid registry name (one record per occurrence).

    An explicit PARTIAL_BASE_PATTERN rule is held to the weaker, still parser-relevant standard: the pattern must occur in at least one
    ground-valid name."""
    from exilelens.filters.base_match import PARTIAL_MARKER
    reg = load_registry() if registry is None else registry
    out: list[dict] = []
    rule_name = ""
    pending_comment = ""
    block: list[tuple[int, str]] = []

    def flush() -> None:
        partial_rule = any(content == PARTIAL_MARKER for _, content in block)
        for number, content in block:
            keyword, _, params = content.partition(" ")
            if keyword != "BaseType":
                continue
            for name in _QUOTED.findall(params):
                if partial_rule:
                    # a substring pattern is not an identity, but the parser still needs at least one real base containing it
                    folded = name.casefold()
                    if any(folded in g.casefold() for g, e in reg.items() if e.ground_valid):
                        continue
                    out.append({"name": name, "line": number, "rule": rule_name,
                                "reason": "PARTIAL pattern matches no ground-valid base name"})
                    continue
                entry = reg.get(name)
                if entry is None or not entry.ground_valid:
                    out.append({"name": name, "line": number, "rule": rule_name,
                                "reason": rejection_reason(name) if registry is None else (
                                    f"{entry.status.value}: {entry.note}" if entry else "UNKNOWN: not in the registry")})

    for number, raw in enumerate(filter_text.splitlines(), 1):
        content = raw.strip()
        if content in _BLOCK:
            flush()
            block = []
            rule_name = pending_comment
            pending_comment = ""
        elif content == PARTIAL_MARKER:
            block.append((number, content))
        elif content.startswith("#"):
            pending_comment = content.lstrip("# ").strip() if not content.startswith("#====") and not content.startswith("# [[") else pending_comment
        elif content:
            block.append((number, content))
    flush()
    return out


def assert_native_base_types(filter_text: str) -> None:
    """The fail-closed gate every serialization passes: raises NativeBaseTypeBlocked instead of returning a filter the game may reject."""
    violations = base_type_violations(filter_text)
    if violations:
        raise NativeBaseTypeBlocked(violations)


def summary() -> dict:
    """Counts for reports: per status, plus ground-valid per scope."""
    counts: dict[str, int] = {}
    scopes: dict[str, int] = {}
    for entry in load_registry().values():
        counts[entry.status.value] = counts.get(entry.status.value, 0) + 1
        if entry.ground_valid:
            scopes[entry.scope] = scopes.get(entry.scope, 0) + 1
    return {"entries": len(load_registry()), "by_status": counts, "ground_by_scope": scopes, **registry_meta()}


# -- registry construction (offline; used by scripts/filter_native_registry.py and its tests) -------------------------------------------------
SOURCE_CODE = "poe2db:class-listing+item-page"
SOURCES = {
    SOURCE_CODE: "PoE2DB (https://poe2db.tw/us) item-class listing and item page: the game's BaseItemTypes (BaseType, Class, DropLevel, Tags)",
    "curated:non-ground": "PoE2DB item page shows a real BaseItemTypes name that no item carries on the ground (see note)",
    "poe2db:page-absent": "PoE2DB has no page for the name; PoB2 builds it in code",
    "poe2db:acquisition": "PoE2DB item page: Acquisition = Not in game",
    "none": "no independent evidence",
}


def pob_native_class(name: str, pob_class: str) -> str | None:
    from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS
    if pob_class == "Shield":
        return "Bucklers" if "Buckler" in name else "Shields"
    return next((native for native, pob in FILTER_TO_POB_CLASS.items() if pob == pob_class), None)


def _variants(ev: dict) -> list[dict]:
    return ev.get("variants") or [ev]


def classify_pob_base(name: str, pob_class: str, pob_tags: list[str], ev: dict | None) -> dict:
    """One PoB2 base -> registry entry (a plain dict). PoB2 data alone never makes a name ground-valid."""
    base = {"pob_class": pob_class}

    def done(status: Status, source: str, confidence: str, *, cls=None, scope="", note="", real=None, drop=None) -> dict:
        out = {**base, "status": status.value, "source": source, "confidence": confidence}
        if cls:
            out["class"] = cls
        if scope:
            out["scope"] = scope
        if note:
            out["note"] = note
        if real:
            out["real_name"] = real
        if drop is not None:
            out["drop_level"] = drop
        return out

    absent = ev is None or ev.get("page") == "absent"
    if name in POB_SYNTHETIC:
        real, why = POB_SYNTHETIC[name]
        return done(Status.POB_SYNTHETIC, "poe2db:page-absent" if absent else "none", "high" if absent else "medium", note=why, real=real)
    if absent:
        return done(Status.UNKNOWN, "none", "low", note="no game item page and not a known PoB synthetic name")
    if ev.get("acquisition") == "Not in game":
        return done(Status.STALE_OBSOLETE, "poe2db:acquisition", "high", note="PoE2DB acquisition: Not in game", drop=ev.get("drop_level"))
    page_class = ev.get("class") or ""
    if page_class.startswith(NON_GROUND_CLASS_PREFIXES):
        return done(Status.NON_GROUND_GAME_OBJECT, "curated:non-ground", "high",
                    note=f"game class `{page_class}` (incursion limb): unique-generation only, never a ground item", drop=ev.get("drop_level"))
    if name in NON_GROUND:
        return done(Status.NON_GROUND_GAME_OBJECT, "curated:non-ground", "medium", note=NON_GROUND[name], drop=ev.get("drop_level"))
    native = pob_native_class(name, pob_class)
    if native is None:
        return done(Status.NON_GROUND_GAME_OBJECT, "curated:non-ground", "medium",
                    note=f"PoB class `{pob_class}` has no native equipment class in the generator", drop=ev.get("drop_level"))
    variants = _variants(ev)
    matching = [v for v in variants if native in (v.get("class") or "")]
    if not matching:
        return done(Status.AMBIGUOUS, SOURCE_CODE, "low", note=f"PoE2DB class {sorted({v.get('class') for v in variants})} does not contain "
                    f"the expected native class `{native}`")
    if not ev.get("listed"):
        return done(Status.AMBIGUOUS, SOURCE_CODE, "low", note="has an item page but is absent from every item-class listing")
    drop = matching[0].get("drop_level")
    for_sale = [v for v in matching if "not_for_sale" not in v.get("tags", [])]
    if for_sale:
        return done(Status.GROUND_FILTER_VALID, SOURCE_CODE, "high", cls=native, scope="any", drop=drop)
    tags = {t for v in matching for t in v.get("tags", [])}
    if tags & set(UNIQUE_ONLY_TAGS) or native in UNIQUE_ONLY_CLASSES:
        return done(Status.GROUND_FILTER_VALID, SOURCE_CODE, "medium", cls=native, scope="unique_only", drop=drop,
                    note="not_for_sale base that exists for a unique item: only ever seen as Rarity Unique")
    return done(Status.AMBIGUOUS, SOURCE_CODE, "low", note="tagged not_for_sale with no unique-item explanation")


def classify_special(name: str, ev: dict | None) -> dict:
    """A non-equipment exact name (currency, shards, incubators): class comes from the game page, not from an assumption."""
    base = {"pob_class": None}
    if ev is None or ev.get("page") == "absent":
        return {**base, "status": Status.UNKNOWN.value, "source": "none", "confidence": "low", "note": "no game item page"}
    if ev.get("acquisition") == "Not in game":
        return {**base, "status": Status.STALE_OBSOLETE.value, "source": "poe2db:acquisition", "confidence": "high",
                "note": "PoE2DB acquisition: Not in game", "class": ev.get("class")}
    if not ev.get("listed"):
        return {**base, "status": Status.AMBIGUOUS.value, "source": SOURCE_CODE, "confidence": "low",
                "note": "has an item page but is absent from every item-class listing"}
    return {**base, "status": Status.GROUND_FILTER_VALID.value, "source": SOURCE_CODE, "confidence": "high", "class": ev["class"],
            "scope": "any", "drop_level": ev.get("drop_level")}


def build_registry(pob_bases: dict[str, str], pob_tags: dict[str, list[str]], special_names, evidence: dict, pob_meta: dict) -> dict:
    items = evidence["items"]
    entries: dict[str, dict] = {}
    for name in sorted(pob_bases):
        entries[name] = classify_pob_base(name, pob_bases[name], pob_tags.get(name, []), items.get(name))
    for name in sorted(special_names):
        if name in entries:
            continue
        entries[name] = classify_special(name, items.get(name))
    counts: dict[str, int] = {}
    for entry in entries.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return {"schema_version": 1, "registry_version": "NATIVE-GROUND-BASES-1", "evidence_retrieved": evidence["retrieved"],
            "evidence_source": evidence["source"], "pob_version": pob_meta["pob_version"], "pob_commit": pob_meta["pob_commit"],
            "sources": SOURCES, "counts": dict(sorted(counts.items())), "entries": entries}
