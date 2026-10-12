"""C9 tests: the gradient-boosted model — one fixed config, in-fold early stopping.

All synthetic and offline; no network, no cached file, no sealed year.

PLAN.md C9's restriction ("one fixed LightGBM config, in-fold early stopping, no
hyperparameter search across cycles") is a rule about what *future cycles* may
do, so most of these tests are tripwires aimed forward rather than checks on
today's arithmetic:

* ``test_the_committed_config_is_exactly_what_plan_md_froze`` and
  ``test_the_fingerprint_changes_when_any_knob_changes`` — the config, pinned to
  literals. A later cycle that nudges ``num_leaves`` after seeing a 2024 number
  cannot do it silently; it has to edit a test, which CLAUDE.md makes a
  flag-and-stop event.
* ``test_early_stopping_uses_only_training_days`` and
  ``test_the_stopping_set_is_the_tail_of_the_window``— early stopping is the one
  quantity this model chooses per fold, so where it chooses it from is the only
  place a fold could look forward.
* ``test_predictions_are_unchanged_when_the_test_target_is_destroyed`` and
  ``test_a_rows_prediction_does_not_depend_on_the_rest_of_the_test_set`` — the
  model reads ``test.features`` and nothing else, and no part of the fit is
  recomputed at predict time.
* ``test_the_harness_refuses_to_run_the_gbm_on_an_injected_future_feature`` with
  ``test_a_leading_feature_would_be_worth_a_lot_to_the_gbm`` — the guard is what
  stands between the booster and a leak, and the second test measures what the
  guard is worth so it is defending a quantity rather than a principle.
* ``test_the_gbm_cannot_be_evaluated_against_a_sealed_year`` — the booster
  inherits the holdout refusal like every other model.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backtest import diagnostics as dx
from backtest.metrics import score, skill_score
from backtest.walk_forward import (
    WalkForwardError,
    WalkForwardSpec,
    evaluation_days,
    run_walk_forward,
)
from forecast.features import build_features
from forecast.gbm import (
    CATEGORICAL_FEATURES,
    GbmModel,
    GbmSpec,
    early_stopping_split,
    gbm_factory,
)
from forecast.leakage import LeakageError
from forecast.lear import _asinh, _inverse_asinh, _vst_params
from forecast.models import Model, ModelError, NaiveLastWeek, TrainMedianBaseline
from tests.test_c3_timing_features import ZONE, _random_walk_prices, _utc_index, _weekly_prices

#: A small spec for the synthetic fixtures: the committed one needs 2 000 rows
#: and 2 000 boosting rounds, which a 730-day toy series cannot usefully feed.
#: Everything these tests assert about *behaviour* is config-independent; the
#: committed values themselves are pinned by the config tests below, which do not
#: fit anything.
SMALL = GbmSpec(
    early_stopping_days=60,
    min_fit_rows=100,
    num_boost_round=600,
    early_stopping_rounds=15,
    num_threads=1,
)
SPEC = WalkForwardSpec(refit_every_days=14, min_train_days=200)


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
    return GbmModel(SMALL).fit(train)


@pytest.fixture(scope="module")
def eval_days(matrix):
    return evaluation_days(matrix, [2022])


# ---------------------------------------------------------------------------
# Shape of the thing
# ---------------------------------------------------------------------------


def test_gbm_satisfies_the_model_protocol():
    assert isinstance(GbmModel(), Model)


def test_predict_before_fit_raises(split):
    _, test = split
    with pytest.raises(ModelError, match="before fit"):
        GbmModel().predict(test)


def test_fit_report_before_fit_raises():
    with pytest.raises(ModelError, match="before fit"):
        GbmModel().fit_report()


def test_feature_importance_before_fit_raises():
    with pytest.raises(ModelError, match="before fit"):
        GbmModel().feature_importance()


def test_spec_rejects_unknown_choices():
    for kwargs, match in (
        ({"nan_policy": "ffill"}, "nan_policy"),
        ({"early_stopping_days": 0}, "early_stopping_days"),
        ({"early_stopping_rounds": 0}, "early_stopping_rounds"),
        ({"num_boost_round": 0}, "num_boost_round"),
        ({"min_fit_rows": 0}, "min_fit_rows"),
        ({"feature_fraction": 0.0}, "feature_fraction"),
        ({"bagging_fraction": 1.5}, "bagging_fraction"),
    ):
        with pytest.raises(ModelError, match=match):
            GbmSpec(**kwargs)


def test_factory_builds_a_fresh_model_per_fold():
    """The harness calls the factory once per fold; a shared model would carry state."""
    factory = gbm_factory(SMALL)
    first, second = factory(), factory()
    assert first is not second
    assert first.booster_ is None and second.booster_ is None


def test_factory_name_reaches_the_prediction_series(split):
    train, test = split
    model = gbm_factory(SMALL, name="gbm_arm_x")().fit(train)
    assert model.predict(test).name == "gbm_arm_x"


# ---------------------------------------------------------------------------
# PLAN.md's restriction, as tripwires
# ---------------------------------------------------------------------------


def test_the_committed_config_is_exactly_what_plan_md_froze():
    """The one fixed config, as literals.

    PLAN.md C9: "one fixed LightGBM config ... no hyperparameter search across
    cycles". A cycle that tunes a knob against a visible 2024 metric has to edit
    this test to get green, and CLAUDE.md makes editing a test a flag-and-stop
    event. That is the whole mechanism: the restriction cannot be enforced by
    good intentions across sessions with no memory of each other.
    """
    spec = GbmSpec()
    assert spec.objective == "regression"
    assert spec.learning_rate == 0.05
    assert spec.num_leaves == 31
    assert spec.min_data_in_leaf == 20
    assert spec.feature_fraction == 0.9
    assert spec.bagging_fraction == 0.9
    assert spec.bagging_freq == 1
    assert spec.lambda_l1 == 0.0
    assert spec.lambda_l2 == 1.0
    assert spec.num_boost_round == 2000
    assert spec.early_stopping_rounds == 50
    assert spec.early_stopping_days == 90
    assert spec.refit_on_full_window is True
    assert spec.nan_policy == "native"
    assert spec.vst is True
    assert spec.seed == 20260101
    assert spec.deterministic is True


def test_the_booster_params_are_fully_seeded_and_deterministic():
    """A run must be reproducible on another machine, not just on this one."""
    params = GbmSpec().booster_params()
    for key in ("seed", "bagging_seed", "feature_fraction_seed", "data_random_seed"):
        assert params[key] == 20260101
    assert params["deterministic"] is True
    assert params["force_row_wise"] is True
    assert params["num_threads"] == GbmSpec().num_threads


def test_the_fingerprint_changes_when_any_knob_changes():
    base = GbmSpec().fingerprint()
    assert len(base) == 16
    for kwargs in (
        {"learning_rate": 0.06},
        {"num_leaves": 32},
        {"lambda_l2": 2.0},
        {"early_stopping_days": 91},
        {"num_boost_round": 2001},
        {"refit_on_full_window": False},
        {"nan_policy": "decline"},
        {"vst": False},
        {"seed": 1},
    ):
        assert GbmSpec(**kwargs).fingerprint() != base, kwargs


def test_the_fingerprint_is_stable_across_identical_specs():
    assert GbmSpec().fingerprint() == GbmSpec().fingerprint()


def test_nothing_is_added_to_the_booster_params_at_fit_time(fitted):
    """The committed params are what LightGBM got — no fit-time additions."""
    assert fitted.report_ is not None
    assert fitted.report_.spec["booster_params"] == SMALL.booster_params()
    assert fitted.report_.spec["fingerprint"] == SMALL.fingerprint()


# ---------------------------------------------------------------------------
# In-fold early stopping: where the round count comes from
# ---------------------------------------------------------------------------


def test_the_stopping_set_is_the_tail_of_the_window():
    days = [dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(100)]
    market_day = pd.Series(np.repeat(days, 24))
    is_fit, is_stopping, fit_days, stopping_days = early_stopping_split(market_day, 30)
    assert stopping_days == days[-30:]
    assert fit_days == days[:-30]
    assert max(fit_days) < min(stopping_days)
    assert int(is_fit.sum()) == 70 * 24
    assert int(is_stopping.sum()) == 30 * 24
    # Every row lands in exactly one side: no row is used twice, none is dropped.
    assert not (is_fit & is_stopping).any()
    assert (is_fit | is_stopping).all()


def test_the_split_keeps_each_market_day_whole():
    """Half a day on each side would put a row's neighbours across the split."""
    days = [dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(50)]
    market_day = pd.Series(np.repeat(days, 24))
    is_fit, is_stopping, _, _ = early_stopping_split(market_day, 10)
    frame = pd.DataFrame({"day": market_day, "fit": is_fit})
    assert frame.groupby("day", observed=True)["fit"].nunique().max() == 1


