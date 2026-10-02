"""C5: the battery LP, the rolling horizon, and PLAN.md's dispatch invariants.

Offline only — every test here builds its own price vector. Nothing reads the
cache, nothing reaches the network, and nothing touches a sealed year.

The tests PLAN.md names for C5 are the first three sections: a hand-computed toy
price vector, value monotone in spread, and value exactly zero on a flat curve.
The rest guard the things that would make those three pass while the result was
still wrong — the efficiency convention, the market-day horizon on DST days, the
SoC carryover, the leak-free terminal mark, and the simultaneous charge/discharge
artefact PLAN.md requires a check for.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from data.config import load_battery_config
from data.contracts import local_day_hours
from dispatch.battery import (
    BatterySpec,
    DispatchError,
    assert_oracle_dominates,
    simultaneity_report,
    solve_day,
    value_schedule,
)
from dispatch.rolling import (
    RollingError,
    market_day_blocks,
    run_rolling_dispatch,
    trailing_reference_prices,
)

BERLIN = "Europe/Berlin"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def hours(n: int, start: str = "2024-03-05 00:00") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def lossless(**overrides) -> BatterySpec:
    """1 MW / 1 MWh, no losses, no cost, no terminal mark — arithmetic by hand."""
    fields = dict(
        power_mw=1.0,
        energy_mwh=1.0,
        round_trip_efficiency=1.0,
        throughput_cost_eur_per_mwh=0.0,
        terminal_mode="none",
    )
    fields.update(overrides)
    return BatterySpec(**fields)


def dispatch(prices, spec: BatterySpec, soc_start: float = 0.0, reference=None):
    series = pd.Series(np.asarray(prices, dtype=float), index=hours(len(prices)))
    schedule = solve_day(series, spec, soc_start_mwh=soc_start, reference_price=reference)
    valuation = value_schedule(
        schedule, series, spec, prices_are_decision_prices=True
    )
    return schedule, valuation


def local_day_series(
    day: dt.date, price: float = 50.0, tz: str = BERLIN
) -> pd.Series:
    """One complete market day of flat prices, however many hours the calendar says."""
    start = pd.Timestamp(day.isoformat(), tz=tz).tz_convert("UTC")
    n = local_day_hours(day, tz)
    index = pd.date_range(start, periods=n, freq="h", tz="UTC")
    return pd.Series(np.full(n, float(price)), index=index)


def flat_window(first: dt.date, n_days: int, price: float = 50.0) -> pd.Series:
    return pd.concat(
        [local_day_series(first + dt.timedelta(days=i), price) for i in range(n_days)]
    )


# ---------------------------------------------------------------------------
# 1. the hand-computed toy price vector (PLAN.md C5)
# ---------------------------------------------------------------------------


def test_toy_vector_lossless_costless_matches_hand_arithmetic():
    """Buy the cheap hour, sell the dear one. 1 MWh, no losses: exactly 90 EUR."""
    spec = lossless()
    schedule, valuation = dispatch([10.0, 10.0, 100.0, 100.0], spec, soc_start=0.0)

    assert valuation.cash_eur == pytest.approx(90.0, abs=1e-9)
    assert valuation.value_added_eur == pytest.approx(90.0, abs=1e-9)
    assert valuation.energy_charged_mwh == pytest.approx(1.0, abs=1e-9)
    assert valuation.energy_discharged_mwh == pytest.approx(1.0, abs=1e-9)
    # One full charge then one full discharge; the store never exceeds capacity.
    assert schedule.soc_mwh.max() == pytest.approx(1.0, abs=1e-9)
    assert schedule.soc_end_mwh == pytest.approx(0.0, abs=1e-9)


def test_toy_vector_with_efficiency_and_throughput_cost_matches_hand_arithmetic():
    """The full convention, by hand: eta per leg, cost per MWh *delivered*.

    ``rte = 0.81`` so ``eta = 0.9`` exactly. Filling a 1 MWh store needs
    ``1 / 0.9 = 10/9`` MWh from the grid, bought over two cheap hours because the
    1 MW rating caps one hour at 1 MWh. Emptying it delivers ``0.9`` MWh.

        cash = 0.9 * 100            (revenue)
             - (10/9) * 10          (grid energy at the cheap price)
             - 2.0 * 0.9            (throughput, per MWh delivered)
             = 90 - 100/9 - 1.8
    """
    spec = BatterySpec(
        power_mw=1.0,
        energy_mwh=1.0,
        round_trip_efficiency=0.81,
        throughput_cost_eur_per_mwh=2.0,
        terminal_mode="none",
    )
    assert spec.eta_leg == pytest.approx(0.9, abs=1e-12)

    _, valuation = dispatch([10.0, 10.0, 100.0, 100.0], spec, soc_start=0.0)

    expected = 0.9 * 100.0 - (10.0 / 9.0) * 10.0 - 2.0 * 0.9
    assert valuation.cash_eur == pytest.approx(expected, abs=1e-7)
    assert valuation.energy_charged_mwh == pytest.approx(10.0 / 9.0, abs=1e-7)
    assert valuation.energy_discharged_mwh == pytest.approx(0.9, abs=1e-7)
    assert valuation.throughput_cost_eur == pytest.approx(1.8, abs=1e-7)


def test_charging_at_a_negative_price_earns_money():
    """Being paid to consume is real, not an artefact. It must not be clipped away."""
    spec = lossless()
    _, valuation = dispatch([-30.0, 0.0, 0.0, 0.0], spec, soc_start=0.0)

    # Charge 1 MWh at -30: the grid pays 30 EUR. Nothing to sell into afterwards.
    assert valuation.energy_charged_mwh == pytest.approx(1.0, abs=1e-9)
    assert valuation.cash_eur == pytest.approx(30.0, abs=1e-9)


def test_committed_config_round_trip_efficiency_is_symmetric_sqrt():
    """PLAN.md: symmetric legs at sqrt(0.88). Asserted on the committed config."""
    spec = BatterySpec.from_config()
    cfg = load_battery_config()

    assert spec.round_trip_efficiency == cfg["battery"]["round_trip_efficiency"] == 0.88
    assert spec.eta_leg == pytest.approx(math.sqrt(0.88), abs=1e-12)
    # Symmetry is the statement that one leg squared is the round trip.
    assert spec.eta_leg**2 == pytest.approx(spec.round_trip_efficiency, abs=1e-12)
    assert spec.energy_mwh == spec.power_mw * cfg["battery"]["duration_hours"]
    assert 2.0 <= spec.throughput_cost_eur_per_mwh <= 5.0


# ---------------------------------------------------------------------------
# 2. value monotone in spread (PLAN.md C5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_name", ["lossless", "committed"])
def test_value_is_monotone_non_decreasing_in_spread(spec_name):
    """Widen the peak/trough gap and the day can only be worth more, never less."""
    spec = lossless() if spec_name == "lossless" else BatterySpec.from_config()
    reference = 50.0 if spec_name == "committed" else None

    values = []
    for spread in (0.0, 5.0, 20.0, 60.0, 200.0):
        prices = np.full(8, 50.0)
        prices[1] = 50.0 - spread / 2
        prices[6] = 50.0 + spread / 2
        _, valuation = dispatch(prices, spec, soc_start=0.5 * spec.energy_mwh,
                                reference=reference)
        values.append(valuation.value_added_eur)

    for narrower, wider in zip(values, values[1:]):
        assert wider >= narrower - 1e-9, f"value fell as spread widened: {values}"
    # And it is strictly increasing once the spread clears the round-trip cost.
    assert values[-1] > values[1] + 1.0


def test_value_is_monotone_non_decreasing_in_capacity_and_power():
    """More MWh or more MW cannot be worth less: both only enlarge the feasible set."""
    prices = np.array([10.0, 10.0, 10.0, 10.0, 100.0, 100.0, 100.0, 100.0])

    by_energy = [
        dispatch(prices, lossless(energy_mwh=e), soc_start=0.0)[1].value_added_eur
        for e in (0.5, 1.0, 2.0, 4.0)
    ]
    for smaller, bigger in zip(by_energy, by_energy[1:]):
        assert bigger >= smaller - 1e-9, by_energy

    by_power = [
        dispatch(prices, lossless(power_mw=p, energy_mwh=4.0), soc_start=0.0)[
            1
        ].value_added_eur
        for p in (0.25, 0.5, 1.0, 2.0)
    ]
    for smaller, bigger in zip(by_power, by_power[1:]):
        assert bigger >= smaller - 1e-9, by_power


# ---------------------------------------------------------------------------
# 3. value exactly zero on a flat curve (PLAN.md C5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("price", [0.0, 2.0, 50.0, 400.0])
@pytest.mark.parametrize("soc_fraction", [0.0, 0.5, 1.0])
def test_value_added_is_exactly_zero_on_a_flat_non_negative_curve(price, soc_fraction):
    """No spread, no value — PLAN.md's flat-curve test, with its one real caveat.

    Two things this pins, both of which the first draft of this test got wrong.

    *It is ``value_added`` that must vanish, not ``cash``.* A battery that opens
    half full on a flat positive curve can always liquidate, and that cash is
    inventory turning into money rather than value the day's trading created.
    Marking opening and closing inventory at the same price is what separates the
    two, which is why the valuation carries three money fields instead of one.

    *And only on a **non-negative** flat curve.* See
    :func:`test_a_flat_negative_curve_is_genuinely_worth_something` — a battery is
    a load, and a load has value at a negative price with no spread whatsoever.
    """
    spec = BatterySpec.from_config()
    _, valuation = dispatch(
        np.full(24, price),
        spec,
        soc_start=soc_fraction * spec.energy_mwh,
        reference=price,
    )
    assert valuation.value_added_eur == pytest.approx(0.0, abs=1e-7)


def test_a_flat_negative_curve_is_genuinely_worth_something():
    """FINDING C5-A: with no spread at all, a negative price still pays.

    PLAN.md's invariant is "value = 0 on a flat curve", and that is right for a
    non-negative one. At a flat *negative* price the battery is simply a load
    being paid to consume: it charges to full and never discharges, and the money
    is real. A lossless, costless battery shows it with no round-trip artefact
    anywhere in sight, which is how this is distinguished from the simultaneous
    charge/discharge problem that also appears at negative prices.
    """
    # Lossless, so there is no round-trip channel to burn power through at all
    # (``simultaneity_price_threshold`` is -inf), but with a throughput cost so
    # that value-neutral churn between hours is not an alternative optimum either.
    ideal = BatterySpec(
        power_mw=1.0,
        energy_mwh=2.0,
        round_trip_efficiency=1.0,
        throughput_cost_eur_per_mwh=2.0,
        terminal_mode="trailing_value",
    )
    assert ideal.simultaneity_price_threshold == -math.inf
    schedule, valuation = dispatch(
        np.full(24, -25.0), ideal, soc_start=0.0, reference=-25.0
    )
    assert valuation.simultaneity.n_intervals == 0, "not the LP artefact"
    assert valuation.energy_discharged_mwh == pytest.approx(0.0, abs=1e-7)
    # Fill the store at -25 EUR/MWh: 2 MWh in, 50 EUR of genuine revenue.
    assert valuation.energy_charged_mwh == pytest.approx(2.0, abs=1e-7)
    assert valuation.value_added_eur == pytest.approx(50.0, abs=1e-6)
    assert schedule.soc_end_mwh == pytest.approx(2.0, abs=1e-7)


def test_a_flat_day_priced_away_from_the_mark_trades_toward_the_mark():
    """What a flat curve means depends on where the trailing level sits.

    "No spread, no trade" is only true for a flat day priced *at* the trailing
    level. Priced below it, buying and holding is a real trade and the LP fills
    up; priced above it, selling is, and the LP empties out. There is no
    non-degenerate flat case in which the LP stands still: at ``p_ref == p``
    holding and liquidating are worth the same to the penny, so the LP may return
    either, and the day's cycling is arbitrary while its value is exactly 0 (see
    the two tests above). Real prices make the exact tie measure-zero — a 7-day
    trailing median essentially never equals the day's own flat price — and the
    C5 run reports how often an exactly-flat day occurs at all.

    The direction being tested is also the reason the headline annual number is
    settled **cash** and not summed ``value_added``: trading toward the mark books
    an inventory revaluation, which is a mark, not money.
    """
    spec = BatterySpec.from_config()
    half = 0.5 * spec.energy_mwh

    cheap_today, cheap_value = dispatch(
        np.full(24, 60.0), spec, soc_start=half, reference=150.0
    )
    assert cheap_today.soc_end_mwh > half, "a day below the trailing level should fill"
    assert cheap_value.energy_discharged_mwh == pytest.approx(0.0, abs=1e-9)

    dear_today, dear_value = dispatch(
        np.full(24, 150.0), spec, soc_start=half, reference=60.0
    )
    assert dear_today.soc_end_mwh < half, "a day above the trailing level should empty"
    assert dear_value.energy_charged_mwh == pytest.approx(0.0, abs=1e-9)
    assert dear_value.cash_eur > 0.0


def test_the_flat_curve_optimum_is_value_neutral_even_where_it_is_degenerate():
    """The degeneracy above costs nothing: whatever the LP picks, the day adds 0.

    Stated as cash, so it is checkable against the artefacts: on a flat curve the
    only cash is opening inventory liquidated at the mark.
    """
    spec = BatterySpec.from_config()
    schedule, valuation = dispatch(
        np.full(24, 60.0), spec, soc_start=0.5 * spec.energy_mwh, reference=60.0
    )
    mark = schedule.terminal_price_eur_per_mwh
    assert valuation.cash_eur == pytest.approx(
        mark * (schedule.soc_start_mwh - schedule.soc_end_mwh), abs=1e-6
    )
    assert valuation.value_added_eur == pytest.approx(0.0, abs=1e-7)


def test_value_added_is_never_negative_because_doing_nothing_is_feasible():
    """Standing still is always in the feasible set, so the optimum cannot lose."""
    rng = np.random.default_rng(5)
    spec = BatterySpec.from_config()
    for _ in range(25):
        prices = rng.normal(70.0, 60.0, size=24)
        _, valuation = dispatch(
            prices, spec, soc_start=0.5 * spec.energy_mwh, reference=70.0
        )
        assert valuation.value_added_eur >= -1e-7


# ---------------------------------------------------------------------------
# the LP's own objective must equal an independent recomputation
# ---------------------------------------------------------------------------


def test_solver_objective_equals_recomputed_cash_plus_terminal_value():
    """Two expressions of one number. Disagreement means the matrices are wrong."""
    rng = np.random.default_rng(11)
    spec = BatterySpec.from_config()
    for _ in range(15):
        prices = rng.normal(80.0, 90.0, size=24)
        schedule, valuation = dispatch(
            prices, spec, soc_start=0.3 * spec.energy_mwh, reference=75.0
        )
        assert schedule.objective_eur == pytest.approx(
            valuation.cash_eur + valuation.terminal_value_eur, rel=1e-8, abs=1e-6
        )


def test_schedule_never_violates_power_or_energy_bounds():
    rng = np.random.default_rng(17)
    spec = BatterySpec.from_config()
    for _ in range(25):
        prices = rng.normal(60.0, 150.0, size=24)
        schedule, _ = dispatch(prices, spec, soc_start=0.5 * spec.energy_mwh,
                               reference=60.0)
        assert schedule.charge_mw.min() >= -1e-12
        assert schedule.discharge_mw.min() >= -1e-12
        assert schedule.charge_mw.max() <= spec.power_mw + 1e-9
        assert schedule.discharge_mw.max() <= spec.power_mw + 1e-9
        assert schedule.soc_mwh.min() >= -1e-9
        assert schedule.soc_mwh.max() <= spec.energy_mwh + 1e-9


def test_a_partial_price_vector_is_refused_rather_than_filled():
    """NOTE C4-02's hole must stop a day, not be imputed inside the LP."""
    spec = BatterySpec.from_config()
    prices = np.full(24, 50.0)
    prices[7] = np.nan
    with pytest.raises(DispatchError, match="partial price vector"):
        dispatch(prices, spec, soc_start=0.0, reference=50.0)


