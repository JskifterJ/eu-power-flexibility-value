"""CLI: (re)build the committed exogenous manifest from whatever is cached.

    python -m data.build_exog_manifest
    python -m data.build_exog_manifest --zones DE-LU --years 2024

Reads only the local cache — never the network. Writes
``data/manifest/exogenous_manifest.{csv,json}``. Sealed-holdout years cannot
appear: the loader refuses them (see :mod:`data.holdout`).
"""

from __future__ import annotations

import argparse
import sys

from data.config import load_data_config, load_zones
from data.entsoe import cached_years, load_documents
from data.exog_manifest import build_exog_manifest, write_exog_manifest

DISPLAY_COLUMNS = [
    "zone", "document", "series", "leakage_status", "year", "n_points_native",
    "coverage_ratio", "resolutions_seconds", "n_gap_intervals", "max_gap_hours",
    "n_nan", "mw_min", "mw_mean", "mw_max", "n_negative",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None)
    parser.add_argument("--documents", nargs="*", default=None)
    parser.add_argument("--years", nargs="*", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_data_config()
    zones = load_zones()
    documents = load_documents(cfg)

    selected = args.zones or [k for k, z in zones.items() if z.tier == "A"]
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}", file=sys.stderr)
        return 2
    doc_keys = args.documents or list(documents)
    unknown_docs = [d for d in doc_keys if d not in documents]
    if unknown_docs:
        print(f"unknown document key(s): {unknown_docs}", file=sys.stderr)
        return 2

    n_cached = sum(
        len(cached_years(z, d, cfg)) for z in selected for d in doc_keys
    )
    if n_cached == 0:
        print("no cached ENTSO-E documents found — run "
              "`python -m data.fetch_exogenous` first.", file=sys.stderr)
        print(f"expected cache root: {cfg['sources']['entsoe']['cache_dir']}",
              file=sys.stderr)
        return 3

    frame = build_exog_manifest(selected, doc_keys, args.years, cfg)
    csv_path, json_path = write_exog_manifest(frame, config=cfg)
    print(frame[DISPLAY_COLUMNS].to_string(index=False))
    print(f"\n{len(frame)} rows -> {csv_path}\n{' ' * 9} -> {json_path}")

    suspicious = frame[
        (frame["coverage_ratio"] < 0.999)
        | (frame["n_gap_intervals"] > 0)
        | (frame["n_nan"] > 0)
        | (frame["n_negative"] > 0)
    ]
    if not suspicious.empty:
        print("\nrows with gaps / missing intervals / NaNs / negatives "
              "(see data/manifest/exogenous_contract_report.json):", file=sys.stderr)
        print(suspicious[["zone", "document", "series", "year", "n_points_native",
                          "n_expected_native", "coverage_ratio", "n_gap_intervals",
                          "n_nan", "n_negative"]].to_string(index=False),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
