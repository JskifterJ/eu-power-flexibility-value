"""C3 tests: the gate-closure guard, the walk-forward harness, and the three
leakage assertions PLAN.md requires to exist before the first real model.

All synthetic and offline. Two tests name the year 2025 in order to prove the
harness *refuses* it; they pass bare :class:`datetime.date` labels and never load,
read or compute anything from sealed data — the same line C2 drew for its
resolution-cutover tests.

The three PLAN.md assertions are:

(i)   ``test_shifting_the_feature_matrix_forward_one_day_degrades_metrics``
(ii)  ``test_guard_catches_a_deliberately_inserted_future_feature``
(iii) ``test_target_permutation_destroys_skill``

Everything else here exists so that those three cannot pass for an uninteresting
reason.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backtest import diagnostics as dx
from backtest.metrics import MetricError, Scores, mae, rmae, score, skill_score
from backtest.walk_forward import (
    Fold,
    WalkForwardError,
    WalkForwardSpec,
    _assert_training_targets_were_public,
    evaluation_days,
    make_folds,
    run_walk_forward,
)
from forecast.features import build_features
from forecast.leakage import LeakageError, assert_no_leakage, find_leakage, mask_unavailable
from forecast.models import ModelError, NaiveLastWeek, TrainMeanBaseline
from forecast.timing import gate_closure_utc, publication_utc
from tests.test_c3_timing_features import (
    ZONE,
    _random_walk_prices,
    _utc_index,
    _weekly_prices,
)

SPEC = WalkForwardSpec(refit_every_days=14, min_train_days=200)


@pytest.fixture(scope="module")
def matrix():
    """Two years of synthetic week-periodic prices, built into a clean matrix."""
    return build_features(_weekly_prices(_utc_index("2021-01-01", 730)), ZONE)


@pytest.fixture(scope="module")
def eval_days(matrix):
    return evaluation_days(matrix, [2022])


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_the_real_matrix_passes_the_guard(matrix):
    assert find_leakage(
        matrix.features, matrix.information_times, matrix.gate_closure, matrix.deterministic
    ) == []
    matrix.assert_clean()


def test_guard_rejects_an_undeclared_column(matrix):
    """Fail closed: a column with no declared information time is a violation.

    This is the rule that protects against a future cycle adding a feature and
    forgetting the bookkeeping — the failure mode no diff review catches.
    """
    features = matrix.features.copy()
    features["mystery"] = 1.0
    violations = find_leakage(
        features, matrix.information_times, matrix.gate_closure, matrix.deterministic
    )
    assert [(v.kind, v.column) for v in violations] == [("undeclared", "mystery")]
    with pytest.raises(LeakageError, match="undeclared"):
        assert_no_leakage(
            features, matrix.information_times, matrix.gate_closure, matrix.deterministic
        )


def test_guard_rejects_a_declared_feature_published_after_gate_closure(matrix):
    information = matrix.information_times.copy()
    information["price_lag_48h"] = matrix.gate_closure + pd.Timedelta(minutes=1)
    violations = find_leakage(
        matrix.features, information, matrix.gate_closure, matrix.deterministic
    )
    assert [(v.kind, v.column) for v in violations] == [
        ("after_gate_closure", "price_lag_48h")
    ]
    assert violations[0].worst_lateness == pd.Timedelta(minutes=1)


def test_guard_rejects_a_calendar_column_that_carries_market_information(matrix):
    information = matrix.information_times.copy()
    information["hour_of_day_utc"] = matrix.gate_closure - pd.Timedelta(days=5)
    violations = find_leakage(
        matrix.features, information, matrix.gate_closure, matrix.deterministic
    )
    assert [v.kind for v in violations] == ["deterministic_with_information"]


def test_guard_rejects_a_value_with_no_information_time(matrix):
    """A present value whose availability is unknown cannot be given the benefit."""
    information = matrix.information_times.copy()
    information["price_lag_72h"] = pd.NaT
    violations = find_leakage(
        matrix.features, information, matrix.gate_closure, matrix.deterministic
    )
    assert [v.kind for v in violations] == ["missing_information_time"]


def test_guard_rejects_a_stale_declaration_and_misaligned_frames(matrix):
    information = matrix.information_times.copy()
    information["ghost"] = pd.NaT
    violations = find_leakage(
        matrix.features, information, matrix.gate_closure, matrix.deterministic
    )
    assert [(v.kind, v.column) for v in violations] == [("stale_declaration", "ghost")]

    with pytest.raises(LeakageError, match="different indexes"):
        find_leakage(
            matrix.features,
            matrix.information_times.iloc[:-1],
            matrix.gate_closure,
            matrix.deterministic,
        )
    with pytest.raises(LeakageError, match="does not share"):
        find_leakage(
            matrix.features,
            matrix.information_times,
            matrix.gate_closure.iloc[:-1],
            matrix.deterministic,
        )


def test_guard_fails_closed_on_a_malformed_information_time_column(matrix):
    """A declaration the guard cannot interpret must be a violation, not a crash.

    One careless assignment turns a timestamp column into ``object`` or tz-naive
    dtype, and comparing that against a tz-aware gate closure raises an opaque
    ``TypeError`` from deep inside pandas. In a guard that is the worst outcome:
    the check neither passes nor fails. So an uninterpretable declaration is
    reported, and :func:`mask_unavailable` blanks the whole column rather than
    keeping values whose availability nobody can establish.
    """
    information = matrix.information_times.copy()
    information["price_lag_48h"] = "not a timestamp"
    violations = find_leakage(
        matrix.features, information, matrix.gate_closure, matrix.deterministic
    )
    assert [(v.kind, v.column) for v in violations] == [
        ("malformed_information_time", "price_lag_48h")
    ]

    masked, report = mask_unavailable(
        matrix.features, information, matrix.gate_closure, matrix.deterministic
    )
    assert masked["price_lag_48h"].isna().all()
    assert report.masked_per_column["price_lag_48h"] == int(
        matrix.features["price_lag_48h"].notna().sum()
    )

    naive_tz = matrix.information_times.copy()
    naive_tz["price_lag_72h"] = matrix.information_times["price_lag_72h"].dt.tz_localize(None)
    assert [
        (v.kind, v.column)
        for v in find_leakage(
            matrix.features, naive_tz, matrix.gate_closure, matrix.deterministic
        )
    ] == [("malformed_information_time", "price_lag_72h")], (
        "a tz-naive declaration is reported, not assumed to be UTC"
    )


def test_guard_refuses_an_unusable_gate_closure_series(matrix):
    with pytest.raises(LeakageError, match="gate-closure series is not a usable"):
        find_leakage(
            matrix.features,
            matrix.information_times,
            pd.Series("noon-ish", index=matrix.index),
            matrix.deterministic,
        )


def test_mask_unavailable_blanks_only_unavailable_cells_and_reports_them(matrix):
    information = matrix.information_times.copy()
    late = np.zeros(len(matrix.index), dtype=bool)
    # Well inside the series: the first 48 hours have no 48-hour lag to mask.
    late[[1000, 1001, 1002]] = True
    column = information["price_lag_48h"].copy()
    column[late] = matrix.gate_closure[late] + pd.Timedelta(hours=3)
    information["price_lag_48h"] = column

    masked, report = mask_unavailable(
        matrix.features, information, matrix.gate_closure, matrix.deterministic
    )
    assert report.masked_per_column == {"price_lag_48h": 3}
    assert report.total_masked == 3
    assert masked["price_lag_48h"].iloc[1000:1003].isna().all()
    assert masked["price_lag_48h"].iloc[1003] == matrix.features["price_lag_48h"].iloc[1003]
    assert matrix.features["price_lag_48h"].iloc[1000:1003].notna().all(), "input not mutated"
    assert_no_leakage(masked, information, matrix.gate_closure, matrix.deterministic)


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------


def test_no_fold_trains_on_its_own_target_day_or_later(matrix, eval_days):
    folds, _ = make_folds(sorted(set(matrix.market_day)), eval_days, SPEC)
    assert folds
    for fold in folds:
        assert fold.train_end_day < fold.target_days[0]
        assert fold.train_end_day == fold.target_days[0] - dt.timedelta(days=1)
        assert publication_utc(fold.train_end_day) < fold.gate_closure_utc
        assert fold.gate_closure_utc == gate_closure_utc(fold.target_days[0])


def test_refit_cadence_blocks_days_and_holds_the_training_window_fixed(matrix, eval_days):
    """A weekly refit means the last day of a block is predicted by a stale model.

    That is the real cost of refitting weekly, not a bug: the guard requires the
    training window to end before the *first* day of the block, and everything
    after that is honest staleness.
    """
    weekly, _ = make_folds(sorted(set(matrix.market_day)), eval_days, WalkForwardSpec(
        refit_every_days=7, min_train_days=200
    ))
    assert all(len(f.target_days) <= 7 for f in weekly)
    assert sum(len(f.target_days) for f in weekly) == len(eval_days)
    last_block = weekly[0]
    assert last_block.train_end_day == last_block.target_days[0] - dt.timedelta(days=1)
    staleness = last_block.target_days[-1] - last_block.train_end_day
    assert staleness == dt.timedelta(days=7)

    daily, _ = make_folds(sorted(set(matrix.market_day)), eval_days, WalkForwardSpec(
        refit_every_days=1, min_train_days=200
    ))
    assert len(daily) == len(eval_days)


def test_min_train_days_skips_days_and_says_why(matrix):
    """Insufficient history is reported, never padded over."""
    days = evaluation_days(matrix, [2021])
    folds, skipped = make_folds(
        sorted(set(matrix.market_day)), days, WalkForwardSpec(refit_every_days=1, min_train_days=200)
    )
    assert len(skipped) == 200, "the first 200 days of the series cannot be evaluated"
    assert all("min_train_days=200" in reason for reason in skipped.values())
    assert len(folds) == len(days) - 200

    result = run_walk_forward(
        matrix, NaiveLastWeek, days, WalkForwardSpec(refit_every_days=1, min_train_days=200)
    )
    assert len(result.skipped_days) == 200
    assert result.predictions["market_day"].min() == days[200]


def test_rolling_window_keeps_only_the_recent_past(matrix, eval_days):
    folds, _ = make_folds(
        sorted(set(matrix.market_day)),
        eval_days,
        WalkForwardSpec(refit_every_days=14, min_train_days=200, train_window_days=300),
    )
    for fold in folds:
        assert fold.n_train_days <= 300
        assert fold.train_start_day >= fold.target_days[0] - dt.timedelta(days=300)


def test_spec_refuses_a_window_smaller_than_its_own_minimum():
    with pytest.raises(WalkForwardError, match="smaller than"):
        WalkForwardSpec(min_train_days=365, train_window_days=100)
    with pytest.raises(WalkForwardError, match="refit_every_days"):
        WalkForwardSpec(refit_every_days=0)


def test_harness_now_passes_the_holdout_guard_for_2025(matrix):
    """Was test_harness_refuses_a_sealed_holdout_year. Checkpoint C (2026-10-12)
    unsealed 2025 in this repo's real PROGRESS.md, which evaluation_days()
    checks by default — exactly the capability C17's evaluation depends on.
    `matrix` is a synthetic fixture with bare date labels built only to test the
    guard, never populated with actual 2025 rows (it never needed to be, when
    the point was proving the guard fired before any data was touched), so past
    the now-passing guard this correctly reaches a *different* complaint —
    WalkForwardError for having no 2025 rows at all — rather than succeeding
    outright. That different error is the proof: SealedHoldoutError is gone."""
    with pytest.raises(WalkForwardError, match="no complete market days"):
        evaluation_days(matrix, [2025])
    with pytest.raises(WalkForwardError, match="no fold could be run"):
        run_walk_forward(matrix, NaiveLastWeek, [dt.date(2025, 6, 1)], SPEC)


def test_harness_raises_if_a_training_target_was_not_public_at_gate_closure(matrix):
    """The guard that a day-arithmetic bug cannot talk its way past."""
    first_target = dt.date(2022, 6, 1)
    train = matrix.select_days([first_target - dt.timedelta(days=n) for n in range(1, 30)])
    good = Fold(
        index=0,
        target_days=(first_target,),
        train_start_day=first_target - dt.timedelta(days=29),
        train_end_day=first_target - dt.timedelta(days=1),
        gate_closure_utc=gate_closure_utc(first_target),
        n_train_days=29,
    )
    _assert_training_targets_were_public(train, good, ZONE)

    too_early = Fold(**{**good.__dict__, "gate_closure_utc": gate_closure_utc(
        first_target - dt.timedelta(days=1)
    )})
    with pytest.raises(WalkForwardError, match="after this fold's gate closure"):
        _assert_training_targets_were_public(train, too_early, ZONE)

    # Training data that reaches into the target day itself is caught by the
    # publication check before the (belt-and-braces) day-ordering check can fire.
    overlapping = matrix.select_days([first_target])
    with pytest.raises(WalkForwardError, match="after this fold's gate closure"):
        _assert_training_targets_were_public(overlapping, good, ZONE)


def test_harness_rejects_a_model_that_predicts_on_the_wrong_index(matrix, eval_days):
    class Wanderer:
        name = "wanderer"

        def fit(self, train):
            return self

        def predict(self, test):
            return pd.Series(1.0, index=test.index[:-1])

    with pytest.raises(WalkForwardError, match="different index"):
        run_walk_forward(matrix, Wanderer, eval_days[:14], SPEC)


def test_walk_forward_covers_every_evaluation_hour_exactly_once(matrix, eval_days):
    result = run_walk_forward(matrix, NaiveLastWeek, eval_days, SPEC)
    assert not result.predictions.index.has_duplicates
    assert result.predictions.index.is_monotonic_increasing
    assert sorted(set(result.predictions["market_day"])) == eval_days
    assert len(result.predictions) == 8760, "2022 has 8760 hours"
    assert result.predictions["y_pred"].notna().all()
    assert set(result.predictions["model"]) == {"naive_last_week"}
    assert len(result.folds) == len(result.folds_frame())
    assert result.as_dict()["n_folds"] == len(result.folds)


def test_each_fold_is_fitted_fresh(matrix, eval_days):
    """A fold must never inherit state fitted on another fold's data."""
    seen: list[int] = []

    class Counter:
        name = "counter"

        def __init__(self):
            seen.append(id(self))

        def fit(self, train):
            self.n = len(train.index)
            return self

        def predict(self, test):
            return pd.Series(float(self.n), index=test.index)

    result = run_walk_forward(matrix, Counter, eval_days[:28], SPEC)
    # One construction to read the model name, then one per fold.
    assert len(set(seen)) == len(result.folds) + 1
    assert result.predictions["y_pred"].nunique() == len(result.folds)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_naive_predicts_the_same_hour_one_week_earlier(matrix, eval_days):
    result = run_walk_forward(matrix, NaiveLastWeek, eval_days[:7], SPEC)
    probe = result.predictions.index[30]
    assert result.predictions["y_pred"].loc[probe] == pytest.approx(
        matrix.target.loc[probe - pd.Timedelta(hours=168)]
    )


