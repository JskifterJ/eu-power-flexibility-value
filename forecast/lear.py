"""LEAR — the regularised linear day-ahead price model (PLAN.md C4).

LEAR is the standard open-benchmark linear model for day-ahead power prices
(Uniejewski/Weron/Ziel's variance-stabilised LASSO, as consolidated in Lago et
al. 2021): **one LASSO per delivery hour**, fitted on variance-stabilised
prices, with the regularisation strength chosen *inside* the fold. It is the
model a desk would actually reach for first, and it is a much harder reference
than the naive floor because it can mix the weekly cycle, the day-before level
and the calendar shape instead of copying one of them.

Four properties are load-bearing here, and each one is a place where a price
model usually goes quietly wrong.

**Per delivery hour, not per timestamp.** Hour 03 and hour 18 are different
products with different drivers; pooling them makes one model that is wrong
about both. So there are 24 independent LASSOs, partitioned by the *local*
delivery hour — the hour the market actually trades, which is what
``hour_of_day_local`` already carries. CLAUDE.md forbids using local time for
*resampling or alignment*; this is neither — no row moves, nothing is
reindexed, the matrix is only grouped. The partition key is itself a declared,
gate-closure-checked feature column, so the thing that decides which model sees
a row is subject to the same guard as everything else. ``hour_key="utc"``
selects the alternative, which blurs each model across two local hours as DST
moves, and is kept only so the choice is visible rather than baked in.

**Everything is fitted in-fold.** Medians, MADs, standardisation, the one-hot
levels, and the LASSO penalty are all estimated on the training window alone
and then *applied* — never recomputed — at predict time. Scaling on the pooled
train+test sample is the classic invisible leak: it does not look like a future
price anywhere in the code, and it still lets the test set vote on the fit. The
test suite asserts the invariance directly (a row's prediction does not move
when the rest of the test set is replaced).

**The asinh variance-stabilising transform, inverted exactly.** Power prices
are heavy-tailed and go negative, so a log is unavailable and an untransformed
LASSO spends its whole budget on the 2022 spikes. ``asinh((y - a) / b)`` with
``a`` the in-fold median and ``b`` the in-fold MAD is defined on the whole real
line, is near-linear in the body of the distribution and compresses the tails.
Predictions are mapped back with ``a + b * sinh(z)``, the exact inverse.

**NaN is answered, not absorbed.** The gate-closure mask leaves genuine holes
(one per autumn DST day even in a plain 24-hour lag — FINDING C3-A) and the lag
warm-up leaves more. LASSO cannot take NaN, so a policy is required, and the
honest ones are narrow:

* *training rows* with any missing design cell are **dropped from the fit**
  (listwise). Nothing is invented; the count is reported per hour-model.
* *test rows* with any missing design cell get **no prediction** under the
  default ``nan_policy="decline"``. :mod:`backtest.metrics` counts a declined
  hour as missing rather than silently shrinking the denominator, so declining
  costs the model coverage and cannot flatter it. ``nan_policy="impute"``
  substitutes the in-fold column median instead, and is offered for later
  cycles that need full coverage — it is a choice to be stated in a results
  table, not a default.

Deliberately **not** here: no hyperparameter search across cycles (PLAN.md —
the penalty is selected in-fold, per fold, by a fixed rule), no feature
selection by hand, no clipping of the back-transformed prediction (a run that
produces an absurd price should show an absurd number, not a tidied one; the
fit report carries the predicted min/max so it is visible).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LassoCV, LassoLarsIC
from sklearn.model_selection import TimeSeriesSplit

from forecast.features import FeatureMatrix
from forecast.models import ModelError

#: MAD -> sigma for a normal sample. Keeps ``b`` on a standard-deviation scale.
MAD_TO_SIGMA = 1.4826

#: Calendar columns treated as unordered categories and one-hot encoded.
CATEGORICAL_CALENDAR = ("day_of_week", "month")

SELECTORS = ("aic", "bic", "cv")
HOUR_KEYS = {"local": "hour_of_day_local", "utc": "hour_of_day_utc"}
NAN_POLICIES = ("decline", "impute")


@dataclass(frozen=True)
class LearSpec:
    """Every choice the model makes, in one committed object.

    ``selector`` picks the in-fold penalty rule: ``aic``/``bic`` run the LARS
    information criterion (fast, deterministic, the LEAR literature's default),
    ``cv`` runs a time-ordered cross-validation *within the training window*
    (never across it). All three are in-fold; none of them may be tuned by
    looking at backtest metrics across cycles.
    """

    selector: str = "aic"
    hour_key: str = "local"
    nan_policy: str = "decline"
    cv_splits: int = 5
    cv_alphas: int = 50
    max_iter: int = 20_000
    min_fit_rows: int = 120
    vst: bool = True

    def __post_init__(self) -> None:
        if self.selector not in SELECTORS:
            raise ModelError(f"unknown selector {self.selector!r}; use one of {SELECTORS}")
        if self.hour_key not in HOUR_KEYS:
            raise ModelError(f"unknown hour_key {self.hour_key!r}; use {sorted(HOUR_KEYS)}")
        if self.nan_policy not in NAN_POLICIES:
            raise ModelError(
                f"unknown nan_policy {self.nan_policy!r}; use one of {NAN_POLICIES}"
            )
        if self.cv_splits < 2:
            raise ModelError("cv_splits must be >= 2")
        if self.min_fit_rows < 2:
            raise ModelError("min_fit_rows must be >= 2")

    @property
    def hour_column(self) -> str:
        return HOUR_KEYS[self.hour_key]

    def as_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "hour_key": self.hour_key,
            "hour_column": self.hour_column,
            "nan_policy": self.nan_policy,
            "cv_splits": self.cv_splits,
            "cv_alphas": self.cv_alphas,
            "max_iter": self.max_iter,
            "min_fit_rows": self.min_fit_rows,
            "vst": self.vst,
        }


@dataclass
class HourFitReport:
    """What one hour-model's fit saw and threw away. Aggregated into the summary."""

    hour: int
    n_rows_available: int = 0
    n_rows_dropped_nan: int = 0
    n_rows_fitted: int = 0
    n_design_columns: int = 0
    n_dropped_constant: int = 0
    n_nonzero_coefficients: int = 0
    alpha: float = float("nan")
    target_centre: float = float("nan")
    target_scale: float = float("nan")
    degenerate_scale_columns: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "hour": self.hour,
            "n_rows_available": self.n_rows_available,
            "n_rows_dropped_nan": self.n_rows_dropped_nan,
            "n_rows_fitted": self.n_rows_fitted,
            "n_design_columns": self.n_design_columns,
            "n_dropped_constant": self.n_dropped_constant,
            "n_nonzero_coefficients": self.n_nonzero_coefficients,
            "alpha": None if np.isnan(self.alpha) else round(float(self.alpha), 10),
            "target_centre": round(float(self.target_centre), 6),
            "target_scale": round(float(self.target_scale), 6),
            "degenerate_scale_columns": list(self.degenerate_scale_columns),
        }


