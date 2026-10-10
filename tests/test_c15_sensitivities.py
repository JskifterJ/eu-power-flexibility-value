"""C15: the sensitivity ladder, and the one lever that needed new dispatch code.

Four groups of tests, in the order the risks matter.

**1. The ``soc_policy`` lever.** This is the only change C15 makes to a
pre-existing module, and the obvious way to write it invents energy. Most of
these tests exist to make that impossible: the unsafe spec combinations are
refused up front, the safe one is checked to conserve energy over a solved run,
and ``"carry"`` is pinned byte-for-byte against the same call without the
argument, so the committed default cannot have moved.

**2. The ladder itself.** Each rung must be exactly one declared departure from
``config/battery.yaml``, ``base`` must *be* the committed spec, and every rung's
store key must be recoverable — a ladder whose zero rung is not the published
battery measures its own re-implementation.

**3. The comparisons.** A ratio over one day set against a denominator over
another is not a ratio of anything, so the day-set alignment is asserted rather
than hoped for; the capture arithmetic and the friction decomposition are
checked against hand-computed numbers; the contrast builder is checked to
*refuse* a misaligned pairing rather than silently reindex it.

**4. The guards.** The 2025 holdout, the frozen GBM config, the store's schema,
and NOTE C14-01's Spearman invariance (which this file asserts *is* a tautology
of the design, because that is exactly what C15 reports it as).

Everything here is synthetic or reads only committed artefacts. No network, no
re-fitting, no 2025.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import numpy as np
import pandas as pd
import pytest

from backtest.results_store import METRIC_NAME, SCOPES, VINTAGES
from backtest.run_c11_dispatch import ALIGNED_FROM, FULL_HISTORY_FROM, GBM_FINGERPRINT
from backtest.run_c15_sensitivities import (
    BASE_RUNG,
    COMPARABLE_CURVE,
    DAILY_COLUMNS,
    LADDER,
    LADDER_YEARS,
    LEVER_CONTRASTS,
    MAIN_LEG,
    NAIVE_CURVE,
    ORACLE_CURVE,
    RES_CONTRASTS,
    RES_LEG,
    RES_YEARS,
    RUNGS_BY_NAME,
    SensitivityError,
    boundary_inventory_check,
    check_baseline_reproduction,
    check_reset_conserves_energy,
    curves_for,
    friction_decomposition,
    lever_contrast_rows,
    load_prediction_frame,
    main_curves,
    no2_ordering_table,
    point_row,
    point_table,
    res_curves,
    rungs_for,
    store_rows,
)
from backtest.run_c3_naive import RESULTS_DIR
from data.config import load_battery_config, load_zones
from data.holdout import SealedHoldoutError
from dispatch.battery import BatterySpec
from dispatch.rolling import (
    VALID_SOC_POLICIES,
    RollingError,
    run_rolling_dispatch,
)

BERLIN = "Europe/Berlin"
ZONES_A = ("DE-LU", "ES", "NO2")
SEALED_YEAR = 2025


# ---------------------------------------------------------------------------
# helpers — a small deterministic market, self-contained
# ---------------------------------------------------------------------------


def price_series(n_days: int = 20, start: str = "2024-03-04", seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.date_range(f"{start} 00:00", periods=24 * n_days, freq="h", tz="UTC")
    hour = index.hour.to_numpy()
    shape = 55 + 40 * np.sin((hour - 5) / 24 * 2 * np.pi)
    return pd.Series(shape + rng.normal(0, 14, len(index)), index=index, name="price")


def day_set(series: pd.Series, drop_edges: int = 2) -> list[dt.date]:
    days = sorted({d for d in pd.Series(series.index).dt.tz_convert(BERLIN).dt.date})
    return days[drop_edges:-1]


def roll(realised, spec, decision=None, curve="oracle", days=None, **kwargs):
    return run_rolling_dispatch(
        "DE-LU", realised, spec, decision_prices=decision, curve=curve, days=days,
        tz=BERLIN, **kwargs,
    )


def reset_spec(**overrides) -> BatterySpec:
    fields = dict(
        power_mw=1.0, energy_mwh=2.0, round_trip_efficiency=0.88,
        throughput_cost_eur_per_mwh=2.0, initial_soc_fraction=0.5,
        terminal_mode="floor", terminal_floor_fraction=0.5,
    )
    fields.update(overrides)
    return BatterySpec(**fields)


@pytest.fixture(scope="module")
def market():
    realised = price_series()
    rng = np.random.default_rng(23)
    forecast = realised + rng.normal(0, 10, len(realised))
    return realised, forecast, day_set(realised)


# ---------------------------------------------------------------------------
# 1. the soc_policy lever
# ---------------------------------------------------------------------------


def test_the_policy_list_is_exactly_carry_and_reset():
    assert VALID_SOC_POLICIES == ("carry", "reset")


def test_an_unknown_soc_policy_is_refused(market):
    realised, _, days = market
    with pytest.raises(RollingError, match="unknown soc_policy"):
        roll(realised, reset_spec(), days=days, soc_policy="midnight")


def test_carry_is_the_default_and_is_unchanged_by_naming_it(market):
    """The committed behaviour must be bit-identical with and without the lever."""
    realised, forecast, days = market
    spec = BatterySpec(
        power_mw=1.0, energy_mwh=2.0, round_trip_efficiency=0.88,
        throughput_cost_eur_per_mwh=2.0, initial_soc_fraction=0.5,
        terminal_mode="trailing_value",
    )
    implicit = roll(realised, spec, forecast, "f", days)
    explicit = roll(realised, spec, forecast, "f", days, soc_policy="carry")
    pd.testing.assert_frame_equal(implicit.daily_frame(), explicit.daily_frame())
    assert implicit.soc_policy == explicit.soc_policy == "carry"
    assert implicit.soc_reset_discarded_mwh == 0.0


@pytest.mark.parametrize("mode", ["trailing_value", "none"])
def test_reset_is_refused_unless_the_day_cannot_end_below_where_it_opened(market, mode):
    """Under either other terminal mode a reset would conjure or mis-mark energy."""
    realised, _, days = market
    spec = reset_spec(terminal_mode=mode, terminal_floor_fraction=0.0)
    with pytest.raises(RollingError, match="terminal_mode='floor'"):
        roll(realised, spec, days=days, soc_policy="reset")


def test_reset_is_refused_when_the_floor_sits_below_the_opening_soc(market):
    realised, _, days = market
    spec = reset_spec(terminal_floor_fraction=0.25, initial_soc_fraction=0.5)
    with pytest.raises(RollingError, match="free energy"):
        roll(realised, spec, days=days, soc_policy="reset")


def test_reset_opens_every_day_at_the_configured_soc(market):
    realised, forecast, days = market
    spec = reset_spec()
    result = roll(realised, spec, forecast, "f", days, soc_policy="reset")
    assert result.n_days == len(days)
    assert result.soc_policy == "reset"
    openings = np.array(list(result.soc_opening.values()), dtype=float)
    assert np.allclose(openings, spec.initial_soc_mwh, atol=1e-9)


def test_reset_only_ever_discards_energy_and_says_how_much(market):
    realised, forecast, days = market
    spec = reset_spec()
    result = roll(realised, spec, forecast, "f", days, soc_policy="reset")
    assert all(v >= 0.0 for v in result.soc_reset_discarded.values())
    assert result.soc_reset_discarded_mwh >= 0.0
    report = check_reset_conserves_energy(result, spec)
    assert report["holds"] is True
    assert report["n_days_energy_created"] == 0
    assert report["n_days_opening_soc_wrong"] == 0
    assert report["n_days_checked"] == len(days)


def test_the_conservation_check_does_not_apply_to_a_carrying_run(market):
    realised, forecast, days = market
    spec = reset_spec(terminal_mode="trailing_value", terminal_floor_fraction=0.0)
    result = roll(realised, spec, forecast, "f", days)
    assert check_reset_conserves_energy(result, spec)["applicable"] is False


def test_the_conservation_check_catches_a_run_that_opened_somewhere_else(market):
    """The guard is about the spec; this is about the 365 days actually solved."""
    realised, forecast, days = market
    spec = reset_spec()
    result = roll(realised, spec, forecast, "f", days, soc_policy="reset")
    result.soc_opening[days[3]] = spec.initial_soc_mwh + 0.4
    result.soc_reset_discarded[days[4]] = -0.2
    report = check_reset_conserves_energy(result, spec)
    assert report["holds"] is False
    assert report["n_days_opening_soc_wrong"] == 1
    assert report["n_days_energy_created"] == 1


def test_every_reset_day_hands_back_at_least_what_it_was_given(market):
    """The floor is what makes the reset a discard rather than a top-up."""
    realised, forecast, days = market
    spec = reset_spec()
    result = roll(realised, spec, forecast, "f", days, soc_policy="reset")
    for day in result.days:
        assert result.schedules[day].soc_end_mwh >= spec.terminal_floor_mwh - 1e-7


def test_the_reset_makes_the_days_genuinely_independent(market):
    """Changing yesterday's prices cannot change today's schedule under a reset.

    This is the property the leg is *for*. Under ``"carry"`` it is false by
    design, and the contrast between the two runs below is what the SoC
    sensitivity measures — so it is worth pinning rather than assuming.
    """
    realised, _, days = market
    spec = reset_spec()
    target = days[8]
    disturbed = realised.copy()
    labels = pd.Series(disturbed.index).dt.tz_convert(BERLIN).dt.date.to_numpy()
    # Perturb a day *after* the trailing reference window of `target` can see it.
    mask = labels == days[7]
    disturbed[mask] = disturbed[mask] * 3.0 - 40.0

    kept = roll(realised, spec, days=[days[7], target], soc_policy="reset")
    moved = roll(disturbed, spec, realised, "oracle_prices_kept",
                 [days[7], target], soc_policy="reset")
    np.testing.assert_allclose(
        kept.schedules[target].charge_mw, moved.schedules[target].charge_mw, atol=1e-7
    )
    np.testing.assert_allclose(
        kept.schedules[target].discharge_mw, moved.schedules[target].discharge_mw,
        atol=1e-7,
    )


# ---------------------------------------------------------------------------
# 2. the ladder
# ---------------------------------------------------------------------------


def test_the_ladder_has_exactly_one_baseline_and_covers_plan_mds_four_levers():
    bases = [r for r in LADDER if r.is_base]
    assert [r.name for r in bases] == [BASE_RUNG]
    levers = {r.lever for r in LADDER}
    assert levers == {"baseline", "throughput_cost", "duration", "soc_policy"}
    costs = {
        r.overrides.get("throughput_cost_eur_per_mwh")
        for r in LADDER if r.lever == "throughput_cost"
    }
    assert costs == {0.0, 5.0}, "PLAN.md's ladder is 0 / 2 / 5; 2 is the base rung"
    durations = {
        r.overrides.get("duration_hours") for r in LADDER if r.lever == "duration"
    }
    assert durations == {4.0}, "PLAN.md's duration sensitivity is 2h vs 4h"


def test_the_base_rung_is_exactly_the_committed_battery():
    """If this drifts, every delta in the cycle is measured from somewhere else."""
    cfg = load_battery_config()
    assert RUNGS_BY_NAME[BASE_RUNG].overrides == {}
    assert RUNGS_BY_NAME[BASE_RUNG].soc_policy == "carry"
    assert RUNGS_BY_NAME[BASE_RUNG].spec(cfg) == BatterySpec.from_config(cfg)


def test_the_committed_battery_is_still_the_one_c5_to_c14_dispatched():
    """A sensitivity ladder around a moved baseline is not a sensitivity ladder."""
    spec = BatterySpec.from_config(load_battery_config())
    assert spec.power_mw == 1.0
    assert spec.energy_mwh == 2.0
    assert spec.duration_hours == 2.0
    assert spec.round_trip_efficiency == 0.88
    assert spec.throughput_cost_eur_per_mwh == 2.0
    assert spec.initial_soc_fraction == 0.5
    assert spec.terminal_mode == "trailing_value"
    assert spec.forbid_simultaneous is False


@pytest.mark.parametrize("rung", [r for r in LADDER if not r.is_base], ids=lambda r: r.name)
def test_every_rung_is_exactly_one_declared_departure_from_base(rung):
    """One lever at a time: a rung that moved two knobs cannot be attributed."""
    cfg = load_battery_config()
    base = BatterySpec.from_config(cfg)
    other = rung.spec(cfg)
    moved = {
        field
        for field in base.as_dict()
        if base.as_dict()[field] != other.as_dict()[field]
    }
    # Derived fields move with the declared one and are not a second lever:
    # a 4h battery holds 4 MWh and opens half full at 2 MWh, and the throughput
    # cost is what defines the simultaneity threshold.
    allowed = {
        "throughput_cost": {"throughput_cost_eur_per_mwh",
                            "simultaneity_price_threshold_eur_per_mwh"},
        "duration": {"duration_hours", "energy_mwh", "initial_soc_mwh"},
        "soc_policy": {"terminal_mode", "terminal_floor_fraction",
                       "simultaneity_price_threshold_eur_per_mwh"},
    }[rung.lever]
    assert moved and moved <= allowed, f"{rung.name} moved {sorted(moved)}"


def test_only_the_daily_reset_rung_resets_the_soc():
    resetting = {r.name for r in LADDER if r.soc_policy == "reset"}
    assert resetting == {"soc_daily_reset"}


def test_the_reset_rung_is_the_combination_dispatch_rolling_will_accept():
    """The rung and the guard must agree, or the ladder dies mid-run."""
    cfg = load_battery_config()
    spec = RUNGS_BY_NAME["soc_daily_reset"].spec(cfg)
    assert spec.terminal_mode == "floor"
    assert spec.terminal_floor_mwh == pytest.approx(spec.initial_soc_mwh)


def test_rungs_for_always_includes_base_because_every_delta_is_against_it():
    assert [r.name for r in rungs_for(["throughput_5"])] == [BASE_RUNG, "throughput_5"]
    assert [r.name for r in rungs_for(None)] == [r.name for r in LADDER]
    with pytest.raises(SensitivityError, match="unknown rung"):
        rungs_for(["duration_8h"])


def test_every_lever_contrast_names_a_rung_that_exists_and_moves_one_lever():
    for rung, baseline, question in LEVER_CONTRASTS:
        assert rung in RUNGS_BY_NAME and baseline in RUNGS_BY_NAME
        assert baseline == BASE_RUNG
        assert question
    assert {r for r, _, _ in LEVER_CONTRASTS} == {
        r.name for r in LADDER if not r.is_base
    }, "every non-base rung must be contrasted, or it was computed for nothing"


# ---------------------------------------------------------------------------
# 3. the curves: committed artefacts, correct labels, no 2025
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", LADDER_YEARS)
def test_every_main_leg_artefact_this_cycle_needs_is_committed(year):
    zones = load_zones()
    for zone_key, zone in zones.items():
        for spec in main_curves(zone_key, zone.tier, year):
            assert (RESULTS_DIR / spec.artefact).exists(), spec.artefact


@pytest.mark.parametrize("year", RES_YEARS)
@pytest.mark.parametrize("zone", ZONES_A)
def test_every_res_leg_artefact_this_cycle_needs_is_committed(zone, year):
    for spec in res_curves(zone, year):
        assert (RESULTS_DIR / spec.artefact).exists(), spec.artefact


@pytest.mark.parametrize("year", LADDER_YEARS)
def test_the_main_leg_is_the_comparable_lear_and_the_naive_floor_only(year):
    zones = load_zones()
    for zone_key, zone in zones.items():
        specs = main_curves(zone_key, zone.tier, year)
        assert [s.curve for s in specs] == [COMPARABLE_CURVE, NAIVE_CURVE]
        assert all(s.train_from == FULL_HISTORY_FROM for s in specs)
        assert all(s.vintage == "honest" for s in specs)


@pytest.mark.parametrize("zone", ZONES_A)
def test_only_the_as_published_arms_are_labelled_after_gate_closure(zone):
    for year in RES_YEARS:
        for spec in res_curves(zone, year):
            late = "as_published" in spec.curve
            assert (spec.vintage == "after_gate_closure") is late, spec.curve
            assert spec.train_from == ALIGNED_FROM


@pytest.mark.parametrize("zone", ZONES_A)
def test_every_gbm_arm_carries_the_frozen_config_fingerprint(zone):
    """PLAN.md forbids a hyperparameter search; C15 must dispatch C9's own config."""
    for year in RES_YEARS:
        for spec in res_curves(zone, year):
            if spec.model == "gbm":
                assert spec.model_fingerprint == GBM_FINGERPRINT


