"""The three leakage experiments PLAN.md requires, written before the real model.

PLAN.md, C3: "Leakage tests written *before* the real model, as executable
assertions: (i) shifting the feature matrix forward one day must degrade metrics;
(ii) a deliberately inserted future-timestamped feature must be caught by a guard
comparing every feature's max timestamp to gate closure; (iii) target permutation
must destroy skill."

They live here as library functions rather than only inside ``tests/`` so that any
later cycle — a new zone, a new model — can run the same three probes against the
real pipeline and commit the numbers, instead of re-deriving the idea.

What each one actually establishes, and what it does not:

(i) :func:`day_shift_experiment` — **alignment matters.** Correct alignment must
    beat both a one-day-staler and a one-day-fresher feature matrix. Note that
    *both* directions hurt a weekly-seasonal model: ``price_lag_168h`` shifted
    either way stops being the same weekday. So the sign of the shift effect is
    not itself a leakage detector — it establishes that the harness is sensitive
    to time at all, which is the precondition for (ii) meaning anything.

(ii) :func:`inject_future_feature` — **the guard has teeth.** A column built from
     prices the bidder could not have seen must be rejected, whether it is
     declared honestly (caught by the gate-closure comparison) or smuggled in
     undeclared (caught by the guard failing closed). The accompanying
     :func:`future_feature_value` measures what that leak would have been *worth*,
     which is the number that makes the guard feel necessary rather than
     bureaucratic.

(iii) :func:`target_permutation_experiment` — **skill is real, not an artefact.**
      Permuting the target destroys the feature-target relationship, so the
      pipeline must lose all of its advantage over a train-mean baseline. A
      pipeline that still scores well on shuffled targets is measuring something
      other than forecasting ability.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from backtest.metrics import Scores, score, skill_score
from backtest.walk_forward import (
    ModelFactory,
    WalkForwardSpec,
    run_walk_forward,
)
from forecast.features import FeatureMatrix, shift_feature_matrix
from forecast.leakage import LeakageViolation, find_leakage
from forecast.models import TrainMeanBaseline
from forecast.timing import publication_for, zone_timezone


@dataclass
class ShiftResult:
    """Scores for one feature-matrix shift, in days."""

    shift_days: int
    scores: Scores

    def as_dict(self) -> dict[str, Any]:
        return {"shift_days": self.shift_days, **self.scores.as_dict()}


@dataclass
class ShiftExperiment:
    """(i) Correct alignment against deliberate misalignment."""

    model: str
    zone: str
    results: list[ShiftResult] = field(default_factory=list)

    def by_shift(self) -> dict[int, Scores]:
        return {r.shift_days: r.scores for r in self.results}

    @property
    def baseline(self) -> Scores:
        return self.by_shift()[0]

    def degrades_everywhere(self) -> bool:
        """True iff every non-zero shift has a strictly worse MAE than alignment."""
        scores = self.by_shift()
        return all(
            s.mae > scores[0].mae for shift, s in scores.items() if shift != 0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "zone": self.zone,
            "aligned_mae": round(self.baseline.mae, 6),
            "degrades_for_every_shift": self.degrades_everywhere(),
            "results": [r.as_dict() for r in self.results],
        }


def day_shift_experiment(
    matrix: FeatureMatrix,
    model_factory: ModelFactory,
    eval_days: Sequence[dt.date],
    spec: WalkForwardSpec | None = None,
    shifts: Sequence[int] = (0, 1, -1),
) -> ShiftExperiment:
    """Run the same walk-forward at several whole-day feature misalignments.

    ``shift_days=+1`` feeds each row the features belonging to the row 24 hours
    earlier (one day staler); ``-1`` feeds it features from a day later, which is
    information after that row's gate closure. The shifted runs skip the leakage
    guard on purpose — they are *built* to violate it, and asserting otherwise
    would just assert that the shift happened.
    """
    model_name = getattr(model_factory(), "name", "model")
    experiment = ShiftExperiment(model=model_name, zone=matrix.zone)
    for shift in shifts:
        candidate = matrix if shift == 0 else shift_feature_matrix(matrix, shift)
        result = run_walk_forward(
            candidate,
            model_factory,
            eval_days,
            spec,
            check_leakage=(shift == 0),
        )
        experiment.results.append(
            ShiftResult(shift_days=shift, scores=score(result.y_true, result.y_pred))
        )
    return experiment


def future_feature(matrix: FeatureMatrix, lead_hours: int = 24) -> tuple[pd.Series, pd.Series]:
    """A feature built from a price ``lead_hours`` in the **future**, and its honest
    information time.

    This is the thing a leakage guard exists to catch: a column that is trivially
    informative and completely unavailable at the moment the bid had to be made.
    The information time is the publication instant of the *source* hour's market
    day — the same rule :mod:`forecast.features` applies to a lag, so the guard is
    being tested on its own terms rather than on a special case.
    """
    if lead_hours <= 0:
        raise ValueError("lead_hours must be positive — this builds a future feature")
    source = matrix.index + pd.Timedelta(hours=lead_hours)
    values = matrix.target.reindex(source)
    values.index = matrix.index
    source_market_day = pd.Series(
        list(source.tz_convert(zone_timezone(matrix.zone)).date),
        index=matrix.index,
        dtype="object",
    )
    name = f"price_lead_{lead_hours}h"
    return (
        values.rename(name).astype("float64"),
        publication_for(source_market_day).rename(name),
    )


def inject_future_feature(
    matrix: FeatureMatrix, lead_hours: int = 24, declare: bool = True
) -> FeatureMatrix:
    """Add a future-priced column to a matrix, declared honestly or smuggled in.

    ``declare=True`` attaches the column's true information time, so the guard
    must reject it as published after gate closure. ``declare=False`` adds the
    column with **no** declaration, so the guard must reject it for being
    undeclared — the fail-closed path, which is the one that protects against a
    future cycle adding a column and forgetting the bookkeeping.
    """
    values, information = future_feature(matrix, lead_hours)
    features = matrix.features.copy()
    features[values.name] = values
    if not declare:
        return matrix.with_features(features)
    information_times = matrix.information_times.copy()
    information_times[information.name] = information
    return matrix.with_features(features, information_times[features.columns])


def guard_catches_future_feature(
    matrix: FeatureMatrix, lead_hours: int = 24, declare: bool = True
) -> list[LeakageViolation]:
    """The violations the guard reports for an injected future feature. Never empty."""
    injected = inject_future_feature(matrix, lead_hours, declare)
    return find_leakage(
        injected.features,
        injected.information_times,
        injected.gate_closure,
        injected.deterministic,
    )


@dataclass
class PermutationExperiment:
    """(iii) Skill with real targets against skill with shuffled targets."""

    model: str
    zone: str
    mode: str
    seed: int
    real_scores: Scores
    permuted_scores: Scores
    real_skill: float
    permuted_skill: float

    def destroys_skill(self, tolerance: float = 0.0) -> bool:
        return self.real_skill > tolerance and self.permuted_skill <= tolerance

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "zone": self.zone,
            "mode": self.mode,
            "seed": self.seed,
            "real": self.real_scores.as_dict(),
            "permuted": self.permuted_scores.as_dict(),
            "real_skill_vs_train_mean": round(self.real_skill, 6),
            "permuted_skill_vs_train_mean": round(self.permuted_skill, 6),
            "destroys_skill": self.destroys_skill(),
        }


def permute_target(
    matrix: FeatureMatrix, seed: int = 0, mode: str = "hours"
) -> FeatureMatrix:
    """A copy of ``matrix`` whose target is shuffled, breaking the feature link.

    ``mode="hours"`` shuffles every hour independently — the strongest break, and
    the one the skill assertion uses. ``mode="days"`` permutes whole market days,
    preserving the within-day shape; a model that has only learned the average
    daily profile keeps its skill under that weaker shuffle, which is why it is
    reported separately rather than used as the pass/fail probe.
    """
    rng = np.random.default_rng(seed)
    if mode == "hours":
        values = matrix.target.to_numpy(dtype="float64").copy()
        rng.shuffle(values)
        permuted = pd.Series(values, index=matrix.index, name=matrix.target.name)
    elif mode == "days":
        days = sorted(set(matrix.market_day))
        donor_order = [days[i] for i in rng.permutation(len(days))]
        by_day = {
            day: matrix.target[(matrix.market_day == day).to_numpy()].to_numpy(dtype="float64")
            for day in days
        }
        pieces = []
        for day, donor in zip(days, donor_order):
            size = len(by_day[day])
            source_values = by_day[donor]
            # Market days differ in length across DST transitions, so a donor can
            # be one hour short or long: take what fits and repeat only if forced.
            pieces.append(
                source_values[:size]
                if len(source_values) >= size
                else np.resize(source_values, size)
            )
        permuted = pd.Series(
            np.concatenate(pieces), index=matrix.index, name=matrix.target.name
        )
    else:
        raise ValueError(f"unknown permutation mode {mode!r}; use 'hours' or 'days'")
    return matrix.with_target(permuted)


def target_permutation_experiment(
    matrix: FeatureMatrix,
    model_factory: ModelFactory,
    eval_days: Sequence[dt.date],
    spec: WalkForwardSpec | None = None,
    seed: int = 0,
    mode: str = "hours",
) -> PermutationExperiment:
    """Compare the pipeline's skill on real targets with its skill on shuffled ones.

    Skill is measured against a train-mean baseline refitted inside the same
    walk-forward, so both numbers come from the same machinery and the comparison
    cannot be an artefact of two different evaluation sets.
    """
    model_name = getattr(model_factory(), "name", "model")

    def _skill(candidate: FeatureMatrix) -> tuple[Scores, float]:
        model_run = run_walk_forward(candidate, model_factory, eval_days, spec)
        mean_run = run_walk_forward(candidate, TrainMeanBaseline, eval_days, spec)
        if not model_run.predictions.index.equals(mean_run.predictions.index):
            raise RuntimeError("model and baseline runs covered different hours")
        scores = score(model_run.y_true, model_run.y_pred)
        return scores, skill_score(model_run.y_true, model_run.y_pred, mean_run.y_pred)

    real_scores, real_skill = _skill(matrix)
    permuted_scores, permuted_skill = _skill(permute_target(matrix, seed, mode))
    return PermutationExperiment(
        model=model_name,
        zone=matrix.zone,
        mode=mode,
        seed=seed,
        real_scores=real_scores,
        permuted_scores=permuted_scores,
        real_skill=real_skill,
        permuted_skill=permuted_skill,
    )
