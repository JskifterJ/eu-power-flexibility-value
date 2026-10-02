"""C6: commit-then-settle across curves, the two oracles, and the pooled ordering.

Offline only — every test builds its own price vector and its own forecast.
Nothing reads the cache, nothing reaches the network, nothing touches a sealed
year.

What these tests are actually defending, in order of how badly it would hurt:

1. **A forecast run must never report its own objective as value.** The LP solved
   on a forecast has an objective that is larger than the money, by exactly the
   amount the forecast was wrong. CLAUDE.md names this as the error to prevent,
   and the tests here check it structurally (the settled value differs from the
   objective, and ``prices_are_decision_prices`` is false) rather than by reading
   the code.
2. **The per-day oracle bound is exact, and it is the *same-start* oracle.**
   Random forecasts, adversarial forecasts, a perfect forecast and a constant
   forecast all have to sit at or below the oracle re-solved from their own
   opening SoC — and the test that a *rolled* oracle gives no such bound is here
   too, because that is the trap the bound is written to avoid.
3. **Curves are compared on a common day set**, so a curve with a forecast hole
   cannot have its 365-day total compared against a 366-day one.
4. **Capture is undefined, not 1 and not 0, where perfect foresight itself adds
   nothing.** A filled-in ratio there would quietly flatter or punish a model.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from dispatch.battery import (
    BatterySpec,
    DispatchError,
    assert_oracle_dominates,
    solve_day,
    value_schedule,
)
from dispatch.curves import (
    Curve,
    CurveError,
    assert_curve_aligns,
    assert_settlement_is_not_a_readback,
    capture_frame,
    capture_summary,
    check_decision_value_added_non_negative,
    check_per_day_dominance,
    common_days,
    pooled_comparison,
    report_realised_losses,
    same_start_oracle,
)
from dispatch.rolling import run_rolling_dispatch

BERLIN = "Europe/Berlin"


# ---------------------------------------------------------------------------
# helpers — a small, deterministic market
# ---------------------------------------------------------------------------


def realistic_spec(**overrides) -> BatterySpec:
    """The committed asset's shape, but constructed here so the test is self-contained."""
    fields = dict(
        power_mw=1.0,
        energy_mwh=2.0,
        round_trip_efficiency=0.88,
        throughput_cost_eur_per_mwh=2.0,
        initial_soc_fraction=0.5,
        terminal_mode="trailing_value",
    )
    fields.update(overrides)
    return BatterySpec(**fields)


