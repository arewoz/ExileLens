from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProductSlot(str, Enum):
    HELMET = "HELMET"
    BODY_ARMOUR = "BODY_ARMOUR"
    GLOVES = "GLOVES"
    BOOTS = "BOOTS"
    BELT = "BELT"
    AMULET = "AMULET"
    RING_1 = "RING_1"
    RING_2 = "RING_2"
    WEAPON_1 = "WEAPON_1"
    WEAPON_2 = "WEAPON_2"
    OFFHAND_1 = "OFFHAND_1"
    OFFHAND_2 = "OFFHAND_2"


POB_TO_PRODUCT: dict[str, ProductSlot] = {
    "Helmet": ProductSlot.HELMET,
    "Body Armour": ProductSlot.BODY_ARMOUR,
    "Gloves": ProductSlot.GLOVES,
    "Boots": ProductSlot.BOOTS,
    "Belt": ProductSlot.BELT,
    "Amulet": ProductSlot.AMULET,
    "Ring 1": ProductSlot.RING_1,
    "Ring 2": ProductSlot.RING_2,
    "Weapon 1": ProductSlot.WEAPON_1,
    "Weapon 2": ProductSlot.WEAPON_2,
}

PRODUCT_TO_POB: dict[ProductSlot, str] = {value: key for key, value in POB_TO_PRODUCT.items()}

OFFHAND_TYPES = {"Shield", "Focus", "Quiver"}
WEAPON_TYPES = {
    "Wand",
    "Sceptre",
    "Staff",
    "Bow",
    "Crossbow",
    "Spear",
    "Mace",
    "Sword",
    "Axe",
    "Dagger",
    "Claw",
    "Flail",
}


def is_jewel_socket_pob_slot(pob_slot: str) -> bool:
    """True for a dynamic, per-build jewel-socket slot name ("Jewel <nodeId>").

    Jewel sockets are not equipment slots (M1.3): PoB creates one socket per
    passive-tree jewel-socket tree node, so there is no fixed, enumerable set
    of names the way there is for "Ring 1"/"Weapon 2"/etc. -- the socket count
    and node ids differ per build. Deliberately NOT modeled as `ProductSlot`
    members (that enum is for the fixed equipment slot set); see
    `pob_slot_to_product` below.
    """
    return bool(pob_slot) and pob_slot.startswith("Jewel ") and pob_slot[len("Jewel "):].isdigit()


def jewel_socket_display_label(index: int) -> str:
    """Player-facing label for one jewel socket in an ordered list of legal
    placements -- never the raw tree-node id ("Jewel 11184").

    PoB does not expose a real passive-tree location/name for a socket node,
    so an ordinal ("Socket 1", "Socket 2", ...) is used rather than inventing
    one. The raw slot name remains available for Copy diagnostics.
    """
    return f"Socket {index + 1}"


def pob_slot_to_product(pob_slot: str, *, item_type: str | None = None) -> ProductSlot | str:
    """Map a PoB slot name to its product-facing identity.

    Returns a `ProductSlot` enum member for the fixed equipment slots, or the
    raw PoB slot name itself (e.g. "Jewel 26196") for a jewel socket -- jewel
    sockets are per-build and dynamic, so they cannot be fixed enum members.
    Callers that unconditionally did `.value` on the old return type must
    branch on `isinstance(result, ProductSlot)` first (`str(result)` also
    works for both cases, since `ProductSlot` is itself a `str` subclass, but
    `.value` is not defined on a plain `str`).
    """
    if is_jewel_socket_pob_slot(pob_slot):
        return pob_slot
    if pob_slot == "Weapon 2" and item_type in OFFHAND_TYPES:
        return ProductSlot.OFFHAND_1
    if pob_slot == "Weapon 2" and item_type in WEAPON_TYPES:
        return ProductSlot.WEAPON_2
    return POB_TO_PRODUCT[pob_slot]


