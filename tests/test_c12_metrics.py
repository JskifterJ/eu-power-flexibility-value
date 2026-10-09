"""C12 — the metrics layer and the daily-block bootstrap.

Three things are tested here, in increasing order of what they protect.

**The new metrics are right.** The daily-spread error and the within-day
Spearman are computed on hand-made price vectors whose answers can be read off
by eye, including the cases that matter: a flat day has no ordering to predict,
a tie is averaged rather than broken, and a pooled MAE over days of different
length is a ratio of sums and *not* a mean of per-day MAEs. The last one is the
DST bug that would otherwise be invisible.

**The bootstrap is calibrated.** The block resample is checked against the two
cases where the answer is known analytically — ``block_days=1`` is the ordinary
iid-over-days bootstrap, and ``block_days=n_days`` can only produce rotations
of the whole year, so every replicate of a day-additive statistic is the point
estimate itself. The null-band test is checked for *calibration*: on groups that
really are identical its p-value must not be systematically small, and on a
group shifted far out it must be ~0. A band test that cried wolf would make
FINDING C12-A an artefact of this file.

**The C12 findings are pinned to the committed artefacts.** FINDING C12-C (the
within-day Spearman is the only point-forecast metric whose cross-zone ranking
tracks capture with an interval excluding zero), FINDING C12-D (capture decides
far fewer arm contrasts than MAE or the Spearman at one year) and FINDING C12-E
(the GBM-exogenous capture gain's interval includes zero in all three Tier-A
zones) are each asserted against the files the cycle committed, so a later cycle
cannot quietly promote MAE back or re-report a gain this one could not
establish.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.bootstrap import (
    BLOCK_LADDER,
    BlockBootstrapSpec,
    BootstrapError,
    DEFAULT_SEED,
    difference_interval,
    mean_interval,
    mean_replicates,
    noise_only_spread,
    ratio_interval,
    ratio_replicates,
    replicate_counts,
    spearman_rows,
)
from backtest.metrics import (
    MIN_HOURS_FOR_SPEARMAN,
    MetricError,
    daily_shape_table,
    daily_spread_error,
    score,
    shape_scores,
    spearman_rho,
    within_day_spearman,
)

RESULTS = Path(__file__).resolve().parent.parent / "backtest" / "results"


def _hours(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_hours(len(values)), dtype="float64")


# ---------------------------------------------------------------------------
# spearman_rho
# ---------------------------------------------------------------------------


def test_a_forecast_in_the_right_order_scores_one_however_wrong_its_level():
    """The whole point of a rank metric: the LP reads order, not level."""
    truth = _series([10.0, 20.0, 30.0, 40.0])
    shifted = _series([110.0, 120.0, 130.0, 140.0])
    assert spearman_rho(shifted, truth) == pytest.approx(1.0)


def test_a_forecast_in_exactly_the_wrong_order_scores_minus_one():
    truth = _series([10.0, 20.0, 30.0, 40.0])
    reversed_ = _series([40.0, 30.0, 20.0, 10.0])
    assert spearman_rho(reversed_, truth) == pytest.approx(-1.0)


def test_a_flat_day_has_no_ordering_and_the_rho_is_nan_not_zero():
    """Undefined is not "no skill" — it has to be counted, not scored."""
    flat = _series([30.0, 30.0, 30.0, 30.0])
    assert math.isnan(spearman_rho(_series([1.0, 2.0, 3.0, 4.0]), flat))
    assert math.isnan(spearman_rho(flat, _series([1.0, 2.0, 3.0, 4.0])))


def test_ties_are_averaged_rather_than_broken():
    """Average ranks is what "Spearman" means; argsort order is not a tiebreak.

    The forecast here orders the two tied realised hours, so the two rules give
    genuinely different answers: averaging the tied ranks gives 0.9487, while
    breaking the tie in index order would give 0.8. European market days carry
    ties often (identical clearing prices in consecutive hours), so this is not
    a corner case.
    """
    truth = _series([1.0, 2.0, 2.0, 3.0])
    forecast = _series([5.0, 7.0, 6.0, 8.0])
    assert spearman_rho(forecast, truth) == pytest.approx(4.5 / math.sqrt(22.5))
    assert spearman_rho(forecast, truth) == pytest.approx(0.9486832981)
    assert spearman_rho(forecast, truth) != pytest.approx(0.8)


def test_too_few_hours_is_undefined_rather_than_a_coincidence():
    short = _series([1.0, 2.0])
    assert MIN_HOURS_FOR_SPEARMAN == 3
    assert math.isnan(spearman_rho(short, _series([2.0, 1.0])))


def test_a_missing_hour_is_dropped_from_the_pair_not_from_the_count():
    truth = _series([10.0, 20.0, 30.0, 40.0])
    forecast = _series([1.0, float("nan"), 3.0, 4.0])
    assert spearman_rho(forecast, truth) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# daily_shape_table
# ---------------------------------------------------------------------------


def test_the_spread_error_is_signed_so_an_over_promised_day_is_visible():
    """Positive = the forecast promised a wider day than arrived.

    That is the sign that makes a battery over-trade, so it must not be
    collapsed into an absolute value before it is reported.
    """
    truth = _series([0.0, 100.0, 50.0, 50.0])
    wide = _series([0.0, 200.0, 50.0, 50.0])
    narrow = _series([40.0, 60.0, 50.0, 50.0])
    days = np.array(["2024-01-01"] * 4)
    assert daily_shape_table(truth, wide, days)["spread_error"].iloc[0] == pytest.approx(100.0)
    assert daily_shape_table(truth, narrow, days)["spread_error"].iloc[0] == pytest.approx(-80.0)


def test_the_pooled_mae_is_a_ratio_of_sums_not_a_mean_of_daily_maes():
    """The DST bug this shape protects against, made explicit.

    A 23-hour day and a 25-hour day do not carry equal weight in a pooled MAE.
    A mean of per-day MAEs says they do, and would be wrong by the amount the
    two days' errors differ — invisible in a diff and invisible in a plot.
    """
    index = _hours(4)
    truth = pd.Series([0.0, 0.0, 0.0, 0.0], index=index)
    forecast = pd.Series([10.0, 10.0, 10.0, 1.0], index=index)
    days = np.array(["d1", "d1", "d1", "d2"])
    table = daily_shape_table(truth, forecast, days)
    pooled = shape_scores(table).mae
    assert pooled == pytest.approx((10 + 10 + 10 + 1) / 4)
    mean_of_daily = np.mean([10.0, 1.0])
    assert pooled != pytest.approx(mean_of_daily)


def test_shape_scores_agrees_exactly_with_the_c3_scorer_on_the_same_hours():
    """The identity that lets C12 put a point error beside a dispatch metric.

    If :func:`shape_scores` and :func:`score` could disagree, every paired
    comparison in this cycle would be a comparison of two samples.
    """
    frame = pd.read_csv(RESULTS / "c8_exog_DE-LU_2024_predictions.csv.gz")
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
    frame = frame.set_index(index)
    table = daily_shape_table(
        frame["y_true"], frame["y_pred_price_only_full_history"], frame["market_day"].to_numpy()
    )
    mine = shape_scores(table)
    theirs = score(frame["y_true"], frame["y_pred_price_only_full_history"])
    assert mine.mae == pytest.approx(theirs.mae, abs=1e-12)
    assert mine.rmse == pytest.approx(theirs.rmse, abs=1e-12)
    assert mine.bias == pytest.approx(theirs.bias, abs=1e-12)
    assert mine.n_hours == theirs.n_scored


def test_an_undefined_spearman_day_is_counted_and_excluded_from_the_mean():
    index = _hours(6)
    truth = pd.Series([1.0, 2.0, 3.0, 7.0, 7.0, 7.0], index=index)
    forecast = pd.Series([1.0, 2.0, 3.0, 1.0, 2.0, 3.0], index=index)
    days = np.array(["d1"] * 3 + ["d2"] * 3)
    scores = shape_scores(daily_shape_table(truth, forecast, days))
    assert scores.n_days_scored == 2
    assert scores.n_days_spearman_undefined == 1
    assert scores.spearman_mean == pytest.approx(1.0)


def test_the_two_plan_md_wrappers_read_off_the_same_table():
    frame = pd.read_csv(RESULTS / "c10_tierb_FR_2024_predictions.csv.gz")
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
    frame = frame.set_index(index)
    table = daily_shape_table(
        frame["y_true"], frame["y_pred_lear_price_only"], frame["market_day"].to_numpy()
    )
    scores = shape_scores(table)
    assert daily_spread_error(table) == pytest.approx(scores.spread_mae)
    assert within_day_spearman(table) == pytest.approx(scores.spearman_mean)


def test_mismatched_day_labels_are_refused_rather_than_broadcast():
    truth = _series([1.0, 2.0, 3.0])
    with pytest.raises(MetricError, match="day_labels"):
        daily_shape_table(truth, truth, np.array(["d1", "d2"]))


# ---------------------------------------------------------------------------
# The block resample
# ---------------------------------------------------------------------------


def test_every_replicate_draws_exactly_n_days():
    for block_days in (1, 7, 14, 30):
        counts = replicate_counts(
            BlockBootstrapSpec(n_days=90, n_replicates=200, block_days=block_days)
        )
        assert counts.shape == (200, 90)
        assert np.allclose(counts.sum(axis=1), 90)


def test_the_same_seed_gives_the_same_draw_and_a_different_seed_does_not():
    a = replicate_counts(BlockBootstrapSpec(n_days=40, n_replicates=50))
    b = replicate_counts(BlockBootstrapSpec(n_days=40, n_replicates=50))
    c = replicate_counts(BlockBootstrapSpec(n_days=40, n_replicates=50, seed=DEFAULT_SEED + 1))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_a_block_as_long_as_the_year_can_only_rotate_it_so_every_replicate_ties():
    """The analytic end of the ladder, and a real check on the wrap-around.

    With ``block_days == n_days`` a replicate is one circular block, i.e. a
    rotation of the whole year — so every day is drawn exactly once and a
    day-additive statistic is the point estimate in every replicate. If the
    wrap-around were wrong this would not hold.
    """
    spec = BlockBootstrapSpec(n_days=30, n_replicates=100, block_days=30)
    counts = replicate_counts(spec)
    assert np.all(counts == 1.0)
    values = np.arange(30.0) ** 2
    assert np.allclose(mean_replicates(values, counts), values.mean())


def test_the_identity_resample_recovers_the_point_estimate():
    counts = np.ones((3, 5))
    numerator = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    denominator = np.array([2.0, 2.0, 2.0, 2.0, 2.0])
    assert np.allclose(
        ratio_replicates(numerator, denominator, counts), numerator.sum() / denominator.sum()
    )


def test_a_reported_interval_is_centred_on_the_published_point_not_the_boot_mean():
    """``point`` is passed in, never re-derived from the replicates.

    A bootstrap mean is a different number from the statistic it is the
    bootstrap of, and reporting it as the point estimate would silently
    supersede C11's committed value.
    """
    rng = np.random.default_rng(3)
    counts = replicate_counts(BlockBootstrapSpec(n_days=60, n_replicates=400))
    values = rng.normal(5.0, 1.0, 60)
    interval = mean_interval(values, counts, BlockBootstrapSpec(n_days=60, n_replicates=400))
    assert interval.point == pytest.approx(values.mean())
    assert interval.ci_low < interval.point < interval.ci_high


def test_a_nan_day_is_refused_rather_than_poisoning_every_replicate_it_lands_in():
    counts = np.ones((2, 3))
    with pytest.raises(BootstrapError, match="non-finite"):
        mean_replicates(np.array([1.0, np.nan, 3.0]), counts)


def test_a_wrongly_shaped_column_is_refused():
    counts = np.ones((2, 3))
    with pytest.raises(BootstrapError, match="one value per day"):
        mean_replicates(np.array([1.0, 2.0]), counts)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_days": 1},
        {"n_days": 10, "block_days": 0},
        {"n_days": 10, "block_days": 11},
        {"n_days": 10, "n_replicates": 1},
        {"n_days": 10, "alpha": 0.0},
        {"n_days": 10, "alpha": 1.0},
    ],
)
def test_a_spec_that_cannot_produce_an_interval_is_refused(kwargs):
    with pytest.raises(BootstrapError):
        BlockBootstrapSpec(**kwargs)


def test_paired_replicates_must_line_up_before_they_are_differenced():
    spec = BlockBootstrapSpec(n_days=10, n_replicates=10)
    with pytest.raises(BootstrapError, match="same shape"):
        difference_interval(np.zeros(10), np.zeros(9), 0.0, spec)


def test_pairing_narrows_a_difference_relative_to_resampling_independently():
    """Why the draws are shared: two highly correlated arms differ by very little.

    Resampling them independently would attribute the year's common variation to
    the difference between them, which is exactly the variation a paired
    comparison is meant to remove.
    """
    rng = np.random.default_rng(11)
    common = rng.normal(0.0, 10.0, 120)
    left = common + rng.normal(0.0, 0.1, 120)
    right = common
    spec = BlockBootstrapSpec(n_days=120, n_replicates=2000)
    shared = replicate_counts(spec)
    other = replicate_counts(
        BlockBootstrapSpec(n_days=120, n_replicates=2000, seed=DEFAULT_SEED + 7)
    )
    paired = mean_replicates(left, shared) - mean_replicates(right, shared)
    unpaired = mean_replicates(left, shared) - mean_replicates(right, other)
    assert np.std(paired) < np.std(unpaired) / 10.0


# ---------------------------------------------------------------------------
# The null-band test: is it calibrated?
# ---------------------------------------------------------------------------


def test_the_band_test_does_not_cry_wolf_on_groups_that_are_really_identical():
    """Calibration. FINDING C12-A would be an artefact of this function otherwise.

    Eight groups drawn from one distribution have no real spread, so the share
    of null bands at least as wide as the observed one must be an ordinary
    p-value and not a small number. Checked over several draws so a single lucky
    seed cannot carry it.
    """
    rng = np.random.default_rng(5)
    spec = BlockBootstrapSpec(n_days=200, n_replicates=1500)
    counts = replicate_counts(spec)
    small = 0
    trials = 12
    for _ in range(trials):
        columns = [rng.normal(0.9, 0.05, 200) for _ in range(8)]
        point = np.array([c.mean() for c in columns])
        replicates = np.column_stack([mean_replicates(c, counts) for c in columns])
        if noise_only_spread(point, replicates)["p_value"] < 0.05:
            small += 1
    assert small <= 2, f"{small}/{trials} identical-group draws were called significant"


def test_the_band_test_finds_a_group_that_really_is_far_out():
    rng = np.random.default_rng(6)
    spec = BlockBootstrapSpec(n_days=200, n_replicates=1500)
    counts = replicate_counts(spec)
    columns = [rng.normal(0.9, 0.05, 200) for _ in range(7)]
    columns.append(rng.normal(0.6, 0.05, 200))
    point = np.array([c.mean() for c in columns])
    replicates = np.column_stack([mean_replicates(c, counts) for c in columns])
    report = noise_only_spread(point, replicates)
    assert report["p_value"] < 0.01
    assert report["between_over_within"] > 3.0


def test_the_band_test_refuses_a_single_group_and_a_shape_mismatch():
    with pytest.raises(BootstrapError, match="not a band"):
        noise_only_spread([0.5], np.zeros((10, 1)))
    with pytest.raises(BootstrapError, match="n_groups"):
        noise_only_spread([0.5, 0.6], np.zeros((10, 3)))


# ---------------------------------------------------------------------------
# spearman_rows
# ---------------------------------------------------------------------------


def test_row_wise_spearman_matches_the_single_series_implementation():
    rng = np.random.default_rng(13)
    x = rng.normal(size=(40, 9))
    y = rng.normal(size=(40, 9))
    rows = spearman_rows(x, y)
    for i in range(40):
        assert rows[i] == pytest.approx(
            spearman_rho(pd.Series(x[i]), pd.Series(y[i])), abs=1e-12
        )


def test_row_wise_spearman_handles_ties_and_a_flat_row():
    x = np.array([[1.0, 2.0, 2.0, 3.0], [5.0, 5.0, 5.0, 5.0]])
    y = np.array([[10.0, 20.0, 20.0, 30.0], [1.0, 2.0, 3.0, 4.0]])
    rows = spearman_rows(x, y)
    assert rows[0] == pytest.approx(1.0)
    assert math.isnan(rows[1])


def test_row_wise_spearman_refuses_fewer_than_three_items():
    with pytest.raises(BootstrapError, match="k>=3"):
        spearman_rows(np.zeros((4, 2)), np.zeros((4, 2)))


# ---------------------------------------------------------------------------
# The C12 run: structure and refusals
# ---------------------------------------------------------------------------


def test_the_honest_contrast_set_excludes_every_leaking_arm():
    """FINDING C9-C: an ``after_gate_closure`` arm is a measurement, not a model.

    The rank correlation of FINDING C12-D must not contain a comparison nobody
    could have traded, or it stops being a statement about model choice.
    """
    from backtest.run_c12_metrics import HONEST_CONTRASTS
    from backtest.run_c11_dispatch import CONTRASTS

    assert len(HONEST_CONTRASTS) == 5
    assert len(CONTRASTS) == 7
    assert not any("as_published" in t or "as_published" in b for t, b in HONEST_CONTRASTS)


def test_a_basis_restriction_can_only_narrow_never_extend():
    from backtest.run_c12_metrics import Basis, MetricsRunError

    basis = Basis(name="t", days=("d1", "d2", "d3"), n_replicates=20, seed=1)
    narrowed = basis.restricted(("d1", "d3"), 1)
    assert narrowed.shape == (20, 2)
    assert np.all(narrowed.sum(axis=1) <= 3)
    with pytest.raises(MetricsRunError, match="never extend"):
        basis.restricted(("d1", "d9"), 1)


def test_own_coverage_is_per_curve_and_cannot_be_asked_of_a_zone():
    """NOTE C10-01's two scopes do not mean the same kind of thing.

    ``common_hours`` is a property of the zone (the intersection of its curves'
    days); ``own_coverage`` is a property of each curve. Conflating them is how
    a ratio of sums ends up with a numerator and a denominator over different
    day sets.
    """
    from backtest.run_c12_metrics import MetricsRunError, basis_days

    with pytest.raises(MetricsRunError, match="per curve"):
        basis_days({}, "own_coverage")
    with pytest.raises(MetricsRunError, match="unknown scope"):
        basis_days({}, "all_days")


def test_the_c11_reproduction_check_can_actually_fail():
    """A check that cannot fail is decoration.

    Perturbing one capture ratio by 1e-6 — four orders of magnitude below
    anything this project reports — must still be caught, because the point of
    the check is that C12 recomputes C11's numbers rather than approximating
    them.
    """
    from backtest.run_c12_metrics import check_c11_reproduction
    from backtest.results_store import latest_results

    store = latest_results()
    c11 = store[(store["source_cycle"] == "C11") & (store["scope"] == "common_hours")]
    rows = c11[c11["metric"] == "capture_rolled_oracle_cash"]
    assert not rows.empty
    points = pd.DataFrame(
        [
            {
                "zone": r.zone,
                "curve": f"{r.model}_{r.exog_variant}",
                "scope": "common_hours",
                "model": r.model,
                "exog_variant": r.exog_variant,
                "vintage": r.vintage,
                "train_from": r.train_from,
                "n_days": 365,
                "capture_rolled_oracle_cash": float(r.value),
            }
            for r in rows.itertuples()
        ]
    )
    assert check_c11_reproduction(points, store)["checks"][0]["holds"]
    nudged = points.copy()
    nudged.loc[0, "capture_rolled_oracle_cash"] += 1e-6
    assert not check_c11_reproduction(nudged, store)["checks"][0]["holds"]


def test_the_oracle_gets_dispatch_metrics_and_no_forecast_error_metrics():
    """Perfect foresight has no error, so an MAE on it would be a zero that means
    nothing. The point-error columns are absent, not zero."""
    from backtest.run_c12_metrics import curve_days_for_zone, load_c11_daily, point_metrics

    daily = load_c11_daily()
    curves = curve_days_for_zone("IT-North", "B", "gas-dominated", daily, 1.0)
    oracle = curves["oracle"]
    assert not oracle.has_forecast_error
    block = point_metrics(oracle, tuple(oracle.frame.index), 1.0)
    assert block["capture_rolled_oracle_cash"] == pytest.approx(1.0)
    assert "mae_on_dispatched_hours" not in block
    assert "within_day_spearman_mean" not in block


def test_the_naive_floor_has_no_rmae_against_itself():
    from backtest.run_c12_metrics import curve_days_for_zone, load_c11_daily, rmae_point

    daily = load_c11_daily()
    curves = curve_days_for_zone("PL", "B", "coal-dominated", daily, 1.0)
    naive = curves["naive"]
    comparable = curves["lear_full_history"]
    days = tuple(comparable.frame.index)
    assert rmae_point(naive, naive, days) is None
    assert rmae_point(curves["oracle"], naive, days) is None
    ratio = rmae_point(comparable, naive, days)
    assert 0.0 < ratio < 1.0


def test_a_day_the_curve_did_not_dispatch_is_refused_not_reindexed():
    from backtest.run_c12_metrics import MetricsRunError, curve_days_for_zone, load_c11_daily

    daily = load_c11_daily()
    curves = curve_days_for_zone("ES", "A", "solar-dominated", daily, 1.0)
    arm = curves["lear_res_persistence"]
    absent = [d for d in curves["naive"].frame.index if d not in arm.frame.index]
    assert absent, "ES's res_* arms are expected to decline days the naive floor dispatches"
    with pytest.raises(MetricsRunError, match="did not dispatch"):
        arm.on([absent[0]])


def test_the_annualisation_reproduces_c11s_span_based_definition():
    """A declined day counts as a day the battery earned nothing.

    C11 annualised over the calendar span, not over the days dispatched, and
    C12's ``mean(cash) * annualisation`` must be the same number — otherwise the
    interval is around a near neighbour of the published figure.
    """
    from backtest.run_c12_metrics import curve_days_for_zone, load_c11_daily, point_metrics

    daily = load_c11_daily()
    curves = curve_days_for_zone("DE-LU", "A", "thermal-RES-mixed", daily, 1.0)
    curve = curves["lear_full_history"]
    days = tuple(curve.frame.index)
    block = point_metrics(curve, days, 1.0)
    frame = curve.on(days)
    assert block["span_days"] == 366
    assert block["n_days"] == 365
    assert block["dispatch_cash_eur_per_mw_year"] == pytest.approx(
        frame["cash"].sum() / 1.0 / 366 * 365.25, rel=1e-12
    )


# ---------------------------------------------------------------------------
# The findings, pinned against the artefacts this cycle committed
# ---------------------------------------------------------------------------

SUMMARY = RESULTS / "c12_metrics_summary.json"


def _summary() -> dict:
    with SUMMARY.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_the_committed_summary_reproduces_c11_before_any_interval_is_read():
    report = _summary()["c11_reproduction"]
    assert report["holds"], report
    assert report["n_checks"] == 7
    for check in report["checks"]:
        assert check.get("n_over_tolerance", 0) == 0, check
        assert check.get("n_unmatched_in_c11", 0) == 0, check


def test_finding_c12_a_the_capture_band_is_wider_than_noise_and_rmaes_is_not():
    """FINDING C11-A's inequality-of-bands claim, confirmed at every block length.

    The nine-zone capture band is further outside its noise-only distribution
    than any block length changes; rMAE's band is inside its own at every block
    length. The CV ratio's interval excludes 1, which is the interval on C11's
    "capture's CV is 3.0x rMAE's".
    """
    cross = _summary()["cross_zone"]
    for block in ("1", "7", "14"):
        block_all = cross[block]["all_zones"]
        assert block_all["capture_band_vs_noise"]["p_value"] < 0.01
        assert block_all["capture_band_vs_noise"]["between_over_within"] > 3.0
        assert block_all["rmae_band_vs_noise"]["p_value"] > 0.05
        assert block_all["rmae_band_vs_noise"]["between_over_within"] < 1.5
        ratio = block_all["cv_ratio_capture_over_rmae"]
        assert ratio["ci_low"] > 1.0, ratio


def test_finding_c12_b_the_eight_zone_band_is_not_established_at_the_daily_block():
    """The honest answer to NOTE C11-01 (i), and it is not a clean yes.

    With NO2 removed the capture band is 8.29pp and its noise-only p-value is
    0.078 at PLAN.md's literal daily block — outside 5%. It clears at the 7- and
    14-day blocks, so the conclusion depends on the block length, which is the
    definition of not established. C13's second year is the test.
    """
    cross = _summary()["cross_zone"]
    daily_block = cross["1"]["excluding_NO2"]
    assert daily_block["capture_band_pp"]["point"] == pytest.approx(8.29, abs=0.02)
    assert daily_block["capture_band_vs_noise"]["p_value"] > 0.05
    assert cross["7"]["excluding_NO2"]["capture_band_vs_noise"]["p_value"] < 0.05


def test_finding_c12_c_only_the_within_day_spearman_tracks_capture_across_zones():
    """The within-day rank correlation is the one point-forecast metric that does.

    Its cross-zone rank correlation with capture is +0.70 with an interval
    excluding zero and the sign a forecastability story predicts, at every block
    length and with or without NO2. Every other candidate — MAE, rMAE, the
    spread error, the spread bias — has an interval spanning zero, and rMAE's
    point estimate has the *wrong* sign, which is why C11 was right not to lean
    on it.
    """
    cross = _summary()["cross_zone"]
    for block in ("1", "7", "14"):
        for label in ("all_zones", "excluding_NO2"):
            metrics = cross[block][label]["forecast_metrics"]
            spearman = metrics["within_day_spearman_mean"]
            assert spearman["spearman_excludes_zero"], (block, label, spearman)
            assert spearman["spearman_has_expected_sign"]
            assert spearman["spearman_vs_capture"]["point"] > 0.4
            for other in (
                "mae_on_dispatched_hours",
                "rmae_vs_naive_on_dispatched_hours",
                "daily_spread_mae_eur_per_mwh",
                "daily_spread_bias_eur_per_mwh",
            ):
                assert not metrics[other]["spearman_excludes_zero"], (block, label, other)
    nine = cross["1"]["all_zones"]["forecast_metrics"]
    assert nine["within_day_spearman_mean"]["spearman_vs_capture"]["point"] == pytest.approx(0.70)
    assert nine["rmae_vs_naive_on_dispatched_hours"]["spearman_has_expected_sign"] is False


def test_finding_c12_d_capture_decides_far_fewer_contrasts_than_mae_or_spearman():
    """Why FINDING C11-D is "undetermined", not "contradicted".

    One of the fifteen honest capture deltas has an interval excluding zero,
    against seven for MAE and eight for the within-day Spearman, and the median
    capture delta is under half its own bootstrap standard deviation. A metric
    that cannot rank arms at this sample size cannot be shown to rank them
    differently from another metric either — and the rank-correlation interval
    says exactly that, spanning from a strong negative to a strong positive.
    """
    summary = _summary()
    decided = summary["decidability"]["1"]
    assert decided["n_honest_contrasts"] == 15
    assert decided["capture_delta_pp"]["n_excluding_zero"] == 1
    assert decided["mae_pct_gain"]["n_excluding_zero"] == 7
    assert decided["within_day_spearman_delta"]["n_excluding_zero"] == 8
    assert decided["capture_delta_pp"]["median_abs_point_over_boot_sd"] < 0.5
    assert decided["within_day_spearman_delta"]["median_abs_point_over_boot_sd"] > 2.0

    correlation = summary["mae_vs_capture"]["1"]
    assert correlation["n_comparisons"] == 15
    assert correlation["spearman"]["ci_low"] < -0.4
    assert correlation["spearman"]["ci_high"] > 0.4
    assert not correlation["spearman"]["excludes_zero"]

    # The ordering is not an artefact of the block length: capture decides
    # fewest, the Spearman most, at every rung of the ladder.
    for block in BLOCK_LADDER:
        rung = summary["decidability"][str(block)]
        assert (
            rung["capture_delta_pp"]["n_excluding_zero"]
            < rung["mae_pct_gain"]["n_excluding_zero"]
            <= rung["within_day_spearman_delta"]["n_excluding_zero"]
        ), (block, rung)
        assert not summary["mae_vs_capture"][str(block)]["spearman"]["excludes_zero"]


def test_finding_c12_e_the_gbm_exogenous_capture_gain_mostly_does_not_survive_a_ci():
    """NOTE C11-01 (iii), answered — and the answer is "one of three, conditionally".

    C11 answered NOTE C8-01 affirmatively on three point estimates (+0.35 /
    +2.04 / +2.71pp of capture in DE-LU / ES / NO2, under the GBM). Under a
    daily-block bootstrap:

    * **DE-LU** (+0.35pp) contains zero at every block length. Not established.
    * **NO2** (+2.71pp) contains zero at every block length, despite being the
      largest of the three — NO2's per-day capture is far the noisiest of the
      nine zones, so its interval is ~5pp wide. Not established.
    * **ES** (+2.04pp) contains zero at the daily block by a hair
      (``ci_low = -0.26``, with 4.2% of replicates at or below zero) and
      excludes it at the 7- and 14-day blocks. Established only conditionally
      on the block length, which is the one place in this cycle where a
      one-sided reading matters: NOTE C8-01 asked a directional question, and
      one-sided the daily block clears 5%.

    So the affirmative answer survives for ES and not for the other two. This
    test pins all three so that a later cycle cannot restate the C11 table as
    though a CI had confirmed it.
    """
    frame = pd.read_csv(RESULTS / "c12_contrasts.csv")
    gain = frame[
        (frame["treatment"] == "gbm_res_persistence")
        & (frame["baseline"] == "gbm_price_only")
    ]
    assert len(gain) == 3 * len(BLOCK_LADDER)
    assert set(gain["zone"]) == {"DE-LU", "ES", "NO2"}
    by_key = gain.set_index(["zone", "block_days"])

    for zone in ("DE-LU", "NO2"):
        for block in BLOCK_LADDER:
            row = by_key.loc[(zone, block)]
            assert not bool(row["capture_delta_pp_excludes_zero"]), (zone, block, row)
            assert row["capture_delta_pp_ci_low"] < 0.0 < row["capture_delta_pp_ci_high"]

    es_daily = by_key.loc[("ES", 1)]
    assert not bool(es_daily["capture_delta_pp_excludes_zero"])
    assert es_daily["capture_delta_pp_ci_low"] == pytest.approx(-0.26, abs=0.05)
    assert es_daily["capture_delta_pp_prob_le_zero"] < 0.05
    for block in (7, 14):
        assert bool(by_key.loc[("ES", block)]["capture_delta_pp_excludes_zero"])

    headline = by_key.xs(1, level="block_days")
    assert headline.loc["DE-LU", "capture_delta_pp"] == pytest.approx(0.352, abs=0.01)
    assert headline.loc["ES", "capture_delta_pp"] == pytest.approx(2.039, abs=0.01)
    assert headline.loc["NO2", "capture_delta_pp"] == pytest.approx(2.714, abs=0.01)


def test_the_one_honest_contrast_that_is_established_at_every_block_length():
    """ES: the booster captures *less* than the LASSO, price-only, honest vintage.

    Of the fifteen honest contrasts this is the only capture delta whose
    interval excludes zero at all three block lengths — and it runs against the
    booster, in the zone where the booster also has the lower MAE. It is the one
    piece of FINDING C11-D's claim (ii) that a single validation year does
    establish.
    """
    frame = pd.read_csv(RESULTS / "c12_contrasts.csv")
    honest = frame[frame["honest"]]
    always = (
        honest.groupby(["zone", "treatment", "baseline"])["capture_delta_pp_excludes_zero"]
        .all()
    )
    established = sorted(always[always].index.tolist())
    assert established == [("ES", "gbm_price_only", "lear_price_only")]
    row = honest[
        (honest["zone"] == "ES")
        & (honest["treatment"] == "gbm_price_only")
        & (honest["block_days"] == 1)
    ].iloc[0]
    assert row["capture_delta_pp"] == pytest.approx(-2.221, abs=0.01)
    assert row["capture_delta_pp_ci_high"] < 0.0


def test_every_zone_under_predicts_the_daily_spread():
    """A systematic finding, not a per-zone curiosity.

    The spread bias is negative in all nine zones on the comparable arm: the
    forecast day is flatter than the day that arrives, by 8-24 EUR/MWh. That is
    the regularised model shrinking towards the mean, and it biases a battery
    towards under-trading rather than over-trading.
    """
    frame = pd.read_csv(RESULTS / "c12_metrics_table.csv")
    comparable = frame[
        (frame["curve"] == "lear_full_history") & (frame["scope"] == "own_coverage")
    ]
    assert len(comparable) == 9
    assert (comparable["daily_spread_bias_eur_per_mwh"] < 0).all()
    assert comparable["daily_spread_bias_eur_per_mwh"].max() < -5.0


def test_the_sealed_holdout_guard_was_armed_before_and_after_the_run():
    guard = _summary()["holdout_guard"]
    for phase in ("before", "after"):
        assert guard[phase]["sealed_years"] == [2025]
        assert guard[phase]["holdout_is_unsealed"] is False
    assert _summary()["evaluation_years"] == [2024]


def test_no_c12_artefact_mentions_a_sealed_year_as_a_market_day():
    frame = pd.read_csv(RESULTS / "c12_daily_metrics_2024.csv.gz", dtype={"market_day": str})
    assert frame["market_day"].str[:4].unique().tolist() == ["2024"]
    assert len(frame) == 16440
