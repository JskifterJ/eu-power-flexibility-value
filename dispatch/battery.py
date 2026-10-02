"""One market day of battery dispatch: the optimisation, and the valuation.

This module holds two things and keeps them strictly apart, because conflating
them is the single error PLAN.md's "commit-then-settle" rule exists to prevent:

:func:`solve_day`
    **Decide.** Given a price vector and an opening state of charge, choose a
    schedule. The prices handed in are *decision* prices — realised prices for
    the oracle curve, a forecast for every other curve. The LP's own objective
    value is a property of that decision problem and is **never** a result.

:func:`value_schedule`
    **Settle.** Given a schedule that is already fixed, and the prices that
    actually cleared, work out what it earned. This is the only function whose
    output is ever reported as value.

C5 builds both and uses only the oracle path (decision prices == realised
prices, so the two coincide). C6 wires the forecast and naive curves through
the same pair, which is the whole point of writing them separately now.

The physics
-----------
Per interval ``t`` of length ``dt`` hours, with grid-side charge ``c_t`` and
discharge ``d_t`` in MW and ``s_t`` the stored energy in MWh at the *end* of the
interval::

    s_t = s_{t-1} + eta * c_t * dt - (1 / eta) * d_t * dt
    0 <= c_t <= P,   0 <= d_t <= P,   0 <= s_t <= E

``eta = sqrt(round_trip_efficiency)`` is the per-leg efficiency, so a MWh bought
from the grid stores ``eta`` MWh and a MWh sold to the grid costs ``1 / eta`` MWh
of store: round trip ``eta ** 2``, symmetric, as PLAN.md requires.

Cash over the day, which is what settles::

    cash = sum_t dt * (p_t * d_t - p_t * c_t - k * d_t)

with ``k`` the throughput cost in EUR per MWh *delivered to the grid*. Charging
at a negative price earns money; that is real and is left alone.

Why there is a terminal value at all
------------------------------------
A 24h horizon with no terminal condition always ends the day empty: the last
stored MWh is free revenue inside the horizon and worth nothing outside it. That
is precisely the midnight SoC reset PLAN.md forbids, arrived at by the LP rather
than by a line of code, which is worse because nothing in the diff shows it. So
closing inventory is marked at ``v = max(0, eta * (p_ref - k))`` EUR/MWh — what
it would fetch if sold at the reference level, after the discharge leg and the
throughput cost it still owes.

``p_ref`` is supplied by the caller (:mod:`dispatch.rolling` derives it from
*trailing realised* prices) and must satisfy two properties, neither optional:

* **Knowable at gate closure.** It is built from market days ``<= D-1``, whose
  prices were published at 13:00 local on ``D-2`` — before 12:00 local on ``D-1``.
* **Identical across curves.** The oracle, the forecast and the naive run must be
  scored against the same objective or the comparison is meaningless. A reference
  read off the day's *own* decision prices would differ between curves and would
  destroy the per-day upper bound below.

Three numbers, and which one is "the value"
-------------------------------------------
:class:`DayValuation` reports all of:

``cash_eur``
    Settled cash. The headline annual number (EUR/MW/yr) is a sum of these.
``terminal_value_eur`` / ``opening_value_eur``
    ``v`` times closing / opening inventory. Marks, not cash.
``value_added_eur = cash + terminal - opening``
    What the day's trading added over holding the opening inventory and doing
    nothing. This is the quantity the LP maximises, and so the quantity the
    invariants are stated on: it is exactly ``0`` on a flat price curve, never
    negative (doing nothing is always feasible), and monotone in spread.

The per-day invariant CLAUDE.md requires —
``value(forecast schedule @ realised) <= value(oracle schedule @ realised)`` —
holds on ``value_added_eur`` **by construction and exactly**, provided both are
solved from the same opening SoC with the same ``p_ref``: the frozen forecast
schedule is a feasible point of the oracle's own problem, and the oracle is its
maximiser. :func:`assert_oracle_dominates` is that statement as an assertion.
Across two independently rolled trajectories the opening SoCs differ and no such
bound exists; C6 therefore compares against an oracle re-solved from the
forecast run's own opening SoC, which is why ``soc_start_mwh`` is an explicit
argument here rather than internal state.

Simultaneous charge and discharge
---------------------------------
PLAN.md requires an explicit check for it and calls it an LP artefact needing a
penalty term or a MILP. It is not hypothetical here. With a binding upper SoC
bound, ``c_t`` and ``d_t`` both positive lets the battery draw a net
``c - d = c * (1 - eta**2) > 0`` MW from the grid while its stored energy stays
flat — i.e. burn power in the round-trip losses. At a sufficiently negative price
being paid to consume beats the throughput cost of doing it, and the LP takes the
trade: the threshold is ``|p| > k * eta**2 / (1 - eta**2)``, about
``-14.7 EUR/MWh`` at the committed settings. A real single-inverter BESS cannot
do this. :func:`simultaneity_report` measures it on every solve, and
``forbid_simultaneous=True`` rules it out exactly with one binary per interval
(scipy's HiGHS MILP). The pure LP stays the default because that is what C5
scopes; the gap between the two is a reported number, not an assumption.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.optimize import linprog, milp, Bounds, LinearConstraint

from data.config import load_battery_config

TerminalMode = Literal["trailing_value", "floor", "none"]

VALID_TERMINAL_MODES: tuple[str, ...] = ("trailing_value", "floor", "none")


class DispatchError(RuntimeError):
    """The dispatch problem is malformed, infeasible, or the solver failed."""


# ---------------------------------------------------------------------------
# Specification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatterySpec:
    """The asset and the conventions it is optimised under.

    Frozen on purpose: a cycle that wants different numbers constructs a new
    spec (and says so in its results), rather than mutating one mid-run.
    """

    power_mw: float
    energy_mwh: float
    round_trip_efficiency: float
    throughput_cost_eur_per_mwh: float
    initial_soc_fraction: float = 0.5
    terminal_mode: TerminalMode = "trailing_value"
    terminal_floor_fraction: float = 0.0
    forbid_simultaneous: bool = False
    zero_tolerance_mw: float = 1e-7
    objective_check_rtol: float = 1e-6

    def __post_init__(self) -> None:
        if not self.power_mw > 0:
            raise DispatchError(f"power_mw must be > 0, got {self.power_mw}")
        if not self.energy_mwh > 0:
            raise DispatchError(f"energy_mwh must be > 0, got {self.energy_mwh}")
        if not 0 < self.round_trip_efficiency <= 1:
            raise DispatchError(
                f"round_trip_efficiency must be in (0, 1], got "
                f"{self.round_trip_efficiency}"
            )
        if self.throughput_cost_eur_per_mwh < 0:
            raise DispatchError(
                f"throughput_cost_eur_per_mwh must be >= 0, got "
                f"{self.throughput_cost_eur_per_mwh}"
            )
        if not 0 <= self.initial_soc_fraction <= 1:
            raise DispatchError(
                f"initial_soc_fraction must be in [0, 1], got {self.initial_soc_fraction}"
            )
        if self.terminal_mode not in VALID_TERMINAL_MODES:
            raise DispatchError(
                f"unknown terminal_mode {self.terminal_mode!r}; "
                f"expected one of {VALID_TERMINAL_MODES}"
            )
        if not 0 <= self.terminal_floor_fraction <= 1:
            raise DispatchError(
                f"terminal_floor_fraction must be in [0, 1], got "
                f"{self.terminal_floor_fraction}"
            )

    # -- derived ----------------------------------------------------------
    @property
    def eta_leg(self) -> float:
        """Per-leg efficiency, ``sqrt(round_trip_efficiency)``. Symmetric."""
        return math.sqrt(self.round_trip_efficiency)

    @property
    def duration_hours(self) -> float:
        return self.energy_mwh / self.power_mw

    @property
    def initial_soc_mwh(self) -> float:
        return self.initial_soc_fraction * self.energy_mwh

    @property
    def terminal_floor_mwh(self) -> float:
        return self.terminal_floor_fraction * self.energy_mwh

    @property
    def simultaneity_price_threshold(self) -> float:
        """Price below which burning power in the losses pays, at a full battery.

        Returns a *negative* number (or ``-inf`` when nothing stops it): the LP
        has an incentive to charge and discharge at once when
        ``p < -k * eta**2 / (1 - eta**2)``. Reported so the check's findings can
        be compared against the threshold that predicts them.
        """
        eta_sq = self.round_trip_efficiency
        if eta_sq >= 1.0:
            # No loss channel to burn: matched charge and discharge draw a net
            # zero from the grid whatever the price, so no price makes it pay.
            return -math.inf
        return -self.throughput_cost_eur_per_mwh * eta_sq / (1.0 - eta_sq)

    def terminal_price(self, reference_price: float | None) -> float:
        """EUR per MWh of *stored* energy left at the end of the horizon.

        ``eta * (p_ref - k)``, floored at zero: energy in the store will pay the
        discharge leg and the throughput cost on its way out, and holding it can
        never be worth less than nothing. A negative mark would pay the LP to
        burn energy, which is the artefact this module already has one of.
        """
        if self.terminal_mode != "trailing_value":
            return 0.0
        if reference_price is None or not np.isfinite(reference_price):
            raise DispatchError(
                "terminal_mode='trailing_value' needs a finite reference price; "
                "got " + repr(reference_price)
            )
        return max(
            0.0,
            self.eta_leg * (float(reference_price) - self.throughput_cost_eur_per_mwh),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "power_mw": self.power_mw,
            "energy_mwh": self.energy_mwh,
            "duration_hours": round(self.duration_hours, 6),
            "round_trip_efficiency": self.round_trip_efficiency,
            "eta_leg": round(self.eta_leg, 8),
            "throughput_cost_eur_per_mwh": self.throughput_cost_eur_per_mwh,
            "initial_soc_fraction": self.initial_soc_fraction,
            "initial_soc_mwh": round(self.initial_soc_mwh, 8),
            "terminal_mode": self.terminal_mode,
            "terminal_floor_fraction": self.terminal_floor_fraction,
            "forbid_simultaneous": self.forbid_simultaneous,
            "simultaneity_price_threshold_eur_per_mwh": round(
                self.simultaneity_price_threshold, 6
            )
            if np.isfinite(self.simultaneity_price_threshold)
            else None,
        }

    @classmethod
    def from_config(
        cls, config: dict[str, Any] | None = None, **overrides: Any
    ) -> "BatterySpec":
        """Build the committed spec from ``config/battery.yaml``.

        ``overrides`` exists for the C15 sensitivities (throughput cost,
        duration, terminal mode) and for tests, and every override a run uses is
        recorded in its summary — a sensitivity that is not labelled as one is
        just an undocumented change of result.
        """
        cfg = config or load_battery_config()
        battery = cfg["battery"]
        terminal = cfg.get("terminal") or {}
        solver = cfg.get("solver") or {}
        power = float(battery["power_mw"])
        fields: dict[str, Any] = {
            "power_mw": power,
            "energy_mwh": power * float(battery["duration_hours"]),
            "round_trip_efficiency": float(battery["round_trip_efficiency"]),
            "throughput_cost_eur_per_mwh": float(
                battery["throughput_cost_eur_per_mwh"]
            ),
            "initial_soc_fraction": float(battery.get("initial_soc_fraction", 0.5)),
            "terminal_mode": str(terminal.get("mode", "trailing_value")),
            "terminal_floor_fraction": float(terminal.get("floor_fraction", 0.0)),
            "forbid_simultaneous": bool(solver.get("forbid_simultaneous", False)),
            "zero_tolerance_mw": float(solver.get("zero_tolerance_mw", 1e-7)),
            "objective_check_rtol": float(solver.get("objective_check_rtol", 1e-6)),
        }
        # `duration_hours` is a config-level convenience, not a spec field.
        if "duration_hours" in overrides:
            fields["energy_mwh"] = fields["power_mw"] * float(
                overrides.pop("duration_hours")
            )
        unknown = set(overrides) - set(fields)
        if unknown:
            raise DispatchError(f"unknown BatterySpec override(s): {sorted(unknown)}")
        fields.update(overrides)
        return cls(**fields)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimultaneityReport:
    """Intervals in which the schedule both charges and discharges.

    PLAN.md's required check. ``n_intervals`` of zero is the expected and
    desirable reading; anything else is a FLAG, and ``energy_burned_mwh`` says
    how much grid energy the schedule puts through the round-trip losses on
    purpose rather than to move energy in time.
    """

    n_intervals: int
    n_intervals_negative_price: int
    max_overlap_mw: float
    energy_burned_mwh: float
    cash_from_overlap_eur: float
    min_price_with_overlap: float | None

    @property
    def found(self) -> bool:
        return self.n_intervals > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_intervals": self.n_intervals,
            "n_intervals_negative_price": self.n_intervals_negative_price,
            "max_overlap_mw": round(self.max_overlap_mw, 8),
            "energy_burned_mwh": round(self.energy_burned_mwh, 8),
            "cash_from_overlap_eur": round(self.cash_from_overlap_eur, 6),
            "min_price_with_overlap": (
                None
                if self.min_price_with_overlap is None
                else round(self.min_price_with_overlap, 4)
            ),
        }


@dataclass(frozen=True)
class DaySchedule:
    """A schedule, frozen. Everything needed to settle it later and nothing more.

    ``objective_eur`` is the optimiser's own value **on the decision prices**.
    It is kept so the solve can be audited (and because an LP objective that
    disagrees with a recomputation of the same quantity means the matrices are
    wrong), and it is never a result: see :func:`value_schedule`.
    """

    index: pd.DatetimeIndex
    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    soc_mwh: np.ndarray
    soc_start_mwh: float
    interval_hours: float
    terminal_price_eur_per_mwh: float
    decision_prices: np.ndarray
    objective_eur: float
    solver_status: str
    n_variables: int
    integral: bool

    @property
    def soc_end_mwh(self) -> float:
        return float(self.soc_mwh[-1]) if len(self.soc_mwh) else self.soc_start_mwh

    @property
    def n_intervals(self) -> int:
        return int(len(self.index))

    def frame(self) -> pd.DataFrame:
        """The schedule as a UTC-indexed frame, for persisting or plotting."""
        return pd.DataFrame(
            {
                "charge_mw": self.charge_mw,
                "discharge_mw": self.discharge_mw,
                "soc_mwh": self.soc_mwh,
                "decision_price": self.decision_prices,
            },
            index=self.index,
        )


@dataclass(frozen=True)
class DayValuation:
    """What a frozen schedule earned at a given set of prices.

    The distinction between the three money fields is the point of the class;
    see the module docstring. ``prices_are_decision_prices`` records whether
    this is a settlement at realised prices or a read-back of the decision
    problem — the oracle curve is the one case where they are the same vector,
    and a result that quietly relies on that is the bug PLAN.md names.
    """

    cash_eur: float
    terminal_value_eur: float
    opening_value_eur: float
    energy_charged_mwh: float
    energy_discharged_mwh: float
    throughput_cost_eur: float
    soc_start_mwh: float
    soc_end_mwh: float
    terminal_price_eur_per_mwh: float
    n_intervals: int
    prices_are_decision_prices: bool
    simultaneity: SimultaneityReport = field(
        default_factory=lambda: SimultaneityReport(0, 0, 0.0, 0.0, 0.0, None)
    )

    @property
    def value_added_eur(self) -> float:
        """Value created over holding the opening inventory and doing nothing."""
        return self.cash_eur + self.terminal_value_eur - self.opening_value_eur

    def as_dict(self) -> dict[str, Any]:
        return {
            "cash_eur": round(self.cash_eur, 6),
            "terminal_value_eur": round(self.terminal_value_eur, 6),
            "opening_value_eur": round(self.opening_value_eur, 6),
            "value_added_eur": round(self.value_added_eur, 6),
            "energy_charged_mwh": round(self.energy_charged_mwh, 8),
            "energy_discharged_mwh": round(self.energy_discharged_mwh, 8),
            "throughput_cost_eur": round(self.throughput_cost_eur, 6),
            "soc_start_mwh": round(self.soc_start_mwh, 8),
            "soc_end_mwh": round(self.soc_end_mwh, 8),
            "terminal_price_eur_per_mwh": round(self.terminal_price_eur_per_mwh, 6),
            "n_intervals": self.n_intervals,
            "prices_are_decision_prices": self.prices_are_decision_prices,
            "simultaneity": self.simultaneity.as_dict(),
        }


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------


def _as_price_array(prices: pd.Series | np.ndarray | list[float]) -> np.ndarray:
    values = np.asarray(
        prices.to_numpy() if isinstance(prices, pd.Series) else prices, dtype=float
    )
    if values.ndim != 1:
        raise DispatchError(f"prices must be 1-D, got shape {values.shape}")
    if len(values) == 0:
        raise DispatchError("cannot dispatch an empty price vector")
    if not np.isfinite(values).all():
        n_bad = int((~np.isfinite(values)).sum())
        raise DispatchError(
            f"{n_bad} of {len(values)} decision prices are NaN or infinite. A day "
            f"cannot be committed from a partial price vector — the caller must "
            f"skip the day and report it skipped, not fill the hole here."
        )
    return values


def _build_day_program(
    prices: np.ndarray,
    spec: BatterySpec,
    soc_start_mwh: float,
    interval_hours: float,
    terminal_price: float,
) -> tuple[np.ndarray, LinearConstraint, Bounds, int]:
    """Objective, SoC-balance equalities and bounds for one horizon.

    Variable order is ``[c_0..c_{n-1}, d_0..d_{n-1}, s_0..s_{n-1}]`` with ``s_t``
    the stored energy at the *end* of interval ``t``. Minimisation form, so the
    cost vector is the negative of revenue.
    """
    n = len(prices)
    dt = interval_hours
    eta = spec.eta_leg

    # minimise  -(revenue) = -(sum dt (p d - p c - k d)) - terminal * s_{n-1}
    cost = np.concatenate(
        [
            prices * dt,  # charging pays p per MWh drawn
            -(prices - spec.throughput_cost_eur_per_mwh) * dt,
            np.zeros(n),
        ]
    )
    cost[2 * n + (n - 1)] = -terminal_price

    # s_t - s_{t-1} - eta*dt*c_t + (dt/eta)*d_t = 0, with s_{-1} = soc_start
    balance = np.zeros((n, 3 * n))
    rhs = np.zeros(n)
    for t in range(n):
        balance[t, t] = -eta * dt
        balance[t, n + t] = dt / eta
        balance[t, 2 * n + t] = 1.0
        if t == 0:
            rhs[t] = soc_start_mwh
        else:
            balance[t, 2 * n + t - 1] = -1.0
    constraint = LinearConstraint(balance, lb=rhs, ub=rhs)

    lower = np.concatenate([np.zeros(n), np.zeros(n), np.zeros(n)])
    upper = np.concatenate(
        [
            np.full(n, spec.power_mw),
            np.full(n, spec.power_mw),
            np.full(n, spec.energy_mwh),
        ]
    )
    if spec.terminal_mode == "floor":
        lower[2 * n + (n - 1)] = min(spec.terminal_floor_mwh, spec.energy_mwh)
    return cost, constraint, Bounds(lb=lower, ub=upper), n


def solve_day(
    prices: pd.Series | np.ndarray | list[float],
    spec: BatterySpec,
    soc_start_mwh: float,
    index: pd.DatetimeIndex | None = None,
    interval_hours: float = 1.0,
    reference_price: float | None = None,
) -> DaySchedule:
    """Optimise one horizon against ``prices``, opening at ``soc_start_mwh``.

    ``prices`` are **decision** prices. For the oracle curve they are the
    realised prices; for any other curve they are a forecast, and the returned
    schedule must then be settled against realised prices via
    :func:`value_schedule` rather than read off ``objective_eur``.

    ``reference_price`` is the trailing realised price level used to mark closing
    inventory (see the module docstring). It is required under
    ``terminal_mode='trailing_value'`` and ignored otherwise.
    """
    values = _as_price_array(prices)
    if isinstance(prices, pd.Series) and index is None:
        index = prices.index  # type: ignore[assignment]
    if index is None:
        raise DispatchError("solve_day needs an index (pass a Series or index=)")
    if len(index) != len(values):
        raise DispatchError(
            f"index has {len(index)} entries but {len(values)} prices were given"
        )
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise DispatchError("solve_day requires a tz-aware (UTC) DatetimeIndex")
    if interval_hours <= 0:
        raise DispatchError(f"interval_hours must be > 0, got {interval_hours}")
    if not -1e-9 <= soc_start_mwh <= spec.energy_mwh + 1e-9:
        raise DispatchError(
            f"opening SoC {soc_start_mwh} is outside [0, {spec.energy_mwh}]"
        )
    soc_start = float(min(max(soc_start_mwh, 0.0), spec.energy_mwh))

    terminal_price = spec.terminal_price(reference_price)
    cost, constraint, bounds, n = _build_day_program(
        values, spec, soc_start, interval_hours, terminal_price
    )

    if spec.forbid_simultaneous:
        # One binary u_t per interval: charge is allowed only when u_t = 1,
        # discharge only when u_t = 0. Exact, and 24 binaries a day is free.
        integrality = np.concatenate(
            [np.zeros(3 * n), np.ones(n)]
        )
        cost_m = np.concatenate([cost, np.zeros(n)])
        rows = []
        for t in range(n):
            row_c = np.zeros(4 * n)
            row_c[t] = 1.0
            row_c[3 * n + t] = -spec.power_mw
            rows.append(row_c)
            row_d = np.zeros(4 * n)
            row_d[n + t] = 1.0
            row_d[3 * n + t] = spec.power_mw
            rows.append(row_d)
        exclusivity = LinearConstraint(
            np.vstack(rows),
            lb=np.array([-np.inf, -np.inf] * n),
            ub=np.array([0.0, spec.power_mw] * n),
        )
        balance_m = LinearConstraint(
            np.hstack([constraint.A, np.zeros((n, n))]),
            lb=constraint.lb,
            ub=constraint.ub,
        )
        bounds_m = Bounds(
            lb=np.concatenate([bounds.lb, np.zeros(n)]),
            ub=np.concatenate([bounds.ub, np.ones(n)]),
        )
        result = milp(
            c=cost_m,
            constraints=[balance_m, exclusivity],
            bounds=bounds_m,
            integrality=integrality,
        )
        if not result.success or result.x is None:
            raise DispatchError(
                f"MILP dispatch failed: {result.message} (status {result.status})"
            )
        solution = np.asarray(result.x, dtype=float)[: 3 * n]
        objective = -float(result.fun)
        status = str(result.message)
        n_vars = 4 * n
    else:
        result = linprog(
            c=cost,
            A_eq=constraint.A,
            b_eq=constraint.lb,
            bounds=list(zip(bounds.lb, bounds.ub)),
            method="highs",
        )
        if not result.success or result.x is None:
            raise DispatchError(
                f"LP dispatch failed: {result.message} (status {result.status})"
            )
        solution = np.asarray(result.x, dtype=float)
        objective = -float(result.fun)
        status = str(result.message)
        n_vars = 3 * n

    charge = _clean(solution[:n], spec.zero_tolerance_mw, spec.power_mw)
    discharge = _clean(solution[n : 2 * n], spec.zero_tolerance_mw, spec.power_mw)
    # Recompute SoC from the cleaned instructions rather than trusting the
    # solver's own s_t: the schedule is what gets committed, so the state must be
    # the state that schedule actually produces.
    soc = _simulate_soc(charge, discharge, spec, soc_start, interval_hours)

    schedule = DaySchedule(
        index=index,
        charge_mw=charge,
        discharge_mw=discharge,
        soc_mwh=soc,
        soc_start_mwh=soc_start,
        interval_hours=interval_hours,
        terminal_price_eur_per_mwh=terminal_price,
        decision_prices=values,
        objective_eur=objective,
        solver_status=status,
        n_variables=n_vars,
        integral=bool(spec.forbid_simultaneous),
    )

    # The LP's own objective and an independent recomputation of the same
    # quantity must agree. They are two different expressions of one number, so
    # a disagreement means the matrices encode a different problem than the
    # docstring claims — which is exactly the kind of error no result would show.
    recomputed = value_schedule(
        schedule, values, spec, prices_are_decision_prices=True
    )
    expected = recomputed.cash_eur + recomputed.terminal_value_eur
    scale = max(1.0, abs(expected), abs(objective))
    if abs(expected - objective) > spec.objective_check_rtol * scale:
        raise DispatchError(
            f"solver objective {objective:.8f} disagrees with the recomputed "
            f"cash+terminal {expected:.8f} on {index[0].isoformat()} — the LP "
            f"matrices do not encode the documented problem"
        )
    return schedule


def _clean(values: np.ndarray, tolerance: float, cap: float) -> np.ndarray:
    """Snap solver noise to zero and clip to the rating, without hiding anything.

    HiGHS returns values like ``-3e-14`` and ``P + 1e-13``. Both are noise, and
    both would otherwise show up as spurious "simultaneous charge/discharge" or
    as a bound violation. The tolerance is tiny and configured; anything larger
    than it survives into the schedule and into the checks.
    """
    out = np.asarray(values, dtype=float).copy()
    out[np.abs(out) < tolerance] = 0.0
    if (out < -tolerance).any():
        raise DispatchError("solver returned a materially negative power")
    out = np.clip(out, 0.0, cap)
    return out


def _simulate_soc(
    charge: np.ndarray,
    discharge: np.ndarray,
    spec: BatterySpec,
    soc_start: float,
    interval_hours: float,
) -> np.ndarray:
    """Roll the SoC forward through a schedule, asserting it stays feasible."""
    eta = spec.eta_leg
    soc = np.empty(len(charge), dtype=float)
    level = soc_start
    slack = 1e-6 * max(1.0, spec.energy_mwh)
    for t in range(len(charge)):
        level = (
            level
            + eta * charge[t] * interval_hours
            - discharge[t] * interval_hours / eta
        )
        if level < -slack or level > spec.energy_mwh + slack:
            raise DispatchError(
                f"schedule drives SoC to {level:.9f} MWh at interval {t}, outside "
                f"[0, {spec.energy_mwh}]"
            )
        level = min(max(level, 0.0), spec.energy_mwh)
        soc[t] = level
    return soc


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------


def simultaneity_report(
    schedule: DaySchedule, spec: BatterySpec, prices: np.ndarray
) -> SimultaneityReport:
    """PLAN.md's required check: where does the schedule charge and discharge at once?

    ``energy_burned_mwh`` is the grid energy that the overlap puts through the
    round-trip losses — the physically impossible part — and
    ``cash_from_overlap_eur`` is what the schedule is paid for doing it, so the
    FLAG can carry a magnitude rather than just a count.
    """
    tol = spec.zero_tolerance_mw
    both = (schedule.charge_mw > tol) & (schedule.discharge_mw > tol)
    n = int(both.sum())
    if n == 0:
        return SimultaneityReport(0, 0, 0.0, 0.0, 0.0, None)
    overlap = np.minimum(schedule.charge_mw, schedule.discharge_mw)[both]
    dt = schedule.interval_hours
    prices_both = np.asarray(prices, dtype=float)[both]
    net_draw = (schedule.charge_mw - schedule.discharge_mw)[both]
    return SimultaneityReport(
        n_intervals=n,
        n_intervals_negative_price=int((prices_both < 0).sum()),
        max_overlap_mw=float(overlap.max()),
        # Grid energy dissipated rather than stored: both legs' losses on the
        # overlapping power.
        energy_burned_mwh=float((overlap * dt).sum() * (1.0 - spec.round_trip_efficiency)),
        cash_from_overlap_eur=float((-prices_both * net_draw * dt).sum()),
        min_price_with_overlap=float(prices_both.min()),
    )


def value_schedule(
    schedule: DaySchedule,
    prices: pd.Series | np.ndarray | list[float],
    spec: BatterySpec,
    prices_are_decision_prices: bool = False,
) -> DayValuation:
    """Settle a frozen schedule at ``prices``. The only source of reported value.

    Pass the **realised** price vector. ``prices_are_decision_prices`` must be
    set explicitly to ``True`` for the one legitimate case where the two
    coincide (the oracle curve, and the internal consistency check in
    :func:`solve_day`); it is recorded on the result so a summary can never
    present a decision-price read-back as a settlement by accident.
    """
    realised = _as_price_array(prices)
    if len(realised) != schedule.n_intervals:
        raise DispatchError(
            f"cannot settle a {schedule.n_intervals}-interval schedule against "
            f"{len(realised)} prices"
        )
    dt = schedule.interval_hours
    discharged = float((schedule.discharge_mw * dt).sum())
    charged = float((schedule.charge_mw * dt).sum())
    throughput_cost = spec.throughput_cost_eur_per_mwh * discharged
    cash = (
        float((realised * schedule.discharge_mw * dt).sum())
        - float((realised * schedule.charge_mw * dt).sum())
        - throughput_cost
    )
    v = schedule.terminal_price_eur_per_mwh
    return DayValuation(
        cash_eur=cash,
        terminal_value_eur=v * schedule.soc_end_mwh,
        opening_value_eur=v * schedule.soc_start_mwh,
        energy_charged_mwh=charged,
        energy_discharged_mwh=discharged,
        throughput_cost_eur=throughput_cost,
        soc_start_mwh=schedule.soc_start_mwh,
        soc_end_mwh=schedule.soc_end_mwh,
        terminal_price_eur_per_mwh=v,
        n_intervals=schedule.n_intervals,
        prices_are_decision_prices=bool(prices_are_decision_prices),
        simultaneity=simultaneity_report(schedule, spec, realised),
    )


# ---------------------------------------------------------------------------
# The invariant, as an assertion
# ---------------------------------------------------------------------------


def assert_oracle_dominates(
    candidate: DayValuation,
    oracle: DayValuation,
    label: str = "",
    atol: float = 1e-6,
) -> None:
    """CLAUDE.md's per-day invariant: nothing beats perfect foresight.

    Exact **only** when both schedules were solved from the same opening SoC
    against the same terminal price and settled at the same realised prices —
    then the candidate is a feasible point of the oracle's own problem. The
    preconditions are checked here rather than trusted, because the assertion is
    worthless if it is quietly comparing two different problems.

    ``atol`` absorbs float noise in the LP solution, nothing more: it is scaled
    by the size of the numbers being compared.
    """
    if abs(candidate.soc_start_mwh - oracle.soc_start_mwh) > 1e-7:
        raise DispatchError(
            f"{label}: oracle dominance is only defined from a common opening SoC "
            f"(candidate {candidate.soc_start_mwh}, oracle {oracle.soc_start_mwh})"
        )
    if abs(
        candidate.terminal_price_eur_per_mwh - oracle.terminal_price_eur_per_mwh
    ) > 1e-9:
        raise DispatchError(
            f"{label}: the two runs mark closing inventory at different prices "
            f"({candidate.terminal_price_eur_per_mwh} vs "
            f"{oracle.terminal_price_eur_per_mwh}) — they are not maximising the "
            f"same objective, so no bound holds"
        )
    if candidate.n_intervals != oracle.n_intervals:
        raise DispatchError(
            f"{label}: {candidate.n_intervals} vs {oracle.n_intervals} intervals"
        )
    scale = max(1.0, abs(oracle.value_added_eur), abs(candidate.value_added_eur))
    if candidate.value_added_eur > oracle.value_added_eur + atol * scale:
        raise DispatchError(
            f"{label}: a schedule beat perfect foresight at realised prices — "
            f"{candidate.value_added_eur:.8f} > {oracle.value_added_eur:.8f} EUR. "
            f"Either the oracle is not solving on realised prices, or the two "
            f"runs do not share a feasible set."
        )
