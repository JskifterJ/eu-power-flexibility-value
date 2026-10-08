"""CLI: the C8 run — exogenous features into LEAR, Tier A, with the mandatory
RES-forecast degradation sensitivity.

    python -m backtest.run_c8_exogenous                      # DE-LU, ES, NO2; 2024
    python -m backtest.run_c8_exogenous --zones DE-LU
    python -m backtest.run_c8_exogenous --no-full-history-reference

Writes, per zone, into ``backtest/results/``:

* ``c8_exog_<ZONE>_<YEARS>_predictions.csv.gz`` — every evaluated hour with the
  realised price and one forecast column per arm, so every number below can be
  recomputed from the artefact without rerunning anything.
* ``c8_exog_<ZONE>_<YEARS>_folds.csv`` — one row per refit.
* ``c8_exog_<ZONE>_<YEARS>_summary.json`` — scores per arm, the degradation
  table, the attach report for each arm (clocks, vintages, masked cells,
  acknowledged violations), and the git SHA plus config hash of the run.

---

**Four arms, one ladder.** :mod:`forecast.exog_features` builds the same
exogenous column set at four declared vintages — ``price_only``, ``load_only``,
``res_persistence``, ``res_as_published`` — in increasing order of information.
The headline numbers of this cycle are two differences:

* ``load_only - price_only``: the **capturable** exogenous gain. Every cell was
  public before gate closure, so this is a gain a bidder could have banked.
* ``res_as_published - res_persistence``: the **vintage premium**. Both arms hold
  the same columns; only the publication time differs. This is the number that
  says how much of a RES-fed model's apparent skill is owed to the archive
  knowing more than the market did, and it is the reason PLAN.md refuses to let
  the Art. 14 series into a result without it.

**The arms are compared on hours every arm predicted.** The committed LEAR
declines an hour whose design has a hole, and the exogenous columns bring holes
of their own (FINDING C7-C's source gaps: ES solar is absent for 120 hours of
December 2024). Scored on their own coverage, the arms would be four different
measurements wearing one table. So each arm's own scores are reported *and* a
``common_hours`` block re-scores every arm on the intersection, and the
comparison is read off the latter. Both are in the summary; neither is hidden.

**Every arm trains from the same day.** The exogenous series start in 2022
(PLAN.md: no archived D-1 forecast vintage exists earlier), and LEAR drops a
training row with any missing design cell, so an exogenous arm on an expanding
2019-start window silently trains on 2022+ while ``price_only`` trains on
2019+. The difference between the arms would then be partly "more features" and
partly "less history", with no way to tell which. All four arms are therefore
run on a training window beginning ``--align-train-from`` (2022-01-01), and
``price_only`` is *additionally* run on the full history as a labelled reference
row — which is C4's committed configuration and should reproduce its number.

**The late arm's guard is pointed at it, not switched off.** For
``res_as_published`` the harness's per-fold guard is replaced by
:func:`forecast.exog_features.assert_only_acknowledged_leakage` on the whole
matrix, which demands that the only violations anywhere are
``after_gate_closure`` on exactly the declared RES columns, late by exactly what
the declared publication clock predicts. That implies the per-fold check it
replaces: the guard is a per-(row, column) predicate, so a violation in any row
subset is a violation of the whole, and a whole-matrix pass with no
unacknowledged violation leaves no subset with one. What it adds over the
per-fold check is the lateness equality and the refusal of a *silent*
acknowledgement. Sealed-year refusal and the "training targets must be public"
guard are untouched and still run on every fold of every arm.

Sealed-holdout years are refused by :mod:`data.holdout` before any fold is
built. The summary's ``git_sha`` identifies the code the run was made from, so
it necessarily predates the commit that adds these files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

import pandas as pd

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
    attach_exogenous,
    assert_only_acknowledged_leakage,
    publication_clocks,
    variant_is_monotone_in_information,
)
from forecast.features import build_features
from forecast.lear import LearSpec, lear_factory
from forecast.models import NaiveLastWeek, TrainMeanBaseline

#: First market day every arm is allowed to train from, so the four arms differ
#: only in their columns. 2022-01-01 is where the exogenous series begin
#: (``sources.entsoe.exogenous_available_from_year``).
ALIGN_TRAIN_FROM = dt.date(2022, 1, 1)

#: The two differences this cycle exists to produce.
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
    parser.add_argument("--selector", default=None,
                        help="LEAR in-fold penalty rule (default: the C4-committed one)")
    parser.add_argument("--refit-every", type=int, default=1,
                        help="evaluation days per refit (default 1 = daily)")
    parser.add_argument("--min-train-days", type=int, default=365,
                        help="market days of history required before a fold may run")
    parser.add_argument("--train-window-days", type=int, default=None,
                        help="rolling training window; default expanding")
    parser.add_argument("--align-train-from", default=ALIGN_TRAIN_FROM.isoformat(),
                        help="first market day any arm may train from")
    parser.add_argument("--persistence-lag-hours", type=int, default=24,
                        help="the RES degradation offset (PLAN.md: the previous vintage)")
    parser.add_argument("--no-full-history-reference", action="store_true",
                        help="skip the price_only run on the full 2019+ history")
    return parser.parse_args(argv)


def _run_arm(
    matrix,
    variant: str,
    exog: pd.DataFrame,
    days: list[dt.date],
    spec: WalkForwardSpec,
    lear_spec: LearSpec,
    persistence_lag_hours: int,
    clocks: dict[str, Any],
) -> tuple[Any, Any]:
    """One arm: attach its vintage, then walk it forward. Returns (result, report)."""
    exog_spec = ExogSpec(variant=variant, persistence_lag_hours=persistence_lag_hours)
    arm_matrix, report = attach_exogenous(matrix, exog, exog_spec)
    factory = lear_factory(lear_spec, name=f"lear_{variant}")

    if report.acknowledged_late_columns:
        # Not a relaxation: the acknowledgement check already ran inside
        # attach_exogenous and is re-run here against the *exact* arm matrix the
        # folds are cut from, so the thing the harness would have checked per
        # fold has been checked once for every row it will ever see. See the
        # module docstring for why one whole-matrix pass implies every subset's.
        assert_only_acknowledged_leakage(
            arm_matrix,
            report.acknowledged_late_columns,
            clocks,
            f"{matrix.zone} {variant} arm matrix (run_c8_exogenous)",
        )
        result = run_walk_forward(arm_matrix, factory, days, spec, check_leakage=False)
    else:
        result = run_walk_forward(arm_matrix, factory, days, spec)
    return result, report


def _common_hours_table(
    y_true: pd.Series, predictions: dict[str, pd.Series]
) -> dict[str, Any]:
    """Re-score every arm on the hours every arm predicted."""
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
        "scores": scores,
        "note": (
            "The arms decline different hours (the committed LEAR declines an hour "
            "whose design has a hole, and the exogenous columns carry FINDING C7-C's "
            "source gaps). These are the only scores in this summary that compare the "
            "arms on one evaluation set; the per-arm block above is each arm on its own "
            "coverage."
        ),
    }


def _delta_table(common: dict[str, Any], naive_mae: float) -> dict[str, Any]:
    """The ladder differences, on the common-hours scores."""
    scores = common["scores"]
    out: dict[str, Any] = {}
    for better, worse, label in HEADLINE_DELTAS:
        if better not in scores or worse not in scores:
            continue
        mae_better = scores[better]["mae"]
        mae_worse = scores[worse]["mae"]
        out[label] = {
            "arms": f"{better} vs {worse}",
            "mae_improvement_eur_mwh": round(mae_worse - mae_better, 6),
            "mae_improvement_fraction": round((mae_worse - mae_better) / mae_worse, 6),
            "mae_improvement_as_fraction_of_naive_mae": round(
                (mae_worse - mae_better) / naive_mae, 6
            ),
        }
    ladder = [v for v in EXOG_VARIANTS if v in scores]
    maes = [scores[v]["mae"] for v in ladder]
    out["ladder"] = {
        "variants": ladder,
        "mae": [round(m, 6) for m in maes],
        "listed_in_information_order": variant_is_monotone_in_information(ladder),
        "mae_monotone_non_increasing": all(
            later <= earlier + 1e-9 for earlier, later in zip(maes, maes[1:])
        ),
        "note": (
            "Each arm's information set contains the previous arm's, so MAE is "
            "expected to be non-increasing along the ladder. A violation is a finding "
            "about the model — a column the LASSO cannot exploit, or a weak signal "
            "swamped by the extra parameters it costs — not a plumbing bug, and it is "
            "reported as such rather than smoothed."
        ),
    }
    return out


def run_zone(zone_key: str, args: argparse.Namespace) -> dict[str, Any]:
    spec = WalkForwardSpec(
        refit_every_days=args.refit_every,
        min_train_days=args.min_train_days,
        train_window_days=args.train_window_days,
    )
    lear_spec = LearSpec(**({"selector": args.selector} if args.selector else {}))
    align_from = dt.date.fromisoformat(args.align_train_from)
    clocks = publication_clocks()

    print(f"\n=== {zone_key} ===")
    prices = load_zone_series(zone_key)
    stitch = prices.attrs["stitch_report"]
    print(f"  prices: {stitch.n_points} hours, "
          f"{stitch.first_ts_utc.date()}..{stitch.last_ts_utc.date()}")

    # `on_partial="flag"` rather than "raise": FINDING C7-C's source gaps leave
    # partial hours in the native-resolution series, and C7's standing rule is
    # that a gap is reported and left as NaN, never filled. Raising here would
    # cost a whole Tier-A zone for a handful of intervals.
    exog = load_zone_exogenous(zone_key, on_partial="flag")
    print(f"  exogenous: {len(exog)} hours, {exog.index[0].date()}..{exog.index[-1].date()}, "
          f"status {exog.attrs['leakage_status']}, flagged {exog.attrs['flagged_columns']}")
    for key, clock in clocks.items():
        print(f"    clock {key}: public {clock.describe()} ({clock.leakage_status})")

    full = build_features(prices, zone_key)
    matrix = full.subset((full.market_day >= align_from).to_numpy())
    print(f"  features: {len(full.columns)} price/calendar columns; "
          f"{len(matrix.index)} rows from {align_from} (aligned training window), "
          f"{len(full.index)} rows in full history")

    days = evaluation_days(matrix, args.years)
    print(f"  evaluating {len(days)} market days: {days[0]}..{days[-1]}")

    naive = run_walk_forward(matrix, NaiveLastWeek, days, spec)
    mean_run = run_walk_forward(matrix, TrainMeanBaseline, days, spec)
    naive_scores = score(naive.y_true, naive.y_pred)
    mean_scores = score(mean_run.y_true, mean_run.y_pred)
    print(f"  naive_last_week: MAE {naive_scores.mae:.3f}  RMSE {naive_scores.rmse:.3f}")
    print(f"  train_mean:      MAE {mean_scores.mae:.3f}")

    arms: dict[str, Any] = {}
    predictions: dict[str, pd.Series] = {}
    attach_reports: dict[str, Any] = {}
    y_true: pd.Series | None = None

    for variant in args.variants:
        result, report = _run_arm(
            matrix, variant, exog, days, spec, lear_spec,
            args.persistence_lag_hours, clocks,
        )
        scores = score(result.y_true, result.y_pred)
        predictions[variant] = result.y_pred
        attach_reports[variant] = report.as_dict()
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
        }
        late = (
            f"  [LATE VINTAGE: {len(report.acknowledged_late_columns)} acknowledged "
            f"column(s)]" if report.acknowledged_late_columns else ""
        )
        print(f"  {variant:17s} MAE {scores.mae:.3f}  RMSE {scores.rmse:.3f}  "
              f"bias {scores.bias:+.3f}  rMAE {arms[variant]['rmae_vs_naive']:.4f}  "
              f"coverage {scores.coverage:.5f}{late}")
        if report.persistence_masked_dst_rows:
            print(f"    {report.persistence_masked_dst_rows} row(s) blanked where the "
                  f"persistence offset lands on the target day's own first hour "
                  f"(autumn DST): {report.persistence_masked_dst_timestamps}")

    assert y_true is not None
    common = _common_hours_table(y_true, predictions)
    deltas = _delta_table(common, naive_scores.mae)
    print(f"  common hours: {common['n_hours']} "
          f"({common['n_hours_dropped']} dropped)")
    for label, block in deltas.items():
        if label == "ladder":
            continue
        print(f"    {label}: {block['arms']} -> "
              f"{block['mae_improvement_eur_mwh']:+.4f} EUR/MWh "
              f"({block['mae_improvement_fraction']:+.2%} of MAE)")
    print(f"    ladder MAE {deltas['ladder']['mae']} monotone="
          f"{deltas['ladder']['mae_monotone_non_increasing']}")

    summary: dict[str, Any] = {
        "cycle": "C8",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "zone": zone_key,
        "evaluation_years": list(args.years),
        "walk_forward_spec": spec.as_dict(),
        "lear_spec": lear_spec.as_dict(),
        "align_train_from": align_from.isoformat(),
        "persistence_lag_hours": args.persistence_lag_hours,
        "price_series": stitch.as_dict(),
        "exogenous_source": {
            "n_hours": int(len(exog)),
            "first_utc": exog.index[0].isoformat(),
            "last_utc": exog.index[-1].isoformat(),
            "leakage_status": exog.attrs["leakage_status"],
            "flagged_columns": list(exog.attrs["flagged_columns"]),
            "documents": exog.attrs["documents"],
        },
        "publication_clocks": {k: c.as_dict() for k, c in clocks.items()},
        "feature_build": full.report.as_dict(),
        "n_rows_aligned": int(len(matrix.index)),
        "n_rows_full_history": int(len(full.index)),
        "reference_scores": {
            naive.model_name: naive_scores.as_dict(),
            mean_run.model_name: mean_scores.as_dict(),
        },
        "arms": arms,
        "attach_reports": attach_reports,
        "common_hours": common,
        "degradation": deltas,
    }

    if not args.no_full_history_reference and "price_only" in args.variants:
        full_days = evaluation_days(full, args.years)
        reference = run_walk_forward(
            full, lear_factory(lear_spec, name="lear_price_only_full_history"),
            full_days, spec,
        )
        reference_scores = score(reference.y_true, reference.y_pred)
        summary["full_history_reference"] = {
            "variant": "price_only",
            "train_from": full.market_day.min().isoformat(),
            "scores": reference_scores.as_dict(),
            "rmae_vs_naive": round(
                rmae(reference.y_true, reference.y_pred, naive.y_pred), 6
            ),
            "mae_vs_aligned_price_only": round(
                arms["price_only"]["scores"]["mae"] - reference_scores.mae, 6
            ),
            "note": (
                "C4's committed configuration: price-history features on the full "
                "2019+ expanding window. Reported so the cost of aligning every arm "
                "to the 2022 exogenous start is a number rather than a caveat. It is "
                "NOT part of the ladder — it trains on different rows."
            ),
        }
        print(f"  price_only (full 2019+ history, C4 config): "
              f"MAE {reference_scores.mae:.3f} — aligning to 2022 costs "
              f"{summary['full_history_reference']['mae_vs_aligned_price_only']:+.3f} "
              f"EUR/MWh of MAE")
        predictions["price_only_full_history"] = reference.y_pred.reindex(y_true.index)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{zone_key}_{'-'.join(str(y) for y in args.years)}"

    combined = pd.DataFrame(
        {"market_day": matrix.market_day.reindex(y_true.index).to_numpy(),
         "y_true": y_true.to_numpy(dtype="float64")},
        index=y_true.index,
    )
    for name, series in predictions.items():
        combined[f"y_pred_{name}"] = series.to_numpy(dtype="float64")
    combined["y_pred_naive_last_week"] = naive.y_pred.to_numpy(dtype="float64")
    combined["y_pred_train_mean"] = mean_run.y_pred.to_numpy(dtype="float64")

    predictions_path = RESULTS_DIR / f"c8_exog_{tag}_predictions.csv.gz"
    combined.to_csv(predictions_path, float_format="%.4f")
    # Every arm is cut from the same rows with the same spec, so the folds are
    # identical across arms; one copy is the record, not one per arm.
    folds_path = RESULTS_DIR / f"c8_exog_{tag}_folds.csv"
    naive.folds_frame().to_csv(folds_path, index=False)
    summary_path = RESULTS_DIR / f"c8_exog_{tag}_summary.json"
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
