# ExileLens update signing and release publishing

ExileLens in-app updates require a **signed update manifest** for every published
Windows ZIP. SHA-256 alone is never sufficient: if signature verification fails,
installation is blocked.

## Keys

| Key ID | Purpose | Trusted by |
|--------|---------|------------|
| `exilelens-prod-1` | Production releases | **Every build** (`PRODUCTION_VERIFY_KEYS`) |
| `exilelens-test-1` | Tests and pipeline self-checks | **Source runs only, on explicit opt-in** (`TEST_VERIFY_KEYS`) |

The test key's private half is a **public test fixture**
(`fixtures/update_signing/test_signing_key.pem`). It therefore must never be
accepted by an installed copy, and since R2-P0 it is not.

The production private key must **never** be committed. Keep it in the GitHub
Actions secret and an offline vault.

### Trust profiles (R2-P0)

`src/exilelens/app/updates/trust.py` exposes two trust profiles:

- **production**: `exilelens-prod-1` only. This is the only profile a frozen
  (packaged) build can use. Environment variables and test helpers are ignored
  when `sys.frozen` is set, so a shipped binary has no test-key fallback.
- **test**: production plus `exilelens-test-1`. It is available only to source
  runs, through `use_test_trust_profile()` in tests or
  `EXILELENS_UPDATE_TRUST_PROFILE=test` for pipeline self-checks.

Evidence that this holds:

- The source release gate (`update_trust_set`) blocks if the frozen trust set is
  anything other than `["exilelens-prod-1"]`, or if test key material appears in
  the production set.
- The packaged-artifact gate (`packaged_update_trust`, run by
  `release-gate --require-artifact`) runs the built binary as
  `ExileLens.exe --exilelens-update-trust-report <file>`. It asserts that the
  binary *itself* reports `frozen: true` and trusts only `exilelens-prod-1`. The
  report holds key ids only, never key material.
- `release.yml` re-verifies the freshly signed manifest with
  `verify_signed_update_manifest.py --trust-profile production --expect-tag <tag>`.
