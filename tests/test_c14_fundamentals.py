"""C14 — the fundamentals chapter, NOTE C13-03, and the 2023 exogenous ladder.

Five things are tested here, and only the first two are new machinery.

**The descriptive/predictive line is a refusal, not a comment.** C14 is the first
cycle to use the as-published Art. 14 wind/solar vintage for anything other than
measuring the leak it creates. That is legitimate — nothing here is fitted or
scored — but "legitimate because we were careful" is not a guarantee, so
``assert_descriptive_only`` is a callable that raises, every row and artefact
carries ``after_gate_closure``, and the tests below pin both.

**The supply-curve statistics are checked against hand-built fixtures** whose
answers are known from construction: a synthetic zone with an exactly linear
stack must come back with equal slopes and no convexity; one with a convex stack
must come back convex; one whose negative prices are sprinkled uniformly across
the residual-load distribution must *not* be labelled an RES-surplus mechanism,
because that label is the whole content of FINDING C14-D.

**The bootstrap is C12's bootstrap.** A C14 interval is only comparable to a C12
or C13 one if the resample is identical, so ``block_day_picks`` asserts its own
draw counts against ``backtest.bootstrap.replicate_counts`` and a test checks
that the assertion can fail rather than trusting that it is there.

**The sealed holdout cannot be reached**, from any of the five phases, and the
guard fires on the year list before a path is built.

**The findings are pinned to the committed artefacts** (C12/C13's precedent), so
a later cycle cannot quietly restate a claim this cycle could not establish.
Tests needing an artefact skip when it is absent; nothing here needs the price
cache or the ENTSO-E cache, both of which are gitignored.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.bootstrap import BlockBootstrapSpec, replicate_counts
from backtest.run_c3_naive import RESULTS_DIR
from backtest.run_c14_fundamentals import (
    BLOCK_LADDER,
    EXOG_YEARS,
    FUNDAMENTALS_VINTAGE,
    HEADROOM_QUESTIONS,
    LADDER_CONTRASTS,
    LADDER_YEAR,
    N_RESIDUAL_LOAD_BINS,
    FundamentalsError,
    FundamentalsFrame,
    assert_descriptive_only,
    block_day_picks,
    convexity,
    cross_cell_headroom,
    cross_check_full_history_against_c13,
    explanatory_power,
    fundamentals_frame,
    headroom_correlations,
    headroom_frame,
    ladder_arms,
    level_versus_shape,
    merit_order_table,
    negative_price_concentration,
    residual_load_sufficiency,
    selected_zones,
    spearman_interval,
    verify_exog_cache,
    verify_price_cache,
)
from data.energy_charts import PRICE_COLUMN
from data.exogenous import (
    LOAD_COLUMN,
    RESIDUAL_LOAD_COLUMN,
    SOLAR_COLUMN,
    WIND_COLUMN,
)
from data.holdout import SealedHoldoutError

RESULTS = Path(RESULTS_DIR)
FUNDAMENTALS = RESULTS / "c14_fundamentals_summary.json"
HEADROOM = RESULTS / "c14_headroom_summary.json"
LADDER = RESULTS / "c14_ladder_summary.json"
DECILES = RESULTS / "c14_merit_order_deciles.csv"
POWER = RESULTS / "c14_explanatory_power.csv"
SLOPES = RESULTS / "c14_supply_curve_slopes.csv"
NEGATIVES = RESULTS / "c14_negative_price_mechanism.csv"
SUFFICIENCY = RESULTS / "c14_residual_load_sufficiency.csv"
HEADROOM_DAILY = RESULTS / "c14_headroom_daily.csv.gz"
HEADROOM_CELLS = RESULTS / "c14_headroom_cells.csv"
VERIFICATION = RESULTS / "c14_cache_verification.json"


def _needs(path: Path):
    if not path.exists():
        pytest.skip(f"{path.name} has not been produced in this working tree")


# ---------------------------------------------------------------------------
# Fixtures: synthetic zones whose answers are known by construction
# ---------------------------------------------------------------------------


def _synthetic(
    price_of_residual_load,
    n_days: int = 365,
    mean_load: float = 50_000.0,
    wind_amplitude: float = 15_000.0,
    solar_amplitude: float = 8_000.0,
    seed: int = 7,
) -> pd.DataFrame:
    """A year of hourly rows whose price is an exact function of residual load.

    Built the way the real frame is built — a UTC index, explicit
    ``local_market_day`` / ``local_hour`` / ``weekday`` / ``year`` columns, MW
    quantities — so the statistics under test see the same shape they see in
    production. ``price_of_residual_load`` is applied with **no noise** where a
    test needs an exact answer, and callers add noise themselves when they want
    a realistic one.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-01-01", periods=24 * n_days, freq="h", tz="UTC")
    hour = index.hour.to_numpy()
    load = mean_load + 8_000.0 * np.sin((hour - 7) / 24.0 * 2 * np.pi)
    wind = wind_amplitude * (0.5 + 0.5 * rng.random(len(index)))
    solar = solar_amplitude * np.clip(np.sin((hour - 6) / 12.0 * np.pi), 0.0, None)
    residual = load - wind - solar
    frame = pd.DataFrame(
        {
            PRICE_COLUMN: price_of_residual_load(residual),
            LOAD_COLUMN: load,
            WIND_COLUMN: wind,
            SOLAR_COLUMN: solar,
            RESIDUAL_LOAD_COLUMN: residual,
        },
        index=index,
    )
    frame["local_market_day"] = [ts.date() for ts in index]
    frame["local_hour"] = hour
    frame["weekday"] = index.weekday.to_numpy()
    frame["year"] = 2023
    return frame


