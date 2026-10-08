"""CLI: the C10 scale-out — all nine zones, every model, into the append-only store.

    python -m backtest.run_c10_scale                       # compute then ingest
    python -m backtest.run_c10_scale --phase compute --zones FR NL
    python -m backtest.run_c10_scale --phase ingest

PLAN.md C10: *"Scale the harness: Tier A (3 models, exogenous features) + Tier B
(naive + LEAR, price-only). Results written append-only, each row tagged with
git SHA + config hash."* This module is the scale-out, and it runs in two
phases on purpose.

**``compute`` — Tier B, the only new fitting in this cycle.** Six zones (FR, NL,
BE, IT-North, DK1, PL) x ``naive_last_week`` + ``train_mean`` + LEAR on
price-history and calendar features only, walked forward daily across 2024 on an
expanding window from the start of the price history. Writes
``c10_tierb_<ZONE>_<YEARS>_{predictions.csv.gz,folds.csv,summary.json}``. Each
zone is independent, so the phase takes ``--zones`` and several processes may run
it in parallel; nothing is appended to the store here, which is what makes that
safe.

**``ingest`` — one process, one append.** Reads every committed artefact (C8's
LEAR arms, C9's GBM arms, this cycle's Tier-B runs), **recomputes** every metric
from the prediction columns, cross-checks each recomputed number against the
number its source summary committed, and appends the lot to
:mod:`backtest.results_store` as a single run. Also writes
``c10_scale_summary.json``: the nine-zone comparable table, the per-zone model
tables, and the cross-check report.

---

**Why Tier A is ingested rather than refitted.** C8 committed LEAR's
predictions for four exogenous arms x three Tier-A zones on 2024, and C9
committed the GBM's on the same rows, vintages, folds and aligned training
window. Refitting 24 model-arms here would spend hours reproducing committed
numbers, and — worse — would let the store's Tier-A rows drift from the
artefacts the findings were written against if any spec had moved. So C9's
precedent is followed and extended: the artefact is the source of truth, its
realised prices are asserted against a freshly loaded price series, and every
metric is **recomputed from the predictions** rather than copied out of the
summary, with the recomputation asserted equal to the committed value to the
artefact's own ``%.4f`` precision. A disagreement is a loud failure, not a
rounding note.

**Why Tier B trains on the full price history.** Tier A's four arms are cut from
2022-01-01 because no archived ENTSO-E forecast vintage exists earlier; Tier B
has no exogenous block and therefore no such constraint, so it runs C4's
committed configuration on everything available (2019+). The nine-zone
comparable row set is consequently ``lear`` / ``price_only`` /
``train_from=2019-01-01``, which exists for Tier A too: C8 ran exactly that as
its ``full_history_reference`` and committed it as
``y_pred_price_only_full_history``. So the cross-zone table is like-for-like by
construction rather than by assertion.

**What ``scope`` means in the store.** ``own_coverage`` scores each series on the
hours it answered. ``common_hours`` re-scores every series of that zone on the
intersection of all of them — for Tier A, the intersection over exactly the nine
series C9's artefact carries, which is what makes the recomputation checkable
against C9's committed ``common_hours`` block. The two tiers' intersections are
therefore over different series sets, which is why the cross-zone table is built
from ``own_coverage`` rows and carries ``n_scored`` beside every number (LEAR
declines one hour a year — the autumn DST hour whose 24-hour lag the gate-closure
mask blanks, FINDING C3-A — so it is 8 783 against the naive floor's 8 784).

**The late arm is labelled in the schema, not in a caveat.** Every
``res_as_published`` row is written with ``vintage="after_gate_closure"``, and
:func:`backtest.results_store.honest_rows` is the default filter. FINDING C9-C
measured that arm at +18-24% of MAE over the honest one, none of which a bidder
could have had, so the store refuses to carry such a number without its label.

Sealed years are refused by :mod:`data.holdout` before any fold is built, and
again by the store before any row is written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.metrics import rmae, score, skill_score
from backtest.results_store import (
    ResultRow,
    append_rows,
    library_versions,
    rows_from_scores,
    verify_append_only,
)
from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.walk_forward import WalkForwardSpec, evaluation_days, run_walk_forward
from data.config import REPO_ROOT, config_hash, load_zones
from data.prices import load_zone_series
from forecast.features import build_features
from forecast.lear import LearSpec, lear_factory
from forecast.models import NaiveLastWeek, TrainMeanBaseline

#: The four exogenous arms, in information order, as C8 and C9 named them.
EXOG_ARMS = ("price_only", "load_only", "res_persistence", "res_as_published")

#: The one arm whose information was published after gate closure (Art. 14,
#: 18:00 on D-1). Carried only as the measurement of that leak.
LATE_ARMS = frozenset({"res_as_published"})

#: C8/C9's aligned start for the Tier-A arms, and the full-history start the
#: nine-zone comparable row set uses. Both are properties of the committed
#: artefacts, repeated here so the ingest can label rows without guessing.
ALIGNED_TRAIN_FROM = "2022-01-01"
FULL_HISTORY_TRAIN_FROM = "2019-01-01"

#: The artefact is written with ``%.4f``, so a recomputation agrees with the
#: committed summary to about that. Anything larger is a provenance problem.
RECOMPUTE_TOLERANCE = 5e-4

#: Metrics taken from a :class:`backtest.metrics.Scores`.
SCORE_METRICS = ("mae", "rmse", "bias", "coverage")


class ScaleError(RuntimeError):
    """The scale-out cannot proceed without making a number untrustworthy."""


class _ReportingFactory:
    """A model factory that keeps each fold's fit report.

    The harness owns the fold loop and hands back only predictions, so the only
    place to collect what each fit did is the factory it calls. Lifted from
    :mod:`backtest.run_c9_gbm`, which needed the same thing for the booster's
    round counts; it still builds a fresh model per fold, which is the whole
    point of the factory indirection.
    """

    def __init__(self, factory, name: str) -> None:
        self._factory = factory
        self.reports: list[dict[str, Any]] = []
        self.name = name

    def __call__(self):
        model = self._factory()
        original_fit = model.fit

        def fit(train):
            fitted = original_fit(train)
            self.reports.append(fitted.fit_report())
            return fitted

        model.fit = fit  # type: ignore[method-assign]
        return model


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["compute", "ingest", "all"], default="all")
    parser.add_argument("--zones", nargs="*", default=None,
                        help="compute phase: Tier-B zone keys (default: every Tier-B zone)")
    parser.add_argument("--years", nargs="*", type=int, default=[2024],
                        help="evaluation years (validation only; 2025 is sealed)")
    parser.add_argument("--refit-every", type=int, default=1,
                        help="evaluation days per refit (default 1 = daily, as C4/C8/C9)")
    parser.add_argument("--min-train-days", type=int, default=365,
                        help="market days of history required before a fold may run")
    parser.add_argument("--train-window-days", type=int, default=None,
                        help="rolling training window; default expanding")
    parser.add_argument("--dry-run", action="store_true",
                        help="ingest phase: compute and cross-check, append nothing")
    return parser.parse_args(argv)


def tag(zone_key: str, years: list[int]) -> str:
    return f"{zone_key}_{'-'.join(str(y) for y in years)}"


# ---------------------------------------------------------------------------
# Phase 1 — Tier B
# ---------------------------------------------------------------------------


def compute_tier_b_zone(zone_key: str, args: argparse.Namespace) -> dict[str, Any]:
    """naive + train_mean + LEAR (price-only, full history) for one Tier-B zone."""
    spec = WalkForwardSpec(
        refit_every_days=args.refit_every,
        min_train_days=args.min_train_days,
        train_window_days=args.train_window_days,
    )
    lear_spec = LearSpec()
    zones = load_zones()
    zone = zones[zone_key]
    if zone.tier != "B":
        raise ScaleError(
            f"{zone_key} is Tier {zone.tier}; the compute phase is Tier-B only — "
            f"Tier A is ingested from C8's and C9's committed artefacts"
        )

    print(f"\n=== {zone_key} (Tier B, {zone.regime}) ===")
    prices = load_zone_series(zone_key)
    stitch = prices.attrs["stitch_report"]
    print(f"  prices: {stitch.n_points} hours, "
          f"{stitch.first_ts_utc.date()}..{stitch.last_ts_utc.date()}")

    matrix = build_features(prices, zone_key)
    days = evaluation_days(matrix, args.years)
    print(f"  features: {len(matrix.columns)} price/calendar columns, "
          f"{len(matrix.index)} rows; evaluating {len(days)} market days "
          f"{days[0]}..{days[-1]}")

    naive = run_walk_forward(matrix, NaiveLastWeek, days, spec)
    mean_run = run_walk_forward(matrix, TrainMeanBaseline, days, spec)
    naive_scores = score(naive.y_true, naive.y_pred)
    mean_scores = score(mean_run.y_true, mean_run.y_pred)
    print(f"  naive_last_week: MAE {naive_scores.mae:.3f}  RMSE {naive_scores.rmse:.3f}")

    factory = _ReportingFactory(lear_factory(lear_spec, name="lear"), "lear")
    lear = run_walk_forward(matrix, factory, days, spec)
    lear_scores = score(lear.y_true, lear.y_pred)
    if not lear.y_true.index.equals(naive.y_true.index):
        raise ScaleError(
            f"{zone_key}: LEAR and the naive floor were evaluated on different "
            f"indices — they would not be comparable"
        )
    print(f"  lear_price_only: MAE {lear_scores.mae:.3f}  RMSE {lear_scores.rmse:.3f}  "
          f"bias {lear_scores.bias:+.3f}  "
          f"rMAE {rmae(lear.y_true, lear.y_pred, naive.y_pred):.4f}  "
          f"coverage {lear_scores.coverage:.5f}")

    predictions = {
        "lear_price_only": lear.y_pred,
        "naive_last_week": naive.y_pred,
        "train_mean": mean_run.y_pred,
    }
    summary: dict[str, Any] = {
        "cycle": "C10",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "libraries": library_versions(),
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "evaluation_years": list(args.years),
        "walk_forward_spec": spec.as_dict(),
        "lear_spec": lear_spec.as_dict(),
        "train_from": FULL_HISTORY_TRAIN_FROM,
        "price_series": stitch.as_dict(),
        "feature_build": matrix.report.as_dict(),
        "n_rows": int(len(matrix.index)),
        "reference_scores": {
            naive.model_name: naive_scores.as_dict(),
            mean_run.model_name: mean_scores.as_dict(),
        },
        "lear": {
            "scores": lear_scores.as_dict(),
            "rmae_vs_naive": round(rmae(lear.y_true, lear.y_pred, naive.y_pred), 6),
            "skill_vs_train_mean": round(
                skill_score(lear.y_true, lear.y_pred, mean_run.y_pred), 6
            ),
            "n_folds": len(lear.folds),
            "n_fit_reports": len(factory.reports),
            "fit_report_last_fold": factory.reports[-1] if factory.reports else {},
            "declined_rows_total": sum(
                int(r.get("n_predict_declined_nan", 0)) for r in factory.reports
            ),
            "train_rows_dropped_nan_last_fold": (
                factory.reports[-1].get("n_train_rows_dropped_nan") if factory.reports
                else None
            ),
        },
        "walk_forward": lear.as_dict(),
        "note": (
            "Tier B per PLAN.md C10: price-history and calendar features only, "
            "naive + LEAR, C4's committed LearSpec, expanding window over the whole "
            "cached price history. The exogenous block is Tier-A only, and FINDING "
            "C8-A/C9-C are the reason that is not a loss worth mourning."
        ),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    label = tag(zone_key, args.years)
    combined = pd.DataFrame(
        {
            "market_day": matrix.market_day.reindex(lear.y_true.index).to_numpy(),
            "y_true": lear.y_true.to_numpy(dtype="float64"),
        },
        index=lear.y_true.index,
    )
    for name, series in predictions.items():
        combined[f"y_pred_{name}"] = series.to_numpy(dtype="float64")
    predictions_path = RESULTS_DIR / f"c10_tierb_{label}_predictions.csv.gz"
    combined.to_csv(predictions_path, float_format="%.4f")

    folds_path = RESULTS_DIR / f"c10_tierb_{label}_folds.csv"
    lear.folds_frame().to_csv(folds_path, index=False)

    summary_path = RESULTS_DIR / f"c10_tierb_{label}_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    for path in (predictions_path, folds_path, summary_path):
        print(f"  wrote {path.relative_to(REPO_ROOT)} "
              f"({path.stat().st_size / 1024:.0f} KiB)")
    return summary


# ---------------------------------------------------------------------------
# Phase 2 — ingest
# ---------------------------------------------------------------------------


def _load_artefact(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0, parse_dates=[0])
    frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
    return frame


def _assert_prices_match_cache(zone_key: str, y_true: pd.Series, label: str) -> float:
    """The artefact's realised prices against a freshly loaded price series.

    NOTE C2-02: the raw cache does not survive a container, so every cycle
    re-pulls it. That makes this check free and worth doing every time — it is
    the only thing standing between a silently changed upstream series and a
    results table that still looks fine.
    """
    prices = load_zone_series(zone_key)
    column = prices.columns[0]
    fresh = prices[column].reindex(y_true.index)
    if fresh.isna().any():
        raise ScaleError(
            f"{label}: {int(fresh.isna().sum())} hour(s) of the artefact's index are "
            f"absent from the freshly loaded {zone_key} price series"
        )
    worst = float((fresh - y_true).abs().max())
    if worst > RECOMPUTE_TOLERANCE:
        raise ScaleError(
            f"{label}: realised prices disagree with the fresh {zone_key} cache by up "
            f"to {worst} EUR/MWh. That is a data-provenance problem, not rounding."
        )
    return worst


def _check(label: str, metric: str, recomputed: float, committed: Any,
           checks: list[dict[str, Any]]) -> None:
    """Record (and enforce) that a recomputed number equals its committed one."""
    if committed is None:
        return
    delta = abs(float(recomputed) - float(committed))
    checks.append({
        "series": label,
        "metric": metric,
        "recomputed": round(float(recomputed), 6),
        "committed": round(float(committed), 6),
        "abs_delta": round(delta, 9),
    })
    if delta > RECOMPUTE_TOLERANCE:
        raise ScaleError(
            f"{label}: recomputed {metric} {recomputed:.6f} against the committed "
            f"{float(committed):.6f} (delta {delta:.6f} > {RECOMPUTE_TOLERANCE}). The "
            f"store must not carry a number that disagrees with the artefact it "
            f"claims to come from."
        )


def _common_mask(y_true: pd.Series, series: dict[str, pd.Series]) -> pd.Series:
    mask = y_true.notna()
    for value in series.values():
        mask &= value.notna()
    return mask


def _series_rows(
    *,
    zone_key: str,
    tier: str,
    regime: str,
    model: str,
    variant: str,
    train_from: str,
    years: list[int],
    spec: dict[str, Any],
    n_folds: Any,
    scope: str,
    scores: dict[str, Any],
    extra: dict[str, float],
    source: dict[str, str],
    model_fingerprint: str = "",
) -> list[ResultRow]:
    common = {
        "regime": regime,
        "exog_variant": variant,
        "vintage": "after_gate_closure" if variant in LATE_ARMS else "honest",
        "train_from": train_from,
        "evaluation_years": "-".join(str(y) for y in years),
        "refit_every_days": str(spec.get("refit_every_days", "")),
        "min_train_days": str(spec.get("min_train_days", "")),
        "train_window_days": "" if spec.get("train_window_days") is None
                             else str(spec["train_window_days"]),
        "n_folds": "" if n_folds is None else str(n_folds),
        "scope": scope,
        "model_fingerprint": model_fingerprint,
        "source_artefact": source["artefact"],
        "source_cycle": source["cycle"],
        "source_git_sha": source["git_sha"],
    }
    rows = rows_from_scores(
        scores, zone=zone_key, tier=tier, model=model,
        metrics=SCORE_METRICS, **common,
    )
    for metric, value in extra.items():
        rows.append(
            ResultRow(
                zone=zone_key, tier=tier, model=model, metric=metric,
                value=float(value), n=str(scores.get("n", "")),
                n_scored=str(scores.get("n_scored", "")), **common,
            )
        )
    return rows


def ingest_tier_a_zone(zone_key: str, years: list[int]) -> dict[str, Any]:
    """C8's LEAR arms and C9's GBM arms for one Tier-A zone, recomputed and checked."""
    zones = load_zones()
    zone = zones[zone_key]
    label = tag(zone_key, years)
    c8_predictions = RESULTS_DIR / f"c8_exog_{label}_predictions.csv.gz"
    c8_summary_path = RESULTS_DIR / f"c8_exog_{label}_summary.json"
    c9_predictions = RESULTS_DIR / f"c9_gbm_{label}_predictions.csv.gz"
    c9_summary_path = RESULTS_DIR / f"c9_gbm_{label}_summary.json"
    for path in (c8_predictions, c8_summary_path, c9_predictions, c9_summary_path):
        if not path.exists():
            raise ScaleError(
                f"{path} is missing — Tier A's rows come from C8's and C9's committed "
                f"artefacts (see this module's docstring). Re-run that cycle for "
                f"{zone_key} rather than refitting here."
            )

    c8 = _load_artefact(c8_predictions)
    c9 = _load_artefact(c9_predictions)
    with c8_summary_path.open(encoding="utf-8") as fh:
        c8_summary = json.load(fh)
    with c9_summary_path.open(encoding="utf-8") as fh:
        c9_summary = json.load(fh)

    if not c8.index.equals(c9.index):
        raise ScaleError(
            f"{zone_key}: C8's and C9's prediction indices differ "
            f"({len(c8)} vs {len(c9)} rows) — the two cycles did not evaluate the "
            f"same hours and their arms cannot share a zone's table"
        )
    worst_cross = float((c8["y_true"] - c9["y_true"]).abs().max())
    if worst_cross > RECOMPUTE_TOLERANCE:
        raise ScaleError(
            f"{zone_key}: C8's and C9's committed realised prices disagree by up to "
            f"{worst_cross} EUR/MWh"
        )
    y_true = c9["y_true"]
    worst_cache = _assert_prices_match_cache(zone_key, y_true, f"{zone_key} (Tier A)")

    checks: list[dict[str, Any]] = []
    rows: list[ResultRow] = []
    source_c8 = {"artefact": c8_predictions.name, "cycle": "C8",
                 "git_sha": str(c8_summary.get("git_sha", ""))}
    source_c9 = {"artefact": c9_predictions.name, "cycle": "C9",
                 "git_sha": str(c9_summary.get("git_sha", ""))}
    gbm_fingerprint = str(c9_summary.get("gbm_spec", {}).get("fingerprint", ""))
    spec = c9_summary["walk_forward_spec"]

    naive = c9["y_pred_naive_last_week"]

    # --- the nine series C9's artefact carries, on their own coverage --------
    series: dict[str, pd.Series] = {"naive_last_week": naive}
    for arm in EXOG_ARMS:
        for model in ("gbm", "lear"):
            column = f"y_pred_{model}_{arm}"
            if column in c9.columns:
                series[f"{model}_{arm}"] = c9[column]

    for name, values in series.items():
        scores = score(y_true, values).as_dict()
        if name == "naive_last_week":
            model, variant, source, fingerprint, n_folds = (
                "naive_last_week", "", source_c9, "", None,
            )
            committed = c9_summary["reference_scores"]["naive_last_week"]
            extra: dict[str, float] = {}
        else:
            model, arm = name.split("_", 1)
            variant = arm
            source = source_c9 if model == "gbm" else source_c8
            fingerprint = gbm_fingerprint if model == "gbm" else ""
            arm_block = (
                c9_summary["arms"].get(arm, {}) if model == "gbm"
                else c8_summary["arms"].get(arm, {})
            )
            committed = arm_block.get("scores")
            n_folds = arm_block.get("n_folds")
            extra = {"rmae_vs_naive": rmae(y_true, values, naive)}
            if "rmae_vs_naive" in arm_block:
                _check(name, "rmae_vs_naive", extra["rmae_vs_naive"],
                       arm_block["rmae_vs_naive"], checks)
        for metric in ("mae", "rmse", "bias"):
            _check(name, metric, scores[metric], (committed or {}).get(metric), checks)
        rows.extend(_series_rows(
            zone_key=zone_key, tier=zone.tier, regime=zone.regime, model=model,
            variant=variant, train_from=ALIGNED_TRAIN_FROM, years=years, spec=spec,
            n_folds=n_folds, scope="own_coverage", scores=scores, extra=extra,
            source=source, model_fingerprint=fingerprint,
        ))

    # --- the same nine series on the hours all nine answered ----------------
    mask = _common_mask(y_true, series)
    committed_common = c9_summary.get("common_hours", {})
    if int(mask.sum()) != int(committed_common.get("n_hours", mask.sum())):
        raise ScaleError(
            f"{zone_key}: the intersection of C9's nine prediction columns is "
            f"{int(mask.sum())} hours, but C9's summary committed "
            f"{committed_common.get('n_hours')} — the artefact and its summary "
            f"disagree about what was compared"
        )
    for name, values in series.items():
        scores = score(y_true[mask], values[mask]).as_dict()
        committed = committed_common.get("scores", {}).get(name)
        for metric in ("mae", "rmse", "bias"):
            _check(f"{name} (common)", metric, scores[metric],
                   (committed or {}).get(metric), checks)
        if name == "naive_last_week":
            model, variant, source, fingerprint, extra = (
                "naive_last_week", "", source_c9, "", {},
            )
        else:
            model, variant = name.split("_", 1)
            source = source_c9 if model == "gbm" else source_c8
            fingerprint = gbm_fingerprint if model == "gbm" else ""
            extra = {"rmae_vs_naive": rmae(y_true[mask], values[mask], naive[mask])}
        rows.extend(_series_rows(
            zone_key=zone_key, tier=zone.tier, regime=zone.regime, model=model,
            variant=variant, train_from=ALIGNED_TRAIN_FROM, years=years, spec=spec,
            n_folds=None, scope="common_hours", scores=scores, extra=extra,
            source=source, model_fingerprint=fingerprint,
        ))

    # --- the full-history LEAR, which is the nine-zone comparable series ----
    full_column = "y_pred_price_only_full_history"
    if full_column not in c8.columns:
        raise ScaleError(
            f"{zone_key}: C8's artefact has no {full_column} column, so Tier A has "
            f"no counterpart to Tier B's full-history LEAR and the nine-zone table "
            f"would not be like-for-like"
        )
    full = c8[full_column]
    full_scores = score(y_true, full).as_dict()
    committed_full = c8_summary.get("full_history_reference", {})
    for metric in ("mae", "rmse", "bias"):
        _check("lear_price_only (full history)", metric, full_scores[metric],
               committed_full.get("scores", {}).get(metric), checks)
    full_rmae = rmae(y_true, full, naive)
    _check("lear_price_only (full history)", "rmae_vs_naive", full_rmae,
           committed_full.get("rmae_vs_naive"), checks)
    rows.extend(_series_rows(
        zone_key=zone_key, tier=zone.tier, regime=zone.regime, model="lear",
        variant="price_only", train_from=FULL_HISTORY_TRAIN_FROM, years=years,
        spec=c8_summary["walk_forward_spec"], n_folds=None, scope="own_coverage",
        scores=full_scores, extra={"rmae_vs_naive": full_rmae}, source=source_c8,
    ))

    print(f"  {zone_key:9s} Tier A: {len(series)} aligned series + full-history LEAR, "
          f"{int(mask.sum())} common hours, {len(checks)} cross-checks all within "
          f"{RECOMPUTE_TOLERANCE}, cache agreement {worst_cache:.6f} EUR/MWh")
    return {
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "rows": rows,
        "checks": checks,
        "n_common_hours": int(mask.sum()),
        "worst_y_true_vs_cache_eur_mwh": round(worst_cache, 6),
        "worst_c8_vs_c9_y_true_eur_mwh": round(worst_cross, 6),
        "sources": [source_c8, source_c9],
    }


def ingest_tier_b_zone(zone_key: str, years: list[int]) -> dict[str, Any]:
    """This cycle's Tier-B artefact for one zone, recomputed and checked."""
    zones = load_zones()
    zone = zones[zone_key]
    label = tag(zone_key, years)
    predictions_path = RESULTS_DIR / f"c10_tierb_{label}_predictions.csv.gz"
    summary_path = RESULTS_DIR / f"c10_tierb_{label}_summary.json"
    for path in (predictions_path, summary_path):
        if not path.exists():
            raise ScaleError(
                f"{path} is missing — run `--phase compute --zones {zone_key}` first"
            )
    frame = _load_artefact(predictions_path)
    with summary_path.open(encoding="utf-8") as fh:
        summary = json.load(fh)

    y_true = frame["y_true"]
    worst_cache = _assert_prices_match_cache(zone_key, y_true, f"{zone_key} (Tier B)")
    naive = frame["y_pred_naive_last_week"]
    lear = frame["y_pred_lear_price_only"]
    mean = frame["y_pred_train_mean"]

    checks: list[dict[str, Any]] = []
    rows: list[ResultRow] = []
    source = {"artefact": predictions_path.name, "cycle": "C10",
              "git_sha": str(summary.get("git_sha", ""))}
    spec = summary["walk_forward_spec"]

    series = {
        "lear_price_only": lear,
        "naive_last_week": naive,
        "train_mean": mean,
    }
    committed_by_series = {
        "lear_price_only": summary["lear"]["scores"],
        "naive_last_week": summary["reference_scores"]["naive_last_week"],
        "train_mean": summary["reference_scores"]["train_mean"],
    }

    for scope, mask in (
        ("own_coverage", y_true.notna()),
        ("common_hours", _common_mask(y_true, series)),
    ):
        for name, values in series.items():
            scores = score(y_true[mask], values[mask]).as_dict()
            if scope == "own_coverage":
                for metric in ("mae", "rmse", "bias"):
                    _check(name, metric, scores[metric],
                           committed_by_series[name].get(metric), checks)
            model = "lear" if name == "lear_price_only" else name
            variant = "price_only" if name == "lear_price_only" else ""
            extra: dict[str, float] = {}
            if name == "lear_price_only":
                extra["rmae_vs_naive"] = rmae(y_true[mask], values[mask], naive[mask])
                extra["skill_vs_train_mean"] = skill_score(
                    y_true[mask], values[mask], mean[mask]
                )
                if scope == "own_coverage":
                    _check(name, "rmae_vs_naive", extra["rmae_vs_naive"],
                           summary["lear"].get("rmae_vs_naive"), checks)
                    _check(name, "skill_vs_train_mean", extra["skill_vs_train_mean"],
                           summary["lear"].get("skill_vs_train_mean"), checks)
            rows.extend(_series_rows(
                zone_key=zone_key, tier=zone.tier, regime=zone.regime, model=model,
                variant=variant, train_from=FULL_HISTORY_TRAIN_FROM, years=years,
                spec=spec, n_folds=summary["lear"].get("n_folds") if model == "lear" else None,
                scope=scope, scores=scores, extra=extra, source=source,
            ))

    n_common = int(_common_mask(y_true, series).sum())
    print(f"  {zone_key:9s} Tier B: {len(series)} series, {n_common} common hours, "
          f"{len(checks)} cross-checks all within {RECOMPUTE_TOLERANCE}, "
          f"cache agreement {worst_cache:.6f} EUR/MWh")
    return {
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "rows": rows,
        "checks": checks,
        "n_common_hours": n_common,
        "worst_y_true_vs_cache_eur_mwh": round(worst_cache, 6),
        "sources": [source],
    }