# ---------------------------------------------------------------------------
# the terminal condition, and why it exists
# ---------------------------------------------------------------------------


def test_without_a_terminal_condition_the_lp_empties_the_battery_at_midnight():
    """The reason the default is not ``none``: the LP invents the forbidden reset.

    PLAN.md forbids resetting SoC to zero at midnight. A 24h horizon with no
    terminal condition does it unprompted, because the last stored MWh is free
    revenue inside the horizon and worthless outside it.
    """
    spec = BatterySpec.from_config(terminal_mode="none")
    schedule, _ = dispatch(np.full(24, 80.0), spec, soc_start=spec.energy_mwh)
    assert schedule.soc_end_mwh == pytest.approx(0.0, abs=1e-7)

    # The committed mode marks the inventory instead, and so keeps it whenever the
    # mark beats selling today. (At ``p_ref == p`` the two are worth exactly the
    # same and the LP may do either; see the flat-curve degeneracy tests.)
    marked = BatterySpec.from_config()
    kept, _ = dispatch(
        np.full(24, 80.0), marked, soc_start=marked.energy_mwh, reference=200.0
    )
    assert kept.soc_end_mwh == pytest.approx(marked.energy_mwh, abs=1e-7)


def test_terminal_mark_is_floored_at_zero_so_the_lp_is_never_paid_to_burn_energy():
    spec = BatterySpec.from_config()
    assert spec.terminal_price(-500.0) == 0.0
    assert spec.terminal_price(spec.throughput_cost_eur_per_mwh) == 0.0
    assert spec.terminal_price(100.0) == pytest.approx(
        spec.eta_leg * (100.0 - spec.throughput_cost_eur_per_mwh), abs=1e-12
    )


