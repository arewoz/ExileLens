from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

#: One cached payload is large (a ring result is ~830 KB, a helmet ~550 KB), so an
#: unbounded store grew by roughly a megabyte per distinct item checked in a session.
#: 64 entries is far more than a player re-hovers within one baseline, and every entry
#: is dropped anyway when the baseline generation, loadout, item set, source or
#: context changes.
DEFAULT_RESULT_CACHE_ENTRIES = 64


def evaluation_cache_key(
    *,
    content_hash: str,
    fingerprint: str,
    build_path: str = "",
    source_identity: str = "",
    loadout: str,
    item_set: str,
    context: str,
    generation: int,
    context_identity: str = "",
    candidate_fingerprint: str = "",
) -> str:
    if context_identity:
        # v3: bumped because a restore/damage-selection semantics fix (a comparison's
        # verdict, not its identity components) could otherwise still be served from a
        # v2-keyed entry computed under the old, buggy semantics for the same build
        # state. Bump this prefix again for any future fix to how a cached payload's
        # *content* is computed, even when nothing that feeds the identity itself changed.
        return f"v3|{candidate_fingerprint or content_hash}|{context_identity}"
    return "|".join(
        [
            str(content_hash or ""),
            str(fingerprint or ""),
            str(source_identity or build_path or ""),
            str(loadout or ""),
            str(item_set or ""),
            str(context or ""),
            str(int(generation)),
        ]
    )


@dataclass
class EvaluationResultCache:
    """Reuse raw PoB comparison payloads. Never used to suppress a new clipboard event.

    Bounded LRU: the least recently used entry is evicted once ``limit`` is reached.
    Reading an entry marks it as recently used, so an item the player keeps re-checking
    stays cached while one-off hovers age out.

    Both copies are load-bearing and are deliberately kept:

    * ``put`` snapshots because the caller keeps mutating the very same payload after
      storing it -- optional presentation enrichment, upgrade-path priming and the
      overlay's ``request_meta`` writes all land on that object afterwards. Without the
      copy the cache would silently accumulate one request's enrichment.
    * ``get`` copies because the caller rescores the returned payload and overwrites its
      ``request_meta`` in place. Handing out the stored object would let one cache hit
      corrupt every later one.

    Removing either would mean making the whole delivery path treat the payload as
    immutable, which is a larger change than this cache. Measured cost is ~1.9 ms per
    copy on a ring-sized payload.
    """

    limit: int = DEFAULT_RESULT_CACHE_ENTRIES
    _store: "OrderedDict[str, dict[str, Any]]" = field(default_factory=OrderedDict)

    def get(self, key: str) -> dict[str, Any] | None:
        payload = self._store.get(key)
        if payload is None:
            return None
        self._store.move_to_end(key)
        return deepcopy(payload)

    def put(self, key: str, result: dict[str, Any]) -> None:
        if not key:
            return
        self._store[key] = deepcopy(result)
        self._store.move_to_end(key)
        self._evict()

    def invalidate(self) -> None:
        self._store.clear()

    def _evict(self) -> None:
        limit = max(1, int(self.limit))
        while len(self._store) > limit:
            self._store.popitem(last=False)