@pytest.fixture(scope="module")
def linear_zone() -> pd.DataFrame:
    """An exactly linear stack: 2 EUR/MWh per GW, no noise, no negatives."""
    return _synthetic(lambda rl: 20.0 + 2.0 * rl / 1000.0)


@pytest.fixture(scope="module")
def convex_zone() -> pd.DataFrame:
    """A convex stack: quadratic in residual load, so the top is steeper."""
    return _synthetic(lambda rl: 20.0 + 0.04 * (rl / 1000.0) ** 2)


# ---------------------------------------------------------------------------
# The descriptive/predictive line
# ---------------------------------------------------------------------------


def test_the_fundamentals_vintage_is_after_gate_closure():
    """The Art. 14 vintage is six hours late and must be filed as such.

    If this constant were ever flipped to ``honest``, every artefact this cycle
    writes would claim a bidder could have had wind and solar they could not,
    and the claim would look identical in a diff.
    """
    assert FUNDAMENTALS_VINTAGE == "after_gate_closure"


def test_a_fundamentals_frame_refuses_to_be_modelled_on(linear_zone):
    bundle = FundamentalsFrame(
        zone="TEST", frame=linear_zone, vintage=FUNDAMENTALS_VINTAGE,
        n_price_hours=len(linear_zone), n_exog_hours=len(linear_zone),
        n_joined_hours=len(linear_zone), n_dropped_missing_residual_load=0,
        years=(2023,),
    )
    with pytest.raises(FundamentalsError, match="after gate closure"):
        assert_descriptive_only(bundle)


def test_the_refusal_names_the_vintage_before_it_names_the_use(linear_zone):
    """A mislabelled frame is refused for the label, which is the earlier error.

    A frame carrying ``honest`` is a frame someone has already decided is safe to
    model on. The refusal has to name *that* rather than the generic one, or the
    message sends a reader looking for the wrong bug.
    """
    bundle = FundamentalsFrame(
        zone="TEST", frame=linear_zone, vintage="honest",
        n_price_hours=1, n_exog_hours=1, n_joined_hours=1,
        n_dropped_missing_residual_load=0, years=(2023,),
    )
    with pytest.raises(FundamentalsError, match="must be labelled"):
        assert_descriptive_only(bundle)


def test_every_committed_fundamentals_row_carries_the_late_vintage():
    _needs(FUNDAMENTALS)
    summary = json.loads(FUNDAMENTALS.read_text(encoding="utf-8"))
    assert summary["vintage"] == "after_gate_closure"
    assert "after gate closure" in summary["vintage_note"]
    # And the note has to say the series is a forecast, not a measurement.
    assert "forecast" in summary["vintage_note"]


# ---------------------------------------------------------------------------
# The supply curve, against known answers
# ---------------------------------------------------------------------------


def test_a_linear_stack_has_equal_slopes_and_is_not_convex(linear_zone):
    table = merit_order_table(linear_zone, "TEST", 2023)
    assert len(table) == N_RESIDUAL_LOAD_BINS
    shape = convexity(table)
    # Built at exactly 2 EUR/MWh per GW, so every measured slope must be 2.
    for key in ("slope_low_eur_mwh_per_gw", "slope_mid_eur_mwh_per_gw",
                "slope_high_eur_mwh_per_gw"):
        assert shape[key] == pytest.approx(2.0, abs=1e-6)
    assert shape["high_over_mid"] == pytest.approx(1.0, abs=1e-6)
    assert shape["monotone_decile_medians"] is True
    assert shape["n_decile_decreases"] == 0


def test_a_falling_curve_does_not_report_a_convexity_ratio():
    """NO2 2022's two slopes are both negative, so their ratio is not convexity.

    ``high / mid`` on two negative numbers comes out positive and would read as
    "steeply convex" when it means "steeper downward at the top". The flag is
    what stops that misreading; ``convex_at_the_top`` compares the slopes
    directly and is right either way.
    """
    falling = _synthetic(lambda rl: 300.0 - 3.0 * rl / 1000.0)
    shape = convexity(merit_order_table(falling, "TEST", 2023))
    assert shape["slope_mid_eur_mwh_per_gw"] < 0
    assert shape["slope_high_eur_mwh_per_gw"] < 0
    assert shape["high_over_mid"] > 0          # the trap
    assert shape["slopes_are_positive"] is False
    assert shape["high_over_mid_is_a_convexity_ratio"] is False
    assert shape["monotone_decile_medians"] is False


def test_a_convex_stack_is_measured_as_convex(convex_zone):
    shape = convexity(merit_order_table(convex_zone, "TEST", 2023))
    assert shape["convex_at_the_top"] is True
    assert shape["slope_high_eur_mwh_per_gw"] > shape["slope_mid_eur_mwh_per_gw"]
    assert shape["slope_mid_eur_mwh_per_gw"] > shape["slope_low_eur_mwh_per_gw"]
    assert shape["high_over_mid"] > 1.0
    assert shape["slopes_are_positive"] is True


def test_an_exact_function_of_residual_load_is_fully_explained(linear_zone):
    """A price that *is* a function of residual load must come back at R^2 = 1.

    This is the upper end of the scale every number in FINDING C14-A is read
    against, so it is worth pinning rather than assuming.
    """
    power = explanatory_power(linear_zone, "TEST", 2023)
    assert power["r2_linear"] == pytest.approx(1.0, abs=1e-9)
    assert power["r2_piecewise_linear_20"] == pytest.approx(1.0, abs=1e-9)
    assert power["spearman_price_residual_load"] == pytest.approx(1.0, abs=1e-9)


