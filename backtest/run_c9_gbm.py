"""CLI: the C9 run — the gradient-boosted model, Tier A, on C8's four exogenous arms.

    python -m backtest.run_c9_gbm                        # DE-LU, ES, NO2; 2024
    python -m backtest.run_c9_gbm --zones DE-LU
    python -m backtest.run_c9_gbm --no-day-shift-diagnostic

Writes, per zone, into ``backtest/results/``:

* ``c9_gbm_<ZONE>_<YEARS>_predictions.csv.gz`` — every evaluated hour with the
  realised price, one GBM forecast column per arm, and the LEAR forecast C8
  committed for the same arm, so every number below is recomputable from the
  artefact without rerunning anything.
* ``c9_gbm_<ZONE>_<YEARS>_folds.csv`` — one row per refit, with the round count
  in-fold early stopping chose for each arm.
* ``c9_gbm_<ZONE>_<YEARS>_summary.json`` — scores per arm per model, the
  vintage-premium table computed separately for the GBM and for LEAR, the
  GBM−LEAR difference per arm, the early-stopping report, split-gain importances,
  the real-data day-shift diagnostic, and the git SHA, config hash and GBM
  config fingerprint of the run.

---

**Why the same four arms.** C8's FINDING C8-A is the project's headline so far:
at an honest vintage the whole ENTSO-E exogenous block is worth nothing on 2024
MAE for all three Tier-A zones (−0.8% to +0.7%), while the *same columns* fed at
the as-published Art. 14 vintage — 18:00 on D−1, six hours after the gate the
model is predicting — buy 8-11% in the two RES-exposed zones. That was measured
with a per-hour LASSO, and a per-hour LASSO is exactly the model you would expect
to waste a residual-load column: it can fit one slope through it and nothing
else. If the vintage premium is a property of the *information* rather than of
the linear functional form, a tree ensemble should reproduce it; if the honest
arms are worth nothing to a booster too, then the finding is about the data and
not about the model, which is a far stronger claim. So the GBM runs on all four
arms and the premium is **re-measured**, never inherited.

The second question this run settles is NOTE C8-01's: PLAN.md keeps the
exogenous block for Tier A on the argument that "a GBM may use residual load
where a LASSO cannot". That is a testable sentence, and ``load_only`` and
``res_persistence`` against ``price_only``, under the booster, are the test.

**LEAR is read from C8's artefact, not refitted.** C8 committed the per-hour
LASSO's predictions for all four arms on this zone, this evaluation year, this
aligned training window and this walk-forward spec. Refitting it here would
spend an hour of compute to reproduce a committed number, and would quietly
allow the two models to be compared on different folds if any spec drifted.
Instead the artefact is loaded and its index and realised prices are asserted
against this run's — so a mismatch is a loud failure rather than an invisible
one, and a clean match additionally re-verifies C8's committed result against a
freshly re-pulled cache. ``--no-lear-reference`` skips it.

**Everything is scored on the hours every model and arm predicted.** The GBM
routes a missing cell natively and so answers hours the committed LEAR declines
(FINDING C7-C's source gaps, chiefly ES's 120-hour December 2024 solar hole).
Raw per-arm coverage therefore differs between the two models, and a headline
MAE difference read off different evaluation sets would be meaningless. Each
series' own scores are reported *and* a ``common_hours`` block re-scores
everything on the intersection; every comparison in the summary is read off the
latter. Both are present; neither is hidden.

**The late arm's guard is pointed at it, not switched off.** For
``res_as_published`` the harness's per-fold guard is replaced by
:func:`forecast.exog_features.assert_only_acknowledged_leakage` over the whole
arm matrix, exactly as in :mod:`backtest.run_c8_exogenous` — which demands that
the only violations anywhere are ``after_gate_closure`` on exactly the declared
RES columns, late by exactly what the declared publication clock predicts. That
implies the per-fold check it replaces, because the guard is a per-(row, column)
predicate. Sealed-year refusal and the "training targets must be public" guard
are untouched and still run on every fold of every arm.

**The day-shift diagnostic runs on real prices because the synthetic version is
vacuous for this model** (FINDING C9-A). PLAN.md C3's assertion (i) — a
one-day-staler feature matrix must score worse — is asserted in
``tests/test_c9_gbm.py`` on a persistence-dominated synthetic series, and is
*not* informative on the week-periodic one C3 used for the naive floor: a pooled
booster also holds the calendar columns, which on that series explain the price
exactly, so the lags are a noisier restatement of a free signal and misaligning
them can help. This run therefore measures the assertion where it matters, on
each zone's real prices at the committed config, and records the number.

Sealed-holdout years are refused by :mod:`data.holdout` before any fold is
built. The summary's ``git_sha`` identifies the code the run was made from, so it
necessarily predates the commit that adds these files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

import numpy as np
import pandas as pd

from backtest import diagnostics as dx
from backtest.metrics import rmae, score, skill_score
from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.walk_forward import (
    WalkForwardSpec,
    evaluation_days,
    run_walk_forward,
)
from data.config import REPO_ROOT, config_hash, load_zones, zones_for_tier
from data.exogenous import load_zone_exogenous
from data.prices import load_zone_series
from forecast.exog_features import (
    EXOG_VARIANTS,
    ExogSpec,
    assert_only_acknowledged_leakage,
    attach_exogenous,
    publication_clocks,
    variant_is_monotone_in_information,
)
from forecast.features import build_features
from forecast.gbm import GbmSpec, gbm_factory
from forecast.models import NaiveLastWeek, TrainMeanBaseline

#: C8's aligned training start, repeated here so the two cycles' arms are cut
#: from the same rows and the GBM-vs-LEAR difference is not partly a difference
#: of training history.
ALIGN_TRAIN_FROM = dt.date(2022, 1, 1)

#: The two differences C8 defined, re-measured here under the booster.
HEADLINE_DELTAS = (
    ("load_only", "price_only", "capturable_exogenous_gain"),
    ("res_as_published", "res_persistence", "vintage_premium"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None,
                        help="zone keys (default: every Tier-A zone)")
    parser.add_argument("--years", nargs="*", type=int, default=[2024],
                        help="evaluation years (validation only; 2025 is sealed)")
    parser.add_argument("--variants", nargs="*", default=list(EXOG_VARIANTS),
                        help="arms to run, in ladder order")
    parser.add_argument("--refit-every", type=int, default=1,
                        help="evaluation days per refit (default 1 = daily, as C8)")
    parser.add_argument("--min-train-days", type=int, default=365,
                        help="market days of history required before a fold may run")
    parser.add_argument("--train-window-days", type=int, default=None,
                        help="rolling training window; default expanding")
    parser.add_argument("--align-train-from", default=ALIGN_TRAIN_FROM.isoformat(),
                        help="first market day any arm may train from")
    parser.add_argument("--persistence-lag-hours", type=int, default=24,
                        help="the RES degradation offset (PLAN.md: the previous vintage)")
    parser.add_argument("--no-lear-reference", action="store_true",
                        help="skip loading C8's committed LEAR predictions")
    parser.add_argument("--no-day-shift-diagnostic", action="store_true",
                        help="skip the real-data one-day-staler diagnostic")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# One arm
# ---------------------------------------------------------------------------


def _refit_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the per-fold fit reports a run produced."""
    if not reports:
        return {}
    best = np.array([r["best_iteration"] for r in reports], dtype="float64")
    capped = sum(1 for r in reports if r["n_rounds_capped"])
    return {
        "n_folds": len(reports),
        "best_iteration_min": int(best.min()),
        "best_iteration_median": float(np.median(best)),
        "best_iteration_mean": round(float(best.mean()), 2),
        "best_iteration_max": int(best.max()),
        "n_folds_hitting_the_round_cap": capped,
        "n_fit_rows_last_fold": reports[-1]["n_fit_rows"],
        "n_stopping_rows_last_fold": reports[-1]["n_stopping_rows"],
        "stopping_window_last_fold": [
            reports[-1]["stopping_first_day"], reports[-1]["stopping_last_day"]
        ],
        "n_predict_rows_with_any_nan_last_fold": reports[-1][
            "n_predict_rows_with_any_nan"
        ],
        "note": (
            "best_iteration is the round count the in-fold stopping set chose, per "
            "fold. n_folds_hitting_the_round_cap > 0 means the boosting cap, not the "
            "stopping curve, ended those fits — which would make the round count a "
            "fixed hyperparameter rather than an in-fold choice."
        ),
    }


