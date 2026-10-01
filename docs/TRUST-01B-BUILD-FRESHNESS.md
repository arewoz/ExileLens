# TRUST-01B — PoB Build Freshness

**An old build file is NOT a confirmed stale game character.** ExileLens has no live character
synchronization, so it can only know what is on disk and what it loaded. Copy therefore speaks about the
*PoB build / file*, never "your character".

## What ExileLens can know

* the selected XML's revision (mtime + size) versus the revision it loaded;
* whether a reload is running, or failed and the previous working build was kept;
* the file's modification time (a filesystem fact, not a character fact).

It cannot know whether the live character differs from the PoB build.

## States (`app/build_freshness.py`, `EvaluationController.build_freshness()`)

Stat-only: no XML read, no hashing, no PoB calculation, no timer or watcher. Priority top to bottom:

| State | Evidence | Strength | Copy |
|---|---|---|---|
| `RELOADING` | build state LOADING/RELOADING | strong, transient | PoB build changed on disk — reloading… |
| `USING_LAST_GOOD` | newest revision failed to load; previous build restored (`reload_warning`) | strong | Latest PoB build could not be loaded. Using the previous working version. |
| `DISK_CHANGED` | current stat differs from the loaded revision | strong | PoB build changed on disk — reloading… |
| `OLD_FILE` | file mtime at least `SOFT_STALE_AGE_DAYS = 7` days old | advisory | PoB build may be outdated · last modified 9 days ago |
| `CURRENT` | none of the above | — | (nothing shown) |
| `UNKNOWN` | no build, unreadable file | — | (nothing shown) |

Future, zero or missing timestamps never mark a build stale. Age copy is coarse (`today`, `1 day ago`, `9 days ago`).
"Loaded at" (when ExileLens loaded) is a different timestamp from "file modified" and is never mixed with it.

## Reload behavior (unchanged)

On Item Check a changed on-disk revision still defers the evaluation and reloads first; a failed reload restores the
last good build and rejects the triggering check. A successful reload clears `DISK_CHANGED`, `RELOADING` and
`USING_LAST_GOOD`; `OLD_FILE` can still apply if the file is objectively old.

## Presentation

* **Overview**: quiet when `CURRENT`; otherwise one notice under the build (warning for `OLD_FILE`/`DISK_CHANGED`,
  error for `USING_LAST_GOOD`), with the existing Refresh action. Recomputed on the existing refresh signals.
* **Compact tooltip**: one ordinary note (`⚠ PoB build may be outdated · last modified 9 days ago`). It is appended only
  when the existing `MAX_NOTES` budget has room, so it never displaces a can't-equip, cap-loss or uncertainty note and
  never grows the tooltip. The `OLD_FILE` note is surfaced at most once per app session (in-memory flag); strong states
  are not suppressed.
* **More Info**: a `BUILD SOURCE` section only for non-current states.

## No verdict impact

Freshness lives in `result["build_freshness"]` (attached after the evaluation cache store) and the presentation model.
It is not read by scoring, guardrails, verdict, or evaluation quality.
