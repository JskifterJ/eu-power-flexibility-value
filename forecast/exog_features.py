"""Tier-A exogenous columns, attached to the price feature matrix at a declared
*vintage* (PLAN.md C8).

C7 fetched, validated and contracted the two ENTSO-E day-ahead forecast
documents but deliberately let no model see them. This module is the join, and
the whole difficulty lives in one fact:

    the Art. 6.1.B **load** forecast for market day ``D`` is public by 10:00
    local on ``D-1``; the Art. 14.1.D **wind/solar** forecast for ``D`` is
    public at 18:00 local on ``D-1`` — *six hours after* the 12:00 gate at
    which the bids being modelled were already in.

So the archived RES vintage is not information a bidder held, and a model fed it
is reading tomorrow's weather off tomorrow's newspaper. PLAN.md's answer is not
to drop the series and not to use it quietly either, but to make the gap a
measured quantity. This module therefore builds the same exogenous column set at
four declared **variants**, and :mod:`backtest.run_c8_exogenous` runs all four:

``price_only``
    No exogenous column at all — the C4 feature set, carried through the same
    code path so the comparison is not against a differently-built matrix.
``load_only``
    ``+ load_forecast_da_mw``. Every cell public before gate closure. **This is
    the honest exogenous model**: whatever it gains over ``price_only`` is a
    gain a bidder could actually have banked.
``res_persistence``
    ``+`` wind, solar and residual load, but taken from the vintage published
    for the *previous* market day (a 24-hour offset) — which was public at 18:00
    on ``D-2``, comfortably before the gate. A real bidder's fallback: yesterday's
    RES forecast is the best RES forecast they are allowed to have. Leak-free,
    and still informative because wind and solar are autocorrelated day to day.
``res_as_published``
    ``+`` the same three columns at the as-published vintage. **Knowingly late.**
    It exists to be measured, never to be reported as achievable, and the
    distance between it and ``res_persistence`` is the number PLAN.md C8 asks
    for: how much of the apparent exogenous gain is owed purely to the archive
    being better informed than the market was.

The ladder is monotone in information by construction, which gives the run a
free sanity check: ``price_only`` ≤ ``load_only`` ≤ ``res_persistence`` ≤
``res_as_published`` in expectation, and a violation is a finding about the
model (a feature the LASSO cannot use, or noise swamping a weak signal), not a
bug in the plumbing.

---

**The guard is not loosened for the late variant; it is pointed at it.**

Three rules keep ``res_as_published`` from becoming an accident:

1. Every exogenous column carries a real information time, derived from the
   publication clock now declared in ``config/data.yaml`` beside the document it
   belongs to — not from a comment, and not from the target timestamp.
2. For every variant *except* ``res_as_published``, cells that were not public
   at the row's own gate closure are blanked by
   :func:`forecast.leakage.mask_unavailable` exactly as C3 blanks a late price
   lag, and :func:`forecast.leakage.assert_no_leakage` then has to pass clean.
3. ``res_as_published`` names its late columns out loud, in
   :attr:`ExogAttachReport.acknowledged_late_columns`, and
   :func:`assert_only_acknowledged_leakage` demands that the *only* violations
   the guard finds are ``after_gate_closure`` on exactly those columns, with
   exactly the lateness the declared clock predicts. Any other violation — a
   late price lag, an undeclared column, a column late by the wrong amount —
   still raises. That check is **stricter** than the plain guard on that matrix,
   not weaker: it pins the leak's shape instead of merely allowing one.

Nothing in :mod:`forecast.leakage`, :mod:`forecast.features`,
:mod:`data.contracts` or ``tests/`` is modified to make this work. The late
variant is a measurement, in the same sense as
:func:`backtest.diagnostics.day_shift_experiment`, and it is built out of the
existing primitives rather than by relaxing them.

---

**The persistence variant is a 24-hour UTC offset, and that offset is read back
from the clock rather than assumed to be safe.** For one row per autumn
DST day the offset lands on the *same* 25-hour local market day (the day's last
hour minus 24 hours is its own first hour), so the "previous day's" vintage is
in fact that day's own 18:00 publication — late. The guard catches those rows
and the mask blanks them; the count is reported as
:attr:`ExogAttachReport.persistence_masked_dst_rows` rather than papered over.
That is the machinery doing real work on a case nobody would have thought to
special-case.

**The residual-load column is derived after degradation, not before.** Under
``res_persistence`` a bidder holds the load forecast for ``D`` *and* the RES
forecast for ``D-1``, so the best residual-load estimate available to them is
``load(t) - wind(t-24h) - solar(t-24h)``. That is what this module builds — a
quantity the bidder could actually have computed — rather than lagging C7's
already-derived residual-load column by 24 hours, which would throw away the
load forecast they did have. Its information time is the element-wise maximum of
its three inputs' information times: a derived value is knowable only once its
last input is.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from data.config import load_data_config
from data.entsoe import load_documents, series_owner
from data.exogenous import (
    LOAD_COLUMN,
    RESIDUAL_LOAD_COLUMN,
    SOLAR_COLUMN,
    WIND_COLUMN,
)
from forecast.features import FeatureMatrix, FeatureError
from forecast.leakage import (
    LeakageError,
    LeakageViolation,
    find_leakage,
    mask_unavailable,
)
from forecast.timing import market_days, zone_timezone

#: The four variants, in increasing order of information. The order is load-bearing:
#: :func:`variant_is_monotone_in_information` reads the ladder off this tuple.
EXOG_VARIANTS = ("price_only", "load_only", "res_persistence", "res_as_published")

#: Variants whose columns are all public at gate closure, and which therefore must
#: pass the plain C3 guard with no acknowledgement of any kind.
LEAK_FREE_VARIANTS = ("price_only", "load_only", "res_persistence")

#: The FLAGGED (Art. 14) columns plus the column derived from them.
RES_COLUMNS = (WIND_COLUMN, SOLAR_COLUMN)

ONE_DAY = dt.timedelta(days=1)


class ExogFeatureError(RuntimeError):
    """The exogenous frame and the feature matrix cannot be reconciled."""


@dataclass(frozen=True)
class ExogSpec:
    """Which exogenous columns enter the matrix, and at which vintage.

    ``persistence_lag_hours`` is the degradation. 24 is the one PLAN.md names
    ("a deliberately degraded/persistence version") and the only one a bidder's
    information set actually offers for free: the forecast published for
    yesterday. It is a committed constant here rather than a swept knob — C8 is
    a sensitivity, not a search.
    """

    variant: str = "load_only"
    persistence_lag_hours: int = 24
    include_residual_load: bool = True

    def __post_init__(self) -> None:
        if self.variant not in EXOG_VARIANTS:
            raise ExogFeatureError(
                f"unknown exogenous variant {self.variant!r}; use one of {EXOG_VARIANTS}"
            )
        if self.persistence_lag_hours <= 0:
            raise ExogFeatureError(
                f"persistence_lag_hours must be positive, got {self.persistence_lag_hours}"
            )
        if self.persistence_lag_hours % 24 != 0:
            raise ExogFeatureError(
                f"persistence_lag_hours={self.persistence_lag_hours} is not a whole "
                f"number of days. A fractional-day offset mixes delivery hours, so the "
                f"'same hour, previous publication' reading of the feature stops being true."
            )

    @property
    def uses_res(self) -> bool:
        return self.variant in ("res_persistence", "res_as_published")

    @property
    def uses_load(self) -> bool:
        return self.variant != "price_only"

    @property
    def res_lag_hours(self) -> int:
        """0 for the as-published vintage, the degradation otherwise."""
        return 0 if self.variant == "res_as_published" else self.persistence_lag_hours

    @property
    def acknowledges_late_columns(self) -> bool:
        return self.variant == "res_as_published"

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "persistence_lag_hours": self.persistence_lag_hours,
            "include_residual_load": self.include_residual_load,
            "res_lag_hours": self.res_lag_hours,
            "acknowledges_late_columns": self.acknowledges_late_columns,
        }


@dataclass(frozen=True)
class PublicationClock:
    """When one ENTSO-E document's forecast for market day ``D`` became public."""

    document_key: str
    day_offset: int
    local_time: dt.time
    tz: str
    leakage_status: str

    def describe(self) -> str:
        sign = "+" if self.day_offset >= 0 else "-"
        return (
            f"{self.local_time.strftime('%H:%M')} {self.tz} on "
            f"D{sign}{abs(self.day_offset)}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "document": self.document_key,
            "day_offset": self.day_offset,
            "local_time": self.local_time.strftime("%H:%M"),
            "tz": self.tz,
            "leakage_status": self.leakage_status,
            "describes": self.describe(),
        }