def test_trailing_value_mode_demands_a_reference_price():
    spec = BatterySpec.from_config()
    with pytest.raises(DispatchError, match="reference price"):
        dispatch(np.full(24, 50.0), spec, soc_start=0.0, reference=None)


def test_floor_mode_holds_the_closing_soc_above_the_floor():
    spec = BatterySpec.from_config(terminal_mode="floor", terminal_floor_fraction=0.5)
    schedule, _ = dispatch(np.full(24, 90.0), spec, soc_start=spec.energy_mwh)
    assert schedule.soc_end_mwh >= 0.5 * spec.energy_mwh - 1e-7


# ---------------------------------------------------------------------------
# simultaneous charge and discharge (PLAN.md C5: explicit check, FLAG if found)
# ---------------------------------------------------------------------------


def test_the_simultaneity_threshold_predicts_where_the_artefact_appears():
    """It is not hypothetical: a full battery plus a deep negative price triggers it.

    Net grid draw ``c - d = c (1 - eta**2) > 0`` with stored energy flat is the
    battery burning power in its own losses to be paid for consuming. The LP takes
    the trade below ``-k * eta**2 / (1 - eta**2)``.
    """
    spec = BatterySpec.from_config()
    threshold = spec.simultaneity_price_threshold
    assert threshold == pytest.approx(-2.0 * 0.88 / 0.12, abs=1e-9)

    # Well below the threshold, with the battery already full so it cannot absorb.
    deep = np.full(6, threshold - 100.0)
    schedule, valuation = dispatch(
        deep, spec, soc_start=spec.energy_mwh, reference=50.0
    )
    report = valuation.simultaneity
    assert report.found, "expected the LP artefact at a price far below the threshold"
    assert report.n_intervals_negative_price == report.n_intervals
    assert report.energy_burned_mwh > 0
    assert report.min_price_with_overlap < threshold

    # Just above it, the throughput cost makes burning uneconomic.
    shallow = np.full(6, threshold + 1.0)
    _, mild = dispatch(shallow, spec, soc_start=spec.energy_mwh, reference=50.0)
    assert not mild.simultaneity.found


