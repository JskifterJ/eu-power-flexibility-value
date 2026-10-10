"""Rolling the day LP forward across a year: market days, carried SoC, and skips.

:mod:`dispatch.battery` solves one horizon. This module decides what a horizon
*is*, what state it opens at, and what to do when a day cannot be dispatched at
all — the three places a dispatch backtest quietly stops being honest.

The horizon is the market day
-----------------------------
Not a UTC day and not 24 rows. The day-ahead auction clears a *local* calendar
day as one block of products, which is 23 or 25 hours twice a year, and a bidder
commits exactly that block. :func:`dispatch.rolling.market_day_blocks` therefore
groups on :func:`forecast.timing.market_days` and asserts each block's length
against :func:`data.contracts.local_day_hours` — the tz database's answer, not a
remembered one. That is the DST whitelist assertion CLAUDE.md requires, applied
to dispatch: a short or long day is accepted when and only when the calendar says
it should be, and is never reindexed or padded to 24.

PLAN.md writes the horizon as "24h, D+1". The 23/25-hour days are that same
convention read off the calendar rather than assumed, and the alternative —
forcing 24 rows — would mean dispatching hours that no auction cleared.

SoC carries, and it carries the *realised* state
------------------------------------------------
Day ``D`` opens at the SoC day ``D-1``'s committed schedule actually ended at.
Nothing resets at midnight (PLAN.md). When a day is skipped the SoC is carried
across the gap unchanged — the battery sat idle, which is what a desk with no
price vector would have done — and the gap is recorded, not smoothed over.

``soc_policy="reset"`` is the one departure, added in C15 as PLAN.md's declared
*daily-reset* sensitivity — the leg that measures what the carryover is worth by
removing it. It is deliberately hard to use wrongly, because the obvious way to
write it invents energy: a reset that opens every day half full while the
horizon's terminal condition lets the LP end the day empty hands the battery
``initial_soc_fraction`` of a capacity, free, 365 times a year, and the extra
cash looks like a sensitivity result. So the reset is accepted only under a
terminal **floor** at or above the opening fraction, where the LP must hand back
at least what it was given and the reset can therefore only ever *discard*
energy, never create it. How much it discarded is counted
(:attr:`RollingResult.soc_reset_discarded_mwh`) rather than assumed to be zero.

A day is skipped, never patched
-------------------------------
Three reasons, each counted and reported in :class:`RollingResult.skipped`:

``incomplete``
    The block holds fewer rows than the local calendar says it should, or a price
    is missing. A day cannot be committed from a partial vector, and filling the
    hole here would be the silent-fill bug :mod:`data.prices` refuses to commit.
``no_reference``
    Fewer than ``min_trailing_days`` of trailing realised prices exist, so
    closing inventory cannot be marked at a price that was knowable at gate
    closure. Only ever the first day or two of a series.
``boundary``
    The block is the partial first/last local day of the loaded window.

The trailing reference price
----------------------------
``p_ref(D)`` is a quantile of realised hourly prices over the last
``trailing_days`` *complete* market days before ``D``. Two properties matter and
both are asserted: it is built only from days whose prices were published before
``D``'s gate closure, and it does not look at ``D``'s own prices — so it is
identical whether the curve being dispatched is the oracle, a forecast or the
naive floor, which is what makes the per-day oracle bound in
:func:`dispatch.battery.assert_oracle_dominates` exact rather than approximate.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from data.contracts import local_day_hours
from dispatch.battery import (
    BatterySpec,
    DaySchedule,
    DayValuation,
    DispatchError,
    solve_day,
    value_schedule,
)
from forecast.timing import (
    gate_closure_utc,
    market_days,
    publication_utc,
    zone_timezone,
)

#: Local-day lengths a DST-aware calendar can produce in the EU. Mirrors
#: ``config/data.yaml -> time.dst_transition_local_day_lengths``; a block whose
#: length is outside this set is a contract violation, not a short day.
VALID_BLOCK_HOURS: tuple[int, ...] = (23, 24, 25)

#: How a market day's opening SoC is chosen. ``"carry"`` is PLAN.md's rolling
#: horizon and the committed default; ``"reset"`` is C15's declared daily-reset
#: sensitivity and is guarded (see the module docstring and
#: :func:`run_rolling_dispatch`).
VALID_SOC_POLICIES: tuple[str, ...] = ("carry", "reset")


class RollingError(RuntimeError):
    """The rolling horizon cannot be built from the series it was handed."""


@dataclass(frozen=True)
class MarketDayBlock:
    """One market day's hours, as the auction cleared them."""

    day: dt.date
    index: pd.DatetimeIndex
    expected_hours: int

    @property
    def n_hours(self) -> int:
        return int(len(self.index))

    @property
    def is_complete(self) -> bool:
        return self.n_hours == self.expected_hours