@dataclass
class ExogAttachReport:
    """What the join did — committed beside the scores, so the arm is auditable."""

    zone: str
    spec: dict[str, Any] = field(default_factory=dict)
    exogenous_columns: list[str] = field(default_factory=list)
    clocks: dict[str, dict[str, Any]] = field(default_factory=dict)
    column_vintage: dict[str, str] = field(default_factory=dict)
    acknowledged_late_columns: list[str] = field(default_factory=list)
    acknowledged_violations: list[dict[str, Any]] = field(default_factory=list)
    masked_per_column: dict[str, int] = field(default_factory=dict)
    persistence_masked_dst_rows: int = 0
    persistence_masked_dst_timestamps: list[str] = field(default_factory=list)
    n_rows: int = 0
    n_rows_with_all_exogenous: int = 0
    first_complete_exogenous_utc: str | None = None
    coverage_per_column: dict[str, float] = field(default_factory=dict)
    exogenous_source: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "spec": dict(self.spec),
            "exogenous_columns": list(self.exogenous_columns),
            "clocks": dict(self.clocks),
            "column_vintage": dict(self.column_vintage),
            "acknowledged_late_columns": list(self.acknowledged_late_columns),
            "acknowledged_violations": list(self.acknowledged_violations),
            "masked_per_column": dict(self.masked_per_column),
            "persistence_masked_dst_rows": self.persistence_masked_dst_rows,
            "persistence_masked_dst_timestamps": list(self.persistence_masked_dst_timestamps),
            "n_rows": self.n_rows,
            "n_rows_with_all_exogenous": self.n_rows_with_all_exogenous,
            "first_complete_exogenous_utc": self.first_complete_exogenous_utc,
            "coverage_per_column": dict(self.coverage_per_column),
            "exogenous_source": dict(self.exogenous_source),
        }


