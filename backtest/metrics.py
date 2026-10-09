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

from dataclasses import asdict, dataclass
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


# ---------------------------------------------------------------------------
# C12: the decision-relevant metrics (PLAN.md's "daily-spread error, within-day
# Spearman"), computed per market day so a daily-block bootstrap can resample
# them.
# ---------------------------------------------------------------------------
#
# MAE answers "how far out was the price?". A battery does not trade the level —
# it trades the *shape* of the day: how wide the trough-to-peak spread is (how
# much there is to earn) and in which order the hours fall (when to charge and
# when to discharge). Those are the two numbers PLAN.md asks for here, and
# FINDING C11-D is the reason they are worth having: across fifteen paired
# comparisons the MAE ranking and the capture ranking agreed nine times, a coin
# flip, so a point-error metric is not telling us what a dispatch metric does.
#
# Both are **per-day** statistics, and that is deliberate. A day is the unit the
# battery optimises over, the unit the capture ratio is pooled over, and the
# block the C12 bootstrap resamples — so every number in this section is built
# from a one-row-per-day table and aggregated afterwards, never the other way
# round.
#
# Nothing here drops a day quietly. A day whose realised prices are flat has no
# rank ordering to predict and its Spearman is undefined; such days are
# *counted* in ``n_days_spearman_undefined`` rather than skipped into a smaller
# and flattering denominator.


#: Fewest non-missing (truth, forecast) pairs in a day for a rank correlation to
#: mean anything. Three is the floor at which a Spearman is defined at all; real
#: market days carry 23/24/25.
MIN_HOURS_FOR_SPEARMAN = 3