@dataclass(frozen=True)
class Skip:
    """A market day that was not dispatched, and exactly why."""

    day: dt.date
    reason: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"day": self.day.isoformat(), "reason": self.reason, "detail": self.detail}


@dataclass
class RollingResult:
    """Every dispatched day, its valuation, and everything that was not dispatched."""

    zone: str
    spec: BatterySpec
    curve: str
    days: list[dt.date] = field(default_factory=list)
    schedules: dict[dt.date, DaySchedule] = field(default_factory=dict)
    valuations: dict[dt.date, DayValuation] = field(default_factory=dict)
    skipped: list[Skip] = field(default_factory=list)
    soc_opening: dict[dt.date, float] = field(default_factory=dict)
    reference_prices: dict[dt.date, float] = field(default_factory=dict)
    #: ``"carry"`` (PLAN.md's rolling horizon) or ``"reset"`` (C15's declared
    #: daily-reset sensitivity). Recorded on the result so a per-day artefact
    #: cannot be read without knowing which policy produced it.
    soc_policy: str = "carry"
    #: Stored energy the daily reset threw away, MWh, per day it threw any away.
    #: Empty under ``"carry"``. Counted rather than assumed: the reset is only
    #: ever allowed to discard (see :func:`run_rolling_dispatch`), and a
    #: sensitivity whose leg quietly destroys energy should say how much.
    soc_reset_discarded: dict[dt.date, float] = field(default_factory=dict)

    # -- aggregates --------------------------------------------------------
    @property
    def n_days(self) -> int:
        return len(self.days)

    @property
    def total_cash_eur(self) -> float:
        return float(sum(v.cash_eur for v in self.valuations.values()))

    @property
    def total_value_added_eur(self) -> float:
        return float(sum(v.value_added_eur for v in self.valuations.values()))

    @property
    def total_discharged_mwh(self) -> float:
        return float(sum(v.energy_discharged_mwh for v in self.valuations.values()))

    @property
    def total_charged_mwh(self) -> float:
        return float(sum(v.energy_charged_mwh for v in self.valuations.values()))

    @property
    def equivalent_full_cycles(self) -> float:
        """Discharged grid energy in battery-fulls — the cycling the result implies."""
        return self.total_discharged_mwh / self.spec.energy_mwh

    @property
    def soc_reset_discarded_mwh(self) -> float:
        """Total stored energy the daily reset discarded. Zero under ``"carry"``."""
        return float(sum(self.soc_reset_discarded.values()))

    @property
    def n_simultaneity_days(self) -> int:
        return sum(1 for v in self.valuations.values() if v.simultaneity.found)

    def daily_frame(self) -> pd.DataFrame:
        """One row per dispatched market day. The artefact C11/C12 aggregate."""
        rows = []
        for day in self.days:
            val = self.valuations[day]
            sched = self.schedules[day]
            sim = val.simultaneity
            rows.append(
                {
                    "market_day": day.isoformat(),
                    "zone": self.zone,
                    "curve": self.curve,
                    "n_hours": val.n_intervals,
                    "soc_start_mwh": sched.soc_start_mwh,
                    "soc_end_mwh": sched.soc_end_mwh,
                    "reference_price": self.reference_prices.get(day, float("nan")),
                    "terminal_price": val.terminal_price_eur_per_mwh,
                    "cash_eur": val.cash_eur,
                    "terminal_value_eur": val.terminal_value_eur,
                    "opening_value_eur": val.opening_value_eur,
                    "value_added_eur": val.value_added_eur,
                    "charged_mwh": val.energy_charged_mwh,
                    "discharged_mwh": val.energy_discharged_mwh,
                    "throughput_cost_eur": val.throughput_cost_eur,
                    "n_simultaneous_intervals": sim.n_intervals,
                    "simultaneity_energy_burned_mwh": sim.energy_burned_mwh,
                    "simultaneity_cash_eur": sim.cash_from_overlap_eur,
                    "realised_price_min": self.realised_min.get(day, float("nan")),
                    "realised_price_max": self.realised_max.get(day, float("nan")),
                }
            )
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values("market_day").reset_index(drop=True)
        return frame

    def schedule_frame(self) -> pd.DataFrame:
        """Every dispatched hour, with the realised price alongside the instruction."""
        if not self.days:
            return pd.DataFrame()
        parts = []
        for day in self.days:
            block = self.schedules[day].frame()
            block["market_day"] = day.isoformat()
            block["realised_price"] = self.realised_prices[day]
            parts.append(block)
        out = pd.concat(parts).sort_index()
        out.index.name = "timestamp_utc"
        return out

    #: Filled by :func:`run_rolling_dispatch`; kept off the constructor so the
    #: reporting helpers above can stay simple.
    realised_prices: dict[dt.date, np.ndarray] = field(default_factory=dict)
    realised_min: dict[dt.date, float] = field(default_factory=dict)
    realised_max: dict[dt.date, float] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        per_mw_year = float("nan")
        if self.days:
            span_days = (max(self.days) - min(self.days)).days + 1
            if span_days > 0:
                per_mw_year = (
                    self.total_cash_eur / self.spec.power_mw / span_days * 365.25
                )
        return {
            "zone": self.zone,
            "curve": self.curve,
            "n_days_dispatched": self.n_days,
            "n_days_skipped": len(self.skipped),
            "first_day": self.days[0].isoformat() if self.days else None,
            "last_day": self.days[-1].isoformat() if self.days else None,
            "total_cash_eur": round(self.total_cash_eur, 4),
            "total_value_added_eur": round(self.total_value_added_eur, 4),
            "cash_eur_per_mw_year": round(per_mw_year, 2),
            "total_charged_mwh": round(self.total_charged_mwh, 4),
            "total_discharged_mwh": round(self.total_discharged_mwh, 4),
            "equivalent_full_cycles": round(self.equivalent_full_cycles, 3),
            "closing_soc_mwh": round(
                self.schedules[self.days[-1]].soc_end_mwh, 6
            )
            if self.days
            else None,
            "n_days_with_simultaneity": self.n_simultaneity_days,
            "simultaneity_energy_burned_mwh": round(
                float(
                    sum(
                        v.simultaneity.energy_burned_mwh
                        for v in self.valuations.values()
                    )
                ),
                6,
            ),
            "simultaneity_cash_eur": round(
                float(
                    sum(
                        v.simultaneity.cash_from_overlap_eur
                        for v in self.valuations.values()
                    )
                ),
                4,
            ),
            "skips_by_reason": {
                reason: sum(1 for s in self.skipped if s.reason == reason)
                for reason in sorted({s.reason for s in self.skipped})
            },
            "spec": self.spec.as_dict(),
        }


