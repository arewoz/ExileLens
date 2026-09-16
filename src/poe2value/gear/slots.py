from __future__ import annotations

from poe2value.items.slots import ProductSlot, product_slot_to_pob

GEAR_OPTIMIZER_SLOTS: tuple[ProductSlot, ...] = (
    ProductSlot.HELMET,
    ProductSlot.BODY_ARMOUR,
    ProductSlot.GLOVES,
    ProductSlot.BOOTS,
    ProductSlot.BELT,
    ProductSlot.AMULET,
    ProductSlot.RING_1,
    ProductSlot.RING_2,
    ProductSlot.WEAPON_1,
    ProductSlot.WEAPON_2,
)

GEAR_SLOT_LABELS: dict[str, str] = {
    ProductSlot.HELMET.value: "Helmet",
    ProductSlot.BODY_ARMOUR.value: "Body Armour",
    ProductSlot.GLOVES.value: "Gloves",
    ProductSlot.BOOTS.value: "Boots",
    ProductSlot.BELT.value: "Belt",
    ProductSlot.AMULET.value: "Amulet",
    ProductSlot.RING_1.value: "Ring 1",
    ProductSlot.RING_2.value: "Ring 2",
    ProductSlot.WEAPON_1.value: "Weapon 1",
    ProductSlot.WEAPON_2.value: "Weapon 2",
}


def pob_slot_for_product(product_slot: str) -> str:
    return product_slot_to_pob(ProductSlot(product_slot))