# ---------------------------------------------------------------------------
# The publication clock, read from config
# ---------------------------------------------------------------------------


def _parse_hhmm(value: Any, context: str) -> dt.time:
    text = str(value)
    try:
        hour, minute = (int(part) for part in text.split(":"))
        return dt.time(hour=hour, minute=minute)
    except (TypeError, ValueError) as exc:
        raise ExogFeatureError(
            f"{context}: {value!r} is not an HH:MM local time"
        ) from exc


def publication_clocks(config: dict[str, Any] | None = None) -> dict[str, PublicationClock]:
    """``{document_key: PublicationClock}`` from ``config/data.yaml``.

    Every document must declare its clock. A missing declaration is an error and
    not a default, because the only safe default — "assume it was late" — would
    silently disable a column, and the only convenient one — "assume it was
    early" — is the bug this whole module exists to prevent.
    """
    cfg = config or load_data_config()
    entsoe = cfg["sources"]["entsoe"]
    tz = entsoe.get("publication_tz")
    if not tz:
        raise ExogFeatureError(
            "config/data.yaml sources.entsoe declares no 'publication_tz' — the "
            "information time of an exogenous column cannot be derived without it"
        )
    raw_documents = entsoe.get("documents") or {}
    clocks: dict[str, PublicationClock] = {}
    for key, document in load_documents(cfg).items():
        spec = raw_documents.get(key) or {}
        if "published_local" not in spec or "published_day_offset" not in spec:
            raise ExogFeatureError(
                f"entsoe document {key!r} declares no publication clock "
                f"('published_local' / 'published_day_offset' in config/data.yaml). "
                f"The gate-closure guard cannot check its columns, so this fails "
                f"closed rather than guessing."
            )
        clocks[key] = PublicationClock(
            document_key=key,
            day_offset=int(spec["published_day_offset"]),
            local_time=_parse_hhmm(spec["published_local"], f"document {key}"),
            tz=str(tz),
            leakage_status=document.leakage_status,
        )
    return clocks