def test_naive_refuses_a_matrix_without_its_committed_lag_column(matrix):
    stripped = matrix.with_features(matrix.features.drop(columns=["price_lag_168h"]))
    with pytest.raises(ModelError, match="price_lag_168h"):
        NaiveLastWeek().fit(stripped)


def test_train_mean_baseline_predicts_the_training_mean(matrix, eval_days):
    train = matrix.select_days(
        [eval_days[0] - dt.timedelta(days=n) for n in range(1, 101)]
    )
    model = TrainMeanBaseline().fit(train)
    assert model.mean_ == pytest.approx(train.target.mean())
    assert TrainMeanBaseline().__class__ is TrainMeanBaseline
    with pytest.raises(ModelError, match="before fit"):
        TrainMeanBaseline().predict(train)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_match_hand_computed_values():
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    truth = pd.Series([10.0, 20.0, -5.0, 0.0], index=index)
    pred = pd.Series([12.0, 18.0, -1.0, 2.0], index=index)
    # errors: +2, -2, +4, +2  ->  MAE 2.5, RMSE sqrt(28/4)=sqrt(7), bias 1.5
    s = score(truth, pred)
    assert s == Scores(
        n=4, n_scored=4, n_missing_prediction=0,
        mae=2.5, rmse=float(np.sqrt(7.0)), bias=1.5,
    )
    assert s.coverage == 1.0