def test_the_step_fit_loses_to_discretisation_on_a_smooth_relationship(linear_zone):
    """The 20-bin step function is *not* an upper bound, and the table says so.

    On an exactly linear zone the step fit scores below the straight line,
    because it discards the variation inside each bin. DE-LU 2024 is the real
    case. Reading ``r2_binned_20`` as "the best residual load can do" would
    therefore understate the merit order wherever the relationship is smooth —
    which is the conservative direction, and so the kind of error that survives
    review. ``r2_piecewise_linear_20`` is the column that does not have it.
    """
    power = explanatory_power(linear_zone, "TEST", 2023)
    assert power["r2_binned_20"] < power["r2_linear"]
    assert power["discretisation_loss_of_the_step_fit"] > 0.0


def test_the_nonlinearity_gain_is_nested_and_so_cannot_be_negative(convex_zone):
    """``piecewise_linear`` nests ``linear``, so curvature is measured cleanly."""
    power = explanatory_power(convex_zone, "TEST", 2023)
    assert power["nonlinearity_gain"] > 0.0
    assert power["r2_piecewise_linear_20"] > power["r2_linear"]


@pytest.mark.parametrize("builder", [
    lambda rl: 20.0 + 2.0 * rl / 1000.0,
    lambda rl: 20.0 + 0.04 * (rl / 1000.0) ** 2,
    lambda rl: 20.0 - 3.0 * rl / 1000.0,
])
def test_the_two_gains_are_never_negative_whatever_the_shape(builder):
    """Both reported gains are differences between nested fits.

    A negative value would mean the larger design matrix is not actually larger,
    which is a coding error and not a property of any price series — so it is
    checked across a rising, a convex and a *falling* stack (NO2 2022 is the
    real falling case).
    """
    power = explanatory_power(_synthetic(builder), "TEST", 2023)
    assert power["nonlinearity_gain"] >= 0.0
    assert power["gain_over_calendar"] >= 0.0


def test_the_calendar_block_is_additive_not_a_saturated_interaction(linear_zone):
    """An hour x weekday x bin interaction would be ~2.6 rows per cell.

    Its in-sample R^2 would be a statement about the cell count, not the price.
    The parameter counts are reported so this is checkable rather than asserted.
    """
    power = explanatory_power(linear_zone, "TEST", 2023)
    # 1 intercept + 24 hours + 7 weekdays, rank-deficient by two dummy traps.
    assert power["n_parameters_calendar_only"] == 30
    # And the joint fit stays far below the row count.
    assert power["n_parameters_residual_load_plus_calendar"] < 100
    assert power["r2_residual_load_plus_calendar"] <= 1.0


def test_the_calendar_control_is_computed_on_hour_and_weekday_cells(linear_zone):
    """The control must be a *clock* fit, not a second residual-load fit.

    FINDING C14-A's claim is that residual load explains the price beyond what a
    clock would. If the calendar column were accidentally built from residual
    load, the control would absorb the signal and the finding would read as
    weaker than it is — a silent failure in the conservative direction, which is
    the kind that survives review.
    """
    power = explanatory_power(linear_zone, "TEST", 2023)
    # The synthetic price depends on wind, which is iid noise, so a clock cannot
    # explain all of it; and the zone is built diurnal, so it must explain some.
    assert 0.0 < power["r2_calendar_only"] < power["r2_binned_20"]
    assert power["gain_over_calendar"] > 0.0


def test_a_flat_price_is_refused_rather_than_divided_by_zero():
    frame = _synthetic(lambda rl: np.full_like(rl, 42.0))
    with pytest.raises(FundamentalsError, match="constant"):
        explanatory_power(frame, "TEST", 2023)


def test_a_short_year_is_refused(linear_zone):
    with pytest.raises(FundamentalsError, match="too few"):
        merit_order_table(linear_zone.head(500), "TEST", 2023)


# ---------------------------------------------------------------------------
# The negative-price mechanism — the label FINDING C14-D turns on
# ---------------------------------------------------------------------------


def test_negatives_at_the_bottom_of_the_stack_are_labelled_res_surplus():
    """Negative prices only in the lowest residual-load hours: the textbook case.

    The cut is taken from the frame's own 8th percentile of residual load, so
    every negative hour is inside the bottom decile by construction and the
    expected concentration is exactly 10x uniform.
    """
    frame = _synthetic(lambda rl: 40.0 + 2.0 * rl / 1000.0)
    residual = frame[RESIDUAL_LOAD_COLUMN].to_numpy()
    cut = float(np.quantile(residual, 0.08))
    prices = frame[PRICE_COLUMN].to_numpy().copy()
    prices[residual <= cut] = -15.0
    frame = frame.assign(**{PRICE_COLUMN: prices})
    table = merit_order_table(frame, "TEST", 2023)
    report = negative_price_concentration(frame, "TEST", 2023, table)
    assert report["n_negative_hours"] > 400
    assert report["share_of_negatives_in_bottom_decile"] == pytest.approx(1.0)
    assert report["concentration_vs_uniform"] == pytest.approx(10.0)
    assert report["mechanism_consistent_with_res_surplus"] is True
    # The bottom decile is then majority-negative, which is the threshold the
    # reported crossing point measures.
    assert report["residual_load_gw_below_which_negative_is_more_likely_than_not"] is not None


