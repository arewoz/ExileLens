"""LANG-01: cheap, deterministic detection of non-English PoE 2 clipboard text.

Why this exists
---------------
ExileLens analyzes English PoE 2 clipboard items. A localized client produces text
the parser cannot resolve, and PoB's bridge reports that as
``item base type could not be resolved`` -- which reads as "your item is broken"
rather than "your client is not English". This module is the classifier that lets
the pipeline tell those two apart.

Scope guard
-----------
This is NOT a localization layer. It does not map localized bases or mods to their
English equivalents, it reads no game files, and it makes no network calls. It only
answers "which localized client did this text most likely come from?".

Extension point (LOCALIZATION-01)
---------------------------------
When a canonical localization layer arrives, the detection below stays as-is; the
only change needed is at the single call site in
``exilelens.items.evaluation._classify_localization_failure``: instead of raising
``UnsupportedGameLanguage``, route ``(raw_text, detection.language)`` through the
canonicalizer and re-enter the existing English analyzer. Nothing downstream of
that call site needs to change, because the UI already consumes a typed error and
never parses message strings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

# A Latin-script language needs this many distinct structural marker categories
# before we are willing to name it, and it must beat the runner-up by this margin.
# One ambiguous ordinary word must never be enough.
MIN_LATIN_SCORE = 2
MIN_LATIN_MARGIN = 1

# Below this, callers must treat the detection as UNKNOWN and preserve the
# original parser error.
CONFIDENT_THRESHOLD = 0.7


class PoeItemLanguage(str, Enum):
    ENGLISH = "en"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"
    JAPANESE = "ja"
    KOREAN = "ko"
    PORTUGUESE_BR = "pt-BR"
    RUSSIAN = "ru"
    THAI = "th"
    UNKNOWN = "unknown"


DISPLAY_NAMES: dict[PoeItemLanguage, str] = {
    PoeItemLanguage.ENGLISH: "English",
    PoeItemLanguage.FRENCH: "French",
    PoeItemLanguage.GERMAN: "German",
    PoeItemLanguage.SPANISH: "Spanish",
    PoeItemLanguage.JAPANESE: "Japanese",
    PoeItemLanguage.KOREAN: "Korean",
    PoeItemLanguage.PORTUGUESE_BR: "Portuguese (Brazil)",
    PoeItemLanguage.RUSSIAN: "Russian",
    PoeItemLanguage.THAI: "Thai",
    PoeItemLanguage.UNKNOWN: "Unknown",
}


@dataclass(frozen=True)
class LanguageDetection:
    language: PoeItemLanguage = PoeItemLanguage.UNKNOWN
    confidence: float = 0.0
    evidence: tuple[str, ...] = field(default_factory=tuple)
    item_like: bool = False

    @property
    def display_name(self) -> str:
        return DISPLAY_NAMES.get(self.language, "Unknown")

    @property
    def is_confident_non_english(self) -> bool:
        """The only predicate callers should branch on."""
        return (
            self.item_like
            and self.language not in (PoeItemLanguage.UNKNOWN, PoeItemLanguage.ENGLISH)
            and self.confidence >= CONFIDENT_THRESHOLD
        )


# --------------------------------------------------------------------------- #
# Structural vocabulary
#
# Only PoE item *structure* lives here -- rarity, item class, requirements, level,
# defences, quality, sockets, status flags. Item names are deliberately excluded:
# "Couronne divine" must not be what decides a language, the headers around it must.
# A term listed under two languages (Spanish/Portuguese share several) scores for
# both and therefore discriminates nothing -- that is the point of the margin rule.
# --------------------------------------------------------------------------- #

_STRUCTURAL_MARKERS: dict[PoeItemLanguage, dict[str, tuple[str, ...]]] = {
    PoeItemLanguage.ENGLISH: {
        "rarity": ("rarity",),
        "item_class": ("item class",),
        "requirements": ("requirements",),
        "level": ("level",),
        "armour": ("armour",),
        "energy_shield": ("energy shield",),
        "evasion": ("evasion rating", "evasion"),
        "quality": ("quality",),
        "sockets": ("sockets",),
        "item_level": ("item level",),
        "status": ("unidentified", "corrupted"),
    },
    PoeItemLanguage.FRENCH: {
        "rarity": ("rareté",),
        "item_class": ("classe d'objet",),
        "requirements": ("prérequis", "exigences"),
        "level": ("niveau",),
        "armour": ("armure",),
        "energy_shield": ("bouclier d'énergie",),
        "evasion": ("évasion",),
        "quality": ("qualité",),
        "sockets": ("emplacements",),
        "item_level": ("niveau d'objet",),
        "status": ("non identifié", "corrompu", "corrompue"),
    },
    PoeItemLanguage.GERMAN: {
        "rarity": ("seltenheit",),
        "item_class": ("gegenstandsklasse",),
        "requirements": ("anforderungen",),
        "level": ("stufe",),
        "armour": ("rüstung",),
        "energy_shield": ("energieschild",),
        "evasion": ("ausweichen",),
        "quality": ("qualität",),
        "sockets": ("fassungen",),
        "item_level": ("gegenstandsstufe",),
        "status": ("unidentifiziert", "verderbt"),
    },
    PoeItemLanguage.SPANISH: {
        "rarity": ("rareza",),
        "item_class": ("clase de objeto",),
        "requirements": ("requisitos",),
        "level": ("nivel",),
        "armour": ("armadura",),
        "energy_shield": ("escudo de energía",),
        "evasion": ("evasión",),
        "quality": ("calidad",),
        "sockets": ("engarces",),
        "item_level": ("nivel de objeto",),
        "status": ("sin identificar", "corrupto"),
    },
    PoeItemLanguage.PORTUGUESE_BR: {
        "rarity": ("raridade",),
        "item_class": ("classe do item", "classe de item"),
        "requirements": ("requisitos",),
        "level": ("nível",),
        "armour": ("armadura",),
        "energy_shield": ("escudo de energia",),
        "evasion": ("evasão",),
        "quality": ("qualidade",),
        "sockets": ("encaixes",),
        "item_level": ("nível do item",),
        "status": ("não identificado", "corrompido"),
    },
    PoeItemLanguage.RUSSIAN: {
        "rarity": ("редкость",),
        "item_class": ("класс предмета",),
        "requirements": ("требования",),
        "level": ("уровень",),
        "armour": ("броня",),
        "energy_shield": ("энергетический щит",),
        "evasion": ("уклонение",),
        "quality": ("качество",),
        "sockets": ("гнёзда", "гнезда"),
        "item_level": ("уровень предмета",),
        "status": ("неопознан", "осквернён", "осквернен"),
    },
    PoeItemLanguage.JAPANESE: {
        "rarity": ("レアリティ",),
        "item_class": ("アイテムクラス",),
        "requirements": ("要求",),
        "level": ("レベル",),
        "armour": ("アーマー",),
        "energy_shield": ("エネルギーシールド",),
        "evasion": ("回避",),
        "quality": ("クオリティ", "品質"),
        "sockets": ("ソケット",),
        "item_level": ("アイテムレベル",),
        "status": ("未鑑定", "コラプト"),
    },
    PoeItemLanguage.KOREAN: {
        "rarity": ("희귀도",),
        "item_class": ("아이템 종류", "아이템 등급"),
        "requirements": ("요구 사항", "요구사항"),
        "level": ("레벨",),
        "armour": ("방어구", "아머"),
        "energy_shield": ("에너지 보호막",),
        "evasion": ("회피",),
        "quality": ("품질",),
        "sockets": ("홈",),
        "item_level": ("아이템 레벨",),
        "status": ("미확인", "타락"),
    },
    PoeItemLanguage.THAI: {
        "rarity": ("ความหายาก",),
        "item_class": ("ประเภทไอเทม",),
        "requirements": ("ความต้องการ",),
        "level": ("เลเวล",),
        "armour": ("เกราะ",),
        "energy_shield": ("โล่พลังงาน",),
        "evasion": ("การหลบหลีก",),
        "quality": ("คุณภาพ",),
        "sockets": ("ช่องเสียบ",),
        "item_level": ("เลเวลไอเทม",),
        "status": ("ยังไม่ระบุ", "เสื่อมทราม"),
    },
}

_LATIN_LANGUAGES = (
    PoeItemLanguage.FRENCH,
    PoeItemLanguage.GERMAN,
    PoeItemLanguage.SPANISH,
    PoeItemLanguage.PORTUGUESE_BR,
)

# PoE clipboard blocks use a dashed separator in every client language. It is the
# cheapest language-independent "this is an item, not prose" signal we have.
_SEPARATOR_RE = re.compile(r"(?m)^-{4,}\s*$")

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_THAI_RE = re.compile(r"[฀-๿]")
_KANA_RE = re.compile(r"[぀-ヿ]")
_HAN_RE = re.compile(r"[一-鿿]")

_SCRIPT_LANGUAGES: tuple[tuple[re.Pattern[str], PoeItemLanguage], ...] = (
    (_KANA_RE, PoeItemLanguage.JAPANESE),
    (_HANGUL_RE, PoeItemLanguage.KOREAN),
    (_THAI_RE, PoeItemLanguage.THAI),
    (_CYRILLIC_RE, PoeItemLanguage.RUSSIAN),
)


def _normalize(text: str) -> str:
    """NFC + typographic apostrophes + collapsed whitespace, case-folded.

    Accents are preserved on purpose: they are load-bearing for
    Qualite/Qualitaet/Calidad/Qualidade and for Nivel/Nivel.
    """
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("’", "'").replace("ʼ", "'")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t ]+", " ", normalized)
    return normalized.lower()


def _score_markers(normalized: str) -> dict[PoeItemLanguage, tuple[int, list[str]]]:
    """Distinct structural categories matched per language, with the evidence."""
    scores: dict[PoeItemLanguage, tuple[int, list[str]]] = {}
    for language, categories in _STRUCTURAL_MARKERS.items():
        evidence: list[str] = []
        for category, terms in categories.items():
            for term in terms:
                if term in normalized:
                    evidence.append(f"{category}:{term}")
                    break
        scores[language] = (len(evidence), evidence)
    return scores


def _script_hit(text: str) -> tuple[PoeItemLanguage, str] | None:
    for pattern, language in _SCRIPT_LANGUAGES:
        if pattern.search(text):
            return language, f"script:{language.value}"
    if _HAN_RE.search(text):
        # Han without kana is ambiguous (Chinese is not a supported PoE 2 client
        # language); only the Japanese structural vocabulary may claim it.
        return PoeItemLanguage.JAPANESE, "script:han"
    return None


def detect_poe_item_language(raw_text: str) -> LanguageDetection:
    """Classify clipboard text by the client language that produced it.

    Deterministic, allocation-light, no I/O. Returns UNKNOWN whenever the evidence
    is thin or conflicting -- callers must then preserve their original error.
    """
    if not raw_text or not raw_text.strip():
        return LanguageDetection()

    normalized = _normalize(raw_text)
    scores = _score_markers(normalized)
    best_structural = max((count for _lang, (count, _ev) in scores.items()), default=0)
    item_like = bool(_SEPARATOR_RE.search(raw_text)) or best_structural >= 1

    script = _script_hit(raw_text)
    if script is not None:
        language, script_evidence = script
        count, evidence = scores.get(language, (0, []))
        if not item_like:
            # Foreign-script prose is not a PoE item; do not manufacture an item error.
            return LanguageDetection(
                language=PoeItemLanguage.UNKNOWN,
                confidence=0.0,
                evidence=(script_evidence, "not_item_like"),
                item_like=False,
            )
        if script_evidence == "script:han" and not count:
            # Han-only text with no Japanese structure proves nothing.
            return LanguageDetection(
                language=PoeItemLanguage.UNKNOWN,
                confidence=0.0,
                evidence=(script_evidence, "no_structural_markers"),
                item_like=item_like,
            )
        return LanguageDetection(
            language=language,
            confidence=0.95 if count else 0.85,
            evidence=(script_evidence, *evidence),
            item_like=item_like,
        )

    english_count, english_evidence = scores[PoeItemLanguage.ENGLISH]
    ranked = sorted(
        ((lang, scores[lang][0]) for lang in _LATIN_LANGUAGES),
        key=lambda pair: pair[1],
        reverse=True,
    )
    top_language, top_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0

    if (
        top_score >= MIN_LATIN_SCORE
        and top_score - runner_up_score >= MIN_LATIN_MARGIN
        and top_score > english_count
    ):
        return LanguageDetection(
            language=top_language,
            confidence=min(0.95, 0.55 + 0.1 * top_score),
            evidence=tuple(scores[top_language][1]),
            item_like=item_like,
        )

    if english_count >= MIN_LATIN_SCORE and english_count >= top_score:
        return LanguageDetection(
            language=PoeItemLanguage.ENGLISH,
            confidence=min(0.95, 0.55 + 0.1 * english_count),
            evidence=tuple(english_evidence),
            item_like=item_like,
        )

    return LanguageDetection(
        language=PoeItemLanguage.UNKNOWN,
        confidence=0.0,
        evidence=tuple(scores[top_language][1]),
        item_like=item_like,
    )


# --------------------------------------------------------------------------- #
# User-facing copy -- one message, one place.
# --------------------------------------------------------------------------- #

UNSUPPORTED_LANGUAGE_TITLE = "Unsupported game language"

_LEAD = "ExileLens currently analyzes items copied from the English Path of Exile 2 client."
_ACTION = "Switch the game language to English and copy the item again."
_UNKNOWN_LINE = "This item appears to come from a non-English game client."


def unsupported_language_body(detection: LanguageDetection | None) -> str:
    if detection is not None and detection.language not in (
        PoeItemLanguage.UNKNOWN,
        PoeItemLanguage.ENGLISH,
    ):
        middle = f"Detected language: {detection.display_name}"
    else:
        middle = _UNKNOWN_LINE
    return f"{_LEAD}\n\n{middle}\n\n{_ACTION}"