@dataclass
class LearFitReport:
    """The whole fit, hour by hour, plus what predict had to do about NaN."""

    spec: dict[str, Any]
    n_hours: int = 0
    n_train_rows: int = 0
    n_train_rows_fitted: int = 0
    n_train_rows_dropped_nan: int = 0
    hours: list[HourFitReport] = field(default_factory=list)
    n_predict_rows: int = 0
    n_predict_declined_nan: int = 0
    n_predict_imputed_cells: int = 0
    n_predict_unknown_hour: int = 0
    n_predict_unseen_category_rows: int = 0
    predicted_min: float = float("nan")
    predicted_max: float = float("nan")

    @property
    def train_drop_fraction(self) -> float:
        return (
            float(self.n_train_rows_dropped_nan) / float(self.n_train_rows)
            if self.n_train_rows
            else float("nan")
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": dict(self.spec),
            "n_hours": self.n_hours,
            "n_train_rows": self.n_train_rows,
            "n_train_rows_fitted": self.n_train_rows_fitted,
            "n_train_rows_dropped_nan": self.n_train_rows_dropped_nan,
            "train_drop_fraction": round(self.train_drop_fraction, 6),
            "n_predict_rows": self.n_predict_rows,
            "n_predict_declined_nan": self.n_predict_declined_nan,
            "n_predict_imputed_cells": self.n_predict_imputed_cells,
            "n_predict_unknown_hour": self.n_predict_unknown_hour,
            "n_predict_unseen_category_rows": self.n_predict_unseen_category_rows,
            "predicted_min": (
                None if np.isnan(self.predicted_min) else round(float(self.predicted_min), 4)
            ),
            "predicted_max": (
                None if np.isnan(self.predicted_max) else round(float(self.predicted_max), 4)
            ),
            "mean_nonzero_coefficients": (
                round(
                    float(np.mean([h.n_nonzero_coefficients for h in self.hours])), 3
                )
                if self.hours
                else None
            ),
            "alpha_by_hour": {h.hour: h.as_dict()["alpha"] for h in self.hours},
            "hours": [h.as_dict() for h in self.hours],
        }


