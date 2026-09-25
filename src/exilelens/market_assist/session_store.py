"""Session lifecycle, rapid capture queue, and history."""

from __future__ import annotations

import time
import uuid
from typing import Any

from exilelens.app.build_revision import BuildFileRevision, read_build_revision
from exilelens.gear.slots import pob_slot_for_product
from exilelens.items.raw_input import RawItemInput
from exilelens.market_assist.guidance import AdaptiveMarketGuidance
from exilelens.market_assist.models import (
    CaptureQueueState,
    MarketCaptureObservation,
    MarketCaptureSession,
    SessionEndReason,
)
from exilelens.market_assist.price_parser import observation_key, parse_price_note
from exilelens.market_assist.search_status import compute_search_status

MAX_SESSION_HISTORY = 20


class MarketCaptureSessionStore:
    """Owns active session, capture queue, and bounded history."""

    def __init__(self) -> None:
        self._session: MarketCaptureSession | None = None
        self._history: list[MarketCaptureSession] = []
        self._guidance = AdaptiveMarketGuidance()
        self._capture_serial = 0
        self._observation_index: dict[str, MarketCaptureObservation] = {}
        self._content_seen: dict[str, MarketCaptureObservation] = {}

    @property
    def active_session(self) -> MarketCaptureSession | None:
        return self._session if self._session and self._session.active else None

    @property
    def history(self) -> list[MarketCaptureSession]:
        return list(self._history)

    def start_session(
        self,
        *,
        target_slot: str,
        profile: str,
        baseline_generation: int,
        baseline_fingerprint: str,
        build_path: str,
        budget: Any | None = None,
        search_intent: dict[str, Any] | None = None,
    ) -> MarketCaptureSession:
        revision = read_build_revision(build_path)
        build_revision = (
            {"path": revision.path, "mtime_ns": revision.mtime_ns, "size": revision.size}
            if revision
            else {"path": build_path, "mtime_ns": 0, "size": 0}
        )
        session = MarketCaptureSession(
            session_id=uuid.uuid4().hex[:16],
            active=True,
            target_slot=target_slot,
            pob_slot=pob_slot_for_product(target_slot),
            profile=profile,
            baseline_generation=baseline_generation,
            baseline_fingerprint=baseline_fingerprint,
            build_revision=build_revision,
            budget=budget,
            search_intent=search_intent,
        )
        session.guidance = self._guidance.compute(session)
        session.search_status = compute_search_status(session)
        self._session = session
        self._capture_serial = 0
        self._observation_index.clear()
        self._content_seen.clear()
        return session

    def stop_session(self, *, reason: SessionEndReason = SessionEndReason.USER_STOPPED) -> MarketCaptureSession | None:
        session = self._session
        if session is None:
            return None
        session.active = False
        session.ended_reason = reason.value
        session.ended_at = time.time()
        self._archive_session(session)
        self._session = None
        return session

    def check_baseline_frozen(
        self,
        *,
        baseline_generation: int,
        baseline_fingerprint: str,
        build_path: str,
    ) -> bool:
        session = self.active_session
        if session is None:
            return False
        revision = read_build_revision(build_path)
        prior = BuildFileRevision(
            path=str(session.build_revision.get("path") or build_path),
            mtime_ns=int(session.build_revision.get("mtime_ns") or 0),
            size=int(session.build_revision.get("size") or 0),
        )
        if revision and revision.changed_from(prior):
            self.stop_session(reason=SessionEndReason.BUILD_CHANGED)
            return True
        if baseline_generation != session.baseline_generation or (
            baseline_fingerprint and baseline_fingerprint != session.baseline_fingerprint
        ):
            self.stop_session(reason=SessionEndReason.BASELINE_CHANGED)
            return True
        return False

    def capture_clipboard(
        self,
        item_raw: str,
        *,
        content_hash: str | None = None,
        compatible_product_slots: set[str] | None = None,
    ) -> tuple[MarketCaptureObservation | None, str]:
        session = self.active_session
        if session is None:
            return None, "No active capture session."

        raw = RawItemInput.from_text(item_raw, content_hash=content_hash)
        parsed_price = parse_price_note(item_raw)
        obs_key = observation_key(raw.content_hash, parsed_price.price)

        existing = self._observation_index.get(obs_key)
        if existing is not None:
            existing.seen_count += 1
            existing.queue_state = CaptureQueueState.DUPLICATE
            return existing, f"Seen {existing.seen_count}× (cached PoB)"

        content_existing = self._content_seen.get(raw.content_hash)
        if content_existing is not None and content_existing.price != parsed_price.price:
            pass
        elif content_existing is not None:
            content_existing.seen_count += 1
            content_existing.queue_state = CaptureQueueState.DUPLICATE
            return content_existing, f"Seen {content_existing.seen_count}× (cached PoB)"

        slot_match = True
        slot_message = ""
        if compatible_product_slots is not None:
            slot_match = session.target_slot in compatible_product_slots
            if not slot_match:
                slot_message = f"Wrong slot — ignoring for {session.target_slot}"

        self._capture_serial += 1
        observation = MarketCaptureObservation(
            observation_id=uuid.uuid4().hex[:12],
            capture_index=self._capture_serial,
            item_raw=item_raw,
            content_hash=raw.content_hash,
            observation_key=obs_key,
            queue_state=CaptureQueueState.CAPTURED if slot_match else CaptureQueueState.INVALID,
            price_note_raw=parsed_price.raw_price_note,
            price=parsed_price.price,
            slot_match=slot_match,
            slot_message=slot_message,
        )
        if slot_match:
            observation.queue_state = CaptureQueueState.QUEUED
            session.observations.append(observation)
            self._observation_index[obs_key] = observation
            self._content_seen[raw.content_hash] = observation
            self._refresh_session_state(session)
            return observation, f"CAPTURED #{observation.capture_index}"

        session.observations.append(observation)
        return observation, slot_message or "Invalid slot"

    def mark_evaluating(self, observation_id: str, request_id: int) -> None:
        row = self._observation_index.get(observation_id) or self._find_observation(observation_id)
        if row is None:
            return
        row.queue_state = CaptureQueueState.EVALUATING
        row.request_id = request_id

    def apply_evaluation(self, observation_id: str, evaluation: dict[str, Any]) -> None:
        session = self.active_session
        row = self._observation_index.get(observation_id) or self._find_observation(observation_id)
        if row is None or session is None:
            return
        row.evaluation = evaluation
        row.evaluated_at = time.time()
        row.queue_state = CaptureQueueState.EVALUATED if evaluation.get("status") != "error" else CaptureQueueState.INVALID
        self._refresh_session_state(session)

    def pending_observations(self) -> list[MarketCaptureObservation]:
        session = self.active_session
        if session is None:
            return []
        return [
            row
            for row in session.observations
            if row.slot_match and row.queue_state in {CaptureQueueState.QUEUED, CaptureQueueState.CAPTURED}
        ]

    def snapshot(self) -> dict[str, Any] | None:
        session = self.active_session or (self._history[-1] if self._history else None)
        return session.to_dict() if session else None

    def update_guidance(self, *, probe_scores: dict[str, float] | None = None) -> None:
        session = self.active_session
        if session is None:
            return
        session.guidance = self._guidance.compute(session, probe_scores=probe_scores)
        session.search_status = compute_search_status(session)

    def _refresh_session_state(self, session: MarketCaptureSession) -> None:
        best_id: str | None = None
        best_delta = float("-inf")
        best_value_id: str | None = None
        best_ppc = float("-inf")
        for row in session.observations:
            if row.queue_state is not CaptureQueueState.EVALUATED or not row.evaluation:
                continue
            delta = float(row.evaluation.get("build_value_delta") or 0.0)
            if delta > best_delta:
                best_delta = delta
                best_id = row.observation_id
            ppc = row.evaluation.get("power_per_currency") or {}
            power = float(ppc.get("power_per_currency") or 0.0)
            if power > best_ppc:
                best_ppc = power
                best_value_id = row.observation_id
        session.best_observation_id = best_id
        session.best_value_observation_id = best_value_id
        session.guidance = self._guidance.compute(session)
        session.search_status = compute_search_status(session)

    def _find_observation(self, observation_id: str) -> MarketCaptureObservation | None:
        session = self.active_session
        if session is None:
            return None
        for row in session.observations:
            if row.observation_id == observation_id:
                return row
        return None

    def _archive_session(self, session: MarketCaptureSession) -> None:
        self._history.append(session)
        if len(self._history) > MAX_SESSION_HISTORY:
            self._history = self._history[-MAX_SESSION_HISTORY:]
