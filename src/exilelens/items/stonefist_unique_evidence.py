"""Evidence for Way of the Stonefist on unique gloves (CORPUS-02C follow-up).

Nothing here is a guessed modifier. Values and lines always come from PoB's own
data (``get_item_transform_mods`` / ``get_mod_lines``); this module only records the
two facts PoB's runtime data cannot answer, each with its source:

``UNIQUE_GLOVE_MODS``
    Which game modifiers a unique glove carries. PoB's unique definitions are text,
    and 77 of their 217 glove lines are printed identically by several modifiers
    that transform differently (e.g. Lochtonial Caress's "+(40-60) to maximum Life"
    by 13 modifiers); PoB's export source (``src/Export/Uniques/gloves.lua``) names a
    different modifier than the game for 21 of the 32 uniques below. The ids here are
    the modifiers observed on real items: poe.ninja character data, Runes of Aldur
    league, snapshot 2026-09-27, untransformed items of any character and transformed
    items of Way of the Stonefist characters (item fields only; no account or
    character identifiers were stored). Vaal-mutated modifiers vary per item and are
    matched separately.

``GAME_ONLY_TARGETS``
    Transformed ("HandWraps...") modifiers the game has but the supported PoB's data
    lacks (GGPK export, repoe-fork poe2 ``mods.json``, 2026-09-11): ``removed`` have no
    displayed stat, so the source line disappears (observed: Facebreaker loses its
    Stun Buildup line); ``unavailable`` have stats PoB cannot supply, so a glove
    carrying their source cannot be measured.

The transformation rule itself -- every modifier ``X`` becomes ``HandWrapsX`` when the
game has that modifier, otherwise it stays -- was checked against every one of
231 untransformed/transformed pairs of the uniques below. See docs/CORPUS-02C.md §10.
"""

from __future__ import annotations

EVIDENCE_SOURCE = "poe.ninja Runes of Aldur character data, 2026-09-27"

GAME_ONLY_TARGETS: dict[str, frozenset[str]] = {
    "removed": frozenset({
        "HandWrapsUniqueCriticalStrikesCannotBeRerolled1",
        "HandWrapsUniqueElementalDamageConvertToCold1",
        "HandWrapsUniqueElementalDamageConvertToLightning1",
        "HandWrapsUniqueShockImmunityWhenShocked1",
        "HandWrapsThunderfistUnique__1",
        "HandWrapsUniqueStunDamageIncrease1",
    }),
    "unavailable": frozenset({
        "HandWrapsUniqueIntelligence51",
        "HandWrapsUniqueIncreasedLife62",
        "HandWrapsUniqueLocalIncreasedArmourAndEnergyShield30",
    }),
}

