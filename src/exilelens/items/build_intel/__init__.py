"""ITEM-COMP-02 semantic build intelligence.

PoB whole-item evaluation remains canonical truth.
This package interprets that evidence. It must not override a valid exact result.
Market desirability / listing price must never enter these functions.
"""

from exilelens.items.build_intel.engine import attach_build_intelligence, attach_decomposition
from exilelens.items.build_intel.models import BuildComparisonResult

__all__ = [
    "BuildComparisonResult",
    "attach_build_intelligence",
    "attach_decomposition",
]
