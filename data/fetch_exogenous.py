"""CLI: fetch the Tier-A ENTSO-E day-ahead forecasts into the cache.

    python -m data.fetch_exogenous                      # Tier A, 2022-2024, both documents
    python -m data.fetch_exogenous --dry-run
    python -m data.fetch_exogenous --zones DE-LU --documents load_forecast_da

Already-cached (zone, document, year) triples are skipped without a request —
there is no force-refetch flag by design (CLAUDE.md: never re-download cached
data; ENTSO-E throttles abusive tokens). Sealed-holdout years are refused by
:mod:`data.holdout` before any request, and 2019-2021 are refused because no
archived D-1 forecast vintage exists there (PLAN.md).

Tier A only: PLAN.md gives exogenous features to DE-LU, ES and NO2 and keeps
Tier B on price history alone. ``--zones`` can name a Tier-B zone explicitly,
which is how a later cycle would widen the scope deliberately rather than by
accident.

If ``ENTSOE_API_KEY`` is not set, this prints one FLAG line and exits 4 without
making a request — per CLAUDE.md the cycle then continues with whatever does not
depend on it rather than blocking.

A 404 / Acknowledgement / schema-violating response for one triple is reported
as a FLAG, that triple is skipped, the remaining ones still run, and the process
exits non-zero so a cycle cannot mistake a partial pull for a complete one.
Copy the FLAG lines into PROGRESS.md.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

from data.config import load_data_config, load_zones
from data.entsoe import (
    FetchFailed,
    MissingCredential,
    UnexpectedResponse,
    api_key_is_set,
    cache_path,
    exogenous_years,
    load_documents,
    redact,
)
from data.holdout import SealedHoldoutError
from data.manifest import MANIFEST_DIR

FAILURES_PATH = MANIFEST_DIR / "exogenous_fetch_failures.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None,
                        help="zone keys (default: every Tier-A zone)")
    parser.add_argument("--documents", nargs="*", default=None,
                        help="document keys (default: all configured)")
    parser.add_argument("--years", nargs="*", type=int, default=None,
                        help="calendar years (default: config exogenous years)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list the (zone, document, year) triples that would be requested")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_data_config()
    zones = load_zones()
    documents = load_documents(cfg)

    selected = args.zones or [k for k, z in zones.items() if z.tier == "A"]
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}; known: {sorted(zones)}", file=sys.stderr)
        return 2

    doc_keys = args.documents or list(documents)
    unknown_docs = [d for d in doc_keys if d not in documents]
    if unknown_docs:
        print(f"unknown document key(s): {unknown_docs}; known: {sorted(documents)}",
              file=sys.stderr)
        return 2

    allowed = exogenous_years(cfg)
    years = args.years or allowed
    out_of_scope = sorted(set(years) - set(allowed))
    if out_of_scope:
        print(f"years {out_of_scope} are outside the declared exogenous window "
              f"{allowed} — refusing (PLAN.md: no archived D-1 forecast vintage "
              f"before {min(allowed)}, and sealed years are never fetched)",
              file=sys.stderr)
        return 2

    print(f"zones={selected}\ndocuments={doc_keys}\nyears={years}\n")
    for key in doc_keys:
        spec = documents[key]
        print(f"  {key}: {spec.document_type}/{spec.process_type} — {spec.title}")
        print(f"      leakage_status={spec.leakage_status}; columns={spec.column_names}")
    print()

    if args.dry_run:
        for zone_key in selected:
            for document_key in doc_keys:
                for year in years:
                    cached = cache_path(zone_key, document_key, year, cfg).exists()
                    state = "cached, no request" if cached else "would fetch"
                    print(f"  {state:22s} {zone_key} {document_key} {year}")
        return 0

    if not api_key_is_set(cfg):
        var = cfg["sources"]["entsoe"]["key_env_var"]
        print(f"  FLAG  {var} is not set — no ENTSO-E request made. Per CLAUDE.md, "
              f"record this in PROGRESS.md and continue with Tier-B / "
              f"Energy-Charts-only work rather than blocking the cycle.",
              file=sys.stderr)
        return 4

    downloaded, skipped = 0, 0
    failures: list[dict[str, str]] = []

    with requests.Session() as session:
        session.headers.update({"Accept": "application/xml"})
        # Imported lazily so --dry-run and the missing-key path never need the token.
        from data.entsoe import fetch_year

        for zone_key in selected:
            for document_key in doc_keys:
                for year in years:
                    label = f"{zone_key} {document_key} {year}"
                    try:
                        path, was_downloaded = fetch_year(
                            zone_key, document_key, year, cfg, session=session
                        )
                    except (
                        UnexpectedResponse,
                        FetchFailed,
                        SealedHoldoutError,
                        MissingCredential,
                    ) as exc:
                        kind = type(exc).__name__
                        message = redact(str(exc))
                        print(f"  FLAG  {label}: {kind}: {message}", file=sys.stderr)
                        failures.append({
                            "zone": zone_key,
                            "document": document_key,
                            "year": str(year),
                            "error_type": kind,
                            "message": message,
                        })
                        continue
                    if was_downloaded:
                        downloaded += 1
                        size_mb = path.stat().st_size / 1e6
                        print(f"  fetched      {label}  -> {path}  ({size_mb:.1f} MB gz)")
                    else:
                        skipped += 1
                        print(f"  cached       {label}  (no request made)")

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
