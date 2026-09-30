"""The continuous UTC price series: stitching the per-year cache into one index.

C1 caches one file per ``(zone, year)``, and :func:`data.energy_charts.read_cached_year`
trims each to its UTC calendar year — which is right for a per-year manifest row
and *wrong* for a modelling series. Energy-Charts interprets the request window
in the zone's **local** time, so file ``Y`` covers UTC
``[Y-1-12-31T23:00Z, Y-12-31T22:00Z]`` for the CET/CEST zones in scope. Trimming
every file to its own UTC year would therefore leave a one-hour hole at every
single year boundary: ``Y-12-31T23:00Z`` belongs to file ``Y+1``, not file ``Y``.

So this module parses each cached file **untruncated**, concatenates, sorts and
de-duplicates on timestamp — exactly what NOTE C1-02 in ``PROGRESS.md`` requires.
It never reindexes and never fills: a missing hour stays missing and is reported
by :mod:`data.contracts`, because a silently filled gap is a modelling bug that
looks like clean data.

The sealed-holdout guard is applied per year before any file is opened, so a
stray sealed-year cache file cannot enter a series by accident.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data.config import load_data_config, load_zones, sealed_years
from data.energy_charts import PRICE_COLUMN, cache_path, cached_years, parse_payload
from data.holdout import assert_not_sealed


class PriceDataError(RuntimeError):
    """The cached files cannot be stitched into a single coherent series."""


@dataclass(frozen=True)
class StitchReport:
    """What stitching did, so a cycle can log it instead of trusting it."""

    zone: str
    years: tuple[int, ...]
    n_points: int
    n_duplicate_timestamps: int
    first_ts_utc: pd.Timestamp
    last_ts_utc: pd.Timestamp

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "years": list(self.years),
            "n_points": self.n_points,
            "n_duplicate_timestamps": self.n_duplicate_timestamps,
            "first_ts_utc": self.first_ts_utc.isoformat(),
            "last_ts_utc": self.last_ts_utc.isoformat(),
        }


def read_cached_file(
    zone_key: str, year: int, config: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Parse one cached ``(zone, year)`` file with **no** per-UTC-year truncation.

    Contrast :func:`data.energy_charts.read_cached_year`, which trims to the UTC
    calendar year and is what the manifest uses.
    """
    assert_not_sealed(year, f"load cached prices for {zone_key} {year}")
    path = cache_path(zone_key, year, config)
    if not path.exists():
        raise FileNotFoundError(f"no cached Energy-Charts price file at {path}")
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    frame = parse_payload(payload, f"cached {path}")
    frame.attrs["cache_path"] = str(path)
    frame.attrs["fetch_meta"] = payload.get("_fetch_meta", {})
    return frame


def load_zone_series(
    zone_key: str,
    years: list[int] | None = None,
    config: dict[str, Any] | None = None,
    utc_years_only: bool = False,
) -> pd.DataFrame:
    """One zone's day-ahead prices as a single sorted, unique, UTC-indexed frame.

    ``years`` selects which cache *files* to read (default: every cached year).
    Because of the local-time request window, reading files ``years`` yields UTC
    coverage running from ``min(years)-1-12-31T23:00Z``. Pass
    ``utc_years_only=True`` to trim the result to whole UTC years
    ``[min(years)-01-01T00:00Z, max(years)+1-01-01T00:00Z)``; note that this
    drops the leading partial day *and* cannot recover the final UTC hour of
    ``max(years)``, which lives only in the next (possibly sealed) file.

    Gaps are never filled. Duplicate timestamps are collapsed only when the two
    files agree on the price; a genuine disagreement raises.
    """
    cfg = config or load_data_config()
    if zone_key not in load_zones():
        raise PriceDataError(f"unknown zone key {zone_key!r}")

    available = cached_years(zone_key, cfg)
    if not available:
        raise PriceDataError(
            f"no cached price files for {zone_key} — run `python -m data.fetch_prices`"
        )
    wanted = sorted(set(available) & set(years)) if years is not None else available
    if years is not None:
        missing = sorted(set(years) - set(available))
        if missing:
            raise PriceDataError(
                f"{zone_key}: requested years {missing} are not cached "
                f"(cached: {available})"
            )
    if not wanted:
        raise PriceDataError(f"{zone_key}: no cached years among {years}")

    sealed = sealed_years(None).intersection(wanted)
    if sealed:  # belt and braces; read_cached_file also guards per year
        assert_not_sealed(sealed, f"stitch a price series for {zone_key}")

    frames = [read_cached_file(zone_key, year, cfg) for year in wanted]
    combined = pd.concat(frames).sort_index()

    duplicated = combined.index.duplicated(keep=False)
    n_dupes = int(combined.index.duplicated(keep="first").sum())
    if duplicated.any():
        clashing = combined.loc[duplicated].groupby(level=0)[PRICE_COLUMN].nunique(
            dropna=False
        )
        conflicts = clashing[clashing > 1]
        if len(conflicts):
            raise PriceDataError(
                f"{zone_key}: {len(conflicts)} timestamp(s) appear in more than one "
                f"cached file with different prices, e.g. "
                f"{conflicts.index[0].isoformat()} — refusing to pick one. "
                f"Delete and refetch the affected year deliberately."
            )
        combined = combined[~combined.index.duplicated(keep="first")]

    if utc_years_only:
        start = pd.Timestamp(year=min(wanted), month=1, day=1, tz="UTC")
        end = pd.Timestamp(year=max(wanted) + 1, month=1, day=1, tz="UTC")
        combined = combined.loc[(combined.index >= start) & (combined.index < end)]
        if combined.empty:
            raise PriceDataError(
                f"{zone_key}: nothing left after trimming to UTC years {wanted}"
            )

    if not combined.index.is_monotonic_increasing:
        raise PriceDataError(f"{zone_key}: stitched index is not monotonic increasing")

    report = StitchReport(
        zone=zone_key,
        years=tuple(wanted),
        n_points=int(len(combined)),
        n_duplicate_timestamps=n_dupes,
        first_ts_utc=combined.index[0],
        last_ts_utc=combined.index[-1],
    )
    combined.attrs["stitch_report"] = report
    combined.attrs["zone"] = zone_key
    combined.attrs["years"] = list(wanted)
    combined.index.name = "timestamp_utc"
    return combined


def load_panel(
    zone_keys: list[str] | None = None,
    years: list[int] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    """``{zone_key: stitched frame}`` for the requested zones, in config order."""
    cfg = config or load_data_config()
    keys = zone_keys or list(load_zones())
    return {key: load_zone_series(key, years, cfg) for key in keys}


def wide_prices(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """A ``timestamp_utc`` x zone price matrix from a panel. Outer join, no fill."""
    if not panel:
        raise PriceDataError("empty panel")
    wide = pd.DataFrame(
        {zone: frame[PRICE_COLUMN] for zone, frame in panel.items()}
    ).sort_index()
    wide.index.name = "timestamp_utc"
    return wide