def test_forbid_simultaneous_rules_the_artefact_out_exactly():
    """PLAN.md's named remedy: one binary per interval. Same prices, no overlap."""
    prices = np.full(6, -120.0)
    lp = BatterySpec.from_config()
    milp_spec = BatterySpec.from_config(forbid_simultaneous=True)

    _, lp_value = dispatch(prices, lp, soc_start=lp.energy_mwh, reference=50.0)
    milp_schedule, milp_value = dispatch(
        prices, milp_spec, soc_start=milp_spec.energy_mwh, reference=50.0
    )

    assert lp_value.simultaneity.found
    assert not milp_value.simultaneity.found
    assert milp_schedule.integral
    assert (milp_schedule.charge_mw * milp_schedule.discharge_mw).max() <= 1e-9
    # Forbidding a trade cannot make the day worth more: the MILP optimises over
    # a strict subset of the LP's feasible set.
    assert milp_value.value_added_eur <= lp_value.value_added_eur + 1e-6


def test_simultaneity_report_reads_zero_on_a_clean_schedule():
    spec = BatterySpec.from_config()
    schedule, valuation = dispatch(
        [10.0, 10.0, 100.0, 100.0], spec, soc_start=0.0, reference=50.0
    )
    report = simultaneity_report(schedule, spec, schedule.decision_prices)
    assert not report.found
    assert report.as_dict()["n_intervals"] == 0
    assert valuation.simultaneity.as_dict() == report.as_dict()


