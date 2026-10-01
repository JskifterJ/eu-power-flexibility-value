"""CLI: the C3 walk-forward run — naive same-hour-last-week, DE-LU, validation year.

    python -m backtest.run_c3_naive                      # DE-LU, 2024
    python -m backtest.run_c3_naive --zones DE-LU --years 2024 --refit-every 1
    python -m backtest.run_c3_naive --no-diagnostics      # skip the three probes

Writes, per zone, into ``backtest/results/``:

* ``c3_naive_<ZONE>_<YEARS>_predictions.csv.gz`` — every evaluated hour, with the
  realised price, the forecast, the market day and the fold that produced it.
* ``c3_naive_<ZONE>_<YEARS>_folds.csv`` — one row per refit: its target days, its
  training window, and the gate closure it was bound by.
* ``c3_naive_<ZONE>_<YEARS>_summary.json`` — scores, the feature-build report
  (including how many cells the gate-closure mask had to blank), the three
  leakage diagnostics, and the git SHA plus config hash of the run.

Sealed-holdout years are refused by :mod:`data.holdout` before any fold is built.
The summary's ``git_sha`` is the commit the run was *made from*, so it necessarily
predates the commit that adds these files — it identifies the code, not the
artefact. The append-only, SHA-tagged results store PLAN.md asks for is C10's job;
this is the C3 artefact it will later supersede.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from backtest import diagnostics as dx
from backtest.metrics import score
from backtest.walk_forward import (
    WalkForwardSpec,
    evaluation_days,
    run_walk_forward,
)
from data.config import REPO_ROOT, config_hash, load_zones
from data.prices import load_zone_series
from forecast.features import build_features
from forecast.models import NaiveLastWeek, TrainMeanBaseline

RESULTS_DIR = REPO_ROOT / "backtest" / "results"


def git_sha() -> str:
    """The commit this run was made from, or ``"unknown"`` outside a work tree."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=["DE-LU"], help="zone keys")
    parser.add_argument("--years", nargs="*", type=int, default=[2024],
                        help="evaluation years (validation only; 2025 is sealed)")
    parser.add_argument("--refit-every", type=int, default=1,
                        help="evaluation days per refit (default 1 = daily)")
    parser.add_argument("--min-train-days", type=int, default=365,
                        help="market days of history required before a fold may run")
    parser.add_argument("--train-window-days", type=int, default=None,
                        help="rolling training window; default expanding")
    parser.add_argument("--no-diagnostics", action="store_true",
                        help="skip the three C3 leakage probes")
    parser.add_argument("--seed", type=int, default=11, help="permutation seed")
    return parser.parse_args(argv)


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
    masked = matrix.report.mask.total_masked
    print(f"  features: {len(matrix.columns)} columns, "
          f"{masked} cell(s) masked as unavailable at gate closure")

    days = evaluation_days(matrix, args.years)
    print(f"  evaluating {len(days)} market days: {days[0]}..{days[-1]}")

    result = run_walk_forward(matrix, NaiveLastWeek, days, spec)
    baseline = run_walk_forward(matrix, TrainMeanBaseline, days, spec)
    scores = score(result.y_true, result.y_pred)
    mean_scores = score(baseline.y_true, baseline.y_pred)
    print(f"  {result.model_name}: MAE {scores.mae:.3f}  RMSE {scores.rmse:.3f}  "
          f"bias {scores.bias:+.3f}  over {len(result.folds)} fold(s)")
    print(f"  train_mean baseline: MAE {mean_scores.mae:.3f}")

    summary: dict[str, Any] = {
        "cycle": "C3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "zone": zone_key,
        "evaluation_years": list(args.years),
        "spec": spec.as_dict(),
        "price_series": stitch.as_dict(),
        "feature_build": matrix.report.as_dict(),
        "walk_forward": result.as_dict(),
        "scores": {
            result.model_name: scores.as_dict(),
            baseline.model_name: mean_scores.as_dict(),
        },
        "skill_vs_train_mean": round(1.0 - scores.mae / mean_scores.mae, 6),
    }

    if not args.no_diagnostics:
        print("  leakage diagnostics:")
        shift = dx.day_shift_experiment(matrix, NaiveLastWeek, days, spec)
        by_shift = shift.by_shift()
        print(f"    (i)  shift  aligned MAE {by_shift[0].mae:.3f} | "
              f"+1d {by_shift[1].mae:.3f} | -1d {by_shift[-1].mae:.3f} | "
              f"degrades everywhere: {shift.degrades_everywhere()}")

        guard = {
            "declared": [v.as_dict() for v in dx.guard_catches_future_feature(matrix, 24, True)],
            "undeclared": [v.as_dict() for v in dx.guard_catches_future_feature(matrix, 24, False)],
        }
        print(f"    (ii) guard  declared future feature -> "
              f"{[v['kind'] for v in guard['declared']]}; undeclared -> "
              f"{[v['kind'] for v in guard['undeclared']]}")

        permutations = {}
        for mode in ("hours", "days"):
            experiment = dx.target_permutation_experiment(
                matrix, NaiveLastWeek, days, spec, seed=args.seed, mode=mode
            )
            permutations[mode] = experiment.as_dict()
            print(f"    (iii) permute {mode:5s} real skill "
                  f"{experiment.real_skill:+.4f} -> permuted "
                  f"{experiment.permuted_skill:+.4f}  "
                  f"(destroys skill: {experiment.destroys_skill()})")

        summary["diagnostics"] = {
            "day_shift": shift.as_dict(),
            "future_feature_guard": guard,
            "target_permutation": permutations,
        }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{zone_key}_{'-'.join(str(y) for y in args.years)}"
    predictions_path = RESULTS_DIR / f"c3_naive_{tag}_predictions.csv.gz"
    result.predictions.to_csv(predictions_path, float_format="%.4f")
    folds_path = RESULTS_DIR / f"c3_naive_{tag}_folds.csv"
    result.folds_frame().to_csv(folds_path, index=False)
    summary_path = RESULTS_DIR / f"c3_naive_{tag}_summary.json"
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
