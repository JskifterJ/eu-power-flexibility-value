"""The feature matrix, built from ``config/features.yaml``, with an information
time attached to every single cell.

Two ideas carry this module.

**Config is the spec.** The columns, their lags and their aggregates come from
``config/features.yaml``, not from literals here, so the committed spec and the
built matrix cannot drift apart.

**Every cell declares when it became knowable.** Alongside the feature frame
this returns an identically-shaped frame of *information times* — the UTC instant
at which a bidder could have known that cell's value. Calendar columns carry
``NaT`` (they embed no market information). Price-derived columns carry the
publication instant of the auction that set the price they came from — which is
*not* the price's own timestamp. :mod:`forecast.leakage` then checks the whole
matrix against each row's gate closure in one pass.

Lags are taken by **explicit UTC offset reindexing**, never ``.shift(n)``:
``shift`` counts rows, so across a gap it silently hands back the wrong hour and
calls it a 24-hour lag. A gap stays a NaN here (CLAUDE.md: never fill).

---

**NOTE C3-01 — the daily-aggregate features cannot be built the way
``features.yaml`` literally describes, because that description leaks.**

``features.yaml`` declares ``price_daily_{mean,min,max}_lag_24h`` with
``aggregate: mean_over_utc_day`` and ``lag_hours: 24``. Read literally — the mean
over the UTC day containing ``t - 24h`` — that window is UTC day ``D-1`` for 23 of
the 24 hours of target market day ``D``. For a CET zone, UTC day ``D-1`` ends at
``D-1 23:00Z``, which is **local midnight on day D**: market day ``D``'s own first
hour, published after gate closure for day ``D``. So the literal feature embeds
one hour of the very day it is predicting, on nearly every row.

This module therefore builds those three columns over **the latest UTC calendar
day whose every hour was public at the row's gate closure** — mechanically
derived, not hardcoded; for the CET/CEST zones in scope that resolves to UTC day
``D-2``. The column *names* are kept exactly as the committed spec declares them,
so config remains the single source of truth, but the ``lag_24h`` in those names
is now a misnomer. A human decision is requested on whether ``features.yaml``
should rename them (``..._prev_available_utc_day``) and restate the aggregate.
Proposed, not done — editing the feature spec to make a leak disappear is
precisely the move CLAUDE.md warns about, so the leak is documented and the
*code* is conservative instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from data.config import load_feature_config
from data.energy_charts import PRICE_COLUMN
from forecast.leakage import MaskReport, assert_no_leakage, mask_unavailable
from forecast.timing import (
    GateClosureConvention,
    gate_closure_convention,
    gate_closure_for,
    market_days,
    publication_for,
    zone_timezone,
)

HOURS_PER_UTC_DAY = 24

#: Aggregates ``features.yaml`` may ask for, and the pandas reduction each maps to.
SUPPORTED_AGGREGATES = {
    "mean_over_utc_day": "mean",
    "min_over_utc_day": "min",
    "max_over_utc_day": "max",
}

#: Calendar columns this module knows how to build. Anything else in the spec's
#: ``calendar`` block that is not marked ``status: deferred`` is an error, not a
#: column to skip silently.
CALENDAR_BUILDERS = ("hour_of_day_local", "hour_of_day_utc", "day_of_week", "is_weekend", "month")


class FeatureError(RuntimeError):
    """The feature spec and the data cannot be reconciled."""


@dataclass
class FeatureBuildReport:
    """What the build did — logged and committed, so the matrix is auditable."""

    zone: str
    n_rows: int = 0
    first_target_utc: str | None = None
    last_target_utc: str | None = None
    price_columns: list[str] = field(default_factory=list)
    calendar_columns: list[str] = field(default_factory=list)
    deferred_columns: list[str] = field(default_factory=list)
    daily_aggregate_source: dict[str, str] = field(default_factory=dict)
    n_incomplete_utc_days: int = 0
    mask: MaskReport = field(default_factory=MaskReport)

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "n_rows": self.n_rows,
            "first_target_utc": self.first_target_utc,
            "last_target_utc": self.last_target_utc,
            "price_columns": list(self.price_columns),
            "calendar_columns": list(self.calendar_columns),
            "deferred_columns": list(self.deferred_columns),
            "daily_aggregate_source": dict(self.daily_aggregate_source),
            "n_incomplete_utc_days": self.n_incomplete_utc_days,
            "mask": self.mask.as_dict(),
        }


@dataclass(frozen=True)
class FeatureMatrix:
    """Features, their information times, the target, and the decision clock.

    The pieces travel together on purpose: a feature frame separated from its
    information times is a feature frame nobody can check.
    """

    zone: str
    features: pd.DataFrame
    information_times: pd.DataFrame
    target: pd.Series
    gate_closure: pd.Series
    market_day: pd.Series
    deterministic: tuple[str, ...]
    report: FeatureBuildReport

    def __post_init__(self) -> None:
        for name, obj in (
            ("information_times", self.information_times),
            ("target", self.target),
            ("gate_closure", self.gate_closure),
            ("market_day", self.market_day),
        ):
            if not self.features.index.equals(obj.index):
                raise FeatureError(f"{name} does not share the feature index")

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.features.index

    @property
    def columns(self) -> list[str]:
        return list(self.features.columns)

    def assert_clean(self, context: str | None = None) -> None:
        """Re-run the gate-closure guard. Cheap; call it after anything clever."""
        assert_no_leakage(
            self.features,
            self.information_times,
            self.gate_closure,
            self.deterministic,
            context or f"{self.zone} feature matrix",
        )

    def select_days(self, days) -> "FeatureMatrix":
        """The sub-matrix whose target rows fall on the given market days."""
        wanted = set(days)
        keep = self.market_day.isin(wanted).to_numpy()
        return self.subset(keep)

    def subset(self, mask) -> "FeatureMatrix":
        """Row subset, keeping every frame aligned and the report attached."""
        mask = np.asarray(mask)
        return FeatureMatrix(
            zone=self.zone,
            features=self.features.loc[mask],
            information_times=self.information_times.loc[mask],
            target=self.target.loc[mask],
            gate_closure=self.gate_closure.loc[mask],
            market_day=self.market_day.loc[mask],
            deterministic=self.deterministic,
            report=self.report,
        )

    def with_features(
        self, features: pd.DataFrame, information_times: pd.DataFrame | None = None
    ) -> "FeatureMatrix":
        """Replace the feature frame (used by the leakage/shift experiments)."""
        return FeatureMatrix(
            zone=self.zone,
            features=features,
            information_times=(
                self.information_times if information_times is None else information_times
            ),
            target=self.target,
            gate_closure=self.gate_closure,
            market_day=self.market_day,
            deterministic=self.deterministic,
            report=self.report,
        )

    def with_target(self, target: pd.Series) -> "FeatureMatrix":
        """Replace the target (used by the target-permutation assertion)."""
        if not self.features.index.equals(target.index):
            raise FeatureError("replacement target does not share the feature index")
        return FeatureMatrix(
            zone=self.zone,
            features=self.features,
            information_times=self.information_times,
            target=target,
            gate_closure=self.gate_closure,
            market_day=self.market_day,
            deterministic=self.deterministic,
            report=self.report,
        )


def _validate_price_frame(prices: pd.DataFrame) -> pd.Series:
    if PRICE_COLUMN not in prices.columns:
        raise FeatureError(f"price frame has no {PRICE_COLUMN!r} column")
    index = prices.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise FeatureError("price frame must have a tz-aware DatetimeIndex")
    if str(index.tz) != "UTC":
        raise FeatureError(f"price frame index must be UTC, got {index.tz}")
    if not index.is_monotonic_increasing:
        raise FeatureError("price frame index must be sorted")
    if index.has_duplicates:
        raise FeatureError("price frame index has duplicate timestamps")
    return prices[PRICE_COLUMN].astype("float64")


def _lag_by_offset(
    price: pd.Series, published: pd.Series, index: pd.DatetimeIndex, lag_hours: int
) -> tuple[np.ndarray, np.ndarray]:
    """Value and information time of ``price`` at ``index - lag_hours``.

    Reindexing on the shifted instants — not ``.shift`` — so a gap in the series
    yields NaN instead of silently returning the wrong hour's price.
    """
    source = index - pd.Timedelta(hours=lag_hours)
    values = price.reindex(source).to_numpy(dtype="float64")
    info = published.reindex(source).to_numpy()
    return values, info


def _daily_stats(
    price: pd.Series, published: pd.Series
) -> tuple[pd.DataFrame, pd.Series, int]:
    """Per-UTC-calendar-day price statistics, each with its availability instant.

    The availability instant of a UTC day is the publication time of its **last**
    hour — for a CET zone that hour belongs to the *next* market day, which is
    exactly why a naive "yesterday's UTC day" window leaks (see NOTE C3-01).

    A UTC day holding fewer than 24 hours yields NaN statistics rather than a
    mean over a short day; the count of such days is reported.
    """
    utc_date = pd.Index(price.index.date, name="utc_date")
    grouped = price.groupby(utc_date)
    stats = pd.DataFrame(
        {
            "mean": grouped.mean(),
            "min": grouped.min(),
            "max": grouped.max(),
            "n_hours": grouped.size(),
        }
    )
    incomplete = stats["n_hours"] != HOURS_PER_UTC_DAY
    stats.loc[incomplete, ["mean", "min", "max"]] = np.nan
    available_at = published.groupby(utc_date).max()
    if not available_at.is_monotonic_increasing:
        raise FeatureError(
            "UTC-day availability instants are not monotone in date — the "
            "publication convention has stopped making sense"
        )
    return stats, available_at, int(incomplete.sum())


def _latest_available_day(
    gate_closure: pd.Series, available_at: pd.Series
) -> tuple[np.ndarray, np.ndarray]:
    """For each row, the index into ``available_at`` of the latest fully public UTC day.

    ``-1`` means no UTC day in the series was complete and public by that row's
    gate closure (the first days of the series).
    """
    info_values = available_at.to_numpy(dtype="datetime64[ns]")
    gates = gate_closure.to_numpy(dtype="datetime64[ns]")
    positions = np.searchsorted(info_values, gates, side="right") - 1
    return positions, info_values


def build_features(
    prices: pd.DataFrame,
    zone_key: str,
    feature_config: dict[str, Any] | None = None,
    convention: GateClosureConvention | None = None,
    mask: bool = True,
    check: bool = True,
) -> FeatureMatrix:
    """Build the full feature matrix for one zone from a stitched price series.

    ``mask`` blanks cells that were not public at gate closure (see NOTE C3-01 —
    there is one such cell per autumn DST day even in the plain 24-hour lag) and
    ``check`` runs the leakage guard afterwards. Both default on; the tests turn
    them off deliberately in order to watch the guard fire.
    """
    spec = feature_config or load_feature_config()
    conv = convention or gate_closure_convention()
    tz = zone_timezone(zone_key)

    price = _validate_price_frame(prices)
    index = prices.index
    day = market_days(index, tz)
    gate = gate_closure_for(day, conv)
    published = publication_for(day, conv)

    features: dict[str, pd.Series] = {}
    info: dict[str, pd.Series] = {}
    report = FeatureBuildReport(
        zone=zone_key,
        n_rows=int(len(index)),
        first_target_utc=index[0].isoformat(),
        last_target_utc=index[-1].isoformat(),
    )

    daily_stats, day_available_at, n_incomplete = _daily_stats(price, published)
    report.n_incomplete_utc_days = n_incomplete
    positions, day_info_values = _latest_available_day(gate, day_available_at)
    has_day = positions >= 0

    for entry in spec.get("price_history") or []:
        name = entry.get("name")
        if not name:
            raise FeatureError("a price_history entry has no name")
        if entry.get("status") == "deferred":
            report.deferred_columns.append(name)
            continue
        lag_hours = entry.get("lag_hours")
        if lag_hours is None:
            raise FeatureError(f"price_history feature {name!r} declares no lag_hours")
        aggregate = entry.get("aggregate")

        if aggregate is None:
            values, info_values = _lag_by_offset(price, published, index, int(lag_hours))
            features[name] = pd.Series(values, index=index, name=name)
            info[name] = pd.Series(pd.to_datetime(info_values, utc=True), index=index, name=name)
            continue

        if aggregate not in SUPPORTED_AGGREGATES:
            raise FeatureError(
                f"feature {name!r} asks for aggregate {aggregate!r}; supported: "
                f"{sorted(SUPPORTED_AGGREGATES)}"
            )
        column = SUPPORTED_AGGREGATES[aggregate]
        source = daily_stats[column].to_numpy(dtype="float64")
        values = np.full(len(index), np.nan)
        values[has_day] = source[positions[has_day]]
        info_values = np.full(len(index), np.datetime64("NaT"), dtype="datetime64[ns]")
        info_values[has_day] = day_info_values[positions[has_day]]
        features[name] = pd.Series(values, index=index, name=name)
        info[name] = pd.Series(pd.to_datetime(info_values, utc=True), index=index, name=name)
        chosen = daily_stats.index.to_numpy()
        report.daily_aggregate_source[name] = (
            f"latest fully public UTC calendar day ({column}); "
            f"e.g. target {index[-1].isoformat()} -> UTC day "
            f"{chosen[positions[-1]] if has_day[-1] else 'none'} (NOTE C3-01)"
        )

    report.price_columns = [c for c in features]

    local_hour = index.tz_convert(tz).hour
    weekday = np.array([d.weekday() for d in day], dtype="int16")
    calendar_values = {
        "hour_of_day_local": np.asarray(local_hour, dtype="int16"),
        "hour_of_day_utc": np.asarray(index.hour, dtype="int16"),
        "day_of_week": weekday,
        "is_weekend": (weekday >= 5).astype("int8"),
        "month": np.array([d.month for d in day], dtype="int16"),
    }
    deterministic: list[str] = []
    for entry in spec.get("calendar") or []:
        name = entry.get("name")
        if not name:
            raise FeatureError("a calendar entry has no name")
        if entry.get("status") == "deferred":
            report.deferred_columns.append(name)
            continue
        if name not in calendar_values:
            raise FeatureError(
                f"calendar feature {name!r} is declared and not deferred, but this "
                f"module cannot build it; known: {CALENDAR_BUILDERS}"
            )
        features[name] = pd.Series(calendar_values[name], index=index, name=name)
        info[name] = pd.Series(pd.NaT, index=index, name=name, dtype="datetime64[ns, UTC]")
        deterministic.append(name)
    report.calendar_columns = list(deterministic)

    if not features:
        raise FeatureError("the feature spec produced no columns")

    frame = pd.DataFrame(features, index=index)
    info_frame = pd.DataFrame(info, index=index)[frame.columns]

    if mask:
        frame, mask_report = mask_unavailable(frame, info_frame, gate, deterministic)
        report.mask = mask_report

    matrix = FeatureMatrix(
        zone=zone_key,
        features=frame,
        information_times=info_frame,
        target=price.rename("target_price_eur_mwh"),
        gate_closure=gate,
        market_day=day,
        deterministic=tuple(deterministic),
        report=report,
    )
    if check:
        matrix.assert_clean(f"{zone_key} feature matrix (build_features)")
    return matrix


def shift_feature_matrix(matrix: FeatureMatrix, days: int) -> FeatureMatrix:
    """Deliberately misalign features against targets by whole days.

    PLAN.md's first leakage assertion. ``days=+1`` makes every row see the
    features that properly belong to the row 24 hours **earlier** — the same
    pipeline, one day staler — and metrics must get worse. ``days=-1`` hands each
    row features from a day **later**, which is future information at that row's
    gate closure, and metrics must get better. Either direction beating correct
    alignment would mean the harness is insensitive to time, which is the state
    in which leakage hides.

    The returned matrix keeps the original information times, so it is knowingly
    *dishonest* about availability for ``days < 0`` — it exists to be measured,
    never to be fitted for real, and :meth:`FeatureMatrix.assert_clean` on it
    fails by design.
    """
    if days == 0:
        return matrix
    source = matrix.index - pd.Timedelta(days=days)
    shifted = matrix.features.reindex(source)
    shifted.index = matrix.index
    deterministic = list(matrix.deterministic)
    # Calendar columns are pure functions of the target timestamp: a forecaster
    # always knows what hour and weekday they are bidding for. Misaligning them
    # would test clock arithmetic, not feature alignment.
    for column in deterministic:
        shifted[column] = matrix.features[column]
    return matrix.with_features(shifted[matrix.features.columns])