def price_series(n_days: int = 30, start: str = "2024-02-01", seed: int = 0) -> pd.Series:
    """A diurnal price shape with noise, on a UTC hourly index, no DST inside it."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(
        f"{start} 00:00", periods=24 * n_days, freq="h", tz="UTC"
    )
    hour = index.hour.to_numpy()
    shape = 60 + 35 * np.sin((hour - 4) / 24 * 2 * np.pi) + 20 * np.sin(hour / 12 * np.pi)
    noise = rng.normal(0, 12, size=len(index))
    return pd.Series(shape + noise, index=index, name="price")


def forecast_of(realised: pd.Series, error_sd: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    return realised + rng.normal(0, error_sd, size=len(realised))


def roll(realised, spec, decision=None, curve="oracle", days=None, **kw):
    return run_rolling_dispatch(
        "DE-LU",
        realised,
        spec,
        decision_prices=decision,
        curve=curve,
        days=days,
        tz=BERLIN,
        **kw,
    )


@pytest.fixture(scope="module")
def market():
    """Realised prices, a decent forecast and the naive floor, over one month."""
    realised = price_series()
    model = forecast_of(realised, error_sd=14.0, seed=7)
    naive = realised.shift(24 * 7)
    return realised, model, naive


@pytest.fixture(scope="module")
def runs(market):
    realised, model, naive = market
    spec = realistic_spec()
    days = sorted(
        {d for d in pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date}
    )[8:]  # leave run-in for the naive lag and the trailing mark
    return {
        "spec": spec,
        "realised": realised,
        "oracle": roll(realised, spec, None, "oracle", days),
        "model": roll(realised, spec, model, "model", days),
        "naive": roll(realised, spec, naive, "naive", days),
    }


# ---------------------------------------------------------------------------
# 1. A forecast run never reports its own objective as value
# ---------------------------------------------------------------------------


def test_forecast_settlement_differs_from_the_lp_objective(market):
    """The gap between the two is exactly what commit-then-settle exists to keep."""
    realised, model, _ = market
    spec = realistic_spec()
    index = realised.index[48:72]
    schedule = solve_day(
        model.reindex(index), spec, soc_start_mwh=1.0, index=index, reference_price=60.0
    )
    settled = value_schedule(schedule, realised.reindex(index), spec)
    objective = schedule.objective_eur
    settled_equivalent = settled.cash_eur + settled.terminal_value_eur
    assert abs(objective - settled_equivalent) > 1.0, (
        "the forecast was wrong, so the LP's objective must exceed the money; if "
        "these agree the run is settling at its own decision prices"
    )
    assert objective > settled_equivalent
    assert settled.prices_are_decision_prices is False


def test_a_forecast_run_is_never_stamped_as_a_decision_price_readback(runs):
    for name in ("model", "naive"):
        report = assert_settlement_is_not_a_readback(runs[name])
        assert report["holds"], report["offenders"]
        assert report["worst_decision_vs_realised_gap_eur_per_mwh"] > 0
        assert all(
            value.prices_are_decision_prices is False
            for value in runs[name].valuations.values()
        )


def test_the_oracle_run_is_stamped_as_one_and_must_be(runs):
    report = assert_settlement_is_not_a_readback(runs["oracle"])
    assert report["holds"]
    assert report["worst_decision_vs_realised_gap_eur_per_mwh"] == 0.0
    assert report["n_days_decision_equals_realised"] == runs["oracle"].n_days


def test_a_curve_claiming_to_be_the_oracle_is_checked_against_the_data(market):
    realised, model, _ = market
    liar = Curve(name="oracle", prices=model, source="test", is_oracle=True)
    with pytest.raises(CurveError, match="declared an oracle curve"):
        assert_curve_aligns(liar, realised)
    honest = Curve(name="oracle", prices=realised, source="test", is_oracle=True)
    assert assert_curve_aligns(honest, realised)["on_realised_grid"]


# ---------------------------------------------------------------------------
# 2. Curve alignment — an off-grid forecast is a leak that looks like skill
# ---------------------------------------------------------------------------


def test_a_forecast_off_the_realised_grid_is_refused(market):
    realised, model, _ = market
    shifted = model.copy()
    shifted.index = shifted.index + pd.Timedelta(minutes=30)
    with pytest.raises(CurveError, match="absent from the realised series"):
        assert_curve_aligns(Curve("model", shifted, "test"), realised)


def test_a_shorter_curve_is_allowed(market):
    realised, model, _ = market
    report = assert_curve_aligns(Curve("model", model.iloc[100:200], "test"), realised)
    assert report["n_points"] == 100


@pytest.mark.parametrize(
    "mangle, match",
    [
        (lambda s: s.to_numpy(), "must be a Series"),
        (lambda s: s.tz_localize(None), "tz-aware"),
        (lambda s: pd.concat([s, s.iloc[:3]]), "duplicate|sorted"),
        (lambda s: s.iloc[::-1], "not sorted"),
    ],
)
def test_malformed_curves_are_refused(market, mangle, match):
    _, model, _ = market
    with pytest.raises(CurveError, match=match):
        Curve("model", mangle(model), "test")


# ---------------------------------------------------------------------------
# 3. The same-start oracle is the exact per-day bound
# ---------------------------------------------------------------------------


def test_same_start_oracle_opens_each_day_where_the_candidate_did(runs):
    bound = same_start_oracle(runs["model"], runs["spec"])
    assert set(bound) == set(runs["model"].days)
    for day, value in bound.items():
        assert value.soc_start_mwh == pytest.approx(
            runs["model"].schedules[day].soc_start_mwh, abs=1e-12
        )
        assert value.terminal_price_eur_per_mwh == pytest.approx(
            runs["model"].valuations[day].terminal_price_eur_per_mwh, abs=1e-12
        )


def test_same_start_oracle_refuses_a_different_asset(runs):
    with pytest.raises(CurveError, match="candidate's own battery spec"):
        same_start_oracle(runs["model"], realistic_spec(power_mw=5.0))


@pytest.mark.parametrize("curve", ["model", "naive"])
def test_per_day_dominance_holds_on_every_day(runs, curve):
    """CLAUDE.md's per-day invariant. Exact — the margin must not be positive."""
    report = check_per_day_dominance(runs[curve], same_start_oracle(runs[curve], runs["spec"]))
    assert report["holds"], report["failures"]
    assert report["n_days_checked"] == runs[curve].n_days
    assert report["worst_excess_eur"] <= 1e-9