def test_the_res_contrast_is_the_leak_direction_in_both_model_classes():
    assert len(RES_CONTRASTS) == 2
    for late, honest, _ in RES_CONTRASTS:
        assert "as_published" in late and "persistence" in honest
        assert late.split("_")[0] == honest.split("_")[0]


def test_the_sealed_year_has_no_artefact_mapping_at_all():
    """2025 must fail before a path is built, not as a missing-file message."""
    with pytest.raises(SensitivityError, match="no committed artefact"):
        main_curves("DE-LU", "A", SEALED_YEAR)


def test_an_unknown_leg_is_refused():
    with pytest.raises(SensitivityError, match="unknown leg"):
        curves_for("stretch", "DE-LU", "A", 2024)


def test_a_prediction_artefact_whose_y_true_moved_is_refused(tmp_path, monkeypatch):
    """An off-by-one index is a leak that looks like skill."""
    import backtest.run_c15_sensitivities as mod

    index = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    realised = pd.Series(np.linspace(10, 60, 48), index=index)
    frame = pd.DataFrame({
        "timestamp_utc": index.astype(str),
        "market_day": [d.date().isoformat() for d in index],
        "y_true": realised.to_numpy(),
        "y_pred_x": realised.to_numpy() + 1.0,
    })
    good = tmp_path / "good.csv.gz"
    frame.to_csv(good, index=False)
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    assert load_prediction_frame("DE-LU", 2024, "good.csv.gz", ["y_pred_x"], realised) is not None

    bad = frame.copy()
    bad.loc[5, "y_true"] = bad.loc[5, "y_true"] + 0.5
    bad.to_csv(tmp_path / "bad.csv.gz", index=False)
    with pytest.raises(SensitivityError, match="y_true differs"):
        load_prediction_frame("DE-LU", 2024, "bad.csv.gz", ["y_pred_x"], realised)

    with pytest.raises(SensitivityError, match="is missing"):
        load_prediction_frame("DE-LU", 2024, "absent.csv.gz", ["y_pred_x"], realised)


