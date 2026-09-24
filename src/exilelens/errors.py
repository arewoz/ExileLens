from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineError(Exception):
    code: str
    message: str
    details: dict | None = None

    def to_dict(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class PobPathInvalid(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("POB_PATH_INVALID", message, details)


class PobBootFailed(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("POB_BOOT_FAILED", message, details)


class UnsupportedPobRevision(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("UNSUPPORTED_POB_REVISION", message, details)


class PobLoadoutApiUnsupported(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("POB_LOADOUT_API_UNSUPPORTED", message, details)


class BuildNotFound(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("BUILD_NOT_FOUND", message, details)


class BuildParseFailed(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("BUILD_PARSE_FAILED", message, details)


class BuildSourceIncomplete(EngineError):
    """Build XML on disk is unreadable or incomplete (e.g. PoB caught mid-save)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__("BUILD_SOURCE_INCOMPLETE", message, details)


class StaleBuildGeneration(EngineError):
    """A request was prepared for a different loaded build revision than the worker holds."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__("STALE_BUILD_GENERATION", message, details)


class NoBuildLoaded(EngineError):
    def __init__(self, message: str = "No build is loaded", details: dict | None = None):
        super().__init__("NO_BUILD_LOADED", message, details)


class ItemParseFailed(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("ITEM_PARSE_FAILED", message, details)


class ItemIncompatible(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("ITEM_INCOMPATIBLE", message, details)


class SlotInvalid(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("SLOT_INVALID", message, details)


class CalcFailed(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("CALC_FAILED", message, details)


class RestoreFailed(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("RESTORE_FAILED", message, details)


class WorkerUnhealthy(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("WORKER_UNHEALTHY", message, details)


class NotPoe2Item(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("NOT_POE2_ITEM", message, details)


class ItemUnsupported(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("ITEM_UNSUPPORTED", message, details)


class UnsupportedGameLanguage(EngineError):
    """LANG-01: the clipboard text came from a non-English PoE 2 client.

    Raised instead of the raw parser failure only when language detection is
    confident. The original error is preserved in ``details["original_error"]`` so
    debug logs never lose a genuine English parser bug.
    """

    def __init__(self, message: str, details: dict | None = None):
        super().__init__("UNSUPPORTED_GAME_LANGUAGE", message, details)

    @property
    def detected_language(self) -> str:
        return str((self.details or {}).get("detected_language") or "")

    @property
    def language_code(self) -> str:
        return str((self.details or {}).get("language_code") or "")

    @property
    def confidence(self) -> float:
        try:
            return float((self.details or {}).get("confidence") or 0.0)
        except (TypeError, ValueError):
            return 0.0


class SlotResolutionFailed(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("SLOT_RESOLUTION_FAILED", message, details)


class SlotResolutionAmbiguous(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("SLOT_RESOLUTION_AMBIGUOUS", message, details)


class NoCompatibleSlot(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("NO_COMPATIBLE_SLOT", message, details)


class EvaluationInvalidBuildState(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("EVALUATION_INVALID_BUILD_STATE", message, details)


class PrimaryMetricUnresolved(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("PRIMARY_METRIC_UNRESOLVED", message, details)


class BaselineItemUnresolved(EngineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__("BASELINE_ITEM_UNRESOLVED", message, details)


ERROR_MAP = {
    "POB_PATH_INVALID": PobPathInvalid,
    "POB_BOOT_FAILED": PobBootFailed,
    "UNSUPPORTED_POB_REVISION": UnsupportedPobRevision,
    "POB_LOADOUT_API_UNSUPPORTED": PobLoadoutApiUnsupported,
    "BUILD_NOT_FOUND": BuildNotFound,
    "BUILD_PARSE_FAILED": BuildParseFailed,
    "BUILD_SOURCE_INCOMPLETE": BuildSourceIncomplete,
    "STALE_BUILD_GENERATION": StaleBuildGeneration,
    "NO_BUILD_LOADED": NoBuildLoaded,
    "ITEM_PARSE_FAILED": ItemParseFailed,
    "ITEM_INCOMPATIBLE": ItemIncompatible,
    "SLOT_INVALID": SlotInvalid,
    "CALC_FAILED": CalcFailed,
    "RESTORE_FAILED": RestoreFailed,
    "WORKER_UNHEALTHY": WorkerUnhealthy,
    "NOT_POE2_ITEM": NotPoe2Item,
    "ITEM_UNSUPPORTED": ItemUnsupported,
    "UNSUPPORTED_GAME_LANGUAGE": UnsupportedGameLanguage,
    "SLOT_RESOLUTION_FAILED": SlotResolutionFailed,
    "SLOT_RESOLUTION_AMBIGUOUS": SlotResolutionAmbiguous,
    "NO_COMPATIBLE_SLOT": NoCompatibleSlot,
    "EVALUATION_INVALID_BUILD_STATE": EvaluationInvalidBuildState,
    "PRIMARY_METRIC_UNRESOLVED": PrimaryMetricUnresolved,
    "BASELINE_ITEM_UNRESOLVED": BaselineItemUnresolved,
}


def raise_from_payload(payload: dict) -> None:
    code = payload.get("code", "CALC_FAILED")
    message = payload.get("message", "Unknown engine error")
    details = payload.get("details")
    exc_type = ERROR_MAP.get(code, CalcFailed)
    raise exc_type(message, details)
