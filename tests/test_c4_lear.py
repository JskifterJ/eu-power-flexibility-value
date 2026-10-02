"""C4 tests: the LEAR model — per-hour LASSO, in-fold scaling, in-fold selection.

All synthetic and offline; no network, no cached file, no sealed year.

The tests that matter most here are not the ones that check LEAR forecasts well.
They are the ones that check it cannot forecast well *for the wrong reason*:

* ``test_a_rows_prediction_does_not_depend_on_the_rest_of_the_test_set`` and
  ``test_scaling_is_frozen_at_fit_time`` — the in-fold-scaling requirement, as a
  behavioural assertion. Fitting a scaler on train+test is the classic invisible
  leak: nothing in the code looks like a future price, and the test set still
  votes on the fit.
* ``test_predictions_are_unchanged_when_the_test_target_is_destroyed`` — the
  model reads ``test.features`` and nothing else.
* ``test_training_rows_with_a_missing_cell_are_dropped_not_imputed`` and
  ``test_a_test_row_with_a_missing_cell_is_declined`` — the NaN policy C3 asked
  for, pinned down so a later cycle cannot quietly start imputing.
* ``test_the_harness_refuses_to_run_lear_on_an_injected_future_feature`` with
  ``test_a_leading_feature_would_be_worth_a_lot_to_lear`` — the guard is what
  stands between the model and a leak, and the second test measures how much
  the guard is worth.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LassoCV, LassoLarsIC
from sklearn.model_selection import TimeSeriesSplit

from backtest import diagnostics as dx
from backtest.metrics import score, skill_score
from backtest.walk_forward import WalkForwardSpec, evaluation_days, run_walk_forward
from forecast.features import build_features
from forecast.leakage import LeakageError
from forecast.lear import (
    LearModel,
    LearSpec,
    _asinh,
    _inverse_asinh,
    _vst_params,
    lear_factory,
)
from forecast.models import Model, ModelError, NaiveLastWeek
from tests.test_c3_timing_features import ZONE, _random_walk_prices, _utc_index, _weekly_prices

SPEC = WalkForwardSpec(refit_every_days=14, min_train_days=200)
SMALL = LearSpec(min_fit_rows=30)


@pytest.fixture(scope="module")
def matrix():
    """Two years of synthetic week-periodic prices, built through the real pipeline."""
    return build_features(_weekly_prices(_utc_index("2021-01-01", 730)), ZONE)


@pytest.fixture(scope="module")
def split(matrix):
    """One year of training, the following fortnight as a test block."""
    train = matrix.subset(
        (
            (matrix.market_day >= dt.date(2021, 1, 1))
            & (matrix.market_day <= dt.date(2021, 12, 31))
        ).to_numpy()
    )
    test = matrix.select_days(
        [dt.date(2022, 1, 1) + dt.timedelta(days=i) for i in range(14)]
    )
    return train, test


@pytest.fixture(scope="module")
def fitted(split):
    train, _ = split
    return LearModel(SMALL).fit(train)


@pytest.fixture(scope="module")
def eval_days(matrix):
    return evaluation_days(matrix, [2022])


# ---------------------------------------------------------------------------
# Shape of the thing
# ---------------------------------------------------------------------------


def test_lear_satisfies_the_model_protocol():
    assert isinstance(LearModel(), Model)


def test_predict_before_fit_raises(split):
    _, test = split
    with pytest.raises(ModelError, match="before fit"):
        LearModel().predict(test)


def test_fit_report_before_fit_raises():
    with pytest.raises(ModelError, match="before fit"):
        LearModel().fit_report()


def test_spec_rejects_unknown_choices():
    for kwargs, match in (
        ({"selector": "ridge"}, "selector"),
        ({"hour_key": "market"}, "hour_key"),
        ({"nan_policy": "ffill"}, "nan_policy"),
        ({"cv_splits": 1}, "cv_splits"),
        ({"min_fit_rows": 1}, "min_fit_rows"),
    ):
        with pytest.raises(ModelError, match=match):
            LearSpec(**kwargs)


def test_factory_builds_a_fresh_model_per_fold():
    """The harness calls the factory once per fold; a shared model would carry state."""
    factory = lear_factory(SMALL)
    first, second = factory(), factory()
    assert first is not second
    assert first.spec is second.spec  # the *spec* is shared and frozen; the model is not


def test_one_lasso_per_delivery_hour(fitted):
    assert sorted(fitted.models_) == list(range(24))
    assert fitted.fit_report()["n_hours"] == 24


def test_the_partition_column_is_not_in_the_design(fitted):
    """Constant inside an hour-model by construction, so it carries nothing there."""
    for hour, model in fitted.models_.items():
        assert "hour_of_day_local" not in model.encoding.source_columns
        assert all("hour_of_day_local" not in c for c in model.encoding.design_columns)


def test_hour_key_utc_partitions_by_the_other_clock(split):
    train, test = split
    model = LearModel(LearSpec(min_fit_rows=30, hour_key="utc")).fit(train)
    assert sorted(model.models_) == list(range(24))
    for hour_model in model.models_.values():
        assert "hour_of_day_utc" not in hour_model.encoding.source_columns
        assert "hour_of_day_local" in hour_model.encoding.categorical
    assert model.predict(test).notna().any()


def test_missing_partition_column_is_a_loud_error(split):
    train, _ = split
    stripped = train.with_features(train.features.drop(columns=["hour_of_day_local"]))
    with pytest.raises(ModelError, match="hour_of_day_local"):
        LearModel(SMALL).fit(stripped)


def test_every_selector_fits_and_cv_is_time_ordered(split):
    train, test = split
    for selector in ("aic", "bic", "cv"):
        model = LearModel(LearSpec(min_fit_rows=30, selector=selector))
        estimator = model._estimator()
        if selector == "cv":
            assert isinstance(estimator, LassoCV)
            # A shuffled K-fold inside the training window would let a later day
            # pick the penalty for an earlier one.
            assert isinstance(estimator.cv, TimeSeriesSplit)
        else:
            assert isinstance(estimator, LassoLarsIC)
            assert estimator.criterion == selector
        predictions = model.fit(train).predict(test)
        assert predictions.notna().all()
        assert model.name == f"lear_{selector}"


# ---------------------------------------------------------------------------
# The variance-stabilising transform
# ---------------------------------------------------------------------------


def test_asinh_round_trip_is_exact():
    values = np.array([-500.0, -17.3, 0.0, 1.0, 42.0, 871.0, 4000.0])
    centre, scale, degenerate = _vst_params(values)
    assert not degenerate
    recovered = _inverse_asinh(_asinh(values, centre, scale), centre, scale)
    assert np.allclose(recovered, values, rtol=1e-10, atol=1e-8)


def test_vst_params_fall_back_when_the_mad_is_zero():
    """More than half the sample on one value gives MAD 0 — divide by nothing."""
    mostly_flat = np.array([50.0] * 10 + [10.0, 90.0])
    centre, scale, degenerate = _vst_params(mostly_flat)
    assert centre == 50.0
    assert scale == pytest.approx(float(np.std(mostly_flat)))
    assert degenerate

    constant = np.full(8, 7.0)
    centre, scale, degenerate = _vst_params(constant)
    assert (centre, scale, degenerate) == (7.0, 1.0, True)

    empty = np.array([np.nan, np.nan])
    assert _vst_params(empty) == (0.0, 1.0, True)


def test_vst_handles_negative_prices(split):
    """A log is unavailable on this market; asinh must simply work through zero."""
    train, test = split
    shifted_prices = train.target - 120.0
    assert (shifted_prices < 0).any()
    negative = train.with_target(shifted_prices)
    model = LearModel(SMALL).fit(negative)
    assert np.isfinite(model.predict(test)).all()
    assert model.fit_report()["hours"][0]["target_centre"] < 0


def test_untransformed_fit_is_available_and_differs(split):
    train, test = split
    with_vst = LearModel(SMALL).fit(train).predict(test)
    without = LearModel(LearSpec(min_fit_rows=30, vst=False)).fit(train).predict(test)
    assert not np.allclose(with_vst.to_numpy(), without.to_numpy())


# ---------------------------------------------------------------------------
# In-fold only: the test set must not vote on the fit
# ---------------------------------------------------------------------------


def test_a_rows_prediction_does_not_depend_on_the_rest_of_the_test_set(fitted, split):
    """Predicting one row alone must give exactly what predicting the block gave.

    If any scaling, centring or median were computed over the frame handed to
    ``predict``, these two numbers would differ — which is how a scaler fitted on
    train+test betrays itself.
    """
    _, test = split
    block = fitted.predict(test)
    for position in (0, 7, 100, len(test.index) - 1):
        single = test.subset(np.arange(len(test.index)) == position)
        assert fitted.predict(single).iloc[0] == pytest.approx(
            block.iloc[position], rel=0, abs=1e-12
        )


def test_scaling_is_frozen_at_fit_time(fitted, split):
    """Corrupting other test rows cannot move a row's prediction."""
    _, test = split
    before = fitted.predict(test)
    corrupted = test.features.copy()
    corrupted.iloc[1:, :4] = corrupted.iloc[1:, :4] * 1_000.0 + 5_000.0
    after = fitted.predict(test.with_features(corrupted))
    assert after.iloc[0] == pytest.approx(before.iloc[0], rel=0, abs=1e-12)
    assert not np.allclose(after.iloc[1:], before.iloc[1:])


