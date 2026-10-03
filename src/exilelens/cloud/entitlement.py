"""Signed entitlement leases: the ONLY thing the cloud can say about updates is "may automate".

A lease is a small Ed25519-signed statement ``{schema, kid, lease_id, sub, capabilities, issued_at,
refresh_after, expires_at, policy_version}`` issued by the ExileLens service for one linked device.

Security properties (all covered by tests):

* **Separate keys.** Leases are verified only against ``ENTITLEMENT_VERIFY_KEYS``; update manifests only
  against the update trust set. The two key-id sets and key bytes are disjoint, and the signed message of a
  lease starts with a domain-separation prefix that is not valid manifest JSON, so a signature made for one
  purpose can never validate for the other.
* **Closed output.** The only product of a valid lease is a ``frozenset`` of capability names this app
  knows (``KNOWN_CAPABILITIES``). Unknown capabilities and unknown fields are ignored (unknown fields are
  rejected at parse time). A lease cannot carry a URL, version, file name or hash — there is nowhere for
  them to go.
* **Fail closed.** Anything wrong (signature, key, device, shape, expiry) yields an empty capability set;
  the app then behaves exactly like a free install and the manual updater is unaffected.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from exilelens.app.updates import trust

LEASE_SCHEMA = 1
LEASE_DOMAIN_PREFIX = b"exilelens/entitlement-lease/v1\n"
CLOCK_SKEW_SECONDS = 10 * 60
MAX_LEASE_BYTES = 4096

CAP_SEAMLESS_UPDATES = "seamless_updates"
KNOWN_CAPABILITIES = frozenset({CAP_SEAMLESS_UPDATES})

ENTITLEMENT_PROD_KEY_ID = "exilelens-entitlement-1"
ENTITLEMENT_TEST_KEY_ID = "exilelens-entitlement-test-1"

# Public keys only. The production entry is provisioned by the owner (scripts/create_entitlement_key.py ->
# paste the printed public key here); until then production builds verify nothing, so supporter
# automation stays dark and every install behaves as a free install.
PRODUCTION_ENTITLEMENT_KEYS: Mapping[str, bytes] = MappingProxyType({})
# Test key: used by the golden vector and tests in source runs only (never trusted by a frozen build).
TEST_ENTITLEMENT_KEYS: Mapping[str, bytes] = MappingProxyType(
    {ENTITLEMENT_TEST_KEY_ID: base64.b64decode("7uT5nCI2848DtVlDbBEUsIM30CjxIt9H1e0eD9hBjr0=")}
)

_LEASE_KEYS = frozenset(
    {"schema", "kid", "lease_id", "sub", "capabilities", "issued_at", "refresh_after", "expires_at", "policy_version"}
)
_HEX32 = re.compile(r"[0-9a-f]{32}")
_CAP_NAME = re.compile(r"[a-z][a-z_]{0,31}")
_KID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def entitlement_verify_keys(*, frozen: bool | None = None) -> Mapping[str, bytes]:
    keys = dict(PRODUCTION_ENTITLEMENT_KEYS)
    if trust.active_trust_profile(frozen=frozen) == trust.TEST_PROFILE:
        keys.update(TEST_ENTITLEMENT_KEYS)
    return MappingProxyType(keys)


class LeaseStatus(str, Enum):
    VALID = "valid"
    MALFORMED = "malformed"
    UNKNOWN_KEY = "unknown_key"
    BAD_SIGNATURE = "bad_signature"
    WRONG_DEVICE = "wrong_device"
    NOT_YET_VALID = "not_yet_valid"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Lease:
    kid: str
    lease_id: str
    device_id: str
    capabilities: frozenset[str]
    issued_at: int
    refresh_after: int
    expires_at: int
    policy_version: int


@dataclass(frozen=True)
class LeaseResult:
    status: LeaseStatus
    lease: Lease | None = None

    @property
    def valid(self) -> bool:
        return self.status is LeaseStatus.VALID and self.lease is not None

    @property
    def capabilities(self) -> frozenset[str]:
        """Known capabilities of a VALID lease; empty otherwise."""
        return self.lease.capabilities & KNOWN_CAPABILITIES if self.valid and self.lease else frozenset()


def canonical_lease_bytes(lease: Mapping[str, Any]) -> bytes:
    return json.dumps(lease, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def signing_message(lease: Mapping[str, Any]) -> bytes:
    return LEASE_DOMAIN_PREFIX + canonical_lease_bytes(lease)


def _is_int(value: Any) -> bool:
    return type(value) is int and 0 <= value < 2**40


def _parse(raw: Mapping[str, Any]) -> Lease | None:
    if set(raw) != _LEASE_KEYS or raw["schema"] != LEASE_SCHEMA or type(raw["schema"]) is not int:
        return None
    kid, lease_id, sub = raw["kid"], raw["lease_id"], raw["sub"]
    caps = raw["capabilities"]
    if not (isinstance(kid, str) and _KID.fullmatch(kid) and isinstance(lease_id, str) and _HEX32.fullmatch(lease_id)):
        return None
    if not (isinstance(sub, str) and _HEX32.fullmatch(sub)):
        return None
    if not (isinstance(caps, list) and len(caps) <= 8 and all(isinstance(c, str) and _CAP_NAME.fullmatch(c) for c in caps)):
        return None
    if not all(_is_int(raw[k]) for k in ("issued_at", "refresh_after", "expires_at", "policy_version")):
        return None
    if not raw["issued_at"] <= raw["refresh_after"] <= raw["expires_at"]:
        return None
    return Lease(kid, lease_id, sub, frozenset(caps), raw["issued_at"], raw["refresh_after"], raw["expires_at"], raw["policy_version"])


def verify_lease(envelope: object, *, device_id: str, now: float, keys: Mapping[str, bytes] | None = None) -> LeaseResult:
    """Verify a ``{"lease": {...}, "signature": "<b64>"}`` envelope for this device at time ``now``."""
    if not isinstance(envelope, dict) or set(envelope) != {"lease", "signature"}:
        return LeaseResult(LeaseStatus.MALFORMED)
    raw, signature_b64 = envelope["lease"], envelope["signature"]
    if not isinstance(raw, dict) or not isinstance(signature_b64, str):
        return LeaseResult(LeaseStatus.MALFORMED)
    try:
        if len(json.dumps(envelope)) > MAX_LEASE_BYTES:
            return LeaseResult(LeaseStatus.MALFORMED)
    except (TypeError, ValueError):
        return LeaseResult(LeaseStatus.MALFORMED)
    lease = _parse(raw)
    if lease is None:
        return LeaseResult(LeaseStatus.MALFORMED)
    verify_keys = entitlement_verify_keys() if keys is None else keys
    public_key = verify_keys.get(lease.kid)
    if public_key is None:
        return LeaseResult(LeaseStatus.UNKNOWN_KEY)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        signature = base64.b64decode(signature_b64, validate=True)
        if len(signature) != 64:
            return LeaseResult(LeaseStatus.BAD_SIGNATURE)
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, signing_message(raw))
    except (ValueError, InvalidSignature):
        return LeaseResult(LeaseStatus.BAD_SIGNATURE)
    if lease.device_id != device_id:
        return LeaseResult(LeaseStatus.WRONG_DEVICE)
    if lease.issued_at > now + CLOCK_SKEW_SECONDS:
        return LeaseResult(LeaseStatus.NOT_YET_VALID)
    if now >= lease.expires_at:
        return LeaseResult(LeaseStatus.EXPIRED, lease)
    return LeaseResult(LeaseStatus.VALID, lease)


def key_sets_are_disjoint() -> bool:
    """True when no entitlement key id or key bytes appear in the update trust set (and vice versa)."""
    entitlement_ids = set(PRODUCTION_ENTITLEMENT_KEYS) | set(TEST_ENTITLEMENT_KEYS)
    update_ids = set(trust.PRODUCTION_VERIFY_KEYS) | set(trust.TEST_VERIFY_KEYS)
    entitlement_bytes = set(PRODUCTION_ENTITLEMENT_KEYS.values()) | set(TEST_ENTITLEMENT_KEYS.values())
    update_bytes = set(trust.PRODUCTION_VERIFY_KEYS.values()) | set(trust.TEST_VERIFY_KEYS.values())
    return not (entitlement_ids & update_ids) and not (entitlement_bytes & update_bytes)
