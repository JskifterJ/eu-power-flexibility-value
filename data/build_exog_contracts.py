"""CLI: run the C7 exogenous contracts over every cached Tier-A zone.

    python -m data.build_exog_contracts
    python -m data.build_exog_contracts --zones DE-LU NO2

Reads only the local cache — never the network. Writes

    data/manifest/exogenous_contract_report.csv    one row per (zone, series)
    data/manifest/exogenous_contract_report.json   full detail incl. every finding

Exit codes: 0 all contracts hold; 1 at least one violation (the report still
gets written — a violation is evidence, not a reason to write nothing);
3 nothing cached.

Note on what counts as a violation here, versus the C2 price contract: gaps and
NaNs are reported in ``notes`` rather than failed. These forecast series are
genuinely ragged at DST boundaries and PLAN.md's answer to a source gap is to
report it and skip the dependent work, not to throw away a training year. A
negative MW forecast, a duplicate timestamp, a non-UTC index or a bad day count
*is* a violation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from data.config import config_hash, load_data_config, load_zones
from data.entsoe import cached_years, load_documents
from data.exog_contracts import build_exog_contract_report
from data.exogenous import RESIDUAL_LOAD_COLUMN, load_zone_exogenous
from data.manifest import MANIFEST_DIR, git_sha

CONTRACT_CSV = MANIFEST_DIR / "exogenous_contract_report.csv"
CONTRACT_JSON = MANIFEST_DIR / "exogenous_contract_report.json"

SUMMARY_COLUMNS = [
    "zone", "tier", "series", "document", "leakage_status", "n_points",
    "first_ts_utc", "last_ts_utc", "modal_resolution_seconds", "payload_sha256",
    "index_is_utc", "index_is_monotonic", "n_duplicate_timestamps", "n_nan_values",
    "n_negative_values", "is_constant", "mw_min", "mw_max", "n_missing_intervals",
    "max_gap_hours", "n_utc_days_checked", "n_utc_day_violations",
    "n_local_days_checked", "n_local_day_violations", "n_dst_days_seen",
    "n_resolution_changes", "n_partial_psr_intervals", "n_notes", "n_violations",
    "ok",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None)
    parser.add_argument("--years", nargs="*", type=int, default=None)
    parser.add_argument("--manifest-dir", default=None,
                        help="override the output directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_data_config()
    zones = load_zones()
    documents = load_documents(cfg)
    out_dir = Path(args.manifest_dir) if args.manifest_dir else MANIFEST_DIR

    selected = args.zones or [k for k, z in zones.items() if z.tier == "A"]
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}", file=sys.stderr)
        return 2

    if sum(len(cached_years(z, d, cfg)) for z in selected for d in documents) == 0:
        print("no cached ENTSO-E documents found — run "
              "`python -m data.fetch_exogenous` first.", file=sys.stderr)
        return 3

    reports = []
    for zone_key in selected:
        if not any(cached_years(zone_key, d, cfg) for d in documents):
            print(f"FLAG {zone_key}: nothing cached, skipped", file=sys.stderr)
            continue
        # on_partial="flag" keeps a partially-covered hour as NaN instead of
        # raising: for this source a ragged hour is a finding to report, which
        # is exactly what this CLI exists to do.
        frame = load_zone_exogenous(
            zone_key, args.years, cfg, hourly=True, on_partial="flag"
        )
        for series in frame.columns:
            reports.append(
                build_exog_contract_report(zone_key, series, frame, cfg)
            )

    rows = [
        {
            "zone": r.zone,
            "tier": r.tier,
            "series": r.series,
            "document": r.document,
            "leakage_status": r.leakage_status,
            "n_points": r.n_points,
            "first_ts_utc": r.first_ts_utc,
            "last_ts_utc": r.last_ts_utc,
            "modal_resolution_seconds": r.modal_resolution_seconds,
            "payload_sha256": r.payload_sha256,
            "index_is_utc": r.index_is_utc,
            "index_is_monotonic": r.index_is_monotonic,
            "n_duplicate_timestamps": r.n_duplicate_timestamps,
            "n_nan_values": r.n_nan_values,
            "n_negative_values": r.n_negative_values,
            "is_constant": r.is_constant,
            "mw_min": r.mw_min,
            "mw_max": r.mw_max,
            "n_missing_intervals": r.n_missing_intervals,
            "max_gap_hours": r.max_gap_hours,
            "n_utc_days_checked": r.n_utc_days_checked,
            "n_utc_day_violations": len(r.utc_day_violations),
            "n_local_days_checked": r.n_local_days_checked,
            "n_local_day_violations": len(r.local_day_violations),
            "n_dst_days_seen": r.n_dst_days_seen,
            "n_resolution_changes": len(r.resolution_changes),
            "n_partial_psr_intervals": r.n_partial_psr_intervals,
            "n_notes": len(r.notes),
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
        "cycle": "C7",
        "source": "ENTSO-E Transparency Platform (web-api.tp.entsoe.eu)",
        "licence": cfg["sources"]["entsoe"]["licence"],
        "attribution": cfg["sources"]["entsoe"]["attribution"],
        "sealed_holdout_years": sorted(cfg["splits"]["holdout"]["years"]),
        "series_resolution": "hourly (UTC), aggregated per data/aggregate.py",
        "contracts": [
            "index is tz-aware UTC and strictly monotonic, no duplicate timestamps",
            "every fully-covered UTC day holds exactly 86400/resolution rows",
            "every fully-covered local day holds the DST-derived expected row count",
            "any deviation from a 24h local day falls on a tz-database transition date",
            "no negative value in a MW load / wind / solar day-ahead forecast",
        ],
        "reported_but_not_failed": [
            "gaps (missing intervals) — the source is genuinely ragged at DST "
            "boundaries; PLAN.md's answer to a source gap is to report it and skip "
            "the dependent work, not to discard a training year",
            "NaN values — an interval covered by only some of the summed psrTypes, "
            "kept NaN rather than partially summed",
            "resolution changes — the SDAC 15-minute cutover rule applies to the "
            "day-ahead price series, not to a TSO's own forecast publication",
            "a constant series — real for a zone with no such fleet (NO2 solar)",
        ],
        "leakage": {
            key: {
                "document_type": spec.document_type,
                "leakage_status": spec.leakage_status,
                "leakage_note": spec.leakage_note,
            }
            for key, spec in documents.items()
        }
        | {
            RESIDUAL_LOAD_COLUMN: {
                "document_type": "derived",
                "leakage_status": "FLAGGED",
                "leakage_note": (
                    "load - wind - solar; FLAGGED by inheritance because two of "
                    "its three inputs are the Art. 14 post-gate-closure vintage."
                ),
            }
        },
        "n_series": len(reports),
        "n_series_ok": sum(1 for r in reports if r.ok),
        "series": [r.as_dict() for r in reports],
    }
    with (out_dir / CONTRACT_JSON.name).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    print(summary.drop(columns=["payload_sha256", "first_ts_utc", "last_ts_utc"])
          .to_string(index=False))
    print(f"\n{len(summary)} series -> {out_dir / CONTRACT_CSV.name}")
    print(f"{' ' * 11} -> {out_dir / CONTRACT_JSON.name}")

    noted = [r for r in reports if r.notes]
    if noted:
        print("\nNOTES (reported, not failures):")
        for report in noted:
            for line in report.notes:
                print(f"  note {report.zone}/{report.series}: {line}")

    failed = [r for r in reports if not r.ok]
    if failed:
        print("\nEXOGENOUS DATA CONTRACT VIOLATIONS:", file=sys.stderr)
        for report in failed:
            for line in report.violations:
                print(f"  FLAG {report.zone}/{report.series}: {line}", file=sys.stderr)
        return 1
    print("\nall exogenous data contracts hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