def test_negatives_sprinkled_uniformly_are_not_labelled_res_surplus():
    """The falsification FINDING C14-D rests on.

    NO2 prints negative prices that are *not* concentrated at low residual load,
    and the whole content of the finding is that this is a different mechanism.
    If the label could not come back False, the finding would be unfalsifiable.
    """
    rng = np.random.default_rng(3)
    frame = _synthetic(lambda rl: 40.0 + 0.0 * rl)
    chosen = rng.choice(len(frame), size=400, replace=False)
    prices = frame[PRICE_COLUMN].to_numpy().copy()
    prices[chosen] = -10.0
    frame = frame.assign(**{PRICE_COLUMN: prices})
    table = merit_order_table(frame, "TEST", 2023)
    report = negative_price_concentration(frame, "TEST", 2023, table)
    assert report["n_negative_hours"] == 400
    # Uniform by construction, so the bottom decile should hold ~10% of them.
    assert report["share_of_negatives_in_bottom_decile"] == pytest.approx(0.1, abs=0.04)
    assert report["mechanism_consistent_with_res_surplus"] is False


def test_a_year_with_no_negative_hours_reports_none_not_zero():
    """ES 2022 and 2023 printed no negative hour at all.

    A share of negatives is undefined there, and reporting 0.0 would read as
    "negatives exist and none are at the bottom", which is the opposite of the
    truth. ES's two empty years are in the committed table, so this distinction
    is load-bearing and not hypothetical.
    """
    frame = _synthetic(lambda rl: 40.0 + 2.0 * rl / 1000.0)
    table = merit_order_table(frame, "TEST", 2023)
    report = negative_price_concentration(frame, "TEST", 2023, table)
    assert report["n_negative_hours"] == 0
    assert report["share_of_negatives_in_bottom_decile"] is None
    assert report["mechanism_consistent_with_res_surplus"] is None


# ---------------------------------------------------------------------------
# Sufficiency
# ---------------------------------------------------------------------------


def test_a_price_built_from_residual_load_makes_the_components_cancel(linear_zone):
    """Built as a function of ``load - wind - solar``, so the fit must recover it.

    The merit-order restriction is that the three coefficients are
    ``(+b, -b, -b)``. Here they must be exactly that, because the data-generating
    process is exactly residual load.
    """
    report = residual_load_sufficiency(linear_zone, "TEST", 2023)
    assert report["coef_load_eur_mwh_per_gw"] == pytest.approx(2.0, abs=1e-6)
    assert report["coef_wind_eur_mwh_per_gw"] == pytest.approx(-2.0, abs=1e-6)
    assert report["coef_solar_eur_mwh_per_gw"] == pytest.approx(-2.0, abs=1e-6)
    assert report["wind_plus_load_cancels"] == pytest.approx(0.0, abs=1e-6)
    assert report["r2_lost_by_imposing_residual_load"] == pytest.approx(0.0, abs=1e-9)


def test_a_zone_with_no_solar_fleet_reports_no_solar_coefficient():
    """NO2's solar forecast is identically zero for whole years.

    A fitted coefficient on an all-zero column is not identified, and reporting
    one would put a meaningless number in a published table.
    """
    frame = _synthetic(lambda rl: 20.0 + 2.0 * rl / 1000.0, solar_amplitude=0.0)
    report = residual_load_sufficiency(frame, "TEST", 2023)
    assert report["solar_coefficient_identified"] is False
    assert report["coef_solar_eur_mwh_per_gw"] is None
    assert report["solar_cannibalises_more_than_wind"] is None


def test_the_size_normalised_slope_makes_two_zones_comparable():
    """A per-GW slope is not comparable across a 4 GW and a 54 GW system.

    Two synthetic zones with the same *relative* price response and a 10x size
    difference must agree on the normalised figure and disagree by 10x on the raw
    one. NO2's 23 EUR/MWh/GW against DE-LU's 3.1 is exactly this artefact, and a
    cross-zone sentence that used the raw numbers would be wrong.
    """
    big = _synthetic(
        lambda rl: 20.0 + 2.0 * rl / 1000.0, mean_load=50_000.0,
        wind_amplitude=15_000.0, solar_amplitude=8_000.0,
    )
    small = _synthetic(
        lambda rl: 20.0 + 20.0 * rl / 1000.0, mean_load=5_000.0,
        wind_amplitude=1_500.0, solar_amplitude=800.0,
    )
    a = residual_load_sufficiency(big, "BIG", 2023)
    b = residual_load_sufficiency(small, "SMALL", 2023)
    assert b["coef_load_eur_mwh_per_gw"] == pytest.approx(
        10.0 * a["coef_load_eur_mwh_per_gw"], rel=1e-4
    )
    assert b["coef_load_eur_mwh_per_10pct_mean_load"] == pytest.approx(
        a["coef_load_eur_mwh_per_10pct_mean_load"], rel=1e-3
    )


def test_the_sufficiency_contrasts_carry_intervals(linear_zone):
    report = residual_load_sufficiency(linear_zone, "TEST", 2023)
    assert "wind_plus_load_cancels_ci_low" in report
    assert report["wind_plus_load_cancels_ci_low"] <= report["wind_plus_load_cancels"]
    assert report["wind_plus_load_cancels"] <= report["wind_plus_load_cancels_ci_high"]
    # Zero violation by construction, so the interval must contain zero.
    assert report["wind_plus_load_cancels_excludes_zero"] is False


# ---------------------------------------------------------------------------
# Level versus shape
# ---------------------------------------------------------------------------