- `update-signing-validation.yml`: when it falls back to the test key, it labels
  the run as a pipeline self-check only. It also asserts that the production
  profile *rejects* the test-signed manifest.

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
    "channel": "stable",
    "version": "0.6.0",
    "tag": "v0.6.0",
    "signing_key_id": "exilelens-prod-1",
    "artifact": {
      "filename": "ExileLens-v0.6.0-win64.zip",
      "size": 69927974,
      "sha256": "<hex>",
      "url": "https://github.com/arewoz/ExileLens/releases/download/v0.6.0/ExileLens-v0.6.0-win64.zip"
    }
  },
  "signature": "<base64 ed25519 over canonical manifest JSON>"
}
```

Canonical signing payload: JSON with sorted keys, no insignificant whitespace
(see `canonical_manifest_bytes()`). New optional fields may be added under
`schema: 1` because older clients ignore unknown signed fields. Never bump
`schema` for an additive change: older clients reject any other schema value.

### Manifest ↔ release binding (R2-P0)

The GitHub release listing (tag name, asset list) is **not signed**. After the
signature verifies, `bind_manifest_to_release()` requires all of the following:

- `manifest.tag == release.tag`, and `manifest.tag == "v" + manifest.version`;
- `manifest.version == release version`, and strictly **newer than the installed
  version** (no downgrade, no same-version reinstall);
- `artifact.filename == "ExileLens-<tag>-win64.zip"`, and it equals the release's
  zip asset name;
- `artifact.url == "https://github.com/arewoz/ExileLens/releases/download/<tag>/<filename>"`.

Any mismatch is a verification failure. For example, a valid old manifest
attached to a newer-looking release is rejected as `tag_mismatch`.

### Optional manifest field `seamless_eligible` (R2)

`artifact`-level trust is unchanged. The signed manifest may carry `"seamless_eligible": false` to keep one
release on the manual path even for supporters (for example after a risky layout change). Absent means
eligible (older manifests); any non-boolean value is treated as `false`. It describes the *release*, never a
person: Patreon entitlement is never encoded in a manifest. `release.yml` exposes it as the `seamless_eligible`
dispatch input (default true). Security fixes must not be made manual-only for free users: this flag only
removes *automation*, the manual updater always works.

### Download and archive bounds

- **Downloads** never write past the signed `size`; an oversized stream is
  discarded.
- **Resume** requires `206 Partial Content` with a matching `Content-Range`.
  A `200` restarts from byte 0; a `416` (or any other mismatch) discards the
  `.part` file and restarts once.
- **Integrity:** a `.part` file is only promoted after its full SHA-256 matches.
- **Stalls:** a chunk that takes longer than 120 s fails with `stall_timeout`.
- **Archive limits:**
  - at most 10,000 entries;
  - at most 1 GiB uncompressed in total;
  - at most 256 MiB per entry;
  - at most 100:1 compression ratio for entries over 1 MiB;
  - every entry under `ExileLens/`;
  - no `..`, `:`, raw backslashes, duplicate names (case-insensitive), symlinks
    or devices.

  For reference, v0.6.0 has 204 entries, ~146 MB uncompressed, a largest entry
  of ~20 MB and a worst ratio of ~4.5:1.

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

Local signing (test key) produces manifests that only a **source run in the test
profile** accepts; no packaged build accepts them.

## Updater lifecycle (R2-P0)

### Self-refresh

The external updater runs from `%LOCALAPPDATA%\ExileLens\ExileLensUpdater.exe`,
so it is never inside the directory it replaces. On every packaged start (and
before each check), the app compares the **SHA-256** of that copy with the
bundled `_internal\ExileLensUpdater.exe`. Timestamps are never used.

- **They differ:** the bundled copy is written to a temporary file, verified,
  and swapped in with `os.replace`.
- **An updater holds the updater mutex:** the refresh is deferred.
- **The refresh fails:** the existing copy is kept.

`updater_matches_bundled()` is the job-contract handshake. The app writes
`restart_after_update: false` only when the app-data updater is byte-identical
to the bundled v2 updater, because a legacy updater would ignore the flag and
always relaunch.

First upgrade from a pre-M4.2 build still requires a manual ZIP install.

### Job contract v2 (`updates\jobs\pending.json`)

```json
{
  "schema": 2,
  "job_id": "<32 hex>",
  "from_version": "0.6.0",
  "to_version": "0.7.0",
  "restart_after_update": true,
  "install_root": "<install dir>",
  "staged_root": "<updates>\\staging\\ExileLens",
  "backup_root": "<updates>\\backup",
  "exe_path": "<install dir>\\ExileLens.exe",
  "zip_path": "<updates>\\downloads\\ExileLens-v0.7.0-win64.zip",
  "zip_sha256": "<signed sha256>",
  "zip_size": 123,
  "pid": 1234,
  "version": "0.7.0"
}
```

**Validation:** the updater rejects unknown or missing fields. It also
re-derives every path from the fixed layout of the job file's own `updates`
directory and compares them:

- `install_root` must contain `ExileLens.exe` and `_internal`;
- `exe_path` must equal `install_root\ExileLens.exe`;
- staging, backup and zip must sit at their fixed locations.

**Compatibility:**

- `pid` and `version` are kept so that a not-yet-refreshed schema-1 updater can
  still run a restart job.
- Schema-1 jobs (written by ExileLens ≤ 0.6.0, e.g. after a manual downgrade)
  are still accepted. They always restart and carry no package provenance.
- In P0, only "Restart & Update" (`restart_after_update: true`) is wired.
  `false` is updater infrastructure for a future install-on-exit and has no
  production caller.

### Install transaction

Windows cannot atomically replace a directory tree, so the updater swaps
top-level entries and journals the operation.

1. **Mutex:** take `Local\ExileLens.Updater`. A second updater exits with
   `already_running`.
2. **Wait for processes:** wait (at most 120 s, never killing anything) until
   the parent process **and every process whose image lives under the install
   root** have exited. This includes the PoB worker, which is `ExileLens.exe`
   too. On timeout: `process_timeout`, with the install untouched.
3. **Recover first:** roll back any incomplete journal from an earlier run.
4. **Prepare** (the install is untouched):
   - re-hash the package against `zip_sha256`/`zip_size`;
   - copy staging to `<install>\.update-new`;
   - verify that tree against the package's central directory: exact file set,
     sizes and CRC-32;
   - back up the entries that will be replaced.
5. **Journal** `updates\jobs\journal.json`: install root plus, per entry,
   whether an old version existed. It is written with fsync and an atomic
   replace.
6. **Swap:** per entry, `X → .update-old\X`, then `.update-new\X → X`, with
   `ExileLens.exe` last. Sharing violations (antivirus or indexer locks) are
   retried with backoff for up to 30 s per rename.
7. **Commit:** delete the journal. `.update-old` remains as recovery material.
8. **Failure:** roll back by inspecting the filesystem per entry. Rollback is
   idempotent and does not trust progress counters. If rollback fails, copy the
   backup back. If both fail, report `restore_failed` and keep the journal as
   evidence.

**Interrupted updater** (killed or power loss): the next updater run, or
`ExileLensUpdater.exe --recover [--restart]`, rolls the journal back. The app
starts recovery automatically at launch. The journal is never deleted before the
rollback succeeds, and its entries must be single path components inside the
recorded install root.

**Residual window:** the milliseconds between the two renames of one entry. It is
covered by recovery as long as the updater can run.

**Manual recovery:** if ExileLens cannot start after an interrupted update, run
`%LOCALAPPDATA%\ExileLens\ExileLensUpdater.exe --recover --restart`, or extract
the latest release ZIP over the install folder.

### Restart semantics

| Outcome | `restart_after_update: true` | `false` |
|---|---|---|
| success | relaunch the new version | no relaunch |
| restored / recovered / prepare_failed | relaunch the previous version | no relaunch |
| process_timeout / invalid_job / restore_failed | no relaunch | no relaunch |

**Launches during an install:** if the user starts ExileLens while an updater
holds the mutex, the app records `updates\jobs\launch_requested` and exits. The
updater then relaunches when it finishes, even for `false`.

### Result file (`updates\jobs\last_result.json`)

```json
{"schema": 1, "job_id": "<hex|empty>", "from_version": "0.6.0", "to_version": "0.7.0",
 "mode": "restart|no_restart|recover", "outcome": "<enum>", "exit_code": 0, "finished_at": 1790000000}