def test_a_window_with_nothing_left_to_fit_on_raises():
    days = [dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(10)]
    market_day = pd.Series(np.repeat(days, 24))
    with pytest.raises(ModelError, match="nothing left"):
        early_stopping_split(market_day, 10)
    with pytest.raises(ModelError, match="nothing left"):
        early_stopping_split(market_day, 11)


def test_an_empty_window_raises():
    with pytest.raises(ModelError, match="empty training window"):
        early_stopping_split(pd.Series([], dtype="object"), 5)


def test_early_stopping_uses_only_training_days(split, fitted):
    """The stopping set is inside the training window — never the test fold.

    This is the one place a GBM fold could look forward, because the round count
    is the only thing chosen per fold. The report names the days it was chosen
    from, and they all sit inside the window the harness already asserted was
    public at gate closure.
    """
    train, test = split
    report = fitted.fit_report()
    train_days = set(train.market_day)
    test_days = set(test.market_day)
    stopping_first = dt.date.fromisoformat(report["stopping_first_day"])
    stopping_last = dt.date.fromisoformat(report["stopping_last_day"])
    fit_last = dt.date.fromisoformat(report["fit_last_day"])
    assert stopping_first in train_days and stopping_last in train_days
    assert stopping_last < min(test_days)
    assert fit_last < stopping_first
    assert not test_days & {stopping_first, stopping_last}