class _ReportingFactory:
    """A model factory that keeps each fold's fit report.

    The harness owns the fold loop and hands back only predictions, so the only
    place to collect what each fit did is the factory it calls. It still builds a
    fresh model per fold — the whole point of the factory indirection — and only
    the finished reports are retained.
    """

    def __init__(self, gbm_spec: GbmSpec, name: str) -> None:
        self._factory = gbm_factory(gbm_spec, name=name)
        self.reports: list[dict[str, Any]] = []
        self.last_model: Any | None = None
        self.name = name

    def __call__(self):
        model = self._factory()
        original_fit = model.fit

        def fit(train):
            fitted = original_fit(train)
            self.reports.append(fitted.fit_report())
            self.last_model = fitted
            return fitted

        model.fit = fit  # type: ignore[method-assign]
        return model


# ---------------------------------------------------------------------------
# Scoring across models
# ---------------------------------------------------------------------------


def _common_hours_table(
    y_true: pd.Series, predictions: dict[str, pd.Series]
) -> dict[str, Any]:
    """Re-score every series on the hours every series predicted."""
    shared = y_true.notna()
    for series in predictions.values():
        shared &= series.notna()
    scores = {
        name: score(y_true[shared], series[shared]).as_dict()
        for name, series in predictions.items()
    }
    return {
        "n_hours": int(shared.sum()),
        "n_hours_dropped": int(len(y_true) - shared.sum()),
        "series": sorted(predictions),
        "scores": scores,
        "note": (
            "The GBM routes a missing cell natively and so answers hours the "
            "committed LEAR declines, which makes raw coverage differ between the "
            "two models. These are the only scores in this summary that compare "
            "them on one evaluation set; the per-arm blocks above are each series "
            "on its own coverage."
        ),
    }


