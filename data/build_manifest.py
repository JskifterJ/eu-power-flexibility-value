"""CLI: (re)build the committed price manifest from whatever is cached.

    python -m data.build_manifest
    python -m data.build_manifest --zones DE-LU --years 2023 2024

Reads only the local cache — never the network. Writes
``data/manifest/prices_manifest.{csv,json}``. Sealed-holdout years cannot appear:
the loader refuses them (see :mod:`data.holdout`).
"""

from __future__ import annotations

import argparse
import sys

from data.config import load_data_config, load_zones
from data.energy_charts import cached_years
from data.manifest import build_manifest, write_manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None)
    parser.add_argument("--years", nargs="*", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_data_config()
    zones = load_zones()

    selected = args.zones or list(zones)
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}", file=sys.stderr)
        return 2

    have = {z: cached_years(z, cfg) for z in selected}
    n_cached = sum(len(v) for v in have.values())
    if n_cached == 0:
        print("no cached price files found — run `python -m data.fetch_prices` first.",
              file=sys.stderr)
        print(f"expected cache root: {cfg['sources']['energy_charts']['cache_dir']}",
              file=sys.stderr)
        return 3

    frame = build_manifest(selected, args.years, cfg)
    csv_path, json_path = write_manifest(frame, config=cfg)
    print(frame.to_string(index=False))
    print(f"\n{len(frame)} rows -> {csv_path}\n{' ' * 9} -> {json_path}")

    suspicious = frame[(frame["coverage_ratio"] < 0.999) | (frame["n_gap_intervals"] > 0)
                       | (frame["n_nan"] > 0)]
    if not suspicious.empty:
        print("\nrows with gaps / missing intervals / NaNs (investigate in C2):",
              file=sys.stderr)
        print(suspicious[["zone", "year", "n_points", "n_expected_points",
                          "coverage_ratio", "n_gap_intervals", "n_nan"]].to_string(index=False),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
