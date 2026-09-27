"""Roll bounds for ranged Way of the Stonefist modifiers (CORPUS-02C).

Evidence (docs/CORPUS-02C.md): the game rolls a ranged transformed modifier
independently of the original modifier's roll -- e.g. a fixed "+2 to Level of all
Melee Skills" transforms into "(10-12)% to Quality of all Skills" observed at 10, 11
and 12 on different real items. The actual value only exists once the gloves are
equipped, so it cannot be derived from the item the player copies.

What is exact is its range (game data, via PoB). Item Check therefore measures the
candidate with every ranged value at its worst end, a middle roll and its best end,
and reports a verdict only when PoB's results are ordered and agree across all three.
The middle roll is a verification point only; results are reported as a range, never
as one assumed roll.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from exilelens.items.stonefist import ModPair, RollRule, no_ranged_rule

# Lines where a larger value is worse for the character.
_WORSE_WHEN_LARGER = re.compile(r"\bslower\b", re.IGNORECASE)
_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")


def _decimals(text: str) -> int:
    return max((len(part.split(".")[1]) for part in re.findall(r"\d+\.\d+", text)), default=0)


def _middle(low: float, high: float, decimals: int) -> float:
    quantum = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    return float(((Decimal(str(low)) + Decimal(str(high))) / 2).quantize(quantum, rounding=ROUND_HALF_UP))


def _bound_rule(position: str) -> RollRule:
    """``worst`` / ``best`` end of every range, or a displayable ``middle`` roll."""

    def rule(pair: ModPair, source_values: list[float]) -> list[float]:
        values: list[float] = []
        for line in pair.target_lines:
            larger_is_worse = bool(_WORSE_WHEN_LARGER.search(line))
            decimals = _decimals(line)
            for match in _RANGE.finditer(line):
                low, high = sorted((float(match.group(1)), float(match.group(2))))
                if low == high:
                    values.append(low)
                elif position == "middle":
                    values.append(_middle(low, high, decimals))
                else:
                    values.append(high if (position == "best") != larger_is_worse else low)
        return values

    rule.__name__ = f"stonefist_{position}_rolls"
    rule.source_independent = True  # type: ignore[attr-defined]
    return rule


WORST_ROLLS: RollRule = _bound_rule("worst")
MIDDLE_ROLLS: RollRule = _bound_rule("middle")
BEST_ROLLS: RollRule = _bound_rule("best")
BOUND_RULES: dict[str, RollRule] = {
    "worst": WORST_ROLLS, "middle": MIDDLE_ROLLS, "best": BEST_ROLLS, "none": no_ranged_rule,
}

#: Default rule for callers that do not evaluate bounds: ranged rolls unresolved.
STONEFIST_ROLL_RULE = no_ranged_rule

__all__ = ["BEST_ROLLS", "BOUND_RULES", "MIDDLE_ROLLS", "STONEFIST_ROLL_RULE", "WORST_ROLLS"]
