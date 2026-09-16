from __future__ import annotations

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


def pob_slot_to_product(pob_slot: str, *, item_type: str | None = None) -> ProductSlot:
    if pob_slot == "Weapon 2" and item_type in OFFHAND_TYPES:
        return ProductSlot.OFFHAND_1
    if pob_slot == "Weapon 2" and item_type in WEAPON_TYPES:
        return ProductSlot.WEAPON_2
    return POB_TO_PRODUCT[pob_slot]


def product_slot_to_pob(product_slot: ProductSlot) -> str:
    if product_slot == ProductSlot.OFFHAND_1:
        return "Weapon 2"
    if product_slot == ProductSlot.OFFHAND_2:
        return "Weapon 2 Swap"
    return PRODUCT_TO_POB[product_slot]


EVALUABLE_POB_SLOTS = tuple(POB_TO_PRODUCT.keys())