```

| outcome | exit code | meaning |
|---|---|---|
| `success` | 0 | new version installed |
| `invalid_job` | 10 | job rejected; install untouched |
| `already_running` | 11 | another updater active (no result written) |
| `process_timeout` | 12 | ExileLens processes did not exit; install untouched |
| `prepare_failed` | 13 | package, provenance, copy or backup failed; install untouched |
| `restored` | 14 | swap failed; previous version restored |
| `restore_failed` | 15 | previous version could not be fully restored (`EL-UPD-005`) |
| `recovered` | 16 | an interrupted install was rolled back |
| `relaunch_failed` | 17 | installed, but the relaunch failed |

The result never contains messages, paths or tracebacks; the parser rejects any
other shape.

**Next launch:** the result is consumed once and moved to
`last_result.seen.json`, which Diagnostics reads. The app shows a non-modal tray
notice and a line in Settings → Updates:

- "Updated to X";
- "Update to X failed. The previous version was restored." (`EL-UPD-004`);
- for `restore_failed`, recovery guidance plus "Open GitHub Releases"
  (`EL-UPD-005`).

### Persisted ready state (`updates\ready.json`)

After a verified download, the app stores the **signed envelope** together with
the package name, size and SHA-256. On the next launch the record is not trusted
just because the app wrote it. A worker thread re-verifies:

- the signature (production profile);
- the version binding (strictly newer than installed);
- the package size and full SHA-256.

Only then does it show the update as ready again, without downloading it again.
Anything invalid, superseded or already installed is discarded together with its
package.

### Supporter automation (R2 Package C) on top of the same pipeline

There is exactly one update pipeline: GitHub release → signed manifest (production key) → release binding →
`DownloadManager` (size + SHA-256) → archive limits → persisted `ready.json` → updater v2. Entitlement is an
optional **gate** (`UpdateService.set_automation_gate`, a `Callable[[], bool]` that must return exactly `True`),
so no URL, hash, version or manifest can come from it, and nothing under `app/updates/` or `updater/` imports
the cloud or entitlement modules (enforced by a test).

With the gate open, `seamless_eligible` true and the matching toggles on:

* **Check cadence:** every 6 hours instead of 24 (GitHub's unauthenticated limit is far above this).
* **Automatic download** (`updates_auto_download`, default on): starts after a verified check when the disk has at
  least 3× the package size free; at most one automatic attempt per version per session; a verified package is
  announced once by a tray message that says when it will install.
* **Pre-staging:** the verified package is extracted in the background so the exit step is short and bounded.
* **Install on exit** (`updates_install_on_exit`, default on): at a *clean, user-initiated* exit (tray Exit, or
  closing the only window) the app hands the prepared package to the updater with `restart_after_update: false`.
  Nothing is downloaded or extracted at that point; if anything is not already verified and prepared the update
  just stays pending. It is skipped for crashes, IPC/takeover quits, update restarts, an invalid ready state, an
  out-of-date updater, a missing or expired lease, and whenever Windows is ending the session
  (`commitDataRequest` through a hidden sentinel window, plus `GetSystemMetrics(SM_SHUTTINGDOWN)`).
* The next normal launch runs the new version and shows "Updated to X"; nothing ever relaunches unasked.

If the app is killed while the updater runs (for example a forced shutdown), the P0 journal recovers the install
on the next start. Free users keep *Download & Install* / *Restart & Update* unchanged.

### Cleanup

Post-launch cleanup runs once, 30 s after a packaged start, and is skipped while
a journal exists or an updater runs.

- **Removed after a healthy launch:** `.update-old`, `.update-new`, the backup,
  staging, `pending.json`, packages for versions ≤ installed, and `.part` files
  older than 14 days.
- **Kept:** the ready package.
- **Kept after `restore_failed`:** `.update-old` and the backup.

## Pre-flight without publishing (`dry_run`)

`release.yml` has a `dry_run` input (default **false**). With it on, the workflow runs every gate, the packaged build, the packaged-artifact
gate, production signing in the protected `production-release` environment, verification of the signed manifest under the *production* trust
profile with tag/version/URL binding, and the release-notes check, then stops: no tag, no GitHub Release, no assets, no Discord post and no
uploaded artifacts (the log shows the SHA-256 and the signed manifest). Dispatch it from `main` on the exact commit and tag you intend to release;
if it is green, the real release is the same dispatch with `dry_run` off. It cannot replace the first real N -> N+1 field update, which
additionally exercises GitHub release discovery and asset download.
