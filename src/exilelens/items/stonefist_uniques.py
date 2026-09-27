"""Way of the Stonefist on unique gloves: the transformed item, from evidence only.

The game transforms a unique glove like any other: each modifier ``X`` becomes
``HandWrapsX`` when the game has that modifier (a few have no displayed stat and
simply disappear); every other modifier stays as it is. PoB's data holds the
``HandWraps...`` lines and ranges; which modifiers a given unique carries is taken
from real items (``stonefist_unique_evidence``). The candidate's own lines must match
those modifiers one to one -- line text, and each value within the modifier's range
-- or the glove stays unresolved with the reason. Nothing is estimated: ranged
transformed values go through the same bound rules as ordinary gloves.
"""

from __future__ import annotations

import re
from typing import Any

from exilelens.items.stonefist import (
    FISTS, RUNEFORGED_FISTS, ModPair, TransformResult, _ranges, _render, _render_fixed, _template,
    engine_base_implicits,
)
from exilelens.items.stonefist_unique_evidence import GAME_ONLY_TARGETS, UNIQUE_GLOVE_MODS

_SIGNED = re.compile(r"(-?)\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)|(-?\d+(?:\.\d+)?)")


def _match_template(line: str) -> str:
    """A line's text with every number (signed or ranged) as ``#``, sign-insensitive."""
    return re.sub(r"[+-]#", "#", _template(line))


def _signed_ranges(line: str) -> list[tuple[float, float]]:
    """Ranges with their displayed sign: ``-(20-10)%`` is -20..-10, ``+(-10-10)`` -10..10."""
    out: list[tuple[float, float]] = []
    for match in _SIGNED.finditer(line):
        if match.group(2) is not None:
            low, high = float(match.group(2)), float(match.group(3))
            if match.group(1):
                low, high = -low, -high
            out.append((min(low, high), max(low, high)))
        else:
            value = float(match.group(4))
            out.append((value, value))
    return out


def _signed_values(line: str) -> list[float]:
    return [float(m.group(4)) for m in _SIGNED.finditer(line) if m.group(4) is not None]


def _fits(candidate: str, pattern: str) -> bool:
    if _match_template(candidate) != _match_template(pattern):
        return False
    values, ranges = _signed_values(candidate), _signed_ranges(pattern)
    return len(values) == len(ranges) and all(
        low - 1e-9 <= value <= high + 1e-9 for value, (low, high) in zip(values, ranges)
    )


def _mod_lines(engine: Any, *, ids: list[str] | None = None, prefix: str | None = None) -> dict[str, dict[str, Any]]:
    cache = getattr(engine, "_stonefist_mod_lines", None)
    if cache is None:
        cache = {}
        setattr(engine, "_stonefist_mod_lines", cache)
    key = ("prefix", prefix) if prefix else ("ids", tuple(sorted(ids or ())))
    if key not in cache:
        params: dict[str, Any] = {"prefix": prefix} if prefix else {"ids": list(ids or ())}
        cache[key] = dict(engine._call("get_mod_lines", params).get("mods") or {})
    return cache[key]


def _clean(line: str) -> str:
    return re.sub(r"\+-", "-", line)


