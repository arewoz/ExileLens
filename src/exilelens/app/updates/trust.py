from __future__ import annotations

import base64
from typing import Mapping

TEST_SIGNING_KEY_ID = "exilelens-test-1"
PROD_SIGNING_KEY_ID = "exilelens-prod-1"

# Test key only — used for CI, local E2E, and pre-production builds.
# Production public key is added here during release provisioning (never the private key).
EMBEDDED_VERIFY_KEYS: Mapping[str, bytes] = {
    TEST_SIGNING_KEY_ID: base64.b64decode("V6Pm+fZKJPgxpmxtwQJkGl+FWTj3BZmspsX8HwYPl0o="),
}


def verify_key_for(signing_key_id: str) -> bytes | None:
    return EMBEDDED_VERIFY_KEYS.get(str(signing_key_id or "").strip())


def production_signing_configured() -> bool:
    return PROD_SIGNING_KEY_ID in EMBEDDED_VERIFY_KEYS


def install_allowed_for_key(signing_key_id: str) -> bool:
    key_id = str(signing_key_id or "").strip()
    if key_id == PROD_SIGNING_KEY_ID:
        return production_signing_configured()
    return verify_key_for(key_id) is not None