def test_predictions_are_unchanged_when_the_test_target_is_destroyed(fitted, split):
    """``predict`` reads ``test.features``; the realised price is none of its business."""
    _, test = split
    before = fitted.predict(test)
    blinded = test.with_target(pd.Series(np.nan, index=test.index, name=test.target.name))
    pd.testing.assert_series_equal(fitted.predict(blinded), before)


def test_fitting_on_more_history_changes_the_fit(matrix, split):
    """Sanity check on the previous two: the fit *is* sensitive to the training data."""
    train, test = split
    shorter = train.subset((train.market_day >= dt.date(2021, 7, 1)).to_numpy())
    assert not np.allclose(
        LearModel(SMALL).fit(train).predict(test).to_numpy(),
        LearModel(SMALL).fit(shorter).predict(test).to_numpy(),
    )


def test_the_fit_is_deterministic(split):
    train, test = split
    first = LearModel(SMALL).fit(train).predict(test)
    second = LearModel(SMALL).fit(train).predict(test)
    pd.testing.assert_series_equal(first, second)


# ---------------------------------------------------------------------------
# The NaN policy (the open question C3 handed to C4)
# ---------------------------------------------------------------------------


def test_training_rows_with_a_missing_cell_are_dropped_not_imputed(split):
    """Listwise deletion in the fit, and the count is reported, not swallowed."""
    train, test = split
    # Well past the lag warm-up, where these cells are genuinely present —
    # poking a hole in an already-NaN cell would prove nothing.
    rows = [5_000, 5_001, 5_002]
    holed = train.features.copy()
    assert holed.iloc[rows, 0].notna().all()
    holed.iloc[rows, 0] = np.nan
    with_holes = train.with_features(holed)

    model = LearModel(SMALL).fit(with_holes)
    report = model.fit_report()
    baseline = LearModel(SMALL).fit(train).fit_report()
    assert report["n_train_rows_dropped_nan"] == baseline["n_train_rows_dropped_nan"] + 3
    assert report["n_train_rows_fitted"] == baseline["n_train_rows_fitted"] - 3
    assert report["train_drop_fraction"] > baseline["train_drop_fraction"]

    # Dropping the row must be *equivalent* to the row never being there — i.e.
    # nothing was imputed into it behind the report's back.
    keep = np.ones(len(train.index), dtype=bool)
    keep[rows] = False
    physically_removed = LearModel(SMALL).fit(train.subset(keep))
    for hour in rows:
        hour_of = int(train.features["hour_of_day_local"].iloc[hour])
        assert np.allclose(
            model.models_[hour_of].coef, physically_removed.models_[hour_of].coef
        )


