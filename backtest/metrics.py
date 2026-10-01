"""Point-forecast metrics. The minimum C3 needs, and no more.

PLAN.md gives C12 the full metrics layer — daily-spread error, within-day
Spearman, capture ratio, block-bootstrap confidence intervals. This module
deliberately stops at the three numbers the C3 leakage assertions need in order
to say "that made things worse": MAE, RMSE, and rMAE against a naive reference.

**sMAPE is absent on purpose** (PLAN.md): with negative and near-zero clearing
prices a percentage error is not just noisy, it changes sign.

Missing values are counted, never quietly dropped into a smaller denominator: a
model that declines to predict 5% of hours must not thereby look 5% better.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class MetricError(RuntimeError):
    """A metric was asked for on data that cannot support it."""


@dataclass(frozen=True)
class Scores:
    """One model's error on one evaluation set."""

    n: int
    n_scored: int
    n_missing_prediction: int
    mae: float
    rmse: float
    bias: float

    @property
    def coverage(self) -> float:
        return float(self.n_scored) / float(self.n) if self.n else float("nan")

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "n_scored": self.n_scored,
            "n_missing_prediction": self.n_missing_prediction,
            "coverage": round(self.coverage, 6),
            "mae": round(self.mae, 6),
            "rmse": round(self.rmse, 6),
            "bias": round(self.bias, 6),
        }


def _aligned(y_true: pd.Series, y_pred: pd.Series) -> tuple[pd.Series, pd.Series, int]:
    if not y_true.index.equals(y_pred.index):
        raise MetricError("y_true and y_pred must share an index")
    both = y_true.notna() & y_pred.notna()
    n_missing = int((y_true.notna() & y_pred.isna()).sum())
    return y_true[both], y_pred[both], n_missing


def score(y_true: pd.Series, y_pred: pd.Series) -> Scores:
    """MAE / RMSE / bias, with the scored and unscored counts kept visible."""
    truth, pred, n_missing = _aligned(y_true, y_pred)
    if truth.empty:
        raise MetricError("no overlapping non-missing rows to score")
    error = pred.to_numpy(dtype="float64") - truth.to_numpy(dtype="float64")
    return Scores(
        n=int(len(y_true)),
        n_scored=int(len(truth)),
        n_missing_prediction=n_missing,
        mae=float(np.mean(np.abs(error))),
        rmse=float(np.sqrt(np.mean(error**2))),
        bias=float(np.mean(error)),
    )


def mae(y_true: pd.Series, y_pred: pd.Series) -> float:
    return score(y_true, y_pred).mae


def rmse(y_true: pd.Series, y_pred: pd.Series) -> float:
    return score(y_true, y_pred).rmse


def rmae(y_true: pd.Series, y_pred: pd.Series, y_reference: pd.Series) -> float:
    """Relative MAE against a reference forecast. ``< 1`` beats the reference.

    Scored on the rows where *all three* series are present, so the ratio is a
    comparison on identical hours rather than two different samples.
    """
    for name, series in (("y_pred", y_pred), ("y_reference", y_reference)):
        if not y_true.index.equals(series.index):
            raise MetricError(f"{name} must share the index of y_true")
    both = y_true.notna() & y_pred.notna() & y_reference.notna()
    if not bool(both.any()):
        raise MetricError("no rows where truth, prediction and reference are all present")
    model = mae(y_true[both], y_pred[both])
    reference = mae(y_true[both], y_reference[both])
    if reference == 0.0:
        raise MetricError("reference MAE is zero — rMAE is undefined")
    return float(model / reference)


def skill_score(y_true: pd.Series, y_pred: pd.Series, y_reference: pd.Series) -> float:
    """``1 - MAE(model)/MAE(reference)``: 0 means no better than the reference.

    Used by the C3 target-permutation assertion, where the reference is the
    training-set mean: a model with real skill scores well above 0, and a model
    fitted on permuted targets must collapse to ~0 or below.
    """
    return 1.0 - rmae(y_true, y_pred, y_reference)