# ---------------------------------------------------------------------------
# Market-day blocks
# ---------------------------------------------------------------------------


def market_day_blocks(
    index: pd.DatetimeIndex,
    tz: str,
    drop_partial_edges: bool = True,
) -> tuple[list[MarketDayBlock], list[Skip]]:
    """Group a UTC index into market days, asserting each block's length.

    Returns the blocks and the skips for blocks that cannot be dispatched. A
    block whose length is neither its calendar length nor anything in
    :data:`VALID_BLOCK_HOURS` raises: that is a data-contract violation
    (:mod:`data.contracts` owns it) rather than a dispatchable short day.
    """
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise RollingError("market_day_blocks requires a tz-aware (UTC) index")
    if not index.is_monotonic_increasing:
        raise RollingError("index must be sorted")
    labels = market_days(index, tz)
    blocks: list[MarketDayBlock] = []
    skips: list[Skip] = []
    all_days = list(dict.fromkeys(labels.tolist()))
    for position, day in enumerate(all_days):
        rows = index[(labels == day).to_numpy()]
        expected = local_day_hours(day, tz)
        if expected not in VALID_BLOCK_HOURS:
            raise RollingError(
                f"{tz} {day}: calendar says {expected} hours, outside "
                f"{VALID_BLOCK_HOURS} — a data contract, not a dispatch decision"
            )
        block = MarketDayBlock(day=day, index=rows, expected_hours=expected)
        is_edge = position in (0, len(all_days) - 1)
        if not block.is_complete:
            reason = "boundary" if (drop_partial_edges and is_edge) else "incomplete"
            skips.append(
                Skip(
                    day=day,
                    reason=reason,
                    detail=(
                        f"{block.n_hours} of {expected} hours present "
                        f"({'partial window edge' if reason == 'boundary' else 'gap in the series'})"
                    ),
                )
            )
            continue
        blocks.append(block)
    return blocks, skips


