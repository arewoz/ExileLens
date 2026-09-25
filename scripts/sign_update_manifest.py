#!/usr/bin/env python3
"""Sign an ExileLens update manifest envelope for GitHub Release publication."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from exilelens.app.updates.manifest import canonical_manifest_bytes


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    data = path.read_bytes()
    return serialization.load_pem_private_key(data, password=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True, help="Unsigned manifest JSON object")
    parser.add_argument("--private-key", type=Path, required=True, help="Ed25519 private key PEM")
    parser.add_argument("--output", type=Path, required=True, help="Signed envelope output path")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("manifest must be a JSON object")
    key = _load_private_key(args.private_key)
    signature = key.sign(canonical_manifest_bytes(manifest))
    envelope = {"manifest": manifest, "signature": base64.b64encode(signature).decode("ascii")}
    args.output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
