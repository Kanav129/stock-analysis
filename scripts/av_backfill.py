#!/usr/bin/env python3
"""Drip Alpha Vantage statement snapshots into av_fundamentals.

The daily price+news sync calls the same service after sync succeeds, and
only spends Alpha Vantage when Yahoo fundamentals are failing. See README,
"Daily Alpha Vantage drip".

Examples:
  python scripts/av_backfill.py --dry-run
  python scripts/av_backfill.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from services.av_backfill_service import AvBackfillService


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Choose tickers and exit without calling Alpha Vantage.",
    )
    args = parser.parse_args(argv)
    result = AvBackfillService().run(dry_run=args.dry_run)
    print(json.dumps(result, default=str, indent=2))
    if result.get("reason") == "missing_api_key":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
