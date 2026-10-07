"""The continuous UTC exogenous series: stitching, then hourly aggregation.

Tier-A only (PLAN.md): DE-LU, ES, NO2. Three columns, from two ENTSO-E
documents — ``load_forecast_da_mw`` (A65, safe), ``wind_forecast_da_mw`` and
``solar_forecast_da_mw`` (A69, **FLAGGED**) — plus the derived
``residual_load_forecast_mw`` that ``config/features.yaml`` declares and the C14
fundamentals chapter needs.

Two differences from :mod:`data.prices`, both consequences of the source rather
than choices:

* **No year-boundary hole.** Energy-Charts interprets its request window in the
  zone's *local* time, so its file ``Y`` straddles UTC years and the final UTC
  hour of ``Y`` lives only in file ``Y+1`` (see :mod:`data.prices`). ENTSO-E's
  ``periodStart``/``periodEnd`` are UTC, so each cached year covers exactly its
  UTC calendar year and the files butt up against each other exactly.
* **Native resolution is sub-hourly for two of the three zones.** DE-LU and ES
  publish both documents at PT15M, NO2 at PT60M. The main backtest is hourly, so
  these are aggregated by :mod:`data.aggregate`'s one documented method — the
  unweighted mean of the sub-hourly values in each UTC hour, which for an
  equal-duration MW quantity is the correct average power over the hour. The raw
  cache keeps native resolution; aggregation happens here and is reported on
  ``frame.attrs['aggregation_reports']`` so a later cycle can see what it got.

Nothing is reindexed or filled. A gap stays a gap and is reported by
:mod:`data.exog_contracts`; a partial hour is never quietly averaged (that is
:func:`data.aggregate.to_hourly`'s own refusal).

**The FLAGGED status travels with the data.** Any frame containing a column from
the A69 document carries ``frame.attrs['leakage_status'] == 'FLAGGED'`` and
``frame.attrs['flagged_columns']``. C8 must not build these into a model without
the degradation sensitivity PLAN.md requires; this attribute is how a later
cycle notices rather than remembers.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from data.aggregate import to_hourly
from data.config import load_data_config, load_zones, sealed_years
from data.contracts import DataContractViolation
from data.entsoe import (
    cache_path,
    cached_years,
    document_spec,
    load_documents,
    meta_path,
    parse_document,
    series_owner,
)
from data.holdout import assert_not_sealed

RESIDUAL_LOAD_COLUMN = "residual_load_forecast_mw"
LOAD_COLUMN = "load_forecast_da_mw"
WIND_COLUMN = "wind_forecast_da_mw"
SOLAR_COLUMN = "solar_forecast_da_mw"


class ExogenousDataError(RuntimeError):
    """The cached documents cannot be stitched into a single coherent series."""


@dataclass(frozen=True)
class ExogenousStitchReport:
    """What stitching did, so a cycle can log it instead of trusting it."""

    zone: str
    document: str
    years: tuple[int, ...]
    columns: tuple[str, ...]
    n_points_native: int
    n_duplicate_timestamps: int
    native_resolutions_seconds: tuple[int, ...]
    first_ts_utc: str
    last_ts_utc: str
    n_points_hourly: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "document": self.document,
            "years": list(self.years),
            "columns": list(self.columns),
            "n_points_native": self.n_points_native,
            "n_duplicate_timestamps": self.n_duplicate_timestamps,
            "native_resolutions_seconds": list(self.native_resolutions_seconds),
            "first_ts_utc": self.first_ts_utc,
            "last_ts_utc": self.last_ts_utc,
            "n_points_hourly": self.n_points_hourly,
        }


def read_cached_file(
    zone_key: str,
    document_key: str,
    year: int,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Parse one cached document with **no** per-UTC-year truncation.

    Contrast :func:`data.entsoe.read_cached_year`, which trims to the UTC
    calendar year and is what the exogenous manifest uses.
    """
    cfg = config or load_data_config()
    assert_not_sealed(
        year, f"load cached ENTSO-E {document_key} for {zone_key} {year}"
    )
    path = cache_path(zone_key, document_key, year, cfg)
    if not path.exists():
        raise FileNotFoundError(f"no cached ENTSO-E document at {path}")
    with gzip.open(path, "rb") as fh:
        body = fh.read()
    frame = parse_document(body, document_key, f"cached {path}", cfg)
    frame.attrs["cache_path"] = str(path)
    sidecar = meta_path(zone_key, document_key, year, cfg)
    frame.attrs["cache_meta_path"] = str(sidecar) if sidecar.exists() else ""
    return frame


