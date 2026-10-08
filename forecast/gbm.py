"""GBM — the gradient-boosted tree day-ahead price model (PLAN.md C9).

The third and last model of the family. LEAR (C4) is the linear reference a desk
reaches for first; this is the non-linear one it reaches for second, and the
question it exists to answer is narrow: **is there structure in these features
that a per-hour LASSO cannot express?** Price formation is a merit-order stack —
piecewise, kinked, saturating — so a tree ensemble is the natural second shape,
and residual load is exactly the kind of column whose effect on price is flat
over most of its range and violent at the top of it.

PLAN.md is explicit and restrictive about how this is allowed to be built:

    **one fixed LightGBM config, in-fold early stopping, no hyperparameter
    search across cycles.**

That restriction is not frugality, it is the only defence this execution model
has. Validation metrics are visible to every cycle; a booster has a dozen knobs;
nudging any of them after seeing a 2024 number and keeping the nudge is
overfitting the validation year through the agent rather than through the code,
and it would leave no trace in the diff. So :class:`GbmSpec` is frozen,
fingerprinted, and pinned by ``tests/test_c9_gbm.py`` against the literal values
below — a later silent tweak surfaces as a failing test, not as drift. Every
value is either a LightGBM default or a standard, defensible choice stated with
its reason; none of them was chosen by looking at a score.

Four decisions carry this module.

**Pooled over delivery hours, with the hour as a categorical feature — not 24
models.** This is the deliberate asymmetry with LEAR, and it is how a booster is
actually used. LEAR partitions because a 30-parameter linear model per hour is
estimable from ~1 000 rows and pooling would force one slope to describe hour 03
and hour 18 at once. A tree ensemble has the opposite problem: splitting the
sample 24 ways starves every one of the 24 boosters, while a single pooled model
can *learn* the hour interaction from a split on ``hour_of_day_local`` wherever
the data supports one and ignore it where it does not. The consequence is stated
rather than hidden: a GBM-vs-LEAR difference is a difference of functional form
**and** of pooling, and this module cannot separate the two. What it can do is
measure the same four exogenous arms LEAR was measured on, so the *vintage
premium* — the within-model difference C8's FINDING C8-A turns on — is measured
again under a second functional form instead of being inherited from the first.

**The target transform is LEAR's, imported rather than re-implemented.** The
asinh VST with the in-fold median/MAD, inverted exactly by ``sinh``, is applied
to the target here too, and the helpers come straight from :mod:`forecast.lear`
on purpose: an *identical* transform is what makes the model comparison a
comparison of functional form rather than of loss scale, and importing is the
only way to guarantee it stays identical as the code moves. Trees are invariant
to monotone transforms of a *feature*, so no feature is transformed (the lear
module's per-column price VST is pointless here and is not used); they are very
much not invariant to one of the *target*, because L2 boosting on raw European
power prices spends its whole budget on the 2022 spikes.

**Early stopping is in-fold, and the fold is split by time.** The number of
boosting rounds is the one quantity that must adapt per fold, and the only honest
place to choose it is inside the training window. The last
``early_stopping_days`` *market days* of the window become the stopping set and
everything before them is the fitting set; the split is strictly time-ordered,
the stopping set never touches the test fold, and both sets sit entirely before
the fold's gate closure (the harness has already asserted that for the window as
a whole). The chosen round count is reported per fold so a run that always hits
the cap is visible rather than silent. With ``refit_on_full_window`` the model is
then refit on the *whole* training window for that many rounds, so the most
recent — and in power prices the most relevant — days are not thrown away by the
act of choosing a round count. That second fit sees the stopping days' targets,
which is in-fold model selection, not leakage: every one of those days was
published before the fold's gate closure.

**Missing cells are routed, not invented.** LightGBM takes NaN natively and
learns a default side for each split, so under the default
``nan_policy="native"`` the booster predicts hours that LEAR declines — a real
property of the model, not a trick, but one that makes raw coverage differ
between the two. The runner therefore scores every comparison on the hours *all*
models and arms predicted, and ``nan_policy="decline"`` is available to mirror
LEAR's listwise refusal exactly. Note what the routing can and cannot do: the
gate-closure mask writes NaN into cells that were not yet public, so missingness
is itself a pattern the booster can split on — but it is a pattern derived from
the publication calendar, which is public, and never from the target.

Deliberately **not** here: no hyperparameter search, no early-stopping metric
other than the training objective's own L2 in VST space (choosing the stopping
metric to match the reported metric is metric-chasing by another route), no
clipping of the back-transformed prediction, and no per-hour models.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from forecast.features import FeatureMatrix
from forecast.lear import CATEGORICAL_CALENDAR, HOUR_KEYS, _asinh, _inverse_asinh, _vst_params
from forecast.models import ModelError

NAN_POLICIES = ("native", "decline")

#: Calendar columns handed to LightGBM as unordered categories. Read from the
#: same two constants LEAR encodes one-hot, so the two models cannot disagree
#: about what is a category and what is a number.
CATEGORICAL_FEATURES = tuple(CATEGORICAL_CALENDAR) + tuple(HOUR_KEYS.values())


@dataclass(frozen=True)
class GbmSpec:
    """The one fixed LightGBM configuration, and the fold-level mechanics.

    PLAN.md C9 forbids a hyperparameter search across cycles, so every value
    here is frozen and justified in advance:

    * ``learning_rate=0.05`` — below LightGBM's 0.1 default. With early stopping
      doing the round selection, a smaller step and more rounds is the standard
      bias/variance trade for a few tens of thousands of rows; it costs compute,
      not honesty.
    * ``num_leaves=31``, ``min_data_in_leaf=20`` — LightGBM's own defaults.
    * ``feature_fraction=0.9``, ``bagging_fraction=0.9``, ``bagging_freq=1`` —
      mild stochastic regularisation, the conventional starting point. Both
      seeds are fixed, so the randomness is reproducible.
    * ``lambda_l2=1.0`` — a nominal ridge on the leaf values. Zero (the default)
      leaves leaf values unshrunk on a heavy-tailed target.
    * ``num_boost_round=2000`` with ``early_stopping_rounds=50`` — a cap high
      enough that early stopping, not the cap, is what normally ends the fit.
      ``n_rounds_capped`` in the fit report says when that was not true.
    * ``deterministic=True``, ``force_row_wise=True``, ``num_threads=4``,
      ``seed=20260101`` — a bit-reproducible fit. LightGBM's histogram
      construction is otherwise thread-count dependent, which would make a run
      irreproducible on another machine for no gain.

    ``early_stopping_days=90`` is a *fold* choice, not a booster one: one quarter
    of the most recent history is enough rows (~2 160) to see a validation curve
    turn, and short enough that the fitting set still ends close to the fold.
    """

    objective: str = "regression"
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.9
    bagging_freq: int = 1
    lambda_l1: float = 0.0
    lambda_l2: float = 1.0
    num_boost_round: int = 2000
    early_stopping_rounds: int = 50
    early_stopping_days: int = 90
    refit_on_full_window: bool = True
    min_fit_rows: int = 2_000
    nan_policy: str = "native"
    vst: bool = True
    seed: int = 20260101
    num_threads: int = 4
    deterministic: bool = True

    def __post_init__(self) -> None:
        if self.nan_policy not in NAN_POLICIES:
            raise ModelError(
                f"unknown nan_policy {self.nan_policy!r}; use one of {NAN_POLICIES}"
            )
        if self.early_stopping_days < 1:
            raise ModelError("early_stopping_days must be >= 1")
        if self.early_stopping_rounds < 1:
            raise ModelError("early_stopping_rounds must be >= 1")
        if self.num_boost_round < 1:
            raise ModelError("num_boost_round must be >= 1")
        if self.min_fit_rows < 1:
            raise ModelError("min_fit_rows must be >= 1")
        if not 0.0 < self.feature_fraction <= 1.0:
            raise ModelError("feature_fraction must be in (0, 1]")
        if not 0.0 < self.bagging_fraction <= 1.0:
            raise ModelError("bagging_fraction must be in (0, 1]")

    def booster_params(self) -> dict[str, Any]:
        """Exactly what is handed to LightGBM. Nothing is added at fit time."""
        return {
            "objective": self.objective,
            "metric": "l2",
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "min_data_in_leaf": self.min_data_in_leaf,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "lambda_l1": self.lambda_l1,
            "lambda_l2": self.lambda_l2,
            "seed": self.seed,
            "bagging_seed": self.seed,
            "feature_fraction_seed": self.seed,
            "data_random_seed": self.seed,
            "num_threads": self.num_threads,
            "deterministic": self.deterministic,
            "force_row_wise": True,
            "verbosity": -1,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "booster_params": self.booster_params(),
            "num_boost_round": self.num_boost_round,
            "early_stopping_rounds": self.early_stopping_rounds,
            "early_stopping_days": self.early_stopping_days,
            "refit_on_full_window": self.refit_on_full_window,
            "min_fit_rows": self.min_fit_rows,
            "nan_policy": self.nan_policy,
            "vst": self.vst,
            "fingerprint": self.fingerprint(),
        }

    def fingerprint(self) -> str:
        """A short hash of every committed value, recorded beside each result row.

        Two runs with the same fingerprint used the same configuration; a cycle
        that quietly changed one knob cannot produce a row that claims otherwise.
        """
        payload = {
            "booster_params": self.booster_params(),
            "num_boost_round": self.num_boost_round,
            "early_stopping_rounds": self.early_stopping_rounds,
            "early_stopping_days": self.early_stopping_days,
            "refit_on_full_window": self.refit_on_full_window,
            "min_fit_rows": self.min_fit_rows,
            "nan_policy": self.nan_policy,
            "vst": self.vst,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class GbmFitReport:
    """What one fold's fit did: the split, the rounds chosen, what was dropped."""

    spec: dict[str, Any] = field(default_factory=dict)
    n_train_rows: int = 0
    n_train_rows_usable: int = 0
    n_train_rows_dropped_target_nan: int = 0
    n_fit_rows: int = 0
    n_stopping_rows: int = 0
    fit_first_day: str | None = None
    fit_last_day: str | None = None
    stopping_first_day: str | None = None
    stopping_last_day: str | None = None
    n_features: int = 0
    categorical_features: list[str] = field(default_factory=list)
    best_iteration: int = 0
    n_rounds_used: int = 0
    n_trees_in_booster: int = 0
    n_rounds_capped: bool = False
    best_stopping_score: float = float("nan")
    refit_on_full_window: bool = False
    target_centre: float = float("nan")
    target_scale: float = float("nan")
    target_scale_degenerate: bool = False
    n_predict_rows: int = 0
    n_predict_declined_nan: int = 0
    n_predict_rows_with_any_nan: int = 0
    predicted_min: float = float("nan")
    predicted_max: float = float("nan")

    def as_dict(self) -> dict[str, Any]:
        def _round(value: float, digits: int = 6) -> float | None:
            return None if not np.isfinite(value) else round(float(value), digits)

        return {
            "spec": dict(self.spec),
            "n_train_rows": self.n_train_rows,
            "n_train_rows_usable": self.n_train_rows_usable,
            "n_train_rows_dropped_target_nan": self.n_train_rows_dropped_target_nan,
            "n_fit_rows": self.n_fit_rows,
            "n_stopping_rows": self.n_stopping_rows,
            "fit_first_day": self.fit_first_day,
            "fit_last_day": self.fit_last_day,
            "stopping_first_day": self.stopping_first_day,
            "stopping_last_day": self.stopping_last_day,
            "n_features": self.n_features,
            "categorical_features": list(self.categorical_features),
            "best_iteration": self.best_iteration,
            "n_rounds_used": self.n_rounds_used,
            "n_trees_in_booster": self.n_trees_in_booster,
            "n_rounds_capped": self.n_rounds_capped,
            "best_stopping_score": _round(self.best_stopping_score),
            "refit_on_full_window": self.refit_on_full_window,
            "target_centre": _round(self.target_centre),
            "target_scale": _round(self.target_scale),
            "target_scale_degenerate": self.target_scale_degenerate,
            "n_predict_rows": self.n_predict_rows,
            "n_predict_declined_nan": self.n_predict_declined_nan,
            "n_predict_rows_with_any_nan": self.n_predict_rows_with_any_nan,
            "predicted_min": _round(self.predicted_min, 4),
            "predicted_max": _round(self.predicted_max, 4),
        }


