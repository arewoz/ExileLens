from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from poe2value.market.models import ListingPrice


class CaptureQueueState(str, Enum):
    CAPTURED = "CAPTURED"
    QUEUED = "QUEUED"
    EVALUATING = "EVALUATING"
    EVALUATED = "EVALUATED"
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"


class SessionEndReason(str, Enum):
    USER_STOPPED = "USER_STOPPED"
    BUILD_CHANGED = "BUILD_CHANGED"
    BASELINE_CHANGED = "BASELINE_CHANGED"


@dataclass
class MarketCaptureObservation:
    observation_id: str
    capture_index: int
    item_raw: str
    content_hash: str
    observation_key: str
    queue_state: CaptureQueueState
    price_note_raw: str | None = None
    price: ListingPrice | None = None
    seen_count: int = 1
    slot_match: bool = True
    slot_message: str = ""
    evaluation: dict[str, Any] | None = None
    captured_at: float = field(default_factory=time.time)
    evaluated_at: float | None = None
    request_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "capture_index": self.capture_index,
            "item_raw": self.item_raw,
            "content_hash": self.content_hash,
            "observation_key": self.observation_key,
            "queue_state": self.queue_state.value,
            "price_note_raw": self.price_note_raw,
            "price": self.price.to_dict() if self.price else None,
            "seen_count": self.seen_count,
            "slot_match": self.slot_match,
            "slot_message": self.slot_message,
            "evaluation": self.evaluation,
            "captured_at": self.captured_at,
            "evaluated_at": self.evaluated_at,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketCaptureObservation:
        price = ListingPrice.from_dict(data.get("price"))
        return cls(
            observation_id=str(data.get("observation_id") or uuid.uuid4().hex[:12]),
            capture_index=int(data.get("capture_index") or 0),
            item_raw=str(data.get("item_raw") or ""),
            content_hash=str(data.get("content_hash") or ""),
            observation_key=str(data.get("observation_key") or ""),
            queue_state=CaptureQueueState(str(data.get("queue_state") or CaptureQueueState.CAPTURED.value)),
            price_note_raw=data.get("price_note_raw"),
            price=price,
            seen_count=int(data.get("seen_count") or 1),
            slot_match=bool(data.get("slot_match", True)),
            slot_message=str(data.get("slot_message") or ""),
            evaluation=data.get("evaluation"),
            captured_at=float(data.get("captured_at") or time.time()),
            evaluated_at=data.get("evaluated_at"),
            request_id=data.get("request_id"),
        )


@dataclass
class MarketCaptureSession:
    session_id: str
    active: bool
    target_slot: str
    pob_slot: str
    profile: str
    baseline_generation: int
    baseline_fingerprint: str
    build_revision: dict[str, Any]
    budget: ListingPrice | None = None
    search_intent: dict[str, Any] | None = None
    observations: list[MarketCaptureObservation] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    search_status: dict[str, Any] = field(default_factory=dict)
    best_observation_id: str | None = None
    best_value_observation_id: str | None = None
    ended_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    @property
    def capture_count(self) -> int:
        return len(self.observations)

    @property
    def evaluated_count(self) -> int:
        return sum(1 for row in self.observations if row.queue_state is CaptureQueueState.EVALUATED)

    @property
    def queued_count(self) -> int:
        return sum(
            1
            for row in self.observations
            if row.queue_state in {CaptureQueueState.QUEUED, CaptureQueueState.EVALUATING}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active": self.active,
            "target_slot": self.target_slot,
            "pob_slot": self.pob_slot,
            "profile": self.profile,
            "baseline_generation": self.baseline_generation,
            "baseline_fingerprint": self.baseline_fingerprint,
            "build_revision": self.build_revision,
            "budget": self.budget.to_dict() if self.budget else None,
            "search_intent": self.search_intent,
            "observations": [row.to_dict() for row in self.observations],
            "guidance": self.guidance,
            "search_status": self.search_status,
            "best_observation_id": self.best_observation_id,
            "best_value_observation_id": self.best_value_observation_id,
            "ended_reason": self.ended_reason,
            "metadata": self.metadata,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "capture_count": self.capture_count,
            "evaluated_count": self.evaluated_count,
            "queued_count": self.queued_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketCaptureSession:
        budget = ListingPrice.from_dict(data.get("budget"))
        observations = [MarketCaptureObservation.from_dict(row) for row in (data.get("observations") or [])]
        return cls(
            session_id=str(data.get("session_id") or uuid.uuid4().hex[:16]),
            active=bool(data.get("active", False)),
            target_slot=str(data.get("target_slot") or ""),
            pob_slot=str(data.get("pob_slot") or ""),
            profile=str(data.get("profile") or "BALANCED"),
            baseline_generation=int(data.get("baseline_generation") or 0),
            baseline_fingerprint=str(data.get("baseline_fingerprint") or ""),
            build_revision=dict(data.get("build_revision") or {}),
            budget=budget,
            search_intent=data.get("search_intent"),
            observations=observations,
            guidance=dict(data.get("guidance") or {}),
            search_status=dict(data.get("search_status") or {}),
            best_observation_id=data.get("best_observation_id"),
            best_value_observation_id=data.get("best_value_observation_id"),
            ended_reason=data.get("ended_reason"),
            metadata=dict(data.get("metadata") or {}),
            started_at=float(data.get("started_at") or time.time()),
            ended_at=data.get("ended_at"),
        )