def _local_to_utc(day: dt.date, time: dt.time, tz: str) -> pd.Timestamp:
    naive = pd.Timestamp(dt.datetime.combine(day, time))
    return naive.tz_localize(tz, ambiguous="raise", nonexistent="raise").tz_convert("UTC")


def publication_instants(days: pd.Series, clock: PublicationClock) -> pd.Series:
    """The UTC instant at which ``clock``'s document became public, per market day.

    Memoised over distinct days: a year of hourly rows holds ~365 of them.
    """
    offset = dt.timedelta(days=clock.day_offset)
    distinct = pd.unique(days.dropna())
    lookup = {
        day: _local_to_utc(day + offset, clock.local_time, clock.tz) for day in distinct
    }
    out = pd.to_datetime(days.map(lookup), utc=True)
    out.name = f"{clock.document_key}_published_utc"
    return out


def column_clock(
    column: str, clocks: dict[str, PublicationClock]
) -> PublicationClock:
    """The clock of the document a raw exogenous column comes from."""
    document = series_owner(column)
    if document.key not in clocks:
        raise ExogFeatureError(
            f"column {column!r} belongs to document {document.key!r}, which has no clock"
        )
    return clocks[document.key]


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


def _validate_exogenous(exog: pd.DataFrame, zone_key: str) -> None:
    index = exog.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise ExogFeatureError(f"{zone_key}: exogenous frame needs a tz-aware index")
    if str(index.tz) != "UTC":
        raise ExogFeatureError(f"{zone_key}: exogenous index must be UTC, got {index.tz}")
    if not index.is_monotonic_increasing:
        raise ExogFeatureError(f"{zone_key}: exogenous index must be sorted")
    if index.has_duplicates:
        raise ExogFeatureError(f"{zone_key}: exogenous index has duplicate timestamps")


def _lagged(
    series: pd.Series, index: pd.DatetimeIndex, lag_hours: int
) -> np.ndarray:
    """``series`` sampled at ``index - lag_hours``, by offset reindexing.

    Reindexing on the shifted instants, never ``.shift(n)`` — ``shift`` counts
    rows, so across a gap it hands back the wrong hour and calls it a lag.
    """
    source = index if lag_hours == 0 else index - pd.Timedelta(hours=lag_hours)
    return series.reindex(source).to_numpy(dtype="float64")


def _lagged_market_days(
    index: pd.DatetimeIndex, tz: str, lag_hours: int
) -> pd.Series:
    """Market-day label of each ``index - lag_hours`` instant, indexed by ``index``."""
    source = index if lag_hours == 0 else index - pd.Timedelta(hours=lag_hours)
    days = market_days(source, tz)
    days.index = index
    return days