def test_a_test_row_with_a_missing_cell_is_declined(fitted, split):
    """No prediction, counted as missing — never a guessed number."""
    _, test = split
    holed = test.features.copy()
    holed.iloc[3, 2] = np.nan
    predictions = fitted.predict(test.with_features(holed))
    assert np.isnan(predictions.iloc[3])
    assert predictions.drop(predictions.index[3]).notna().all()
    assert fitted.fit_report()["n_predict_declined_nan"] == 1

    # And the metrics layer must charge the model for declining, not reward it
    # with a smaller denominator.
    scores = score(test.target, predictions)
    assert scores.n == len(test.index)
    assert scores.n_missing_prediction == 1
    assert scores.n_scored == len(test.index) - 1
    assert scores.coverage < 1.0


def test_the_impute_policy_is_available_and_reports_what_it_filled(split):
    train, test = split
    holed = test.features.copy()
    holed.iloc[3, 2] = np.nan
    model = LearModel(LearSpec(min_fit_rows=30, nan_policy="impute")).fit(train)
    predictions = model.predict(test.with_features(holed))
    assert predictions.notna().all()
    report = model.fit_report()
    assert report["n_predict_imputed_cells"] == 1
    assert report["n_predict_declined_nan"] == 0


def test_a_missing_calendar_cell_is_missing_not_a_zero_indicator(fitted, split):
    """One-hot encoding a NaN would silently make it the reference level."""
    _, test = split
    holed = test.features.copy()
    holed["day_of_week"] = holed["day_of_week"].astype("float64")
    holed.iloc[9, holed.columns.get_loc("day_of_week")] = np.nan
    predictions = fitted.predict(test.with_features(holed))
    assert np.isnan(predictions.iloc[9])