def _stitch_intervals(
    frames: list[pd.DataFrame],
    index: pd.DatetimeIndex,
    zone_key: str,
    document_key: str,
) -> pd.Series:
    """Per-row interval length for the stitched series, from the parsed Periods.

    Each cached year carries its rows' true resolutions on
    ``attrs['interval_seconds']`` (see :mod:`data.entsoe`); this lines them up
    with the de-duplicated stitched index.
    """
    pieces = [
        pd.Series(f.attrs["interval_seconds"], index=f.index, dtype="int64")
        for f in frames
        if f.attrs.get("interval_seconds")
    ]
    if not pieces:
        raise ExogenousDataError(
            f"{zone_key}/{document_key}: no interval lengths on the parsed frames — "
            f"hourly aggregation cannot tell a resolution change from a gap"
        )
    intervals = pd.concat(pieces).sort_index()
    intervals = intervals[~intervals.index.duplicated(keep="first")].reindex(index)
    if intervals.isna().any():
        missing = index[intervals.isna()]
        raise ExogenousDataError(
            f"{zone_key}/{document_key}: {len(missing)} stitched row(s) have no "
            f"interval length, first at {missing[0].isoformat()}"
        )
    return intervals.astype("int64")


def _aggregate_hourly(
    native: pd.DataFrame,
    intervals: pd.Series,
    on_partial: Literal["raise", "flag"],
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], int, int]:
    """Aggregate a possibly mixed-resolution native series to UTC hours.

    Two things make this more than a single :func:`data.aggregate.to_hourly`
    call, and both are live in this data:

    * **A TSO can change resolution mid-series.** ES published its day-ahead
      load and RES forecasts at PT60M until 2022-05-23T00:00Z and at PT15M
      after. :func:`~data.aggregate.to_hourly` documents a single input
      resolution and takes the modal one, so over the stitched series it would
      treat the whole PT60M stretch — 3408 hours of real data — as partial
      hours. So the series is split into maximal runs of constant resolution
      and each run is handed to ``to_hourly`` on its own, which is exactly the
      uniform input that function is specified for. ``data/aggregate.py`` is
      untouched: it holds the C2 aggregation method and its tests.
    * **An hour must tile exactly, and NaN is not a value.** An hour is kept
      only if its rows' interval lengths sum to 3600s *and* none of them is
      NaN. ``to_hourly`` means with pandas' default ``skipna``, so an hour with
      three real quarter-hours and one NaN would otherwise come back as the
      mean of the three — a number that looks real and is not. The honest
      reading of DE-LU's DST-day gap is that the hour is unknown, not
      three-quarters known.

    Returns ``(hourly frame, per-column aggregation reports, n hours masked for
    NaN, n hours masked for not tiling)``.
    """
    hour_key = native.index.floor("h")
    covered = intervals.groupby(hour_key).sum()
    incomplete_hours = covered[covered != 3600].index
    if len(incomplete_hours) and on_partial == "raise":
        raise DataContractViolation(
            f"{len(incomplete_hours)} UTC hour(s) are not tiled exactly by their "
            f"sub-hourly intervals, e.g. {incomplete_hours[0].isoformat()} with "
            f"{int(covered.loc[incomplete_hours[0]])}s of 3600s — refusing to "
            f"average a partial hour. Fix the gap, or pass on_partial='flag' to "
            f"keep it as NaN."
        )

    # Maximal runs of constant resolution; `to_hourly` is specified for one.
    run_id = (intervals != intervals.shift()).cumsum()
    columns: dict[str, pd.Series] = {}
    reports: dict[str, dict[str, Any]] = {}
    for column in native.columns:
        chunks = []
        for _, rows in native[[column]].groupby(run_id, sort=True):
            if len(rows) < 2:
                # `to_hourly` needs two rows to infer a resolution; a one-row
                # run is already its own hour at whatever length it declares,
                # and the tiling check above decides whether it survives.
                chunks.append(rows[column].groupby(rows.index.floor("h")).mean())
                continue
            reduced = to_hourly(rows, column=column, on_partial="flag")
            chunks.append(reduced[column])
            report = reduced.attrs.get("aggregation_report")
            if report is not None:
                reports.setdefault(column, report.as_dict())
        values = pd.concat(chunks).sort_index()
        values = values[~values.index.duplicated(keep="first")]

        nan_per_hour = native[column].isna().groupby(hour_key).sum()
        has_nan = nan_per_hour.reindex(values.index).fillna(0) > 0
        not_tiled = covered.reindex(values.index).fillna(0) != 3600
        columns[column] = values.mask(has_nan | not_tiled)

    out = pd.DataFrame(columns).sort_index()
    out.index.name = "timestamp_utc"
    n_nan_masked = int(
        sum(
            int((native[c].isna().groupby(hour_key).sum() > 0).sum())
            for c in native.columns
        )
    )
    return out, reports, n_nan_masked, int(len(incomplete_hours))