# ---------------------------------------------------------------------------
# commit-then-settle: the decision price vector and the settlement vector
# ---------------------------------------------------------------------------


def test_settling_a_frozen_schedule_at_realised_prices_differs_from_the_lp_objective():
    """PLAN.md's rule, as a behavioural test rather than a convention.

    Optimise on a wrong forecast, freeze the schedule, settle at realised. The
    LP's own objective is a number about the forecast; reporting it as value is
    the error the rule names, and here the two differ by a wide margin.
    """
    spec = BatterySpec.from_config()
    index = hours(24)
    forecast = pd.Series(np.full(24, 50.0), index=index)
    forecast.iloc[2] = 10.0     # forecast says hour 2 is cheap
    forecast.iloc[20] = 200.0   # and hour 20 is dear
    realised = pd.Series(np.full(24, 50.0), index=index)
    realised.iloc[2] = 200.0    # in fact it was the other way round
    realised.iloc[20] = 10.0

    schedule = solve_day(forecast, spec, soc_start_mwh=0.0, reference_price=50.0)
    settled = value_schedule(schedule, realised, spec)

    assert not settled.prices_are_decision_prices
    assert schedule.objective_eur > 100.0
    assert settled.value_added_eur < 0.0, "buying the peak and selling the trough loses"
    assert settled.cash_eur < schedule.objective_eur - 100.0


def test_the_oracle_dominates_any_frozen_schedule_from_the_same_opening_state():
    """CLAUDE.md's per-day invariant, on randomised price pairs.

    The forecast schedule is a feasible point of the oracle's own problem, so the
    oracle's optimum bounds it exactly — provided both open at the same SoC and
    mark closing inventory at the same price, which is what
    :func:`assert_oracle_dominates` insists on.
    """
    rng = np.random.default_rng(23)
    spec = BatterySpec.from_config()
    index = hours(24)
    for trial in range(40):
        realised = pd.Series(rng.normal(70.0, 70.0, size=24), index=index)
        forecast = realised + rng.normal(0.0, 40.0, size=24)
        soc0 = float(rng.uniform(0.0, spec.energy_mwh))
        reference = 65.0

        committed = solve_day(forecast, spec, soc0, reference_price=reference)
        oracle = solve_day(realised, spec, soc0, reference_price=reference)

        assert_oracle_dominates(
            value_schedule(committed, realised, spec),
            value_schedule(oracle, realised, spec, prices_are_decision_prices=True),
            label=f"trial {trial}",
        )


def test_the_oracle_dominates_a_random_feasible_schedule():
    """Not only forecast-driven schedules: any feasible schedule at all."""
    rng = np.random.default_rng(29)
    spec = BatterySpec.from_config()
    index = hours(24)
    realised = pd.Series(rng.normal(70.0, 80.0, size=24), index=index)
    soc0 = 0.5 * spec.energy_mwh
    oracle = solve_day(realised, spec, soc0, reference_price=70.0)
    oracle_value = value_schedule(
        oracle, realised, spec, prices_are_decision_prices=True
    )

    for _ in range(30):
        # A random "forecast" is just a random way of choosing a feasible schedule.
        noise = pd.Series(rng.normal(70.0, 120.0, size=24), index=index)
        other = solve_day(noise, spec, soc0, reference_price=70.0)
        assert_oracle_dominates(value_schedule(other, realised, spec), oracle_value)