def _ladder_table(scores: dict[str, Any], prefix: str) -> dict[str, Any]:
    """The arms' MAE in information order, for one model, plus the two deltas."""
    ladder = [v for v in EXOG_VARIANTS if f"{prefix}{v}" in scores]
    maes = [scores[f"{prefix}{v}"]["mae"] for v in ladder]
    out: dict[str, Any] = {
        "model": prefix.rstrip("_"),
        "variants": ladder,
        "mae": [round(m, 6) for m in maes],
        "listed_in_information_order": variant_is_monotone_in_information(ladder),
        "mae_monotone_non_increasing": all(
            later <= earlier + 1e-9 for earlier, later in zip(maes, maes[1:])
        ),
        "deltas": {},
    }
    for better, worse, label in HEADLINE_DELTAS:
        keys = (f"{prefix}{better}", f"{prefix}{worse}")
        if not all(k in scores for k in keys):
            continue
        mae_better = scores[keys[0]]["mae"]
        mae_worse = scores[keys[1]]["mae"]
        rmse_better = scores[keys[0]]["rmse"]
        rmse_worse = scores[keys[1]]["rmse"]
        out["deltas"][label] = {
            "arms": f"{better} vs {worse}",
            "mae_improvement_eur_mwh": round(mae_worse - mae_better, 6),
            "mae_improvement_fraction": round((mae_worse - mae_better) / mae_worse, 6),
            "rmse_improvement_eur_mwh": round(rmse_worse - rmse_better, 6),
            "rmse_improvement_fraction": round(
                (rmse_worse - rmse_better) / rmse_worse, 6
            ),
        }
    return out


