"""Commit-then-settle across several price curves, and the invariants that bind them.

:mod:`dispatch.battery` decides one day and settles one schedule.
:mod:`dispatch.rolling` rolls that forward across a year. This module is the
third layer and the one C6 exists to build: it runs *more than one curve* over
the same days and checks that the resulting values stand in the order PLAN.md and
CLAUDE.md require them to.

The curve, and what "commit-then-settle" means mechanically
-----------------------------------------------------------
A **curve** is a decision price vector. Three of them here:

``oracle``
    The realised prices. Perfect foresight — the ceiling, and the denominator of
    every capture ratio.
``model``
    A forecast produced by the walk-forward harness, available at gate closure
    and nothing more.
``naive``
    Same hour last week. PLAN.md's floor.

Each one is handed to :func:`dispatch.rolling.run_rolling_dispatch` as
``decision_prices``; the schedule it produces is **frozen** and then settled at
realised prices by :func:`dispatch.battery.value_schedule`. The LP's own
objective from a forecast solve is a property of the decision problem and is
never reported — CLAUDE.md names this as the error to prevent, and the machinery
prevents it structurally rather than by care: ``decision_prices`` and
``realised_prices`` are separate arguments, and every
:class:`~dispatch.battery.DayValuation` carries
``prices_are_decision_prices``, which only the oracle curve may set.
:func:`assert_settlement_is_not_a_readback` is that statement as an assertion
over a whole run.

Two oracles, because the per-day bound needs the second one
-----------------------------------------------------------
CLAUDE.md requires ``value(forecast @ realised) <= value(oracle @ realised)``
**every day**. It holds exactly — and only — when both schedules are solved from
the *same opening SoC* against the *same mark*, because the frozen forecast
schedule is then a feasible point of the oracle's own problem. Across two
independently *rolled* trajectories the opening SoCs diverge, and a forecast run
that happens to open a day with a fuller battery can out-earn the rolled oracle
on that day. That is expected, not a bug (see ``docs/battery_lp.md``).

So there are two oracles and they answer different questions:

:func:`same_start_oracle`
    Re-solves the oracle each day from **the candidate run's own opening SoC**
    and its own mark. This is the exact per-day upper bound, and
    :func:`check_per_day_dominance` asserts it on *every* dispatched day, not a
    sample.
the rolled oracle
    One continuous perfect-foresight trajectory over the same days. This is the
    annual ceiling, the thing a capture ratio is a share *of*, and the subject of
    the pooled comparison in :func:`pooled_comparison`.

The pooled half — ``value(naive) <= value(forecast)`` **on average, not per day**
— is checked on pooled totals by :func:`pooled_comparison`, which also records
how often the per-day version fails, because CLAUDE.md says per-day violations
there are real and expected and a number is better than a reassurance.

Curves must be compared on a common day set
-------------------------------------------
A curve with a hole in its forecast skips that day (``dispatch.rolling`` skips,
never patches). The oracle has no holes, so the runs can end up with different
day counts, and summing each run over *its own* days would compare a 366-day
total against a 365-day one. :func:`common_days` intersects them and every pooled
number is computed over that intersection, with the difference reported rather
than absorbed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from dispatch.battery import (
    BatterySpec,
    DayValuation,
    DispatchError,
    assert_oracle_dominates,
    solve_day,
    value_schedule,
)
from dispatch.rolling import RollingResult

#: Curve names whose decision prices legitimately *are* the realised prices.
ORACLE_CURVES: tuple[str, ...] = ("oracle", "oracle_no_simultaneous")


class CurveError(RuntimeError):
    """Two curves cannot be compared as asked, or a settlement is a read-back."""


# ---------------------------------------------------------------------------
# Decision-price curves
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Curve:
    """A decision price series, named, with its provenance attached.

    ``is_oracle`` is not inferred from the name: it is the caller's explicit
    declaration that these prices are the realised ones, and it is what ends up
    in ``prices_are_decision_prices`` on every valuation of the run. A forecast
    curve that set it would be exactly the mislabelling CLAUDE.md forbids, so
    :func:`assert_settlement_is_not_a_readback` re-checks it against the data.
    """

    name: str
    prices: pd.Series
    source: str
    is_oracle: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.prices, pd.Series):
            raise CurveError(f"curve {self.name!r}: prices must be a Series")
        if not isinstance(self.prices.index, pd.DatetimeIndex):
            raise CurveError(f"curve {self.name!r}: prices need a DatetimeIndex")
        if self.prices.index.tz is None:
            raise CurveError(f"curve {self.name!r}: prices need a tz-aware (UTC) index")
        if self.prices.index.has_duplicates:
            raise CurveError(f"curve {self.name!r}: duplicate timestamps")
        if not self.prices.index.is_monotonic_increasing:
            raise CurveError(f"curve {self.name!r}: index is not sorted")

    @property
    def n_missing(self) -> int:
        return int(self.prices.isna().sum())

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "is_oracle": self.is_oracle,
            "n_points": int(len(self.prices)),
            "n_missing": self.n_missing,
            "first_ts_utc": self.prices.index[0].isoformat() if len(self.prices) else None,
            "last_ts_utc": self.prices.index[-1].isoformat() if len(self.prices) else None,
        }


def assert_curve_aligns(curve: Curve, realised: pd.Series, label: str = "") -> dict[str, Any]:
    """A forecast curve must sit on the realised index it will be settled against.

    Checked rather than assumed, because an off-by-one-hour forecast index is a
    leak that looks like skill: a schedule built against hour ``t + 1``'s price
    and settled at hour ``t``'s would show the model beating the oracle, and the
    per-day assertion would catch it only after the fact. The curve is allowed to
    be *shorter* than the realised series (it covers the evaluation window, the
    realised series also carries the trailing-mark run-in); it is not allowed to
    carry a timestamp the realised series does not have.
    """
    tag = label or curve.name
    missing = curve.prices.index.difference(realised.index)
    if len(missing) > 0:
        raise CurveError(
            f"{tag}: {len(missing)} timestamp(s) in the curve are absent from the "
            f"realised series, first {missing[0].isoformat()}. The curve is not on "
            f"the grid it would be settled against."
        )
    overlap = curve.prices.index
    if curve.is_oracle:
        diff = np.abs(
            curve.prices.to_numpy(dtype=float)
            - realised.reindex(overlap).to_numpy(dtype=float)
        )
        worst = float(np.nanmax(diff)) if len(diff) else 0.0
        if worst > 1e-9:
            raise CurveError(
                f"{tag}: declared an oracle curve, but its prices differ from the "
                f"realised series by up to {worst:.6g} EUR/MWh."
            )
    return {
        "curve": curve.name,
        "n_points": int(len(overlap)),
        "n_missing_values": curve.n_missing,
        "first_ts_utc": overlap[0].isoformat() if len(overlap) else None,
        "last_ts_utc": overlap[-1].isoformat() if len(overlap) else None,
        "on_realised_grid": True,
    }


def assert_settlement_is_not_a_readback(result: RollingResult) -> dict[str, Any]:
    """No non-oracle run may report a valuation taken at its own decision prices.

    ``prices_are_decision_prices`` is set by
    :func:`dispatch.battery.value_schedule`'s caller, so this re-derives the
    truth from the schedules themselves: it compares each day's decision price
    vector against the realised one and requires the flag to agree with what it
    finds. A forecast run whose decision prices happen to equal the realised
    ones on a day is not an error (a perfect forecast is legitimate); a forecast
    run that *claims* its settlement is a decision-price read-back is.
    """
    offenders: list[str] = []
    n_days_identical = 0
    worst_gap = 0.0
    for day in result.days:
        schedule = result.schedules[day]
        valuation = result.valuations[day]
        realised = np.asarray(result.realised_prices[day], dtype=float)
        decision = np.asarray(schedule.decision_prices, dtype=float)
        gap = float(np.max(np.abs(decision - realised))) if len(realised) else 0.0
        worst_gap = max(worst_gap, gap)
        if gap <= 1e-9:
            n_days_identical += 1
        if valuation.prices_are_decision_prices and result.curve not in ORACLE_CURVES:
            offenders.append(day.isoformat())
        if not valuation.prices_are_decision_prices and result.curve in ORACLE_CURVES:
            offenders.append(day.isoformat())
    if result.curve in ORACLE_CURVES and worst_gap > 1e-9:
        offenders.append(
            f"curve is named {result.curve!r} but its decision prices differ from "
            f"realised by up to {worst_gap:.6g}"
        )
    return {
        "holds": not offenders,
        "curve": result.curve,
        "n_days_checked": result.n_days,
        "n_days_decision_equals_realised": n_days_identical,
        "worst_decision_vs_realised_gap_eur_per_mwh": round(worst_gap, 8),
        "offenders": offenders[:10],
    }


# ---------------------------------------------------------------------------
# The same-start oracle: the exact per-day upper bound
# ---------------------------------------------------------------------------


def same_start_oracle(
    candidate: RollingResult,
    spec: BatterySpec,
    interval_hours: float = 1.0,
) -> dict[dt.date, DayValuation]:
    """Re-solve the oracle each day from ``candidate``'s own opening SoC and mark.

    This is the second of the two oracles (see the module docstring). It is a
    per-day problem, not a trajectory: each day is solved independently from the
    state the candidate run actually arrived in, which is precisely what makes
    the frozen candidate schedule a feasible point of it and the bound exact.

    ``spec`` must be the candidate's own spec — a bound computed under a
    different asset is not a bound — and that is checked, not trusted.
    """
    if spec != candidate.spec:
        raise CurveError(
            "the same-start oracle must use the candidate's own battery spec; "
            f"got {spec.as_dict()} vs {candidate.spec.as_dict()}"
        )
    out: dict[dt.date, DayValuation] = {}
    for day in candidate.days:
        schedule = candidate.schedules[day]
        realised = pd.Series(candidate.realised_prices[day], index=schedule.index)
        oracle_schedule = solve_day(
            realised,
            spec,
            soc_start_mwh=schedule.soc_start_mwh,
            index=schedule.index,
            interval_hours=interval_hours,
            reference_price=candidate.reference_prices.get(day),
        )
        out[day] = value_schedule(
            oracle_schedule, realised, spec, prices_are_decision_prices=True
        )
    return out


def check_per_day_dominance(
    candidate: RollingResult,
    oracle_by_day: Mapping[dt.date, DayValuation],
    atol: float = 1e-6,
) -> dict[str, Any]:
    """CLAUDE.md's per-day invariant, on **every** dispatched day.

    ``assert_oracle_dominates`` does the comparing (and refuses mismatched
    opening SoCs or marks). This walks the run, collects the worst margin, and
    returns a report rather than raising, so the caller can persist the evidence
    before it fails the run.
    """
    failures: list[str] = []
    worst_excess = -float("inf")
    worst_day: str | None = None
    for day in candidate.days:
        oracle_value = oracle_by_day.get(day)
        if oracle_value is None:
            failures.append(f"{day.isoformat()}: no same-start oracle for this day")
            continue
        candidate_value = candidate.valuations[day]
        excess = candidate_value.value_added_eur - oracle_value.value_added_eur
        if excess > worst_excess:
            worst_excess, worst_day = excess, day.isoformat()
        try:
            assert_oracle_dominates(
                candidate_value, oracle_value, label=day.isoformat(), atol=atol
            )
        except DispatchError as exc:
            failures.append(str(exc))
    return {
        "holds": not failures,
        "curve": candidate.curve,
        "n_days_checked": candidate.n_days,
        "worst_excess_eur": (
            None if worst_excess == -float("inf") else round(worst_excess, 10)
        ),
        "worst_excess_day": worst_day,
        "n_failures": len(failures),
        "failures": failures[:10],
    }


# ---------------------------------------------------------------------------
# Pooled comparison across curves
# ---------------------------------------------------------------------------


def common_days(results: Mapping[str, RollingResult]) -> list[dt.date]:
    """The days every run dispatched. Every pooled number is computed over these."""
    if not results:
        return []
    sets = [set(result.days) for result in results.values()]
    shared = set.intersection(*sets) if sets else set()
    return sorted(shared)


def _pooled(result: RollingResult, days: Iterable[dt.date]) -> dict[str, float]:
    days = list(days)
    cash = float(sum(result.valuations[d].cash_eur for d in days))
    added = float(sum(result.valuations[d].value_added_eur for d in days))
    discharged = float(sum(result.valuations[d].energy_discharged_mwh for d in days))
    charged = float(sum(result.valuations[d].energy_charged_mwh for d in days))
    return {
        "n_days": len(days),
        "cash_eur": cash,
        "value_added_eur": added,
        "charged_mwh": charged,
        "discharged_mwh": discharged,
    }


def pooled_comparison(
    results: Mapping[str, RollingResult],
    oracle_curve: str = "oracle",
    model_curve: str = "model",
    naive_curve: str = "naive",
    atol_eur: float = 1e-6,
) -> dict[str, Any]:
    """PLAN.md C6's assertion: ``oracle >= model >= naive`` on pooled value.

    Pooled, not per day. The ``oracle >= model`` half is a near-certainty rather
    than a theorem here because the three runs are independently *rolled*
    trajectories (the exact statement is
    :func:`check_per_day_dominance`); the ``model >= naive`` half is exactly what
    CLAUDE.md says to assert on average and not per day, so the per-day win rate
    is reported beside it rather than asserted.
    """
    for name in (oracle_curve, model_curve, naive_curve):
        if name not in results:
            raise CurveError(f"pooled_comparison needs a {name!r} run; got {sorted(results)}")
    days = common_days(results)
    if not days:
        raise CurveError("the runs share no dispatched day, so nothing can be pooled")
    pooled = {name: _pooled(result, days) for name, result in results.items()}
    oracle, model, naive = (
        pooled[oracle_curve],
        pooled[model_curve],
        pooled[naive_curve],
    )

    def _ratio(numerator: float, denominator: float) -> float | None:
        return None if denominator == 0 else round(numerator / denominator, 6)

    per_day_model_beats_naive = sum(
        1
        for d in days
        if results[model_curve].valuations[d].value_added_eur
        > results[naive_curve].valuations[d].value_added_eur + 1e-9
    )
    per_day_model_beats_oracle = [
        d.isoformat()
        for d in days
        if results[model_curve].valuations[d].value_added_eur
        > results[oracle_curve].valuations[d].value_added_eur + 1e-6
    ]
    checks = {
        "oracle_ge_model_pooled_cash": {
            "holds": oracle["cash_eur"] >= model["cash_eur"] - atol_eur,
            "oracle_eur": round(oracle["cash_eur"], 4),
            "model_eur": round(model["cash_eur"], 4),
            "margin_eur": round(oracle["cash_eur"] - model["cash_eur"], 4),
        },
        "model_ge_naive_pooled_cash": {
            "holds": model["cash_eur"] >= naive["cash_eur"] - atol_eur,
            "model_eur": round(model["cash_eur"], 4),
            "naive_eur": round(naive["cash_eur"], 4),
            "margin_eur": round(model["cash_eur"] - naive["cash_eur"], 4),
        },
        "oracle_ge_model_pooled_value_added": {
            "holds": oracle["value_added_eur"] >= model["value_added_eur"] - atol_eur,
            "margin_eur": round(
                oracle["value_added_eur"] - model["value_added_eur"], 4
            ),
        },
        "model_ge_naive_pooled_value_added": {
            "holds": model["value_added_eur"] >= naive["value_added_eur"] - atol_eur,
            "margin_eur": round(model["value_added_eur"] - naive["value_added_eur"], 4),
        },
    }
    return {
        "holds": all(check["holds"] for check in checks.values()),
        "n_common_days": len(days),
        "first_common_day": days[0].isoformat(),
        "last_common_day": days[-1].isoformat(),
        "days_dispatched_per_curve": {
            name: result.n_days for name, result in results.items()
        },
        "days_excluded_from_pool_per_curve": {
            name: sorted(d.isoformat() for d in set(result.days) - set(days))
            for name, result in results.items()
        },
        "pooled": {
            name: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in block.items()}
            for name, block in pooled.items()
        },
        "checks": checks,
        "capture_ratio_rolled_cash": _ratio(model["cash_eur"], oracle["cash_eur"]),
        "naive_capture_ratio_rolled_cash": _ratio(naive["cash_eur"], oracle["cash_eur"]),
        "capture_ratio_rolled_value_added": _ratio(
            model["value_added_eur"], oracle["value_added_eur"]
        ),
        "eur_lost_to_forecast_error": round(oracle["cash_eur"] - model["cash_eur"], 2),
        "per_day_model_beats_naive_days": per_day_model_beats_naive,
        "per_day_model_beats_naive_share": round(
            per_day_model_beats_naive / len(days), 6
        ),
        "per_day_model_beats_rolled_oracle_days": len(per_day_model_beats_oracle),
        "per_day_model_beats_rolled_oracle_examples": per_day_model_beats_oracle[:10],
        "note": (
            "Pooled over the day set every curve dispatched. The rolled oracle is "
            "a different trajectory from the model run, so a day on which the "
            "model out-earns it is expected and is counted, not asserted away; "
            "the exact per-day bound is the same-start oracle."
        ),
    }


# ---------------------------------------------------------------------------
# Capture ratios
# ---------------------------------------------------------------------------


def capture_frame(
    candidate: RollingResult,
    rolled_oracle: RollingResult,
    same_start: Mapping[dt.date, DayValuation],
) -> pd.DataFrame:
    """One row per day: what the curve earned, both ceilings, and the ratios.

    Two denominators, deliberately:

    ``capture_same_start``
        Against the oracle re-solved from this run's own opening SoC. Bounded
        above by 1 **exactly** (that is :func:`check_per_day_dominance`), so this
        is the honest per-day "share of attainable value captured".
    ``capture_rolled``
        Against the rolled oracle's value on the same day. Not bounded by 1 — the
        two trajectories open the day in different states — and only meaningful
        summed over a long window, which is what the annual headline uses.
    """
    rows = []
    for day in candidate.days:
        value = candidate.valuations[day]
        bound = same_start.get(day)
        rolled = rolled_oracle.valuations.get(day)
        prices = np.asarray(candidate.realised_prices[day], dtype=float)
        rows.append(
            {
                "market_day": day.isoformat(),
                "zone": candidate.zone,
                "curve": candidate.curve,
                "n_hours": value.n_intervals,
                "soc_start_mwh": value.soc_start_mwh,
                "soc_end_mwh": value.soc_end_mwh,
                "reference_price": candidate.reference_prices.get(day, float("nan")),
                "realised_price_min": float(prices.min()),
                "realised_price_max": float(prices.max()),
                "realised_spread": float(prices.max() - prices.min()),
                "cash_eur": value.cash_eur,
                "value_added_eur": value.value_added_eur,
                "same_start_oracle_cash_eur": bound.cash_eur if bound else float("nan"),
                "same_start_oracle_value_added_eur": (
                    bound.value_added_eur if bound else float("nan")
                ),
                "rolled_oracle_cash_eur": rolled.cash_eur if rolled else float("nan"),
                "rolled_oracle_value_added_eur": (
                    rolled.value_added_eur if rolled else float("nan")
                ),
                "capture_same_start": _safe_ratio(
                    value.value_added_eur, bound.value_added_eur if bound else None
                ),
                "capture_rolled": _safe_ratio(
                    value.value_added_eur, rolled.value_added_eur if rolled else None
                ),
                "n_simultaneous_intervals": value.simultaneity.n_intervals,
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("market_day").reset_index(drop=True)
    return frame


def _safe_ratio(numerator: float, denominator: float | None) -> float:
    """A ratio, or NaN where the denominator is ~0 — never a divide-by-zero fill.

    A day on which perfect foresight itself adds nothing (a flat curve, or an
    opening-SoC-constrained day) has no meaningful capture *share*: the honest
    answer is "undefined", and NaN propagates that into the aggregates instead of
    a 0 or a 1 that nobody chose.
    """
    if denominator is None or not np.isfinite(denominator) or abs(denominator) < 1e-9:
        return float("nan")
    return float(numerator) / float(denominator)


def capture_summary(frame: pd.DataFrame) -> dict[str, Any]:
    """Pooled and distributional capture, from a :func:`capture_frame`.

    PLAN.md asks for the full distribution and not just the mean, so the
    quantiles are here from the start. The pooled ratio is a ratio of sums (what
    a desk would quote); the mean of the per-day ratios is reported beside it
    because the two differ whenever value is concentrated in a few days, which
    on power prices it always is.
    """
    if frame.empty:
        return {"n_days": 0}
    same_start = frame["capture_same_start"].to_numpy(dtype=float)
    defined = np.isfinite(same_start)
    pooled_numerator = float(frame["value_added_eur"].sum())
    pooled_denominator = float(frame["same_start_oracle_value_added_eur"].sum())
    return {
        "n_days": int(len(frame)),
        "n_days_capture_defined": int(defined.sum()),
        "n_days_capture_undefined": int((~defined).sum()),
        "pooled_capture_same_start": (
            round(pooled_numerator / pooled_denominator, 6)
            if abs(pooled_denominator) > 1e-9
            else None
        ),
        "mean_daily_capture_same_start": round(float(np.mean(same_start[defined])), 6)
        if defined.any()
        else None,
        "quantiles_daily_capture_same_start": {
            f"p{int(q * 100):02d}": round(float(np.quantile(same_start[defined], q)), 6)
            for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
        }
        if defined.any()
        else {},
        "n_days_capture_above_one": int((same_start[defined] > 1 + 1e-9).sum())
        if defined.any()
        else 0,
        "n_days_capture_negative": int((same_start[defined] < 0).sum())
        if defined.any()
        else 0,
        "worst_day": (
            {
                "market_day": str(frame.loc[int(np.argmin(np.where(defined, same_start, np.inf))), "market_day"]),
                "capture_same_start": round(float(np.min(same_start[defined])), 6),
            }
            if defined.any()
            else None
        ),
        "cash_eur": round(float(frame["cash_eur"].sum()), 4),
        "value_added_eur": round(pooled_numerator, 4),
        "same_start_oracle_value_added_eur": round(pooled_denominator, 4),
    }


# ---------------------------------------------------------------------------
# "Doing nothing is feasible" — which problem that is a statement about
# ---------------------------------------------------------------------------


def check_decision_value_added_non_negative(
    result: RollingResult, spec: BatterySpec, atol: float = 1e-6
) -> dict[str, Any]:
    """``value_added >= 0`` on the curve's **own decision prices**. A theorem.

    C5 asserts ``value_added >= 0`` on the oracle run and the reasoning is "doing
    nothing is always feasible, so the optimum cannot lose". That is a statement
    about the *decision* problem, and for the oracle curve the decision prices
    **are** the realised prices, so it also holds at settlement. For a forecast
    curve the two are different vectors and it does not transfer: a schedule
    committed against a wrong forecast can and does lose money at realised
    prices, which is the entire quantity this project exists to measure.

    So the theorem is asserted where it is a theorem — against the prices the LP
    actually optimised — and the realised-price losses are *reported* by
    :func:`report_realised_losses` rather than asserted away. Reading the
    valuation back at decision prices is legitimate here and only here: it is an
    audit of the optimiser, flagged as such via
    ``prices_are_decision_prices=True``, and it is never reported as value.
    """
    offenders: dict[str, float] = {}
    worst = 0.0
    for day in result.days:
        schedule = result.schedules[day]
        readback = value_schedule(
            schedule,
            schedule.decision_prices,
            spec,
            prices_are_decision_prices=True,
        )
        worst = min(worst, readback.value_added_eur)
        if readback.value_added_eur < -atol:
            offenders[day.isoformat()] = round(readback.value_added_eur, 8)
    return {
        "holds": not offenders,
        "curve": result.curve,
        "n_days_checked": result.n_days,
        "worst_day_eur": round(worst, 8),
        "offenders": dict(sorted(offenders.items(), key=lambda kv: kv[1])[:10]),
        "note": (
            "Asserted on the decision prices the LP optimised, where standing "
            "still is a feasible point and so the optimum cannot be negative. "
            "The realised-price analogue is NOT a theorem for a forecast curve "
            "and is reported, not asserted."
        ),
    }


def report_realised_losses(result: RollingResult) -> dict[str, Any]:
    """Days on which a committed schedule lost money at realised prices.

    Reported, never asserted. For the oracle this is empty by the theorem above;
    for a forecast curve a nonempty list is the cost of forecast error showing up
    as an outright loss rather than merely as forgone upside, and the count and
    the size of it are a **result** — one of the more decision-relevant numbers
    in the project, since a desk cares about the left tail and not only the mean.
    """
    losses = {
        day.isoformat(): round(value.value_added_eur, 6)
        for day, value in result.valuations.items()
        if value.value_added_eur < -1e-6
    }
    ordered = sorted(losses.items(), key=lambda kv: kv[1])
    return {
        "curve": result.curve,
        "n_days_checked": result.n_days,
        "n_days_value_added_negative_at_realised": len(losses),
        "share_of_days": round(len(losses) / result.n_days, 6) if result.n_days else 0.0,
        "total_eur": round(float(sum(losses.values())), 4),
        "worst_days": [
            {"market_day": day, "value_added_eur": value} for day, value in ordered[:10]
        ],
        "note": (
            "A schedule frozen on a forecast and settled at realised prices can "
            "lose money; doing nothing was feasible in the LP's own problem, not "
            "in hindsight. This is a measured result, not an invariant breach."
        ),
    }