def test_dominance_assertion_refuses_to_compare_two_different_problems():
    """The assertion is worthless if it silently compares mismatched setups."""
    spec = BatterySpec.from_config()
    index = hours(24)
    realised = pd.Series(np.linspace(10.0, 150.0, 24), index=index)

    from_empty = value_schedule(
        solve_day(realised, spec, 0.0, reference_price=60.0), realised, spec
    )
    from_full = value_schedule(
        solve_day(realised, spec, spec.energy_mwh, reference_price=60.0),
        realised,
        spec,
    )
    with pytest.raises(DispatchError, match="common opening SoC"):
        assert_oracle_dominates(from_empty, from_full)

    cheap_mark = value_schedule(
        solve_day(realised, spec, 0.0, reference_price=10.0), realised, spec
    )
    with pytest.raises(DispatchError, match="same objective"):
        assert_oracle_dominates(cheap_mark, from_empty)


def test_dominance_assertion_fires_when_something_beats_perfect_foresight():
    """A deliberately broken 'oracle' must trip the assertion, not sail past it."""
    spec = BatterySpec.from_config()
    index = hours(24)
    realised = pd.Series(np.linspace(10.0, 150.0, 24), index=index)
    good = value_schedule(
        solve_day(realised, spec, 0.0, reference_price=60.0), realised, spec
    )
    # An "oracle" that optimised on a flat curve and so earns nothing.
    broken = value_schedule(
        solve_day(pd.Series(np.full(24, 60.0), index=index), spec, 0.0,
                  reference_price=60.0),
        realised,
        spec,
    )
    with pytest.raises(DispatchError, match="beat perfect foresight"):
        assert_oracle_dominates(good, broken)


# ---------------------------------------------------------------------------
# the horizon is the market day: 23 and 25 hours included
# ---------------------------------------------------------------------------


def test_market_day_blocks_accept_23_and_25_hour_local_days():
    """The DST whitelist, applied to dispatch. No padding, no reindexing."""
    spring = dt.date(2024, 3, 31)   # 23 local hours in Europe/Berlin
    autumn = dt.date(2024, 10, 27)  # 25
    assert local_day_hours(spring, BERLIN) == 23
    assert local_day_hours(autumn, BERLIN) == 25

    for day, expected in ((spring, 23), (autumn, 25)):
        window = pd.concat(
            [
                local_day_series(day - dt.timedelta(days=1)),
                local_day_series(day),
                local_day_series(day + dt.timedelta(days=1)),
            ]
        )
        blocks, skips = market_day_blocks(window.index, BERLIN)
        found = {b.day: b for b in blocks}
        assert day in found, f"{day} was not dispatchable: {[s.as_dict() for s in skips]}"
        assert found[day].n_hours == expected
        assert found[day].expected_hours == expected
        assert found[day].is_complete


def test_a_short_day_that_is_not_a_dst_day_is_skipped_not_padded():
    day = dt.date(2024, 6, 10)
    window = pd.concat(
        [
            local_day_series(day - dt.timedelta(days=1)),
            local_day_series(day).drop(index=local_day_series(day).index[9]),
            local_day_series(day + dt.timedelta(days=1)),
        ]
    )
    blocks, skips = market_day_blocks(window.index, BERLIN)
    assert day not in {b.day for b in blocks}
    incomplete = [s for s in skips if s.day == day]
    assert incomplete and incomplete[0].reason == "incomplete"
    assert "23 of 24" in incomplete[0].detail


def test_the_dst_days_dispatch_as_whole_blocks_in_the_rolling_run():
    spec = BatterySpec.from_config()
    first = dt.date(2024, 10, 20)
    series = flat_window(first, 12, price=50.0)
    # Give the autumn day a spread so there is something to dispatch.
    autumn = dt.date(2024, 10, 27)
    block = series.index[pd.Series(series.index).dt.tz_convert(BERLIN).dt.date.to_numpy() == autumn]
    series.loc[block[0]] = 5.0
    series.loc[block[-1]] = 300.0

    result = run_rolling_dispatch("DE-LU", series, spec, tz=BERLIN)
    assert autumn in result.valuations
    assert result.valuations[autumn].n_intervals == 25
    lengths = {d: v.n_intervals for d, v in result.valuations.items()}
    assert set(lengths.values()) <= {23, 24, 25}


# ---------------------------------------------------------------------------
# the trailing terminal reference: leak-free and curve-independent
# ---------------------------------------------------------------------------