def test_an_unknown_delivery_hour_is_declined_not_guessed(split):
    """A clock the training window never showed gets no model and no number."""
    train, test = split
    hours = train.features["hour_of_day_local"].to_numpy()
    model = LearModel(SMALL).fit(train.subset(hours != 4))
    predictions = model.predict(test)
    missing = test.features["hour_of_day_local"].to_numpy() == 4
    assert np.isnan(predictions.to_numpy()[missing]).all()
    assert predictions.to_numpy()[~missing].size and np.isfinite(
        predictions.to_numpy()[~missing]
    ).all()
    assert model.fit_report()["n_predict_unknown_hour"] == int(missing.sum())


def test_a_thin_delivery_hour_raises_rather_than_being_fitted(split):
    """Below ``min_fit_rows`` the honest answer is "look at the data", not a fit."""
    train, _ = split
    with pytest.raises(ModelError, match="min_fit_rows"):
        LearModel(LearSpec(min_fit_rows=10_000)).fit(train)


def test_constant_design_columns_are_dropped(split):
    train, test = split
    flattened = train.features.copy()
    flattened["price_lag_72h"] = 55.0
    model = LearModel(SMALL).fit(train.with_features(flattened))
    assert model.fit_report()["hours"][0]["n_dropped_constant"] >= 1
    assert model.predict(test).notna().all()


def test_a_single_month_window_still_fits(matrix):
    """With one month in the window the month block is empty, not a constant column."""
    january = matrix.subset(
        (
            (matrix.market_day >= dt.date(2021, 1, 8))
            & (matrix.market_day <= dt.date(2021, 1, 31))
        ).to_numpy()
    )
    february = matrix.select_days(
        [dt.date(2021, 2, 1) + dt.timedelta(days=i) for i in range(3)]
    )
    model = LearModel(LearSpec(min_fit_rows=20)).fit(january)
    for hour_model in model.models_.values():
        assert hour_model.encoding.levels["month"] == ()
    # February is an unseen month; with no month dummies that is not an unseen
    # *category*, it simply has no month term — and the model must still predict.
    assert model.predict(february).notna().all()


def test_an_unseen_category_is_counted(split):
    train, test = split
    model = LearModel(SMALL).fit(train)
    odd = test.features.copy()
    odd.iloc[0, odd.columns.get_loc("month")] = 99
    model.predict(test.with_features(odd))
    assert model.fit_report()["n_predict_unseen_category_rows"] == 1


# ---------------------------------------------------------------------------
# Does it actually forecast?
# ---------------------------------------------------------------------------


