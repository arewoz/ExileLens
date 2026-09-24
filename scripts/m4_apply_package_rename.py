"""One-shot M4.0 package rename: poe2value -> exilelens with preserved legacy tokens."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIR_NAMES = {
    ".git",
    ".release-validation",
    "ExileLens-onboarding-01",
    "dist",
    "build",
    "__pycache__",
    ".release-venv",
    "node_modules",
}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".json",
    ".ps1",
    ".spec",
    ".lua",
    ".toml",
    ".ini",
    ".bat",
    ".sh",
}

# Lines containing these substrings are never rewritten (legacy compatibility).
LINE_GUARD_SUBSTRINGS = (
    "poe2-value-overlay",
    "PoE2ValueForMyBuild",
    "PoE2 Value",
    "poe2value.log",
    "poe2-value-overlay/0.5",
    "poe2-value-overlay/phase35",
    "--poe2value-worker",
    "POE2VALUE_",
    "poe2-value-overlay (product core)",
)


def should_skip_path(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def guarded_replace_line(line: str) -> str:
    if any(token in line for token in LINE_GUARD_SUBSTRINGS):
        return line
    updated = line
    updated = updated.replace("poe2value-gui", "exilelens-gui")
    updated = re.sub(r"\bpoe2value\b", "exilelens", updated)
    updated = updated.replace("Poe2ValueApp", "ExileLensApp")
    return updated


def rewrite_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = text.splitlines(keepends=True)
    new_lines = [guarded_replace_line(line) for line in lines]
    new_text = "".join(new_lines)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> int:
    src_old = ROOT / "src" / "poe2value"
    src_new = ROOT / "src" / "exilelens"
    if src_old.is_dir() and not src_new.exists():
        subprocess.run(["git", "mv", str(src_old), str(src_new)], cwd=ROOT, check=True)

    spec_old = ROOT / "packaging" / "poe2value-gui.spec"
    spec_new = ROOT / "packaging" / "exilelens-gui.spec"
    if spec_old.is_file() and not spec_new.exists():
        subprocess.run(["git", "mv", str(spec_old), str(spec_new)], cwd=ROOT, check=True)

    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip_path(path.relative_to(ROOT)):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "Makefile"}:
            continue
        if path.name == "m4_apply_package_rename.py":
            continue
        if rewrite_file(path):
            changed += 1
    print(f"rewrote {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
