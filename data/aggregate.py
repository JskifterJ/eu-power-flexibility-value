"""Aggregation of sub-hourly prices to the hourly market time unit.

Why this exists before there is any sub-hourly data: SDAC moved the day-ahead
market time unit from 60 to 15 minutes on 2025-10-01. PLAN.md keeps the main
backtest hourly and ends it 2025-09-30, treating native 15-minute analysis as a
labelled stretch goal — so any post-cutover series that *is* touched must be
aggregated by one documented, tested method rather than by whatever
``.resample()`` call a later cycle happens to write.

**The method, stated plainly.** The hourly price for UTC hour *h* is the
**unweighted arithmetic mean** of the sub-hourly clearing prices whose interval
*starts* inside *h*. Sub-hourly intervals within an hour are equal in duration,
so the unweighted mean is the correct duration-weighted average price.

**It is not a volume-weighted price, and it cannot be.** A volume-weighted hourly
price would need cleared volume per 15-minute interval; the Energy-Charts
``/price`` payload carries prices only (``unix_seconds`` / ``price``), and no
volume series is fetched anywhere in this project. So:

* Duration weighting: correct, and what the default does.
* Volume weighting: **not available**. :func:`to_hourly` accepts an explicit
  ``volume`` series so the machinery exists if a volume source is ever added,
  but nothing in this repo supplies one, and the write-up states the hourly
  figure is a duration-weighted mean of 15-minute prices, not a VWAP.

Consequence for interpretation, which belongs in the write-up's Limits section: a
battery's realisable value is *higher* at 15-minute granularity than the
aggregated hourly series implies, because aggregation destroys within-hour
spread. Aggregated post-cutover results therefore understate flexibility value
and must never be pooled with pre-cutover hourly results as though they were the
same measurement.

**Partial hours are never silently averaged.** An hour holding fewer intervals
than the resolution implies is a defect, not something to mean over: by default
it raises, and ``on_partial="flag"`` keeps it as NaN with the hour recorded. The
grouping key is the UTC hour — local time is never used for resampling
(CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from data.contracts import (
    HOURLY_SECONDS,
    DataContractViolation,
    modal_resolution_seconds,
)
from data.energy_charts import PRICE_COLUMN

SECONDS_PER_HOUR = 3600


@dataclass
class AggregationReport:
    """What aggregation did. Committed alongside results so the method is auditable."""

    method: str
    input_resolution_seconds: int
    intervals_per_hour: int
    n_input_rows: int
    n_output_hours: int
    n_partial_hours: int = 0
    partial_hours_utc: list[str] = field(default_factory=list)
    volume_weighted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "input_resolution_seconds": self.input_resolution_seconds,
            "intervals_per_hour": self.intervals_per_hour,
            "n_input_rows": self.n_input_rows,
            "n_output_hours": self.n_output_hours,
            "n_partial_hours": self.n_partial_hours,
            "partial_hours_utc": self.partial_hours_utc,
            "volume_weighted": self.volume_weighted,
        }


def to_hourly(
    frame: pd.DataFrame,
    column: str = PRICE_COLUMN,
    volume: pd.Series | None = None,
    on_partial: Literal["raise", "flag"] = "raise",
) -> pd.DataFrame:
    """Aggregate a UTC-indexed sub-hourly price frame to hourly.

    Already-hourly input is returned unchanged (idempotent), so a caller can run
    this over a series that straddles the cutover without special-casing.
    ``frame.attrs['aggregation_report']`` records what happened.
    """
    if column not in frame.columns:
        raise DataContractViolation(
            f"cannot aggregate: no {column!r} column (got {list(frame.columns)})"
        )
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise DataContractViolation(
            "cannot aggregate: index must be a tz-aware (UTC) DatetimeIndex"
        )
    if len(index) < 2:
        raise DataContractViolation(f"cannot aggregate {len(index)} row(s)")

    resolution = modal_resolution_seconds(index)
    if resolution == HOURLY_SECONDS:
        out = frame.copy()
        out.attrs = dict(frame.attrs)
        out.attrs["aggregation_report"] = AggregationReport(
            method="passthrough (input already hourly)",
            input_resolution_seconds=resolution,
            intervals_per_hour=1,
            n_input_rows=int(len(frame)),
            n_output_hours=int(len(frame)),
        )
        return out
    if resolution > HOURLY_SECONDS or SECONDS_PER_HOUR % resolution:
        raise DataContractViolation(
            f"input resolution {resolution}s does not divide an hour — refusing to "
            f"aggregate rather than guessing a rule"
        )

    per_hour = SECONDS_PER_HOUR // resolution
    hour_key = index.floor("h")
    grouped = frame[column].groupby(hour_key)
    counts = grouped.size()

    if volume is not None:
        weights = volume.reindex(index)
        if weights.isna().any():
            raise DataContractViolation(
                "volume series does not cover every input interval — refusing to "
                "weight by partially-missing volumes"
            )
        numerator = (frame[column] * weights).groupby(hour_key).sum()
        denominator = weights.groupby(hour_key).sum()
        if (denominator == 0).any():
            raise DataContractViolation(
                "zero total volume in at least one hour — a volume-weighted price is "
                "undefined there"
            )
        hourly = numerator / denominator
        method = f"volume-weighted mean of {per_hour} x {resolution}s prices per UTC hour"
    else:
        hourly = grouped.mean()
        method = (
            f"unweighted arithmetic mean of {per_hour} x {resolution}s prices per UTC "
            f"hour (= duration-weighted; NOT volume-weighted, no volume series exists)"
        )

    partial = counts[counts != per_hour]
    if len(partial):
        if on_partial == "raise":
            raise DataContractViolation(
                f"{len(partial)} hour(s) hold fewer/more than {per_hour} intervals, "
                f"e.g. {partial.index[0].isoformat()} with {int(partial.iloc[0])} — "
                f"refusing to average a partial hour. Fix the gap, or pass "
                f"on_partial='flag' to keep it as NaN."
            )
        hourly = hourly.mask(counts != per_hour)

    out = pd.DataFrame({column: hourly})
    out.index.name = "timestamp_utc"
    out.attrs = dict(frame.attrs)
    out.attrs["aggregation_report"] = AggregationReport(
        method=method,
        input_resolution_seconds=resolution,
        intervals_per_hour=per_hour,
        n_input_rows=int(len(frame)),
        n_output_hours=int(len(out)),
        n_partial_hours=int(len(partial)),
        partial_hours_utc=[t.isoformat() for t in partial.index[:20]],
        volume_weighted=volume is not None,
    )
    return out
