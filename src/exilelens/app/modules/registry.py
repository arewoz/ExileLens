"""Static product capability gate."""

from __future__ import annotations

import os
from enum import Enum


class FeatureModule(str, Enum):
    ITEM_CHECK = "ITEM_CHECK"
    BUILD_ANALYSIS = "BUILD_ANALYSIS"
    TREE_TOOLS = "TREE_TOOLS"
    MARKET = "MARKET"
    MARKET_ASSISTANT = "MARKET_ASSISTANT"
    GEAR_OPTIMIZER = "GEAR_OPTIMIZER"
    LIVE_TREE_OVERLAY = "LIVE_TREE_OVERLAY"


SUPPORTED_MODULES = frozenset({FeatureModule.ITEM_CHECK})
PARKED_MODULES = frozenset(set(FeatureModule) - set(SUPPORTED_MODULES))


def parking_enforced() -> bool:
    return os.environ.get("POE2VALUE_UNPARK_MODULES", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }


def is_module_parked(module: FeatureModule) -> bool:
    return parking_enforced() and module in PARKED_MODULES


def is_enabled(module: FeatureModule) -> bool:
    return module in SUPPORTED_MODULES or not parking_enforced()