def test_lear_beats_the_naive_floor_on_the_synthetic_series(matrix, eval_days):
    lear = run_walk_forward(matrix, lear_factory(SMALL), eval_days, SPEC)
    naive = run_walk_forward(matrix, NaiveLastWeek, eval_days, SPEC)
    lear_mae = score(lear.y_true, lear.y_pred).mae
    naive_mae = score(naive.y_true, naive.y_pred).mae
    assert lear_mae < naive_mae, f"LEAR {lear_mae:.3f} did not beat naive {naive_mae:.3f}"


def test_lear_declines_exactly_the_hours_whose_features_have_a_hole(matrix, eval_days):
    """Coverage is the mask's doing, not the model's mood.

    Over a full evaluation year the only hours LEAR leaves unpredicted must be
    the ones whose design really has a missing cell — which on this zone means
    the autumn DST hour whose 24-hour lag the gate-closure mask had to blank
    (FINDING C3-A). Anything else unpredicted would be the model quietly giving
    up somewhere.
    """
    result = run_walk_forward(matrix, lear_factory(SMALL), eval_days, SPEC)
    assert result.predictions.index.is_unique
    assert not result.skipped_days

    evaluated = matrix.subset(matrix.index.isin(result.predictions.index))
    holed = evaluated.features.isna().any(axis=1)
    declined = result.predictions["y_pred"].isna()
    assert declined.sum() > 0, "expected at least the masked autumn-DST hour"
    pd.testing.assert_series_equal(
        declined, holed, check_names=False, check_freq=False
    )


def test_target_permutation_destroys_lear_skill(matrix, eval_days):
    """PLAN.md assertion (iii), re-run on the real model rather than the floor."""
    experiment = dx.target_permutation_experiment(
        matrix, lear_factory(SMALL), eval_days, SPEC, seed=4, mode="hours"
    )
    assert experiment.real_skill > 0.0
    assert experiment.permuted_skill <= 0.0
    assert experiment.destroys_skill()


# ---------------------------------------------------------------------------
# What the guard is worth
# ---------------------------------------------------------------------------


def test_the_harness_refuses_to_run_lear_on_an_injected_future_feature(matrix, eval_days):
    injected = dx.inject_future_feature(matrix, lead_hours=24, declare=True)
    with pytest.raises(LeakageError, match="after_gate_closure"):
        run_walk_forward(injected, lear_factory(SMALL), eval_days, SPEC)

    smuggled = dx.inject_future_feature(matrix, lead_hours=24, declare=False)
    with pytest.raises(LeakageError, match="undeclared"):
        run_walk_forward(smuggled, lear_factory(SMALL), eval_days, SPEC)


def test_a_leading_feature_would_be_worth_a_lot_to_lear():
    """Measured on a persistence-dominated series, with the guard switched off.

    This is the number the guard protects: a linear model handed a price from
    after gate closure simply uses it. The run is knowingly dishonest and exists
    only to be measured — hence ``check_leakage=False``, which real runs never
    pass.

    The bound is 0.8, not the 0.5 the naive floor showed in C3, and the
    difference is the point. The naive baseline had only the *week-old* price,
    so a price 24 hours ahead replaced a week of random-walk drift with a day of
    it — a factor of about sqrt(7). LEAR already holds the price 24 hours
    *back*, so the leading feature is a second observation the same distance
    away on the other side: averaging two symmetric observations cuts the error
    by about sqrt(2), i.e. roughly 30%. A leak is worth less to a model that was
    already using everything legal — which is an argument for the guard, not
    against it, because 30% of MAE is still the whole gap between a good model
    and a mediocre one.
    """
    series = build_features(_random_walk_prices(_utc_index("2021-01-01", 730)), ZONE)
    days = evaluation_days(series, [2022])
    honest = run_walk_forward(series, lear_factory(SMALL), days, SPEC)
    leaking = run_walk_forward(
        dx.inject_future_feature(series, lead_hours=24, declare=True),
        lear_factory(SMALL),
        days,
        SPEC,
        check_leakage=False,
    )
    honest_mae = score(honest.y_true, honest.y_pred).mae
    leaking_mae = score(leaking.y_true, leaking.y_pred).mae
    assert leaking_mae < 0.8 * honest_mae, (honest_mae, leaking_mae)