def test_a_pure_level_shift_keeps_its_shape():
    """Multiply every price by 3 and the decile *shape* must not move.

    This is the measurement FINDING C14-C makes about the 2022 crisis, so a
    fixture where the answer is known by construction is the right test: the
    normalised curves must coincide and the level ratio must be exactly 3.
    """
    base = _synthetic(lambda rl: 20.0 + 2.0 * rl / 1000.0)
    tripled = base.assign(**{PRICE_COLUMN: base[PRICE_COLUMN] * 3.0})
    tables = {
        2022: merit_order_table(base, "TEST", 2023).assign(year=2022),
        2023: merit_order_table(tripled, "TEST", 2023),
    }
    report = level_versus_shape(tables, "TEST")
    pair = report["pairs"][0]
    assert pair["level_ratio_mid_decile"] == pytest.approx(3.0, abs=1e-3)
    assert pair["shape_spearman_decile_medians"] == pytest.approx(1.0, abs=1e-9)
    assert pair["shape_pearson_normalised"] == pytest.approx(1.0, abs=1e-6)
    assert pair["normalised_curve_max_abs_difference"] == pytest.approx(0.0, abs=1e-6)


def test_a_bent_curve_is_distinguished_from_a_shifted_one():
    """A steepened curve must not pass as a parallel shift.

    Rank correlation alone cannot tell them apart — any two monotone curves
    rank-correlate at 1 — which is why the normalised comparison exists.
    """
    base = _synthetic(lambda rl: 20.0 + 2.0 * rl / 1000.0)
    bent = _synthetic(lambda rl: 20.0 + 0.04 * (rl / 1000.0) ** 2)
    tables = {
        2022: merit_order_table(base, "TEST", 2023).assign(year=2022),
        2023: merit_order_table(bent, "TEST", 2023),
    }
    pair = level_versus_shape(tables, "TEST")["pairs"][0]
    assert pair["shape_spearman_decile_medians"] == pytest.approx(1.0, abs=1e-9)
    assert pair["normalised_curve_max_abs_difference"] > 0.1


# ---------------------------------------------------------------------------
# The bootstrap is C12's bootstrap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", BLOCK_LADDER)
def test_c14_day_picks_reproduce_the_shared_count_matrix(block):
    spec = BlockBootstrapSpec(n_days=120, n_replicates=200, block_days=block, seed=11)
    picks = block_day_picks(spec)
    assert picks.shape == (200, 120)
    counts = np.zeros((200, 120))
    rows = np.repeat(np.arange(200), 120)
    np.add.at(counts, (rows, np.asarray(picks).reshape(-1)), 1.0)
    assert np.array_equal(counts, replicate_counts(spec))


def test_the_cached_picks_cannot_be_mutated_by_a_caller():
    """A cached array handed out mutable would let one caller corrupt the rest."""
    spec = BlockBootstrapSpec(n_days=60, n_replicates=50, block_days=1, seed=5)
    picks = block_day_picks(spec)
    with pytest.raises(ValueError):
        picks[0, 0] = 999


def test_a_perfectly_ranked_pair_bootstraps_to_one():
    spec = BlockBootstrapSpec(n_days=200, n_replicates=500, block_days=1, seed=2)
    x = np.arange(200, dtype=float)
    interval = spearman_interval(x, 2.0 * x + 1.0, spec)
    assert interval.point == pytest.approx(1.0, abs=1e-9)
    assert interval.ci_low == pytest.approx(1.0, abs=1e-9)
    assert interval.excludes_zero is True


def test_an_unrelated_pair_bootstraps_across_zero():
    spec = BlockBootstrapSpec(n_days=300, n_replicates=2000, block_days=1, seed=4)
    rng = np.random.default_rng(99)
    interval = spearman_interval(rng.normal(size=300), rng.normal(size=300), spec)
    assert abs(interval.point) < 0.2
    assert interval.excludes_zero is False


def test_a_sign_flip_flips_the_interval():
    spec = BlockBootstrapSpec(n_days=150, n_replicates=400, block_days=1, seed=6)
    x = np.arange(150, dtype=float)
    positive = spearman_interval(x, x, spec)
    negative = spearman_interval(x, -x, spec)
    assert positive.point == pytest.approx(-negative.point, abs=1e-9)


def test_mismatched_columns_are_refused():
    spec = BlockBootstrapSpec(n_days=50, n_replicates=50, block_days=1, seed=1)
    with pytest.raises(FundamentalsError, match="equal length"):
        spearman_interval(np.arange(50.0), np.arange(49.0), spec)


# ---------------------------------------------------------------------------
# The sealed holdout
# ---------------------------------------------------------------------------


def test_the_declared_years_stop_before_the_holdout():
    assert 2025 not in EXOG_YEARS
    assert LADDER_YEAR == 2023
    assert max(EXOG_YEARS) == 2024


def test_a_fundamentals_frame_refuses_a_sealed_year_before_touching_a_path():
    """The guard fires on the year list, so 2025 cannot arrive as a file error.

    If it fired later, a missing-file message would be the *only* thing standing
    between this cycle and the holdout, and a cached 2025 file would be enough
    to defeat it.
    """
    with pytest.raises(SealedHoldoutError):
        fundamentals_frame("DE-LU", [2025])


def test_a_headroom_frame_refuses_a_sealed_year_before_touching_a_path():
    with pytest.raises(SealedHoldoutError):
        headroom_frame("DE-LU", [2024, 2025])


def test_no_committed_c14_artefact_names_a_sealed_market_day():
    for path in (HEADROOM_DAILY, HEADROOM_CELLS, DECILES, POWER, SLOPES, NEGATIVES,
                 SUFFICIENCY):
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if "year" in frame.columns:
            assert set(frame["year"].astype(int)) <= set(EXOG_YEARS) | {LADDER_YEAR}
        if "market_day" in frame.columns:
            years = {int(str(d)[:4]) for d in frame["market_day"]}
            assert 2025 not in years, f"{path.name} holds a 2025 market day"


