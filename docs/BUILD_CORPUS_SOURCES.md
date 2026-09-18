# Public Build Corpus and real-PoB validation assets

## Purpose

This repository includes a deliberately small, deterministic regression corpus for
the Item Check engine. It validates that a supported local Path of Building 2 runtime
can load representative player, minion, and staged-skill builds from fixtures checked
into this repository. The strategic suite additionally validates ring replacement,
ring trade-off handling, an explicit empty slot, bow/quiver behavior, restore recovery,
and one batched candidate evaluation.

The corpus is a regression gate, not a build downloader or a live market tool. It does
not need network access, a game login, or any data outside this checkout and the local
PoB2 runtime.

## Fixture inventory

| Fixture | Coverage |
| --- | --- |
| `fixtures/builds/core04_player_ring.xml` | Player Spark context; Ring 1/Ring 2 replacement, trade-off, empty Ring 2 mutation, restore recovery, and batching. |
| `fixtures/builds/public_corpus/core04_bow_quiver.xml` | Player Ice Shot with a bow/quiver equipment layout. |
| `fixtures/builds/public_corpus/core04_minion_actor.xml` | Summon Infernal Hound with minion-owned primary output. |
| `fixtures/builds/public_corpus/core04_stage_context.xml` | Flameblast channel-release stage context. |
| `fixtures/items/core04_*.txt` | Deterministic ring candidates used by the strategic suite. |

`fixtures/builds/public_corpus/manifest.json` is the authoritative three-scenario
corpus manifest. It contains repository-relative paths and expected semantic identity,
not captured output snapshots.

## Provenance and sanitization

The fixtures were selected from a prior local development validation corpus as
calculation inputs only. They were screened before publication for filenames and text
containing local paths, home-directory references, account or character metadata,
emails, credentials, session/cookie/authentication fields, and private links.

The selected XML files have no retained account or character attributes. Empty
`itemPbURL` attributes are retained because they are part of the PoB fixture format;
they contain no URLs. Item display names are ordinary in-game fixture text and are not
account identifiers. No player profiles, account names, character names, IDs tied to a
real account, tokens, cookies, diagnostics, local caches, or source-machine metadata
are stored.

The public safety regression scans every selected text fixture for these categories.
It is intentionally conservative: a fixture that cannot pass the scan should be
excluded or re-sanitized rather than worked around in a test.

## Commands

Set `POB2_PATH` to a supported local Path of Building 2 installation. The path is an
environment input only and is never committed or written by the tests.

```powershell
$env:POB2_PATH = '<path-to-supported-PoB2>'
python -m pytest -m real_pob
python -m pytest -m build_corpus
```

`real_pob` runs the strategic suite. `build_corpus` runs static manifest/safety checks
and real-worker loading for the checked-in corpus. If no supported runtime is found,
worker tests are reported as **SKIPPED** with a message explaining how to configure
`POB2_PATH`; they do not become passing tests. A configured but invalid or unsupported
runtime is a test error.

## Updating the corpus

Corpus generation is intentionally not part of the regular test command. A future
update may use external/public sources during curation, but the resulting regression
fixtures must be materialized here, sanitized, documented, and runnable without the
generation environment. Do not add live account, market, or API acquisition to this
gate.
