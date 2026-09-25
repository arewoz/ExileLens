#!/usr/bin/env python3
"""Regenerate the hash-locked Windows release dependency lock.

Reads the human-readable direct pins from
`packaging/requirements-release.txt` and writes the fully resolved,
hash-pinned lock to `packaging/requirements-release.lock`, which is what
official release builds install with `pip install --require-hashes`.

Usage:
    py -3.12 scripts/lock_release_deps.py          # refresh the lock (network)
    py -3.12 scripts/lock_release_deps.py --check  # offline drift/hash check

Design:
    * `packaging/requirements-release.txt` stays the readable set of direct
      `Package==Version` pins. This script never edits it, and the release
      preflight keeps its strict direct-pin parser (no hash syntax there).
    * `RESOLVED` below is the fully resolved closure (direct + transitive)
      for the pinned release Python in `.python-version` on Windows
      (`win_amd64`). Every entry uses an exact version; hashes for ALL PyPI
      files of that version are recorded so pip can verify whichever
      artifact it selects.
    * Release-time drift detection lives in
      `scripts/release_python_preflight.ps1`, which fails the build if any
      direct pin disagrees with the lock. `--check` performs the same
      comparison offline (plus a missing-hash check) for convenience.

Refreshing after a dependency change:
    1. Edit the direct pin(s) in `packaging/requirements-release.txt`.
    2. Resolve the new transitive closure on Windows with the pinned
       release Python, e.g.:
           py -3.12 -m pip install --dry-run --ignore-installed ^
               --requirement packaging/requirements-release.txt ^
               --report report.json
       (read the `install` list in report.json for exact versions)
    3. Update `RESOLVED` below to those exact versions.
    4. Run `py -3.12 scripts/lock_release_deps.py` and commit both files.

Only the standard library is used, so refreshing needs no extra tooling.
Do not bump direct versions unless the release itself requires it.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIRECT_REQUIREMENTS = REPO_ROOT / "packaging" / "requirements-release.txt"
LOCK_FILE = REPO_ROOT / "packaging" / "requirements-release.lock"
PYTHON_VERSION_FILE = REPO_ROOT / ".python-version"

# Fully resolved closure for the Windows release environment, as reported
# by `pip install --dry-run` on win_amd64 with the pinned release Python.
# Keep exact versions only. Do not bump direct pins here; edit
# packaging/requirements-release.txt first (see steps above).
RESOLVED: dict[str, str] = {
    "altgraph": "0.17.5",
    "cffi": "2.1.1",
    "cryptography": "44.0.2",
    "packaging": "26.3",
    "pefile": "2024.8.26",
    "pillow": "12.3.0",
    "pycparser": "3.0",
    "pyinstaller": "6.22.2",
    "pyinstaller-hooks-contrib": "2026.7",
    "pyside6": "6.11.2",
    "pyside6-addons": "6.11.2",
    "pyside6-essentials": "6.11.2",
    "pywin32-ctypes": "0.2.3",
    "setuptools": "84.0.0",
    "shiboken6": "6.11.2",
}

_DIRECT_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+!*]+)$")
_HASH_RE = re.compile(r"^--hash=sha256:([0-9a-fA-F]{64})$")


def normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def read_release_python() -> str:
    value = PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise SystemExit(f"{PYTHON_VERSION_FILE} must contain major.minor.patch")
    return value


def parse_direct_pins(path: Path) -> dict[str, str]:
    """Parse the direct requirements file (strict simple `Name==Version`)."""
    pins: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _DIRECT_RE.match(line)
        if not m:
            raise SystemExit(
                f"{path}:{lineno}: direct pins must be simple `Name==Version` "
                f"lines (no hashes/options): {raw!r}"
            )
        pins[normalize(m.group(1))] = m.group(2)
    if not pins:
        raise SystemExit(f"{path}: no direct pins found")
    return pins


def parse_lock(path: Path) -> dict[str, dict]:
    """Parse the generated lock into {name: {version, hashes, line}}."""
    entries: dict[str, dict] = {}
    current: str | None = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cont = line.endswith("\\")
        line = line[:-1].strip() if cont else line
        if not line:
            continue
        if current is None:
            m = _DIRECT_RE.match(line)
            if not m:
                raise SystemExit(f"{path}:{lineno}: expected `Name==Version`: {raw!r}")
            current = normalize(m.group(1))
            if current in entries:
                raise SystemExit(f"{path}:{lineno}: duplicate entry for {current}")
            entries[current] = {"version": m.group(2), "hashes": [], "line": lineno}
            if not cont:
                current = None
        else:
            m = _HASH_RE.match(line)
            if not m:
                raise SystemExit(
                    f"{path}:{lineno}: expected `--hash=sha256:<hex>`: {raw!r}"
                )
            entries[current]["hashes"].append(m.group(1).lower())
            if not cont:
                current = None
    if current is not None:
        raise SystemExit(f"{path}: truncated entry for {current}")
    return entries


def check_consistency(direct: dict[str, str], locked: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    for name, version in sorted(direct.items()):
        if name not in locked:
            errors.append(f"direct pin {name}=={version} missing from lock file")
        elif locked[name]["version"] != version:
            errors.append(
                f"drift: direct pin {name}=={version} != "
                f"lock {name}=={locked[name]['version']}"
            )
    for name, entry in sorted(locked.items()):
        if not entry["hashes"]:
            errors.append(f"lock entry {name}=={entry['version']} has no hashes")
    return errors


def fetch_package(package: str, version: str) -> tuple[str, list[tuple[str, str]]]:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.load(resp)
    info_version = data["info"]["version"]
    if info_version != version:
        raise SystemExit(f"PyPI version mismatch for {package}: {info_version} != {version}")
    files = data.get("urls", [])
    if not files:
        raise SystemExit(f"PyPI returned no files for {package}=={version}")
    out: list[tuple[str, str]] = []
    for f in files:
        digest = f.get("digests", {}).get("sha256", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise SystemExit(f"bad sha256 for {f.get('filename')} ({package}=={version})")
        out.append((f["filename"], digest.lower()))
    out.sort(key=lambda t: t[0].lower())
    return data["info"]["name"], out


def render_lock(python_version: str,
                hashed: dict[str, tuple[str, list[tuple[str, str]]]]) -> str:
    lines = [
        "# Generated by `py -3.12 scripts/lock_release_deps.py` — DO NOT EDIT.",
        "# Source: packaging/requirements-release.txt (direct pins).",
        f"# Release Python: {python_version} (see .python-version) on windows-latest (win_amd64).",
        "# Install (official release builds):",
        "#   pip install --require-hashes --requirement packaging/requirements-release.lock",
        "# Refresh after changing direct pins: see scripts/lock_release_deps.py.",
        "",
    ]
    for name in sorted(hashed, key=lambda n: n.lower()):
        version, files = hashed[name]
        lines.append(f"{name}=={version} \\")
        for i, (_, digest) in enumerate(files):
            sep = " \\" if i < len(files) - 1 else ""
            lines.append(f"    --hash=sha256:{digest}{sep}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    release_python = read_release_python()
    direct = parse_direct_pins(DIRECT_REQUIREMENTS)
    resolved = {normalize(k): v for k, v in RESOLVED.items()}

    drift = [
        f"direct pin {n}=={v} not reflected in RESOLVED ({resolved.get(n, 'missing')})"
        for n, v in sorted(direct.items())
        if resolved.get(n) != v
    ]
    if drift:
        print("Direct pins disagree with RESOLVED in scripts/lock_release_deps.py:",
              file=sys.stderr)
        for d in drift:
            print(f"  - {d}", file=sys.stderr)
        print("Update RESOLVED (see `pip install --dry-run` steps above) and rerun.",
              file=sys.stderr)
        return 1

    if check_only:
        if not LOCK_FILE.exists():
            print(f"missing lock file: {LOCK_FILE}", file=sys.stderr)
            return 1
        locked = parse_lock(LOCK_FILE)
        errors = check_consistency(direct, locked)
        extra = sorted(set(locked) - set(resolved))
        if extra:
            errors.append(f"lock has unexpected entries not in RESOLVED: {extra}")
        missing = sorted(set(resolved) - set(locked))
        if missing:
            errors.append(f"lock missing resolved packages: {missing}")
        for name in sorted(set(resolved) & set(locked)):
            if locked[name]["version"] != resolved[name]:
                errors.append(
                    f"lock {name}=={locked[name]['version']} != "
                    f"RESOLVED {name}=={resolved[name]}"
                )
        if errors:
            for e in errors:
                print(f"lock check FAILED: {e}", file=sys.stderr)
            return 1
        print(f"lock check OK: {len(locked)} packages, "
              f"{sum(len(e['hashes']) for e in locked.values())} hashes")
        return 0

    hashed: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    for name in sorted(resolved, key=lambda n: n.lower()):
        display, files = fetch_package(name, resolved[name])
        hashed[display] = (resolved[name], files)
        print(f"{display}=={resolved[name]}: {len(files)} file(s) hashed")
    LOCK_FILE.write_text(render_lock(release_python, hashed), encoding="utf-8",
                         newline="\n")
    print(f"wrote {LOCK_FILE} ({len(hashed)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