def product_slot_to_pob(product_slot: ProductSlot) -> str:
    # OFFHAND_2 -> "Weapon 2 Swap" is superseded, not wired up: M1.1's weapon-swap
    # fix (runtime/lua/bridge.lua's `active_weapon_slot`) makes the bridge itself
    # transparently redirect logical "Weapon 1"/"Weapon 2" to the active item set's
    # physical Swap slots whenever `useSecondWeaponSet` is true. Product code never
    # needs to name a Swap slot explicitly: OFFHAND_1 already means "whatever
    # offhand is currently active," swap or not. This branch has no reachable
    # caller (the bridge's EVALUABLE_SLOTS never reports "Weapon 2 Swap" as a
    # compatible slot, so pob_slot_to_product below never produces OFFHAND_2 from
    # live data either) and is kept only because ProductSlot.OFFHAND_2 remains a
    # public enum member used elsewhere for weapon-slot categorization (see
    # analysis/opportunity.py's WEAPON_PRODUCT_SLOTS). Do not build new logic on
    # this branch; if a future feature needs to address the INACTIVE weapon set
    # explicitly, that is a distinct concept from OFFHAND_2 as declared here.
    if product_slot == ProductSlot.OFFHAND_1:
        return "Weapon 2"
    if product_slot == ProductSlot.OFFHAND_2:
        return "Weapon 2 Swap"
    return PRODUCT_TO_POB[product_slot]


EVALUABLE_POB_SLOTS = tuple(POB_TO_PRODUCT.keys())

#: Exact physical weapon storage slots in PoB's ItemsTab. The bridge already
#: documents that these four objects are independent and that the active pair
#: is selected per item set by `useSecondWeaponSet`. Normal product code must
#: never name a Swap slot; Slice 3 contextual evaluation addresses them only
#: through :class:`PhysicalEvaluationTarget` below.
PHYSICAL_WEAPON_SLOTS: tuple[str, ...] = ("Weapon 1", "Weapon 2", "Weapon 1 Swap", "Weapon 2 Swap")

#: Physical slot by (logical product slot, weapon set). Only weapon-category
#: product slots have a physical contextual target.
_PHYSICAL_WEAPON_TARGET: dict[tuple[str, int], str] = {
    (ProductSlot.WEAPON_1.value, 1): "Weapon 1",
    (ProductSlot.WEAPON_1.value, 2): "Weapon 1 Swap",
    (ProductSlot.WEAPON_2.value, 1): "Weapon 2",
    (ProductSlot.WEAPON_2.value, 2): "Weapon 2 Swap",
    (ProductSlot.OFFHAND_1.value, 1): "Weapon 2",
    (ProductSlot.OFFHAND_1.value, 2): "Weapon 2 Swap",
}

WEAPON_PRODUCT_SLOTS = frozenset({ProductSlot.WEAPON_1, ProductSlot.WEAPON_2, ProductSlot.OFFHAND_1})


@dataclass(frozen=True)
class PhysicalEvaluationTarget:
    """INTERNAL address of an exact physical weapon slot in one weapon set.

    ``logical_product_slot`` is the product-facing slot the candidate was
    resolved for; ``physical_pob_slot`` is the exact PoB storage slot that
    will be mutated; ``weapon_set`` is 1 or 2. This is not a new public
    ``ProductSlot`` and never surfaces Swap names to product callers.
    """

    logical_product_slot: str
    physical_pob_slot: str
    weapon_set: int

    @classmethod
    def from_parts(cls, logical_product_slot: ProductSlot | str, weapon_set: int) -> "PhysicalEvaluationTarget":
        logical = logical_product_slot.value if isinstance(logical_product_slot, ProductSlot) else str(logical_product_slot)
        if int(weapon_set) not in (1, 2):
            raise ValueError("weapon_set must be 1 or 2")
        physical = _PHYSICAL_WEAPON_TARGET.get((logical, int(weapon_set)))
        if physical is None:
            raise ValueError(f"no physical weapon target for logical slot {logical!r}")
        return cls(logical_product_slot=logical, physical_pob_slot=physical, weapon_set=int(weapon_set))

    def to_dict(self) -> dict[str, object]:
        return {
            "logical_product_slot": self.logical_product_slot,
            "physical_pob_slot": self.physical_pob_slot,
            "weapon_set": self.weapon_set,
        }


def opposite_physical_slot(physical_pob_slot: str) -> str:
    """The physical slot holding the same logical weapon in the other set."""
    mapping = {
        "Weapon 1": "Weapon 1 Swap",
        "Weapon 1 Swap": "Weapon 1",
        "Weapon 2": "Weapon 2 Swap",
        "Weapon 2 Swap": "Weapon 2",
    }
    try:
        return mapping[physical_pob_slot]
    except KeyError as exc:
        raise ValueError(f"not a physical weapon slot: {physical_pob_slot!r}") from exc