def load_zone_document(
    zone_key: str,
    document_key: str,
    years: list[int] | None = None,
    config: dict[str, Any] | None = None,
    hourly: bool = True,
    on_partial: Literal["raise", "flag"] = "raise",
) -> pd.DataFrame:
    """One zone's series from one document, stitched and (by default) hourly.

    ``years`` selects which cache files to read (default: every cached year).
    Duplicate timestamps across files are collapsed only when the files agree;
    a genuine disagreement raises rather than picking one.
    """
    cfg = config or load_data_config()
    if zone_key not in load_zones():
        raise ExogenousDataError(f"unknown zone key {zone_key!r}")
    spec = document_spec(document_key, cfg)

    available = cached_years(zone_key, document_key, cfg)
    if not available:
        raise ExogenousDataError(
            f"no cached ENTSO-E {document_key} for {zone_key} — run "
            f"`python -m data.fetch_exogenous`"
        )
    if years is not None:
        missing = sorted(set(years) - set(available))
        if missing:
            raise ExogenousDataError(
                f"{zone_key}/{document_key}: requested years {missing} are not "
                f"cached (cached: {available})"
            )
        wanted = sorted(set(available) & set(years))
    else:
        wanted = available
    if not wanted:
        raise ExogenousDataError(f"{zone_key}/{document_key}: no cached years among {years}")

    sealed = sealed_years(None).intersection(wanted)
    if sealed:  # belt and braces; read_cached_file also guards per year
        assert_not_sealed(sealed, f"stitch an exogenous series for {zone_key}")

    frames = [read_cached_file(zone_key, document_key, y, cfg) for y in wanted]
    resolutions = sorted(
        {s for f in frames for s in f.attrs.get("resolutions_seconds", [])}
    )
    combined = pd.concat(frames).sort_index()

    duplicated = combined.index.duplicated(keep=False)
    n_dupes = int(combined.index.duplicated(keep="first").sum())
    if duplicated.any():
        clashing = combined.loc[duplicated].groupby(level=0).nunique(dropna=False)
        conflicts = clashing[(clashing > 1).any(axis=1)]
        if len(conflicts):
            raise ExogenousDataError(
                f"{zone_key}/{document_key}: {len(conflicts)} timestamp(s) appear "
                f"in more than one cached file with different values, e.g. "
                f"{conflicts.index[0].isoformat()} — refusing to pick one. Delete "
                f"and refetch the affected year deliberately."
            )
        combined = combined[~combined.index.duplicated(keep="first")]

    if not combined.index.is_monotonic_increasing:
        raise ExogenousDataError(
            f"{zone_key}/{document_key}: stitched index is not monotonic increasing"
        )

    intervals = _stitch_intervals(frames, combined.index, zone_key, document_key)
    n_native = int(len(combined))
    aggregation_reports: dict[str, dict[str, Any]] = {}
    n_nan_masked_hours = 0
    n_incomplete_hours = 0
    if hourly:
        out, aggregation_reports, n_nan_masked_hours, n_incomplete_hours = (
            _aggregate_hourly(combined, intervals, on_partial)
        )
    else:
        out = combined
        out.attrs["interval_seconds"] = tuple(int(v) for v in intervals.to_numpy())

    out.attrs["zone"] = zone_key
    out.attrs["document_key"] = document_key
    out.attrs["document_type"] = spec.document_type
    out.attrs["process_type"] = spec.process_type
    out.attrs["leakage_status"] = spec.leakage_status
    out.attrs["leakage_note"] = spec.leakage_note
    out.attrs["flagged_columns"] = (
        list(out.columns) if spec.leakage_status.upper() == "FLAGGED" else []
    )
    out.attrs["years"] = list(wanted)
    out.attrs["native_resolutions_seconds"] = resolutions
    out.attrs["aggregation_reports"] = aggregation_reports
    out.attrs["hourly"] = hourly
    out.attrs["unit"] = "MW"
    out.attrs["n_nan_masked_hours"] = n_nan_masked_hours
    out.attrs["n_incomplete_hours"] = n_incomplete_hours
    out.attrs["n_partial_psr_intervals"] = sum(
        int(f.attrs.get("n_partial_psr_intervals", 0)) for f in frames
    )
    out.attrs["zero_components"] = {
        k: v
        for f in frames
        for k, v in (f.attrs.get("zero_components") or {}).items()
    }
    out.attrs["stitch_report"] = ExogenousStitchReport(
        zone=zone_key,
        document=document_key,
        years=tuple(wanted),
        columns=tuple(out.columns),
        n_points_native=n_native,
        n_duplicate_timestamps=n_dupes,
        native_resolutions_seconds=tuple(resolutions),
        first_ts_utc=out.index[0].isoformat(),
        last_ts_utc=out.index[-1].isoformat(),
        n_points_hourly=int(len(out)) if hourly else None,
    )
    return out