def attach_exogenous(
    matrix: FeatureMatrix,
    exog: pd.DataFrame | None,
    spec: ExogSpec | None = None,
    config: dict[str, Any] | None = None,
    mask: bool = True,
    check: bool = True,
) -> tuple[FeatureMatrix, ExogAttachReport]:
    """Return ``matrix`` plus this variant's exogenous columns, and the report.

    ``price_only`` returns the matrix untouched (and needs no ``exog`` frame), so
    every arm of the C8 experiment goes through this one function and the
    baseline is not a differently-constructed object.

    ``mask``/``check`` mirror :func:`forecast.features.build_features`: both
    default on, and the tests turn them off in order to watch the guard fire.
    For ``res_as_published`` the acknowledged columns are exempt from the mask by
    design — that is the whole arm — and ``check`` then runs
    :func:`assert_only_acknowledged_leakage` instead of the plain guard.
    """
    resolved = spec or ExogSpec()
    report = ExogAttachReport(
        zone=matrix.zone,
        spec=resolved.as_dict(),
        n_rows=int(len(matrix.index)),
    )

    if resolved.variant == "price_only":
        report.n_rows_with_all_exogenous = int(len(matrix.index))
        if check:
            matrix.assert_clean(f"{matrix.zone} price_only matrix (attach_exogenous)")
        return matrix, report

    if exog is None:
        raise ExogFeatureError(
            f"{matrix.zone}: variant {resolved.variant!r} needs an exogenous frame"
        )
    _validate_exogenous(exog, matrix.zone)

    clocks = publication_clocks(config)
    report.clocks = {key: clock.as_dict() for key, clock in clocks.items()}
    tz = zone_timezone(matrix.zone)
    index = matrix.index

    for required in (LOAD_COLUMN,) + (RES_COLUMNS if resolved.uses_res else ()):
        if required not in exog.columns:
            raise ExogFeatureError(
                f"{matrix.zone}: exogenous frame has no {required!r} column; it "
                f"carries {list(exog.columns)}"
            )

    values: dict[str, np.ndarray] = {}
    info: dict[str, pd.Series] = {}

    # -- load: always at the target hour's own vintage (Art. 6, pre-gate) ----
    load_clock = column_clock(LOAD_COLUMN, clocks)
    load_days = _lagged_market_days(index, tz, 0)
    values[LOAD_COLUMN] = _lagged(exog[LOAD_COLUMN], index, 0)
    info[LOAD_COLUMN] = publication_instants(load_days, load_clock)
    report.column_vintage[LOAD_COLUMN] = (
        f"as published for the target market day; public {load_clock.describe()}"
    )

    # -- wind / solar: at the variant's vintage --------------------------------
    if resolved.uses_res:
        lag = resolved.res_lag_hours
        res_days = _lagged_market_days(index, tz, lag)
        for column in RES_COLUMNS:
            clock = column_clock(column, clocks)
            values[column] = _lagged(exog[column], index, lag)
            info[column] = publication_instants(res_days, clock)
            report.column_vintage[column] = (
                f"as published for the target market day; public {clock.describe()}"
                if lag == 0
                else (
                    f"the vintage published {lag}h earlier (for market day "
                    f"D-{lag // 24}); public {clock.describe()} of that day"
                )
            )

        if resolved.include_residual_load:
            # load(t) - wind(vintage) - solar(vintage): the best residual-load
            # estimate the variant's information set actually supports.
            residual = values[LOAD_COLUMN].copy()
            for column in RES_COLUMNS:
                residual = residual - values[column]
            values[RESIDUAL_LOAD_COLUMN] = residual
            stacked = pd.concat(
                [info[LOAD_COLUMN]] + [info[c] for c in RES_COLUMNS], axis=1
            )
            info[RESIDUAL_LOAD_COLUMN] = stacked.max(axis=1)
            report.column_vintage[RESIDUAL_LOAD_COLUMN] = (
                f"derived: {LOAD_COLUMN} - {WIND_COLUMN} - {SOLAR_COLUMN}, each at "
                f"this variant's own vintage; information time is the latest of the three"
            )

    exog_columns = list(values)
    frame = pd.DataFrame(values, index=index)
    info_frame = pd.DataFrame({c: info[c] for c in exog_columns}, index=index)

    acknowledged: list[str] = []
    if resolved.acknowledges_late_columns:
        acknowledged = [c for c in exog_columns if c != LOAD_COLUMN]
    report.acknowledged_late_columns = list(acknowledged)

    if mask:
        maskable = [c for c in exog_columns if c not in acknowledged]
        if maskable:
            before = frame[maskable].notna()
            masked, mask_report = mask_unavailable(
                frame[maskable], info_frame[maskable], matrix.gate_closure
            )
            for column in maskable:
                frame[column] = masked[column]
            report.masked_per_column = dict(mask_report.masked_per_column)
            # The persistence offset is late only on the autumn-DST long day,
            # where t-24h lands on the target day's own first hour. Counted as
            # distinct *rows*, not as cells: one such row blanks wind, solar and
            # the residual-load column it feeds, and reporting 3 would overstate
            # how often this happens by a factor of the column count.
            if resolved.variant == "res_persistence":
                blanked = before & masked.isna()
                report.persistence_masked_dst_rows = int(blanked.any(axis=1).sum())
                report.persistence_masked_dst_timestamps = [
                    ts.isoformat() for ts in frame.index[blanked.any(axis=1)]
                ]

    combined = pd.concat([matrix.features, frame], axis=1)
    combined_info = pd.concat([matrix.information_times, info_frame], axis=1)
    if combined.columns.has_duplicates:
        duplicated = sorted(set(combined.columns[combined.columns.duplicated()]))
        raise ExogFeatureError(
            f"{matrix.zone}: exogenous column(s) {duplicated} already exist in the "
            f"price matrix — refusing to shadow a built column"
        )

    report.exogenous_columns = exog_columns
    present = frame.notna().all(axis=1)
    report.n_rows_with_all_exogenous = int(present.sum())
    if bool(present.any()):
        report.first_complete_exogenous_utc = index[present][0].isoformat()
    report.coverage_per_column = {
        column: round(float(frame[column].notna().mean()), 6) for column in exog_columns
    }
    source_attrs = exog.attrs
    report.exogenous_source = {
        "leakage_status": source_attrs.get("leakage_status"),
        "flagged_columns": list(source_attrs.get("flagged_columns") or []),
        "native_resolutions_seconds": list(
            source_attrs.get("native_resolutions_seconds") or []
        ),
        "unit": source_attrs.get("unit"),
    }

    augmented = matrix.with_features(combined, combined_info)
    if check:
        context = f"{matrix.zone} {resolved.variant} matrix (attach_exogenous)"
        if acknowledged:
            report.acknowledged_violations = [
                v.as_dict()
                for v in assert_only_acknowledged_leakage(
                    augmented, acknowledged, clocks, context
                )
            ]
        else:
            augmented.assert_clean(context)
    return augmented, report


