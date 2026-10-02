"""Forecast models, behind one interface so the harness never special-cases them.

C3 ships the two simplest possible members of the family and the protocol that
C4's LEAR and C9's gradient booster must satisfy:

``NaiveLastWeek``
    PLAN.md's floor: the price of the same hour one week ago. It is not a
    strawman — in day-ahead power it is a genuinely hard baseline, because the
    weekly cycle carries most of the predictable shape. Any model that cannot
    beat it has learned nothing.

``TrainMeanBaseline``
    A single number: the mean price of the training window. Not a competitor —
    the denominator for the skill score in the target-permutation assertion. A
    model fitted on shuffled targets should land roughly here.

``TrainMedianBaseline``
    The same idea at the *median*, added in C4. It exists because MAE is
    minimised by the median, not the mean, and European power prices are
    strongly right-skewed (DE-LU 2019-2024: mean 95.65, median 66.18 EUR/MWh —
    the 2022 crisis). So a zero-information constant placed at the median beats
    one placed at the mean by ~7% of MAE, and any median-like estimator inherits
    that margin for free. Without this reference, that free margin is
    indistinguishable from skill — see FINDING C4-A.

A model receives the whole :class:`~forecast.features.FeatureMatrix`, not a bare
array, so it cannot accidentally be handed a frame whose information times
nobody checked.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from forecast.features import FeatureMatrix


class ModelError(RuntimeError):
    """A model was asked to do something its inputs do not support."""


@runtime_checkable
class Model(Protocol):
    """Fit on one matrix, predict on another. Never sees a raw future price."""

    name: str

    def fit(self, train: FeatureMatrix) -> "Model": ...

    def predict(self, test: FeatureMatrix) -> pd.Series: ...


class NaiveLastWeek:
    """Same hour, one week back. Stateless: ``fit`` has nothing to learn.

    The prediction is read from the committed ``price_lag_168h`` feature rather
    than recomputed from the price series, so the baseline is subject to exactly
    the same gate-closure guard and the same masking as every other feature. If
    that column is ever masked or missing, the naive forecast is missing too —
    which is the truth, not a value to invent.
    """

    name = "naive_last_week"
    required_column = "price_lag_168h"

    def __init__(self, column: str | None = None) -> None:
        self.column = column or self.required_column

    def fit(self, train: FeatureMatrix) -> "NaiveLastWeek":
        if self.column not in train.features.columns:
            raise ModelError(
                f"{self.name} needs the {self.column!r} feature; matrix has "
                f"{list(train.features.columns)}"
            )
        return self

    def predict(self, test: FeatureMatrix) -> pd.Series:
        if self.column not in test.features.columns:
            raise ModelError(f"{self.name} needs the {self.column!r} feature")
        return test.features[self.column].rename(self.name).astype("float64")


class TrainMeanBaseline:
    """Predicts the mean target of the training window, for every hour.

    The reference against which "did this model learn anything at all?" is asked.
    """

    name = "train_mean"

    def __init__(self) -> None:
        self.mean_: float | None = None

    def fit(self, train: FeatureMatrix) -> "TrainMeanBaseline":
        target = train.target.dropna()
        if target.empty:
            raise ModelError("cannot fit a mean baseline on an empty training target")
        self.mean_ = float(target.mean())
        return self

    def predict(self, test: FeatureMatrix) -> pd.Series:
        if self.mean_ is None:
            raise ModelError("TrainMeanBaseline.predict called before fit")
        return pd.Series(
            np.full(len(test.index), self.mean_, dtype="float64"),
            index=test.index,
            name=self.name,
        )


class TrainMedianBaseline:
    """Predicts the median target of the training window, for every hour.

    The reference that separates "this model knows something about *this* hour"
    from "this model is shaped like a median and the metric is MAE". A LASSO
    fitted in asinh space and mapped back through ``sinh`` is the latter, which
    is why :class:`TrainMeanBaseline` alone cannot answer the question (FINDING
    C4-A): on a right-skewed price distribution a mean reference hands any such
    model several percent of apparent skill before it has learned anything.
    """

    name = "train_median"

    def __init__(self) -> None:
        self.median_: float | None = None

    def fit(self, train: FeatureMatrix) -> "TrainMedianBaseline":
        target = train.target.dropna()
        if target.empty:
            raise ModelError("cannot fit a median baseline on an empty training target")
        self.median_ = float(target.median())
        return self

    def predict(self, test: FeatureMatrix) -> pd.Series:
        if self.median_ is None:
            raise ModelError("TrainMedianBaseline.predict called before fit")
        return pd.Series(
            np.full(len(test.index), self.median_, dtype="float64"),
            index=test.index,
            name=self.name,
        )