def test_missing_predictions_are_counted_not_quietly_dropped():
    """A model that declines to predict must not look better for it."""
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    truth = pd.Series([10.0, 20.0, 30.0, 40.0], index=index)
    pred = pd.Series([10.0, 20.0, 30.0, np.nan], index=index)
    s = score(truth, pred)
    assert (s.n, s.n_scored, s.n_missing_prediction) == (4, 3, 1)
    assert s.coverage == pytest.approx(0.75)
    assert s.mae == 0.0


def test_rmae_and_skill_compare_on_identical_hours():
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    truth = pd.Series([10.0, 20.0, 30.0, 40.0], index=index)
    good = pd.Series([11.0, 21.0, 31.0, 41.0], index=index)
    poor = pd.Series([14.0, 24.0, 34.0, 44.0], index=index)
    assert rmae(truth, good, poor) == pytest.approx(0.25)
    assert skill_score(truth, good, poor) == pytest.approx(0.75)
    assert mae(truth, good) == pytest.approx(1.0)
    with pytest.raises(MetricError, match="undefined"):
        rmae(truth, good, truth)
    with pytest.raises(MetricError, match="share an index"):
        score(truth, good.iloc[:-1])


# ---------------------------------------------------------------------------
# PLAN.md's three leakage assertions
# ---------------------------------------------------------------------------