# ---------------------------------------------------------------------------
# The acknowledgement check
# ---------------------------------------------------------------------------


def assert_only_acknowledged_leakage(
    matrix: FeatureMatrix,
    acknowledged: list[str],
    clocks: dict[str, PublicationClock] | None = None,
    context: str = "feature matrix",
) -> list[LeakageViolation]:
    """Permit exactly the declared leak, and nothing else. Returns what it permitted.

    This is the only door through which a post-gate-closure column may reach a
    model in this repo, and it is deliberately narrow. A violation is permitted
    only if **all** of the following hold:

    * its column is in ``acknowledged`` — the caller named it, in advance;
    * its kind is ``after_gate_closure`` — an undeclared or malformed
      information time is never acknowledgeable, because then nobody knows
      what is being permitted;
    * its worst lateness equals what the declared publication clock predicts,
      to the minute. A column late by *more* than its clock says is not the
      known leak, it is a different and unexamined one.

    Anything else raises :class:`forecast.leakage.LeakageError`, so a genuine
    leak in a price lag cannot hide behind the RES acknowledgement. An
    acknowledged column that turns out **not** to be late also raises: the arm
    exists to measure a leak, and silently measuring nothing would be reported
    as a finding about forecasting.
    """
    violations = find_leakage(
        matrix.features,
        matrix.information_times,
        matrix.gate_closure,
        matrix.deterministic,
    )
    acknowledged_set = set(acknowledged)
    unknown = sorted(acknowledged_set - set(matrix.features.columns))
    if unknown:
        raise LeakageError(
            f"{context}: acknowledged column(s) {unknown} are not in the matrix — "
            f"the acknowledgement does not describe this matrix"
        )

    permitted: list[LeakageViolation] = []
    refused: list[str] = []
    for violation in violations:
        if violation.column not in acknowledged_set:
            refused.append(violation.describe())
            continue
        if violation.kind != "after_gate_closure":
            refused.append(
                f"{violation.describe()} [acknowledgement covers only "
                f"'after_gate_closure', not {violation.kind!r}]"
            )
            continue
        permitted.append(violation)

    seen = {v.column for v in permitted}
    silent = sorted(acknowledged_set - seen)
    if silent:
        refused.append(
            f"acknowledged column(s) {silent} produced no after_gate_closure "
            f"violation. This arm exists to measure a known leak; a leak that "
            f"does not appear means the publication clock, the vintage or the "
            f"gate-closure convention has changed, and the measurement would be "
            f"of something else."
        )

    if clocks is not None:
        for violation in permitted:
            expected = _expected_lateness(violation.column, clocks)
            actual = violation.worst_lateness
            if actual is None or pd.Timedelta(actual) != expected:
                refused.append(
                    f"{violation.describe()} [declared clock predicts a worst "
                    f"lateness of exactly {expected}, measured {actual}]"
                )

    if refused:
        lines = "\n  ".join(refused)
        raise LeakageError(
            f"{context} fails the gate-closure contract beyond what was "
            f"acknowledged ({len(refused)} unacknowledged finding(s)):\n  {lines}"
        )
    return permitted