# ---------------------------------------------------------------------------
# The cache verification
# ---------------------------------------------------------------------------


def test_the_cache_verification_compares_fingerprints_not_statistics():
    """A re-pull is verified by data fingerprint, not by summary statistics.

    Two series with the same mean, min and max are not the same series. C13
    checked six statistics; this cycle checks the ``payload_sha256`` the
    manifest committed, which is the only comparison that cannot be passed by
    accident.
    """
    _needs(VERIFICATION)
    report = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    assert report["prices"]["n_files"] == 54
    assert report["prices"]["n_matching"] == 54
    # 3 zones x 2 documents x 3 years = 18 documents, carrying 27 series
    # (A65 has one column, A69 has two).
    assert report["exogenous"]["n_files"] == 18
    assert report["exogenous"]["n_series"] == 27
    assert report["exogenous"]["n_matching"] == 27
    for block in ("prices", "exogenous"):
        assert report[block]["n_mismatched"] == 0
        assert report[block]["holds"] is True
    assert report["holds"] is True


def test_the_fingerprint_is_of_the_data_not_of_the_cached_file():
    """A file hash would change on every re-fetch and teach a reader to ignore it.

    The cached file embeds ``_fetch_meta.fetched_at_utc``, which is exactly why
    the Checkpoint-A decision (NOTE C2-01) replaced a file hash with a payload
    fingerprint. A C14 check built on the file would fail every cycle on data
    that had not changed. The report names the function it used so this is
    checkable rather than asserted.
    """
    _needs(VERIFICATION)
    report = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    assert "payload_fingerprint" in report["prices"]["fingerprint"]
    assert "series_fingerprint" in report["exogenous"]["fingerprint"]
    assert "per series" in report["exogenous"]["fingerprint"]


def test_the_exogenous_check_is_keyed_on_the_series_not_the_document():
    """The A69 document carries two series with two different committed hashes.

    A check keyed on (zone, document, year) would find two candidate values and
    have to pick one, which is a check that cannot fail cleanly.
    """
    path = Path(RESULTS_DIR).parent.parent / "data" / "manifest" / "exogenous_manifest.csv"
    _needs(path)
    manifest = pd.read_csv(path)
    a69 = manifest[manifest["document"] == "wind_solar_forecast_da"]
    per_document = a69.groupby(["zone", "year"])["payload_sha256"].nunique()
    assert (per_document == 2).all()


def test_the_cache_verification_runs_without_a_cache_or_skips():
    """The check must *fail* on an absent cache, never pass vacuously."""
    try:
        report = verify_price_cache(selected_zones(None))
    except FileNotFoundError:
        pytest.skip("the price cache is not present in this working tree")
    if report["n_files"] == 0:
        assert report["holds"] is False


# ---------------------------------------------------------------------------
# NOTE C13-03, pinned to the committed artefacts
# ---------------------------------------------------------------------------


def test_the_headroom_questions_name_both_halves_of_the_ratio():
    """``error_over_headroom`` is MAE / spread, so both halves need a question.

    FINDING C13-D is about the ratio. A cycle that only asked about the ratio
    could not say *which* half a fundamental acts on, and the two have different
    consequences for a desk: a bigger error is a worse model, a smaller spread is
    a worse market.
    """
    outcomes = {outcome for _, outcome, _ in HEADROOM_QUESTIONS}
    assert "error_over_headroom" in outcomes
    assert "price_mae_eur_mwh" in outcomes
    assert "realised_spread_eur_mwh" in outcomes


def test_the_headroom_correlations_carry_intervals_at_every_block():
    _needs(HEADROOM)
    summary = json.loads(HEADROOM.read_text(encoding="utf-8"))
    rows = [r for r in summary["correlations"] if "spearman" in r]
    assert rows, "no correlation row carries a point estimate"
    for row in rows:
        assert row["ci_low"] <= row["spearman"] <= row["ci_high"]
        for block in BLOCK_LADDER:
            if block == 1:
                continue
            assert f"block{block}_spearman" in row


def test_the_residual_load_error_is_labelled_a_revision():
    """It is not a forecast error and must never be published as one.

    The as-published Art. 14 vintage is the closest thing available to realised
    residual load, so the day-over-day difference is a *revision* and a lower
    bound on the error a bidder carried. Dropping that label would overstate how
    well this cycle can answer NOTE C13-03.
    """
    _needs(HEADROOM)
    summary = json.loads(HEADROOM.read_text(encoding="utf-8"))
    assert "revision" in summary["residual_load_error_caveat"]
    assert "lower bound" in summary["residual_load_error_caveat"]


def test_the_headroom_phase_reads_c13s_artefact_and_refits_nothing():
    """NOTE C13-03 is answered from committed rows, not from 27 new fits."""
    _needs(HEADROOM)
    summary = json.loads(HEADROOM.read_text(encoding="utf-8"))
    assert summary["dispatch_source"] == "c13_daily_by_year.csv.gz"
    assert summary["dispatch_curve"] == "lear_full_history"


def test_the_cross_cell_version_is_labelled_as_underpowered():
    """Nine cells cannot establish what FINDING C13-D needed 44 for."""
    _needs(HEADROOM)
    summary = json.loads(HEADROOM.read_text(encoding="utf-8"))
    block = summary["cross_cell"]
    assert block["n_cells"] <= 9
    assert "44" in block["honest_label"]
    assert "not established" in block["honest_label"]
    assert "nine" in block["honest_label"]


