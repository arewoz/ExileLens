"""Unit coverage for the socketed-modifier stripper behind "Ignore socketed
modifiers in Item Check" (items/socket_normalize.py).
"""

from __future__ import annotations

import pytest

from poe2value.items.socket_normalize import strip_socketed_modifiers

pytestmark = pytest.mark.itemcheck

# Real fixture text (fixtures/builds/public_corpus/core04_bow_quiver.xml, item id
# 11 "Hysseg's Claw") -- the exact example from the product brief: two rune-granted
# lines (one plain, one "Bonded:") counted inside "Implicits: 4" alongside two real
# implicits ("Minions deal..." and "Grants Skill...").
_RUNE_BOW = """Rarity: UNIQUE
Hysseg's Claw
Runemastered Familial Talisman
Unique ID: 000000000000000000000000000000000000000000000000000000000000000b
Item Level: 70
Quality: 20
Sockets: S S
Rune: Greater Iron Rune
Rune: Greater Iron Rune
LevelReq: 55
Implicits: 4
{enchant}{rune}36% increased Physical Damage
{enchant}{rune}Bonded: 40% increased effect of Fully Broken Armour
Minions deal 83% increased Damage
Grants Skill: Level 15 Cackling Companions
85% increased Physical Damage
6% increased Movement Speed
+14 to Strength"""


def test_rune_and_bonded_lines_are_removed_and_implicits_count_decremented() -> None:
    result = strip_socketed_modifiers(_RUNE_BOW)
    assert result.changed is True
    assert len(result.removed_lines) == 2
    assert any("36% increased Physical Damage" in line for line in result.removed_lines)
    assert any("Fully Broken Armour" in line for line in result.removed_lines)

    lines = result.text.splitlines()
    assert "Implicits: 2" in lines
    assert not any("{rune}" in line or "{soulcore}" in line for line in lines)
    assert not any(line.strip().lower().startswith("bonded:") for line in lines)


def test_socket_headers_and_socket_count_are_preserved() -> None:
    result = strip_socketed_modifiers(_RUNE_BOW)
    lines = result.text.splitlines()
    assert "Sockets: S S" in lines
    assert lines.count("Rune: Greater Iron Rune") == 2


def test_real_implicits_and_explicits_survive_untouched() -> None:
    result = strip_socketed_modifiers(_RUNE_BOW)
    lines = result.text.splitlines()
    assert "Minions deal 83% increased Damage" in lines
    assert "Grants Skill: Level 15 Cackling Companions" in lines
    assert "85% increased Physical Damage" in lines
    assert "6% increased Movement Speed" in lines
    assert "+14 to Strength" in lines


def test_item_with_no_socketed_modifiers_is_unchanged() -> None:
    plain = """Rarity: RARE
Arcane Loop
Sapphire Ring
LevelReq: 80
Implicits: 1
+30% to Cold Resistance
+179 to maximum Mana
+89 to maximum Energy Shield
30% increased Lightning Damage
+45% to Fire Resistance
69% increased Mana Regeneration Rate
+27% to Chaos Resistance"""
    result = strip_socketed_modifiers(plain)
    assert result.changed is False
    assert result.text == plain
    assert result.removed_lines == ()


def test_fractured_crafted_desecrated_and_enchant_lines_are_never_stripped() -> None:
    item = """Rarity: RARE
Rift Grip
Secured Wraps
Item Level: 80
Implicits: 2
{enchant}Allocates Desperate Times
{enchant}Allocates Last Stand
{fractured}Adds 4 to 71 Lightning damage to Attacks
{desecrated}+2 to Level of all Projectile Skills
{crafted}29% increased Critical Damage Bonus
Corrupted"""
    result = strip_socketed_modifiers(item)
    assert result.changed is False
    assert "{enchant}Allocates Desperate Times" in result.text
    assert "{fractured}Adds 4 to 71 Lightning damage to Attacks" in result.text
    assert "{desecrated}+2 to Level of all Projectile Skills" in result.text
    assert "{crafted}29% increased Critical Damage Bonus" in result.text


def test_live_client_trailing_tag_style_is_also_recognized() -> None:
    # The live client tags provenance directly on the mod line instead of counting
    # it in an "Implicits:" header (see bridge.lua's own comment on this format).
    item = """Rarity: RARE
Test Bow
Item Level: 80
Sockets: S
Rune: Iron Rune
LevelReq: 1
36% increased Physical Damage (rune)
Bonded: 40% increased effect of Fully Broken Armour (bonded)
10% increased Attack Speed"""
    result = strip_socketed_modifiers(item)
    assert result.changed is True
    assert len(result.removed_lines) == 2
    assert "10% increased Attack Speed" in result.text.splitlines()