def _expected_lateness(
    column: str, clocks: dict[str, PublicationClock]
) -> pd.Timedelta:
    """How late the declared clock says this column is, at worst.

    Both the gate and the publication are wall-clock times in the same tz
    (``Europe/Brussels`` for the gate, and for these documents), and both sit far
    from a DST transition, so the difference is the plain wall-clock difference
    and is constant across the year. The derived residual-load column inherits
    the latest of its inputs.
    """
    from forecast.timing import gate_closure_convention

    convention = gate_closure_convention()
    if column == RESIDUAL_LOAD_COLUMN:
        sources = [LOAD_COLUMN, *RES_COLUMNS]
    else:
        sources = [column]

    worst = pd.Timedelta(0)
    for source in sources:
        clock = column_clock(source, clocks)
        if clock.tz != convention.tz:
            raise ExogFeatureError(
                f"{source}: publication clock is in {clock.tz} but gate closure is in "
                f"{convention.tz}; the constant-lateness argument does not hold across "
                f"two zones, so this refuses rather than approximating"
            )
        published = dt.datetime.combine(dt.date(2000, 1, 1), clock.local_time) + dt.timedelta(
            days=clock.day_offset
        )
        gate = dt.datetime.combine(dt.date(2000, 1, 1), convention.gate_local_time) - ONE_DAY
        worst = max(worst, pd.Timedelta(published - gate))
    return worst


def variant_is_monotone_in_information(variants: list[str]) -> bool:
    """Are these variants listed in the ladder's own order?

    Used by the runner to state the monotonicity expectation it is about to check
    against the measured scores, rather than hardcoding an ordering twice.
    """
    order = {name: position for position, name in enumerate(EXOG_VARIANTS)}
    positions = [order[v] for v in variants]
    return positions == sorted(positions)


def exogenous_feature_names(config: dict[str, Any] | None = None) -> dict[str, str]:
    """``{features.yaml name: built column name}`` for the exogenous block.

    ``config/features.yaml`` declares ``load_forecast_da``; C7's loader produces
    ``load_forecast_da_mw``, because the unit matters once three MW series sit
    beside a price in EUR/MWh. NOTE C7-01 recorded the two spellings and the
    human resolution (option (a): keep both, document the mapping). This function
    *is* that mapping, derived rather than written down twice, so a rename in
    either file shows up as a missing key instead of silently drifting.
    """
    from data.config import load_feature_config

    declared = [
        entry["name"]
        for entry in (load_feature_config().get("exogenous") or [])
        if entry.get("name")
    ]
    built = {
        series.name
        for document in load_documents(config).values()
        for series in document.series
    } | {RESIDUAL_LOAD_COLUMN}
    mapping: dict[str, str] = {}
    for name in declared:
        candidate = f"{name}_mw"
        if candidate not in built:
            raise ExogFeatureError(
                f"config/features.yaml declares exogenous feature {name!r}, but no "
                f"built column {candidate!r} exists (built: {sorted(built)}). The two "
                f"config files have drifted — see NOTE C7-01."
            )
        mapping[name] = candidate
    return mapping


__all__ = [
    "EXOG_VARIANTS",
    "LEAK_FREE_VARIANTS",
    "RES_COLUMNS",
    "ExogAttachReport",
    "ExogFeatureError",
    "ExogSpec",
    "FeatureError",
    "PublicationClock",
    "assert_only_acknowledged_leakage",
    "attach_exogenous",
    "column_clock",
    "exogenous_feature_names",
    "publication_clocks",
    "publication_instants",
    "variant_is_monotone_in_information",
]