def _model_comparison(scores: dict[str, Any]) -> dict[str, Any]:
    """GBM − LEAR per arm, on the common hours. Negative MAE delta favours the GBM."""
    out: dict[str, Any] = {}
    for variant in EXOG_VARIANTS:
        gbm_key, lear_key = f"gbm_{variant}", f"lear_{variant}"
        if gbm_key not in scores or lear_key not in scores:
            continue
        out[variant] = {
            "gbm_mae": scores[gbm_key]["mae"],
            "lear_mae": scores[lear_key]["mae"],
            "gbm_minus_lear_mae": round(
                scores[gbm_key]["mae"] - scores[lear_key]["mae"], 6
            ),
            "gbm_mae_as_fraction_of_lear": round(
                scores[gbm_key]["mae"] / scores[lear_key]["mae"], 6
            ),
            "gbm_rmse": scores[gbm_key]["rmse"],
            "lear_rmse": scores[lear_key]["rmse"],
            "gbm_minus_lear_rmse": round(
                scores[gbm_key]["rmse"] - scores[lear_key]["rmse"], 6
            ),
        }
    if out:
        out["note"] = (
            "A negative gbm_minus_lear_mae means the booster beat the per-hour LASSO "
            "on that arm. The difference is one of functional form AND of pooling "
            "(LEAR fits 24 models partitioned by delivery hour; the GBM fits one "
            "pooled model with the hour as a categorical feature) — this run cannot "
            "separate the two, and does not claim to."
        )
    return out


# ---------------------------------------------------------------------------
# The LEAR reference, read from C8's committed artefact
# ---------------------------------------------------------------------------


def load_c8_lear_predictions(
    zone_key: str, years: list[int], y_true: pd.Series
) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    """C8's committed LEAR forecasts for the same zone, year, arms and folds.

    Asserts the index and the realised prices against this run's rather than
    reindexing onto them: a mismatch means the two cycles did not evaluate the
    same hours, which must be a loud failure, not a silent realignment. A clean
    match is also a re-verification of C8's committed artefact against a freshly
    re-pulled cache.
    """
    tag = f"{zone_key}_{'-'.join(str(y) for y in years)}"
    path = RESULTS_DIR / f"c8_exog_{tag}_predictions.csv.gz"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing — C8's committed LEAR predictions are the reference "
            f"this run compares against. Re-run C8 for this zone, or pass "
            f"--no-lear-reference to run the GBM alone."
        )
    frame = pd.read_csv(path, index_col=0, parse_dates=[0])
    frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
    if not frame.index.equals(y_true.index):
        raise RuntimeError(
            f"{zone_key}: C8's prediction index ({len(frame)} rows, "
            f"{frame.index[0]}..{frame.index[-1]}) is not this run's "
            f"({len(y_true)} rows, {y_true.index[0]}..{y_true.index[-1]}). The two "
            f"cycles did not evaluate the same hours; refusing to compare them."
        )
    # C8 wrote y_true with %.4f, so the tolerance is the artefact's precision and
    # nothing more. A real disagreement here would mean the cache changed.
    drift = (frame["y_true"] - y_true).abs()
    worst = float(drift.max()) if len(drift) else 0.0
    if worst > 5e-4:
        raise RuntimeError(
            f"{zone_key}: realised prices disagree with C8's artefact by up to "
            f"{worst} EUR/MWh — the cached price series is not the one C8 scored. "
            f"That is a data-provenance problem, not a rounding one."
        )
    series = {
        variant: frame[f"y_pred_{variant}"]
        for variant in EXOG_VARIANTS
        if f"y_pred_{variant}" in frame.columns
    }
    provenance = {
        "path": str(path.relative_to(REPO_ROOT)),
        "n_rows": int(len(frame)),
        "arms_found": sorted(series),
        "worst_y_true_disagreement_eur_mwh": round(worst, 6),
        "note": (
            "LEAR is not refitted in C9. C8 committed its predictions for these "
            "arms, this zone, this evaluation year, this aligned training window "
            "and this walk-forward spec; the index and realised prices are asserted "
            "equal to this run's, which also re-verifies C8's artefact against a "
            "freshly re-pulled cache."
        ),
    }
    return series, provenance


# ---------------------------------------------------------------------------
# Per zone
# ---------------------------------------------------------------------------