def test_trailing_reference_uses_only_days_published_before_gate_closure():
    series = flat_window(dt.date(2024, 5, 1), 15, price=40.0)
    references = trailing_reference_prices(series, BERLIN, trailing_days=7)
    # The first day has nothing before it; the rest do.
    assert dt.date(2024, 5, 1) not in references
    assert references[dt.date(2024, 5, 9)] == pytest.approx(40.0)
    # assert_reference_is_knowable runs inside; a violation would have raised.


def test_trailing_reference_ignores_the_days_own_prices():
    """Curve-independence is what makes the per-day oracle bound exact."""
    base = flat_window(dt.date(2024, 5, 1), 10, price=40.0)
    target = dt.date(2024, 5, 9)
    spiked = base.copy()
    mask = pd.Series(spiked.index).dt.tz_convert(BERLIN).dt.date.to_numpy() == target
    spiked.loc[spiked.index[mask]] = 900.0

    assert trailing_reference_prices(base, BERLIN)[target] == pytest.approx(
        trailing_reference_prices(spiked, BERLIN)[target]
    )


def test_trailing_reference_tracks_the_recent_level():
    low = flat_window(dt.date(2024, 5, 1), 8, price=20.0)
    high = flat_window(dt.date(2024, 5, 9), 8, price=200.0)
    references = trailing_reference_prices(pd.concat([low, high]), BERLIN,
                                           trailing_days=7)
    assert references[dt.date(2024, 5, 8)] == pytest.approx(20.0)
    assert references[dt.date(2024, 5, 16)] == pytest.approx(200.0)


def test_a_day_with_no_trailing_history_is_skipped_with_a_stated_reason():
    spec = BatterySpec.from_config()
    series = flat_window(dt.date(2024, 5, 1), 4, price=50.0)
    result = run_rolling_dispatch("DE-LU", series, spec, tz=BERLIN,
                                 min_trailing_days=2)
    reasons = {s.day: s.reason for s in result.skipped}
    assert reasons.get(dt.date(2024, 5, 2)) == "no_reference"
    assert dt.date(2024, 5, 2) not in result.valuations


def test_an_incomplete_trailing_day_does_not_contaminate_the_reference():
    series = flat_window(dt.date(2024, 5, 1), 10, price=40.0)
    holed_day = dt.date(2024, 5, 5)
    mask = pd.Series(series.index).dt.tz_convert(BERLIN).dt.date.to_numpy() == holed_day
    holed_index = series.index[mask]
    series.loc[holed_index] = 1000.0
    series = series.drop(index=holed_index[3])  # now a 23-hour non-DST day

    references = trailing_reference_prices(series, BERLIN, trailing_days=7)
    # 2024-05-08's window spans the holed day, which must be excluded entirely
    # rather than pooled at whatever hours survived.
    assert references[dt.date(2024, 5, 8)] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# the roll: SoC carries, nothing resets at midnight
# ---------------------------------------------------------------------------


def test_closing_soc_of_each_day_is_the_opening_soc_of_the_next():
    spec = BatterySpec.from_config()
    rng = np.random.default_rng(37)
    first = dt.date(2024, 6, 1)
    series = flat_window(first, 20, price=60.0)
    series.loc[:] = rng.normal(60.0, 70.0, size=len(series))

    result = run_rolling_dispatch("DE-LU", series, spec, tz=BERLIN)
    assert result.n_days >= 15
    for earlier, later in zip(result.days, result.days[1:]):
        assert result.soc_opening[later] == pytest.approx(
            result.schedules[earlier].soc_end_mwh, abs=1e-9
        )
    # And the first dispatched day opens at the configured initial fraction.
    assert result.soc_opening[result.days[0]] == pytest.approx(spec.initial_soc_mwh)


def test_a_skipped_day_carries_the_soc_across_unchanged():
    """The battery sat idle through the gap. It did not reset."""
    spec = BatterySpec.from_config()
    first = dt.date(2024, 6, 1)
    series = flat_window(first, 10, price=60.0)
    # A spread on day 2 so the battery ends that day somewhere interesting.
    day2 = first + dt.timedelta(days=2)
    idx2 = series.index[
        pd.Series(series.index).dt.tz_convert(BERLIN).dt.date.to_numpy() == day2
    ]
    series.loc[idx2[3]] = -50.0
    gap_day = first + dt.timedelta(days=4)
    idx_gap = series.index[
        pd.Series(series.index).dt.tz_convert(BERLIN).dt.date.to_numpy() == gap_day
    ]
    series = series.drop(index=idx_gap[5])

    result = run_rolling_dispatch("DE-LU", series, spec, tz=BERLIN)
    assert gap_day in {s.day for s in result.skipped}
    before = max(d for d in result.days if d < gap_day)
    after = min(d for d in result.days if d > gap_day)
    assert result.soc_opening[after] == pytest.approx(
        result.schedules[before].soc_end_mwh, abs=1e-9
    )


