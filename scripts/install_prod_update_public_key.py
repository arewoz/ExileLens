#!/usr/bin/env python3
"""Install exilelens-prod-1 public key into embedded trust configuration."""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRUST_PATH = REPO_ROOT / "src" / "exilelens" / "app" / "updates" / "trust.py"
PROD_ID = "exilelens-prod-1"


def _load_public_key_b64(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text or "\n" in text.strip():
        # allow single-line file only
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) != 1:
            raise SystemExit("Public key file must contain a single base64 line.")
        text = lines[0]
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise SystemExit(f"Invalid base64 public key: {exc}") from exc
    if len(raw) != 32:
        raise SystemExit(f"Ed25519 public key must be 32 raw bytes; got {len(raw)}.")
    return text


def install_public_key(public_key_b64: str) -> None:
    source = TRUST_PATH.read_text(encoding="utf-8")
    line = f'    {PROD_ID}: base64.b64decode("{public_key_b64}"),\n'
    pattern = re.compile(
        rf'^[ \t]*{re.escape(PROD_ID)}:\s*base64\.b64decode\("[^"]+"\),?\s*\n',
        re.MULTILINE,
    )
    if pattern.search(source):
        TRUST_PATH.write_text(pattern.sub(line, source, count=1), encoding="utf-8")
        return
    marker = "EMBEDDED_VERIFY_KEYS: Mapping[str, bytes] = {"
    idx = source.find(marker)
    if idx < 0:
        raise SystemExit(f"Could not find EMBEDDED_VERIFY_KEYS in {TRUST_PATH}")
    insert_at = source.find("}", idx)
    if insert_at < 0:
        raise SystemExit("Malformed trust.py")
    TRUST_PATH.write_text(source[:insert_at] + line + source[insert_at:], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed exilelens-prod-1 public key in trust.py")
    parser.add_argument(
        "--public-key",
        type=Path,
        required=True,
        help="Path to file containing raw 32-byte Ed25519 public key (standard base64, one line)",
    )
    args = parser.parse_args(argv)
    if not args.public_key.is_file():
        raise SystemExit(f"Public key file not found: {args.public_key}")
    b64 = _load_public_key_b64(args.public_key)
    install_public_key(b64)
    print(f"Installed {PROD_ID} public key into {TRUST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