def test_cross_cell_headroom_refuses_to_report_on_too_few_cells():
    frame = pd.DataFrame(
        {
            "zone": ["A", "B"],
            "year": [2023, 2023],
            "residual_load_revision_mae_mw": [1.0, 2.0],
            "error_over_headroom": [0.2, 0.3],
            "residual_load_range_gw": [1.0, 2.0],
            "residual_load_mean_gw": [1.0, 2.0],
            "price_mae_eur_mwh": [1.0, 2.0],
            "realised_spread_eur_mwh": [1.0, 2.0],
        }
    )
    report = cross_cell_headroom(frame)
    assert report["n_cells"] == 2
    assert not any(k.startswith("spearman_") for k in report)


def test_a_zone_year_with_too_few_days_is_skipped_not_fabricated():
    frame = pd.DataFrame(
        {
            "zone": "TEST", "year": 2023,
            "residual_load_revision_mae_mw": np.arange(10.0),
            "error_over_headroom": np.arange(10.0),
            "price_mae_eur_mwh": np.arange(10.0),
            "realised_spread_eur_mwh": np.arange(10.0),
            "residual_load_range_gw": np.arange(10.0),
        }
    )
    rows = headroom_correlations(frame, "TEST", 2023)
    assert all("spearman" not in row for row in rows)
    assert all(row["skipped"] for row in rows)


# ---------------------------------------------------------------------------
# The 2023 ladder
# ---------------------------------------------------------------------------


def test_the_ladder_arms_match_c11s_taxonomy_exactly():
    """A 2023 capture ratio must join to a 2024 one on the store key.

    The store key is ``(model, exog_variant, vintage, train_from)``. If C14
    spelled any of the four differently, the two years would be two unrelated
    rows and the second-year comparison NOTE C8-01 is waiting on would silently
    not exist.
    """
    from backtest.run_c11_dispatch import arms_for

    mine = {a.curve: a for a in ladder_arms("DE-LU")}
    theirs = {a.curve: a for a in arms_for("DE-LU", "A")}
    shared = set(mine) & set(theirs)
    assert {"gbm_price_only", "gbm_res_persistence", "lear_price_only",
            "lear_res_persistence"} <= shared
    for curve in shared:
        assert mine[curve].model == theirs[curve].model
        assert mine[curve].exog_variant == theirs[curve].exog_variant
        assert mine[curve].vintage == theirs[curve].vintage
        assert mine[curve].train_from == theirs[curve].train_from
        assert mine[curve].column == theirs[curve].column


def test_the_ladder_artefacts_are_the_ladder_years():
    for arm in ladder_arms("ES"):
        assert f"_{LADDER_YEAR}_" in arm.artefact
        assert "2024" not in arm.artefact


def test_the_late_arms_are_the_only_ones_marked_after_gate_closure():
    late = {a.curve for a in ladder_arms("DE-LU") if a.vintage == "after_gate_closure"}
    assert late == {"lear_res_as_published", "gbm_res_as_published"}


def test_every_ladder_contrast_names_a_real_arm():
    curves = {a.curve for a in ladder_arms("NO2")}
    for treatment, baseline, question in LADDER_CONTRASTS:
        assert treatment in curves
        assert baseline in curves
        assert question


def test_the_ladder_year_is_the_only_one_a_2022_aligned_arm_can_add():
    """2022 cannot be an evaluation year for an exogenous arm, and 2025 is sealed.

    The arms are aligned to ``train_from = 2022-01-01`` (no archived ENTSO-E D-1
    vintage exists earlier) and the harness needs 365 market days of history. So
    the honest evaluation years are 2023 and 2024, and 2023 is the one C11/C12
    did not have. NOTE C13-04's "one extra draw" is this arithmetic.
    """
    assert LADDER_YEAR == 2023
    assert LADDER_YEAR in EXOG_YEARS
    assert LADDER_YEAR < 2024


def test_the_ladder_summary_labels_2023_as_a_prediction_not_a_configuration_test():
    _needs(LADDER)
    summary = json.loads(LADDER.read_text(encoding="utf-8"))
    assert "training" in summary["honest_label"]
    assert "configuration test" in summary["honest_label"]
    assert "sealed" in summary["honest_label"]


def test_the_ladder_uses_finding_c11_cs_denominator():
    """``capture_same_start_pooled`` must never be used to rank two curves."""
    _needs(LADDER)
    summary = json.loads(LADDER.read_text(encoding="utf-8"))
    assert "capture_rolled_oracle_cash" in summary["denominator"]
    assert "same days" in summary["denominator"]


def test_the_ladder_contrasts_carry_intervals_at_every_block():
    _needs(RESULTS / "c14_ladder_contrasts.csv")
    frame = pd.read_csv(RESULTS / "c14_ladder_contrasts.csv")
    assert len(frame) == len(LADDER_CONTRASTS) * frame["zone"].nunique()
    for block in BLOCK_LADDER:
        prefix = "" if block == 1 else f"block{block}_"
        assert f"{prefix}ci_low_pp" in frame.columns
        assert f"{prefix}ci_high_pp" in frame.columns
    assert (frame["ci_low_pp"] <= frame["delta_pp"]).all()
    assert (frame["delta_pp"] <= frame["ci_high_pp"]).all()


def test_c8s_full_history_arm_reproduces_c13s_comparable_arm():
    """The C20 reproducibility check, obtained free in C14.

    C8's full-history reference arm and C13's nine-zone comparable arm are the
    *same* configuration — C4's committed LearSpec on price and calendar
    features, expanding window from 2019 — computed by two different runners in
    two different containers off two independent re-pulls of the price cache. If
    they disagree, one of the two cycles' committed forecasts is not what its
    code produces today, which is a provenance failure rather than a tolerance
    question.
    """
    report = cross_check_full_history_against_c13("DE-LU")
    if "skipped" in report:
        pytest.skip(report["skipped"])
    assert report["n_hours_compared"] > 8_000
    assert report["worst_abs_difference_eur_mwh"] <= 5e-4
    assert report["holds"] is True