def add_residual_load(frame: pd.DataFrame) -> pd.DataFrame:
    """Append ``residual_load_forecast_mw`` = load - wind - solar.

    ``config/features.yaml`` declares this as a derived exogenous feature with
    ``leakage_status: FLAGGED``, because two of its three inputs are the Art. 14
    post-gate-closure vintage. It is computed here because it is a property of
    the loaded data, not of any model; **no model consumes it in C7** — that is
    C8's work, behind the degradation sensitivity PLAN.md requires.

    An hour missing any input yields NaN rather than a partial subtraction: a
    residual load computed from load alone would read as a huge residual and
    quietly become the largest outlier in the fundamentals chapter.
    """
    needed = (LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN)
    missing = [c for c in needed if c not in frame.columns]
    if missing:
        raise ExogenousDataError(
            f"cannot derive {RESIDUAL_LOAD_COLUMN}: missing {missing} "
            f"(have {list(frame.columns)})"
        )
    out = frame.copy()
    out.attrs = dict(frame.attrs)
    out[RESIDUAL_LOAD_COLUMN] = (
        frame[LOAD_COLUMN] - frame[WIND_COLUMN] - frame[SOLAR_COLUMN]
    )
    flagged = set(out.attrs.get("flagged_columns") or [])
    flagged.add(RESIDUAL_LOAD_COLUMN)
    out.attrs["flagged_columns"] = sorted(flagged)
    return out


def load_zone_exogenous(
    zone_key: str,
    years: list[int] | None = None,
    config: dict[str, Any] | None = None,
    hourly: bool = True,
    with_residual_load: bool = True,
    on_partial: Literal["raise", "flag"] = "raise",
) -> pd.DataFrame:
    """Every cached exogenous series for one zone, joined on the UTC index.

    The join is an outer join: a document covering fewer years than another
    leaves NaN rather than silently truncating the wider one to the narrower.
    What is actually covered is in ``frame.attrs['documents']``.
    """
    cfg = config or load_data_config()
    pieces: dict[str, pd.DataFrame] = {}
    reports: dict[str, dict[str, Any]] = {}
    flagged: set[str] = set()
    resolutions: set[int] = set()

    for document_key in load_documents(cfg):
        if not cached_years(zone_key, document_key, cfg):
            continue
        frame = load_zone_document(
            zone_key, document_key, years, cfg, hourly=hourly, on_partial=on_partial
        )
        pieces[document_key] = frame
        reports[document_key] = {
            "stitch": frame.attrs["stitch_report"].as_dict(),
            "leakage_status": frame.attrs["leakage_status"],
            "aggregation_reports": frame.attrs["aggregation_reports"],
        }
        flagged.update(frame.attrs.get("flagged_columns") or [])
        resolutions.update(frame.attrs.get("native_resolutions_seconds") or [])

    if not pieces:
        raise ExogenousDataError(
            f"no cached ENTSO-E documents for {zone_key} — run "
            f"`python -m data.fetch_exogenous`"
        )

    combined = pd.concat(list(pieces.values()), axis=1).sort_index()
    combined.index.name = "timestamp_utc"
    combined.attrs["zone"] = zone_key
    combined.attrs["documents"] = reports
    combined.attrs["flagged_columns"] = sorted(flagged)
    combined.attrs["leakage_status"] = "FLAGGED" if flagged else "safe"
    combined.attrs["native_resolutions_seconds"] = sorted(resolutions)
    combined.attrs["hourly"] = hourly
    combined.attrs["unit"] = "MW"

    if with_residual_load and all(
        c in combined.columns for c in (LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN)
    ):
        combined = add_residual_load(combined)
    return combined


def column_leakage_status(
    column: str, config: dict[str, Any] | None = None
) -> str:
    """The declared leakage status of one exogenous column.

    ``residual_load_forecast_mw`` is FLAGGED by inheritance: two of its three
    inputs are the Art. 14 post-gate-closure vintage.
    """
    if column == RESIDUAL_LOAD_COLUMN:
        return "FLAGGED"
    return series_owner(column, config).leakage_status
