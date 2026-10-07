"""The committed exogenous manifest: what ENTSO-E gave us, and what shape it is.

The C7 counterpart to :mod:`data.manifest`. One row per
``(zone, document, series, year)``: counts at native resolution and after
hourly aggregation, coverage against the expected number of UTC intervals, gaps,
NaNs, MW summary stats, the count of negative values (a day-ahead load or
RES forecast must never be negative — a negative one is a source defect, not a
market feature like a negative price), a reproducible payload sha256, and the
declared ``leakage_status`` of the series.

Carrying ``leakage_status`` in the manifest is deliberate. The Art. 14 wind and
solar vintage is published *after* day-ahead gate closure (PLAN.md), so every
artefact that touches it should say so in a place a human reads. A column in the
committed CSV is harder to forget than a paragraph in a doc.

Like the price manifest this is a *description*, not a model input: nothing here
is fitted, and it is built only over non-sealed years (the loader it calls
refuses sealed ones).

This module **adds to** the manifest layer rather than editing
:mod:`data.manifest`, which the C1 and C2 tests pin. Shared pieces
(:func:`data.manifest.git_sha`, ``MANIFEST_DIR``) are imported, not copied.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data.config import config_hash, load_data_config, load_zones
from data.contracts import modal_resolution_seconds
from data.entsoe import (
    cached_years,
    document_spec,
    load_documents,
    meta_path,
    read_cached_year,
)
from data.exogenous import column_leakage_status
from data.manifest import MANIFEST_DIR, git_sha

EXOG_MANIFEST_CSV = MANIFEST_DIR / "exogenous_manifest.csv"
EXOG_MANIFEST_JSON = MANIFEST_DIR / "exogenous_manifest.json"

COLUMNS = [
    "zone",
    "tier",
    "entsoe_domain",
    "document",
    "document_type",
    "process_type",
    "series",
    "leakage_status",
    "year",
    "n_points_native",
    "n_expected_native",
    "coverage_ratio",
    "covered_seconds",
    "year_seconds",
    "resolution_seconds",
    "resolutions_seconds",
    "n_distinct_deltas",
    "n_gap_intervals",
    "max_gap_hours",
    "n_nan",
    "n_out_of_window_dropped",
    "n_hours_after_aggregation",
    "n_expected_hours",
    "first_ts_utc",
    "last_ts_utc",
    "mw_min",
    "mw_p01",
    "mw_mean",
    "mw_median",
    "mw_p99",
    "mw_max",
    "mw_std",
    "n_negative",
    "n_zero",
    "gzip_bytes",
    "payload_sha256",
    "fetched_at_utc",
    "api_url_redacted",
]


def expected_intervals(year: int, resolution_seconds: int) -> int:
    """Intervals in a UTC calendar year at a given resolution.

    UTC years have no DST discontinuity, so this is exact. Unlike the price
    manifest's equivalent, ENTSO-E's request window is already UTC, so a full
    year's file should hit this number exactly.
    """
    if resolution_seconds <= 0:
        raise ValueError(f"resolution_seconds must be positive, got {resolution_seconds}")
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    span = int((end - start).total_seconds())
    if span % resolution_seconds:
        raise ValueError(
            f"{year} spans {span}s, not a whole multiple of {resolution_seconds}s"
        )
    return span // resolution_seconds


def series_fingerprint(frame: pd.DataFrame, column: str) -> str:
    """A reproducible sha256 over the ``(UTC epoch, value)`` pairs themselves.

    The same idea as :func:`data.contracts.payload_fingerprint`, and for the
    same reason (PROGRESS.md NOTE C2-01): hashing the cached *file* would mean
    hashing the ``fetched_at_utc`` stamp too, so the column would change on
    every re-fetch even when the data was identical. Kept as its own function
    because the exogenous frames are multi-column and this hashes exactly one.
    """
    digest = hashlib.sha256()
    epochs = (frame.index.view("int64") // 1_000_000_000).astype("int64")
    for epoch, value in zip(epochs, frame[column].to_numpy(dtype="float64")):
        digest.update(f"{int(epoch)},{value:.6f}\n".encode("ascii"))
    return digest.hexdigest()


def _round(value: Any, digits: int = 3) -> float | None:
    """Round for the committed manifest; None for missing, so CSV/JSON agree."""
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(as_float) else round(as_float, digits)


def summarise_series(
    zone_key: str,
    document_key: str,
    year: int,
    config: dict[str, Any] | None = None,
) -> list[dict]:
    """One manifest row per configured series in one cached (zone, document, year)."""
    cfg = config or load_data_config()
    zone = load_zones()[zone_key]
    spec = document_spec(document_key, cfg)
    frame = read_cached_year(zone_key, document_key, year, cfg)
    meta = frame.attrs.get("fetch_meta", {})
    path = meta_path(zone_key, document_key, year, cfg)

    deltas = pd.Series(frame.index).diff().dropna()
    delta_seconds = (
        deltas.dt.total_seconds().astype("int64")
        if not deltas.empty
        else pd.Series([], dtype="int64")
    )
    intervals_raw = frame.attrs.get("interval_seconds") or ()
    if delta_seconds.empty:
        resolution, n_gaps, max_gap_hours, n_distinct = 3600, 0, 0.0, 0
    else:
        resolution = int(modal_resolution_seconds(frame.index))
        n_distinct = int(delta_seconds.nunique())
        # A gap is a step longer than the *preceding row's own* interval, not
        # longer than the modal one. Against the modal resolution, every hourly
        # step in ES 2022's PT60M first half looked like a 3-interval gap and
        # the year reported 3409 "gaps" where it has one real missing hour.
        own = (
            pd.Series(intervals_raw[:-1], dtype="int64")
            if len(intervals_raw) == len(frame)
            else pd.Series(resolution, index=range(len(delta_seconds)), dtype="int64")
        )
        overrun = delta_seconds.reset_index(drop=True) - own.reset_index(drop=True)
        n_gaps = int((overrun > 0).sum())
        max_gap_hours = float(max(overrun.max(), 0)) / 3600.0

    # Coverage is measured in *time*, not in rows, because a TSO can change
    # resolution mid-year: ES published these documents at PT60M until
    # 2022-05-23 and at PT15M after. Counting rows against the modal resolution
    # made ES 2022 read as 70.8% covered when in fact barely an hour is missing
    # — the hourly half of the year simply has a quarter as many rows per hour.
    # Summing each row's own declared interval length is resolution-agnostic and
    # exact. `n_points_native` and `resolution_seconds` stay as descriptors.
    intervals = frame.attrs.get("interval_seconds") or ()
    covered_seconds = int(sum(intervals))
    year_seconds = expected_intervals(year, 1)
    n_expected = expected_intervals(year, resolution)
    resolution_runs = sorted({int(v) for v in intervals})
    gzip_bytes = int(meta.get("gzip_bytes") or 0)
    if not gzip_bytes and path.exists():
        gzip_bytes = int(path.with_suffix("").with_suffix(".xml.gz").stat().st_size)

    rows = []
    for column in frame.columns:
        values = frame[column]
        finite = values.dropna()
        rows.append(
            {
                "zone": zone_key,
                "tier": zone.tier,
                "entsoe_domain": zone.entsoe_domain,
                "document": document_key,
                "document_type": spec.document_type,
                "process_type": spec.process_type,
                "series": column,
                "leakage_status": column_leakage_status(column, cfg),
                "year": year,
                "n_points_native": int(len(frame)),
                "n_expected_native": n_expected,
                # Time covered / time in the year — see summarise_series.
                "coverage_ratio": round(covered_seconds / year_seconds, 6),
                "covered_seconds": covered_seconds,
                "year_seconds": year_seconds,
                "resolution_seconds": resolution,
                "resolutions_seconds": "|".join(str(v) for v in resolution_runs),
                "n_distinct_deltas": n_distinct,
                "n_gap_intervals": n_gaps,
                "max_gap_hours": round(max_gap_hours, 3),
                "n_nan": int(values.isna().sum()),
                "n_out_of_window_dropped": int(frame.attrs.get("n_out_of_window", 0)),
                "n_hours_after_aggregation": int(
                    pd.Series(frame.index).dt.floor("h").nunique()
                ),
                "n_expected_hours": expected_intervals(year, 3600),
                "first_ts_utc": frame.index[0].isoformat(),
                "last_ts_utc": frame.index[-1].isoformat(),
                "mw_min": _round(finite.min() if len(finite) else np.nan),
                "mw_p01": _round(np.nanpercentile(finite, 1) if len(finite) else np.nan),
                "mw_mean": _round(finite.mean() if len(finite) else np.nan),
                "mw_median": _round(finite.median() if len(finite) else np.nan),
                "mw_p99": _round(np.nanpercentile(finite, 99) if len(finite) else np.nan),
                "mw_max": _round(finite.max() if len(finite) else np.nan),
                "mw_std": _round(finite.std() if len(finite) else np.nan),
                "n_negative": int((finite < 0).sum()),
                "n_zero": int((finite == 0).sum()),
                "gzip_bytes": gzip_bytes,
                "payload_sha256": series_fingerprint(frame, column),
                "fetched_at_utc": meta.get("fetched_at_utc", ""),
                "api_url_redacted": meta.get("url_redacted", ""),
            }
        )
    return rows


def build_exog_manifest(
    zone_keys: list[str] | None = None,
    document_keys: list[str] | None = None,
    years: list[int] | None = None,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Manifest rows for every cached (zone, document, year) among those requested."""
    cfg = config or load_data_config()
    zones = zone_keys or [k for k, z in load_zones().items() if z.tier == "A"]
    documents = document_keys or list(load_documents(cfg))
    rows: list[dict] = []
    for zone_key in zones:
        for document_key in documents:
            available = cached_years(zone_key, document_key, cfg)
            wanted = sorted(set(available) & set(years)) if years else available
            for year in wanted:
                rows.extend(summarise_series(zone_key, document_key, year, cfg))
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return frame.sort_values(
        ["zone", "document", "series", "year"], ignore_index=True
    )