def test_the_round_count_is_chosen_not_fixed(split):
    """Two different training windows should not generally stop at the same round.

    If they did, the "early stopping" would be decorative and the model would be
    running a fixed 120 rounds under another name.
    """
    train, _ = split
    early = train.subset((train.market_day <= dt.date(2021, 9, 30)).to_numpy())
    a = GbmModel(SMALL).fit(train).fit_report()["best_iteration"]
    b = GbmModel(SMALL).fit(early).fit_report()["best_iteration"]
    assert a >= 1 and b >= 1
    assert a != b


def test_the_report_says_when_the_round_cap_was_hit(split):
    """A run that always hits the cap never early-stopped; that must be visible."""
    train, _ = split
    capped = GbmModel(
        GbmSpec(
            early_stopping_days=60, min_fit_rows=100, num_boost_round=3,
            early_stopping_rounds=15, num_threads=1,
        )
    ).fit(train)
    report = capped.fit_report()
    assert report["n_rounds_capped"] is True
    assert report["best_iteration"] == 3
    assert report["n_rounds_used"] == 3


def test_the_default_spec_does_not_hit_the_cap(fitted):
    assert fitted.fit_report()["n_rounds_capped"] is False


def test_refitting_on_the_full_window_uses_the_chosen_round_count(split):
    train, _ = split
    model = GbmModel(SMALL).fit(train)
    report = model.fit_report()
    assert report["refit_on_full_window"] is True
    assert report["n_rounds_used"] == report["best_iteration"]
    # The refit booster holds exactly the rounds that were asked for.
    assert report["n_trees_in_booster"] == report["best_iteration"]
    # The refit saw every usable row of the window, stopping days included.
    assert report["n_fit_rows"] + report["n_stopping_rows"] == report["n_train_rows_usable"]