@pytest.mark.parametrize("error_sd, seed", [(0.0, 1), (5.0, 2), (40.0, 3), (200.0, 4)])
def test_per_day_dominance_holds_for_any_forecast_however_bad(market, error_sd, seed):
    realised, _, _ = market
    spec = realistic_spec()
    days = sorted({d for d in pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date})[8:]
    run = roll(realised, spec, forecast_of(realised, error_sd, seed), "model", days)
    report = check_per_day_dominance(run, same_start_oracle(run, spec))
    assert report["holds"], report["failures"]


def test_a_perfect_forecast_reproduces_the_oracle_exactly(market):
    realised, _, _ = market
    spec = realistic_spec()
    days = sorted({d for d in pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date})[8:]
    perfect = roll(realised, spec, realised.copy(), "model", days)
    oracle = roll(realised, spec, None, "oracle", days)
    assert perfect.total_cash_eur == pytest.approx(oracle.total_cash_eur, abs=1e-6)
    frame = capture_frame(perfect, oracle, same_start_oracle(perfect, spec))
    assert capture_summary(frame)["pooled_capture_same_start"] == pytest.approx(1.0, abs=1e-9)
    # ...and it is still settled, not read back: a perfect forecast is a
    # legitimate case of decision == realised, but the run is not an oracle run.
    assert all(v.prices_are_decision_prices is False for v in perfect.valuations.values())


def test_a_fuller_opening_soc_beats_an_oracle_that_opened_emptier(market):
    """Why the per-day bound needs the *same-start* oracle. A controlled experiment.

    Across two independently rolled trajectories the opening SoCs diverge, and a
    candidate that happens to open a day with a fuller battery can out-earn a
    rolled oracle that opened it emptier. Demonstrated here deterministically
    rather than by hoping a random fixture exhibits it: same day, same prices,
    two opening states.

    Three things have to be true at once, and all three are the design:

    * the candidate (opening full, committed on a *wrong* forecast) out-earns the
      oracle that opened empty — so no bound exists between them;
    * ``assert_oracle_dominates`` **refuses** that comparison rather than
      reporting a breach, because the two are not the same problem;
    * the same-start oracle — opening full, like the candidate — dominates it.
    """
    realised, model, _ = market
    spec = realistic_spec(terminal_mode="none")  # no mark: the comparison is pure cash
    labels = pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date.to_numpy()

    def one_day(day, soc_start, decision):
        index = realised.index[labels == day]
        schedule = solve_day(
            decision.reindex(index), spec, soc_start_mwh=soc_start, index=index
        )
        return index, value_schedule(
            schedule,
            realised.reindex(index),
            spec,
            prices_are_decision_prices=decision is realised,
        )

    days = sorted(set(labels))
    beats = []
    for day in days:
        _, empty_oracle = one_day(day, 0.0, realised)
        _, full_forecast = one_day(day, spec.energy_mwh, model)
        if full_forecast.value_added_eur > empty_oracle.value_added_eur:
            beats.append(day)
    assert beats, (
        "on no day did a forecast run opening full out-earn perfect foresight "
        "opening empty — the fixture no longer demonstrates the trajectory "
        "effect the same-start oracle exists to handle"
    )

    day = beats[0]
    _, empty_oracle = one_day(day, 0.0, realised)
    index, full_forecast = one_day(day, spec.energy_mwh, model)
    assert full_forecast.value_added_eur > empty_oracle.value_added_eur
    with pytest.raises(DispatchError, match="common opening SoC"):
        assert_oracle_dominates(full_forecast, empty_oracle, label=str(day))

    _, bound = one_day(day, spec.energy_mwh, realised)
    assert_oracle_dominates(full_forecast, bound, label=str(day))
    assert full_forecast.value_added_eur <= bound.value_added_eur + 1e-9


