# TRUST-01D — Update Awareness

The secure updater (signed manifest, verified download, external updater) is unchanged. This task only adds
*when* it looks and *how visibly* a verified update is shown.

## Automatic check moments

1. Application start (existing, after tray/UI exist).
2. Dashboard window shown (`DashboardWindow.showEvent` -> `UpdateService.start_automatic()`).
3. A single local `QTimer` owned by `UpdateService` fires when `update_last_check_at + CHECK_COOLDOWN_SECONDS` elapses
   (+1 s tolerance, never sooner than 60 s). It does not poll and uses no thread; it only calls `start_automatic()`.
4. Manual "Check for Updates" (`check_now`) bypasses the cooldown, as before.

## Network cooldown

`start_automatic()` owns the 24 h cooldown, so every caller above is bounded to about one request per 24 h; inside the
cooldown it only re-emits the known state. A request made while a check is already in flight no longer touches
`update_last_check_at` (previously it stamped the cooldown without a check starting).

## Notifications

* **Tray balloon**: unchanged, once per remote version via the persisted `update_notified_version`.
* **Footer + tray menu**: unchanged and persistent.
* **Dashboard notice** (new, non-modal, inside the dashboard, no focus grab, never over the Item Check overlay):
  "ExileLens X is available / You're using Y", `Download update` -> `Downloading… n%` -> `Restart & Update` ->
  `Installing…`, `Later`, and `What's new` only when the verified release already carries a github.com URL.
  It follows the existing state machine and calls the existing `start_download` / `restart_and_update`.

## Frequency and dismissal

`Later` hides the notice for the rest of the session (in-memory set of versions; `update_notified_version` is not
reused). A release found while the dashboard was hidden shows when it is next opened. A new app session shows a
still-pending update again. No persisted snooze, no new settings.

## Verification boundary

The notice appears only for `state == "available"` (a signed, verified, newer release). `verification_failed`, failed
checks, a current version, and a persisted remote not newer than the installed version show nothing. A pending update
remembered from an earlier session has no verified manifest in memory; clicking Download first runs a user-initiated
check that verifies the signed manifest and then downloads. Nothing about verification is relaxed.

## Failures and non-packaged runs

An automatic check failure is silent (state `failed`, no notice, no balloon); manual checks keep their existing
feedback. Source/dev runs report `unavailable`, make no request, start no timer and show no notice.