def test_without_the_refit_the_model_is_the_early_stopped_booster(split):
    train, test = split
    no_refit = GbmSpec(
        early_stopping_days=60, min_fit_rows=100, num_boost_round=600,
        early_stopping_rounds=15, num_threads=1, refit_on_full_window=False,
    )
    a = GbmModel(no_refit).fit(train)
    b = GbmModel(SMALL).fit(train)
    assert a.fit_report()["refit_on_full_window"] is False
    # Same rounds, different rows fitted -> genuinely different predictions.
    assert a.fit_report()["best_iteration"] == b.fit_report()["best_iteration"]
    assert not np.allclose(
        a.predict(test).to_numpy(), b.predict(test).to_numpy(), equal_nan=True
    )


def test_the_booster_is_rolled_back_to_the_best_iteration(split):
    """lightgbm rolls the booster back to ``best_iteration``; this pins that contract.

    **This test began life asserting the opposite, and was wrong.** The worry was
    reasonable — if ``lgb.train`` kept the ``early_stopping_rounds`` trees built
    while discovering the best iteration, then predicting with ``num_trees()``
    would quietly serve the exact overfit tail early stopping existed to reject,
    and nothing would look wrong. So the model was written to carry the round
    count explicitly and a test was written to pin the gap.

    There is no gap. On lightgbm 4.7.0 ``lgb.train`` truncates the booster to the
    best iteration, so ``num_trees() == best_iteration`` and a bare ``predict()``
    already uses the right trees. The test caught the wrong hypothesis, which is
    what it was for — see the retraction of FINDING C9-B in ``PROGRESS.md``.

    What remains is worth pinning, in the other direction: the rollback is a
    library implementation detail, not a documented guarantee this code should
    lean on. ``GbmModel`` therefore still passes ``num_iteration`` explicitly, so
    it is correct whether or not a future version rolls back — and this test
    asserts the version in use *does* roll back, so a version that stops doing so
    shows up here as a failure rather than as a silent change in every result.
    """
    train, test = split
    no_refit = GbmSpec(
        early_stopping_days=60, min_fit_rows=100, num_boost_round=600,
        early_stopping_rounds=15, num_threads=1, refit_on_full_window=False,
    )
    model = GbmModel(no_refit).fit(train)
    report = model.fit_report()

    # The round count the stopping set chose is what the model uses, and what the
    # booster holds. All three agree.
    assert report["n_rounds_used"] == report["best_iteration"]
    assert report["n_trees_in_booster"] == report["best_iteration"]
    assert model.n_iteration_ == report["best_iteration"]
    # Early stopping actually fired, so the rollback had something to roll back.
    assert report["n_rounds_capped"] is False
    assert report["best_iteration"] < no_refit.num_boost_round

    # And because the booster holds only those trees, asking for all of them
    # (num_iteration=0 means "every tree") gives the same answer.
    design = model._design(test.features, model.feature_names_).to_numpy(dtype="float64")
    all_trees = _inverse_asinh(
        np.asarray(model.booster_.predict(design, num_iteration=0), dtype="float64"),
        model.target_centre_,
        model.target_scale_,
    )
    np.testing.assert_allclose(model.predict(test).to_numpy(), all_trees)


# ---------------------------------------------------------------------------
# The model reads features, and only features
# ---------------------------------------------------------------------------


def test_predictions_are_unchanged_when_the_test_target_is_destroyed(fitted, split):
    _, test = split
    poisoned = test.with_target(pd.Series(np.nan, index=test.index, name=test.target.name))
    np.testing.assert_allclose(
        fitted.predict(test).to_numpy(), fitted.predict(poisoned).to_numpy()
    )