def test_rolled_trajectories_do_diverge_in_opening_soc(market):
    """The premise of the two-oracle design, measured rather than asserted in prose.

    If the forecast run and the oracle run always opened each day in the same
    state, the rolled oracle *would* be a per-day bound and the same-start oracle
    would be redundant machinery. They do not.
    """
    realised = price_series(n_days=120, seed=2)
    spec = realistic_spec()
    days = sorted({d for d in pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date})[8:]
    oracle = roll(realised, spec, None, "oracle", days)
    model = roll(realised, spec, forecast_of(realised, 40.0, 102), "model", days)
    divergent = [
        day
        for day in model.days
        if abs(
            model.schedules[day].soc_start_mwh - oracle.schedules[day].soc_start_mwh
        )
        > 1e-9
    ]
    assert divergent, "the two rolled trajectories never diverged in opening SoC"
    # ...and the same-start bound holds on every one of those days.
    bound = same_start_oracle(model, spec)
    for day in divergent:
        assert (
            model.valuations[day].value_added_eur <= bound[day].value_added_eur + 1e-6
        )


def test_per_day_dominance_reports_a_breach_rather_than_hiding_it(runs):
    """Hand it a bogus 'oracle' and it must fail, not pass quietly."""
    bound = same_start_oracle(runs["model"], runs["spec"])
    sabotaged = dict(bound)
    day = runs["model"].days[5]
    schedule = runs["model"].schedules[day]
    idle = solve_day(
        pd.Series(np.zeros(len(schedule.index)), index=schedule.index),
        realistic_spec(terminal_mode="none"),
        soc_start_mwh=schedule.soc_start_mwh,
        index=schedule.index,
    )
    sabotaged[day] = value_schedule(
        idle, pd.Series(runs["model"].realised_prices[day], index=schedule.index),
        realistic_spec(terminal_mode="none"),
    )
    report = check_per_day_dominance(runs["model"], sabotaged)
    assert not report["holds"]
    assert report["n_failures"] >= 1


# ---------------------------------------------------------------------------
# 4. "Doing nothing is feasible" is a statement about the decision problem
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("curve", ["oracle", "model", "naive"])
def test_decision_value_added_is_never_negative(runs, curve):
    report = check_decision_value_added_non_negative(runs[curve], runs["spec"])
    assert report["holds"], report["offenders"]


def test_a_forecast_schedule_may_lose_money_at_realised_prices(market):
    """Not an invariant breach — the quantity this project exists to measure.

    A deliberately terrible forecast (the realised vector reversed within each
    day) must produce losing days, and they must be *reported* rather than
    tripping an assertion.
    """
    realised, _, _ = market
    spec = realistic_spec()
    days = sorted({d for d in pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date})[8:]
    inverted = pd.Series(
        -realised.to_numpy() + 2 * float(realised.mean()), index=realised.index
    )
    run = roll(realised, spec, inverted, "model", days)
    losses = report_realised_losses(run)
    assert losses["n_days_value_added_negative_at_realised"] > 0
    assert losses["total_eur"] < 0
    # The decision-problem theorem still holds, and so does the per-day bound.
    assert check_decision_value_added_non_negative(run, spec)["holds"]
    assert check_per_day_dominance(run, same_start_oracle(run, spec))["holds"]


def test_the_oracle_loses_money_on_no_day(runs):
    assert report_realised_losses(runs["oracle"])["n_days_value_added_negative_at_realised"] == 0


# ---------------------------------------------------------------------------
# 5. Curves are pooled over a common day set
# ---------------------------------------------------------------------------


def test_pooled_comparison_orders_the_three_curves(runs):
    pooled = pooled_comparison(
        {k: runs[k] for k in ("oracle", "model", "naive")}
    )
    assert pooled["holds"], pooled["checks"]
    assert pooled["checks"]["oracle_ge_model_pooled_cash"]["holds"]
    assert pooled["checks"]["model_ge_naive_pooled_cash"]["holds"]
    assert 0 < pooled["capture_ratio_rolled_cash"] <= 1.0


def test_a_curve_with_a_forecast_hole_shrinks_the_common_day_set(market):
    """The NOTE C4-02 mechanism: a hole skips a day, and pooling follows it.

    Without this, a 365-day model total would be compared against a 366-day
    oracle total and the model would look worse than it is for a reason that has
    nothing to do with forecasting.
    """
    realised, model, naive = market
    spec = realistic_spec()
    days = sorted({d for d in pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date})[8:]
    holed = model.copy()
    victim = days[10]
    hole_mask = pd.Series(holed.index).dt.tz_convert(BERLIN).dt.date.to_numpy() == victim
    holed.iloc[np.flatnonzero(hole_mask)[3]] = np.nan

    results = {
        "oracle": roll(realised, spec, None, "oracle", days),
        "model": roll(realised, spec, holed, "model", days),
        "naive": roll(realised, spec, naive, "naive", days),
    }
    assert victim not in results["model"].days
    assert [s.reason for s in results["model"].skipped if s.day == victim] == ["incomplete"]

    shared = common_days(results)
    assert victim not in shared
    assert len(shared) == len(results["oracle"].days) - 1

    pooled = pooled_comparison(results)
    assert pooled["n_common_days"] == len(shared)
    assert pooled["days_excluded_from_pool_per_curve"]["oracle"] == [victim.isoformat()]
    assert pooled["days_excluded_from_pool_per_curve"]["model"] == []
    # every pooled total is over the intersection, so the day counts agree
    assert {block["n_days"] for block in pooled["pooled"].values()} == {len(shared)}
    assert pooled["holds"], pooled["checks"]


