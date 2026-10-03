#!/usr/bin/env python3
"""Generate the production ENTITLEMENT signing key pair OFFLINE (owner-run, once).

The entitlement key signs supporter leases. It is a different key from the update-signing key on purpose:
compromising it can at most forge "may automate updates" for already-signed public releases, never the
software itself.

* The private key is written OUTSIDE the repository (default ``%USERPROFILE%\\.exilelens\\signing\\exilelens-entitlement-1``)
  and the script refuses any output directory inside a git checkout.
* It prints the public key (paste it into ``PRODUCTION_ENTITLEMENT_KEYS`` in
  ``src/exilelens/cloud/entitlement.py`` and ship a release) and the one-line private value for
  ``wrangler secret put ENTITLEMENT_SIGNING_KEY --env <env>``. The private value is only written to the output
  directory, never printed.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

DEFAULT_KEY_ID = "exilelens-entitlement-1"


def _inside_git_checkout(path: Path) -> bool:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key-id", default=DEFAULT_KEY_ID)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    out_dir = args.out_dir or Path(os.path.expanduser("~")) / ".exilelens" / "signing" / args.key_id
    if _inside_git_checkout(out_dir):
        print("Refusing to write a private key inside a git checkout. Choose --out-dir outside the repository.", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    private_path = out_dir / f"{args.key_id}-private.pkcs8.b64"
    if private_path.exists():
        print(f"{private_path} already exists; refusing to overwrite a key.", file=sys.stderr)
        return 2

    key = Ed25519PrivateKey.generate()
    pkcs8 = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    private_path.write_text(base64.b64encode(pkcs8).decode("ascii") + "\n", encoding="ascii")
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    (out_dir / f"{args.key_id}-public.b64").write_text(base64.b64encode(public).decode("ascii") + "\n", encoding="ascii")

    print(f"key id:      {args.key_id}")
    print(f"public key:  {base64.b64encode(public).decode('ascii')}")
    print(f"private key: written to {private_path} (back it up offline; never commit or paste it)")
    print("next: wrangler secret put ENTITLEMENT_SIGNING_KEY --env <env>   (paste the single line from that file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