#: Unique glove name -> the modifiers observed on real items (untransformed, and
#: transformed mapped back to their source), with how many items of each were seen.
UNIQUE_GLOVE_MODS: dict[str, dict[str, object]] = {
    "Atziri's Acuity": {"mods": ("UniqueIncreasedLife58", "UniqueLifeLeech2", "PercentOfPhysicalHitDamageAsAdditionalBloodLoss", "UniqueVaalPact1", "UniqueAtziriHeraldSkill1", "UniqueLocalIncreasedPhysicalDamageReductionRatingPercent11"), "untransformed": 3, "transformed": 3},
    "Dreadfist": {"mods": ("UniqueLocalIncreasedPhysicalDamageReductionRatingPercent6", "UniqueCriticalMultiplier2", "UniqueImpaleOnCriticalHit1", "UniqueCriticalsCannotConsumeImpale1", "UniqueAttackerTakesDamage8"), "untransformed": 2, "transformed": 1},
    "Facebreaker": {"mods": ("UniqueBaseDamageOverrideForMaceAttacks1", "UniqueStunDamageIncrease1", "UniqueUnarmedAttackDamagePerXStrength1", "UnarmedStrikeRangeUnique1", "UniqueGainArmourEqualToStrength1", "UniqueOneHandMaceSkillsUsableUnarmed1"), "untransformed": 3, "transformed": 5},
    "Hateforge": {"mods": ("UniqueLocalIncreasedPhysicalDamageReductionRatingPercent23", "UniqueRageOnAnyHit1", "UniqueGainChargesOnMaximumRage1", "UniqueLoseRageOnMaximumRage1", "UniqueMaximumRage1"), "untransformed": 3, "transformed": 1},
    "Lochtonial Caress": {"mods": ("UniqueShareChargesWithAllies1", "UniqueIncreasedSkillSpeed1", "UniqueMaximumManaIncrease3", "UniqueIncreasedLife9", "UniqueLocalIncreasedPhysicalDamageReductionRating3"), "untransformed": 0, "transformed": 4},
    "Empire's Grasp": {"mods": ("UniqueEnemyKnockbackDirectionReversed1", "UniqueLocalIncreasedPhysicalDamageReductionRatingPercent30", "UniqueStrength41", "UniqueLifeGainedFromEnemyDeath11", "UniqueIncreasedPhysicalDamagePercent1"), "untransformed": 3, "transformed": 2},
    "Grip of Winter": {"mods": ("UniqueLocalIncreasedEvasionRatingPercent6", "UniqueAddedColdDamage1", "UniqueFreezeDamageIncrease2", "UniqueChillEffect1", "UniqueColdResist24"), "untransformed": 1, "transformed": 1},
    "Horror's Flight": {"mods": ("UniqueCrushingFearSkill1", "UniqueLocalIncreasedEvasionRatingPercent36", "UniqueIncreasedAttackSpeed16", "UniqueDexterity45", "UniqueAddedChaosDamage5", "UniqueGainFearIncarnateOnCulling1", "UniqueCanBeInstilled", "UniqueNothingHappened"), "untransformed": 3, "transformed": 5},
    "Idle Hands": {"mods": ("UniqueFullManaThreshold1", "UniqueIncreasedAttackSpeedFullMana1", "UniqueIncreasedAccuracy4", "UniqueIntelligence19", "UniqueLocalIncreasedEvasionRatingPercent7"), "untransformed": 3, "transformed": 2},
    "Maligaro's Virtuosity": {"mods": ("UniqueLocalIncreasedEvasionRatingPercent12", "UniqueCriticalStrikeChance5", "UniqueIncreasedAttackSpeed3", "UniqueDexterity19", "UniqueCriticalStrikesCannotBeRerolled1", "UniqueCriticalStrikeMultiplierOverride1"), "untransformed": 3, "transformed": 3},
    "Northpaw": {"mods": ("UniqueCriticalMultiplier1", "UniqueAddedPhysicalDamage2", "UniqueOverrideWeaponBaseCritical1", "UniqueLocalIncreasedEvasionRating4"), "untransformed": 3, "transformed": 4},
    "Snakebite": {"mods": ("UniqueLocalIncreasedEvasionRatingPercent8", "UniqueChaosResist6", "UniqueBaseChanceToPoison1", "UniquePoisonStackCount1", "UniqueLifeRegeneration12"), "untransformed": 3, "transformed": 1},
    "Candlemaker": {"mods": ("UniqueLocalIncreasedEnergyShieldPercent2", "UniqueFireResist2", "UniqueColdResist1", "UniqueDoubleIgniteChance1", "UniqueFireDamagePercent2", "UniqueColdDamagePercent2"), "untransformed": 3, "transformed": 2},
    "Demon Stitcher": {"mods": ("UniqueIncreasedCastSpeed7", "UniqueLocalIncreasedEnergyShield4", "UniqueIncreasedLife15", "UniqueSacrificeLifeToGainEnergyShield1"), "untransformed": 3, "transformed": 1},
    "Doedre's Tenure": {"mods": ("UniqueIncreasedCastSpeed6", "UniqueSpellDamage1", "UniqueIntelligence18", "UniqueLocalIncreasedEnergyShield10"), "untransformed": 3, "transformed": 4},
    "Essentia Sanguis": {"mods": ("UniqueAddedLightningDamage3", "UniqueLightningResist26", "UniqueLocalIncreasedEvasionAndEnergyShield17", "UniqueIntelligence34", "UniqueLeechEnergyShieldInsteadofLife1"), "untransformed": 3, "transformed": 4},
    "Kitoko's Current": {"mods": ("UniqueLocalIncreasedEnergyShieldPercent7", "UniqueDexterity10", "UniqueAttackAndCastSpeed1", "UniqueLightningDamageCanElectrocute1"), "untransformed": 3, "transformed": 1},
    "Leopold's Applause": {"mods": ("UniqueLocalIncreasedEnergyShieldPercent25", "UniqueIncreasedMana48", "UniqueItemFoundRarityIncrease21", "UniqueElementalPenetrationBelowZero1", "UniqueElementalPenetration1"), "untransformed": 3, "transformed": 2},
    "Nightscale": {"mods": ("UniqueLocalIncreasedEnergyShieldPercent20", "UniqueIntelligence10", "UniqueColdResist30", "UniqueNoManaRegenIfNotCritRecently1", "UniqueManaRegenerationRateIfCritRecently1", "UniqueCriticalStrikeChance14"), "untransformed": 3, "transformed": 5},
    "Painter's Servant": {"mods": ("UniqueElementalDamageConvertToFire1", "UniqueElementalDamageConvertToCold1", "UniqueElementalDamageConvertToLightning1", "UniqueElementalDamageGainedAsFire1", "UniqueElementalDamageGainedAsCold1", "UniqueElementalDamageGainedAsLightning1"), "untransformed": 3, "transformed": 4},
    "Aerisvane's Wings": {"mods": ("UniqueLocalIncreasedArmourAndEvasion15", "UniqueDecimatingStrike1", "UniqueIntelligence22", "UniqueIncreasedAttackSpeed4"), "untransformed": 3, "transformed": 2},
    "Aurseize": {"mods": ("UniqueLocalIncreasedArmourAndEvasion1", "UniqueItemFoundRarityIncrease1", "UniqueMaximumLifeOnKillPercent1"), "untransformed": 3, "transformed": 3},
    "Deathblow": {"mods": ("UniqueLocalIncreasedArmourAndEvasion7", "UniqueLifeGainedFromEnemyDeath4", "UniqueManaGainedFromEnemyDeath5", "UniqueCullingStrike1", "UniqueIncreasedAttackSpeed8"), "untransformed": 3, "transformed": 4},
    "Jarngreipr": {"mods": ("UniqueIncreasedLife10", "UniqueAddedPhysicalDamage3", "UniqueIncreasedAttackSpeed2", "UniqueStrengthSatisfiesAllWeaponRequirements1", "UniqueLocalIncreasedArmourAndEvasion25"), "untransformed": 3, "transformed": 1},
    "Valako's Vice": {"mods": ("UniqueLocalIncreasedArmourAndEvasion19", "UniqueStrength23", "UniqueDexterity24", "UniqueLightningResist23", "UniqueFireDamageConvertToLightning1", "UniqueIncreasedAttackSpeed11"), "untransformed": 3, "transformed": 3},
    "Blueflame Bracers": {"mods": ("UniqueIntelligence12", "UniqueFireResist7", "UniqueColdResist9", "UniqueFireDamageConvertToCold1", "UniqueLocalIncreasedEnergyShield11"), "untransformed": 3, "transformed": 2},
    "Gravebind": {"mods": ("UniqueLocalIncreasedArmourAndEnergyShield4", "UniqueColdResist25", "UniqueLifeGainedFromEnemyDeath3", "UniqueManaGainedFromEnemyDeath4", "UniqueEnemiesKilledCountAsYours1"), "untransformed": 3, "transformed": 2},
    "Shackles of the Wretched": {"mods": ("UniqueLocalIncreasedArmourAndEnergyShield3", "UniqueChillImmunityWhenChilled1", "UniqueFreezeImmunityWhenFrozen1", "UniqueIgniteImmunityWhenIgnited1", "UniqueReflectCurseToSelf1", "UniqueShockImmunityWhenShocked1"), "untransformed": 3, "transformed": 1},
    "Hand of Wisdom and Action": {"mods": ("UniqueDexterity31", "UniqueIntelligence31", "UniqueLightningDamageToAttacksPerIntelligence1", "UniqueIncreasedAttackSpeedPerDexterity1"), "untransformed": 3, "transformed": 5},
    "Plaguefinger": {"mods": ("UniqueIncreasedAttackSpeed1", "UniqueCannotInflictElementalAilments1", "UniqueAllDamageCanPoison1", "UniqueBaseChanceToPoison2", "UniqueLocalIncreasedEvasionAndEnergyShield4"), "untransformed": 3, "transformed": 2},
    "Thunderfist": {"mods": ("ThunderfistUnique__1", "UniqueLocalIncreasedEvasionAndEnergyShield19", "UniqueIncreasedAttackSpeed13", "UniqueLightningResist29", "AddedLightningDamageWhileUnarmedUniqueGloves_1", "BaseUnarmedCriticalStrikeChanceUnique__2"), "untransformed": 0, "transformed": 5},
    "Sine Aequo": {"mods": ("UniqueIncreasedSkillSpeed5", "UniqueLocalArmourAndEvasionAndEnergyShield3", "UniqueImmobiliseThreshold1", "UniqueImmobiliseIncreasedDamageTaken1"), "untransformed": 3, "transformed": 2},
}

__all__ = ["EVIDENCE_SOURCE", "GAME_ONLY_TARGETS", "UNIQUE_GLOVE_MODS"]