def test_a_missing_forecast_column_is_refused_rather_than_filled(tmp_path, monkeypatch):
    import backtest.run_c15_sensitivities as mod

    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")
    realised = pd.Series(np.linspace(10, 40, 24), index=index)
    pd.DataFrame({
        "timestamp_utc": index.astype(str),
        "market_day": [d.date().isoformat() for d in index],
        "y_true": realised.to_numpy(),
    }).to_csv(tmp_path / "thin.csv.gz", index=False)
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    with pytest.raises(SensitivityError, match="no 'y_pred_missing' column"):
        load_prediction_frame("DE-LU", 2024, "thin.csv.gz", ["y_pred_missing"], realised)


# ---------------------------------------------------------------------------
# 4. the comparisons: day sets, arithmetic, and refusals
# ---------------------------------------------------------------------------


def synthetic_ladder(
    rungs=("base", "throughput_0"),
    curves=(ORACLE_CURVE, COMPARABLE_CURVE, NAIVE_CURVE),
    n_days: int = 8,
    zone: str = "DE-LU",
    year: int = 2024,
    leg: str = MAIN_LEG,
) -> pd.DataFrame:
    """A per-day ladder frame in the real column shape, with known sums."""
    days = [f"{year}-04-{d:02d}" for d in range(1, n_days + 1)]
    rows = []
    for rung in rungs:
        bump = 1.0 if rung == BASE_RUNG else 1.1
        for j, curve in enumerate(curves):
            share = {ORACLE_CURVE: 1.0, COMPARABLE_CURVE: 0.9, NAIVE_CURVE: 0.8}.get(
                curve, 0.85 - 0.01 * j
            )
            for i, day in enumerate(days):
                oracle_cash = 100.0 * bump * (1 + 0.01 * i)
                rows.append({
                    "leg": leg, "rung": rung,
                    "lever": RUNGS_BY_NAME[rung].lever,
                    "soc_policy": RUNGS_BY_NAME[rung].soc_policy,
                    "zone": zone, "year": year, "curve": curve, "market_day": day,
                    "n_dispatch_hours": 24, "cash": oracle_cash * share,
                    "oracle_cash": oracle_cash,
                    "lost": oracle_cash * (1 - share),
                    "value_added": oracle_cash * share,
                    "same_start_oracle_value_added": oracle_cash,
                    "terminal_value": 0.0, "opening_value": 0.0,
                    "charged_mwh": 2.0, "discharged_mwh": 1.8,
                    "throughput_cost_eur": 3.6,
                    "soc_start_mwh": 1.0, "soc_end_mwh": 1.0,
                    "soc_reset_discarded_mwh": 0.0,
                    "n_simultaneous_intervals": 0,
                    "simultaneity_energy_burned_mwh": 0.0,
                    "realised_spread": 40.0, "realised_price_min": 5.0,
                    "realised_price_max": 45.0, "reference_price": 30.0,
                    "in_ladder_common_day_set": True,
                    "n_hours": 24.0 if curve != ORACLE_CURVE else np.nan,
                    "sum_abs_error": 240.0 if curve != ORACLE_CURVE else np.nan,
                    "sum_sq_error": 2400.0 if curve != ORACLE_CURVE else np.nan,
                    "sum_error": 24.0 if curve != ORACLE_CURVE else np.nan,
                    "forecast_spread": 35.0 if curve != ORACLE_CURVE else np.nan,
                    "spread_error": -5.0 if curve != ORACLE_CURVE else np.nan,
                    "abs_spread_error": 5.0 if curve != ORACLE_CURVE else np.nan,
                    "spearman": 0.8 if curve != ORACLE_CURVE else np.nan,
                    "spearman_contrib": 0.8 if curve != ORACLE_CURVE else np.nan,
                    "spearman_defined": 1.0 if curve != ORACLE_CURVE else np.nan,
                    "model": (
                        "oracle" if curve == ORACLE_CURVE
                        else "naive_last_week" if curve == NAIVE_CURVE
                        else curve.split("_")[0]
                    ),
                    "exog_variant": (
                        "perfect_foresight" if curve == ORACLE_CURVE
                        else "" if curve == NAIVE_CURVE
                        else "price_only" if curve == COMPARABLE_CURVE
                        else curve.split("_", 1)[1]
                    ),
                    "vintage": (
                        "after_gate_closure" if "as_published" in curve else "honest"
                    ),
                    "train_from": "" if curve == ORACLE_CURVE else FULL_HISTORY_FROM,
                    "tier": "A", "regime": "thermal-RES-mixed",
                })
    return pd.DataFrame(rows)[list(DAILY_COLUMNS)]