def test_pooled_comparison_refuses_an_incomplete_or_disjoint_set(runs):
    with pytest.raises(CurveError, match="needs a 'naive' run"):
        pooled_comparison({"oracle": runs["oracle"], "model": runs["model"]})
    half = sorted(runs["oracle"].days)
    early = {d for d in half[:5]}
    late = {d for d in half[-5:]}
    spec = runs["spec"]
    realised = runs["realised"]
    disjoint = {
        "oracle": roll(realised, spec, None, "oracle", early),
        "model": roll(realised, spec, realised.copy(), "model", late),
        "naive": roll(realised, spec, realised.copy(), "naive", late),
    }
    with pytest.raises(CurveError, match="share no dispatched day"):
        pooled_comparison(disjoint)


def test_common_days_is_the_intersection(runs):
    shared = common_days({k: runs[k] for k in ("oracle", "model", "naive")})
    assert shared == sorted(
        set(runs["oracle"].days) & set(runs["model"].days) & set(runs["naive"].days)
    )


# ---------------------------------------------------------------------------
# 6. Capture ratios: bounded, and undefined where they have no meaning
# ---------------------------------------------------------------------------


def test_no_day_captures_more_than_all_of_the_attainable_value(runs):
    for curve in ("model", "naive"):
        frame = capture_frame(runs[curve], runs["oracle"], same_start_oracle(runs[curve], runs["spec"]))
        ratios = frame["capture_same_start"].to_numpy(dtype=float)
        defined = np.isfinite(ratios)
        assert (ratios[defined] <= 1 + 1e-9).all()
        assert capture_summary(frame)["n_days_capture_above_one"] == 0


def test_capture_is_undefined_not_filled_when_perfect_foresight_adds_nothing():
    """A flat day: the oracle itself adds zero, so a *share* of it has no meaning.

    Filling this with 0 would punish every model on every flat day and filling it
    with 1 would flatter them; NaN says what is true, and the summary counts it.
    """
    spec = realistic_spec()
    index = pd.date_range("2024-02-01 00:00", periods=24 * 12, freq="h", tz="UTC")
    flat = pd.Series(np.full(len(index), 50.0), index=index)
    days = sorted({d for d in pd.Series(index).dt.tz_convert(BERLIN).dt.date})[2:]
    oracle = roll(flat, spec, None, "oracle", days)
    model = roll(flat, spec, flat + 1.0, "model", days)
    frame = capture_frame(model, oracle, same_start_oracle(model, spec))
    assert frame["capture_same_start"].isna().all()
    summary = capture_summary(frame)
    assert summary["n_days_capture_defined"] == 0
    assert summary["n_days_capture_undefined"] == len(frame)
    assert summary["pooled_capture_same_start"] is None


def test_capture_summary_reports_the_distribution_not_just_the_mean(runs):
    frame = capture_frame(runs["model"], runs["oracle"], same_start_oracle(runs["model"], runs["spec"]))
    summary = capture_summary(frame)
    quantiles = summary["quantiles_daily_capture_same_start"]
    assert set(quantiles) == {"p01", "p05", "p25", "p50", "p75", "p95", "p99"}
    assert quantiles["p01"] <= quantiles["p50"] <= quantiles["p99"]
    assert summary["n_days"] == runs["model"].n_days


def test_the_oracle_captures_exactly_all_of_its_own_bound(runs):
    frame = capture_frame(runs["oracle"], runs["oracle"], same_start_oracle(runs["oracle"], runs["spec"]))
    ratios = frame["capture_same_start"].to_numpy(dtype=float)
    assert np.allclose(ratios[np.isfinite(ratios)], 1.0, atol=1e-9)
