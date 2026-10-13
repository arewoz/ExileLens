# Preparing and publishing ExileLens 1.0.0

1.0.0 is the next public release after 0.6.0. The 0.7.0b1 candidate was never published. The application version, both Windows executable version resources, compatibility manifest, packaged README, changelog, GitHub release notes and in-app What's New now identify 1.0.0. The in-app notes cover updates from both 0.6.0 and the internal 0.7.0b1 candidate.

The active release body is `packaging/RELEASE_NOTES.md`; the bundled update notes are `src/exilelens/whats_new/whats_new.json`. The three `*_DRAFT` files in this directory are historical preparation material. The notes use 2026-10-13 as the preparation date; update `released` in the bundled JSON if publication is postponed.

## Manual GitHub Action

After merging the preparation PR into `main`, open [Actions -> Windows release](https://github.com/arewoz/ExileLens/actions/workflows/release.yml) and select **Run workflow**:

| Input | Preflight | Publish |
|---|---|---|
| Branch | `main` | `main`, at the same tested commit |
| `version` | `v1.0.0` (default) | `v1.0.0` |
| `dry_run` | `true` | `false` |
| `seamless_eligible` | `true` | `true` |

The preflight runs the source and packaged gates, mandatory regressions, official build, production signing and manifest verification. It creates no tag, release, uploaded artifact or announcement. Check the run's logs for the checksum and verified manifest. If `main` changes before publication, repeat the preflight on the new commit.

The publishing run creates the tag and published GitHub Release on the exact workflow commit. It uploads:

- `ExileLens-v1.0.0-win64.zip`
- `SHA256SUMS.txt`
- `ExileLens-v1.0.0-win64.update.json` (stable channel, production signature)

The title is **ExileLens v1.0.0**, without a Beta suffix. The workflow rejects an existing tag/release or a tag that differs from the source version. Publication and signing runs are serialized.

## Configuration and remaining release evidence

The workflow requires `EXILELENS_UPDATE_SIGNING_KEY_B64` in the `production-release` environment. The repository variable `EXILELENS_CLOUD_API_URL` controls the cloud configuration embedded by the build; it is currently configured as `https://api.exilelens.app`. A read-only settings check on 2026-10-13 confirmed that the signing secret exists and the environment uses branch restrictions; it showed no required-reviewer protection rule. This preparation does not change environment settings.

The action prepares and publishes the official binaries. Local source checks and a local build do not replace its production-signing preflight. Final real-PoB reliability evidence, a real packaged 0.6.0 -> 1.0.0 update, packaged UI/network checks and final binary scanning remain governed by `docs/1.0-HARDENING-PLAN.md`; this version/content change does not claim those checks are complete.

If `DISCORD_RELEASE_WEBHOOK` is configured, the existing publishing workflow sends its announcement after GitHub publication. A dry run sends nothing.

After publication, download the official ZIP, verify its SHA-256, check a fresh install, then confirm a 0.6.0 installation discovers and installs 1.0.0 while preserving its settings, selected build and pinned items.