def test_shifting_the_feature_matrix_forward_one_day_degrades_metrics(matrix, eval_days):
    """(i) Alignment must matter, in both directions.

    A one-day-staler feature matrix must score worse. So must a one-day-fresher
    one — for a weekly-seasonal model, ``price_lag_168h`` shifted either way stops
    being the same weekday, so the *sign* of the shift effect is not itself a
    leakage detector. What this establishes is that the harness is sensitive to
    time at all, which is the precondition for the guard test below meaning
    anything.
    """
    experiment = dx.day_shift_experiment(
        matrix, NaiveLastWeek, eval_days, SPEC, shifts=(0, 1, -1)
    )
    by_shift = experiment.by_shift()
    assert by_shift[1].mae > by_shift[0].mae, "one day staler must be worse"
    assert by_shift[-1].mae > by_shift[0].mae, "one day misaligned must be worse"
    assert experiment.degrades_everywhere()
    assert experiment.as_dict()["degrades_for_every_shift"] is True


def test_guard_catches_a_deliberately_inserted_future_feature(matrix, eval_days):
    """(ii) A column built from prices after gate closure must be rejected.

    Both smuggling routes are closed: declared honestly, the gate-closure
    comparison rejects it; declared not at all, the guard fails closed.
    """
    declared = dx.guard_catches_future_feature(matrix, lead_hours=24, declare=True)
    assert [(v.kind, v.column) for v in declared] == [
        ("after_gate_closure", "price_lead_24h")
    ]
    assert declared[0].n_rows > 0.9 * len(matrix.index)
    assert declared[0].worst_lateness >= pd.Timedelta(days=1)

    undeclared = dx.guard_catches_future_feature(matrix, lead_hours=24, declare=False)
    assert [(v.kind, v.column) for v in undeclared] == [("undeclared", "price_lead_24h")]

    injected = dx.inject_future_feature(matrix, 24, declare=True)
    with pytest.raises(LeakageError, match="price_lead_24h"):
        injected.assert_clean()
    with pytest.raises(LeakageError, match="price_lead_24h"):
        run_walk_forward(injected, NaiveLastWeek, eval_days[:14], SPEC)


