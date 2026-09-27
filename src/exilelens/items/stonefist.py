"""Way of the Stonefist: in-memory transformation of ordinary gloves into Fists of Stone.

The game transforms equipped gloves of a Way of the Stonefist character: the base
becomes (Runeforged) Fists of Stone and every explicit modifier ``<Id>`` becomes the
game's ``HandWraps<Id>`` modifier (same affix name, tier for tier). PoB's own data
holds both families (read through the bridge, ``get_item_transform_mods``); PoB
also calculates every statistic of the transformed item. This module only decides
which transformed item the character would actually equip, and refuses to guess:

* each displayed explicit line is decomposed into the source modifiers that produce
  it (the game merges same-stat lines, e.g. a %ES prefix plus a hybrid %ES/Life
  prefix show as one line); the decomposition must be unique in its result;
* a transformed modifier with a fixed value is exact; a ranged one needs its roll,
  derived by a ``RollRule`` from the source modifier's own roll, which must be
  individually observable (not hidden inside a merged line);
* anything else (unknown line, unmapped modifier, ambiguous or merged roll, unique
  item) leaves the item ``unresolved`` with the precise reason. Callers keep the
  UNSUPPORTED guard for those.

No values are averaged or estimated.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

FISTS = "Fists of Stone"
RUNEFORGED_FISTS = "Runeforged Fists of Stone"

_NUM = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)|(-?\d+(?:\.\d+)?)")


def _template(line: str) -> str:
    return _NUM.sub("#", line.strip())


def _ranges(line: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for match in _NUM.finditer(line):
        if match.group(1) is not None:
            low, high = float(match.group(1)), float(match.group(2))
            out.append((min(low, high), max(low, high)))
        else:
            value = float(match.group(3))
            out.append((value, value))
    return out


def _values(line: str) -> list[float]:
    return [float(m.group(3) if m.group(3) is not None else m.group(1)) for m in _NUM.finditer(line)]


def _decimals(text: str) -> int:
    return max((len(m.split(".")[1]) for m in re.findall(r"\d+\.\d+", text)), default=0)


@dataclass(frozen=True)
class ModPair:
    source_id: str
    target_id: str
    source_lines: tuple[str, ...]
    target_lines: tuple[str, ...]
    source_type: str
    source_group: str

    @property
    def templates(self) -> tuple[str, ...]:
        return tuple(_template(line) for line in self.source_lines)

    @property
    def target_ranged(self) -> bool:
        return any(low != high for line in self.target_lines for low, high in _ranges(line))


@dataclass
class TransformResult:
    ok: bool
    item_raw: str = ""
    base_name: str = ""
    implicit: list[dict[str, Any]] = field(default_factory=list)
    explicit: list[dict[str, Any]] = field(default_factory=list)
    mapped: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    already_transformed: bool = False
    #: True when a ranged transformed modifier was set to one end of its range.
    bounded: bool = False
    bound: str = ""
    #: Several different transformed items fit the displayed lines; this is one of them.
    alternatives: int = 1
    alternative: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "base_name": self.base_name, "mapped": self.mapped,
            "unresolved": self.unresolved, "already_transformed": self.already_transformed,
            "bounded": self.bounded, "bound": self.bound,
            "alternatives": self.alternatives, "alternative": self.alternative,
        }


#: Maps a source modifier's own displayed values onto its transformed modifier's
#: ranged values. Returns None when the rule is not established for this pair.
RollRule = Callable[[ModPair, list[float]], "list[float] | None"]
Own = dict[tuple[str, str], "list[float] | None"]


def no_ranged_rule(pair: ModPair, source_values: list[float]) -> list[float] | None:
    """Default: ranged transformed rolls are not derivable (no validated rule)."""
    return None


class StonefistTransformer:
    def __init__(
        self, mods: list[dict[str, Any]], roll_rule: RollRule = no_ranged_rule,
        decompose_cache: dict[Any, Any] | None = None,
    ) -> None:
        #: Shared between the per-rule transformers of one engine: decomposition
        #: does not depend on the roll rule.
        self._decompose_cache: dict[Any, Any] = decompose_cache if decompose_cache is not None else {}
        self.pairs = [
            ModPair(
                source_id=str(m["source_id"]), target_id=str(m["target_id"]),
                source_lines=tuple(m.get("source_lines") or ()), target_lines=tuple(m.get("target_lines") or ()),
                source_type=str(m.get("source_type") or m.get("target_type") or ""),
                source_group=str(m.get("source_group") or m["source_id"]),
            )
            for m in mods
            if m.get("source_id") and m.get("source_lines") and m.get("target_lines")
        ]
        self.roll_rule = roll_rule
        self._by_template: dict[str, list[ModPair]] = {}
        for pair in self.pairs:
            for template in set(pair.templates):
                self._by_template.setdefault(template, []).append(pair)

    # ------------------------------------------------------------------ decomposition
    def decompose(self, lines: list[dict[str, Any]], *, max_affixes: int = 3) -> tuple[list[tuple[list[ModPair], Own]], list[str]]:
        """All source-modifier sets that reproduce ``lines`` exactly.

        Each solution is ``(pairs, own)``: ``own[(source_id, template)]`` is that
        modifier's own displayed values, or None when its line is a merged sum of
        several modifiers (the game shows same-stat modifiers as one line; PoB
        exports may list them separately, and then each line is one modifier).
        The result does not depend on the roll rule and is cached per item.
        """
        key = (tuple(str(row["line"]) for row in lines), max_affixes)
        cached = self._decompose_cache.get(key)
        if cached is not None:
            return cached
        result = self._decompose(lines, max_affixes=max_affixes)
        self._decompose_cache[key] = result
        return result

    def _decompose(self, lines: list[dict[str, Any]], *, max_affixes: int) -> tuple[list[tuple[list[ModPair], Own]], list[str]]:
        observed: dict[str, list[list[float]]] = {}
        unknown: list[str] = []
        for row in lines:
            text = str(row["line"])
            template = _template(text)
            if template not in self._by_template:
                unknown.append(text)
                continue
            observed.setdefault(template, []).append(_values(text))
        if unknown:
            return [], [f"no Way of the Stonefist mapping for: {line}" for line in unknown]

        candidates = sorted(
            {pair for template in observed for pair in self._by_template[template]}, key=lambda p: p.source_id,
        )
        candidates = [p for p in candidates if all(t in observed for t in p.templates)]
        # Pre-parsed line data: pair -> [(template, ranges)].
        info = {pair: [(_template(line), _ranges(line)) for line in pair.source_lines] for pair in candidates}
        single = [t for t, rows in observed.items() if len(rows) == 1]

        # remaining_high[i][template][k]: the most that candidates i.. can still add to a
        # merged line (one tier per modifier group, so the largest tier per group).
        remaining_high: list[dict[str, list[float]]] = []
        for start in range(len(candidates) + 1):
            best: dict[tuple[str, str], list[float]] = {}
            for pair in candidates[start:]:
                for template, ranges in info[pair]:
                    if template not in single:
                        continue
                    slot = (pair.source_group, template)
                    highs = [high for _, high in ranges]
                    current = best.get(slot)
                    best[slot] = highs if current is None else [max(a, b) for a, b in zip(current, highs)]
            totals: dict[str, list[float]] = {}
            for (_group, template), highs in best.items():
                total = totals.setdefault(template, [0.0] * len(highs))
                for index, value in enumerate(highs):
                    if index < len(total):
                        total[index] += value
            remaining_high.append(totals)

        def within(values: list[float], ranges: list[tuple[float, float]]) -> bool:
            return len(values) == len(ranges) and all(
                low - 1e-9 <= value <= high + 1e-9 for value, (low, high) in zip(values, ranges)
            )

        def assignments(chosen: list[ModPair], complete: bool, start: int) -> list[Own] | None:
            per_template: list[list[Own]] = []
            for template, rows in observed.items():
                contrib = [(pair, ranges) for pair in chosen for t, ranges in info[pair] if t == template]
                if len(rows) == 1:
                    values = rows[0]
                    room = remaining_high[start].get(template, [])
                    for index, value in enumerate(values):
                        low = sum(r[index][0] for _, r in contrib if index < len(r))
                        high = sum(r[index][1] for _, r in contrib if index < len(r))
                        reachable = high + (room[index] if index < len(room) and not complete else 0.0)
                        # A merged line's sum only grows as modifiers are added: dead once its
                        # minimum exceeds the value, or once even every remaining modifier
                        # group's largest tier cannot lift its maximum up to the value.
                        if value < low - 1e-9 or value > reachable + 1e-9:
                            return None
                    if not contrib:
                        if complete:
                            return None
                        continue
                    if len(contrib) == 1:
                        per_template.append([{(contrib[0][0].source_id, template): values}])
                    else:
                        per_template.append([{(pair.source_id, template): None for pair, _ in contrib}])
                    continue
                if len(contrib) > len(rows) or (complete and len(contrib) != len(rows)):
                    return None
                if not complete or not contrib:
                    continue
                options: list[Own] = []
                for order in itertools.permutations(range(len(rows))):
                    if all(within(rows[order[i]], contrib[i][1]) for i in range(len(contrib))):
                        options.append({(contrib[i][0].source_id, template): rows[order[i]] for i in range(len(contrib))})
                if not options:
                    return None
                per_template.append(options)
            if not complete:
                return []
            combined: list[Own] = []
            for combo in itertools.product(*per_template):
                merged: Own = {}
                for part in combo:
                    merged.update(part)
                combined.append(merged)
            return combined

        solutions: list[tuple[list[ModPair], Own]] = []

        def search(start: int, chosen: list[ModPair], groups: set[str], prefixes: int, suffixes: int) -> None:
            if prefixes > max_affixes or suffixes > max_affixes or assignments(chosen, False, start) is None:
                return
            for own in assignments(chosen, True, start) or []:
                solutions.append((list(chosen), own))
            if len(solutions) > 256:
                return
            for index in range(start, len(candidates)):
                pair = candidates[index]
                if pair.source_group in groups:
                    continue
                chosen.append(pair)
                groups.add(pair.source_group)
                search(index + 1, chosen, groups,
                       prefixes + (pair.source_type == "Prefix"), suffixes + (pair.source_type == "Suffix"))
                chosen.pop()
                groups.discard(pair.source_group)

        search(0, [], set(), 0, 0)
        if not solutions:
            return [], ["the displayed modifiers match no combination of glove modifiers"]
        return solutions, []

    # ------------------------------------------------------------------ transformation
    def transform_lines(self, lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """The transformed explicit lines, or problems when several different items are possible."""
        explicit, mapped, problems, _count = self.transform_lines_alternative(lines, None)
        return explicit, mapped, problems

    def transform_lines_alternative(
        self, lines: list[dict[str, Any]], alternative: int | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], int]:
        """Like ``transform_lines``; ``alternative`` picks one of several possible items.

        Decompositions that yield the same transformed lines with different values are
        merged into bounds; decompositions that yield different lines are separate
        alternatives (ordered deterministically), each of which the caller must evaluate.
        """
        flags: dict[str, dict[str, Any]] = {}
        for row in lines:
            flags.setdefault(_template(str(row["line"])), row)
        solutions, problems = self.decompose(lines)
        if problems:
            return [], [], problems, 0
        outputs: list[tuple[tuple[str, ...], list[dict[str, Any]], list[dict[str, Any]]]] = []
        reasons: list[str] = []
        for solution, own in solutions:
            explicit: list[dict[str, Any]] = []
            mapped: list[dict[str, Any]] = []
            failed = False
            for pair in solution:
                own_values: list[float] | None = []
                for template in pair.templates:
                    values = own.get((pair.source_id, template))
                    if values is None:
                        own_values = None
                        break
                    own_values.extend(values)
                if pair.target_ranged:
                    # A bound rule does not use the source roll (the game rolls the
                    # transformed value independently), so a merged line is no obstacle.
                    if own_values is None and not getattr(self.roll_rule, "source_independent", False):
                        reasons.append(f"{pair.source_id}: its roll is merged into a shared line, so the transformed roll is unknown")
                        failed = True
                        break
                    target_values = self.roll_rule(pair, own_values or [])
                    if target_values is None:
                        reasons.append(f"{pair.source_id} -> {pair.target_id}: no validated roll rule for a ranged transformed modifier")
                        failed = True
                        break
                    rendered = _render(pair.target_lines, target_values)
                else:
                    rendered = [_render_fixed(line) for line in pair.target_lines]
                source_flags = flags[pair.templates[0]]
                for text in rendered:
                    explicit.append({
                        "line": text,
                        "fractured": bool(source_flags.get("fractured")),
                        "desecrated": bool(source_flags.get("desecrated")),
                        "crafted": bool(source_flags.get("crafted")),
                    })
                mapped.append({
                    "source_id": pair.source_id, "target_id": pair.target_id, "lines": rendered,
                    "ranged": pair.target_ranged,
                })
            if not failed:
                key = tuple(sorted(row["line"] for row in explicit))
                outputs.append((key, explicit, mapped))
        if not outputs:
            return [], [], sorted(set(reasons)) or ["no exact transformation"], 0
        groups: dict[tuple[str, ...], list[tuple[tuple[str, ...], list[dict[str, Any]], list[dict[str, Any]]]]] = {}
        for output in outputs:
            shape = tuple(sorted(_template(row["line"]) for row in output[1]))
            groups.setdefault(shape, []).append(output)
        ordered = [groups[shape] for shape in sorted(groups)]
        count = len(ordered)
        if count > 1 and alternative is None:
            return [], [], ["the displayed modifiers allow several different transformed items"], count
        group = ordered[alternative or 0] if (alternative or 0) < count else None
        if group is None:
            return [], [], ["unknown transformation alternative"], count
        if len({key for key, _, _ in group}) > 1:
            merged = self._merge_bound_outputs(group)
            if merged is None:
                return [], [], ["the displayed modifiers allow several different transformed items"], count
            return merged[0], merged[1], [], count
        _, explicit, mapped = group[0]
        return explicit, mapped, [], count

    def _merge_bound_outputs(
        self, outputs: list[tuple[tuple[str, ...], list[dict[str, Any]], list[dict[str, Any]]]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        """Overlapping source tiers that transform into the same lines with different values.

        Only in a bound evaluation: every line takes its worst (or best) value over
        all possible decompositions, which widens the unknown range exactly.
        """
        name = getattr(self.roll_rule, "__name__", "")
        if name not in {"stonefist_worst_rolls", "stonefist_middle_rolls", "stonefist_best_rolls"}:
            return None
        best = name == "stonefist_best_rolls"
        middle = name == "stonefist_middle_rolls"
        shapes = [sorted(_template(row["line"]) for row in explicit) for _, explicit, _ in outputs]
        if any(shape != shapes[0] for shape in shapes):
            return None
        per_output = [sorted(explicit, key=lambda row: (_template(row["line"]), row["line"])) for _, explicit, _ in outputs]
        merged: list[dict[str, Any]] = []
        for rows in zip(*per_output):
            template = _template(rows[0]["line"])
            larger_is_worse = "slower" in template.lower()
            columns = list(zip(*[_values(row["line"]) for row in rows]))
            decimals = max(_decimals(row["line"]) for row in rows)
            if middle:
                quantum = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
                chosen = [
                    float(((Decimal(str(min(c))) + Decimal(str(max(c)))) / 2).quantize(quantum, rounding=ROUND_HALF_UP))
                    for c in columns
                ]
            else:
                pick = max if best != larger_is_worse else min
                chosen = [pick(column) for column in columns]
            iterator = iter(chosen)
            line = re.sub("#", lambda _m: _format(next(iterator), decimals), template)
            merged.append({**rows[0], "line": line})
        alternatives = [[m["source_id"] for m in mapped] for _, _, mapped in outputs]
        mapped = [{
            "source_id": "|".join(sorted({sid for alt in alternatives for sid in alt})),
            "target_id": "overlapping tiers", "lines": [row["line"] for row in merged],
            "ranged": True, "alternatives": alternatives,
        }]
        return merged, mapped

    def transform(self, engine: Any, item_raw: str, alternative: int | None = None) -> TransformResult:
        described = engine._call("describe_item", {"item_raw": item_raw})
        if described.get("type") != "Gloves":
            return TransformResult(ok=False, unresolved=["not a glove item"])
        base = str(described.get("base_name") or "")
        if FISTS in base:
            # Already the item the character equips (e.g. a PoB/poe.ninja export):
            # never transform twice.
            return TransformResult(ok=True, item_raw=item_raw, base_name=base, already_transformed=True)
        if str(described.get("rarity") or "").upper() == "UNIQUE":
            return TransformResult(ok=False, unresolved=["unique gloves have item-specific transformations that are not mapped"])
        explicit, mapped, problems, count = self.transform_lines_alternative(
            list(described.get("explicit") or []), alternative,
        )
        if problems:
            return TransformResult(ok=False, unresolved=problems, alternatives=max(count, 1))
        target_base = RUNEFORGED_FISTS if described.get("runic") else FISTS
        implicit = [{"line": line} for line in engine_base_implicits(engine, target_base)]
        rebuilt = engine._call("rebuild_item", {
            "item_raw": item_raw, "base_name": target_base, "implicit": implicit, "explicit": explicit,
        })
        return TransformResult(
            ok=True, item_raw=str(rebuilt["item_raw"]), base_name=target_base,
            implicit=implicit, explicit=explicit, mapped=mapped,
            bounded=any(row.get("ranged") for row in mapped),
            bound=getattr(self.roll_rule, "__name__", ""),
            alternatives=count, alternative=alternative or 0,
        )


def engine_base_implicits(engine: Any, base_name: str) -> list[str]:
    cache = getattr(engine, "_stonefist_base_implicits", None)
    if cache is None:
        cache = {}
        setattr(engine, "_stonefist_base_implicits", cache)
    if base_name not in cache:
        cache[base_name] = list(engine._call("get_base_implicits", {"base_name": base_name}).get("lines") or [])
    return cache[base_name]


def _format(value: float, decimals: int) -> str:
    quantum = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    return str(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _render_fixed(line: str) -> str:
    return re.sub(r"\((-?\d+(?:\.\d+)?)-\1\)", r"\1", line)


def _render(target_lines: tuple[str, ...], values: list[float]) -> list[str]:
    rendered: list[str] = []
    iterator = iter(values)
    for line in target_lines:
        decimals = _decimals(line)

        def replace(match: re.Match[str]) -> str:
            if match.group(1) is None:
                return match.group(0)
            return _format(next(iterator), decimals)

        rendered.append(_NUM.sub(replace, line))
    return rendered


def transformer_for(engine: Any, roll_rule: RollRule = no_ranged_rule) -> StonefistTransformer:
    mods = getattr(engine, "_stonefist_mods", None)
    if mods is None:
        mods = engine._call("get_item_transform_mods", {"prefix": "HandWraps"}).get("mods") or []
        setattr(engine, "_stonefist_mods", mods)
    cache = getattr(engine, "_stonefist_transformers", None)
    if cache is None:
        cache = {}
        setattr(engine, "_stonefist_transformers", cache)
    key = getattr(roll_rule, "__name__", repr(roll_rule))
    if key not in cache:
        shared = getattr(engine, "_stonefist_decompositions", None)
        if shared is None:
            shared = {}
            setattr(engine, "_stonefist_decompositions", shared)
        cache[key] = StonefistTransformer(mods, roll_rule, shared)
    return cache[key]