def write_exog_manifest(
    frame: pd.DataFrame,
    manifest_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write the exogenous manifest CSV (human-readable) and JSON (with provenance)."""
    cfg = config or load_data_config()
    directory = manifest_dir or MANIFEST_DIR
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / EXOG_MANIFEST_CSV.name
    json_path = directory / EXOG_MANIFEST_JSON.name

    frame.to_csv(csv_path, index=False)
    documents = load_documents(cfg)
    provenance = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "cycle": "C7",
        "source": "ENTSO-E Transparency Platform (web-api.tp.entsoe.eu)",
        "licence": cfg["sources"]["entsoe"]["licence"],
        "attribution": cfg["sources"]["entsoe"]["attribution"],
        "sealed_holdout_years": sorted(cfg["splits"]["holdout"]["years"]),
        "exogenous_available_from_year": int(
            cfg["sources"]["entsoe"]["exogenous_available_from_year"]
        ),
        "documents": {
            key: {
                "document_type": spec.document_type,
                "process_type": spec.process_type,
                "title": spec.title,
                "leakage_status": spec.leakage_status,
                "leakage_note": spec.leakage_note,
                "series": {s.name: list(s.psr_types) for s in spec.series},
            }
            for key, spec in documents.items()
        },
        "note": (
            "One row per (zone, document, series, calendar year) of cached "
            "ENTSO-E day-ahead forecasts, at the source's native resolution. "
            "Tier-A zones only (PLAN.md). Sealed-holdout years are absent by "
            "construction: the loader refuses them until PROGRESS.md records "
            "Checkpoint C approval. The security token appears nowhere — "
            "api_url_redacted carries securityToken=<REDACTED>."
        ),
        "n_rows": int(len(frame)),
        "rows": json.loads(frame.to_json(orient="records")),
    }
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2, sort_keys=False)
        fh.write("\n")
    return csv_path, json_path
