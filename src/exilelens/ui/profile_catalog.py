from __future__ import annotations

from dataclasses import dataclass

from exilelens.items.value_profiles import ValueProfile


@dataclass(frozen=True)
class ProfileCard:
    profile: ValueProfile
    title: str
    description: str


PROFILE_CARDS: tuple[ProfileCard, ...] = (
    ProfileCard(
        ValueProfile.BALANCED,
        "Balanced",
        "General-purpose evaluation that weighs damage and survivability evenly.",
    ),
    ProfileCard(
        ValueProfile.MAPPING,
        "Mapping",
        "Rewards clear speed: more damage and faster movement, less weight on defences.",
    ),
    ProfileCard(
        ValueProfile.BOSSING,
        "Bossing",
        "Rewards damage you can use against big hits: offense plus max-hit survival.",
    ),
    ProfileCard(
        ValueProfile.DEFENSIVE,
        "Defensive",
        "Survival first: EHP, max hit and resistance caps outweigh damage.",
    ),
)
