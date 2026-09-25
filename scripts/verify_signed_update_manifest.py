#!/usr/bin/env python3
"""Verify a signed update manifest envelope against embedded trust keys."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Signed .update.json envelope")
    args = parser.parse_args(argv)
    from exilelens.app.updates.manifest import verify_signed_envelope

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    verified = verify_signed_envelope(payload)
    print(f"OK signing_key_id={verified.signing_key_id} version={verified.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
