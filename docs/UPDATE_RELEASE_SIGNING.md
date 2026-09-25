# ExileLens update signing and release publishing

ExileLens in-app updates require a **signed update manifest** for every published
Windows ZIP. SHA-256 alone is never sufficient: if signature verification fails,
installation is blocked.

## Keys

| Key ID | Purpose | Stored in repo |
|--------|---------|----------------|
| `exilelens-test-1` | CI, local E2E, pre-production | **Public key only** (embedded in app) |
| `exilelens-prod-1` | Production releases | **Public key only** after provisioning |

Private keys must **never** be committed. Keep production private keys in GitHub
Actions secrets or an offline HSM/vault.

### Provision a production key pair

1. Generate Ed25519 keys on a trusted machine (not in the repo).
2. Add the **raw 32-byte public key** (base64) to
   `src/exilelens/app/updates/trust.py` under `exilelens-prod-1`.
3. Store the **base64-encoded PEM bytes** (not the PEM text itself) as GitHub
   Actions secret `EXILELENS_UPDATE_SIGNING_KEY_B64` on the `production-release`
   environment. CI decodes it to a temp file via
   `scripts/materialize_update_signing_key.ps1` and sets
   `EXILELENS_UPDATE_SIGNING_KEY_PATH` for `scripts/sign_update_manifest.py`.

   Generate keys and the exact secret payload locally:

   ```powershell
   powershell -File scripts\create_prod_update_key.ps1
   ```

   Install the public key into the app (public material only):

   ```powershell
   powershell -File scripts\install_prod_update_public_key.ps1 `
     -PublicKeyPath "$env:USERPROFILE\.exilelens\signing\exilelens-prod-1\exilelens-prod-1-public.b64"
   ```

   Validate signing in CI without publishing a release: run workflow
   **Validate update signing (no publish)** (`update-signing-validation.yml`).

Until step 2 is complete, manifests signed with `exilelens-prod-1` are rejected
at install time (`production_signing_unavailable`).

### Rotate keys

1. Generate a new key ID (for example `exilelens-prod-2`).
2. Ship an app release embedding **both** old and new public keys.
3. After adoption, publish only with the new private key and remove the old public
   key in the following release.

## Manifest format

Release asset: `ExileLens-<tag>-win64.update.json`

```json
{
  "manifest": {
    "schema": 1,
    "channel": "beta",
    "version": "0.4.0b2",
    "tag": "v0.4.0b2",
    "signing_key_id": "exilelens-test-1",
    "artifact": {
      "filename": "ExileLens-v0.4.0b2-win64.zip",
      "size": 12345678,
      "sha256": "<hex>",
      "url": "https://github.com/.../download/.../ExileLens-v0.4.0b2-win64.zip"
    }
  },
  "signature": "<base64 ed25519 over canonical manifest JSON>"
}
```

Canonical signing payload: JSON with sorted keys, no insignificant whitespace
(see `canonical_manifest_bytes()`).

## Publishing a release

1. Run the draft release workflow from `main` with the new tag.
2. The workflow builds the onedir ZIP, SHA256SUMS, signed `.update.json`, and
   `ExileLensUpdater.exe` (copied into `_internal` for bootstrap).
3. Upload all assets to the GitHub Release.

Local signing (test key):

```powershell
$env:PYTHONPATH = "src"
python scripts/sign_update_manifest.py `
  --manifest path\to\unsigned-manifest.json `
  --private-key fixtures\update_signing\test_signing_key.pem `
  --output path\to\ExileLens-v0.4.0b2-win64.update.json
```

## Bootstrap for existing installs

Older builds lack `ExileLensUpdater.exe` in app data. On startup, packaged builds
copy `_internal/ExileLensUpdater.exe` into
`%LOCALAPPDATA%/ExileLens/ExileLensUpdater.exe` once. The external updater runs
from app data so it is not replaced during an in-place upgrade.

First upgrade from a pre-M4.2 build still requires a manual ZIP install (or any
release that already contains the updater bootstrap).