def _comparable_table(rows: list[ResultRow]) -> dict[str, Any]:
    """The nine-zone like-for-like table: naive vs full-history price-only LEAR."""
    wanted = {
        ("naive_last_week", ""),
        ("lear", "price_only"),
    }
    table: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.scope != "own_coverage":
            continue
        if (row.model, row.exog_variant) not in wanted:
            continue
        if row.model == "lear" and row.train_from != FULL_HISTORY_TRAIN_FROM:
            continue
        series = "lear_price_only" if row.model == "lear" else row.model
        entry = table.setdefault(row.zone, {"tier": row.tier, "regime": row.regime})
        entry[f"{series}_{row.metric}"] = round(row.value, 6)
        if row.metric == "mae":
            entry[f"{series}_n_scored"] = int(row.n_scored or 0)
    for zone, entry in table.items():
        naive_mae = entry.get("naive_last_week_mae")
        lear_mae = entry.get("lear_price_only_mae")
        if naive_mae and lear_mae:
            entry["lear_mae_as_fraction_of_naive"] = round(lear_mae / naive_mae, 6)
    return {
        "series": ["naive_last_week", "lear_price_only"],
        "train_from": FULL_HISTORY_TRAIN_FROM,
        "scope": "own_coverage",
        "zones": table,
        "note": (
            "Like-for-like across all nine zones: C4's committed LEAR on price-history "
            "and calendar features, expanding window over the whole cached history, "
            "against the naive floor. For Tier A these are C8's committed "
            "full_history_reference rows, for Tier B this cycle's runs. LEAR's "
            "n_scored is one below the naive floor's because it declines the autumn "
            "DST hour whose 24-hour lag the gate-closure mask blanks (FINDING C3-A)."
        ),
    }


