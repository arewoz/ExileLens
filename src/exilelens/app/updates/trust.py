"""Update-signing trust profiles.

Shipping (frozen) builds trust ONLY the production update key. The test key's private half is a
public test fixture (``fixtures/update_signing/test_signing_key.pem``), so it may never be accepted by
an installed copy. Source runs can opt into the test profile explicitly for tests and pipeline checks.
"""

from __future__ import annotations

import base64
import os
import sys
from contextlib import contextmanager
from types import MappingProxyType
from typing import Iterator, Mapping

TEST_SIGNING_KEY_ID = "exilelens-test-1"
PROD_SIGNING_KEY_ID = "exilelens-prod-1"

PRODUCTION_PROFILE = "production"
TEST_PROFILE = "test"
TRUST_PROFILE_ENV = "EXILELENS_UPDATE_TRUST_PROFILE"

# Public keys only. Production private key lives exclusively in the release environment secret.
PRODUCTION_VERIFY_KEYS: Mapping[str, bytes] = MappingProxyType(
    {
        PROD_SIGNING_KEY_ID: base64.b64decode("H4siEurq2DU5UxQU/uoQWOeN82T3aKDQUUGUalwgwxU="),
    }
)
# Test key — CI, local tests and disposable source-run checks only. Never trusted by frozen builds.
TEST_VERIFY_KEYS: Mapping[str, bytes] = MappingProxyType(
    {
        TEST_SIGNING_KEY_ID: base64.b64decode("V6Pm+fZKJPgxpmxtwQJkGl+FWTj3BZmspsX8HwYPl0o="),
    }
)

_test_profile_override: bool | None = None


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def active_trust_profile(*, frozen: bool | None = None) -> str:
    """Return ``production`` unless a source run explicitly selected the test profile."""
    if _frozen() if frozen is None else frozen:
        return PRODUCTION_PROFILE
    if _test_profile_override is not None:
        return TEST_PROFILE if _test_profile_override else PRODUCTION_PROFILE
    if os.environ.get(TRUST_PROFILE_ENV, "").strip().lower() == TEST_PROFILE:
        return TEST_PROFILE
    return PRODUCTION_PROFILE


def trusted_update_keys(*, frozen: bool | None = None) -> Mapping[str, bytes]:
    keys = dict(PRODUCTION_VERIFY_KEYS)
    if active_trust_profile(frozen=frozen) == TEST_PROFILE:
        keys.update(TEST_VERIFY_KEYS)
    return MappingProxyType(keys)


@contextmanager
def use_test_trust_profile(enabled: bool = True) -> Iterator[None]:
    """Source-run/test helper: temporarily trust (or explicitly distrust) the test key."""
    global _test_profile_override
    previous = _test_profile_override
    _test_profile_override = enabled
    try:
        yield
    finally:
        _test_profile_override = previous


def verify_key_for(signing_key_id: str) -> bytes | None:
    return trusted_update_keys().get(str(signing_key_id or "").strip())


def production_signing_configured() -> bool:
    return PROD_SIGNING_KEY_ID in PRODUCTION_VERIFY_KEYS


def install_allowed_for_key(signing_key_id: str) -> bool:
    return verify_key_for(signing_key_id) is not None


def trust_report(*, frozen: bool | None = None) -> dict[str, object]:
    """Bounded, secret-free description of the active trust set (release-gate evidence)."""
    is_frozen = _frozen() if frozen is None else frozen
    return {
        "schema": 1,
        "frozen": is_frozen,
        "profile": active_trust_profile(frozen=is_frozen),
        "key_ids": sorted(trusted_update_keys(frozen=is_frozen)),
    }
