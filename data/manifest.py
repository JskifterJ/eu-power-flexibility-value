"""The committed data manifest: what was fetched, and what shape it is.

The manifest is the artefact a human eyeballs at Checkpoint A (C2) and the thing
that makes "never re-download cached data" and "notice when a source changes
under you" mechanical rather than remembered. One row per (zone, year):
counts, coverage against the expected number of intervals, price summary stats,
negative-hour count, and the sha256 of the raw cached file.

It is a *description*, not a model input — nothing here is fitted, and it is
built only over non-sealed years (the loader it calls refuses sealed ones).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data.config import REPO_ROOT, config_hash, load_data_config, load_zones
from data.energy_charts import (
    PRICE_COLUMN,
    cache_path,
    cached_years,
    read_cached_year,
    sha256_file,
)

MANIFEST_DIR = REPO_ROOT / "data" / "manifest"
MANIFEST_CSV = MANIFEST_DIR / "prices_manifest.csv"
MANIFEST_JSON = MANIFEST_DIR / "prices_manifest.json"

COLUMNS = [
    "zone",
    "tier",
    "bzn",
    "year",
    "n_points",
    "n_expected_points",
    "coverage_ratio",
    "resolution_seconds",
    "n_distinct_deltas",
    "n_gap_intervals",
    "max_gap_hours",
    "n_nan",
    "n_out_of_window_dropped",
    "first_ts_utc",
    "last_ts_utc",
    "price_min",
    "price_p01",
    "price_mean",
    "price_median",
    "price_p99",
    "price_max",
    "price_std",
    "n_negative",
    "n_zero",
    "raw_bytes",
    "raw_sha256",
    "fetched_at_utc",
    "api_url",
]


def git_sha(repo_root: Path | None = None) -> str:
    """Short git SHA of the working tree's HEAD, or 'unknown' outside a repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root or REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def expected_points(year: int, resolution_seconds: int) -> int:
    """Intervals in a UTC calendar year at a given resolution.

    UTC years have no DST discontinuity, so this is exact: 8760 hourly intervals,
    8784 in a leap year. Local-clock 23h/25h days are a feature/presentation
    concern handled by the DST whitelist in the C2 contract tests, never by
    reindexing here.
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


def summarise_year(zone_key: str, year: int, config: dict[str, Any] | None = None) -> dict:
    """One manifest row for one cached (zone, year)."""
    cfg = config or load_data_config()
    zone = load_zones()[zone_key]
    frame = read_cached_year(zone_key, year, cfg)
    path = cache_path(zone_key, year, cfg)
    prices = frame[PRICE_COLUMN]

    deltas = pd.Series(frame.index).diff().dropna()
    delta_seconds = (deltas.dt.total_seconds().astype("int64")
                     if not deltas.empty else pd.Series([], dtype="int64"))
    if delta_seconds.empty:
        resolution = 3600  # single point: assume hourly, coverage will show it
        n_gaps, max_gap_hours, n_distinct = 0, 0.0, 0
    else:
        resolution = int(delta_seconds.mode().iloc[0])
        n_distinct = int(delta_seconds.nunique())
        n_gaps = int((delta_seconds > resolution).sum())
        max_gap_hours = float(delta_seconds.max()) / 3600.0

    finite = prices.dropna()
    meta = frame.attrs.get("fetch_meta", {})
    n_expected = expected_points(year, resolution)

    return {
        "zone": zone_key,
        "tier": zone.tier,
        "bzn": zone.bzn,
        "year": year,
        "n_points": int(len(frame)),
        "n_expected_points": n_expected,
        "coverage_ratio": round(len(frame) / n_expected, 6),
        "resolution_seconds": resolution,
        "n_distinct_deltas": n_distinct,
        "n_gap_intervals": n_gaps,
        "max_gap_hours": round(max_gap_hours, 3),
        "n_nan": int(prices.isna().sum()),
        "n_out_of_window_dropped": int(frame.attrs.get("n_out_of_window", 0)),
        "first_ts_utc": frame.index[0].isoformat(),
        "last_ts_utc": frame.index[-1].isoformat(),
        "price_min": _round(finite.min()),
        "price_p01": _round(np.nanpercentile(finite, 1) if len(finite) else np.nan),
        "price_mean": _round(finite.mean()),
        "price_median": _round(finite.median()),
        "price_p99": _round(np.nanpercentile(finite, 99) if len(finite) else np.nan),
        "price_max": _round(finite.max()),
        "price_std": _round(finite.std()),
        "n_negative": int((finite < 0).sum()),
        "n_zero": int((finite == 0).sum()),
        "raw_bytes": path.stat().st_size,
        "raw_sha256": sha256_file(path),
        "fetched_at_utc": meta.get("fetched_at_utc", ""),
        "api_url": meta.get("url", ""),
    }


def _round(value: Any, digits: int = 3) -> float | None:
    """Round for the committed manifest; None for missing, so CSV/JSON agree."""
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(as_float) else round(as_float, digits)


def build_manifest(
    zone_keys: list[str] | None = None,
    years: list[int] | None = None,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Manifest rows for every cached (zone, year) among those requested."""
    cfg = config or load_data_config()
    zones = zone_keys or list(load_zones())
    rows = []
    for zone_key in zones:
        available = cached_years(zone_key, cfg)
        wanted = sorted(set(available) & set(years)) if years else available
        for year in wanted:
            rows.append(summarise_year(zone_key, year, cfg))
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return frame.sort_values(["zone", "year"], ignore_index=True)


def write_manifest(
    frame: pd.DataFrame,
    manifest_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write the manifest CSV (human-readable) and JSON (with provenance)."""
    cfg = config or load_data_config()
    directory = manifest_dir or MANIFEST_DIR
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / MANIFEST_CSV.name
    json_path = directory / MANIFEST_JSON.name

    frame.to_csv(csv_path, index=False)
    provenance = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "source": "Energy-Charts (Fraunhofer ISE) /price endpoint",
        "licence": cfg["sources"]["energy_charts"]["licence"],
        "attribution": cfg["sources"]["energy_charts"]["attribution"],
        "sealed_holdout_years": sorted(cfg["splits"]["holdout"]["years"]),
        "note": (
            "One row per (zone, calendar year) of cached day-ahead prices. "
            "Sealed-holdout years are absent by construction: the loader refuses "
            "them until PROGRESS.md records Checkpoint C approval."
        ),
        "n_rows": int(len(frame)),
        "rows": json.loads(frame.to_json(orient="records")),
    }
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2, sort_keys=False)
        fh.write("\n")
    return csv_path, json_path