def assert_reference_is_knowable(
    day: dt.date, reference_days: Sequence[dt.date], tz: str
) -> None:
    """Every day feeding ``p_ref(D)`` must have been published before ``D``'s gate.

    The gate-closure guard in :mod:`forecast.leakage` protects the *feature*
    matrix. The terminal mark is not a feature, it is a term in the objective,
    and it would leak just as happily — so it gets the same check, from the same
    two functions, rather than an argument that it is obviously fine.
    """
    gate = gate_closure_utc(day)
    for reference_day in reference_days:
        if reference_day >= day:
            raise RollingError(
                f"terminal reference for {day} includes market day {reference_day}, "
                f"which is not strictly earlier"
            )
        published = publication_utc(reference_day)
        if published > gate:
            raise RollingError(
                f"terminal reference for {day} uses market day {reference_day}, "
                f"published {published.isoformat()} — after gate closure "
                f"{gate.isoformat()}. That is a leak."
            )


def trailing_reference_prices(
    prices: pd.Series,
    tz: str,
    trailing_days: int = 7,
    quantile: float = 0.5,
    min_trailing_days: int = 1,
) -> dict[dt.date, float]:
    """``{market day: p_ref}`` from the trailing ``trailing_days`` complete days.

    Uses only days strictly before ``D`` and only days whose full hour count is
    present, so a gappy day neither contaminates the reference nor silently
    shortens the window. Days with too little history get no entry at all, and
    the caller skips them with reason ``no_reference`` — a default reference
    price would be a number nobody chose.
    """
    if trailing_days < 1:
        raise RollingError(f"trailing_days must be >= 1, got {trailing_days}")
    if not 0 <= quantile <= 1:
        raise RollingError(f"quantile must be in [0, 1], got {quantile}")
    labels = market_days(prices.index, tz)
    by_day: dict[dt.date, np.ndarray] = {}
    for day, group in prices.groupby(labels.to_numpy(), sort=True):
        values = group.to_numpy(dtype=float)
        if len(values) != local_day_hours(day, tz) or not np.isfinite(values).all():
            continue  # incomplete day: not a usable reference
        by_day[day] = values
    ordered = sorted(by_day)
    out: dict[dt.date, float] = {}
    for position, day in enumerate(ordered):
        window = ordered[max(0, position - trailing_days) : position]
        if len(window) < min_trailing_days:
            continue
        assert_reference_is_knowable(day, window, tz)
        pooled = np.concatenate([by_day[d] for d in window])
        out[day] = float(np.quantile(pooled, quantile))
    # Days present in the series but with no complete trailing window get no
    # entry; so do incomplete days, which are skipped for that reason anyway.
    return out


# ---------------------------------------------------------------------------
# The roll
# ---------------------------------------------------------------------------


