"""CLI: fetch day-ahead prices for every (zone, year) in scope into the cache.

    python -m data.fetch_prices                 # all 9 zones, all fetch_years
    python -m data.fetch_prices --dry-run       # show what would be requested
    python -m data.fetch_prices --zones DE-LU ES --years 2023 2024

Already-cached (zone, year) pairs are skipped without a request — there is no
force-refetch flag by design (CLAUDE.md: never re-download cached data).
Sealed-holdout years are refused by :mod:`data.holdout` before any request.

A 404 / empty / schema-violating response for one pair is reported as a FLAG,
that pair is skipped, and the remaining pairs still run; the process then exits
non-zero so the cycle cannot mistake a partial pull for a complete one. Copy the
FLAG lines into PROGRESS.md.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

from data.config import load_data_config, load_zones
from data.energy_charts import FetchFailed, UnexpectedResponse, fetch_year
from data.holdout import SealedHoldoutError
from data.manifest import MANIFEST_DIR

FAILURES_PATH = MANIFEST_DIR / "fetch_failures.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None, help="zone keys (default: all)")
    parser.add_argument("--years", nargs="*", type=int, default=None,
                        help="calendar years (default: config fetch_years)")
    parser.add_argument("--tier", choices=["A", "B"], default=None, help="restrict to a tier")
    parser.add_argument("--dry-run", action="store_true",
                        help="list the (zone, year) pairs that would be requested")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_data_config()
    zones = load_zones()

    selected = args.zones or list(zones)
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}; known: {sorted(zones)}", file=sys.stderr)
        return 2
    if args.tier:
        selected = [z for z in selected if zones[z].tier == args.tier]
    years = args.years or [int(y) for y in cfg["fetch_years"]]

    print(f"zones={selected}\nyears={years}\n")
    downloaded, skipped = 0, 0
    failures: list[dict[str, str]] = []

    with requests.Session() as session:
        session.headers.update({"Accept": "application/json"})
        for zone_key in selected:
            for year in years:
                label = f"{zone_key} {year}"
                if args.dry_run:
                    print(f"  would fetch  {label}")
                    continue
                try:
                    path, was_downloaded = fetch_year(zone_key, year, cfg, session=session)
                except (UnexpectedResponse, FetchFailed, SealedHoldoutError) as exc:
                    kind = type(exc).__name__
                    print(f"  FLAG  {label}: {kind}: {exc}", file=sys.stderr)
                    failures.append({"zone": zone_key, "year": str(year),
                                     "error_type": kind, "message": str(exc)})
                    continue
                if was_downloaded:
                    downloaded += 1
                    print(f"  fetched      {label}  -> {path}")
                else:
                    skipped += 1
                    print(f"  cached       {label}  (no request made)")

    if args.dry_run:
        return 0

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    with FAILURES_PATH.open("w", encoding="utf-8") as fh:
        json.dump({"n_failures": len(failures), "failures": failures}, fh, indent=2)
        fh.write("\n")

    print(f"\ndownloaded={downloaded} already_cached={skipped} flagged={len(failures)}")
    if failures:
        print(f"FLAGs written to {FAILURES_PATH} — record them in PROGRESS.md",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
