"""CLI: the C4 walk-forward run — LEAR, DE-LU, validation year 2024.

    python -m backtest.run_c4_lear                        # DE-LU, 2024, all selectors
    python -m backtest.run_c4_lear --selectors aic        # just the committed default
    python -m backtest.run_c4_lear --no-diagnostics       # skip the three probes

Writes, per zone, into ``backtest/results/``:

* ``c4_lear_<ZONE>_<YEARS>_predictions.csv.gz`` — every evaluated hour, with the
  realised price and the LEAR, naive and train-mean forecasts side by side, so
  rMAE can be recomputed from the artefact without rerunning anything.
* ``c4_lear_<ZONE>_<YEARS>_folds.csv`` — one row per refit.
* ``c4_lear_<ZONE>_<YEARS>_summary.json`` — scores for every model and variant,
  a representative fit report, the three leakage diagnostics re-run on LEAR,
  and the git SHA plus config hash of the run.

**The selector is chosen once, here, and then frozen.** PLAN.md puts 2024 in
scope as the visible validation year and forbids tuning against repeatedly
visible metrics across cycles. So all three in-fold selection rules (AIC, BIC,
time-ordered CV) are run once on 2024, the numbers are recorded, and the rule
written into :class:`~forecast.lear.LearSpec` as the default is the one that
wins here — after which later cycles use it without revisiting the comparison.
The default only moves if a selector wins by more than a token margin; AIC is
the tie-break, being the cheapest and fully deterministic.

**Both NaN policies are reported, on purpose.** The committed model declines to
predict an hour whose design has a hole (the autumn DST hour whose 24-hour lag
the gate-closure mask blanks — FINDING C3-A), and :mod:`backtest.metrics`
charges it coverage for that. But the C5/C6 battery LP needs a *complete* 24-hour
forecast vector to optimise a day, so the ``impute`` variant is measured here
too: C6 then has the cost of full coverage as a number rather than a guess.

Sealed-holdout years are refused by :mod:`data.holdout` before any fold is
built. The summary's ``git_sha`` identifies the code the run was made from, so
it necessarily predates the commit that adds these files.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from backtest import diagnostics as dx
from backtest.metrics import rmae, score, skill_score
from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.walk_forward import (
    WalkForwardSpec,
    evaluation_days,
    run_walk_forward,
)
from data.config import REPO_ROOT, config_hash, load_zones
from data.prices import load_zone_series
from forecast.features import build_features
from forecast.lear import LearModel, LearSpec, lear_factory
from forecast.models import NaiveLastWeek, TrainMeanBaseline, TrainMedianBaseline

#: A selector must beat the default by more than this fraction of MAE to displace
#: it. Stated before the numbers are seen, so the choice is a rule, not a taste.
SELECTOR_MARGIN = 0.005


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=["DE-LU"], help="zone keys")
    parser.add_argument("--years", nargs="*", type=int, default=[2024],
                        help="evaluation years (validation only; 2025 is sealed)")
    parser.add_argument("--selectors", nargs="*", default=["aic", "bic", "cv"],
                        help="in-fold penalty selection rules to compare")
    parser.add_argument("--default-selector", default="aic",
                        help="the committed default, displaced only by a clear win")
    parser.add_argument("--refit-every", type=int, default=1,
                        help="evaluation days per refit (default 1 = daily)")
    parser.add_argument("--min-train-days", type=int, default=365,
                        help="market days of history required before a fold may run")
    parser.add_argument("--train-window-days", type=int, default=None,
                        help="rolling training window; default expanding")
    parser.add_argument("--diagnostics-refit-every", type=int, default=7,
                        help="refit cadence for the leakage probes (cost control)")
    parser.add_argument("--no-diagnostics", action="store_true",
                        help="skip the three leakage probes")
    parser.add_argument("--no-impute-variant", action="store_true",
                        help="skip the full-coverage nan_policy='impute' run")
    parser.add_argument("--seed", type=int, default=11, help="permutation seed")
    return parser.parse_args(argv)


def _mae_by_local_hour(predictions: pd.DataFrame, local_hour: pd.Series) -> dict[int, float]:
    """Per-delivery-hour MAE. Reporting only — C12 owns the real metrics layer."""
    out: dict[int, float] = {}
    hours = local_hour.reindex(predictions.index)
    for hour in sorted(pd.unique(hours.dropna()).tolist()):
        rows = (hours == hour).to_numpy()
        block = predictions.loc[rows]
        if block["y_pred"].notna().any():
            out[int(hour)] = round(score(block["y_true"], block["y_pred"]).mae, 4)
    return out


def _permutation_against_median(
    matrix,
    factory,
    days,
    probe_spec: WalkForwardSpec,
    mode: str,
    seed: int,
) -> dict[str, Any]:
    """Re-base PLAN.md assertion (iii) on a median reference. See FINDING C4-A.

    The assertion's question is whether shuffling the target destroys the
    model's skill. Asked against a *mean* baseline and scored by MAE, the answer
    is contaminated: on a right-skewed price distribution a constant at the
    median beats a constant at the mean, so any median-like estimator — which a
    LASSO fitted in asinh space and inverted through ``sinh`` is — scores
    positively on shuffled targets without knowing anything.

    So the same runs are scored against :class:`TrainMedianBaseline` as well,
    and against the zero-information constant itself. Both references are
    refitted inside the same walk-forward, so nothing here is a different
    evaluation set.
    """
    permuted = dx.permute_target(matrix, seed, mode)
    out: dict[str, Any] = {"mode": mode, "seed": seed}
    for label, candidate in (("real", matrix), ("permuted", permuted)):
        model_run = run_walk_forward(candidate, factory, days, probe_spec)
        mean_run = run_walk_forward(candidate, TrainMeanBaseline, days, probe_spec)
        median_run = run_walk_forward(candidate, TrainMedianBaseline, days, probe_spec)
        out[f"{label}_mae"] = round(score(model_run.y_true, model_run.y_pred).mae, 6)
        out[f"{label}_train_mean_mae"] = round(
            score(mean_run.y_true, mean_run.y_pred).mae, 6
        )
        out[f"{label}_train_median_mae"] = round(
            score(median_run.y_true, median_run.y_pred).mae, 6
        )
        out[f"{label}_skill_vs_train_median"] = round(
            skill_score(model_run.y_true, model_run.y_pred, median_run.y_pred), 6
        )
        # What a constant that knows nothing earns purely from the mean/median
        # gap — the margin that contaminates the mean-referenced skill score.
        out[f"{label}_zero_information_median_skill_vs_train_mean"] = round(
            skill_score(median_run.y_true, median_run.y_pred, mean_run.y_pred), 6
        )
    out["zero_information_median_skill_vs_train_mean"] = out[
        "permuted_zero_information_median_skill_vs_train_mean"
    ]
    out["permuted_beats_zero_information_constant"] = bool(
        out["permuted_mae"] < out["permuted_train_median_mae"]
    )
    out["real_beats_zero_information_constant"] = bool(
        out["real_mae"] < out["real_train_median_mae"]
    )
    return out


def run_zone(zone_key: str, args: argparse.Namespace) -> dict[str, Any]:
    spec = WalkForwardSpec(
        refit_every_days=args.refit_every,
        min_train_days=args.min_train_days,
        train_window_days=args.train_window_days,
    )
    print(f"\n=== {zone_key} ===")
    prices = load_zone_series(zone_key)
    stitch = prices.attrs["stitch_report"]
    print(f"  prices: {stitch.n_points} hours, "
          f"{stitch.first_ts_utc.date()}..{stitch.last_ts_utc.date()}")

    matrix = build_features(prices, zone_key)
    print(f"  features: {len(matrix.columns)} columns, "
          f"{matrix.report.mask.total_masked} cell(s) masked as unavailable")

    days = evaluation_days(matrix, args.years)
    print(f"  evaluating {len(days)} market days: {days[0]}..{days[-1]}")

    # The two references first: the naive floor is rMAE's denominator and the
    # train-mean baseline is the skill score's.
    naive = run_walk_forward(matrix, NaiveLastWeek, days, spec)
    mean_run = run_walk_forward(matrix, TrainMeanBaseline, days, spec)
    naive_scores = score(naive.y_true, naive.y_pred)
    mean_scores = score(mean_run.y_true, mean_run.y_pred)
    print(f"  {naive.model_name}: MAE {naive_scores.mae:.3f}  "
          f"RMSE {naive_scores.rmse:.3f}  bias {naive_scores.bias:+.3f}")
    print(f"  train_mean: MAE {mean_scores.mae:.3f}")

    selector_runs: dict[str, Any] = {}
    runs: dict[str, Any] = {}
    for selector in args.selectors:
        lear_spec = LearSpec(selector=selector)
        result = run_walk_forward(matrix, lear_factory(lear_spec), days, spec)
        scores = score(result.y_true, result.y_pred)
        relative = rmae(result.y_true, result.y_pred, naive.y_pred)
        selector_runs[selector] = {
            "spec": lear_spec.as_dict(),
            "scores": scores.as_dict(),
            "rmae_vs_naive": round(relative, 6),
            "skill_vs_train_mean": round(
                skill_score(result.y_true, result.y_pred, mean_run.y_pred), 6
            ),
            "n_folds": len(result.folds),
        }
        runs[selector] = result
        print(f"  lear_{selector}: MAE {scores.mae:.3f}  RMSE {scores.rmse:.3f}  "
              f"bias {scores.bias:+.3f}  rMAE vs naive {relative:.4f}  "
              f"coverage {scores.coverage:.5f}")

    # Freeze the selector by the rule stated in the module docstring.
    default = args.default_selector
    best = min(selector_runs, key=lambda s: selector_runs[s]["scores"]["mae"])
    chosen = default if default in selector_runs else best
    if best != chosen:
        improvement = (
            selector_runs[chosen]["scores"]["mae"] - selector_runs[best]["scores"]["mae"]
        ) / selector_runs[chosen]["scores"]["mae"]
        if improvement > SELECTOR_MARGIN:
            chosen = best
        print(f"  selector: best on MAE is {best} "
              f"({improvement:+.4%} vs {default}); committed default -> {chosen}")
    else:
        print(f"  selector: committed default {chosen} is also the best on MAE")

    main = runs[chosen]
    main_scores = score(main.y_true, main.y_pred)

    # A representative fit: the model as it stood at the start of the evaluation
    # year. The harness refits per fold and does not hand the models back, so one
    # fit on the first fold's window is reported rather than 366 of them.
    first = main.folds[0]
    train_window = matrix.subset(
        (
            (matrix.market_day >= first.train_start_day)
            & (matrix.market_day <= first.train_end_day)
        ).to_numpy()
    )
    representative = LearModel(LearSpec(selector=chosen)).fit(train_window)
    representative.predict(matrix.select_days(first.target_days))

    summary: dict[str, Any] = {
        "cycle": "C4",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "zone": zone_key,
        "evaluation_years": list(args.years),
        "spec": spec.as_dict(),
        "price_series": stitch.as_dict(),
        "feature_build": matrix.report.as_dict(),
        "walk_forward": main.as_dict(),
        "committed_selector": chosen,
        "selector_margin": SELECTOR_MARGIN,
        "selector_comparison": selector_runs,
        "scores": {
            main.model_name: main_scores.as_dict(),
            naive.model_name: naive_scores.as_dict(),
            mean_run.model_name: mean_scores.as_dict(),
        },
        "rmae_vs_naive": round(rmae(main.y_true, main.y_pred, naive.y_pred), 6),
        "skill_vs_train_mean": round(
            skill_score(main.y_true, main.y_pred, mean_run.y_pred), 6
        ),
        "representative_fit": {
            "train_start_day": first.train_start_day.isoformat(),
            "train_end_day": first.train_end_day.isoformat(),
            **representative.fit_report(),
        },
        "mae_by_local_hour": {
            main.model_name: _mae_by_local_hour(
                main.predictions, matrix.features["hour_of_day_local"]
            ),
            naive.model_name: _mae_by_local_hour(
                naive.predictions, matrix.features["hour_of_day_local"]
            ),
        },
    }

    if not args.no_impute_variant:
        imputed = run_walk_forward(
            matrix,
            lear_factory(LearSpec(selector=chosen, nan_policy="impute"), name="lear_impute"),
            days,
            spec,
        )
        imputed_scores = score(imputed.y_true, imputed.y_pred)
        # Compare on the hours the declining model *did* predict, so the two
        # numbers are a comparison and not two different evaluation sets.
        shared = main.y_pred.notna() & imputed.y_pred.notna()
        summary["nan_policy_variant"] = {
            "policy": "impute",
            "scores": imputed_scores.as_dict(),
            "mae_on_hours_both_predicted": round(
                score(imputed.y_true[shared], imputed.y_pred[shared]).mae, 6
            ),
            "mae_of_committed_model_on_those_hours": round(
                score(main.y_true[shared], main.y_pred[shared]).mae, 6
            ),
            "n_hours_only_impute_predicted": int(
                (main.y_pred.isna() & imputed.y_pred.notna()).sum()
            ),
            "note": (
                "The committed model declines an hour whose design has a hole. The "
                "C5/C6 battery LP needs a complete 24-hour vector, so the cost of "
                "full coverage is measured here rather than assumed at C6."
            ),
        }
        print(f"  lear_impute (full coverage): MAE {imputed_scores.mae:.3f}, "
              f"coverage {imputed_scores.coverage:.5f}, "
              f"{summary['nan_policy_variant']['n_hours_only_impute_predicted']} "
              f"hour(s) only it predicted")

    if not args.no_diagnostics:
        probe_spec = WalkForwardSpec(
            refit_every_days=args.diagnostics_refit_every,
            min_train_days=args.min_train_days,
            train_window_days=args.train_window_days,
        )
        factory = lear_factory(LearSpec(selector=chosen))
        print(f"  leakage diagnostics (refit every {probe_spec.refit_every_days} day(s)):")
        shift = dx.day_shift_experiment(matrix, factory, days, probe_spec)
        by_shift = shift.by_shift()
        print(f"    (i)  shift  aligned MAE {by_shift[0].mae:.3f} | "
              f"+1d {by_shift[1].mae:.3f} | -1d {by_shift[-1].mae:.3f}")

        guard = {
            "declared": [v.as_dict() for v in dx.guard_catches_future_feature(matrix, 24, True)],
            "undeclared": [
                v.as_dict() for v in dx.guard_catches_future_feature(matrix, 24, False)
            ],
        }
        print(f"    (ii) guard  declared -> {[v['kind'] for v in guard['declared']]}; "
              f"undeclared -> {[v['kind'] for v in guard['undeclared']]}")

        permutations = {}
        diagnosis = {}
        for mode in ("hours", "days"):
            experiment = dx.target_permutation_experiment(
                matrix, factory, days, probe_spec, seed=args.seed, mode=mode
            )
            permutations[mode] = experiment.as_dict()
            print(f"    (iii) permute {mode:5s} real skill {experiment.real_skill:+.4f} "
                  f"-> permuted {experiment.permuted_skill:+.4f}  "
                  f"(destroys skill: {experiment.destroys_skill()})")
            diagnosis[mode] = _permutation_against_median(
                matrix, factory, days, probe_spec, mode, args.seed
            )
            print(f"          vs train-median reference: real "
                  f"{diagnosis[mode]['real_skill_vs_train_median']:+.4f} -> permuted "
                  f"{diagnosis[mode]['permuted_skill_vs_train_median']:+.4f}; "
                  f"zero-information constant earns "
                  f"{diagnosis[mode]['zero_information_median_skill_vs_train_mean']:+.4f} "
                  f"(permuted model beats it: "
                  f"{diagnosis[mode]['permuted_beats_zero_information_constant']})")

        summary["diagnostics"] = {
            "refit_every_days": probe_spec.refit_every_days,
            "day_shift": shift.as_dict(),
            "day_shift_interpretation": (
                "For LEAR, shift=-1 feeding features from a day later is expected to "
                "*improve* MAE, not degrade it: the shifted price_lag_24h column then "
                "holds the target day's own price. That is the measurement of what the "
                "leak would be worth, and the reason degrades_for_every_shift is False "
                "here where C3's naive floor had it True — the naive model reads only "
                "price_lag_168h, which any whole-day shift breaks in both directions. "
                "What the probe establishes is that the harness is sensitive to time; "
                "the gate-closure guard, not the sign of this number, is what refuses "
                "the leak on the real matrix."
            ),
            "future_feature_guard": guard,
            "target_permutation": permutations,
            "target_permutation_against_median": diagnosis,
            "target_permutation_interpretation": (
                "FINDING C4-A. destroys_skill is False for LEAR, and the cause is the "
                "reference, not the model. backtest/diagnostics.py measures skill "
                "against the train-MEAN baseline, while the metric is MAE, which is "
                "minimised by the median; DE-LU 2019-2024 prices are strongly "
                "right-skewed (mean 95.65, median 66.18 EUR/MWh — the 2022 crisis), so "
                "a zero-information constant at the training median beats one at the "
                "training mean by ~7% of MAE. A LASSO fitted in asinh space and mapped "
                "back through sinh is a median-like estimator, so it collects that "
                "margin before learning anything. target_permutation_against_median "
                "re-bases the same comparison: against a train-median reference the "
                "permuted model's skill is NEGATIVE, and it earns less than the "
                "zero-information constant median does — i.e. shuffling the target did "
                "destroy every bit of conditional skill. The existing probe is left "
                "exactly as C3 wrote it (it holds a PLAN.md leakage assertion; "
                "re-basing destroys_skill is NOTE C4-01, for a human to decide)."
            ),
        }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{zone_key}_{'-'.join(str(y) for y in args.years)}"

    combined = main.predictions.rename(columns={"y_pred": f"y_pred_{main.model_name}"})
    combined[f"y_pred_{naive.model_name}"] = naive.y_pred
    combined[f"y_pred_{mean_run.model_name}"] = mean_run.y_pred
    combined = combined.drop(columns=["model"])
    predictions_path = RESULTS_DIR / f"c4_lear_{tag}_predictions.csv.gz"
    combined.to_csv(predictions_path, float_format="%.4f")
    folds_path = RESULTS_DIR / f"c4_lear_{tag}_folds.csv"
    main.folds_frame().to_csv(folds_path, index=False)
    summary_path = RESULTS_DIR / f"c4_lear_{tag}_summary.json"
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
    unknown = [z for z in args.zones if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}; known: {sorted(zones)}", file=sys.stderr)
        return 2
    for zone_key in args.zones:
        run_zone(zone_key, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