def _vst_params(values: np.ndarray) -> tuple[float, float, bool]:
    """In-fold centre and scale for the asinh transform, and whether it degenerated.

    ``b`` falls back from MAD to the standard deviation when more than half the
    sample sits on one value (a MAD of zero would divide by nothing), and to 1.0
    only when the column is genuinely constant — which is reported, because a
    constant price column in a training window is a data problem, not a feature.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0, True
    centre = float(np.median(finite))
    scale = float(np.median(np.abs(finite - centre)) * MAD_TO_SIGMA)
    if scale > 0.0:
        return centre, scale, False
    fallback = float(np.std(finite))
    if fallback > 0.0:
        return centre, fallback, True
    return centre, 1.0, True


def _asinh(values: np.ndarray, centre: float, scale: float) -> np.ndarray:
    return np.arcsinh((values - centre) / scale)


def _inverse_asinh(values: np.ndarray, centre: float, scale: float) -> np.ndarray:
    return centre + scale * np.sinh(values)



@dataclass(frozen=True)
class _Encoding:
    """The fixed, in-fold recipe for turning a feature frame into a design matrix.

    Built once per hour-model from the training window and then reused verbatim:
    the same columns, the same one-hot levels, the same reference level. A test
    frame can therefore never introduce a column, and a category the training
    window never saw is counted rather than folded into the reference level
    without trace.
    """

    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    levels: dict[str, tuple[Any, ...]]
    reference: dict[str, Any]
    source_columns: tuple[str, ...]
    design_columns: tuple[str, ...]

    def build(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, int]:
        """Design matrix, per-row validity, and how many rows had an unseen category.

        Validity is read from the *source* columns, not from the finished design
        matrix: a missing ``day_of_week`` would otherwise become a row of zero
        indicators, which is a silent value rather than a missing one.
        """
        missing = [c for c in self.source_columns if c not in frame.columns]
        if missing:
            raise ModelError(f"feature frame is missing fitted column(s) {missing}")
        valid = frame[list(self.source_columns)].notna().all(axis=1).to_numpy()

        blocks: list[np.ndarray] = []
        if self.numeric:
            blocks.append(frame[list(self.numeric)].to_numpy(dtype="float64"))
        unseen = np.zeros(len(frame), dtype=bool)
        for column in self.categorical:
            values = frame[column].to_numpy()
            kept = self.levels[column]
            indicators = np.zeros((len(frame), len(kept)), dtype="float64")
            recognised = values == self.reference[column]
            for position, level in enumerate(kept):
                hit = values == level
                indicators[hit, position] = 1.0
                recognised |= hit
            unseen |= ~recognised & frame[column].notna().to_numpy()
            blocks.append(indicators)
        design = (
            np.concatenate(blocks, axis=1)
            if blocks
            else np.zeros((len(frame), 0), dtype="float64")
        )
        return design, valid, int(unseen.sum())


@dataclass
class _HourModel:
    """One delivery hour's fitted LASSO, with everything it needs to be replayed.

    Nothing here is recomputed at predict time. That is the whole point: the
    centre/scale pairs, the standardisation moments, the one-hot levels and the
    penalty are all frozen artefacts of the training window.
    """

    hour: int
    encoding: _Encoding
    vst_price: dict[str, tuple[float, float]]
    target_centre: float
    target_scale: float
    keep: np.ndarray
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float
    alpha: float
    impute_values: np.ndarray
    vst: bool

    def transform(self, design: np.ndarray) -> np.ndarray:
        """Apply the frozen VST, column drop and standardisation, in that order."""
        out = design.astype("float64", copy=True)
        for position, column in enumerate(self.encoding.numeric):
            if column in self.vst_price:
                centre, scale = self.vst_price[column]
                out[:, position] = _asinh(out[:, position], centre, scale)
        out = out[:, self.keep]
        return (out - self.mean) / self.scale

    def predict_z(self, standardised: np.ndarray) -> np.ndarray:
        return self.intercept + standardised @ self.coef

    def to_price(self, z: np.ndarray) -> np.ndarray:
        if not self.vst:
            return z
        return _inverse_asinh(z, self.target_centre, self.target_scale)


def _build_encoding(
    frame: pd.DataFrame, deterministic: tuple[str, ...], hour_column: str
) -> _Encoding:
    """Decide, from the training frame alone, how the matrix becomes a design.

    * the partition column is dropped — it is constant inside an hour-model by
      construction, so it carries no information *within* the model;
    * ``day_of_week``, ``month`` and the non-partition hour column are unordered
      categories, one-hot encoded with the lowest level as reference (so the
      block is not collinear with the intercept);
    * every remaining column — the price history, ``is_weekend`` — enters
      numerically, and the price-derived ones are variance-stabilised.
    """
    calendar = set(deterministic)
    categorical: list[str] = []
    numeric: list[str] = []
    for column in frame.columns:
        if column == hour_column:
            continue
        if column in calendar and (
            column in CATEGORICAL_CALENDAR or column in HOUR_KEYS.values()
        ):
            categorical.append(column)
        else:
            numeric.append(column)

    levels: dict[str, tuple[Any, ...]] = {}
    reference: dict[str, Any] = {}
    design_columns: list[str] = list(numeric)
    for column in categorical:
        observed = sorted(pd.unique(frame[column].dropna()).tolist())
        if not observed:
            raise ModelError(f"categorical column {column!r} is empty in the training window")
        reference[column] = observed[0]
        kept = tuple(observed[1:])
        levels[column] = kept
        design_columns.extend(f"{column}={level}" for level in kept)

    return _Encoding(
        numeric=tuple(numeric),
        categorical=tuple(categorical),
        levels=levels,
        reference=reference,
        source_columns=tuple(numeric) + tuple(categorical),
        design_columns=tuple(design_columns),
    )


class LearModel:
    """LEAR: one variance-stabilised LASSO per delivery hour, selected in-fold.

    Satisfies :class:`forecast.models.Model`, so the walk-forward harness drives
    it exactly as it drives the naive floor — same folds, same gate-closure
    guard on both the training and the test matrix, same refusal of sealed
    years. The model never sees ``test.target``: :meth:`predict` reads only
    ``test.features``.
    """

    def __init__(self, spec: LearSpec | None = None, name: str | None = None) -> None:
        self.spec = spec or LearSpec()
        self.name = name or f"lear_{self.spec.selector}"
        self.models_: dict[int, _HourModel] = {}
        self.report_: LearFitReport | None = None

    # -- fitting -----------------------------------------------------------

    def fit(self, train: FeatureMatrix) -> "LearModel":
        hour_column = self.spec.hour_column
        if hour_column not in train.features.columns:
            raise ModelError(
                f"{self.name} partitions by {hour_column!r}, which the matrix does "
                f"not carry; columns are {list(train.features.columns)}"
            )
        frame = train.features
        target = train.target.to_numpy(dtype="float64")
        hours = frame[hour_column].to_numpy()

        report = LearFitReport(spec=self.spec.as_dict(), n_train_rows=int(len(frame)))
        self.models_ = {}
        for hour in sorted(pd.unique(pd.Series(hours).dropna()).tolist()):
            rows = hours == hour
            fitted, hour_report = self._fit_hour(
                int(hour), frame.loc[rows], target[rows], train.deterministic
            )
            self.models_[int(hour)] = fitted
            report.hours.append(hour_report)
            report.n_train_rows_fitted += hour_report.n_rows_fitted
            report.n_train_rows_dropped_nan += hour_report.n_rows_dropped_nan
        if not self.models_:
            raise ModelError(f"{self.name}: no delivery hour had any training rows")
        report.n_hours = len(self.models_)
        self.report_ = report
        return self

    def _fit_hour(
        self,
        hour: int,
        frame: pd.DataFrame,
        target: np.ndarray,
        deterministic: tuple[str, ...],
    ) -> tuple[_HourModel, HourFitReport]:
        spec = self.spec
        encoding = _build_encoding(frame, deterministic, spec.hour_column)
        design, valid, _ = encoding.build(frame)
        usable = valid & np.isfinite(target)
        hour_report = HourFitReport(
            hour=hour,
            n_rows_available=int(len(frame)),
            n_rows_dropped_nan=int((~usable).sum()),
            n_rows_fitted=int(usable.sum()),
        )
        if hour_report.n_rows_fitted < spec.min_fit_rows:
            raise ModelError(
                f"{self.name}: delivery hour {hour} has {hour_report.n_rows_fitted} "
                f"complete training row(s) after dropping {hour_report.n_rows_dropped_nan} "
                f"with missing cells, below min_fit_rows={spec.min_fit_rows}. That is a "
                f"data problem to look at, not a fit to attempt."
            )

        design = design[usable]
        y = target[usable]

        # Variance-stabilise the price-derived columns and the target, each on
        # its own in-fold centre/scale. The calendar indicators are already on a
        # 0/1 scale and are left alone.
        degenerate: list[str] = []
        vst_price: dict[str, tuple[float, float]] = {}
        if spec.vst:
            price_columns = [c for c in encoding.numeric if c not in deterministic]
            for position, column in enumerate(encoding.numeric):
                if column not in price_columns:
                    continue
                centre, scale, flag = _vst_params(design[:, position])
                vst_price[column] = (centre, scale)
                design[:, position] = _asinh(design[:, position], centre, scale)
                if flag:
                    degenerate.append(column)
            target_centre, target_scale, target_flag = _vst_params(y)
            if target_flag:
                degenerate.append("target")
            y_t = _asinh(y, target_centre, target_scale)
        else:
            target_centre, target_scale = 0.0, 1.0
            y_t = y

        # Drop columns with no in-fold variation. A one-hot level that never
        # occurs in this hour's training window, or a price column that is
        # constant, carries nothing and would only destabilise the standardiser.
        column_scale = design.std(axis=0)
        keep = column_scale > 0.0
        hour_report.n_dropped_constant = int((~keep).sum())
        kept_design = design[:, keep]
        if kept_design.shape[1] == 0:
            raise ModelError(
                f"{self.name}: delivery hour {hour} has no varying design column"
            )
        mean = kept_design.mean(axis=0)
        scale = kept_design.std(axis=0)
        standardised = (kept_design - mean) / scale

        estimator = self._estimator()
        estimator.fit(standardised, y_t)
        coef = np.asarray(estimator.coef_, dtype="float64").ravel()
        alpha = float(getattr(estimator, "alpha_", float("nan")))

        hour_report.n_design_columns = int(kept_design.shape[1])
        hour_report.n_nonzero_coefficients = int(np.count_nonzero(coef))
        hour_report.alpha = alpha
        hour_report.target_centre = float(target_centre)
        hour_report.target_scale = float(target_scale)
        hour_report.degenerate_scale_columns = tuple(degenerate)

        # Column medians for nan_policy="impute", taken on the *raw* training
        # design (pre-VST) so the substituted value is a price, not a z-score.
        raw_design, raw_valid, _ = encoding.build(frame)
        impute_values = np.nanmedian(
            np.where(np.isfinite(raw_design[raw_valid]), raw_design[raw_valid], np.nan),
            axis=0,
        )

        model = _HourModel(
            hour=hour,
            encoding=encoding,
            vst_price=vst_price,
            target_centre=float(target_centre),
            target_scale=float(target_scale),
            keep=keep,
            mean=mean,
            scale=scale,
            coef=coef,
            intercept=float(estimator.intercept_),
            alpha=alpha,
            impute_values=np.nan_to_num(impute_values, nan=0.0),
            vst=bool(spec.vst),
        )
        return model, hour_report

    def _estimator(self):
        spec = self.spec
        if spec.selector in ("aic", "bic"):
            return LassoLarsIC(criterion=spec.selector, max_iter=spec.max_iter)
        # ``alphas`` as an int means "build a path of this many alphas"
        # (scikit-learn >= 1.7; requirements.txt pins the floor). The splitter is
        # time-ordered on purpose: a shuffled K-fold inside the training window
        # would let a later day pick the penalty for an earlier one.
        return LassoCV(
            cv=TimeSeriesSplit(n_splits=spec.cv_splits),
            alphas=spec.cv_alphas,
            max_iter=spec.max_iter,
        )

    # -- predicting --------------------------------------------------------

    def predict(self, test: FeatureMatrix) -> pd.Series:
        if not self.models_ or self.report_ is None:
            raise ModelError(f"{self.name}.predict called before fit")
        hour_column = self.spec.hour_column
        if hour_column not in test.features.columns:
            raise ModelError(f"{self.name} needs the {hour_column!r} feature to predict")

        frame = test.features
        hours = frame[hour_column].to_numpy()
        out = np.full(len(frame), np.nan, dtype="float64")
        report = self.report_
        report.n_predict_rows = int(len(frame))
        report.n_predict_declined_nan = 0
        report.n_predict_imputed_cells = 0
        report.n_predict_unknown_hour = 0
        report.n_predict_unseen_category_rows = 0

        for hour, model in self.models_.items():
            rows = hours == hour
            if not rows.any():
                continue
            design, valid, unseen = model.encoding.build(frame.loc[rows])
            report.n_predict_unseen_category_rows += unseen
            if self.spec.nan_policy == "impute":
                holes = ~np.isfinite(design)
                if holes.any():
                    report.n_predict_imputed_cells += int(holes.sum())
                    design = np.where(holes, model.impute_values, design)
                usable = np.ones(len(design), dtype=bool)
            else:
                usable = valid & np.isfinite(design).all(axis=1)
                report.n_predict_declined_nan += int((~usable).sum())
            if not usable.any():
                continue
            z = model.predict_z(model.transform(design[usable]))
            prices = model.to_price(z)
            block = np.full(len(design), np.nan, dtype="float64")
            block[usable] = prices
            out[rows] = block

        unknown = ~np.isin(hours, list(self.models_))
        report.n_predict_unknown_hour = int(unknown.sum())
        out[unknown] = np.nan

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


def lear_factory(spec: LearSpec | None = None, name: str | None = None):
    """A zero-argument factory for the harness, which refits per fold.

    The harness calls the factory once per fold precisely so no fold can inherit
    a model fitted on another fold's data, so the factory must build a *new*
    model every call — not hand back a shared one.
    """
    resolved = spec or LearSpec()
    return lambda: LearModel(resolved, name=name)
