"""Executable data contracts over the stitched exogenous (ENTSO-E) series.

The C7 counterpart to :mod:`data.contracts`. Same three design choices, for the
same reasons:

* **Nothing is ever repaired here.** Every function *reports*. A gap stays a
  gap; a NaN stays a NaN. :func:`assert_exog_contract` turns a report into an
  exception. Silently reindexing to the expected shape is precisely the failure
  mode these contracts exist to catch.
* **UTC days and local days are checked separately, and they are different
  contracts.** Reused verbatim from :mod:`data.contracts` — a UTC day always
  holds ``86400/resolution`` intervals, while a local calendar day holds 23, 24
  or 25 hours according to the tz-database transition calendar.
* **A deviation is evidence, not an excuse to change the contract.**

**This module does not edit** :mod:`data.contracts`. CLAUDE.md forbids touching
a data-contract or leakage-assertion file without flagging and stopping first,
and the C2 tests pin that module's behaviour. PLAN.md's C7 line asks to "extend
manifest/contracts", so the extension is additive: every primitive check
(:func:`data.contracts.gap_report`, :func:`~data.contracts.check_utc_day_counts`,
:func:`~data.contracts.check_local_day_counts`,
:func:`~data.contracts.dst_transition_days`, …) is *imported and reused*, and
only the things the price contract cannot express live here.

What this adds over the price contract
--------------------------------------
Four checks that are specific to a forecast quantity in MW:

1. **Non-negativity.** A day-ahead load or RES forecast below zero is a source
   defect. (Contrast a *price*, where a negative value is a real market
   outcome — which is why this cannot be folded into the price contract.)
2. **Not identically constant**, reported rather than failed. NO2's solar
   forecast really is ``0.0`` for every hour of every year, because NO2 has no
   solar fleet; DE-LU's load forecast being constant would be a broken feed.
   The report states it and a human reads it.
3. **The SDAC 15-minute cutover rule does not apply.** These series are
   published at whatever resolution the TSO chooses — DE-LU and ES at PT15M
   from the start, NO2 at PT60M — so a resolution *change* is reported but is
   not automatically a violation the way it is for a day-ahead price series.
4. **The declared leakage status travels into the report.** The A69 wind/solar
   vintage is published after gate closure (PLAN.md), so every committed
   artefact says so where a human will see it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from data.config import load_data_config, load_zones
from data.contracts import (
    DataContractViolation,
    DayCountViolation,
    Gap,
    ResolutionChange,
    ResolutionSegment,
    check_local_day_counts,
    check_utc_day_counts,
    detect_resolution_changes,
    dst_transition_days,
    gap_report,
    index_is_utc,
    modal_resolution_seconds,
    resolution_segments,
)
from data.entsoe import load_documents, series_owner
from data.exog_manifest import series_fingerprint
from data.exogenous import RESIDUAL_LOAD_COLUMN, column_leakage_status


@dataclass
class ExogContractReport:
    """Everything the contracts found for one (zone, series). Serialisable."""

    zone: str
    tier: str
    local_tz: str
    series: str
    document: str
    leakage_status: str
    years: list[int]
    n_points: int
    first_ts_utc: str
    last_ts_utc: str
    modal_resolution_seconds: int
    payload_sha256: str
    index_is_utc: bool
    index_is_monotonic: bool
    n_duplicate_timestamps: int
    n_nan_values: int
    nan_timestamps_utc: list[str] = field(default_factory=list)
    n_negative_values: int = 0
    negative_timestamps_utc: list[str] = field(default_factory=list)
    is_constant: bool = False
    constant_value: float | None = None
    mw_min: float | None = None
    mw_max: float | None = None
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
    n_partial_psr_intervals: int = 0
    zero_components: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    may_be_negative: bool = False

    @property
    def violations(self) -> list[str]:
        """Every hard failure, as human-readable lines. Empty means it holds.

        **The dividing line, stated once.** For this source a finding is a hard
        failure if it means *we* got something wrong, and a reported note if it
        means the *source* is ragged in a way we understand:

        * **Integrity findings are violations** — a non-UTC or non-monotonic
          index, duplicate timestamps, a negative value in a quantity that
          cannot be negative, or a day holding *more* rows than it should
          (which can only come from duplicate or misaligned timestamps, i.e. a
          stitching bug).
        * **Completeness findings are notes** — gaps, NaNs, and a day holding
          *fewer* rows than it should. These series are genuinely ragged: the
          German and Spanish day-ahead publications each drop one hour at the
          autumn DST boundary (see :mod:`data.entsoe`). CLAUDE.md's answer to a
          source gap is to flag it and skip only the dependent work, and this
          project never fills a gap, so failing here would discard whole
          training years over one known hour a year while telling a human
          nothing the gap count does not already say.

        A shortfall and a gap are the same fact counted twice, which is why
        only one of them is a failure. ``n_missing_intervals`` and
        :attr:`notes` carry the detail into the committed report, where C8 must
        read them before building these columns into a model.
        """
        out: list[str] = []
        if not self.index_is_utc:
            out.append("index is not tz-aware UTC")
        if not self.index_is_monotonic:
            out.append("index is not monotonic increasing")
        if self.n_duplicate_timestamps:
            out.append(f"{self.n_duplicate_timestamps} duplicate timestamp(s)")
        if self.n_negative_values and not self.may_be_negative:
            out.append(
                f"{self.n_negative_values} negative value(s) in a MW forecast, "
                f"first at "
                f"{self.negative_timestamps_utc[0] if self.negative_timestamps_utc else '?'}"
            )
        out.extend(
            v.describe() for v in self.utc_day_violations if v.actual > v.expected
        )
        out.extend(
            v.describe() for v in self.local_day_violations if v.actual > v.expected
        )
        return out

    @property
    def ok(self) -> bool:
        return not self.violations

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "tier": self.tier,
            "local_tz": self.local_tz,
            "series": self.series,
            "document": self.document,
            "leakage_status": self.leakage_status,
            "years": self.years,
            "n_points": self.n_points,
            "first_ts_utc": self.first_ts_utc,
            "last_ts_utc": self.last_ts_utc,
            "modal_resolution_seconds": self.modal_resolution_seconds,
            "payload_sha256": self.payload_sha256,
            "index_is_utc": self.index_is_utc,
            "index_is_monotonic": self.index_is_monotonic,
            "n_duplicate_timestamps": self.n_duplicate_timestamps,
            "n_nan_values": self.n_nan_values,
            "nan_timestamps_utc": self.nan_timestamps_utc,
            "n_negative_values": self.n_negative_values,
            "negative_timestamps_utc": self.negative_timestamps_utc,
            "is_constant": self.is_constant,
            "constant_value": self.constant_value,
            "mw_min": self.mw_min,
            "mw_max": self.mw_max,
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
            "n_partial_psr_intervals": self.n_partial_psr_intervals,
            "zero_components": self.zero_components,
            "may_be_negative": self.may_be_negative,
            "notes": self.notes,
            "ok": self.ok,
            "violations": self.violations,
        }


def _document_for(series: str, config: dict[str, Any] | None = None) -> str:
    if series == RESIDUAL_LOAD_COLUMN:
        return "derived"
    return series_owner(series, config).key


def series_may_be_negative(series: str, config: dict[str, Any] | None = None) -> bool:
    """Whether a negative value in this series is real data or a defect.

    Config-driven for the fetched series (``non_negative`` in
    ``config/data.yaml``): a day-ahead load, wind or solar forecast below zero
    is a source defect.

    ``residual_load_forecast_mw`` is the deliberate exception, and the sign is
    the whole point of it. Residual load is ``load - wind - solar``; when
    renewable output exceeds demand it goes **negative**, and that is exactly
    the condition that produces negative day-ahead prices. It is the headline
    quantity of PLAN.md's C14 fundamentals chapter, so flagging its negative
    hours as a contract violation would flag the very signal the chapter is
    about. (C7 observed 262 such hours for DE-LU and 317 for ES across
    2022-2024, first for DE-LU at 2022-03-20T11:00Z — a sunny, windy Sunday
    midday.)
    """
    if series == RESIDUAL_LOAD_COLUMN:
        return True
    for doc in load_documents(config).values():
        for spec in doc.series:
            if spec.name == series:
                return not spec.non_negative
    return False


def build_exog_contract_report(
    zone_key: str,
    series: str,
    frame: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> ExogContractReport:
    """Run every contract over one (zone, series) stitched column and report."""
    cfg = config or load_data_config()
    zone = load_zones()[zone_key]

    if series not in frame.columns:
        raise DataContractViolation(
            f"{zone_key}: frame has no {series!r} column (got {list(frame.columns)})"
        )
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        raise DataContractViolation(
            f"{zone_key}/{series}: index is a {type(index).__name__}, expected a "
            f"DatetimeIndex"
        )
    if len(index) < 2:
        raise DataContractViolation(f"{zone_key}/{series}: only {len(index)} row(s)")

    values = frame[series]
    resolution = modal_resolution_seconds(index)
    gaps, n_missing, max_gap_hours = gap_report(index, resolution)
    utc_violations, n_utc_days, boundary = check_utc_day_counts(index, resolution)
    local_violations, n_local_days, n_dst = check_local_day_counts(
        index, zone.local_tz, resolution
    )
    changes = detect_resolution_changes(index)

    years = sorted({int(y) for y in index.year.unique()})
    nan_mask = values.isna()
    finite = values.dropna()
    negative_mask = values < 0

    may_be_negative = series_may_be_negative(series, cfg)

    notes: list[str] = []
    if n_missing:
        notes.append(
            f"{n_missing} missing interval(s) in {len(gaps)} gap(s), largest "
            f"{max_gap_hours}h — reported, not filled (see data/entsoe.py on the "
            f"DST-day publication gap)"
        )
    if int(nan_mask.sum()):
        notes.append(
            f"{int(nan_mask.sum())} NaN value(s) — a UTC hour not tiled exactly "
            f"by its sub-hourly intervals, or covered by only some of the summed "
            f"psrTypes; kept NaN rather than partially averaged or partially summed"
        )
    shortfalls = [
        v for v in (utc_violations + local_violations) if v.actual < v.expected
    ]
    if shortfalls:
        notes.append(
            f"{len(shortfalls)} day(s) hold fewer rows than expected, e.g. "
            f"{shortfalls[0].describe()} — a completeness finding, the same fact "
            f"as the gap count above; see this report's `violations` for the "
            f"integrity findings that are failures"
        )
    if may_be_negative and int(negative_mask.sum()):
        notes.append(
            f"{int(negative_mask.sum())} negative value(s) — real and expected "
            f"for this series: residual load goes negative when wind + solar "
            f"exceed load, which is the condition that drives negative prices"
        )
    if changes:
        notes.append(
            f"{len(changes)} resolution change(s), e.g. at "
            f"{changes[0].at_utc.isoformat()} ({changes[0].from_seconds}s -> "
            f"{changes[0].to_seconds}s) — the SDAC 15-minute cutover rule does "
            f"not apply to an ENTSO-E forecast series; TSOs publish at their own "
            f"resolution"
        )

    is_constant = bool(len(finite) > 0 and finite.nunique() == 1)
    if is_constant:
        notes.append(
            f"series is identically {float(finite.iloc[0])} over {len(finite)} "
            f"point(s) — real for a zone with no such fleet (NO2 solar), a broken "
            f"feed anywhere else"
        )

    attrs_partial = frame.attrs.get("n_partial_psr_intervals", 0)
    zero_components = dict(frame.attrs.get("zero_components") or {})
    if zero_components:
        notes.append(
            f"psrType component(s) treated as structurally zero where unpublished: "
            f"{zero_components} — each was 0.0 at every point it *was* published"
        )

    return ExogContractReport(
        zone=zone_key,
        tier=zone.tier,
        local_tz=zone.local_tz,
        series=series,
        document=_document_for(series, cfg),
        leakage_status=column_leakage_status(series, cfg),
        years=years,
        n_points=int(len(index)),
        first_ts_utc=index[0].isoformat(),
        last_ts_utc=index[-1].isoformat(),
        modal_resolution_seconds=resolution,
        payload_sha256=series_fingerprint(frame, series),
        index_is_utc=index_is_utc(index),
        index_is_monotonic=bool(index.is_monotonic_increasing),
        n_duplicate_timestamps=int(index.duplicated().sum()),
        n_nan_values=int(nan_mask.sum()),
        nan_timestamps_utc=[t.isoformat() for t in index[nan_mask][:20]],
        n_negative_values=int(negative_mask.sum()),
        negative_timestamps_utc=[t.isoformat() for t in index[negative_mask][:20]],
        is_constant=is_constant,
        constant_value=float(finite.iloc[0]) if is_constant else None,
        mw_min=round(float(finite.min()), 3) if len(finite) else None,
        mw_max=round(float(finite.max()), 3) if len(finite) else None,
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
        dst_whitelist_days={str(d): h for d, h in sorted(
            dst_transition_days(zone.local_tz, years).items()
        )},
        n_dst_days_seen=n_dst,
        n_partial_psr_intervals=int(attrs_partial),
        zero_components=zero_components,
        may_be_negative=may_be_negative,
        notes=notes,
    )


def assert_exog_contract(report: ExogContractReport) -> None:
    """Raise :class:`DataContractViolation` if anything in ``report`` failed.

    Never caught in order to press on with modelling. If this fires, the fix is
    to the data or the loader — not to the contract.
    """
    if report.ok:
        return
    lines = "\n  - ".join(report.violations)
    raise DataContractViolation(
        f"{report.zone}/{report.series}: exogenous data contract violated "
        f"({len(report.violations)} finding(s)):\n  - {lines}"
    )


def expected_series(config: dict[str, Any] | None = None) -> list[str]:
    """Every configured exogenous column, plus the derived residual load."""
    cfg = config or load_data_config()
    names = [s.name for doc in load_documents(cfg).values() for s in doc.series]
    return names + [RESIDUAL_LOAD_COLUMN]


def utc_day_length_hours(day: dt.date) -> int:
    """A UTC day is always 24 hours. Here so a caller need not re-derive it."""
    return 24
