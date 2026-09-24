# Update signing fixtures

`test_signing_key.pem` is a **test-only** Ed25519 private key used by unit tests and
local release dry-runs. It must never sign production releases.

The matching public key is embedded in `src/exilelens/app/updates/trust.py` as
`exilelens-test-1`.