def early_stopping_split(
    market_day: pd.Series, early_stopping_days: int
) -> tuple[np.ndarray, np.ndarray, list[dt.date], list[dt.date]]:
    """Split a training window into (fit, stopping) row masks, by time.

    The last ``early_stopping_days`` distinct market days of the window become the
    stopping set; everything strictly before them is the fitting set. Splitting on
    *days* rather than rows keeps a market day whole — half of a day in each set
    would put a row's own near neighbours on the other side of the split and make
    the stopping curve optimistic.

    Raises if the window has no day left to fit on, rather than returning an empty
    fitting set and letting LightGBM produce a constant.
    """
    days = sorted(set(market_day.dropna().tolist()))
    if not days:
        raise ModelError("cannot split an empty training window for early stopping")
    if len(days) <= early_stopping_days:
        raise ModelError(
            f"training window has {len(days)} market day(s), which is not more than "
            f"early_stopping_days={early_stopping_days}: there would be nothing left "
            f"to fit on. Raise min_train_days or lower early_stopping_days."
        )
    stopping_days = days[-early_stopping_days:]
    fit_days = days[: -early_stopping_days]
    stopping_set = set(stopping_days)
    is_stopping = market_day.isin(stopping_set).to_numpy()
    is_fit = market_day.isin(set(fit_days)).to_numpy()
    return is_fit, is_stopping, fit_days, stopping_days


