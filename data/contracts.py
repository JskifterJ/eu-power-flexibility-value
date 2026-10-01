"""Executable data contracts over the stitched price series.

CLAUDE.md: *"Assert expected row count per (zone, day) against a DST whitelist
rather than silently dropping/filling on a mismatch."* This module is that
assertion, plus the two other things C2 owes: detection of the 2025-10-01
hourly -> 15-minute resolution cutover, and a gap report.

Three deliberate design choices:

* **Nothing is ever repaired here.** Every function *reports*. A gap stays a
  gap; a short day stays short. :func:`assert_contract` turns a report into an
  exception. Silently reindexing to the expected shape is precisely the failure
  mode these contracts exist to catch.
* **UTC days and local days are checked separately, and they are different
  contracts.** A UTC day always holds 24 hourly intervals — UTC has no DST — so
  a UTC-day count that isn't 24 is unambiguously a data defect. A *local*
  calendar day holds 23, 24 or 25 hours depending on the DST transition
  calendar, so its expected count comes from a whitelist. The whitelist is
  *derived* from the zone's IANA timezone (:func:`dst_transition_days`), not
  hardcoded, so it cannot drift from reality.
* **The cutover is a permitted change at one known instant, and a defect
  anywhere else.** ``resolution_seconds`` changing mid-series is how the SDAC
  15-minute go-live will arrive (see ``PLAN.md``); a change *before* that
  instant is a source defect or a stitching bug.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from data.config import load_data_config, load_zones
from data.energy_charts import PRICE_COLUMN

SECONDS_PER_HOUR = 3600
HOURLY_SECONDS = 3600
QUARTER_HOURLY_SECONDS = 900


class DataContractViolation(AssertionError):
    """A committed data contract does not hold. Never caught to "fix" the data."""


# ---------------------------------------------------------------------------
# The DST whitelist — derived from the tz database, not hardcoded
# ---------------------------------------------------------------------------


def local_day_hours(day: dt.date, tz_name: str) -> int:
    """Length in hours of one *local calendar* day: 23, 24 or 25 in the EU.

    Computed from local midnight to the next local midnight via UTC, so it is
    whatever the tz database says rather than whatever we remember.
    """
    tz = ZoneInfo(tz_name)
    start = dt.datetime(day.year, day.month, day.day, tzinfo=tz)
    nxt = day + dt.timedelta(days=1)
    end = dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    seconds = (end.astimezone(dt.timezone.utc) - start.astimezone(dt.timezone.utc)).total_seconds()
    if seconds % SECONDS_PER_HOUR:
        raise DataContractViolation(
            f"{tz_name} {day}: local day is {seconds}s, not a whole number of hours"
        )
    return int(seconds // SECONDS_PER_HOUR)


def dst_transition_days(tz_name: str, years: list[int]) -> dict[dt.date, int]:
    """``{local date: length in hours}`` for every non-24h local day in ``years``.

    This is the DST whitelist. A local day whose row count deviates from 24 is
    acceptable **only** if it appears here with a matching length.
    """
    out: dict[dt.date, int] = {}
    for year in sorted(set(years)):
        day = dt.date(year, 1, 1)
        while day.year == year:
            hours = local_day_hours(day, tz_name)
            if hours != 24:
                out[day] = hours
            day += dt.timedelta(days=1)
    return out


def expected_intervals_for_local_day(
    day: dt.date, tz_name: str, resolution_seconds: int = HOURLY_SECONDS
) -> int:
    """Rows a local calendar day should hold at a given resolution."""
    hours = local_day_hours(day, tz_name)
    total = hours * SECONDS_PER_HOUR
    if total % resolution_seconds:
        raise DataContractViolation(
            f"{tz_name} {day}: {total}s is not a whole multiple of {resolution_seconds}s"
        )
    return total // resolution_seconds


def expected_intervals_for_utc_day(resolution_seconds: int = HOURLY_SECONDS) -> int:
    """Rows a UTC day should hold. Constant: UTC has no DST discontinuity."""
    if 86400 % resolution_seconds:
        raise DataContractViolation(
            f"86400s is not a whole multiple of {resolution_seconds}s"
        )
    return 86400 // resolution_seconds


def payload_fingerprint(frame: pd.DataFrame, column: str = PRICE_COLUMN) -> str:
    """A reproducible sha256 over the (UTC epoch, price) pairs themselves.

    Covers only the data, at fixed 6-decimal precision, so two pulls of the same
    (zone, span) agree iff the source really returned the same prices. This is
    also what the manifest's ``payload_sha256`` column calls (PROGRESS.md NOTE
    C2-01): the manifest originally hashed the cached *file* instead, which
    embeds the ``_fetch_meta.fetched_at_utc`` stamp this project writes, so that
    column changed on every re-fetch even when the data was identical. Both
    places now call this one function, so they can never drift apart again.
    """
    lines = (
        f"{int(ts.timestamp())},{'nan' if pd.isna(v) else format(float(v), '.6f')}"
        for ts, v in zip(frame.index, frame[column])
    )
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DayCountViolation:
    scope: str          # "utc" or "local"
    day: dt.date
    expected: int
    actual: int
    note: str = ""

    def describe(self) -> str:
        extra = f" ({self.note})" if self.note else ""
        return (
            f"{self.scope} day {self.day}: expected {self.expected} rows, "
            f"found {self.actual}{extra}"
        )


@dataclass(frozen=True)
class ResolutionSegment:
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    seconds: int
    n_intervals: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "seconds": self.seconds,
            "n_intervals": self.n_intervals,
        }


@dataclass(frozen=True)
class ResolutionChange:
    at_utc: pd.Timestamp
    from_seconds: int
    to_seconds: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "at_utc": self.at_utc.isoformat(),
            "from_seconds": self.from_seconds,
            "to_seconds": self.to_seconds,
        }


@dataclass(frozen=True)
class Gap:
    after_utc: pd.Timestamp
    before_utc: pd.Timestamp
    missing_intervals: int
    hours: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "after_utc": self.after_utc.isoformat(),
            "before_utc": self.before_utc.isoformat(),
            "missing_intervals": self.missing_intervals,
            "hours": self.hours,
        }


@dataclass
class ContractReport:
    """Everything the contracts found for one zone. Serialisable; committed."""

    zone: str
    tier: str
    local_tz: str
    years: list[int]
    n_points: int
    first_ts_utc: str
    last_ts_utc: str
    modal_resolution_seconds: int
    payload_sha256: str
    index_is_utc: bool
    index_is_monotonic: bool
    n_duplicate_timestamps: int
    n_nan_prices: int
    nan_timestamps_utc: list[str] = field(default_factory=list)
    resolution_segments: list[ResolutionSegment] = field(default_factory=list)
    resolution_changes: list[ResolutionChange] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    n_missing_intervals: int = 0
    max_gap_hours: float = 0.0
    utc_day_violations: list[DayCountViolation] = field(default_factory=list)
    local_day_violations: list[DayCountViolation] = field(default_factory=list)
    n_utc_days_checked: int = 0
    n_local_days_checked: int = 0
    boundary_partial_days: list[str] = field(default_factory=list)
    dst_whitelist_days: dict[str, int] = field(default_factory=dict)
    n_dst_days_seen: int = 0
    cutover_violations: list[str] = field(default_factory=list)

    @property
    def violations(self) -> list[str]:
        """Every hard failure, as human-readable lines. Empty means the contract holds."""
        out: list[str] = []
        if not self.index_is_utc:
            out.append("index is not tz-aware UTC")
        if not self.index_is_monotonic:
            out.append("index is not monotonic increasing")
        if self.n_duplicate_timestamps:
            out.append(f"{self.n_duplicate_timestamps} duplicate timestamp(s)")
        if self.n_nan_prices:
            out.append(
                f"{self.n_nan_prices} NaN price(s), first at "
                f"{self.nan_timestamps_utc[0] if self.nan_timestamps_utc else '?'}"
            )
        if self.n_missing_intervals:
            out.append(
                f"{self.n_missing_intervals} missing interval(s) in "
                f"{len(self.gaps)} gap(s), largest {self.max_gap_hours}h"
            )
        out.extend(v.describe() for v in self.utc_day_violations)
        out.extend(v.describe() for v in self.local_day_violations)
        out.extend(self.cutover_violations)
        return out

    @property
    def ok(self) -> bool:
        return not self.violations

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "tier": self.tier,
            "local_tz": self.local_tz,
            "years": self.years,
            "n_points": self.n_points,
            "first_ts_utc": self.first_ts_utc,
            "last_ts_utc": self.last_ts_utc,
            "modal_resolution_seconds": self.modal_resolution_seconds,
            "payload_sha256": self.payload_sha256,
            "index_is_utc": self.index_is_utc,
            "index_is_monotonic": self.index_is_monotonic,
            "n_duplicate_timestamps": self.n_duplicate_timestamps,
            "n_nan_prices": self.n_nan_prices,
            "nan_timestamps_utc": self.nan_timestamps_utc,
            "resolution_segments": [s.as_dict() for s in self.resolution_segments],
            "resolution_changes": [c.as_dict() for c in self.resolution_changes],
            "gaps": [g.as_dict() for g in self.gaps],
            "n_missing_intervals": self.n_missing_intervals,
            "max_gap_hours": self.max_gap_hours,
            "n_utc_days_checked": self.n_utc_days_checked,
            "n_local_days_checked": self.n_local_days_checked,
            "utc_day_violations": [v.describe() for v in self.utc_day_violations],
            "local_day_violations": [v.describe() for v in self.local_day_violations],
            "boundary_partial_days": self.boundary_partial_days,
            "n_dst_days_seen": self.n_dst_days_seen,
            "dst_whitelist_days": self.dst_whitelist_days,
            "cutover_violations": self.cutover_violations,
            "ok": self.ok,
            "violations": self.violations,
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _as_index(obj: pd.DataFrame | pd.Series | pd.DatetimeIndex) -> pd.DatetimeIndex:
    if isinstance(obj, pd.DatetimeIndex):
        return obj
    index = obj.index
    if not isinstance(index, pd.DatetimeIndex):
        raise DataContractViolation(
            f"index is a {type(index).__name__}, expected a DatetimeIndex"
        )
    return index


def index_is_utc(index: pd.DatetimeIndex) -> bool:
    """True only for a tz-aware index whose offset is exactly UTC."""
    if index.tz is None:
        return False
    return index.tz.utcoffset(None) == dt.timedelta(0) if hasattr(index.tz, "utcoffset") \
        else str(index.tz) == "UTC"


def modal_resolution_seconds(index: pd.DatetimeIndex) -> int:
    """Most common spacing, in whole seconds. Raises on a single-point index."""
    if len(index) < 2:
        raise DataContractViolation(
            f"cannot infer resolution from {len(index)} point(s)"
        )
    deltas = pd.Series(index).diff().dropna().dt.total_seconds()
    return int(deltas.mode().iloc[0])


def resolution_segments(index: pd.DatetimeIndex) -> list[ResolutionSegment]:
    """Run-length encoding of the spacing: one segment per constant-resolution run.

    A gap at a constant resolution shows up as a one-off long delta, so segments
    are keyed on the delta value; :func:`gap_report` is what distinguishes
    "missing rows" from "the resolution changed".
    """
    if len(index) < 2:
        return []
    deltas = pd.Series(index).diff().dropna().dt.total_seconds().astype("int64").tolist()
    segments: list[ResolutionSegment] = []
    run_start_i, run_value = 0, deltas[0]
    for i, value in enumerate(deltas + [None]):
        if value != run_value:
            segments.append(
                ResolutionSegment(
                    start_utc=index[run_start_i],
                    end_utc=index[i],
                    seconds=int(run_value),
                    n_intervals=i - run_start_i,
                )
            )
            if value is None:
                break
            run_start_i, run_value = i, value
    return segments


def detect_resolution_changes(
    index: pd.DatetimeIndex, min_run_intervals: int = 2
) -> list[ResolutionChange]:
    """Resolution *changes*, ignoring one-off long deltas (those are gaps).

    A run shorter than ``min_run_intervals`` is treated as a gap/anomaly, not as
    a genuine market-time-unit change: the 15-minute cutover is permanent, so it
    produces a long run, whereas a missing hour produces a run of length 1.

    Dropping those short runs can leave two runs of the *same* resolution next to
    each other — hourly, one missing hour, hourly again — which is a gap, not a
    change. Same-resolution neighbours are therefore merged before changes are
    read off, so a dropped hour never masquerades as a market-time-unit change.
    """
    kept = [s for s in resolution_segments(index) if s.n_intervals >= min_run_intervals]
    merged: list[ResolutionSegment] = []
    for segment in kept:
        if merged and merged[-1].seconds == segment.seconds:
            previous = merged[-1]
            merged[-1] = ResolutionSegment(
                start_utc=previous.start_utc,
                end_utc=segment.end_utc,
                seconds=segment.seconds,
                n_intervals=previous.n_intervals + segment.n_intervals,
            )
            continue
        merged.append(segment)
    return [
        ResolutionChange(
            at_utc=current.start_utc,
            from_seconds=previous.seconds,
            to_seconds=current.seconds,
        )
        for previous, current in zip(merged, merged[1:])
    ]


def gap_report(
    index: pd.DatetimeIndex, resolution_seconds: int | None = None
) -> tuple[list[Gap], int, float]:
    """``(gaps, n_missing_intervals, max_gap_hours)`` against the local resolution.

    "Local resolution" means the resolution in force on each side of the step, so
    a series that legitimately changes from 3600s to 900s does not report the
    whole 15-minute tail as one enormous gap. A step that is an exact multiple of
    the in-force resolution and larger than it is a gap of
    ``multiple - 1`` missing intervals.
    """
    if len(index) < 2:
        return [], 0, 0.0
    default = resolution_seconds or modal_resolution_seconds(index)
    known = {default}
    for segment in resolution_segments(index):
        if segment.n_intervals >= 2:
            known.add(segment.seconds)

    gaps: list[Gap] = []
    total_missing = 0
    max_hours = 0.0
    deltas = pd.Series(index).diff().dt.total_seconds().astype("Int64")
    for i in range(1, len(index)):
        step = int(deltas.iloc[i])
        if step in known:
            continue
        # Smallest known resolution the step is a clean multiple of.
        base = next((r for r in sorted(known) if step % r == 0 and step > r), None)
        missing = (step // base - 1) if base else 0
        if base is None:
            missing = 0  # ragged, non-multiple step: still reported as a gap
        gaps.append(
            Gap(
                after_utc=index[i - 1],
                before_utc=index[i],
                missing_intervals=int(missing),
                hours=round(step / SECONDS_PER_HOUR, 4),
            )
        )
        total_missing += int(missing)
        max_hours = max(max_hours, step / SECONDS_PER_HOUR)
    return gaps, total_missing, round(max_hours, 4)


def utc_day_counts(index: pd.DatetimeIndex) -> pd.Series:
    """Rows per UTC calendar date."""
    return pd.Series(1, index=index).groupby(index.date).size()


def local_day_counts(index: pd.DatetimeIndex, tz_name: str) -> pd.Series:
    """Rows per *local* calendar date. The tz is used for grouping only, never
    for resampling or alignment — the index itself stays UTC."""
    local = index.tz_convert(ZoneInfo(tz_name))
    return pd.Series(1, index=index).groupby(local.date).size()


def _fully_covered(
    day_start_utc: pd.Timestamp,
    day_seconds: int,
    resolution_seconds: int,
    first_ts: pd.Timestamp,
    last_ts: pd.Timestamp,
) -> bool:
    """True if the series spans every interval that day should contain.

    A day at the edge of the series may be genuinely incomplete — the first
    cached file starts mid-UTC-day — and counting rows on it would report a
    violation that is really just the window boundary. Completeness is decided
    from the expected interval *timestamps*, not by assuming the first and last
    day are always partial: for the CET zones in scope the local-day view happens
    to be complete at both ends, and those days should still be checked.
    """
    last_expected = day_start_utc + pd.Timedelta(seconds=day_seconds - resolution_seconds)
    return day_start_utc >= first_ts and last_expected <= last_ts


def check_utc_day_counts(
    index: pd.DatetimeIndex, resolution_seconds: int | None = None
) -> tuple[list[DayCountViolation], int, list[str]]:
    """Every fully covered UTC day must hold exactly ``86400 / resolution`` rows."""
    resolution = resolution_seconds or modal_resolution_seconds(index)
    counts = utc_day_counts(index)
    expected = expected_intervals_for_utc_day(resolution)
    first_ts, last_ts = index[0], index[-1]

    violations: list[DayCountViolation] = []
    boundary: list[str] = []
    n_checked = 0
    for day in counts.index:
        start = pd.Timestamp(day, tz="UTC")
        if not _fully_covered(start, 86400, resolution, first_ts, last_ts):
            boundary.append(str(day))
            continue
        n_checked += 1
        actual = int(counts.loc[day])
        if actual != expected:
            violations.append(
                DayCountViolation("utc", day, expected, actual,
                                  "UTC days have no DST discontinuity")
            )
    return violations, n_checked, boundary


def check_local_day_counts(
    index: pd.DatetimeIndex, tz_name: str, resolution_seconds: int | None = None
) -> tuple[list[DayCountViolation], int, int]:
    """Every interior local day must match the DST-derived expected row count.

    Returns ``(violations, n_days_checked, n_dst_days_seen)``. A 23h or 25h day
    is a *pass* when the tz database says that date is a transition day, and a
    violation otherwise — that is the whitelist working in both directions.
    """
    resolution = resolution_seconds or modal_resolution_seconds(index)
    counts = local_day_counts(index, tz_name)
    first_ts, last_ts = index[0], index[-1]
    violations: list[DayCountViolation] = []
    n_dst = 0
    n_checked = 0
    for day in counts.index:
        hours = local_day_hours(day, tz_name)
        start = pd.Timestamp(
            dt.datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz_name)).astimezone(
                dt.timezone.utc
            )
        )
        if not _fully_covered(start, hours * SECONDS_PER_HOUR, resolution, first_ts, last_ts):
            continue
        n_checked += 1
        if hours != 24:
            n_dst += 1
        expected = expected_intervals_for_local_day(day, tz_name, resolution)
        actual = int(counts.loc[day])
        if actual != expected:
            violations.append(
                DayCountViolation(
                    "local", day, expected, actual,
                    f"{tz_name}, {hours}h local day"
                    + (" (DST transition)" if hours != 24 else ""),
                )
            )
    return violations, n_checked, n_dst


def cutover_instant_utc(
    tz_name: str, cutover_date: str | dt.date, config: dict[str, Any] | None = None
) -> pd.Timestamp:
    """The UTC instant the market time unit changes for a zone.

    The SDAC 15-minute go-live is a *market day*: local midnight of
    ``structural_dates.sdac_15min_golive`` in the bidding zone's own timezone,
    expressed in UTC (2025-09-30T22:00Z for a CEST zone).
    """
    day = cutover_date if isinstance(cutover_date, dt.date) else dt.date.fromisoformat(
        str(cutover_date)
    )
    local_midnight = dt.datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz_name))
    return pd.Timestamp(local_midnight.astimezone(dt.timezone.utc))


def check_resolution_cutover(
    index: pd.DatetimeIndex,
    tz_name: str,
    config: dict[str, Any] | None = None,
) -> tuple[list[str], list[ResolutionChange]]:
    """The only permitted resolution change is hourly -> 15-min at the cutover.

    Any other change — a different instant, or a different pair of resolutions —
    is a violation. This is what makes the 2025-10-01 SDAC go-live impossible to
    blend silently into the main hourly backtest.
    """
    cfg = config or load_data_config()
    cutover = cutover_instant_utc(tz_name, cfg["structural_dates"]["sdac_15min_golive"], cfg)
    changes = detect_resolution_changes(index)
    problems: list[str] = []
    for change in changes:
        expected_pair = (
            change.from_seconds == HOURLY_SECONDS
            and change.to_seconds == QUARTER_HOURLY_SECONDS
        )
        if change.at_utc == cutover and expected_pair:
            continue
        problems.append(
            f"resolution changed {change.from_seconds}s -> {change.to_seconds}s at "
            f"{change.at_utc.isoformat()}; the only permitted change is "
            f"{HOURLY_SECONDS}s -> {QUARTER_HOURLY_SECONDS}s at "
            f"{cutover.isoformat()} (SDAC 15-minute go-live, "
            f"{cfg['structural_dates']['sdac_15min_golive']} local)"
        )
    return problems, changes


# ---------------------------------------------------------------------------
# The whole contract for one zone
# ---------------------------------------------------------------------------


def build_contract_report(
    zone_key: str, frame: pd.DataFrame, config: dict[str, Any] | None = None
) -> ContractReport:
    """Run every contract over one zone's stitched series and report."""
    cfg = config or load_data_config()
    zone = load_zones()[zone_key]
    index = _as_index(frame)

    if PRICE_COLUMN not in frame.columns:
        raise DataContractViolation(
            f"{zone_key}: frame has no {PRICE_COLUMN!r} column (got {list(frame.columns)})"
        )
    if len(index) < 2:
        raise DataContractViolation(f"{zone_key}: only {len(index)} row(s)")

    resolution = modal_resolution_seconds(index)
    gaps, n_missing, max_gap_hours = gap_report(index, resolution)
    utc_violations, n_utc_days, boundary = check_utc_day_counts(index, resolution)
    local_violations, n_local_days, n_dst = check_local_day_counts(
        index, zone.local_tz, resolution
    )
    cutover_problems, changes = check_resolution_cutover(index, zone.local_tz, cfg)

    years = sorted({int(y) for y in index.year.unique()})
    nan_mask = frame[PRICE_COLUMN].isna()
    whitelist = dst_transition_days(zone.local_tz, years)

    return ContractReport(
        zone=zone_key,
        tier=zone.tier,
        local_tz=zone.local_tz,
        years=years,
        n_points=int(len(index)),
        first_ts_utc=index[0].isoformat(),
        last_ts_utc=index[-1].isoformat(),
        modal_resolution_seconds=resolution,
        payload_sha256=payload_fingerprint(frame),
        index_is_utc=index_is_utc(index),
        index_is_monotonic=bool(index.is_monotonic_increasing),
        n_duplicate_timestamps=int(index.duplicated().sum()),
        n_nan_prices=int(nan_mask.sum()),
        nan_timestamps_utc=[t.isoformat() for t in index[nan_mask][:20]],
        resolution_segments=resolution_segments(index),
        resolution_changes=changes,
        gaps=gaps[:50],
        n_missing_intervals=n_missing,
        max_gap_hours=max_gap_hours,
        utc_day_violations=utc_violations[:50],
        local_day_violations=local_violations[:50],
        n_utc_days_checked=n_utc_days,
        n_local_days_checked=n_local_days,
        boundary_partial_days=boundary,
        dst_whitelist_days={str(d): h for d, h in sorted(whitelist.items())},
        n_dst_days_seen=n_dst,
        cutover_violations=cutover_problems,
    )


def assert_contract(report: ContractReport) -> None:
    """Raise :class:`DataContractViolation` if anything in ``report`` failed.

    Never caught in order to press on with modelling. If this fires, the fix is
    to the data or the loader — not to the contract.
    """
    if report.ok:
        return
    lines = "\n  - ".join(report.violations)
    raise DataContractViolation(
        f"{report.zone}: data contract violated ({len(report.violations)} finding(s)):\n"
        f"  - {lines}"
    )