def test_the_synthetic_frame_matches_the_real_artefact_shape():
    """A fixture that drifts from the artefact tests nothing about the artefact."""
    frame = synthetic_ladder()
    assert list(frame.columns) == list(DAILY_COLUMNS)


def test_the_capture_ratio_is_a_ratio_of_day_sums_not_a_mean_of_ratios():
    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    cfg = load_battery_config()
    points = point_table(frame, cfg)
    row = points[(points["rung"] == BASE_RUNG)
                 & (points["curve"] == COMPARABLE_CURVE)].iloc[0]
    oracle = frame[(frame["rung"] == BASE_RUNG) & (frame["curve"] == ORACLE_CURVE)]
    mine = frame[(frame["rung"] == BASE_RUNG) & (frame["curve"] == COMPARABLE_CURVE)]
    assert row["capture"] == pytest.approx(mine["cash"].sum() / oracle["cash"].sum())
    assert row["capture"] == pytest.approx(0.9)
    assert row["mae"] == pytest.approx(240.0 / 24.0)
    assert row["error_over_headroom"] == pytest.approx(10.0 / 40.0)
    assert row["mean_spearman"] == pytest.approx(0.8)
    assert row["equivalent_full_cycles"] == pytest.approx(
        mine["discharged_mwh"].sum() / 2.0
    )


def test_the_point_table_refuses_a_curve_the_oracle_does_not_cover():
    """A ratio over one day set against a denominator over another is not a ratio."""
    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    trimmed = frame[~(
        (frame["curve"] == ORACLE_CURVE) & (frame["market_day"] == "2024-04-03")
    )]
    with pytest.raises(SensitivityError, match="same ladder-common days"):
        point_table(trimmed, load_battery_config())


def test_the_point_table_refuses_a_rung_with_no_oracle_rows():
    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    with pytest.raises(SensitivityError, match="no oracle rows"):
        point_table(frame[frame["curve"] != ORACLE_CURVE], load_battery_config())


