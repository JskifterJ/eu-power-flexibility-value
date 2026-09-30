"""CLI: run the C2 data contracts over every cached zone and commit the report.

    python -m data.build_contracts
    python -m data.build_contracts --zones DE-LU NO2

Reads only the local cache — never the network. Writes

    data/manifest/contract_report.csv    one row per zone, human-eyeballable
    data/manifest/contract_report.json   full detail incl. every violation
    data/manifest/dst_whitelist.csv      the derived 23h/25h local-day calendar

Exit codes: 0 all contracts hold; 1 at least one violation (the report still
gets written — a violation is evidence, not a reason to write nothing);
3 nothing cached.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from data.config import config_hash, load_data_config, load_zones
from data.contracts import build_contract_report, dst_transition_days
from data.energy_charts import cached_years
from data.manifest import MANIFEST_DIR, git_sha
from data.prices import load_zone_series

CONTRACT_CSV = MANIFEST_DIR / "contract_report.csv"
CONTRACT_JSON = MANIFEST_DIR / "contract_report.json"
DST_CSV = MANIFEST_DIR / "dst_whitelist.csv"

SUMMARY_COLUMNS = [
    "zone", "tier", "local_tz", "n_points", "first_ts_utc", "last_ts_utc",
    "modal_resolution_seconds", "payload_sha256", "index_is_utc", "index_is_monotonic",
    "n_duplicate_timestamps", "n_nan_prices", "n_missing_intervals", "max_gap_hours",
    "n_utc_days_checked", "n_utc_day_violations",
    "n_local_days_checked", "n_local_day_violations", "n_dst_days_seen",
    "n_resolution_changes", "n_cutover_violations", "n_violations", "ok",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None)
    parser.add_argument("--years", nargs="*", type=int, default=None)
    parser.add_argument(
        "--manifest-dir", default=None, help="override the output directory"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_data_config()
    zones = load_zones()
    out_dir = Path(args.manifest_dir) if args.manifest_dir else MANIFEST_DIR

    selected = args.zones or list(zones)
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}", file=sys.stderr)
        return 2
    if sum(len(cached_years(z, cfg)) for z in selected) == 0:
        print("no cached price files found — run `python -m data.fetch_prices` first.",
              file=sys.stderr)
        return 3

    reports = []
    for zone_key in selected:
        if not cached_years(zone_key, cfg):
            print(f"FLAG {zone_key}: nothing cached, skipped", file=sys.stderr)
            continue
        frame = load_zone_series(zone_key, args.years, cfg)
        reports.append(build_contract_report(zone_key, frame, cfg))

    rows = [
        {
            "zone": r.zone,
            "tier": r.tier,
            "local_tz": r.local_tz,
            "n_points": r.n_points,
            "first_ts_utc": r.first_ts_utc,
            "last_ts_utc": r.last_ts_utc,
            "modal_resolution_seconds": r.modal_resolution_seconds,
            "payload_sha256": r.payload_sha256,
            "index_is_utc": r.index_is_utc,
            "index_is_monotonic": r.index_is_monotonic,
            "n_duplicate_timestamps": r.n_duplicate_timestamps,
            "n_nan_prices": r.n_nan_prices,
            "n_missing_intervals": r.n_missing_intervals,
            "max_gap_hours": r.max_gap_hours,
            "n_utc_days_checked": r.n_utc_days_checked,
            "n_utc_day_violations": len(r.utc_day_violations),
            "n_local_days_checked": r.n_local_days_checked,
            "n_local_day_violations": len(r.local_day_violations),
            "n_dst_days_seen": r.n_dst_days_seen,
            "n_resolution_changes": len(r.resolution_changes),
            "n_cutover_violations": len(r.cutover_violations),
            "n_violations": len(r.violations),
            "ok": r.ok,
        }
        for r in reports
    ]
    summary = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)

    out_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_dir / CONTRACT_CSV.name, index=False)

    payload = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "cycle": "C2",
        "source": "Energy-Charts (Fraunhofer ISE) /price endpoint",
        "licence": cfg["sources"]["energy_charts"]["licence"],
        "attribution": cfg["sources"]["energy_charts"]["attribution"],
        "sealed_holdout_years": sorted(cfg["splits"]["holdout"]["years"]),
        "contracts": [
            "index is tz-aware UTC and strictly monotonic, no duplicate timestamps",
            "every fully-covered UTC day holds exactly 86400/resolution rows",
            "every fully-covered local day holds the DST-derived expected row count",
            "any deviation from a 24h local day falls on a tz-database transition date",
            "no gaps (missing intervals) anywhere in the stitched series",
            "no NaN prices",
            "the only permitted resolution change is 3600s -> 900s at the SDAC "
            "15-minute go-live instant (local midnight of "
            f"{cfg['structural_dates']['sdac_15min_golive']} in the zone's timezone)",
        ],
        "n_zones": len(reports),
        "n_zones_ok": sum(1 for r in reports if r.ok),
        "zones": [r.as_dict() for r in reports],
    }
    with (out_dir / CONTRACT_JSON.name).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    # The derived DST whitelist, as its own committed artefact: one row per
    # (zone, local date) that is not 24h long, over the cached years.
    dst_rows = []
    for report in reports:
        for day, hours in dst_transition_days(report.local_tz, report.years).items():
            dst_rows.append(
                {
                    "zone": report.zone,
                    "local_tz": report.local_tz,
                    "local_date": day.isoformat(),
                    "local_day_hours": hours,
                    "expected_hourly_rows": hours,
                    "direction": "spring forward" if hours == 23 else "fall back",
                }
            )
    dst = pd.DataFrame(dst_rows).sort_values(
        ["zone", "local_date"], ignore_index=True
    ) if dst_rows else pd.DataFrame(
        columns=["zone", "local_tz", "local_date", "local_day_hours",
                 "expected_hourly_rows", "direction"]
    )
    dst.to_csv(out_dir / DST_CSV.name, index=False)

    print(summary.to_string(index=False))
    print(f"\n{len(summary)} zones -> {out_dir / CONTRACT_CSV.name}")
    print(f"{' ' * 9} -> {out_dir / CONTRACT_JSON.name}")
    print(f"{len(dst)} DST rows -> {out_dir / DST_CSV.name}")

    failed = [r for r in reports if not r.ok]
    if failed:
        print("\nDATA CONTRACT VIOLATIONS:", file=sys.stderr)
        for report in failed:
            for line in report.violations:
                print(f"  FLAG {report.zone}: {line}", file=sys.stderr)
        return 1
    print("\nall data contracts hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