def test_a_future_feature_would_have_been_worth_a_lot():
    """The number that makes the guard feel necessary rather than bureaucratic.

    Measured on a **persistence-dominated** series (a random walk), where what a
    leak buys is unambiguous: tomorrow's price is close to today's, last week's is
    a week of accumulated drift away. On the week-periodic series the other tests
    use, last-week is nearly perfect by construction and a 24-hour lead is
    *worse* — which says something about that synthetic series, not about leakage,
    and is precisely why this test builds its own.
    """
    class Cheat:
        name = "cheat_lead_24h"

        def fit(self, train):
            return self

        def predict(self, test):
            return test.features["price_lead_24h"]

    walk = build_features(_random_walk_prices(_utc_index("2021-01-01", 500)), ZONE)
    days = evaluation_days(walk, [2022])[:28]
    injected = dx.inject_future_feature(walk, 24, declare=True)
    honest = run_walk_forward(walk, NaiveLastWeek, days, SPEC)
    cheating = run_walk_forward(injected, Cheat, days, SPEC, check_leakage=False)
    assert mae(cheating.y_true, cheating.y_pred) < 0.5 * mae(honest.y_true, honest.y_pred)


def test_target_permutation_destroys_skill(matrix, eval_days):
    """(iii) With shuffled targets the pipeline must lose every advantage.

    Skill is measured against a train-mean baseline run through the same harness,
    so the comparison cannot be an artefact of two different evaluation sets. The
    hour-wise shuffle is the pass/fail probe; the whole-day shuffle, which
    preserves the within-day shape, is asserted separately and more weakly.
    """
    hourly = dx.target_permutation_experiment(
        matrix, NaiveLastWeek, eval_days, SPEC, seed=11, mode="hours"
    )
    assert hourly.real_skill > 0.3, "the naive baseline must beat a constant mean"
    assert hourly.permuted_skill <= 0.0, "shuffled targets must leave no skill at all"
    assert hourly.permuted_scores.mae > 2 * hourly.real_scores.mae
    assert hourly.destroys_skill()

    daily = dx.target_permutation_experiment(
        matrix, NaiveLastWeek, eval_days, SPEC, seed=11, mode="days"
    )
    assert daily.permuted_skill < 0.5 * daily.real_skill
    assert daily.as_dict()["mode"] == "days"


def test_permutation_keeps_the_index_and_the_price_distribution(matrix):
    permuted = dx.permute_target(matrix, seed=3, mode="hours")
    assert permuted.index.equals(matrix.index)
    assert sorted(permuted.target.to_numpy()) == pytest.approx(
        sorted(matrix.target.to_numpy())
    )
    assert not np.allclose(permuted.target.to_numpy(), matrix.target.to_numpy())
    by_day = dx.permute_target(matrix, seed=3, mode="days")
    assert by_day.target.mean() == pytest.approx(matrix.target.mean(), rel=0.02)
    with pytest.raises(ValueError, match="unknown permutation mode"):
        dx.permute_target(matrix, mode="sideways")


def test_future_feature_helper_refuses_a_non_positive_lead(matrix):
    with pytest.raises(ValueError, match="must be positive"):
        dx.future_feature(matrix, lead_hours=0)