def test_point_row_scales_cash_to_a_year_by_the_span_it_actually_covers():
    frame = synthetic_ladder(rungs=(BASE_RUNG,), n_days=8)
    oracle = frame[frame["curve"] == ORACLE_CURVE].sort_values("market_day")
    cell = frame[frame["curve"] == COMPARABLE_CURVE].sort_values("market_day")
    row = point_row(cell.reset_index(drop=True), oracle.reset_index(drop=True))
    assert row["n_days"] == 8
    assert row["cash_eur_per_mw_year"] == pytest.approx(
        cell["cash"].sum() * 365.25 / 8
    )


def test_a_lever_contrast_is_paired_on_the_same_days_and_refuses_otherwise():
    frame = synthetic_ladder()
    contrasts = lever_contrast_rows(
        frame, (("throughput_0", BASE_RUNG, "q"),), n_replicates=200, blocks=(1,)
    )
    assert set(contrasts["curve"]) == {COMPARABLE_CURVE, NAIVE_CURVE}
    assert ORACLE_CURVE not in set(contrasts["curve"])
    # Both rungs' captures are 0.9 by construction, so the delta is exactly zero.
    assert contrasts["delta_capture_pp"].abs().max() == pytest.approx(0.0, abs=1e-9)
    # ... while the cash moved, because the oracle's prize moved with it.
    assert (contrasts["delta_eur_per_mw_year"] > 0).all()

    misaligned = frame[~(
        (frame["rung"] == "throughput_0") & (frame["market_day"] == "2024-04-05")
    )]
    with pytest.raises(SensitivityError, match="same ladder-common days"):
        lever_contrast_rows(
            misaligned, (("throughput_0", BASE_RUNG, "q"),), n_replicates=200,
            blocks=(1,),
        )


def test_a_contrast_whose_rung_was_not_dispatched_is_skipped_not_invented():
    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    contrasts = lever_contrast_rows(
        frame, (("throughput_0", BASE_RUNG, "q"),), n_replicates=200, blocks=(1,)
    )
    assert contrasts.empty


def test_only_days_in_the_ladder_common_set_are_pooled():
    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    frame.loc[frame["market_day"] == "2024-04-08", "in_ladder_common_day_set"] = False
    points = point_table(frame, load_battery_config())
    assert set(points["n_days"]) == {7}


def test_the_friction_decomposition_is_the_share_of_the_shortfall():
    """Hand-computed: a 0.80 base capture that becomes 0.85 at zero friction."""
    frame = synthetic_ladder(rungs=(BASE_RUNG, "throughput_0"))
    frame.loc[
        (frame["rung"] == BASE_RUNG) & (frame["curve"] == COMPARABLE_CURVE), "cash"
    ] = 80.0
    frame.loc[
        (frame["rung"] == BASE_RUNG) & (frame["curve"] == ORACLE_CURVE), "cash"
    ] = 100.0
    frame.loc[
        (frame["rung"] == "throughput_0") & (frame["curve"] == COMPARABLE_CURVE), "cash"
    ] = 85.0
    frame.loc[
        (frame["rung"] == "throughput_0") & (frame["curve"] == ORACLE_CURVE), "cash"
    ] = 100.0
    points = point_table(frame, load_battery_config())
    friction = friction_decomposition(points)
    row = friction[friction["curve"] == COMPARABLE_CURVE].iloc[0]
    assert row["capture_base"] == pytest.approx(0.80)
    assert row["capture_throughput_0"] == pytest.approx(0.85)
    assert row["shortfall_base_pp"] == pytest.approx(20.0)
    assert row["friction_pp"] == pytest.approx(5.0)
    assert row["friction_share_of_shortfall"] == pytest.approx(0.25)
    assert row["residual_shortfall_at_zero_friction_pp"] == pytest.approx(15.0)


def test_a_thin_regime_cell_is_marked_rather_than_dropped():
    """FLAG C13-01's NO2 2020: a shortfall share over a near-zero prize is not one."""
    frame = synthetic_ladder(rungs=(BASE_RUNG, "throughput_0"), zone="NO2")
    frame["cash"] = frame["cash"] / 1000.0
    frame["oracle_cash"] = frame["oracle_cash"] / 1000.0
    points = point_table(frame, load_battery_config())
    friction = friction_decomposition(points)
    assert friction["thin_regime"].all()
    assert len(friction) == 2  # the comparable LEAR and the naive floor


def test_the_boundary_check_bounds_the_inventory_a_rung_still_owns():
    frame = synthetic_ladder(rungs=(BASE_RUNG, "soc_no_terminal"))
    last = frame["market_day"] == frame["market_day"].max()
    frame.loc[last & (frame["rung"] == "soc_no_terminal"), "soc_end_mwh"] = 0.0
    boundary = boundary_inventory_check(frame, load_battery_config())
    row = boundary[(boundary["curve"] == COMPARABLE_CURVE)
                   & (boundary["rung"] == "soc_no_terminal")].iloc[0]
    # base ends where it started (net 0); the other ends 1 MWh lighter.
    assert row["base_net_stored_mwh"] == pytest.approx(0.0)
    assert row["rung_net_stored_mwh"] == pytest.approx(-1.0)
    assert row["inventory_gap_mwh"] == pytest.approx(1.0)
    assert row["boundary_inventory_bound_eur"] == pytest.approx(1.0 * 45.0)
    assert row["delta_over_bound"] == pytest.approx(
        abs(row["cash_delta_eur"]) / 45.0
    )
    # The last-day bound is the tighter, natural one and is reported beside it.
    assert row["boundary_inventory_bound_last_day_eur"] == pytest.approx(
        1.0 * row["last_day_max_price_eur_per_mwh"]
    )
    assert (
        row["boundary_inventory_bound_last_day_eur"]
        <= row["boundary_inventory_bound_eur"] + 1e-9
    )


def test_a_rung_that_ends_where_base_ends_has_no_boundary_term_at_all():
    frame = synthetic_ladder(rungs=(BASE_RUNG, "throughput_0"))
    boundary = boundary_inventory_check(frame, load_battery_config())
    assert (boundary["inventory_gap_mwh"] == 0.0).all()
    assert np.isinf(boundary["delta_over_bound"]).all()
    assert boundary["survives_boundary_objection"].all()


def test_the_no2_table_marks_and_excludes_its_own_thin_year():
    """A mean gap that includes NO2 2020 is reporting that one cell."""
    points = no2_points()
    thin = (points["zone"] == "NO2") & (points["year"] == 2024)
    points.loc[thin, "oracle_cash_eur_per_mw_year"] = 700.0
    report = no2_ordering_table(points)
    assert report["table"]["no2_is_thin_regime"].all()
    note = report["note_c14_01"]
    assert note["thin_regime_years_excluded_from_the_means"] == [2024]
    # Every year is thin, so there is nothing left to average.
    assert note["mean_capture_gap_pp_at_base"] is None
    assert note["mean_capture_gap_pp_at_base_including_thin_years"] is not None


