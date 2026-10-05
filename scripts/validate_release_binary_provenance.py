"""Validate PyInstaller native-binary origins and write the release binary manifest (see exilelens.ops.binary_provenance)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from exilelens.ops.binary_provenance import validate_and_write_manifest  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--venv-root", required=True)
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--dist-root", required=True)
    parser.add_argument("--collect-toc", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--application-version", required=True)
    parser.add_argument("--updater-built", required=True, help="the single updater build output that was copied into the package")
    parser.add_argument("--system-root", action="append", default=[])
    parser.add_argument("--approved-root", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    try:
        payload = validate_and_write_manifest(parse_args())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Validated {len(payload['binaries'])} native binaries and {len(payload['executables'])} executables; manifest: generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