class GbmModel:
    """LightGBM over the pooled hours, early-stopped in-fold, VST target.

    Satisfies :class:`forecast.models.Model`, so the walk-forward harness drives
    it exactly as it drives LEAR and the naive floor — same folds, same
    gate-closure guard on both matrices, same refusal of sealed years. The model
    never reads ``test.target``: :meth:`predict` touches only ``test.features``.
    """

    def __init__(self, spec: GbmSpec | None = None, name: str | None = None) -> None:
        self.spec = spec or GbmSpec()
        self.name = name or "gbm_lightgbm"
        self.booster_: Any | None = None
        self.n_iteration_: int = 0
        self.feature_names_: tuple[str, ...] = ()
        self.categorical_: tuple[str, ...] = ()
        self.target_centre_: float = 0.0
        self.target_scale_: float = 1.0
        self.report_: GbmFitReport | None = None

    # -- design ------------------------------------------------------------

    def _design(self, frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
        """Numeric-only frame in the fitted column order, categoricals as codes.

        LightGBM wants an integer code for a categorical feature. The codes here
        are the *values themselves* (hour 0-23, ISO weekday, month 1-12), not
        positions in a fitted level list, so a level the training window never saw
        cannot shift the meaning of another level — the booster simply has no
        split on it and the row falls to whichever side the fit learned.
        """
        missing = [c for c in columns if c not in frame.columns]
        if missing:
            raise ModelError(f"feature frame is missing fitted column(s) {missing}")
        design = frame.loc[:, list(columns)].astype("float64")
        return design

    # -- fitting -----------------------------------------------------------

    def fit(self, train: FeatureMatrix) -> "GbmModel":
        import lightgbm as lgb

        spec = self.spec
        frame = train.features
        columns = tuple(frame.columns)
        if not columns:
            raise ModelError(f"{self.name}: the training matrix has no feature column")
        categorical = tuple(c for c in CATEGORICAL_FEATURES if c in columns)

        target = train.target.to_numpy(dtype="float64")
        usable = np.isfinite(target)
        report = GbmFitReport(
            spec=spec.as_dict(),
            n_train_rows=int(len(frame)),
            n_train_rows_usable=int(usable.sum()),
            n_train_rows_dropped_target_nan=int((~usable).sum()),
            n_features=len(columns),
            categorical_features=list(categorical),
            refit_on_full_window=spec.refit_on_full_window,
        )
        if report.n_train_rows_usable < spec.min_fit_rows:
            raise ModelError(
                f"{self.name}: {report.n_train_rows_usable} training row(s) have a "
                f"finite target, below min_fit_rows={spec.min_fit_rows}. That is a "
                f"data problem to look at, not a fit to attempt."
            )

        design = self._design(frame, columns)
        market_day = train.market_day[usable]
        X = design.to_numpy(dtype="float64")[usable]
        y = target[usable]

        # In-fold VST of the target, on the whole training window. Centre and
        # scale are frozen here and inverted — never recomputed — at predict time.
        if spec.vst:
            centre, scale, degenerate = _vst_params(y)
            y_t = _asinh(y, centre, scale)
        else:
            centre, scale, degenerate = 0.0, 1.0, False
            y_t = y
        report.target_centre, report.target_scale = float(centre), float(scale)
        report.target_scale_degenerate = bool(degenerate)
        self.target_centre_, self.target_scale_ = float(centre), float(scale)

        is_fit, is_stopping, fit_days, stopping_days = early_stopping_split(
            market_day, spec.early_stopping_days
        )
        report.n_fit_rows = int(is_fit.sum())
        report.n_stopping_rows = int(is_stopping.sum())
        report.fit_first_day = fit_days[0].isoformat()
        report.fit_last_day = fit_days[-1].isoformat()
        report.stopping_first_day = stopping_days[0].isoformat()
        report.stopping_last_day = stopping_days[-1].isoformat()
        if fit_days[-1] >= stopping_days[0]:
            raise ModelError(
                f"{self.name}: the early-stopping split is not time-ordered "
                f"({fit_days[-1]} >= {stopping_days[0]})"
            )

        params = spec.booster_params()
        dataset_kwargs = {
            "feature_name": list(columns),
            "categorical_feature": list(categorical),
            "free_raw_data": False,
        }
        fit_set = lgb.Dataset(X[is_fit], label=y_t[is_fit], params=params, **dataset_kwargs)
        stopping_set = lgb.Dataset(
            X[is_stopping], label=y_t[is_stopping], params=params,
            reference=fit_set, **dataset_kwargs,
        )
        stopped = lgb.train(
            params,
            fit_set,
            num_boost_round=spec.num_boost_round,
            valid_sets=[stopping_set],
            valid_names=["in_fold_stopping"],
            callbacks=[
                lgb.early_stopping(spec.early_stopping_rounds, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )
        best = int(stopped.best_iteration or stopped.current_iteration())
        report.best_iteration = best
        report.n_rounds_capped = best >= spec.num_boost_round
        best_scores = stopped.best_score.get("in_fold_stopping", {}) if stopped.best_score else {}
        if best_scores:
            report.best_stopping_score = float(next(iter(best_scores.values())))

        if spec.refit_on_full_window:
            # Refit on every row of the training window for the round count the
            # stopping set chose. Those rows were all published before the fold's
            # gate closure (the harness asserts it), so this is in-fold model
            # selection, not a peek forward — and it keeps the most recent 90 days,
            # the ones most like the day being predicted, inside the fit.
            full_set = lgb.Dataset(X, label=y_t, params=params, **dataset_kwargs)
            self.booster_ = lgb.train(
                params, full_set, num_boost_round=best,
                callbacks=[lgb.log_evaluation(period=0)],
            )
        else:
            self.booster_ = stopped
        # `lgb.train` does not discard the ``early_stopping_rounds`` trees built
        # *after* the best iteration — it only records which iteration was best.
        # So the booster generally holds more trees than the model should use, and
        # predicting with all of them would quietly serve the overfit tail that
        # early stopping existed to reject. The round count is therefore carried
        # explicitly and passed to every predict call.
        self.n_iteration_ = best
        report.n_rounds_used = best
        report.n_trees_in_booster = int(self.booster_.num_trees())

        self.feature_names_ = columns
        self.categorical_ = categorical
        self.report_ = report
        return self

    # -- predicting --------------------------------------------------------

    def predict(self, test: FeatureMatrix) -> pd.Series:
        if self.booster_ is None or self.report_ is None:
            raise ModelError(f"{self.name}.predict called before fit")
        frame = test.features
        design = self._design(frame, self.feature_names_)
        X = design.to_numpy(dtype="float64")

        report = self.report_
        report.n_predict_rows = int(len(frame))
        has_nan = ~np.isfinite(X).all(axis=1)
        report.n_predict_rows_with_any_nan = int(has_nan.sum())

        out = np.full(len(frame), np.nan, dtype="float64")
        if self.spec.nan_policy == "decline":
            usable = ~has_nan
            report.n_predict_declined_nan = int(has_nan.sum())
        else:
            usable = np.ones(len(frame), dtype=bool)
            report.n_predict_declined_nan = 0
        if usable.any():
            z = np.asarray(
                self.booster_.predict(X[usable], num_iteration=self.n_iteration_),
                dtype="float64",
            )
            out[usable] = (
                _inverse_asinh(z, self.target_centre_, self.target_scale_)
                if self.spec.vst
                else z
            )

        finite = out[np.isfinite(out)]
        if finite.size:
            report.predicted_min = float(finite.min())
            report.predicted_max = float(finite.max())
        return pd.Series(out, index=test.index, name=self.name)

    # -- reporting ---------------------------------------------------------

    def fit_report(self) -> dict[str, Any]:
        if self.report_ is None:
            raise ModelError(f"{self.name}.fit_report called before fit")
        return self.report_.as_dict()

    def feature_importance(self) -> dict[str, float]:
        """Split-gain importance per feature, normalised to sum to 1.

        Reported for the *last* fold of a run only, as a description of what the
        booster leaned on — never as a feature-selection step, which would be a
        search by another name.
        """
        if self.booster_ is None:
            raise ModelError(f"{self.name}.feature_importance called before fit")
        gains = np.asarray(
            self.booster_.feature_importance(importance_type="gain"), dtype="float64"
        )
        total = float(gains.sum())
        if total <= 0.0:
            return {name: 0.0 for name in self.feature_names_}
        return {
            name: round(float(gain) / total, 6)
            for name, gain in zip(self.feature_names_, gains)
        }


def gbm_factory(spec: GbmSpec | None = None, name: str | None = None):
    """A zero-argument factory for the harness, which refits per fold.

    The harness calls the factory once per fold precisely so no fold can inherit
    a booster fitted on another fold's data, so this must build a *new* model
    every call rather than hand back a shared one.
    """
    resolved = spec or GbmSpec()
    return lambda: GbmModel(resolved, name=name)