# ---------------------------------------------------------------------------
# 5. NOTE C14-01: the Spearman invariance is a tautology, and is reported as one
# ---------------------------------------------------------------------------


def no2_points(spearman_by_rung: dict[str, float] | None = None) -> pd.DataFrame:
    """A points table with NO2 and two other zones, one year, every rung."""
    rows = []
    rungs = [r.name for r in LADDER]
    for zone, capture, spearman in (
        ("NO2", 0.61, 0.58), ("DE-LU", 0.92, 0.86), ("ES", 0.88, 0.82),
    ):
        for rung in rungs:
            value = capture + (0.005 if rung == "throughput_0" else 0.0)
            drift = (spearman_by_rung or {}).get(rung, 0.0) if zone == "NO2" else 0.0
            rows.append({
                "leg": MAIN_LEG, "zone": zone, "year": 2024, "rung": rung,
                "lever": RUNGS_BY_NAME[rung].lever, "curve": COMPARABLE_CURVE,
                "tier": "A", "regime": "r", "model": "lear",
                "exog_variant": "price_only", "vintage": "honest",
                "train_from": FULL_HISTORY_FROM, "capacity_mwh": 2.0,
                "n_days": 365, "first_day": "2024-01-01", "last_day": "2024-12-31",
                "capture": value, "mean_spearman": spearman + drift,
                "oracle_cash_eur_per_mw_year": 50_000.0,
                "cash_eur_per_mw_year": 45_000.0, "eur_per_mw_year_lost": 5_000.0,
                "equivalent_full_cycles": 300.0, "mean_realised_spread": 50.0,
                "mae": 12.0, "error_over_headroom": 0.24,
                "n_days_spearman_defined": 365, "mean_abs_spread_error": 9.0,
                "n_days_cash_negative": 3, "n_days_with_simultaneity": 0,
                "simultaneity_energy_burned_mwh": 0.0, "soc_reset_discarded_mwh": 0.0,
                "cash_eur": 45_000.0, "oracle_cash_eur": 50_000.0,
                "discharged_mwh": 600.0,
            })
    return pd.DataFrame(rows)


def test_no2s_within_day_spearman_is_identical_at_every_rung():
    """The substance of C15's answer to NOTE C14-01: the prediction cannot fail."""
    report = no2_ordering_table(no2_points())
    assert report["spearman_is_rung_invariant"]["holds"] is True
    assert report["spearman_is_rung_invariant"]["worst_drift"] == pytest.approx(0.0)
    table = report["table"]
    assert table["no2_mean_spearman"].nunique() == 1
    assert set(table["rung"]) == {r.name for r in LADDER}


def test_a_spearman_that_moved_across_rungs_is_reported_as_a_failure():
    """A non-zero drift means two rungs were pooled over different day sets."""
    report = no2_ordering_table(no2_points({"throughput_0": 0.05}))
    assert report["spearman_is_rung_invariant"]["holds"] is False
    assert report["spearman_is_rung_invariant"]["worst_drift"] == pytest.approx(0.05)


def test_the_substantive_form_of_note_c14_01_is_the_one_reported():
    report = no2_ordering_table(no2_points())
    note = report["note_c14_01"]
    assert note["verdict"] == "untestable by this ladder, and asserted instead"
    assert "removing the friction" in note["substantive_form_tested"]
    # Every zone gains the same 0.5pp at zero friction, so the gap does not close.
    assert note["gap_closed_pp"] == pytest.approx(0.0, abs=1e-9)
    assert note["n_years_no2_last_on_capture_at_zero_friction"] == 1


def test_a_run_without_no2_says_so_instead_of_inventing_a_row():
    points = no2_points()
    report = no2_ordering_table(points[points["zone"] != "NO2"])
    assert report["note_c14_01"]["applicable"] is False
    assert report["table"].empty


def test_a_run_with_no_comparable_curve_cannot_answer_note_c14_01():
    points = no2_points()
    with pytest.raises(SensitivityError, match="cannot answer NOTE C14-01"):
        no2_ordering_table(points[points["curve"] != COMPARABLE_CURVE])


# ---------------------------------------------------------------------------
# 6. the store: long format, the rung in the metric name, no schema change
# ---------------------------------------------------------------------------


def test_every_store_row_is_a_legal_row_and_the_rung_is_in_the_metric_name():
    frame = synthetic_ladder(rungs=(BASE_RUNG, "throughput_0"))
    points = point_table(frame, load_battery_config())
    contrasts = lever_contrast_rows(
        frame, (("throughput_0", BASE_RUNG, "q"),), n_replicates=200, blocks=(1,)
    )
    rows = store_rows(points, contrasts)
    assert rows
    for row in rows:
        assert METRIC_NAME.match(row.metric), row.metric
        assert row.scope in SCOPES
        assert row.vintage in VINTAGES
        assert row.evaluation_years == "2024"
        assert np.isfinite(float(row.value))
        assert row.source_cycle == "C15"
    metrics = {row.metric for row in rows}
    assert any(m.startswith("c15_base_") for m in metrics)
    assert any(m.startswith("c15_throughput_0_") for m in metrics)
    assert any(m.startswith("c15_d_throughput_0_") for m in metrics)


def test_no_store_row_is_written_for_the_oracle_curve():
    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    points = point_table(frame, load_battery_config())
    rows = store_rows(points, pd.DataFrame(columns=["block_days"]))
    assert all(row.model != "oracle" for row in rows)


def test_two_store_rows_never_share_a_key_within_one_run():
    frame = synthetic_ladder(rungs=(BASE_RUNG, "throughput_0", "duration_4h"))
    points = point_table(frame, load_battery_config())
    contrasts = lever_contrast_rows(
        frame,
        (("throughput_0", BASE_RUNG, "q"), ("duration_4h", BASE_RUNG, "q")),
        n_replicates=200, blocks=(1,),
    )
    rows = store_rows(points, contrasts)
    keys = [row.key() for row in rows]
    assert len(keys) == len(set(keys))


