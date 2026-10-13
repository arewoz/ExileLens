# PERF-02 — Filters and Diagnostics navigation

PERF-01 is included in main at `72a5929` (PR #85), but it covered engine loading
and Item Check. It did not remove the navigation stalls reported on 2026-10-13.

Filters regenerated the same selection on every visit, including twice on its
first visit. Cold crafting assessments scanned every item level repeatedly.
Diagnostics built an extended summary just to obtain a session ID, starting Git
three times and querying Windows through WMI on every refresh in a source run.

The dashboard now generates filters in a background thread, coalesces changes,
and applies a result only if the selected profile, theme, needs, fingerprint and
baseline generation still match. Installation is disabled while that selection
is pending. Unchanged visits reuse the existing filter and preview. Standalone
filter tooling keeps its synchronous interface. Background generation yields
between batches so Python's GIL does not starve Qt input and timer callbacks.

Crafting thresholds use a cached binary search over sorted tier levels. An
exhaustive comparison against the original scan covers every verified base.
Preview layout avoids repeated axis scoring and collision checks, and reuses an
unchanged layout. Diagnostics obtains the support ID directly and caches the
source commit and Windows version for the lifetime of the process; live engine,
build, error, event and PoB state still refreshes.

## Measurements

Windows, Python 3.12.10, offscreen Qt, 1280 × 860, isolated profile with the real
dashboard and a synthetic ready controller. No PoB engine or network is used.
These are unprofiled reference runs on the same development machine, not an FPS
guarantee or packaged-build timings. Durations vary with system load.

| Interaction | Main before: handler / largest UI gap | After: handler / largest UI gap |
|---|---:|---:|
| First Filters visit | 1851 / 1851 ms | 116 / 116 ms |
| Repeated Filters visit | 138–140 / 139–141 ms | 5 / 5 ms |
| Diagnostics visit | 111–120 / 111–121 ms | 1–3 / 5–6 ms |
| Profile change | 144 / 144 ms | 7 / 45 ms |
| Theme change | 164 / 165 ms | 7 / 14 ms |

The first preview becomes ready in about 422 ms after the change, versus
1860 ms before. Profile/theme replacement takes about 172–205 ms, with input
remaining responsive during generation. First module/widget creation and
rendering new preview labels still cause a smaller, one-time hitch; this change
does not claim every frame stays below 16.7 ms.

Reproduce in a fresh process:

```powershell
py -3.12 scripts/benchmark_dashboard_navigation.py --output navigation.json
```

## Validation

- Seven navigation/generation regressions cover UI activity while work is
  blocked, coalescing, changed baselines, stale-install prevention, failure and
  retry, unchanged visits, Git caching, threshold equivalence and cooperative
  generation preserving both general and measured filter rules.
- Focused Filters/Analyze Build/preview suite: 85 passed.
- Startup/diagnostics/support composition selection: 48 passed before the final
  two cooperative-equivalence cases were added; those cases are in the 85 above.
- Offline feature report: 40/40 general profile/theme combinations valid,
  both Experimental navigation badges present. Static undefined-name check passed.
- Earlier wider UI/filter selection: 178 passed, two existing Settings layout
  failures. Both failures also reproduce on unchanged main `72a5929`:
  `settings-patreon-expired` at 840 × 640 / 150% text scale, and
  `test_cards_and_zones_stack_deliberately_when_narrow` at width 720.

The added generation regressions run in the existing native Windows PR gate.
Native PoE2 filter acceptance remains separately unverified.