def run_rolling_dispatch(
    zone: str,
    realised_prices: pd.Series,
    spec: BatterySpec,
    decision_prices: pd.Series | None = None,
    curve: str = "oracle",
    days: Iterable[dt.date] | None = None,
    trailing_days: int = 7,
    trailing_quantile: float = 0.5,
    min_trailing_days: int = 1,
    interval_hours: float = 1.0,
    tz: str | None = None,
    initial_soc_mwh: float | None = None,
    soc_policy: str = "carry",
) -> RollingResult:
    """Dispatch day after day, carrying SoC, settling at realised prices.

    ``decision_prices`` defaults to ``realised_prices``, which is the oracle
    curve — the only curve for which that substitution is legitimate, and the one
    C5 scopes. C6 passes a forecast here; the schedule is then frozen from the
    forecast and :func:`dispatch.battery.value_schedule` settles it at
    ``realised_prices``, which is PLAN.md's commit-then-settle rule expressed as
    two arguments that cannot be confused for one another.

    ``days`` restricts dispatch to a subset (e.g. one evaluation year) while
    still letting the trailing reference window reach into the days before it.

    ``soc_policy`` is PLAN.md's SoC lever. ``"carry"`` is the committed rolling
    horizon. ``"reset"`` is C15's declared daily-reset sensitivity: every day
    opens at the same SoC, so each market day is an independent problem. It is
    refused unless the spec's terminal condition is a **floor** at or above the
    opening fraction — without that the LP may end a day below where it started
    and the reset would top the battery up for nothing, which is free energy
    dressed as a sensitivity result.
    """
    if soc_policy not in VALID_SOC_POLICIES:
        raise RollingError(
            f"unknown soc_policy {soc_policy!r}; expected one of {VALID_SOC_POLICIES}"
        )
    zone_tz = tz or zone_timezone(zone)
    if not isinstance(realised_prices, pd.Series):
        raise RollingError("realised_prices must be a Series")
    realised = realised_prices.sort_index()
    decision = realised if decision_prices is None else decision_prices.sort_index()
    is_oracle = decision_prices is None

    blocks, skips = market_day_blocks(realised.index, zone_tz)
    references = trailing_reference_prices(
        realised,
        zone_tz,
        trailing_days=trailing_days,
        quantile=trailing_quantile,
        min_trailing_days=min_trailing_days,
    )

    wanted = None if days is None else set(days)
    result = RollingResult(zone=zone, spec=spec, curve=curve, soc_policy=soc_policy)
    soc = (
        spec.initial_soc_mwh if initial_soc_mwh is None else float(initial_soc_mwh)
    )
    opening_soc = soc
    if soc_policy == "reset":
        # The guard the module docstring explains: a reset is only honest when
        # the horizon cannot end below where it opened, so that the reset can
        # only discard stored energy, never conjure it.
        if spec.terminal_mode != "floor":
            raise RollingError(
                f"soc_policy='reset' needs terminal_mode='floor' so the day cannot "
                f"end below its opening SoC; got terminal_mode="
                f"{spec.terminal_mode!r}. Under 'none' the LP empties the battery "
                f"and the reset would refill it for free; under 'trailing_value' "
                f"the run would book a mark on inventory the reset discards."
            )
        if spec.terminal_floor_mwh < opening_soc - 1e-9:
            raise RollingError(
                f"soc_policy='reset' opens each day at {opening_soc:.6g} MWh but the "
                f"terminal floor is {spec.terminal_floor_mwh:.6g} MWh, so a day may "
                f"end below its opening SoC and the reset would create "
                f"{opening_soc - spec.terminal_floor_mwh:.6g} MWh of free energy"
            )

    for skip in skips:
        if wanted is None or skip.day in wanted:
            result.skipped.append(skip)

    for block in blocks:
        day = block.day
        if wanted is not None and day not in wanted:
            continue

        realised_block = realised.reindex(block.index)
        if not np.isfinite(realised_block.to_numpy(dtype=float)).all():
            result.skipped.append(
                Skip(day, "incomplete", "realised price vector has a NaN")
            )
            continue

        decision_block = decision.reindex(block.index)
        decision_values = decision_block.to_numpy(dtype=float)
        if not np.isfinite(decision_values).all():
            n_bad = int((~np.isfinite(decision_values)).sum())
            result.skipped.append(
                Skip(
                    day,
                    "incomplete",
                    f"decision ({curve}) price vector has {n_bad} missing hour(s) "
                    f"of {block.n_hours}",
                )
            )
            continue

        reference = references.get(day)
        if spec.terminal_mode == "trailing_value" and reference is None:
            result.skipped.append(
                Skip(
                    day,
                    "no_reference",
                    f"fewer than {min_trailing_days} complete trailing market day(s) "
                    f"of realised prices before {day}",
                )
            )
            continue

        schedule = solve_day(
            decision_block,
            spec,
            soc_start_mwh=soc,
            index=block.index,
            interval_hours=interval_hours,
            reference_price=reference,
        )
        valuation = value_schedule(
            schedule,
            realised_block,
            spec,
            prices_are_decision_prices=is_oracle,
        )

        result.days.append(day)
        result.schedules[day] = schedule
        result.valuations[day] = valuation
        result.soc_opening[day] = soc
        if reference is not None:
            result.reference_prices[day] = reference
        realised_values = realised_block.to_numpy(dtype=float)
        result.realised_prices[day] = realised_values
        result.realised_min[day] = float(realised_values.min())
        result.realised_max[day] = float(realised_values.max())

        # PLAN.md: the realised end-of-day SoC is what opens tomorrow. Nothing
        # resets at midnight, and a skipped day carries this value across
        # unchanged rather than restarting from the initial fraction.
        soc = schedule.soc_end_mwh
        if soc_policy == "reset":
            # C15's declared sensitivity. The guard above means `soc` is at or
            # above `opening_soc`, so this only ever throws energy away; what it
            # threw away is recorded rather than rounded off.
            discarded = soc - opening_soc
            if discarded > 1e-9:
                result.soc_reset_discarded[day] = float(discarded)
            soc = opening_soc

    result.days.sort()
    result.skipped.sort(key=lambda s: s.day)
    return result