def transform_unique(transformer: Any, engine: Any, described: dict[str, Any], item_raw: str) -> TransformResult:
    name = str(described.get("name") or "").strip()
    evidence = UNIQUE_GLOVE_MODS.get(name)
    if evidence is None:
        return TransformResult(ok=False, unresolved=[
            f"the unique gloves {name or '(unnamed)'} have no verified Way of the Stonefist transformation",
        ])
    evidence_ids = list(evidence["mods"])  # type: ignore[arg-type]
    known = _mod_lines(engine, ids=evidence_ids)
    pairs: dict[str, ModPair] = transformer.unique_pairs

    rows = [dict(row) for row in (described.get("implicit") or [])] + [dict(row) for row in (described.get("explicit") or [])]
    claimed: dict[int, str] = {}
    matched: list[tuple[str, list[int]]] = []
    stale: list[str] = []
    # How many of the unique's modifier lines, and of the candidate's lines, share each
    # template: a value outside PoB's range is accepted only where both are unique.
    evidence_templates: dict[str, int] = {}
    for mod_id in evidence_ids:
        for line in (known.get(mod_id) or {}).get("lines") or []:
            evidence_templates[_match_template(line)] = evidence_templates.get(_match_template(line), 0) + 1
    row_templates: dict[str, int] = {}
    for row in rows:
        row_templates[_match_template(row["line"])] = row_templates.get(_match_template(row["line"]), 0) + 1

    def claim(mod_id: str, lines: list[str], pool_rows: list[int]) -> None:
        taken: list[int] = []
        outside: list[str] = []
        for line in lines:
            index = next((i for i in pool_rows if i not in claimed and i not in taken and _fits(rows[i]["line"], line)), None)
            if index is None:
                # PoB's data can lag the game's current values (e.g. Facebreaker "per 5
                # Strength" in PoB, "per 4" on current items). The modifier is still
                # identified when this template belongs to exactly one of the unique's
                # modifier lines and exactly one candidate line; the source value is never
                # used (transformed rolls are independent, kept lines are copied).
                template = _match_template(line)
                if evidence_templates.get(template) == 1 and row_templates.get(template) == 1:
                    index = next((i for i in pool_rows if i not in claimed and i not in taken
                                  and _match_template(rows[i]["line"]) == template), None)
                    if index is not None:
                        outside.append(rows[index]["line"])
            if index is None:
                return
            taken.append(index)
        for index in taken:
            claimed[index] = mod_id
        matched.append((mod_id, taken))
        stale.extend(outside)

    plain_rows = [i for i, row in enumerate(rows) if not row.get("mutated")]
    for mod_id in evidence_ids:
        lines = list((known.get(mod_id) or {}).get("lines") or [])
        if lines:
            claim(mod_id, lines, plain_rows)
    # A Vaal-mutated line replaces one of the unique's modifiers; it is matched against
    # PoB's mutated modifiers and accepted only when exactly one of them prints it.
    mutated_rows = [i for i, row in enumerate(rows) if row.get("mutated")]
    if mutated_rows:
        pool = _mod_lines(engine, prefix="UniqueMutatedVaal")
        for index in mutated_rows:
            fits = [mod_id for mod_id, mod in pool.items() if len(mod.get("lines") or []) == 1 and _fits(rows[index]["line"], mod["lines"][0])]
            if len(fits) == 1:
                claimed[index] = fits[0]
                matched.append((fits[0], [index]))
    # Skill grants the game keeps (e.g. Atziri's Herald): their modifiers are not in
    # PoB's data, so the line itself is kept verbatim.
    kept_unknown = [m for m in evidence_ids if m not in known and _fate(m, pairs) == "kept"]
    for index, row in enumerate(rows):
        if index not in claimed and kept_unknown and str(row["line"]).startswith("Grants Skill:"):
            claimed[index] = "grants skill"
            matched.append(("grants skill", [index]))

    unmatched = [rows[i]["line"] for i in range(len(rows)) if i not in claimed]
    if unmatched:
        return TransformResult(ok=False, unresolved=[
            f"{name}: the line \"{line}\" is not one of the verified {name} modifiers" for line in unmatched
        ])

    explicit: list[dict[str, Any]] = []
    mapped: list[dict[str, Any]] = []
    for mod_id, indices in sorted(matched, key=lambda entry: min(entry[1])):
        source_rows = [rows[i] for i in indices]
        flags = {key: bool(source_rows[0].get(key)) for key in ("fractured", "desecrated", "crafted")}
        fate = "kept" if mod_id == "grants skill" else _fate(mod_id, pairs)
        if fate == "unavailable":
            return TransformResult(ok=False, unresolved=[
                f"{name}: Way of the Stonefist turns {mod_id} into a modifier that Path of Building's data does not have",
            ])
        if fate == "removed":
            mapped.append({"source_id": mod_id, "target_id": "HandWraps" + mod_id, "lines": [], "ranged": False, "ranged_lines": []})
            continue
        if fate == "kept":
            explicit.extend({"line": row["line"], **flags} for row in source_rows)
            mapped.append({"source_id": mod_id, "target_id": mod_id, "lines": [row["line"] for row in source_rows], "ranged": False, "ranged_lines": []})
            continue
        pair = pairs[mod_id]
        if pair.target_ranged:
            own = [value for row in source_rows for value in _signed_values(row["line"])]
            values = transformer.roll_rule(pair, own)
            if values is None:
                return TransformResult(ok=False, unresolved=[
                    f"{pair.source_id} -> {pair.target_id}: no validated roll rule for a ranged transformed modifier",
                ])
            rendered = [_clean(line) for line in _render(pair.target_lines, values)]
        else:
            rendered = [_clean(_render_fixed(line)) for line in pair.target_lines]
        explicit.extend({"line": line, **flags} for line in rendered)
        mapped.append({
            "source_id": pair.source_id, "target_id": pair.target_id, "lines": rendered, "ranged": pair.target_ranged,
            "ranged_lines": [_template(line) for line in pair.target_lines if any(lo != hi for lo, hi in _ranges(line))],
        })

    target_base = RUNEFORGED_FISTS if described.get("runic") else FISTS
    implicit = [{"line": line} for line in engine_base_implicits(engine, target_base)]
    rebuilt = engine._call("rebuild_item", {
        "item_raw": item_raw, "base_name": target_base, "implicit": implicit, "explicit": explicit,
    })
    return TransformResult(
        ok=True, item_raw=str(rebuilt["item_raw"]), base_name=target_base,
        implicit=implicit, explicit=explicit, mapped=mapped,
        bounded=any(row.get("ranged") for row in mapped),
        bound=getattr(transformer.roll_rule, "__name__", ""),
        ranged_lines=list(dict.fromkeys(t for row in mapped for t in row.get("ranged_lines") or [])),
        source_values_outside_pob_data=stale,
    )


def _fate(mod_id: str, pairs: dict[str, ModPair]) -> str:
    target = "HandWraps" + mod_id
    if target in GAME_ONLY_TARGETS["removed"]:
        return "removed"
    if target in GAME_ONLY_TARGETS["unavailable"]:
        return "unavailable"
    if mod_id in pairs:
        return "transformed"
    return "kept"


__all__ = ["transform_unique"]
