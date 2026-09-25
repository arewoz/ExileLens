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

### Backup and recovery (production private key)

The production private key lives only under
`%USERPROFILE%\.exilelens\signing\exilelens-prod-1\` (outside the repo). The PEM
file is ACL-restricted to the current Windows user (read-only for that account).

**Do not** store an unencrypted copy in cloud sync folders, email, chat, or the
repository. If the private key is lost, you cannot sign updates for existing
installs until a new key pair is generated and shipped in an app release that
embeds the new public key (see key rotation below).

**Recommended backup**

1. Copy `exilelens-prod-1-private.pem` and `exilelens-prod-1-public.b64` to an
   offline encrypted medium (password manager secure note, hardware-backed vault,
   or encrypted removable drive).
2. Store the GitHub Actions payload separately: the single-line contents of
   `exilelens-prod-1-github-secret.b64.txt` as secret
   `EXILELENS_UPDATE_SIGNING_KEY_B64` on the `production-release` environment
   (re-upload from the backup file if GitHub secrets are reset).
3. After rotation, retain the **previous** private key in the vault until no
   supported release trusts the old public key.

**Recovery**

- **GitHub secret missing:** Re-set `EXILELENS_UPDATE_SIGNING_KEY_B64` from the
  saved `exilelens-prod-1-github-secret.b64.txt` (never commit or log the value).
- **Local PEM missing:** Restore from encrypted backup; verify with
  `sign_update_manifest.py` + `verify_signed_update_manifest.py` using the
  restored PEM and the embedded public key in `trust.py`.
- **Compromise:** Generate `exilelens-prod-2`, embed both public keys in a
  release, migrate CI secret, then retire `exilelens-prod-1`.

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