def test_a_rows_prediction_does_not_depend_on_the_rest_of_the_test_set(fitted, split):
    """Nothing is recomputed at predict time, so one row predicts the same alone."""
    _, test = split
    whole = fitted.predict(test)
    for position in (0, 7, len(test.index) // 2, len(test.index) - 1):
        one = test.subset(np.arange(len(test.index)) == position)
        np.testing.assert_allclose(
            fitted.predict(one).to_numpy(), [whole.to_numpy()[position]]
        )


def test_the_fit_is_bit_reproducible(split):
    """Same spec, same rows, same prediction — twice. Needed for a reproducible run."""
    train, test = split
    a = GbmModel(SMALL).fit(train).predict(test)
    b = GbmModel(SMALL).fit(train).predict(test)
    np.testing.assert_array_equal(a.to_numpy(), b.to_numpy())


def test_a_different_seed_moves_the_prediction(split):
    """The seed is load-bearing: bagging and feature sampling are actually on."""
    train, test = split
    a = GbmModel(SMALL).fit(train).predict(test)
    b = GbmModel(
        GbmSpec(
            early_stopping_days=60, min_fit_rows=100, num_boost_round=600,
            early_stopping_rounds=15, num_threads=1, seed=99,
        )
    ).fit(train).predict(test)
    assert not np.array_equal(a.to_numpy(), b.to_numpy())


def test_predicting_on_a_frame_missing_a_fitted_column_raises(fitted, split):
    _, test = split
    short = test.with_features(test.features.drop(columns=["price_lag_168h"]))
    with pytest.raises(ModelError, match="missing fitted column"):
        fitted.predict(short)


def test_the_column_order_of_the_test_frame_does_not_matter(fitted, split):
    """Columns are selected by name, not by position."""
    _, test = split
    shuffled_columns = list(reversed(test.features.columns))
    shuffled = test.with_features(
        test.features[shuffled_columns],
        test.information_times[shuffled_columns],
    )
    np.testing.assert_allclose(
        fitted.predict(test).to_numpy(), fitted.predict(shuffled).to_numpy()
    )


# ---------------------------------------------------------------------------
# The target transform is LEAR's, exactly
# ---------------------------------------------------------------------------


def test_the_target_transform_is_the_in_fold_asinh_lear_uses(split, fitted):
    """Not "a VST" — *the* VST, so a model comparison is one of functional form."""
    train, _ = split
    target = train.target.to_numpy(dtype="float64")
    centre, scale, _ = _vst_params(target[np.isfinite(target)])
    report = fitted.fit_report()
    assert report["target_centre"] == pytest.approx(centre, abs=1e-6)
    assert report["target_scale"] == pytest.approx(scale, abs=1e-6)


def test_the_inverse_transform_is_applied_to_the_prediction(fitted, split):
    """Predictions come back as prices, on the scale of the training target."""
    train, test = split
    prediction = fitted.predict(test).dropna()
    assert prediction.between(
        train.target.min() - 100.0, train.target.max() + 100.0
    ).all()
    assert prediction.std() > 1.0


def test_turning_the_vst_off_changes_the_prediction(split):
    train, test = split
    raw = GbmSpec(
        early_stopping_days=60, min_fit_rows=100, num_boost_round=600,
        early_stopping_rounds=15, num_threads=1, vst=False,
    )
    a = GbmModel(SMALL).fit(train).predict(test)
    b = GbmModel(raw).fit(train).predict(test)
    assert not np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True)
    assert GbmModel(raw).fit(train).fit_report()["target_centre"] == 0.0


def test_the_asinh_pair_round_trips():
    """A sanity check on the imported helpers: the inverse is exact, not approximate."""
    values = np.array([-500.0, -1.0, 0.0, 37.5, 4000.0])
    centre, scale, _ = _vst_params(values)
    np.testing.assert_allclose(
        _inverse_asinh(_asinh(values, centre, scale), centre, scale), values, atol=1e-9
    )


# ---------------------------------------------------------------------------
# Categoricals and NaN policy
# ---------------------------------------------------------------------------