# ---------------------------------------------------------------------------
# FINDING C4-A — why the permutation probe reads "destroys_skill: False"
# ---------------------------------------------------------------------------


def _spiky_prices(index: pd.DatetimeIndex, seed: int = 23) -> pd.DataFrame:
    """A week-periodic series with a heavy right tail, like a real crisis year.

    Calibrated to roughly DE-LU 2019-2024's skew (mean ~1.45x median), which is
    what makes the mean/median gap large enough to see. The ordinary synthetic
    series in these tests is near-symmetric, so the contamination FINDING C4-A
    describes is invisible on it — which is precisely why it was not noticed
    until LEAR ran on real prices.
    """
    from data.energy_charts import PRICE_COLUMN

    base = _weekly_prices(index, seed=seed)[PRICE_COLUMN].to_numpy()
    rng = np.random.default_rng(seed)
    spikes = (rng.random(len(index)) < 0.03) * rng.exponential(1000.0, size=len(index))
    return pd.DataFrame({PRICE_COLUMN: base + spikes}, index=index)


def test_train_median_baseline_predicts_the_training_median(split):
    from forecast.models import TrainMedianBaseline

    train, test = split
    model = TrainMedianBaseline().fit(train)
    predictions = model.predict(test)
    assert predictions.unique().tolist() == [pytest.approx(float(train.target.median()))]
    assert predictions.index.equals(test.index)
    assert predictions.name == "train_median"

    with pytest.raises(ModelError, match="before fit"):
        TrainMedianBaseline().predict(test)


def test_a_mean_reference_hands_free_skill_to_a_median_like_model():
    """FINDING C4-A, as a regression test on a deliberately skewed series.

    PLAN.md assertion (iii) asks whether shuffling the target destroys the
    model's skill. Scored by MAE against a train-*mean* baseline, the answer is
    contaminated: MAE is minimised by the median, so on a right-skewed price
    distribution a constant at the training median already beats a constant at
    the training mean. LEAR is a LASSO fitted in asinh space and mapped back
    through ``sinh`` — a median-like estimator — so it collects that margin
    before it has learned anything.

    This test pins all three halves of the diagnosis:

    1. against the mean reference, the permuted model scores *positively* —
       which is what makes ``destroys_skill()`` read False;
    2. a zero-information constant at the training median earns at least as
       much, so the margin is not the model's;
    3. against the median reference the permuted model's skill is negative,
       while the honest model's stays clearly positive. Shuffling the target
       did destroy every bit of conditional skill.
    """
    from forecast.models import TrainMedianBaseline

    skewed = build_features(_spiky_prices(_utc_index("2021-01-01", 730)), ZONE)
    assert float(skewed.target.mean()) > 1.3 * float(skewed.target.median())
    days = evaluation_days(skewed, [2022])
    factory = lear_factory(SMALL)

    experiment = dx.target_permutation_experiment(
        skewed, factory, days, SPEC, seed=5, mode="hours"
    )
    assert experiment.real_skill > 0.0
    # (1) the contamination itself
    assert experiment.permuted_skill > 0.0
    assert not experiment.destroys_skill()

    permuted = dx.permute_target(skewed, 5, "hours")
    scores = {}
    for label, candidate in (("real", skewed), ("permuted", permuted)):
        model_run = run_walk_forward(candidate, factory, days, SPEC)
        median_run = run_walk_forward(candidate, TrainMedianBaseline, days, SPEC)
        scores[label] = {
            "model": score(model_run.y_true, model_run.y_pred).mae,
            "median": score(median_run.y_true, median_run.y_pred).mae,
            "skill_vs_median": skill_score(
                model_run.y_true, model_run.y_pred, median_run.y_pred
            ),
        }

    # (2) a constant that knows nothing collects the margin too
    assert scores["permuted"]["model"] >= scores["permuted"]["median"]
    # (3) re-based on the median, the permuted model has negative skill and the
    # honest one keeps real skill
    assert scores["permuted"]["skill_vs_median"] <= 0.0
    assert scores["real"]["skill_vs_median"] > 0.1
