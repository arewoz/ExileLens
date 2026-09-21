"""Authoritative supported equipment matrix for Item Check tooltip coverage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from poe2value.items.recognition import recognize_input
from poe2value.items.raw_input import ItemInputSource, RawItemInput
from poe2value.items.slots import ProductSlot, pob_slot_to_product

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "fixtures" / "items"


class SupportedItemClass(str, Enum):
    HELMET = "HELMET"
    BODY_ARMOUR = "BODY_ARMOUR"
    GLOVES = "GLOVES"
    BOOTS = "BOOTS"
    BELT = "BELT"
    RING = "RING"
    AMULET = "AMULET"
    JEWEL = "JEWEL"
    ONE_HAND_WEAPON = "ONE_HAND_WEAPON"
    TWO_HAND_WEAPON = "TWO_HAND_WEAPON"
    OFFHAND = "OFFHAND"


@dataclass(frozen=True)
class SupportedItemSpec:
    item_class: SupportedItemClass
    fixture: str
    clipboard_item_class: str
    pob_slots: tuple[str, ...]
    product_slots: tuple[ProductSlot, ...]
    pob_item_type: str = ""
    expects_terminal_error: bool = False
    terminal_error_substring: str = ""

    @property
    def fixture_path(self) -> Path:
        return FIXTURES / self.fixture

    def load_text(self) -> str:
        return self.fixture_path.read_text(encoding="utf-8")


def _spec(
    item_class: SupportedItemClass,
    fixture: str,
    clipboard_item_class: str,
    pob_slots: tuple[str, ...],
    *,
    pob_item_type: str = "",
    expects_terminal_error: bool = False,
    terminal_error_substring: str = "",
) -> SupportedItemSpec:
    product_slots = tuple(pob_slot_to_product(slot, item_type=pob_item_type or None) for slot in pob_slots)
    return SupportedItemSpec(
        item_class=item_class,
        fixture=fixture,
        clipboard_item_class=clipboard_item_class,
        pob_slots=pob_slots,
        product_slots=product_slots,
        pob_item_type=pob_item_type,
        expects_terminal_error=expects_terminal_error,
        terminal_error_substring=terminal_error_substring,
    )


SUPPORTED_ITEM_MATRIX: tuple[SupportedItemSpec, ...] = (
    _spec(SupportedItemClass.HELMET, "helmet_sample.txt", "Helmets", ("Helmet",)),
    _spec(SupportedItemClass.BODY_ARMOUR, "body_armour_sample.txt", "Body Armours", ("Body Armour",)),
    _spec(SupportedItemClass.GLOVES, "gloves_sample.txt", "Gloves", ("Gloves",)),
    _spec(SupportedItemClass.BOOTS, "boots_sample.txt", "Boots", ("Boots",)),
    _spec(SupportedItemClass.BELT, "belt_sample.txt", "Belts", ("Belt",)),
    _spec(SupportedItemClass.RING, "ring1_candidate.txt", "Rings", ("Ring 1", "Ring 2")),
    _spec(SupportedItemClass.AMULET, "amulet_sample.txt", "Amulets", ("Amulet",)),
    # M1.3: Jewels are now supported (occupied-socket replacement, multi-socket
    # ranking, empty-allocated-socket comparison -- see
    # tests/integration/test_jewel_real_pob.py and
    # docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md's Jewel row), so this no
    # longer expects a terminal error. `pob_slots`/`product_slots` stay empty
    # here rather than modeling a fake fixed slot: a Jewel's compatible
    # sockets are dynamic, per-build tree-node ids ("Jewel <nodeId>"), which
    # this matrix's static-slot-tuple shape cannot represent -- see
    # `poe2value.items.slots.is_jewel_socket_pob_slot`.
    _spec(
        SupportedItemClass.JEWEL,
        "jewel_sample.txt",
        "Jewels",
        (),
    ),
    _spec(SupportedItemClass.ONE_HAND_WEAPON, "weapon_1h_sample.txt", "Wands", ("Weapon 1",)),
    _spec(SupportedItemClass.TWO_HAND_WEAPON, "weapon_2h_sample.txt", "Staves", ("Weapon 1",)),
    _spec(
        SupportedItemClass.OFFHAND,
        "offhand_focus_sample.txt",
        "Foci",
        ("Weapon 2",),
        pob_item_type="Focus",
    ),
)


SLOT_RESOLUTION_TABLE: tuple[dict[str, str], ...] = tuple(
    {
        "raw_class": spec.clipboard_item_class,
        "normalized_class": spec.item_class.value,
        "fixture": spec.fixture,
        "pob_slot": ", ".join(spec.pob_slots) or "—",
        "product_slot": ", ".join(slot.value for slot in spec.product_slots) or "—",
        "supported": "terminal_error" if spec.expects_terminal_error else "yes",
    }
    for spec in SUPPORTED_ITEM_MATRIX
)


def matrix_recognized(spec: SupportedItemSpec) -> bool:
    raw = RawItemInput.from_text(spec.load_text(), source=ItemInputSource.CLIPBOARD)
    return recognize_input(raw).recognized