def ingest(args: argparse.Namespace) -> dict[str, Any]:
    zones = load_zones()
    years = list(args.years)
    per_zone: list[dict[str, Any]] = []
    print("\n=== ingest ===")
    for key, zone in zones.items():
        if zone.tier == "A":
            per_zone.append(ingest_tier_a_zone(key, years))
        else:
            per_zone.append(ingest_tier_b_zone(key, years))

    rows = [row for z in per_zone for row in z["rows"]]
    checks = [c for z in per_zone for c in z["checks"]]
    worst_check = max((c["abs_delta"] for c in checks), default=0.0)
    comparable = _comparable_table(rows)

    print(f"\n  {len(rows)} result rows across {len(per_zone)} zones; "
          f"{len(checks)} recomputed-vs-committed cross-checks, worst delta "
          f"{worst_check:.9f} (tolerance {RECOMPUTE_TOLERANCE})")
    print("\n  nine-zone comparable table (MAE, EUR/MWh):")
    print(f"    {'zone':9s} {'tier':4s} {'naive':>9s} {'lear':>9s} {'lear/naive':>11s}  regime")
    for zone, entry in comparable["zones"].items():
        print(f"    {zone:9s} {entry['tier']:4s} "
              f"{entry.get('naive_last_week_mae', float('nan')):9.3f} "
              f"{entry.get('lear_price_only_mae', float('nan')):9.3f} "
              f"{entry.get('lear_mae_as_fraction_of_naive', float('nan')):11.4f}  "
              f"{entry['regime']}")

    report: dict[str, Any] = {
        "cycle": "C10",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "libraries": library_versions(),
        "evaluation_years": years,
        "n_rows": len(rows),
        "n_zones": len(per_zone),
        "zones": [
            {k: v for k, v in z.items() if k not in ("rows", "checks")} for z in per_zone
        ],
        "cross_checks": {
            "n": len(checks),
            "tolerance_eur_mwh": RECOMPUTE_TOLERANCE,
            "worst_abs_delta": worst_check,
            "note": (
                "Every metric written into the store was recomputed from the "
                "artefact's prediction columns and asserted equal to the number its "
                "source cycle committed, to the artefact's own %.4f precision. The "
                "store therefore cannot carry a number that disagrees with the "
                "artefact it cites."
            ),
            "checks": checks,
        },
        "comparable_table": comparable,
    }

    if args.dry_run:
        print("\n  --dry-run: nothing appended to the store")
        report["appended"] = None
    else:
        append = append_rows(
            rows,
            cycle="C10",
            git_sha=git_sha(),
            config_hash=config_hash(),
            argv=list(sys.argv[1:]),
            note=(
                "C10 scale-out: Tier A ingested from C8 (LEAR arms) and C9 (GBM arms) "
                "committed artefacts with every metric recomputed and cross-checked; "
                "Tier B computed in this cycle (naive + LEAR, price-only, full "
                "history). res_as_published rows carry vintage=after_gate_closure."
            ),
        )
        report["appended"] = append.as_dict()
        verification = verify_append_only()
        report["append_only_verification"] = verification
        print(f"\n  appended {append.n_rows_appended} rows as run {append.run_id} "
              f"({append.n_rows_before} -> {append.n_rows_after} rows)")
        print(f"  append-only verification: {verification['n_runs']} run(s), "
              f"{verification['n_rows']} rows, verified={verification['verified']}")

    report_path = RESULTS_DIR / "c10_scale_summary.json"
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
        fh.write("\n")
    print(f"  wrote {report_path.relative_to(REPO_ROOT)} "
          f"({report_path.stat().st_size / 1024:.0f} KiB)")
    return report


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    zones = load_zones()
    if args.phase in ("compute", "all"):
        selected = args.zones or [k for k, z in zones.items() if z.tier == "B"]
        unknown = [z for z in selected if z not in zones]
        if unknown:
            print(f"unknown zone key(s): {unknown}; known: {sorted(zones)}",
                  file=sys.stderr)
            return 2
        for zone_key in selected:
            compute_tier_b_zone(zone_key, args)
    if args.phase in ("ingest", "all"):
        ingest(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