def test_the_calendar_categoricals_are_the_same_set_lear_encodes():
    assert set(CATEGORICAL_FEATURES) == {
        "day_of_week", "month", "hour_of_day_local", "hour_of_day_utc"
    }


def test_the_fitted_categoricals_are_only_those_present(fitted):
    report = fitted.fit_report()
    assert set(report["categorical_features"]) <= set(CATEGORICAL_FEATURES)
    assert "price_lag_24h" not in report["categorical_features"]
    assert "is_weekend" not in report["categorical_features"]


def test_native_nan_policy_predicts_a_row_with_a_hole(fitted, split):
    """LightGBM routes a missing cell; under the default policy that row is answered."""
    _, test = split
    holed = test.features.copy()
    holed.iloc[0, holed.columns.get_loc("price_lag_24h")] = np.nan
    prediction = fitted.predict(test.with_features(holed))
    assert np.isfinite(prediction.iloc[0])
    assert fitted.fit_report()["n_predict_rows_with_any_nan"] >= 1


def test_decline_nan_policy_mirrors_lears_listwise_refusal(split):
    train, test = split
    declining = GbmSpec(
        early_stopping_days=60, min_fit_rows=100, num_boost_round=600,
        early_stopping_rounds=15, num_threads=1, nan_policy="decline",
    )
    model = GbmModel(declining).fit(train)
    holed = test.features.copy()
    holed.iloc[3, holed.columns.get_loc("price_lag_24h")] = np.nan
    prediction = model.predict(test.with_features(holed))
    assert np.isnan(prediction.iloc[3])
    assert np.isfinite(prediction.iloc[4])
    assert model.fit_report()["n_predict_declined_nan"] == 1


def test_a_training_row_with_a_missing_target_is_dropped(split):
    """A NaN target cannot be fitted; a NaN *feature* is routed, not dropped."""
    train, _ = split
    broken = train.target.copy()
    broken.iloc[:48] = np.nan
    model = GbmModel(SMALL).fit(train.with_target(broken))
    report = model.fit_report()
    assert report["n_train_rows_dropped_target_nan"] == 48
    assert report["n_train_rows_usable"] == report["n_train_rows"] - 48


def test_too_few_usable_training_rows_raises_rather_than_fitting(split):
    train, _ = split
    tiny = train.subset((train.market_day <= dt.date(2021, 1, 20)).to_numpy())
    with pytest.raises(ModelError, match="min_fit_rows"):
        GbmModel(GbmSpec(early_stopping_days=5, min_fit_rows=100_000)).fit(tiny)


def test_a_matrix_with_no_feature_column_raises(split):
    train, _ = split
    empty = train.with_features(
        train.features.iloc[:, :0], train.information_times.iloc[:, :0]
    )
    with pytest.raises(ModelError, match="no feature column"):
        GbmModel(SMALL).fit(empty)


# ---------------------------------------------------------------------------
# Skill: the booster has to earn its place
# ---------------------------------------------------------------------------


def test_the_gbm_beats_the_median_baseline_on_a_week_periodic_series(matrix, eval_days):
    """Not a strong claim — but a model that cannot do this has learned nothing."""
    gbm = run_walk_forward(matrix, gbm_factory(SMALL), eval_days, SPEC)
    median = run_walk_forward(matrix, TrainMedianBaseline, eval_days, SPEC)
    assert skill_score(gbm.y_true, gbm.y_pred, median.y_pred) > 0.3


def test_the_gbm_predicts_every_hour_the_naive_floor_predicts(matrix, eval_days):
    """Native NaN routing means coverage is at least the floor's, never worse."""
    gbm = run_walk_forward(matrix, gbm_factory(SMALL), eval_days, SPEC)
    naive = run_walk_forward(matrix, NaiveLastWeek, eval_days, SPEC)
    assert gbm.y_pred.index.equals(naive.y_pred.index)
    assert score(gbm.y_true, gbm.y_pred).coverage >= score(naive.y_true, naive.y_pred).coverage