def test_every_rung_name_fits_inside_the_stores_metric_name_limit():
    """A rung whose name overflows the regex would be silently unwritable."""
    for rung in LADDER:
        for _, stem in (("capture", "capture"), ("x", "within_day_spearman")):
            assert METRIC_NAME.match(f"c15_{rung.name}_{stem}")
            assert METRIC_NAME.match(f"c15_d_{rung.name}_{stem}_ci_low")


# ---------------------------------------------------------------------------
# 7. the baseline reproduction and the sealed holdout
# ---------------------------------------------------------------------------


def test_the_reproduction_check_catches_a_base_rung_that_drifted(tmp_path, monkeypatch):
    import backtest.run_c15_sensitivities as mod

    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    reference = frame.rename(columns={})[
        ["zone", "year", "curve", "market_day", "cash", "oracle_cash"]
    ]
    reference.to_csv(tmp_path / "c13_daily_by_year.csv.gz", index=False)
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    assert check_baseline_reproduction(frame)["holds"] is True

    drifted = frame.copy()
    drifted.loc[2, "cash"] = drifted.loc[2, "cash"] + 0.01
    report = check_baseline_reproduction(drifted)
    assert report["holds"] is False
    assert report["worst_abs_cash_gap_eur"] == pytest.approx(0.01)


def test_the_reproduction_check_refuses_to_pass_on_an_empty_join(tmp_path, monkeypatch):
    import backtest.run_c15_sensitivities as mod

    frame = synthetic_ladder(rungs=(BASE_RUNG,))
    other = synthetic_ladder(rungs=(BASE_RUNG,), zone="PL")[
        ["zone", "year", "curve", "market_day", "cash", "oracle_cash"]
    ]
    other.to_csv(tmp_path / "c13_daily_by_year.csv.gz", index=False)
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    with pytest.raises(SensitivityError, match="share no"):
        check_baseline_reproduction(frame)


def test_the_ladder_years_stop_before_the_sealed_holdout():
    assert SEALED_YEAR not in LADDER_YEARS
    assert SEALED_YEAR not in RES_YEARS
    assert max(LADDER_YEARS) == 2024


def test_dispatching_the_sealed_year_raises_before_any_path_is_built():
    import backtest.run_c15_sensitivities as mod

    with pytest.raises((SealedHoldoutError, SensitivityError)):
        mod.dispatch_cell(MAIN_LEG, "DE-LU", SEALED_YEAR, list(LADDER),
                          load_battery_config())


def test_no_committed_c15_artefact_carries_a_2025_datum():
    """C14's three-bucket sweep, applied to this cycle's own files."""
    bare_year = re.compile(r"(?<![\d.])2025(?![\d.])")
    offenders: list[str] = []
    for path in sorted(RESULTS_DIR.glob("c15_*")):
        if path.suffix == ".gz":
            frame = pd.read_csv(path, dtype={"market_day": str}, nrows=5000)
            if "year" in frame.columns:
                assert SEALED_YEAR not in set(frame["year"]), path.name
            if "market_day" in frame.columns:
                assert not frame["market_day"].astype(str).str.startswith("2025").any()
            continue
        text = path.read_text()
        for match in bare_year.finditer(text):
            line = text[max(0, match.start() - 90):match.end() + 90]
            offenders.append(f"{path.name}: ...{line}...")
    assert not offenders, offenders


# ---------------------------------------------------------------------------
# 8. CLAUDE.md's LP invariants, end to end, at every rung
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ladder_runs(market):
    """Every rung solved on the same synthetic market: oracle, forecast, naive."""
    from dispatch.curves import same_start_oracle

    realised, forecast, days = market
    rng = np.random.default_rng(91)
    naive = realised.shift(24 * 7).fillna(realised.mean()) + rng.normal(
        0, 2, len(realised)
    )
    cfg = load_battery_config()
    out = {}
    for rung in LADDER:
        spec = rung.spec(cfg)
        runs = {
            ORACLE_CURVE: roll(realised, spec, None, ORACLE_CURVE, days,
                               soc_policy=rung.soc_policy),
            "forecast": roll(realised, spec, forecast, "forecast", days,
                             soc_policy=rung.soc_policy),
            NAIVE_CURVE: roll(realised, spec, naive, NAIVE_CURVE, days,
                              soc_policy=rung.soc_policy),
        }
        out[rung.name] = {
            "spec": spec, "runs": runs,
            "bounds": {n: same_start_oracle(r, spec) for n, r in runs.items()},
        }
    return out


@pytest.mark.parametrize("rung", [r.name for r in LADDER])
def test_the_same_start_oracle_bound_holds_every_day_at_every_rung(ladder_runs, rung):
    """CLAUDE.md's per-day invariant: forecast <= oracle, re-solved same-start."""
    from dispatch.curves import check_per_day_dominance

    block = ladder_runs[rung]
    for name in ("forecast", NAIVE_CURVE):
        report = check_per_day_dominance(block["runs"][name], block["bounds"][name])
        assert report["holds"] is True, (rung, name, report)
        assert report["n_days_checked"] > 0


@pytest.mark.parametrize("rung", [r.name for r in LADDER])
def test_the_forecast_beats_the_naive_floor_pooled_at_every_rung(ladder_runs, rung):
    """CLAUDE.md's pooled half. Per-day violations are expected and not checked."""
    from backtest.run_c11_dispatch import beats_naive
    from dispatch.curves import common_days

    block = ladder_runs[rung]
    shared = common_days(block["runs"])
    report = beats_naive(block["runs"]["forecast"], block["runs"][NAIVE_CURVE], shared)
    assert report["holds"] is True, (rung, report)
    assert 0.0 < report["per_day_beats_naive_share"] <= 1.0


@pytest.mark.parametrize("rung", [r.name for r in LADDER])
def test_no_run_settles_a_forecast_at_its_own_decision_prices(ladder_runs, rung):
    """Commit-then-settle: only the oracle may declare its prices realised."""
    from dispatch.curves import assert_settlement_is_not_a_readback

    for name, run in ladder_runs[rung]["runs"].items():
        report = assert_settlement_is_not_a_readback(run)
        assert report["holds"] is True, (rung, name, report)


@pytest.mark.parametrize("rung", [r.name for r in LADDER])
def test_doing_nothing_is_always_feasible_at_every_rung(ladder_runs, rung):
    """No day may add negative value *under the objective the LP solved*."""
    from dispatch.curves import check_decision_value_added_non_negative

    block = ladder_runs[rung]
    for name, run in block["runs"].items():
        report = check_decision_value_added_non_negative(run, block["spec"])
        assert report["holds"] is True, (rung, name, report)


