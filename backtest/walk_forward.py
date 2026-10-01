"""The walk-forward harness: fit on the past, predict one market day at a time.

The whole point of this module is that **no fold can see its own future**, and
that this is asserted rather than believed. Three separate guards run on every
fold, and any of them raising stops the backtest:

1. **Training targets must be public.** A fold predicting market days starting at
   ``D0`` may train only on days whose prices were published by ``gate_closure(D0)``
   — i.e. days ``<= D0 - 1``. Asserted against the real publication instants, not
   assumed from the day arithmetic.
2. **Features must be public.** Both the training and the test matrix are run
   through the gate-closure guard (:mod:`forecast.leakage`), per row, against
   that row's own gate closure.
3. **Sealed years are refused.** Evaluating a sealed holdout year raises before a
   single fold is built (CLAUDE.md / :mod:`data.holdout`).

**Refit cadence is explicit, never incidental.** ``refit_every_days`` sets how
many consecutive evaluation days share one fitted model; the training window
always ends the day before the *first* day of the block, so a weekly refit means
the last day of the block is predicted by a model that is six days stale — which
is what a weekly-refit desk actually experiences, not a bug. ``train_window_days``
switches between an expanding window (``None``) and a rolling one.

The harness is model-agnostic: it takes a *factory*, calling it once per fold, so
a fold can never inherit state fitted on a later fold's data.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd

from data.holdout import assert_not_sealed
from forecast.features import FeatureMatrix
from forecast.leakage import assert_no_leakage
from forecast.models import Model
from forecast.timing import gate_closure_utc, publication_utc

ONE_DAY = dt.timedelta(days=1)

ModelFactory = Callable[[], Model]


class WalkForwardError(RuntimeError):
    """The walk-forward specification cannot be honoured on this matrix."""


@dataclass(frozen=True)
class Fold:
    """One refit: the days it predicts, and the window it was allowed to learn from."""

    index: int
    target_days: tuple[dt.date, ...]
    train_start_day: dt.date
    train_end_day: dt.date
    gate_closure_utc: pd.Timestamp
    n_train_days: int
    n_train_rows: int = 0
    n_test_rows: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fold": self.index,
            "first_target_day": self.target_days[0].isoformat(),
            "last_target_day": self.target_days[-1].isoformat(),
            "n_target_days": len(self.target_days),
            "train_start_day": self.train_start_day.isoformat(),
            "train_end_day": self.train_end_day.isoformat(),
            "gate_closure_utc": self.gate_closure_utc.isoformat(),
            "n_train_days": self.n_train_days,
            "n_train_rows": self.n_train_rows,
            "n_test_rows": self.n_test_rows,
        }


@dataclass(frozen=True)
class WalkForwardSpec:
    """How the walk proceeds. Committed alongside results so a run is reproducible."""

    refit_every_days: int = 1
    min_train_days: int = 365
    train_window_days: int | None = None

    def __post_init__(self) -> None:
        if self.refit_every_days < 1:
            raise WalkForwardError("refit_every_days must be >= 1")
        if self.min_train_days < 1:
            raise WalkForwardError("min_train_days must be >= 1")
        if self.train_window_days is not None:
            if self.train_window_days < self.min_train_days:
                raise WalkForwardError(
                    f"train_window_days {self.train_window_days} is smaller than "
                    f"min_train_days {self.min_train_days} — no fold could ever run"
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "refit_every_days": self.refit_every_days,
            "min_train_days": self.min_train_days,
            "train_window_days": self.train_window_days,
        }


@dataclass
class WalkForwardResult:
    """Predictions, the folds that produced them, and what was skipped."""

    model_name: str
    zone: str
    spec: WalkForwardSpec
    predictions: pd.DataFrame
    folds: list[Fold] = field(default_factory=list)
    skipped_days: list[str] = field(default_factory=list)
    skipped_reason: dict[str, str] = field(default_factory=dict)

    @property
    def y_true(self) -> pd.Series:
        return self.predictions["y_true"]

    @property
    def y_pred(self) -> pd.Series:
        return self.predictions["y_pred"]

    def folds_frame(self) -> pd.DataFrame:
        return pd.DataFrame([f.as_dict() for f in self.folds])

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "zone": self.zone,
            "spec": self.spec.as_dict(),
            "n_folds": len(self.folds),
            "n_rows": int(len(self.predictions)),
            "n_predicted": int(self.predictions["y_pred"].notna().sum()),
            "first_target_day": (
                self.predictions["market_day"].iloc[0].isoformat()
                if len(self.predictions)
                else None
            ),
            "last_target_day": (
                self.predictions["market_day"].iloc[-1].isoformat()
                if len(self.predictions)
                else None
            ),
            "n_skipped_days": len(self.skipped_days),
            "skipped_days": list(self.skipped_days),
            "skipped_reason": dict(self.skipped_reason),
        }


def _as_dates(days: Iterable[Any]) -> list[dt.date]:
    out: list[dt.date] = []
    for day in days:
        if isinstance(day, dt.datetime):
            out.append(day.date())
        elif isinstance(day, dt.date):
            out.append(day)
        else:
            out.append(pd.Timestamp(day).date())
    return out


def evaluation_days(matrix: FeatureMatrix, years: Sequence[int]) -> list[dt.date]:
    """Every complete market day of ``years`` present in the matrix, sorted.

    Refuses sealed years up front. A day with fewer than 23 rows is dropped as
    incomplete — a part-day at the edge of the cached series is not an evaluation
    day, and silently scoring it would make the first and last day of every run a
    different measurement from the rest.
    """
    assert_not_sealed(set(int(y) for y in years), f"evaluate {matrix.zone} walk-forward")
    wanted = {int(y) for y in years}
    day = matrix.market_day
    in_years = day.map(lambda d: d.year in wanted)
    counts = day[in_years].value_counts()
    complete = sorted(d for d, n in counts.items() if n >= 23)
    if not complete:
        raise WalkForwardError(
            f"{matrix.zone}: no complete market days in years {sorted(wanted)}"
        )
    return complete


def make_folds(
    available_days: Sequence[dt.date],
    eval_days: Sequence[dt.date],
    spec: WalkForwardSpec,
) -> tuple[list[Fold], dict[dt.date, str]]:
    """Split ``eval_days`` into refit blocks, each with its legal training window.

    Returns the folds plus a ``{day: reason}`` map of evaluation days that could
    not be covered — almost always "not enough training history yet", which is a
    fact about the data and must be reported, not padded over.
    """
    available = sorted(set(_as_dates(available_days)))
    targets = sorted(set(_as_dates(eval_days)))
    if not available:
        raise WalkForwardError("no market days available to train on")
    available_array = np.array(available, dtype="object")

    folds: list[Fold] = []
    skipped: dict[dt.date, str] = {}
    block_size = spec.refit_every_days

    for start in range(0, len(targets), block_size):
        block = targets[start : start + block_size]
        first = block[0]
        train_end = first - ONE_DAY
        in_train = available_array[available_array <= train_end]
        if spec.train_window_days is not None:
            window_start = first - dt.timedelta(days=spec.train_window_days)
            in_train = in_train[in_train >= window_start]
        if len(in_train) < spec.min_train_days:
            for day in block:
                skipped[day] = (
                    f"only {len(in_train)} training day(s) available before {first}, "
                    f"min_train_days={spec.min_train_days}"
                )
            continue
        folds.append(
            Fold(
                index=len(folds),
                target_days=tuple(block),
                train_start_day=in_train[0],
                train_end_day=in_train[-1],
                gate_closure_utc=gate_closure_utc(first),
                n_train_days=int(len(in_train)),
            )
        )
    return folds, skipped


def _assert_training_targets_were_public(
    train: FeatureMatrix, fold: Fold, zone: str
) -> None:
    """Every training row's own target price must have been published by gate closure.

    This is the guard that a day-arithmetic bug cannot talk its way past: it asks
    the publication calendar directly, for the latest training day actually in the
    fold's matrix.
    """
    if train.market_day.empty:
        raise WalkForwardError(f"{zone} fold {fold.index}: empty training matrix")
    latest = max(train.market_day)
    published = publication_utc(latest)
    if published > fold.gate_closure_utc:
        raise WalkForwardError(
            f"{zone} fold {fold.index}: training data includes market day {latest}, "
            f"whose prices were published {published.isoformat()} — after this "
            f"fold's gate closure {fold.gate_closure_utc.isoformat()}. That is "
            f"leakage, not a tolerance."
        )
    # Belt and braces. Under a sane publication convention the check above
    # already implies this one (publication(D) <= gate_closure(D0) forces
    # D <= D0 - 1), so this fires only if the convention itself changes — which
    # is exactly when a silent day-arithmetic assumption would become wrong.
    if latest >= fold.target_days[0]:
        raise WalkForwardError(
            f"{zone} fold {fold.index}: training data reaches market day {latest}, "
            f"which is not before the first target day {fold.target_days[0]}"
        )


def run_walk_forward(
    matrix: FeatureMatrix,
    model_factory: ModelFactory,
    eval_days: Sequence[dt.date],
    spec: WalkForwardSpec | None = None,
    check_leakage: bool = True,
) -> WalkForwardResult:
    """Walk ``eval_days`` forward, refitting as ``spec`` dictates. One model, one zone.

    ``check_leakage=False`` exists only for the deliberate misalignment
    experiments in :mod:`backtest.diagnostics`, which construct a knowingly
    dishonest matrix in order to measure what leakage would be worth. Real runs
    leave it on.
    """
    spec = spec or WalkForwardSpec()
    targets = sorted(set(_as_dates(eval_days)))
    assert_not_sealed(
        {d.year for d in targets}, f"run a walk-forward backtest on {matrix.zone}"
    )
    available = sorted(set(matrix.market_day))
    folds, skipped = make_folds(available, targets, spec)

    model_name = getattr(model_factory(), "name", "model")
    chunks: list[pd.DataFrame] = []
    realised_folds: list[Fold] = []

    for fold in folds:
        train = matrix.subset(
            (
                (matrix.market_day >= fold.train_start_day)
                & (matrix.market_day <= fold.train_end_day)
            ).to_numpy()
        )
        test = matrix.select_days(fold.target_days)
        if test.index.empty:
            skipped.update({day: "no rows in the matrix for this day" for day in fold.target_days})
            continue
        _assert_training_targets_were_public(train, fold, matrix.zone)
        if check_leakage:
            context = f"{matrix.zone} fold {fold.index}"
            assert_no_leakage(
                train.features,
                train.information_times,
                train.gate_closure,
                train.deterministic,
                f"{context} training matrix",
            )
            assert_no_leakage(
                test.features,
                test.information_times,
                test.gate_closure,
                test.deterministic,
                f"{context} test matrix",
            )

        model = model_factory().fit(train)
        predicted = model.predict(test)
        if not predicted.index.equals(test.index):
            raise WalkForwardError(
                f"{matrix.zone} fold {fold.index}: model returned predictions on a "
                f"different index than it was asked to predict"
            )
        chunks.append(
            pd.DataFrame(
                {
                    "market_day": test.market_day.to_numpy(),
                    "fold": fold.index,
                    "model": model_name,
                    "y_true": test.target.to_numpy(dtype="float64"),
                    "y_pred": predicted.to_numpy(dtype="float64"),
                },
                index=test.index,
            )
        )
        realised_folds.append(
            Fold(
                index=fold.index,
                target_days=fold.target_days,
                train_start_day=fold.train_start_day,
                train_end_day=fold.train_end_day,
                gate_closure_utc=fold.gate_closure_utc,
                n_train_days=fold.n_train_days,
                n_train_rows=int(len(train.index)),
                n_test_rows=int(len(test.index)),
            )
        )

    if not chunks:
        raise WalkForwardError(
            f"{matrix.zone}: no fold could be run — "
            f"{len(skipped)} evaluation day(s) skipped, first reason: "
            f"{next(iter(skipped.values()), 'unknown')}"
        )

    predictions = pd.concat(chunks).sort_index()
    predictions.index.name = "timestamp_utc"
    return WalkForwardResult(
        model_name=model_name,
        zone=matrix.zone,
        spec=spec,
        predictions=predictions,
        folds=realised_folds,
        skipped_days=[d.isoformat() for d in sorted(skipped)],
        skipped_reason={d.isoformat(): r for d, r in sorted(skipped.items())},
    )