def test_target_permutation_destroys_the_gbms_skill(matrix, eval_days):
    """PLAN.md C3's third leakage assertion, applied to the booster.

    A model fitted on shuffled targets must collapse to the zero-information
    reference. If it does not, the "skill" is coming from somewhere other than the
    relationship between the features and the target. Read FINDING C4-A before
    trusting the sign of this on a *skewed* series: the reference here is the
    train mean, and on a right-skewed target a median-like estimator — which a
    booster fitted in asinh space is — collects a margin before it has learned
    anything. The synthetic series is near-symmetric, so the probe is clean on it.
    """
    experiment = dx.target_permutation_experiment(
        matrix, gbm_factory(SMALL), eval_days, SPEC, seed=11, mode="hours"
    )
    assert experiment.real_skill > 0.0
    assert experiment.permuted_skill <= 0.0
    assert experiment.destroys_skill(), experiment.as_dict()


def test_shifting_the_features_forward_a_day_degrades_the_gbm():
    """PLAN.md C3's first leakage assertion, applied to the booster.

    ``shifts=(0, 1)``: a matrix whose features are one day staler than the row
    they describe must score strictly worse. The ``-1`` arm of the experiment is
    left out because it is a *leak*, so "it degrades" is the wrong claim to make
    about it — what the leak is worth is measured separately below.

    Measured on the **persistence-dominated** series, not the week-periodic one
    the C3 version of this assertion uses. See FINDING C9-A and the test below
    for why that choice is load-bearing rather than cosmetic.
    """
    persistent = build_features(
        _random_walk_prices(_utc_index("2021-01-01", 730)), ZONE
    )
    days = evaluation_days(persistent, [2022])
    experiment = dx.day_shift_experiment(
        persistent, gbm_factory(SMALL), days, SPEC, shifts=(0, 1)
    )
    by_shift = experiment.by_shift()
    assert by_shift[1].mae > by_shift[0].mae, experiment.as_dict()
    assert experiment.degrades_everywhere(), experiment.as_dict()


def test_the_day_shift_assertion_is_vacuous_for_this_model_on_a_periodic_series(
    matrix, eval_days
):
    """FINDING C9-A, pinned: for a pooled booster, a staler matrix can score *better*.

    C3 asserts assertion (i) against ``NaiveLastWeek``, which *is*
    ``price_lag_168h``, so misaligning the matrix necessarily wrecks it. A pooled
    tree ensemble is a different animal: it also holds ``hour_of_day_local``,
    ``day_of_week`` and ``month``, and on the synthetic week-periodic series the
    price shape is an exact deterministic function of those three. The lagged
    prices are a *noisier restatement* of a signal the calendar gives for free
    (each lag carries its own copy of the noise term), so the best available model
    on that series ignores the lags — and misaligning them, far from hurting,
    nudges the booster towards doing exactly that.

    So assertion (i) is only informative on a series where the lagged prices carry
    something the calendar cannot. That is a fact about the *fixture*, and the
    honest response is to assert the real thing on the right fixture (the test
    above, and the real-data diagnostic in :mod:`backtest.run_c9_gbm`) and to pin
    the vacuity here so nobody later reads a passing periodic-series shift test as
    evidence of anything. Nothing in ``tests/test_c3_leakage_harness.py`` is
    touched: its assertion is about the naive floor and remains true of it.
    """
    experiment = dx.day_shift_experiment(
        matrix, gbm_factory(SMALL), eval_days, SPEC, shifts=(0, 1)
    )
    by_shift = experiment.by_shift()
    assert by_shift[1].mae <= by_shift[0].mae, (
        "FINDING C9-A no longer reproduces; re-read it before changing this test"
    )
    # And the reason: the calendar alone already explains the series, to within
    # the noise floor that no model can beat.
    noise_floor_mae = 2.0 * (2.0 / np.pi) ** 0.5
    assert by_shift[0].mae < 1.25 * noise_floor_mae, by_shift[0].as_dict()