def spearman_rho(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> float:
    """Tie-aware Spearman rank correlation. ``nan`` when either side is flat.

    Implemented as Pearson on average ranks rather than pulled in from
    ``scipy.stats``: that *is* the definition, it handles ties the standard way
    (``method="average"``), and it returns the coefficient without a p-value
    this project has no use for — a per-day n of 24 makes a per-day p-value
    noise, and the C12 bootstrap is where significance comes from.
    """
    left = pd.Series(np.asarray(a, dtype="float64"))
    right = pd.Series(np.asarray(b, dtype="float64"))
    both = left.notna() & right.notna()
    if int(both.sum()) < MIN_HOURS_FOR_SPEARMAN:
        return float("nan")
    ranked_left = left[both].rank(method="average").to_numpy()
    ranked_right = right[both].rank(method="average").to_numpy()
    if np.std(ranked_left) == 0.0 or np.std(ranked_right) == 0.0:
        return float("nan")
    return float(np.corrcoef(ranked_left, ranked_right)[0, 1])


def daily_shape_table(
    y_true: pd.Series, y_pred: pd.Series, day_labels: pd.Series | np.ndarray
) -> pd.DataFrame:
    """One row per market day: the error sums, the spread error, the Spearman.

    This is the table everything else in the C12 layer is built from. Every
    aggregate the cycle reports is a sum or a mean *over its rows*, which is
    what makes the daily-block bootstrap a resample of rows rather than a
    re-derivation from hours — and what makes a pooled MAE over an arbitrary day
    set a ratio of two column sums.

    Columns:

    ``n_hours``
        non-missing (truth, forecast) pairs in the day.
    ``sum_abs_error`` / ``sum_sq_error`` / ``sum_error``
        the three sums from which MAE, RMSE and bias over *any* set of these
        days follow as ratios of column sums.
    ``realised_spread`` / ``forecast_spread``
        within-day max minus min, on the realised and the forecast vector. This
        is the headroom a battery is trading and the headroom it *thought* it
        was trading.
    ``spread_error``
        ``forecast_spread - realised_spread``: positive means the forecast
        promised a wider day than arrived, which is the sign that makes a
        battery over-trade.
    ``spearman``
        within-day rank correlation of the hourly ordering — the direct measure
        of "did the forecast put the hours in the right order", which is the
        only thing the dispatch LP actually reads off the curve.
    """
    if not y_true.index.equals(y_pred.index):
        raise MetricError("y_true and y_pred must share an index")
    labels = np.asarray(day_labels)
    if len(labels) != len(y_true):
        raise MetricError(
            f"day_labels has {len(labels)} entries for {len(y_true)} rows"
        )
    frame = pd.DataFrame(
        {
            "market_day": labels,
            "y_true": y_true.to_numpy(dtype="float64"),
            "y_pred": y_pred.to_numpy(dtype="float64"),
        }
    )
    rows: list[dict[str, Any]] = []
    for day, group in frame.groupby("market_day", sort=True):
        both = group["y_true"].notna() & group["y_pred"].notna()
        truth = group.loc[both, "y_true"].to_numpy(dtype="float64")
        pred = group.loc[both, "y_pred"].to_numpy(dtype="float64")
        if truth.size == 0:
            rows.append(
                {
                    "market_day": day,
                    "n_hours": 0,
                    "n_hours_total": int(len(group)),
                    "sum_abs_error": float("nan"),
                    "sum_sq_error": float("nan"),
                    "sum_error": float("nan"),
                    "realised_spread": float("nan"),
                    "forecast_spread": float("nan"),
                    "spread_error": float("nan"),
                    "spearman": float("nan"),
                }
            )
            continue
        error = pred - truth
        rows.append(
            {
                "market_day": day,
                "n_hours": int(truth.size),
                "n_hours_total": int(len(group)),
                "sum_abs_error": float(np.sum(np.abs(error))),
                "sum_sq_error": float(np.sum(error**2)),
                "sum_error": float(np.sum(error)),
                "realised_spread": float(truth.max() - truth.min()),
                "forecast_spread": float(pred.max() - pred.min()),
                "spread_error": float(
                    (pred.max() - pred.min()) - (truth.max() - truth.min())
                ),
                "spearman": spearman_rho(pred, truth),
            }
        )
    return pd.DataFrame(rows).set_index("market_day").sort_index()


@dataclass(frozen=True)
class ShapeScores:
    """A forecast's within-day shape error over one explicit set of market days.

    Every field is an aggregate of :func:`daily_shape_table` rows, so the same
    numbers come out of a bootstrap resample of those rows unchanged.
    """

    n_days: int
    n_days_scored: int
    n_days_spearman_undefined: int
    n_hours: int
    mae: float
    rmse: float
    bias: float
    spread_mae: float
    spread_bias: float
    spread_rmse: float
    spearman_mean: float
    spearman_median: float
    spearman_p05: float

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


def shape_scores(table: pd.DataFrame) -> ShapeScores:
    """Aggregate a :func:`daily_shape_table` (or any subset of its rows).

    MAE, RMSE and bias are recovered as ratios of column sums, so this function
    and :func:`score` agree exactly on the same hours — which is what lets C12
    put a point-error metric and a dispatch metric on one row and claim they are
    about the same rows.
    """
    if table.empty:
        raise MetricError("no days to score")
    scored = table[table["n_hours"] > 0]
    if scored.empty:
        raise MetricError("every day in the table is empty")
    n_hours = int(scored["n_hours"].sum())
    spearman = scored["spearman"].to_numpy(dtype="float64")
    defined = spearman[np.isfinite(spearman)]
    return ShapeScores(
        n_days=int(len(table)),
        n_days_scored=int(len(scored)),
        n_days_spearman_undefined=int(len(scored) - len(defined)),
        n_hours=n_hours,
        mae=float(scored["sum_abs_error"].sum() / n_hours),
        rmse=float(np.sqrt(scored["sum_sq_error"].sum() / n_hours)),
        bias=float(scored["sum_error"].sum() / n_hours),
        spread_mae=float(np.mean(np.abs(scored["spread_error"].to_numpy()))),
        spread_bias=float(np.mean(scored["spread_error"].to_numpy())),
        spread_rmse=float(
            np.sqrt(np.mean(scored["spread_error"].to_numpy() ** 2))
        ),
        spearman_mean=float(np.mean(defined)) if defined.size else float("nan"),
        spearman_median=float(np.median(defined)) if defined.size else float("nan"),
        spearman_p05=(
            float(np.quantile(defined, 0.05)) if defined.size else float("nan")
        ),
    )


def daily_spread_error(table: pd.DataFrame) -> float:
    """Mean absolute error of the daily max-minus-min spread, in EUR/MWh.

    PLAN.md's first decision-relevant metric. It is reported in EUR/MWh rather
    than as a percentage on purpose: the same reason sMAPE is absent from this
    module is the reason a *relative* spread error misbehaves — a day whose
    realised spread is near zero has no denominator worth dividing by.
    """
    return shape_scores(table).spread_mae


def within_day_spearman(table: pd.DataFrame) -> float:
    """Mean within-day Spearman rank correlation of the hourly price ordering.

    PLAN.md's second decision-relevant metric, and the closest point-forecast
    statistic to what the dispatch LP reads: the LP never sees a price level it
    cares about in isolation, only which hours are cheap relative to which.
    """
    return shape_scores(table).spearman_mean
