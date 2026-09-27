"""Roll bounds for ranged Way of the Stonefist modifiers (CORPUS-02C).

Evidence (docs/CORPUS-02C.md): the game rolls a ranged transformed modifier
independently of the original modifier's roll -- e.g. a fixed "+2 to Level of all
Melee Skills" transforms into "(10-12)% to Quality of all Skills" observed at 10, 11
and 12 on different real items. The actual value only exists once the gloves are
equipped, so it cannot be derived from the item the player copies.

What is exact is its range (game data, via PoB). Item Check therefore measures the
candidate at both ends -- every ranged value at its worst end, then at its best end
-- and reports a verdict only when it is the same for both. No value inside a range
is ever chosen.
"""

from __future__ import annotations

import re

from exilelens.items.stonefist import ModPair, RollRule, _ranges, no_ranged_rule

# Lines where a larger value is worse for the character.
_WORSE_WHEN_LARGER = re.compile(r"\bslower\b", re.IGNORECASE)
_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")


def _bound_rule(best: bool) -> RollRule:
    def rule(pair: ModPair, source_values: list[float]) -> list[float]:
        values: list[float] = []
        for line in pair.target_lines:
            larger_is_worse = bool(_WORSE_WHEN_LARGER.search(line))
            for match in _RANGE.finditer(line):
                low, high = sorted((float(match.group(1)), float(match.group(2))))
                if low == high:
                    values.append(low)
                    continue
                values.append(high if best != larger_is_worse else low)
        return values

    rule.__name__ = "stonefist_best_rolls" if best else "stonefist_worst_rolls"
    return rule


WORST_ROLLS: RollRule = _bound_rule(best=False)
BEST_ROLLS: RollRule = _bound_rule(best=True)
BOUND_RULES: dict[str, RollRule] = {"worst": WORST_ROLLS, "best": BEST_ROLLS, "none": no_ranged_rule}

#: Default rule for callers that do not evaluate bounds: ranged rolls unresolved.
STONEFIST_ROLL_RULE = no_ranged_rule

__all__ = ["BEST_ROLLS", "BOUND_RULES", "STONEFIST_ROLL_RULE", "WORST_ROLLS", "_ranges"]