# ---------------------------------------------------------------------------
# The guard, and what it is defending
# ---------------------------------------------------------------------------


def test_the_harness_refuses_to_run_the_gbm_on_an_injected_future_feature(
    matrix, eval_days
):
    """PLAN.md C3's second leakage assertion: the guard catches a leading column.

    Nothing about the guard is model-specific, which is the point — it sits in the
    harness, so a new model cannot arrive with its own looser version.
    """
    injected = dx.inject_future_feature(matrix, lead_hours=24, declare=True)
    with pytest.raises(LeakageError, match="after_gate_closure"):
        run_walk_forward(injected, gbm_factory(SMALL), eval_days, SPEC)

    smuggled = dx.inject_future_feature(matrix, lead_hours=24, declare=False)
    with pytest.raises(LeakageError, match="undeclared"):
        run_walk_forward(smuggled, gbm_factory(SMALL), eval_days, SPEC)


def test_a_leading_feature_would_be_worth_a_lot_to_the_gbm():
    """What the guard is protecting, as a number rather than a principle.

    On a persistence-dominated series a 24-hour *lead* is nearly the answer. The
    bound is the same 0.8 of MAE that C4 justified for LEAR and for the same
    reason: the model already holds the price 24 hours *back*, so the leading
    feature is a second observation the same distance away on the other side, and
    averaging two symmetric observations cuts the error by about sqrt(2). A leak
    is worth less to a model that was already using everything legal — which
    argues for the guard, not against it, because 20-30% of MAE is the whole gap
    between a good model and a mediocre one.

    The run is knowingly dishonest and exists only to be measured, hence
    ``check_leakage=False``, which real runs never pass.
    """
    persistent = build_features(
        _random_walk_prices(_utc_index("2021-01-01", 730)), ZONE
    )
    days = evaluation_days(persistent, [2022])
    honest = run_walk_forward(persistent, gbm_factory(SMALL), days, SPEC)
    leaking = run_walk_forward(
        dx.inject_future_feature(persistent, lead_hours=24, declare=True),
        gbm_factory(SMALL),
        days,
        SPEC,
        check_leakage=False,
    )
    honest_mae = score(honest.y_true, honest.y_pred).mae
    leaking_mae = score(leaking.y_true, leaking.y_pred).mae
    assert leaking_mae < 0.8 * honest_mae, (honest_mae, leaking_mae)


def test_the_gbm_now_passes_the_holdout_guard_for_2025(matrix):
    """Was test_the_gbm_cannot_be_evaluated_against_a_sealed_year. The booster
    inherits :mod:`data.holdout`'s check with no door of its own — unchanged —
    and that check now permits 2025, unsealed by Checkpoint C (2026-10-12).
    `matrix` is a synthetic fixture never populated with real 2025 rows, so past
    the now-passing guard this reaches a different, expected complaint — see
    test_harness_now_passes_the_holdout_guard_for_2025 in
    tests/test_c3_leakage_harness.py for the same pattern."""
    with pytest.raises(WalkForwardError, match="no complete market days"):
        evaluation_days(matrix, [2025])
    with pytest.raises(WalkForwardError, match="no fold could be run"):
        run_walk_forward(matrix, gbm_factory(SMALL), [dt.date(2025, 6, 1)], SPEC)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_the_fit_report_is_json_serialisable(fitted):
    import json

    json.dumps(fitted.fit_report())


def test_feature_importance_is_a_normalised_distribution_over_the_fitted_columns(fitted):
    importance = fitted.feature_importance()
    assert set(importance) == set(fitted.feature_names_)
    assert sum(importance.values()) == pytest.approx(1.0, abs=1e-4)
    assert min(importance.values()) >= 0.0


def test_the_price_lags_carry_most_of_the_importance_on_a_week_periodic_series(fitted):
    """A description of the fit, never a selection step — but it should be sane."""
    importance = fitted.feature_importance()
    price_share = sum(v for k, v in importance.items() if k.startswith("price_"))
    assert price_share > 0.5, importance