def test_the_reproducibility_check_skips_rather_than_passes_when_absent():
    """A check that silently passes on a missing file is worse than no check."""
    report = cross_check_full_history_against_c13("FR")  # Tier B: no C8 artefact
    assert "skipped" in report
    assert "holds" not in report


def test_the_gbm_fingerprint_is_the_frozen_one():
    """PLAN.md forbids a hyperparameter search across cycles.

    A 2023 run on a re-tuned config would not be a second year of the same
    experiment, and the difference would be invisible in the capture table.
    """
    _needs(LADDER)
    summary = json.loads(LADDER.read_text(encoding="utf-8"))
    assert summary["gbm_fingerprint"] == "a366a760e269bba6"


def test_the_ladder_invariant_flags_are_recorded_not_swallowed():
    path = RESULTS / "c14_ladder_invariant_flags.json"
    _needs(path)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["year"] == LADDER_YEAR
    assert "n_failures" in report
    # A flagged run must still have written its flags, and the count must agree
    # with the detail — a summary number without the detail behind it is how a
    # failure becomes invisible.
    assert report["n_failures"] == sum(len(v) for v in report["flags"].values())


# ---------------------------------------------------------------------------
# The findings, pinned
# ---------------------------------------------------------------------------


def test_finding_c14_a_residual_load_explains_less_in_no2_than_in_de_lu_or_es():
    """FINDING C14-A, pinned: the merit order is mostly a DE-LU/ES fact."""
    _needs(POWER)
    frame = pd.read_csv(POWER).set_index(["zone", "year"])
    for year in (2023, 2024):
        no2 = frame.loc[("NO2", year), "r2_binned_20"]
        assert no2 < frame.loc[("DE-LU", year), "r2_binned_20"]
        assert no2 < frame.loc[("ES", year), "r2_binned_20"]


def test_finding_c14_b_no2s_supply_curve_has_the_wrong_sign_in_2022():
    """FINDING C14-B, pinned. A merit order cannot slope down."""
    _needs(POWER)
    frame = pd.read_csv(POWER).set_index(["zone", "year"])
    assert frame.loc[("NO2", 2022), "spearman_price_residual_load"] < 0
    # And it is the only (zone, year) in the table that does.
    negative = frame[frame["spearman_price_residual_load"] < 0]
    assert list(negative.index) == [("NO2", 2022)]


def test_finding_c14_c_the_crisis_moved_the_level_and_kept_the_shape():
    """FINDING C14-C, pinned, for the two zones with a real merit order."""
    _needs(FUNDAMENTALS)
    summary = json.loads(FUNDAMENTALS.read_text(encoding="utf-8"))
    by_zone = {block["zone"]: block["pairs"] for block in summary["level_versus_shape"]}
    for zone in ("DE-LU", "ES"):
        pair = next(
            p for p in by_zone[zone] if p["early_year"] == 2022 and p["late_year"] == 2024
        )
        # 2024 is well below 2022 in level ...
        assert pair["level_ratio_mid_decile"] < 0.5
        # ... and the normalised shapes still agree.
        assert pair["shape_pearson_normalised"] > 0.9


def test_finding_c14_d_negative_prices_are_concentrated_except_in_no2():
    """FINDING C14-D, pinned, including the size of the gap."""
    _needs(NEGATIVES)
    frame = pd.read_csv(NEGATIVES)
    rows = frame.dropna(subset=["concentration_vs_uniform"]).set_index(["zone", "year"])
    for year in (2022, 2023, 2024):
        if ("DE-LU", year) in rows.index:
            assert rows.loc[("DE-LU", year), "concentration_vs_uniform"] > 8.0
    for year in (2023, 2024):
        assert rows.loc[("NO2", year), "concentration_vs_uniform"] < 5.0
        assert (
            rows.loc[("NO2", year), "concentration_vs_uniform"]
            < rows.loc[("DE-LU", year), "concentration_vs_uniform"] / 2.0
        )


def test_finding_c14_e_the_res_revision_tracks_the_error_except_in_no2():
    """FINDING C14-E, pinned: NOTE C13-03's answer is zone-specific."""
    _needs(HEADROOM)
    summary = json.loads(HEADROOM.read_text(encoding="utf-8"))
    rows = [
        r for r in summary["correlations"]
        if r.get("fundamental") == "residual_load_range_gw"
        and r.get("outcome") == "realised_spread_eur_mwh"
        and r.get("year") != "pooled"
        and "spearman" in r
    ]
    by_cell = {(r["zone"], r["year"]): r for r in rows}
    # The per-year rows are the claim; the pooled row carries between-year
    # co-movement and is explicitly the weaker number (see the docstring on
    # headroom_correlations), so it is not what this finding is pinned to.
    for year in (2023, 2024):
        assert by_cell[("DE-LU", year)]["spearman"] > 0.4
        assert by_cell[("DE-LU", year)]["excludes_zero"] is True
        # NO2's daily price shape has no relationship to its residual-load shape:
        # not merely small, but an interval that contains zero, in every year.
        assert abs(by_cell[("NO2", year)]["spearman"]) < 0.1
        assert by_cell[("NO2", year)]["excludes_zero"] is False
    assert by_cell[("NO2", 2022)]["excludes_zero"] is False