def test_the_rolling_oracle_settles_at_realised_prices_by_construction():
    """The oracle is the one curve where decision and realised prices coincide."""
    spec = BatterySpec.from_config()
    series = flat_window(dt.date(2024, 7, 1), 12, price=70.0)
    rng = np.random.default_rng(41)
    series.loc[:] = rng.normal(70.0, 50.0, size=len(series))

    result = run_rolling_dispatch("DE-LU", series, spec, tz=BERLIN)
    assert result.curve == "oracle"
    for day in result.days:
        valuation = result.valuations[day]
        assert valuation.prices_are_decision_prices
        assert valuation.value_added_eur >= -1e-7
        np.testing.assert_allclose(
            result.schedules[day].decision_prices, result.realised_prices[day]
        )


def test_a_rolling_forecast_run_never_beats_the_rolling_oracle_in_total():
    """The pooled half of CLAUDE.md's invariant, on a 30-day synthetic series."""
    spec = BatterySpec.from_config()
    rng = np.random.default_rng(43)
    series = flat_window(dt.date(2024, 8, 1), 30, price=70.0)
    realised = pd.Series(rng.normal(70.0, 60.0, size=len(series)), index=series.index)
    forecast = realised + rng.normal(0.0, 30.0, size=len(series))

    oracle = run_rolling_dispatch("DE-LU", realised, spec, tz=BERLIN)
    committed = run_rolling_dispatch(
        "DE-LU", realised, spec, decision_prices=forecast, curve="forecast", tz=BERLIN
    )
    assert committed.n_days == oracle.n_days
    assert committed.total_value_added_eur <= oracle.total_value_added_eur + 1e-6
    assert committed.total_cash_eur <= oracle.total_cash_eur + 1e-6


def test_daily_and_schedule_frames_cover_every_dispatched_hour():
    spec = BatterySpec.from_config()
    series = flat_window(dt.date(2024, 9, 1), 8, price=60.0)
    rng = np.random.default_rng(47)
    series.loc[:] = rng.normal(60.0, 40.0, size=len(series))
    result = run_rolling_dispatch("DE-LU", series, spec, tz=BERLIN)

    daily = result.daily_frame()
    schedules = result.schedule_frame()
    assert len(daily) == result.n_days
    assert daily["n_hours"].sum() == len(schedules)
    assert schedules.index.is_monotonic_increasing
    assert daily["cash_eur"].sum() == pytest.approx(result.total_cash_eur, abs=1e-6)
    assert set(daily["curve"]) == {"oracle"}


# ---------------------------------------------------------------------------
# spec validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"power_mw": 0.0}, "power_mw"),
        ({"energy_mwh": -1.0}, "energy_mwh"),
        ({"round_trip_efficiency": 0.0}, "round_trip_efficiency"),
        ({"round_trip_efficiency": 1.5}, "round_trip_efficiency"),
        ({"throughput_cost_eur_per_mwh": -1.0}, "throughput_cost"),
        ({"initial_soc_fraction": 1.5}, "initial_soc_fraction"),
        ({"terminal_mode": "wishful"}, "terminal_mode"),
        ({"terminal_floor_fraction": 2.0}, "terminal_floor_fraction"),
    ],
)
def test_a_nonsensical_spec_is_refused_at_construction(overrides, match):
    fields = dict(
        power_mw=1.0,
        energy_mwh=2.0,
        round_trip_efficiency=0.88,
        throughput_cost_eur_per_mwh=2.0,
    )
    fields.update(overrides)
    with pytest.raises(DispatchError, match=match):
        BatterySpec(**fields)


def test_an_unknown_override_is_refused_rather_than_ignored():
    with pytest.raises(DispatchError, match="unknown BatterySpec override"):
        BatterySpec.from_config(efficiency=0.9)


def test_duration_override_recomputes_capacity_for_the_c15_sensitivity():
    two_hour = BatterySpec.from_config()
    four_hour = BatterySpec.from_config(duration_hours=4.0)
    assert two_hour.energy_mwh == 2.0
    assert four_hour.energy_mwh == 4.0
    assert four_hour.power_mw == two_hour.power_mw


def test_an_opening_soc_outside_capacity_is_refused():
    spec = BatterySpec.from_config()
    with pytest.raises(DispatchError, match="outside"):
        dispatch(np.full(6, 50.0), spec, soc_start=spec.energy_mwh + 1.0,
                 reference=50.0)


def test_solve_day_requires_a_utc_index():
    spec = BatterySpec.from_config()
    naive = pd.Series(np.full(6, 50.0), index=pd.date_range("2024-01-01", periods=6,
                                                            freq="h"))
    with pytest.raises(DispatchError, match="tz-aware"):
        solve_day(naive, spec, 0.0, reference_price=50.0)


def test_market_day_blocks_requires_a_sorted_utc_index():
    series = flat_window(dt.date(2024, 5, 1), 3)
    with pytest.raises(RollingError, match="tz-aware"):
        market_day_blocks(series.index.tz_localize(None), BERLIN)
    with pytest.raises(RollingError, match="sorted"):
        market_day_blocks(series.index[::-1], BERLIN)
