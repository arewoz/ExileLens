from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from exilelens.app.logging_setup import configure_logging
from exilelens.updater.install import run_update_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exilelens-updater")
    parser.add_argument("job", type=Path, help="Path to pending update job JSON")
    args = parser.parse_args(argv)
    configure_logging()
    logging.getLogger(__name__).info("updater_start job=%s", args.job)
    return run_update_job(args.job)


if __name__ == "__main__":
    raise SystemExit(main())