def test_the_oracles_value_is_non_increasing_in_the_throughput_cost(ladder_runs):
    """A higher cost of trading cannot make perfect foresight worth more."""
    k0 = ladder_runs["throughput_0"]["runs"][ORACLE_CURVE]
    k2 = ladder_runs[BASE_RUNG]["runs"][ORACLE_CURVE]
    k5 = ladder_runs["throughput_5"]["runs"][ORACLE_CURVE]
    assert k0.total_value_added_eur >= k2.total_value_added_eur - 1e-6
    assert k2.total_value_added_eur >= k5.total_value_added_eur - 1e-6


def test_the_oracles_value_is_non_decreasing_in_duration(ladder_runs):
    """A 4h battery contains a 2h one, so it cannot earn less."""
    two = ladder_runs[BASE_RUNG]["runs"][ORACLE_CURVE]
    four = ladder_runs["duration_4h"]["runs"][ORACLE_CURVE]
    assert four.total_cash_eur >= two.total_cash_eur - 1e-6


def test_a_higher_throughput_cost_cycles_the_battery_less(ladder_runs):
    k0 = ladder_runs["throughput_0"]["runs"][ORACLE_CURVE]
    k5 = ladder_runs["throughput_5"]["runs"][ORACLE_CURVE]
    assert k0.total_discharged_mwh >= k5.total_discharged_mwh - 1e-6


@pytest.mark.parametrize("rung", [r.name for r in LADDER])
def test_every_rung_dispatches_the_local_calendars_day_lengths(ladder_runs, rung):
    """The DST whitelist assertion CLAUDE.md requires, applied to dispatch."""
    from backtest.run_c5_oracle_lp import check_day_lengths

    for name, run in ladder_runs[rung]["runs"].items():
        report = check_day_lengths(run, "DE-LU")
        assert report["holds"] is True, (rung, name, report)


def test_only_the_reset_rung_reports_discarded_energy(ladder_runs):
    for rung in LADDER:
        total = sum(
            r.soc_reset_discarded_mwh for r in ladder_runs[rung.name]["runs"].values()
        )
        if rung.name == "soc_daily_reset":
            assert total >= 0.0
        else:
            assert total == 0.0


# ---------------------------------------------------------------------------
# 9. NOTE C13-02's named stress cell
# ---------------------------------------------------------------------------


def test_the_stress_cell_is_the_one_note_c13_02_names():
    from backtest.run_c15_sensitivities import STRESS_CELL

    assert STRESS_CELL == ("NO2", 2020)


def test_the_stress_cell_report_marks_a_thin_prize_as_thin():
    from backtest.run_c15_sensitivities import stress_cell_report

    frame = synthetic_ladder(
        rungs=(BASE_RUNG, "throughput_0"), zone="NO2", year=2020
    )
    frame["cash"] = frame["cash"] / 1000.0
    frame["oracle_cash"] = frame["oracle_cash"] / 1000.0
    points = point_table(frame, load_battery_config())
    report = stress_cell_report(points)
    assert report["applicable"] is True
    assert report["is_below_the_thin_regime_floor"] is True
    assert report["best_rung_for_the_comparable_arm"] in {BASE_RUNG, "throughput_0"}
    assert {row["curve"] for row in report["rows"]} == {
        COMPARABLE_CURVE, NAIVE_CURVE
    }


def test_the_stress_cell_report_says_so_when_the_cell_is_absent():
    from backtest.run_c15_sensitivities import stress_cell_report

    points = point_table(synthetic_ladder(zone="DE-LU", year=2024),
                         load_battery_config())
    assert stress_cell_report(points)["applicable"] is False


def test_memoising_the_counts_matrix_changes_no_number():
    """The draw must be the one `backtest.bootstrap` would have made, exactly."""
    from backtest.bootstrap import BlockBootstrapSpec, replicate_counts
    from backtest.run_c15_sensitivities import SEED, bootstrap_spec

    spec, counts = bootstrap_spec(90, 400, 7)
    reference = replicate_counts(
        BlockBootstrapSpec(n_days=90, n_replicates=400, block_days=7, seed=SEED)
    )
    assert spec.seed == SEED
    np.testing.assert_array_equal(counts, reference)
    # The same request must return the same draw, which is what "paired" means.
    assert bootstrap_spec(90, 400, 7)[1] is counts


def test_the_res_leg_reproduction_binds_c11s_own_committed_cash(tmp_path, monkeypatch):
    """``c13_daily_by_year`` carries no exogenous arm, so the RES leg needs C11's."""
    import backtest.run_c15_sensitivities as mod
    from backtest.run_c15_sensitivities import check_res_leg_reproduction

    frame = synthetic_ladder(
        rungs=(BASE_RUNG,),
        curves=(ORACLE_CURVE, "lear_res_persistence", "lear_res_as_published"),
        leg=RES_LEG,
    )
    reference = frame[["zone", "curve", "market_day", "cash"]].rename(
        columns={"cash": "cash_eur"}
    )
    reference.to_csv(tmp_path / "c11_capture_daily_2024.csv.gz", index=False)
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    assert check_res_leg_reproduction(frame)["holds"] is True

    drifted = frame.copy()
    drifted.loc[1, "cash"] = drifted.loc[1, "cash"] + 0.02
    report = check_res_leg_reproduction(drifted)
    assert report["holds"] is False
    assert report["worst_abs_cash_gap_eur"] == pytest.approx(0.02)


def test_the_res_leg_reproduction_is_not_applicable_without_the_res_leg(
    tmp_path, monkeypatch
):
    import backtest.run_c15_sensitivities as mod
    from backtest.run_c15_sensitivities import check_res_leg_reproduction

    pd.DataFrame({"zone": [], "curve": [], "market_day": [], "cash_eur": []}).to_csv(
        tmp_path / "c11_capture_daily_2024.csv.gz", index=False
    )
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    main_only = synthetic_ladder(rungs=(BASE_RUNG,))
    assert check_res_leg_reproduction(main_only)["applicable"] is False


def test_the_store_verification_keys_this_cycle_reads_actually_exist():
    """A typo'd key here fails *after* the whole ladder has been recomputed."""
    from backtest.results_store import verify_append_only

    report = verify_append_only()
    assert "verified" in report and isinstance(report["verified"], bool)
    assert "n_runs" in report and "n_rows" in report
    assert report["verified"] is True, report
