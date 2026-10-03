#!/usr/bin/env python3
"""Verify a signed update manifest envelope against the embedded update trust set.

The default trust profile is *production* (exactly what a shipped ExileLens accepts). ``--trust-profile
test`` additionally trusts the public test key and is only meaningful as a pipeline self-check; it is
never evidence that a manifest would be accepted by an installed copy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Signed .update.json envelope")
    parser.add_argument("--trust-profile", choices=("production", "test"), default="production")
    parser.add_argument("--expect-tag", default=None, help="Require the signed tag/version/artifact binding for this tag")
    args = parser.parse_args(argv)
    from exilelens.app.updates.manifest import bind_manifest_to_release, verify_signed_envelope
    from exilelens.app.updates.trust import use_test_trust_profile
    from exilelens.app.updates.version import ExileLensVersion

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    with use_test_trust_profile(args.trust_profile == "test"):
        verified = verify_signed_envelope(payload)
    if args.expect_tag:
        tag = str(args.expect_tag).strip()
        version = ExileLensVersion.parse(tag[1:] if tag.startswith("v") else tag)
        if version is None:
            raise SystemExit(f"--expect-tag is not a release tag: {tag}")
        bind_manifest_to_release(verified, tag=tag, version=version, installed=None)
    print(f"OK profile={args.trust_profile} signing_key_id={verified.signing_key_id} version={verified.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