def run_zone(zone_key: str, args: argparse.Namespace) -> dict[str, Any]:
    spec = WalkForwardSpec(
        refit_every_days=args.refit_every,
        min_train_days=args.min_train_days,
        train_window_days=args.train_window_days,
    )
    gbm_spec = GbmSpec()
    align_from = dt.date.fromisoformat(args.align_train_from)
    clocks = publication_clocks()

    print(f"\n=== {zone_key} ===")
    print(f"  gbm config fingerprint {gbm_spec.fingerprint()} "
          f"(lr={gbm_spec.learning_rate}, leaves={gbm_spec.num_leaves}, "
          f"cap={gbm_spec.num_boost_round}, es_rounds={gbm_spec.early_stopping_rounds}, "
          f"es_days={gbm_spec.early_stopping_days})")

    prices = load_zone_series(zone_key)
    stitch = prices.attrs["stitch_report"]
    print(f"  prices: {stitch.n_points} hours, "
          f"{stitch.first_ts_utc.date()}..{stitch.last_ts_utc.date()}")

    # `on_partial="flag"` as in C8: FINDING C7-C's source gaps leave partial
    # hours, and C7's standing rule is that a gap is reported and left NaN.
    exog = load_zone_exogenous(zone_key, on_partial="flag")
    print(f"  exogenous: {len(exog)} hours, {exog.index[0].date()}..{exog.index[-1].date()}, "
          f"status {exog.attrs['leakage_status']}, flagged {exog.attrs['flagged_columns']}")

    full = build_features(prices, zone_key)
    matrix = full.subset((full.market_day >= align_from).to_numpy())
    days = evaluation_days(matrix, args.years)
    print(f"  features: {len(matrix.columns)} price/calendar columns, "
          f"{len(matrix.index)} rows from {align_from}; "
          f"evaluating {len(days)} market days {days[0]}..{days[-1]}")

    naive = run_walk_forward(matrix, NaiveLastWeek, days, spec)
    mean_run = run_walk_forward(matrix, TrainMeanBaseline, days, spec)
    naive_scores = score(naive.y_true, naive.y_pred)
    mean_scores = score(mean_run.y_true, mean_run.y_pred)
    print(f"  naive_last_week: MAE {naive_scores.mae:.3f}  RMSE {naive_scores.rmse:.3f}")

    arms: dict[str, Any] = {}
    predictions: dict[str, pd.Series] = {}
    attach_reports: dict[str, Any] = {}
    fold_rounds: dict[str, list[int]] = {}
    importances: dict[str, Any] = {}
    y_true: pd.Series | None = None

    for variant in args.variants:
        factory = _ReportingFactory(gbm_spec, name=f"gbm_{variant}")
        exog_spec = ExogSpec(
            variant=variant, persistence_lag_hours=args.persistence_lag_hours
        )
        arm_matrix, report = attach_exogenous(matrix, exog, exog_spec)
        # This block is deliberately a near-copy of the one in
        # backtest.run_c8_exogenous: that module is the committed record of how
        # C8's numbers were produced, and parameterising it after the fact would
        # make that record depend on a later cycle's edit — a worse trade than a
        # dozen duplicated lines.
        if report.acknowledged_late_columns:
            assert_only_acknowledged_leakage(
                arm_matrix,
                report.acknowledged_late_columns,
                clocks,
                f"{zone_key} {variant} arm matrix (run_c9_gbm)",
            )
            result = run_walk_forward(
                arm_matrix, factory, days, spec, check_leakage=False
            )
        else:
            result = run_walk_forward(arm_matrix, factory, days, spec)

        scores = score(result.y_true, result.y_pred)
        predictions[f"gbm_{variant}"] = result.y_pred
        attach_reports[variant] = report.as_dict()
        fold_rounds[variant] = [r["best_iteration"] for r in factory.reports]
        importances[variant] = (
            factory.last_model.feature_importance() if factory.last_model else {}
        )
        if y_true is None:
            y_true = result.y_true
        elif not y_true.index.equals(result.y_true.index):
            raise RuntimeError(
                f"{zone_key}: arm {variant} was evaluated on a different index than "
                f"the first arm — the arms would not be comparable"
            )
        arms[variant] = {
            "exog_spec": report.spec,
            "exogenous_columns": report.exogenous_columns,
            "acknowledged_late_columns": report.acknowledged_late_columns,
            "scores": scores.as_dict(),
            "rmae_vs_naive": round(rmae(result.y_true, result.y_pred, naive.y_pred), 6),
            "skill_vs_train_mean": round(
                skill_score(result.y_true, result.y_pred, mean_run.y_pred), 6
            ),
            "n_folds": len(result.folds),
            "early_stopping": _refit_report(factory.reports),
            "feature_importance_last_fold": importances[variant],
        }
        late = (
            f"  [LATE VINTAGE: {len(report.acknowledged_late_columns)} acknowledged "
            f"column(s)]" if report.acknowledged_late_columns else ""
        )
        es = arms[variant]["early_stopping"]
        print(f"  gbm_{variant:17s} MAE {scores.mae:.3f}  RMSE {scores.rmse:.3f}  "
              f"bias {scores.bias:+.3f}  rMAE {arms[variant]['rmae_vs_naive']:.4f}  "
              f"coverage {scores.coverage:.5f}  rounds "
              f"{es['best_iteration_min']}-{es['best_iteration_max']} "
              f"(median {es['best_iteration_median']:.0f}, capped "
              f"{es['n_folds_hitting_the_round_cap']}){late}")

    assert y_true is not None

    lear_provenance: dict[str, Any] = {}
    if not args.no_lear_reference:
        lear_series, lear_provenance = load_c8_lear_predictions(
            zone_key, args.years, y_true
        )
        for variant, series in lear_series.items():
            predictions[f"lear_{variant}"] = series
        print(f"  LEAR reference loaded from {lear_provenance['path']} "
              f"({len(lear_series)} arm(s), worst y_true disagreement "
              f"{lear_provenance['worst_y_true_disagreement_eur_mwh']:.5f} EUR/MWh)")

    predictions["naive_last_week"] = naive.y_pred
    common = _common_hours_table(y_true, predictions)
    scores = common["scores"]
    print(f"  common hours: {common['n_hours']} ({common['n_hours_dropped']} dropped)")

    ladders = {"gbm": _ladder_table(scores, "gbm_")}
    if any(k.startswith("lear_") for k in scores):
        ladders["lear"] = _ladder_table(scores, "lear_")
    comparison = _model_comparison(scores)

    for model, ladder in ladders.items():
        print(f"    {model:4s} ladder MAE {ladder['mae']} "
              f"monotone={ladder['mae_monotone_non_increasing']}")
        for label, block in ladder["deltas"].items():
            print(f"      {label}: {block['arms']} -> "
                  f"{block['mae_improvement_eur_mwh']:+.4f} EUR/MWh "
                  f"({block['mae_improvement_fraction']:+.2%} MAE, "
                  f"{block['rmse_improvement_fraction']:+.2%} RMSE)")
    for variant, block in comparison.items():
        if variant == "note":
            continue
        print(f"    {variant:17s} gbm {block['gbm_mae']:.3f} vs lear "
              f"{block['lear_mae']:.3f} -> {block['gbm_minus_lear_mae']:+.3f} EUR/MWh")

    day_shift: dict[str, Any] = {}
    if not args.no_day_shift_diagnostic:
        # PLAN.md C3 assertion (i) at the committed config, on real prices, on the
        # price_only arm. FINDING C9-A: the synthetic week-periodic version of this
        # is vacuous for a pooled booster, so this is where the assertion is
        # actually established for the GBM.
        experiment = dx.day_shift_experiment(
            matrix, gbm_factory(gbm_spec, name="gbm_price_only"), days, spec,
            shifts=(0, 1),
        )
        by_shift = experiment.by_shift()
        degrades = by_shift[1].mae > by_shift[0].mae
        day_shift = {
            "arm": "price_only",
            "shifts": [0, 1],
            "aligned_mae": round(by_shift[0].mae, 6),
            "one_day_staler_mae": round(by_shift[1].mae, 6),
            "degradation_eur_mwh": round(by_shift[1].mae - by_shift[0].mae, 6),
            "degradation_fraction": round(
                (by_shift[1].mae - by_shift[0].mae) / by_shift[0].mae, 6
            ),
            "staler_is_worse": bool(degrades),
            "results": experiment.as_dict()["results"],
            "note": (
                "PLAN.md C3 assertion (i) for the GBM, on real prices at the "
                "committed config. The -1 (fresher) arm is omitted: it is a leak, so "
                "'it degrades' is the wrong claim about it — what a leak is worth to "
                "this model is measured in tests/test_c9_gbm.py instead. See FINDING "
                "C9-A for why the synthetic week-periodic version of this check is "
                "vacuous for a pooled booster and this real-data one is not."
            ),
        }
        print(f"    day-shift (real prices): aligned MAE {by_shift[0].mae:.3f} -> "
              f"one day staler {by_shift[1].mae:.3f} "
              f"({day_shift['degradation_fraction']:+.2%}), "
              f"staler_is_worse={degrades}")
        if not degrades:
            print("      *** PLAN.md assertion (i) does NOT hold for this zone — "
                  "this is a FLAG for PROGRESS.md, not a number to move on from. ***")

    summary: dict[str, Any] = {
        "cycle": "C9",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "zone": zone_key,
        "evaluation_years": list(args.years),
        "walk_forward_spec": spec.as_dict(),
        "gbm_spec": gbm_spec.as_dict(),
        "align_train_from": align_from.isoformat(),
        "persistence_lag_hours": args.persistence_lag_hours,
        "price_series": stitch.as_dict(),
        "exogenous_source": {
            "n_hours": int(len(exog)),
            "first_utc": exog.index[0].isoformat(),
            "last_utc": exog.index[-1].isoformat(),
            "leakage_status": exog.attrs["leakage_status"],
            "flagged_columns": list(exog.attrs["flagged_columns"]),
        },
        "publication_clocks": {k: c.as_dict() for k, c in clocks.items()},
        "feature_build": full.report.as_dict(),
        "n_rows_aligned": int(len(matrix.index)),
        "reference_scores": {
            naive.model_name: naive_scores.as_dict(),
            mean_run.model_name: mean_scores.as_dict(),
        },
        "arms": arms,
        "attach_reports": attach_reports,
        "lear_reference": lear_provenance,
        "common_hours": common,
        "ladders": ladders,
        "model_comparison": comparison,
        "day_shift_diagnostic": day_shift,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{zone_key}_{'-'.join(str(y) for y in args.years)}"

    combined = pd.DataFrame(
        {"market_day": matrix.market_day.reindex(y_true.index).to_numpy(),
         "y_true": y_true.to_numpy(dtype="float64")},
        index=y_true.index,
    )
    for name, series in predictions.items():
        combined[f"y_pred_{name}"] = series.to_numpy(dtype="float64")
    predictions_path = RESULTS_DIR / f"c9_gbm_{tag}_predictions.csv.gz"
    combined.to_csv(predictions_path, float_format="%.4f")

    # Every arm is cut from the same rows with the same spec, so the fold geometry
    # is identical across arms; the per-arm column is the round count in-fold early
    # stopping chose for that arm, which is the part that genuinely differs.
    folds_frame = naive.folds_frame()
    for variant, rounds in fold_rounds.items():
        if len(rounds) == len(folds_frame):
            folds_frame[f"best_iteration_{variant}"] = rounds
    folds_path = RESULTS_DIR / f"c9_gbm_{tag}_folds.csv"
    folds_frame.to_csv(folds_path, index=False)

    summary_path = RESULTS_DIR / f"c9_gbm_{tag}_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    for path in (predictions_path, folds_path, summary_path):
        print(f"  wrote {path.relative_to(REPO_ROOT)} "
              f"({path.stat().st_size / 1024:.0f} KiB)")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    zones = load_zones()
    selected = args.zones or [z.key for z in zones_for_tier("A")]
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}; known: {sorted(zones)}", file=sys.stderr)
        return 2
    bad = [v for v in args.variants if v not in EXOG_VARIANTS]
    if bad:
        print(f"unknown variant(s): {bad}; known: {list(EXOG_VARIANTS)}", file=sys.stderr)
        return 2
    if not variant_is_monotone_in_information(args.variants):
        print(
            f"--variants {args.variants} is not in the ladder's information order "
            f"{list(EXOG_VARIANTS)}; the monotonicity check would be meaningless",
            file=sys.stderr,
        )
        return 2
    for zone_key in selected:
        run_zone(zone_key, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
