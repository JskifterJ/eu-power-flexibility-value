"""CLI: the C13 regime analysis — one evaluation year at a time, 2020-2024.

    python -m backtest.run_c13_regime --phase compute --zones DE-LU --years 2022
    python -m backtest.run_c13_regime --phase dispatch
    python -m backtest.run_c13_regime --phase analyse
    python -m backtest.run_c13_regime --phase ingest

PLAN.md C13: *"Regime analysis: 2022 crisis year reported separately; per-year
tables; pre/post 2025-10-01 flagged; negative-hour counts per zone."*

The cycle has three parts and they are deliberately separable, because only the
first one is expensive:

**``compute`` — the only new fitting.** Every earlier cycle evaluated **2024
only**, so "per-year tables" and "the 2022 crisis year reported separately" did
not exist as results, merely as a wish (NOTE C12-01). This phase walks the
nine-zone comparable arm — C4's committed LEAR on price-history and calendar
features, expanding window from the start of the price history — forward across
one evaluation year at a time for **2020, 2021, 2022 and 2023**, alongside the
naive floor it is measured against. 2019 cannot be an evaluation year
(``min_train_days=365`` and the history starts 2019-01-01) and 2025 is sealed.
Each ``(zone, year)`` is independent, so several processes may run this phase in
parallel; nothing is appended to the store here, which is what makes that safe.

**``dispatch`` — the battery LP on the new years.** Oracle, the comparable LEAR
and the naive floor, through C5/C6's rolling-horizon commit-then-settle
machinery, with C11's ``pooled_capture`` imported rather than re-derived so a
2022 capture ratio means exactly what the 2024 one in ``results.csv`` means.
**2024 is not re-dispatched**: C11 committed its per-day rows and C12's
reproduction check bounds them, so this cycle reads that artefact and re-pools
it, which is also what makes the 2024 column of every per-year table identical
to the number already published.

**``analyse`` — the per-year tables, and the regime split.** Per (zone, year):
capture, EUR/MW/yr, MAE, rMAE, the two C12 decision-relevant metrics, the
realised spread, and the negative-hour count PLAN.md asks for. Across years:
2022 reported on its own, the eight-zone capture band with its noise-only p per
year (**the second-year test FINDINGs C12-B/C12-D/C12-E are waiting on**), and
NO2's capture and within-day Spearman per year.

What this cycle is careful not to claim
---------------------------------------
2020-2023 are PLAN.md **training** years. Every prediction here is a genuine
expanding-window walk-forward — a fold never sees its own day, and the
gate-closure guard runs on every feature matrix — so these are out-of-sample
*predictions*. They are **not** an out-of-sample *configuration* test: C4 chose
the LEAR spec while looking at 2024, and the GBM config was frozen in C9 the
same way. So a year added here weakens "one year decides too little" without
being the clean second draw 2025 will be, and every finding this cycle writes
carries that label. The sealed holdout is the only clean test and it stays
sealed until Checkpoint C.

Pre/post 2025-10-01 (PLAN.md's 15-minute cutover)
-------------------------------------------------
Nothing in this project has crossed it: ``config/data.yaml`` stops fetching at
2024, the main hourly backtest ends 2025-09-30, and 2025 is sealed. So the
cutover appears here as what it is — a **flag on the evaluated window** (every
row is pre-cutover, stated per year in ``c13_cutover_status.json``) — and not as
a comparison. ``data/contracts.py`` already carries the resolution-change
detection that would catch a post-cutover file if one ever landed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from backtest.bootstrap import (
    BlockBootstrapSpec,
    _interval,
    noise_only_spread,
    spearman_rows,
)
from backtest.metrics import daily_shape_table, rmae, score
from backtest.results_store import (
    ResultRow,
    append_rows,
    library_fingerprint,
    library_versions,
    verify_append_only,
)
from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.run_c5_oracle_lp import (
    check_day_lengths,
    check_value_added_non_negative,
    load_realised,
    simultaneity_flag,
)
from backtest.run_c11_dispatch import (
    FULL_HISTORY_FROM,
    ORACLE_MODEL,
    ORACLE_VARIANT,
    beats_naive,
    mae_on_days,
    pooled_capture,
)
from backtest.run_c12_metrics import (
    Basis,
    CANDIDATE_METRICS,
    CurveDays,
    cross_zone_analysis,
    curve_replicates,
    point_metrics,
    rmae_point,
)
from backtest.walk_forward import WalkForwardSpec, evaluation_days, run_walk_forward
from data.config import config_hash, load_battery_config, load_data_config, load_zones
from data.energy_charts import PRICE_COLUMN
from data.holdout import assert_not_sealed
from data.manifest import MANIFEST_CSV
from data.prices import load_zone_series
from dispatch.battery import BatterySpec
from dispatch.curves import (
    Curve,
    assert_curve_aligns,
    assert_settlement_is_not_a_readback,
    capture_frame,
    check_decision_value_added_non_negative,
    check_per_day_dominance,
    common_days,
    report_realised_losses,
    same_start_oracle,
)
from dispatch.rolling import RollingResult, run_rolling_dispatch
from forecast.features import build_features
from forecast.lear import LearSpec, lear_factory
from forecast.models import NaiveLastWeek
from forecast.timing import market_days, zone_timezone

#: The evaluation years this cycle adds. 2019 cannot be one (``min_train_days``
#: 365 against a history that starts 2019-01-01) and 2025 is sealed; 2024 is
#: read from C11's committed artefact rather than recomputed.
NEW_YEARS: tuple[int, ...] = (2020, 2021, 2022, 2023)

#: The year every earlier cycle evaluated, and the one PLAN.md calls the
#: validation year.
VALIDATION_YEAR = 2024

#: PLAN.md's crisis year, reported separately.
CRISIS_YEAR = 2022

#: The three curves of the per-year comparison. The comparable LEAR is the arm
#: FINDING C10-B and the whole cross-zone table are built on; the naive floor is
#: the denominator of every rMAE; the oracle is the denominator of every capture
#: ratio.
COMPARABLE_CURVE = "lear_full_history"
NAIVE_CURVE = "naive"
ORACLE_CURVE = "oracle"

#: The prediction columns this cycle's own artefacts carry.
LEAR_COLUMN = "y_pred_lear_price_only"
NAIVE_COLUMN = "y_pred_naive_last_week"

#: C11's per-day dispatch artefact, the source of the 2024 column.
C11_DAILY = "c11_capture_daily_2024.csv.gz"

#: The zone FINDING C11-B singles out, carried through every table so the
#: "is the band a finding about NO2" question is answerable per year.
OUTLIER_ZONE = "NO2"


class RegimeError(RuntimeError):
    """The regime analysis cannot proceed without making a number untrustworthy."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=["compute", "dispatch", "analyse", "ingest"],
        default="compute",
    )
    parser.add_argument("--zones", nargs="*", default=None, help="zone keys (default: all)")
    parser.add_argument(
        "--years", nargs="*", type=int, default=list(NEW_YEARS),
        help="evaluation years for compute/dispatch (2025 is sealed)",
    )
    parser.add_argument("--refit-every", type=int, default=1,
                        help="evaluation days per refit (default 1 = daily, as C4/C10)")
    parser.add_argument("--min-train-days", type=int, default=365,
                        help="market days of history required before a fold may run")
    parser.add_argument("--train-window-days", type=int, default=None,
                        help="rolling training window; default expanding, as C4/C10")
    parser.add_argument("--no-append", action="store_true",
                        help="ingest phase: compute the rows, append nothing")
    parser.add_argument("--results-path", default=None, help="override the store path (tests)")
    return parser.parse_args(argv)


def selected_zones(requested: list[str] | None) -> dict[str, Any]:
    zones = load_zones()
    keys = requested or list(zones)
    unknown = [z for z in keys if z not in zones]
    if unknown:
        raise RegimeError(f"unknown zone key(s): {unknown}; known: {sorted(zones)}")
    return {k: zones[k] for k in keys}


def artefact_tag(zone: str, year: int) -> str:
    return f"{zone}_{year}"


def predictions_path(zone: str, year: int):
    return RESULTS_DIR / f"c13_year_{artefact_tag(zone, year)}_predictions.csv.gz"


def compute_summary_path(zone: str, year: int):
    return RESULTS_DIR / f"c13_year_{artefact_tag(zone, year)}_summary.json"


def dispatch_daily_path(zone: str, year: int):
    return RESULTS_DIR / f"c13_dispatch_{artefact_tag(zone, year)}_daily.csv.gz"


def dispatch_summary_path(zone: str, year: int):
    return RESULTS_DIR / f"c13_dispatch_{artefact_tag(zone, year)}_summary.json"


# ---------------------------------------------------------------------------
# Phase 1 — compute: the comparable arm, one evaluation year at a time
# ---------------------------------------------------------------------------


def compute_zone_year(zone_key: str, year: int, args: argparse.Namespace) -> dict[str, Any]:
    """Walk the naive floor and the comparable LEAR forward across one year."""
    assert_not_sealed(year, f"walk {zone_key} forward across {year}")
    zones = load_zones()
    zone = zones[zone_key]
    spec = WalkForwardSpec(
        refit_every_days=args.refit_every,
        min_train_days=args.min_train_days,
        train_window_days=args.train_window_days,
    )
    lear_spec = LearSpec()

    print(f"\n=== {zone_key} {year} (tier {zone.tier}, {zone.regime}) ===", flush=True)
    prices = load_zone_series(zone_key)
    stitch = prices.attrs["stitch_report"]
    matrix = build_features(prices, zone_key)
    days = evaluation_days(matrix, [year])
    if not days:
        raise RegimeError(f"{zone_key} {year}: no evaluation day survived the feature build")
    print(f"  prices {stitch.n_points} hours {stitch.first_ts_utc.date()}.."
          f"{stitch.last_ts_utc.date()}; evaluating {len(days)} market days "
          f"{days[0]}..{days[-1]}", flush=True)

    naive = run_walk_forward(matrix, NaiveLastWeek, days, spec)
    lear = run_walk_forward(matrix, lear_factory(lear_spec, name="lear"), days, spec)
    if not lear.y_true.index.equals(naive.y_true.index):
        raise RegimeError(
            f"{zone_key} {year}: LEAR and the naive floor were evaluated on different "
            f"indices — they would not be comparable"
        )
    naive_scores = score(naive.y_true, naive.y_pred)
    lear_scores = score(lear.y_true, lear.y_pred)
    ratio = rmae(lear.y_true, lear.y_pred, naive.y_pred)
    print(f"  naive MAE {naive_scores.mae:.3f}   LEAR MAE {lear_scores.mae:.3f}   "
          f"rMAE {ratio:.4f}   coverage {lear_scores.coverage:.5f}", flush=True)

    frame = pd.DataFrame(
        {
            "market_day": matrix.market_day.reindex(lear.y_true.index).to_numpy(),
            "y_true": lear.y_true.to_numpy(dtype="float64"),
            LEAR_COLUMN: lear.y_pred.to_numpy(dtype="float64"),
            NAIVE_COLUMN: naive.y_pred.to_numpy(dtype="float64"),
        },
        index=lear.y_true.index,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(predictions_path(zone_key, year), float_format="%.4f")

    summary = {
        "cycle": "C13",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "libraries": library_versions(),
        "library_fingerprint": library_fingerprint(),
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "evaluation_years": [year],
        "train_from": FULL_HISTORY_FROM,
        "walk_forward_spec": spec.as_dict(),
        "lear_spec": lear_spec.as_dict(),
        "price_series": stitch.as_dict(),
        "feature_build": matrix.report.as_dict(),
        "n_rows": int(len(matrix.index)),
        "n_evaluation_days": len(days),
        "first_day": days[0].isoformat(),
        "last_day": days[-1].isoformat(),
        "scores": {
            "naive_last_week": naive_scores.as_dict(),
            "lear_price_only": lear_scores.as_dict(),
        },
        "rmae_vs_naive": round(ratio, 6),
        "n_folds": len(lear.folds),
        "walk_forward": lear.as_dict(),
        "note": (
            "C13's per-year arm is exactly C10's nine-zone comparable arm — C4's "
            "committed LearSpec on price-history and calendar features, expanding "
            "window over the whole cached history — run on one earlier evaluation "
            "year. PLAN.md calls 2020-2023 training years: these predictions are "
            "out-of-sample (a fold never sees its own day) but the model "
            "configuration was chosen while looking at 2024, so this is not a "
            "configuration holdout. 2025 remains sealed."
        ),
    }
    with compute_summary_path(zone_key, year).open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    folds = lear.folds_frame()
    folds.to_csv(RESULTS_DIR / f"c13_year_{artefact_tag(zone_key, year)}_folds.csv",
                 index=False)
    return summary


def compute(args: argparse.Namespace) -> int:
    zones = selected_zones(args.zones)
    years = sorted(set(args.years))
    for year in years:
        assert_not_sealed(year, "C13 compute phase")
    done: list[str] = []
    for zone_key in zones:
        for year in years:
            if predictions_path(zone_key, year).exists():
                print(f"{zone_key} {year}: artefact already present, skipped", flush=True)
                continue
            compute_zone_year(zone_key, year, args)
            done.append(f"{zone_key}/{year}")
    print(f"\ncompute phase done: {len(done)} (zone, year) run(s) — {', '.join(done)}")
    return 0



# ---------------------------------------------------------------------------
# Phase 2 — dispatch: the battery LP on the new years
# ---------------------------------------------------------------------------

#: The per-day columns the artefact carries, in C12's spelling. Keeping the
#: column names identical to ``c12_daily_metrics_2024.csv.gz`` is what lets the
#: analyse phase build one frame across years and feed it to C12's own metric
#: and bootstrap code, so a 2022 capture ratio is produced by the same lines of
#: Python as the 2024 one already in ``results.csv``.
DAILY_COLUMNS: tuple[str, ...] = (
    "zone", "curve", "market_day", "cash", "oracle_cash", "lost", "value_added",
    "realised_spread", "in_common_day_set", "n_dispatch_hours", "n_hours",
    "sum_abs_error", "sum_sq_error", "sum_error", "realised_spread_forecastwise",
    "forecast_spread", "spread_error", "abs_spread_error", "spearman",
    "spearman_contrib", "spearman_defined", "model", "exog_variant", "vintage",
    "train_from", "tier", "regime", "year",
)

#: ``(curve, column, model, exog_variant)`` for the two forecast curves of this
#: cycle. The oracle is not a forecast and is handled separately.
C13_ARMS: tuple[tuple[str, str, str, str], ...] = (
    (COMPARABLE_CURVE, LEAR_COLUMN, "lear", "price_only"),
    (NAIVE_CURVE, NAIVE_COLUMN, "naive_last_week", ""),
)


def load_c13_prediction_frame(zone: str, year: int, realised: pd.Series) -> pd.DataFrame:
    """This cycle's prediction artefact, checked against the realised series.

    The same provenance check C11 runs on C8's and C10's artefacts: every
    forecast timestamp must exist in the realised series and the artefact's own
    ``y_true`` must equal it hour for hour. An off-by-one index is a leak that
    looks like skill, and the per-day oracle bound would only catch it
    afterwards.
    """
    path = predictions_path(zone, year)
    if not path.exists():
        raise RegimeError(
            f"{zone} {year}: {path.name} is missing — run the compute phase first"
        )
    frame = pd.read_csv(path, dtype={"market_day": str})
    for column in ("timestamp_utc", "market_day", "y_true", LEAR_COLUMN, NAIVE_COLUMN):
        if column not in frame.columns:
            raise RegimeError(f"{path.name} has no {column!r} column")
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
    frame = frame.set_index(index).sort_index()
    aligned = realised.reindex(frame.index)
    if aligned.isna().any():
        raise RegimeError(
            f"{zone} {year}: {int(aligned.isna().sum())} forecast timestamp(s) have "
            f"no realised price — the artefact and the price cache disagree on the grid"
        )
    gap = float(
        np.nanmax(
            np.abs(frame["y_true"].to_numpy(dtype=float) - aligned.to_numpy(dtype=float))
        )
    )
    if gap > 1e-6:
        raise RegimeError(
            f"{zone} {year}: the artefact's y_true differs from the realised price "
            f"series by up to {gap:.6g} EUR/MWh — one of the two is not what was scored"
        )
    frame.attrs["max_y_true_vs_realised_gap"] = gap
    return frame


def shape_table_for(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """C12's per-day shape table for one forecast column, with its derived flags."""
    table = daily_shape_table(frame["y_true"], frame[column], frame["market_day"].to_numpy())
    table = table.rename(columns={"realised_spread": "realised_spread_forecastwise"})
    table["abs_spread_error"] = table["spread_error"].abs()
    defined = np.isfinite(table["spearman"].to_numpy(dtype=float))
    table["spearman_defined"] = defined.astype(float)
    table["spearman_contrib"] = np.where(
        defined, table["spearman"].to_numpy(dtype=float), 0.0
    )
    return table


def dispatch_zone_year(
    zone_key: str, year: int, spec: BatterySpec, cfg: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Oracle + comparable LEAR + naive floor through the rolling LP, one year."""
    assert_not_sealed(year, f"dispatch {zone_key} {year}")
    zones = load_zones()
    zone = zones[zone_key]
    tz = zone_timezone(zone_key)
    terminal = cfg.get("terminal") or {}
    roll_kwargs = dict(
        trailing_days=int(terminal.get("trailing_days", 7)),
        trailing_quantile=float(terminal.get("trailing_quantile", 0.5)),
        min_trailing_days=int(terminal.get("min_trailing_days", 1)),
        tz=tz,
    )

    realised = load_realised(zone_key, [year])
    frame = load_c13_prediction_frame(zone_key, year, realised)
    curves = {
        curve: Curve(
            name=curve,
            prices=frame[column].astype(float),
            source=f"{predictions_path(zone_key, year).name}:{column}",
        )
        for curve, column, _, _ in C13_ARMS
    }

    forecast_days: set[dt.date] = set()
    for curve in curves.values():
        forecast_days |= set(market_days(pd.DatetimeIndex(curve.prices.index), tz).tolist())
    labels = pd.Series(realised.index).dt.tz_convert(tz).dt.date
    wanted = {d for d in labels if d.year == year} & forecast_days
    if not wanted:
        raise RegimeError(f"{zone_key} {year}: no market day is both in the year and forecast")

    print(f"\n=== {zone_key} {year} (tier {zone.tier}, {zone.regime}) — "
          f"{len(curves)} forecast curve(s) + oracle over {len(wanted)} market days "
          f"{min(wanted)} .. {max(wanted)} ===", flush=True)

    results: dict[str, RollingResult] = {
        ORACLE_CURVE: run_rolling_dispatch(
            zone_key, realised, spec, decision_prices=None, curve=ORACLE_CURVE,
            days=wanted, **roll_kwargs
        )
    }
    for curve, _, _, _ in C13_ARMS:
        results[curve] = run_rolling_dispatch(
            zone_key, realised, spec, decision_prices=curves[curve].prices,
            curve=curve, days=wanted, **roll_kwargs
        )
    bounds = {name: same_start_oracle(res, spec) for name, res in results.items()}
    own = {name: set(res.days) for name, res in results.items()}
    shared = common_days(results)

    pooled: dict[str, dict[str, Any]] = {
        name: {
            "own_coverage": pooled_capture(
                res, bounds[name], results[ORACLE_CURVE], own[name], spec.power_mw
            ),
            "common_hours": pooled_capture(
                res, bounds[name], results[ORACLE_CURVE], shared, spec.power_mw
            ),
        }
        for name, res in results.items()
    }

    # --- invariants (CLAUDE.md), every curve -----------------------------
    invariants: dict[str, dict[str, Any]] = {}
    for name, res in results.items():
        block: dict[str, Any] = {
            "day_lengths_match_local_calendar": check_day_lengths(res, zone_key),
            "settlement_is_not_a_decision_price_readback":
                assert_settlement_is_not_a_readback(res),
            "decision_value_added_non_negative":
                check_decision_value_added_non_negative(res, spec),
        }
        if name == ORACLE_CURVE:
            block["value_added_non_negative_at_realised"] = (
                check_value_added_non_negative(res)
            )
        else:
            block["same_start_oracle_dominates_every_day"] = check_per_day_dominance(
                res, bounds[name]
            )
            block["beats_naive_pooled_common_days"] = (
                {"applicable": False, "reason": "this is the naive floor"}
                if name == NAIVE_CURVE
                else beats_naive(res, results[NAIVE_CURVE], shared)
            )
            arm_cash = pooled[name]["common_hours"]["cash_eur"]
            oracle_cash = pooled[ORACLE_CURVE]["common_hours"]["cash_eur"]
            block["oracle_dominates_pooled_common_days"] = {
                "holds": oracle_cash >= arm_cash - 1e-6,
                "oracle_cash_eur": round(oracle_cash, 4),
                "arm_cash_eur": round(arm_cash, 4),
                "margin_eur": round(oracle_cash - arm_cash, 4),
                "capture_rolled_oracle_cash": round(
                    pooled[name]["common_hours"]["capture_rolled_oracle_cash"], 6
                ),
            }
        invariants[name] = block
    failures = [
        f"{name}.{check}"
        for name, block in invariants.items()
        for check, outcome in block.items()
        if outcome.get("applicable", True) and not outcome.get("holds", True)
    ]
    for name in sorted(results):
        block = pooled[name]["common_hours"]
        rolled = block["capture_rolled_oracle_cash"]
        mark = "OK " if not any(f.startswith(f"{name}.") for f in failures) else "FAIL"
        print(f"  [{mark}] {name:<20} cash {block['cash_eur']:>10,.0f} EUR  "
              f"{block['cash_eur_per_mw_year']:>9,.0f} EUR/MW/yr  "
              f"capture {'  n/a ' if rolled is None else f'{rolled:.4f}'}", flush=True)

    # --- the per-day artefact, in C12's column shape ---------------------
    shapes = {curve: shape_table_for(frame, column) for curve, column, _, _ in C13_ARMS}
    shared_labels = {d.isoformat() for d in shared}
    frames: list[pd.DataFrame] = []
    for name, res in results.items():
        captured = capture_frame(res, results[ORACLE_CURVE], bounds[name])
        if captured.empty:
            continue
        block = pd.DataFrame(index=pd.Index(captured["market_day"], name="market_day"))
        block["zone"] = zone_key
        block["curve"] = name
        block["cash"] = captured["cash_eur"].to_numpy(dtype=float)
        block["oracle_cash"] = captured["rolled_oracle_cash_eur"].to_numpy(dtype=float)
        block["lost"] = block["oracle_cash"] - block["cash"]
        block["value_added"] = captured["value_added_eur"].to_numpy(dtype=float)
        block["realised_spread"] = captured["realised_spread"].to_numpy(dtype=float)
        block["in_common_day_set"] = [d in shared_labels for d in block.index]
        block["n_dispatch_hours"] = captured["n_hours"].to_numpy(dtype=int)
        if name == ORACLE_CURVE:
            for column in (
                "n_hours", "sum_abs_error", "sum_sq_error", "sum_error",
                "realised_spread_forecastwise", "forecast_spread", "spread_error",
                "abs_spread_error", "spearman", "spearman_contrib", "spearman_defined",
            ):
                block[column] = np.nan
            block["model"], block["exog_variant"] = ORACLE_MODEL, ORACLE_VARIANT
            block["train_from"] = ""
        else:
            aligned = shapes[name].reindex(block.index)
            if aligned["n_hours"].isna().any():
                absent = aligned.index[aligned["n_hours"].isna()].tolist()
                raise RegimeError(
                    f"{zone_key} {year}/{name}: {len(absent)} dispatched day(s) have no "
                    f"hourly forecast rows, first {absent[0]} — the dispatch and the "
                    f"prediction artefact disagree about which days exist"
                )
            for column in (
                "n_hours", "sum_abs_error", "sum_sq_error", "sum_error",
                "realised_spread_forecastwise", "forecast_spread", "spread_error",
                "abs_spread_error", "spearman", "spearman_contrib", "spearman_defined",
            ):
                block[column] = aligned[column].to_numpy(dtype=float)
            arm = next(a for a in C13_ARMS if a[0] == name)
            block["model"], block["exog_variant"] = arm[2], arm[3]
            block["train_from"] = FULL_HISTORY_FROM
        block["vintage"] = "honest"
        block["tier"], block["regime"] = zone.tier, zone.regime
        block["year"] = year
        frames.append(block.reset_index())
    daily = pd.concat(frames, ignore_index=True)[list(DAILY_COLUMNS)]

    summary = {
        "cycle": "C13",
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "year": year,
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "battery_spec": spec.as_dict(),
        "n_market_days_wanted": len(wanted),
        "dispatched_days_per_curve": {n: len(d) for n, d in sorted(own.items())},
        "n_common_days": len(shared),
        "skipped_days_per_curve": {
            name: [s.as_dict() for s in res.skipped] for name, res in results.items()
        },
        "curve_sources": {
            curve: {
                **curves[curve].as_dict(),
                "source": curves[curve].source,
                "alignment": assert_curve_aligns(curves[curve], realised),
            }
            for curve in curves
        },
        "max_y_true_vs_realised_gap": frame.attrs["max_y_true_vs_realised_gap"],
        "pooled": pooled,
        "invariants": invariants,
        "invariant_failures": failures,
        "realised_losses": {name: report_realised_losses(res) for name, res in results.items()},
        "simultaneity": {name: simultaneity_flag(res, spec) for name, res in results.items()},
        "point_error_on_dispatched_hours": {
            curve: mae_on_days(curves[curve], realised, shared, tz)
            for curve, _, _, _ in C13_ARMS
        },
        "nan_policy": {
            "policy": "decline",
            "decision": "a market day whose forecast vector has a hole is skipped and "
                        "counted, never patched (NOTE C4-02 / NOTE C10-01)",
        },
        "soc_note": (
            "each evaluation year is its own rolling run and opens at "
            "initial_soc_fraction, exactly as C11's 2024 run did; SoC carries "
            "across days within a year and not across a year boundary, so the "
            "per-year columns are independent runs rather than one slice of a "
            "five-year trajectory"
        ),
    }
    return summary, daily


#: Where a zone-year's invariant failures are recorded. A failure here is a
#: FLAG for ``PROGRESS.md``, not something to be caught and forgotten: the file
#: is written by the dispatch phase, read and labelled by the analyse phase, and
#: the dispatch phase exits non-zero whenever it is non-empty.
INVARIANT_FLAGS = "c13_invariant_flags.json"


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch every (zone, year), recording rather than swallowing a failure.

    CLAUDE.md's two LP invariants are not the same kind of statement. The
    per-day oracle bound is a **theorem** — a curve cannot settle above the
    same-start oracle on a day — and a violation of it would be a bug in the
    LP. ``value(naive @ realised) <= value(forecast @ realised)`` is an
    **empirical claim about an average**, which CLAUDE.md already qualifies
    ("on average, not per-day"), and a year in which it fails for a zone is a
    fact about that regime-year rather than a fault in the code.

    So the run does not stop at the first failure and does not quietly pass
    either: every zone-year is dispatched and written, each failure is recorded
    with its numbers in :data:`INVARIANT_FLAGS`, the phase exits **non-zero**
    when any were found, and the analyse phase labels those zone-years wherever
    their capture ratio appears. Nothing is relaxed in the assertion itself.
    """
    zones = selected_zones(args.zones)
    years = sorted(set(args.years))
    for year in years:
        assert_not_sealed(year, "C13 dispatch phase")
    cfg = load_battery_config()
    spec = BatterySpec.from_config(cfg)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    flagged: list[dict[str, Any]] = []
    for zone_key in zones:
        for year in years:
            summary, daily = dispatch_zone_year(zone_key, year, spec, cfg)
            daily.to_csv(dispatch_daily_path(zone_key, year), index=False,
                         float_format="%.10g")
            with dispatch_summary_path(zone_key, year).open("w", encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2, default=str)
                fh.write("\n")
            n += 1
            for failure in summary["invariant_failures"]:
                curve, _, check = failure.partition(".")
                flagged.append(
                    {
                        "zone": zone_key,
                        "year": year,
                        "curve": curve,
                        "check": check,
                        "detail": summary["invariants"][curve][check],
                        "oracle_eur_per_mw_year": summary["pooled"][ORACLE_CURVE][
                            "common_hours"]["cash_eur_per_mw_year"],
                        "curve_eur_per_mw_year": summary["pooled"][curve][
                            "common_hours"]["cash_eur_per_mw_year"],
                        "capture_rolled_oracle_cash": summary["pooled"][curve][
                            "common_hours"]["capture_rolled_oracle_cash"],
                        "realised_spread_mean_eur_per_mwh": summary["pooled"][curve][
                            "common_hours"]["realised_spread_mean_eur_per_mwh"],
                    }
                )
    existing: list[dict[str, Any]] = []
    flags_path = RESULTS_DIR / INVARIANT_FLAGS
    if flags_path.exists():
        with flags_path.open(encoding="utf-8") as fh:
            existing = json.load(fh).get("flags", [])
    keep = [
        f for f in existing
        if not (f["zone"] in set(zones) and int(f["year"]) in set(years))
    ]
    payload = {
        "cycle": "C13",
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "note": (
            "CLAUDE.md's pooled naive-dominance invariant, per zone-year. The "
            "per-day same-start oracle bound is a theorem and is asserted "
            "separately; it held everywhere. A flag here is a statement about a "
            "regime-year, is labelled wherever its capture ratio is reported, "
            "and belongs in PROGRESS.md as a FLAG."
        ),
        "flags": keep + flagged,
    }
    with flags_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.write("\n")
    print(f"\ndispatch phase done: {n} (zone, year) run(s); "
          f"{len(flagged)} invariant flag(s) this run, "
          f"{len(payload['flags'])} recorded in total")
    for flag in flagged:
        print(f"  FLAG {flag['zone']} {flag['year']} {flag['curve']}.{flag['check']}: "
              f"margin {flag['detail'].get('margin_eur')} EUR, oracle "
              f"{flag['oracle_eur_per_mw_year']:.0f} EUR/MW/yr, capture "
              f"{flag['capture_rolled_oracle_cash']:.4f}")
    return 1 if flagged else 0


# ---------------------------------------------------------------------------
# Phase 3 — analyse: the per-year tables and the regime split
# ---------------------------------------------------------------------------

#: C12's per-day artefact, the source of the 2024 column. Read rather than
#: recomputed: C12's reproduction check already bound those rows to C11's
#: published numbers, so reusing them is what makes the 2024 column of every
#: per-year table the number already in ``results.csv`` instead of a near
#: neighbour of it.
C12_DAILY = "c12_daily_metrics_2024.csv.gz"

#: The block lengths C12 reported its ladder at. A wider block does not mean a
#: wider interval at n = 365 (see C12's warning); the conservative reading is
#: the rung least favourable to the claim being made.
BLOCK_LADDER: tuple[int, ...] = (1, 7, 14)

#: The headline rung — PLAN.md's literal "daily blocks".
HEADLINE_BLOCK = 1

#: Replicates and seed. The seed is C12's, deliberately: the 2024 columns are
#: then drawn exactly as C12 drew them.
N_REPLICATES = 10_000
SEED = 20261009

#: The forecast error measured **in units of the headroom it has to find**:
#: pooled MAE over the mean realised daily spread. Neither half of it predicts
#: the capture ratio on its own — across the 45 (zone, year) cells the MAE's
#: rank correlation with capture is ~0 and the spread's is weak — and the ratio
#: predicts it strongly. It is a ratio of two day-additive aggregates, so it
#: bootstraps like every other metric here rather than needing a new method.
ERROR_OVER_HEADROOM = "error_over_headroom"

#: The metrics given an interval per (zone, year, curve).
INTERVAL_METRICS: tuple[str, ...] = (
    ERROR_OVER_HEADROOM,
    "capture_rolled_oracle_cash",
    "dispatch_cash_eur_per_mw_year",
    "eur_per_mw_year_lost_vs_oracle",
    "mae_on_dispatched_hours",
    "daily_spread_bias_eur_per_mwh",
    "daily_spread_mae_eur_per_mwh",
    "within_day_spearman_mean",
    "realised_spread_mean_eur_per_mwh",
)


def load_daily_by_year(zones: Sequence[str], years: Sequence[int]) -> pd.DataFrame:
    """One per-day frame across every evaluated year, in C12's column shape.

    The sealed-year check runs **first**, before any path is built, so a sealed
    year cannot reach a file-not-found message and be mistaken for a missing
    artefact; it is then re-asserted on the assembled frame's own day labels.
    """
    assert_not_sealed(set(int(y) for y in years), "assemble C13's per-year frame")
    blocks: list[pd.DataFrame] = []
    if VALIDATION_YEAR in years:
        source = RESULTS_DIR / C12_DAILY
        if not source.exists():
            raise RegimeError(
                f"{source.name} is missing — C13's 2024 column is C12's committed "
                f"per-day artefact, not a re-dispatch"
            )
        frame = pd.read_csv(source, dtype={"market_day": str})
        frame = frame[frame["curve"].isin([ORACLE_CURVE, COMPARABLE_CURVE, NAIVE_CURVE])]
        frame = frame[frame["zone"].isin(list(zones))].copy()
        frame["year"] = VALIDATION_YEAR
        # C12's `in_common_day_set` is C11's nine-curve (Tier A) / three-curve
        # (Tier B) intersection. C13's basis is the intersection of *these three*
        # curves in every zone and every year, so the flag is recomputed below
        # and this column is dropped rather than reused at a different meaning.
        blocks.append(frame[[c for c in DAILY_COLUMNS if c in frame.columns]])
    for zone in zones:
        for year in years:
            if year == VALIDATION_YEAR:
                continue
            path = dispatch_daily_path(zone, year)
            if not path.exists():
                raise RegimeError(
                    f"{path.name} is missing — run the dispatch phase for {zone} {year}"
                )
            blocks.append(pd.read_csv(path, dtype={"market_day": str}))
    daily = pd.concat(blocks, ignore_index=True)
    seen = {int(d[:4]) for d in daily["market_day"]}
    assert_not_sealed(seen, "assemble C13's per-year per-day frame")
    for year in sorted(seen):
        if year not in set(years):
            raise RegimeError(
                f"the assembled frame carries market days in {year}, which is not an "
                f"evaluation year of this run"
            )
    return daily


def curve_days_by_year(
    daily: pd.DataFrame,
) -> dict[tuple[str, int], dict[str, CurveDays]]:
    """``(zone, year) -> curve -> CurveDays``, with the C13 basis flag recomputed."""
    out: dict[tuple[str, int], dict[str, CurveDays]] = {}
    for (zone, year), group in daily.groupby(["zone", "year"], sort=True):
        curves: dict[str, CurveDays] = {}
        day_sets: list[set[str]] = []
        for curve, block in group.groupby("curve", sort=True):
            indexed = block.set_index("market_day").sort_index()
            if indexed.index.duplicated().any():
                raise RegimeError(f"{zone} {year}/{curve}: duplicated market_day rows")
            day_sets.append(set(indexed.index))
            frame = indexed[[c for c in indexed.columns
                             if c not in ("zone", "curve", "year", "tier", "regime",
                                          "model", "exog_variant", "vintage",
                                          "train_from", "in_common_day_set")]].copy()
            curves[curve] = CurveDays(
                zone=str(zone),
                curve=str(curve),
                tier=str(indexed["tier"].iloc[0]),
                regime=str(indexed["regime"].iloc[0]),
                model=str(indexed["model"].iloc[0]),
                exog_variant="" if pd.isna(indexed["exog_variant"].iloc[0])
                else str(indexed["exog_variant"].iloc[0]),
                vintage=str(indexed["vintage"].iloc[0]),
                train_from="" if pd.isna(indexed["train_from"].iloc[0])
                else str(indexed["train_from"].iloc[0]),
                model_fingerprint="",
                frame=frame,
                has_forecast_error=str(curve) != ORACLE_CURVE,
            )
        missing = {ORACLE_CURVE, COMPARABLE_CURVE, NAIVE_CURVE} - set(curves)
        if missing:
            raise RegimeError(f"{zone} {year}: missing curve(s) {sorted(missing)}")
        out[(str(zone), int(year))] = curves
    return out


def comparable_basis(curves: dict[str, CurveDays]) -> tuple[str, ...]:
    """The days all three curves dispatched, in order. One basis per zone-year."""
    shared = set(curves[ORACLE_CURVE].days)
    for curve in (COMPARABLE_CURVE, NAIVE_CURVE):
        shared &= set(curves[curve].days)
    if not shared:
        raise RegimeError("the three curves of this zone-year share no dispatched day")
    return tuple(sorted(shared))


def year_basis(
    by_year: dict[tuple[str, int], dict[str, CurveDays]], year: int, zones: Sequence[str]
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """The cross-zone basis for one year: the days every zone could dispatch.

    The cross-zone band is a **paired** statistic — one draw of days applied to
    all nine zones — so it needs one day list the zones share. C12 verified the
    nine zones' 2024 day sets were identical; earlier years need not be, so the
    intersection is taken and what each zone loses to it is reported rather than
    assumed away.
    """
    per_zone = {zone: set(comparable_basis(by_year[(zone, year)])) for zone in zones}
    shared = set.intersection(*per_zone.values())
    if not shared:
        raise RegimeError(f"{year}: the nine zones share no dispatched market day")
    report = {
        "year": year,
        "n_days_shared": len(shared),
        "identical_across_zones": all(days == shared for days in per_zone.values()),
        "per_zone": {
            zone: {
                "n_days": len(days),
                "n_days_not_in_shared": len(days - shared),
                "days_not_in_shared": sorted(days - shared)[:10],
            }
            for zone, days in sorted(per_zone.items())
        },
    }
    return tuple(sorted(shared)), report


def point_table(
    by_year: dict[tuple[str, int], dict[str, CurveDays]], power_mw: float
) -> pd.DataFrame:
    """One row per (zone, year, curve, scope): every point metric C13 reports."""
    rows: list[dict[str, Any]] = []
    for (zone, year), curves in sorted(by_year.items()):
        basis = comparable_basis(curves)
        for scope, days_source in (("common_hours", basis), ("own_coverage", None)):
            for name, series in sorted(curves.items()):
                days = list(series.days) if days_source is None else list(basis)
                metrics = point_metrics(series, days, power_mw)
                # The rMAE needs the floor on the *same* days. At the comparable
                # basis the naive floor has every one of them by construction; at
                # own_coverage a curve can hold a day the floor declined, so the
                # ratio is taken over the intersection and the count it was taken
                # over is reported beside it rather than left to be assumed.
                rmae_days = [d for d in days if d in set(curves[NAIVE_CURVE].days)]
                metrics.update(
                    {
                        "year": year,
                        "scope": scope,
                        "tier": series.tier,
                        "regime": series.regime,
                        "model": series.model,
                        "exog_variant": series.exog_variant,
                        "vintage": series.vintage,
                        "train_from": series.train_from,
                        "rmae_vs_naive_on_dispatched_hours": (
                            rmae_point(series, curves[NAIVE_CURVE], rmae_days)
                            if name != NAIVE_CURVE else None
                        ),
                        "n_days_rmae": len(rmae_days) if name != NAIVE_CURVE else None,
                        ERROR_OVER_HEADROOM: (
                            metrics["mae_on_dispatched_hours"]
                            / metrics["realised_spread_mean_eur_per_mwh"]
                            if series.has_forecast_error
                            and metrics.get("realised_spread_mean_eur_per_mwh")
                            else None
                        ),
                    }
                )
                rows.append(metrics)
    frame = pd.DataFrame(rows)
    front = ["zone", "year", "curve", "scope", "tier", "regime", "n_days"]
    return frame[front + [c for c in frame.columns if c not in front]]


@dataclass
class YearReplicates:
    """One year's replicate arrays, drawn on one cross-zone basis."""

    year: int
    basis: Basis
    days: tuple[str, ...]
    per_zone_days: dict[str, tuple[str, ...]]
    curve_days_used: dict[tuple[str, str], tuple[str, ...]]
    replicates: dict[int, dict[tuple[str, str], dict[str, np.ndarray]]]
    points: dict[tuple[str, str], dict[str, Any]]


def year_replicates(
    by_year: dict[tuple[str, int], dict[str, CurveDays]],
    year: int,
    zones: Sequence[str],
    power_mw: float,
) -> tuple[YearReplicates, dict[str, Any]]:
    """Draw one year's paired replicates for every (zone, curve) and block length."""
    days, report = year_basis(by_year, year, zones)
    basis = Basis(name=f"cross_zone_{year}", days=days, n_replicates=N_REPLICATES, seed=SEED)
    points: dict[tuple[str, str], dict[str, Any]] = {}
    used: dict[tuple[str, str], tuple[str, ...]] = {}
    replicates: dict[int, dict[tuple[str, str], dict[str, np.ndarray]]] = {}
    for zone in zones:
        curves = by_year[(zone, year)]
        for name, series in curves.items():
            own = [d for d in days if d in set(series.days)]
            used[(zone, name)] = tuple(own)
            measured = point_metrics(series, own, power_mw)
            points[(zone, name)] = {
                **measured,
                "rmae_vs_naive_on_dispatched_hours": (
                    rmae_point(series, curves[NAIVE_CURVE], own)
                    if name != NAIVE_CURVE else None
                ),
                ERROR_OVER_HEADROOM: (
                    measured["mae_on_dispatched_hours"]
                    / measured["realised_spread_mean_eur_per_mwh"]
                    if name != ORACLE_CURVE
                    and measured.get("realised_spread_mean_eur_per_mwh")
                    else None
                ),
            }
    for block in BLOCK_LADDER:
        replicates[block] = {}
        for zone in zones:
            curves = by_year[(zone, year)]
            for name, series in curves.items():
                own = [d for d in days if d in set(series.days)]
                counts = basis.restricted(own, block)
                annualisation = points[(zone, name)]["annualisation"]
                drawn = curve_replicates(series, own, counts, annualisation)
                if name != NAIVE_CURVE and series.has_forecast_error:
                    naive_days = [d for d in own if d in set(curves[NAIVE_CURVE].days)]
                    if naive_days == own:
                        naive_counts = counts
                    else:
                        naive_counts = basis.restricted(naive_days, block)
                    naive_mae = curve_replicates(
                        curves[NAIVE_CURVE], naive_days, naive_counts,
                        points[(zone, NAIVE_CURVE)]["annualisation"],
                    )["mae_on_dispatched_hours"]
                    drawn["rmae_vs_naive_on_dispatched_hours"] = (
                        drawn["mae_on_dispatched_hours"] / naive_mae
                    )
                if name != ORACLE_CURVE and series.has_forecast_error:
                    drawn[ERROR_OVER_HEADROOM] = (
                        drawn["mae_on_dispatched_hours"]
                        / drawn["realised_spread_mean_eur_per_mwh"]
                    )
                replicates[block][(zone, name)] = drawn
    return (
        YearReplicates(
            year=year,
            basis=basis,
            days=days,
            per_zone_days={
                zone: tuple(
                    d for d in days
                    if d in set(by_year[(zone, year)][COMPARABLE_CURVE].days)
                )
                for zone in zones
            },
            curve_days_used=used,
            replicates=replicates,
            points=points,
        ),
        report,
    )


def interval_rows(drawn: YearReplicates, zones: Sequence[str]) -> pd.DataFrame:
    """Every (zone, year, curve, metric, block) interval, long format."""
    rows: list[dict[str, Any]] = []
    for block in BLOCK_LADDER:
        for zone in zones:
            for curve in (ORACLE_CURVE, COMPARABLE_CURVE, NAIVE_CURVE):
                point_block = drawn.points[(zone, curve)]
                spec = BlockBootstrapSpec(
                    n_days=len(drawn.curve_days_used[(zone, curve)]),
                    n_replicates=N_REPLICATES,
                    block_days=block,
                    seed=SEED,
                )
                for metric in INTERVAL_METRICS:
                    values = drawn.replicates[block][(zone, curve)].get(metric)
                    point = point_block.get(metric)
                    if values is None or point is None:
                        continue
                    interval = _interval(float(point), values, spec)
                    rows.append(
                        {
                            "zone": zone,
                            "year": drawn.year,
                            "curve": curve,
                            "metric": metric,
                            "block_days": block,
                            **interval.as_dict(),
                        }
                    )
    return pd.DataFrame(rows)


#: A (zone, year) whose **perfect-foresight** battery earns less than this is a
#: regime-year in which there is essentially nothing to trade, and a capture
#: ratio — settled cash over a near-zero denominator — stops being a ratio of
#: anything. Declared as a number rather than discovered per table, and the
#: sensitivity of the choice is reported beside it: in this sample the gap is an
#: order of magnitude wide (769 EUR/MW/yr in NO2 2020 against 8 992 for the next
#: thinnest zone-year), so no value between ~1 000 and ~8 000 changes a single
#: label. The flagged zone-year is still reported everywhere; it is excluded
#: only from the cross-zone *band* statistics, and both versions are given.
THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR = 2000.0

#: Floors the sensitivity block reports the label count at.
THIN_REGIME_SENSITIVITY_FLOORS: tuple[float, ...] = (500.0, 1000.0, 2000.0, 5000.0)


def thin_regime_report(
    drawn: dict[int, YearReplicates], zones: Sequence[str]
) -> dict[str, Any]:
    """Which (zone, year) cells have too little theoretical value to rank.

    The capture ratio is settled cash over the perfect-foresight run's cash. In
    a regime-year where perfect foresight itself earns a few hundred EUR per MW,
    that denominator is noise: NO2 2020's oracle earns **769 EUR/MW/yr** against
    15 994-74 399 in 2024, and the comparable arm settles *negative* there. A
    ratio against such a denominator is reported, never ranked, and never
    averaged into a band.
    """
    cells = []
    for year in sorted(drawn):
        for zone in zones:
            oracle = drawn[year].points[(zone, ORACLE_CURVE)][
                "dispatch_cash_eur_per_mw_year"]
            capture = drawn[year].points[(zone, COMPARABLE_CURVE)][
                "capture_rolled_oracle_cash"]
            cells.append(
                {
                    "zone": zone,
                    "year": year,
                    "oracle_eur_per_mw_year": oracle,
                    "capture_rolled_oracle_cash": capture,
                    "thin_regime": oracle < THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR,
                }
            )
    thin = [c for c in cells if c["thin_regime"]]
    values = sorted(c["oracle_eur_per_mw_year"] for c in cells)
    return {
        "floor_eur_per_mw_year": THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR,
        "n_cells": len(cells),
        "n_thin": len(thin),
        "thin_cells": [f"{c['zone']}/{c['year']}" for c in thin],
        "oracle_eur_per_mw_year_min": values[0] if values else None,
        "oracle_eur_per_mw_year_second_min": values[1] if len(values) > 1 else None,
        "label_count_by_floor": {
            str(floor): sum(1 for c in cells if c["oracle_eur_per_mw_year"] < floor)
            for floor in THIN_REGIME_SENSITIVITY_FLOORS
        },
        "cells": cells,
    }


def cross_zone_by_year(
    drawn: YearReplicates, zones: Sequence[str], exclude: Sequence[str] = ()
) -> dict[str, Any]:
    """C12's cross-zone band test, run on one year's draws.

    Imported rather than re-implemented: the noise-only null band, the CV ratio
    and the rank correlation against capture are C12's code, so a 2022 band test
    is the 2024 band test with different rows.
    """
    kept = [z for z in zones if z not in set(exclude)]
    out: dict[str, Any] = {"year": drawn.year, "zones": kept, "excluded": list(exclude)}
    for block in BLOCK_LADDER:
        capture_point = np.array(
            [drawn.points[(z, COMPARABLE_CURVE)]["capture_rolled_oracle_cash"] for z in kept],
            dtype=float,
        )
        capture = np.column_stack(
            [drawn.replicates[block][(z, COMPARABLE_CURVE)]["capture_rolled_oracle_cash"]
             for z in kept]
        )
        candidates: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for metric, _sign in CANDIDATE_METRICS:
            if any(drawn.points[(z, COMPARABLE_CURVE)].get(metric) is None for z in kept):
                continue
            if any(metric not in drawn.replicates[block][(z, COMPARABLE_CURVE)] for z in kept):
                continue
            candidates[metric] = (
                np.array([drawn.points[(z, COMPARABLE_CURVE)][metric] for z in kept],
                         dtype=float),
                np.column_stack(
                    [drawn.replicates[block][(z, COMPARABLE_CURVE)][metric] for z in kept]
                ),
            )
        spec = BlockBootstrapSpec(
            n_days=len(drawn.days), n_replicates=N_REPLICATES, block_days=block, seed=SEED
        )
        out[f"block_{block}"] = cross_zone_analysis(
            kept, capture_point, capture, candidates, spec
        )
    return out


def unpaired_difference(
    left: np.ndarray, right: np.ndarray, point: float, block: int, n_days: int
) -> dict[str, Any]:
    """Interval for a difference between two *years*, which share no days.

    Within a year the bootstrap is paired — one draw of days applied to every
    zone — and that is what makes a cross-zone difference tight. Two years have
    no days in common, so their difference cannot be paired: the replicates are
    independent draws and their difference is an unpaired bootstrap of the
    year-on-year change. It is labelled as such everywhere it is reported,
    because an unpaired interval is the wider and honest one here.
    """
    spec = BlockBootstrapSpec(
        n_days=n_days, n_replicates=min(len(left), len(right)),
        block_days=min(block, n_days), seed=SEED,
    )
    n = min(len(left), len(right))
    return {
        **_interval(point, left[:n] - right[:n], spec).as_dict(),
        "pairing": "unpaired (two years share no market day)",
        "block_days": block,
    }


def regime_price_table(zones: Sequence[str], years: Sequence[int]) -> pd.DataFrame:
    """Per (zone, year): the price-regime description PLAN.md C13 asks for.

    The negative-hour count is computed over the **market days of the year in
    local labels** — the same day labels every dispatch and metric row in this
    project is keyed on — and the committed manifest's own ``n_negative`` (taken
    over the fetched file's window) is carried beside it as the cross-check,
    together with the resolution the file was served at, which is what the
    2025-10-01 cutover would change.
    """
    assert_not_sealed(set(int(y) for y in years), "describe the price regime of")
    manifest = pd.read_csv(MANIFEST_CSV)
    rows: list[dict[str, Any]] = []
    for zone in zones:
        tz = zone_timezone(zone)
        frame = load_zone_series(zone)
        series = frame[PRICE_COLUMN]
        labels = pd.Series(market_days(pd.DatetimeIndex(series.index), tz), index=series.index)
        day_year = labels.map(lambda d: d.year)
        for year in years:
            keep = day_year == year
            prices = series[keep.to_numpy()]
            if prices.empty:
                raise RegimeError(f"{zone} {year}: no hourly price in the local market year")
            day = labels[keep.to_numpy()]
            daily = pd.DataFrame({"day": day.to_numpy(), "price": prices.to_numpy(dtype=float)})
            spreads = daily.groupby("day")["price"].agg(lambda s: float(s.max() - s.min()))
            manifest_row = manifest[(manifest["zone"] == zone) & (manifest["year"] == year)]
            # The two windows differ by whole hours at the ends — C1's manifest
            # covers [00:00Z on 01-01, the last whole UTC hour of the local
            # year], this cycle covers the local market days of the year, which
            # reaches back one hour into the previous UTC year. Those hours are
            # identified and their negatives counted here, so a count difference
            # against the manifest can be *explained* rather than tolerated.
            extra_negative = missing_negative = 0
            n_extra = n_missing = 0
            boundary: list[dict[str, Any]] = []
            if not manifest_row.empty:
                first = pd.Timestamp(manifest_row["first_ts_utc"].iloc[0])
                last = pd.Timestamp(manifest_row["last_ts_utc"].iloc[0])
                mine = prices.index
                outside = mine[(mine < first) | (mine > last)]
                n_extra = int(len(outside))
                extra_negative = int((prices.loc[outside] < 0).sum())
                boundary = [
                    {"timestamp_utc": ts.isoformat(), "price": float(prices.loc[ts])}
                    for ts in outside
                ]
                inside = series[(series.index >= first) & (series.index <= last)]
                absent = inside.index.difference(mine)
                n_missing = int(len(absent))
                missing_negative = int((inside.loc[absent] < 0).sum())
            rows.append(
                {
                    "zone": zone,
                    "year": year,
                    "n_hours": int(len(prices)),
                    "n_market_days": int(daily["day"].nunique()),
                    "price_mean": float(prices.mean()),
                    "price_median": float(prices.median()),
                    "price_sd": float(prices.std(ddof=1)),
                    "price_min": float(prices.min()),
                    "price_max": float(prices.max()),
                    "n_negative_hours": int((prices < 0).sum()),
                    "share_negative_hours": float((prices < 0).mean()),
                    "n_zero_hours": int((prices == 0).sum()),
                    "n_hours_above_200": int((prices > 200).sum()),
                    "daily_spread_mean": float(spreads.mean()),
                    "daily_spread_median": float(spreads.median()),
                    "daily_spread_p95": float(spreads.quantile(0.95)),
                    "manifest_n_negative_fetch_window": (
                        None if manifest_row.empty
                        else int(manifest_row["n_negative"].iloc[0])
                    ),
                    "manifest_resolution_seconds": (
                        None if manifest_row.empty
                        else int(manifest_row["resolution_seconds"].iloc[0])
                    ),
                    "manifest_price_mean_fetch_window": (
                        None if manifest_row.empty
                        else float(manifest_row["price_mean"].iloc[0])
                    ),
                    "n_boundary_hours_extra_vs_manifest": n_extra,
                    "n_boundary_negative_extra_vs_manifest": extra_negative,
                    "n_boundary_hours_missing_vs_manifest": n_missing,
                    "n_boundary_negative_missing_vs_manifest": missing_negative,
                    "boundary_hours": json.dumps(boundary),
                }
            )
    return pd.DataFrame(rows)


def manifest_cross_check(regime: pd.DataFrame) -> dict[str, Any]:
    """Does the recomputed regime table agree with the committed manifest?

    The negative-hour count PLAN.md C13 asks for is computed here over the
    **local market days** of each year, while C1's manifest counted it over the
    fetched file's own window. The two windows differ by an hour at each end, so
    the counts agreeing exactly is a fact worth checking rather than assuming —
    and the mean price differing in the third decimal is the same fact seen from
    the other side. Reported, not asserted: a genuine window difference is not a
    provenance failure, but a *count* difference would be worth knowing about.
    """
    rows = []
    for _, row in regime.iterrows():
        committed = row.get("manifest_n_negative_fetch_window")
        delta = (
            None if pd.isna(committed)
            else int(row["n_negative_hours"]) - int(committed)
        )
        explained = (
            int(row.get("n_boundary_negative_extra_vs_manifest", 0))
            - int(row.get("n_boundary_negative_missing_vs_manifest", 0))
        )
        rows.append(
            {
                "zone": row["zone"],
                "year": int(row["year"]),
                "n_negative_market_days": int(row["n_negative_hours"]),
                "n_negative_manifest": None if pd.isna(committed) else int(committed),
                "delta": delta,
                "equal": delta == 0,
                "explained_by_boundary_hours": None if delta is None else delta == explained,
                "boundary_negative_explanation": explained,
                "n_boundary_hours": int(row.get("n_boundary_hours_extra_vs_manifest", 0)),
                "boundary_hours": row.get("boundary_hours"),
                "price_mean_delta": (
                    None if pd.isna(row.get("manifest_price_mean_fetch_window"))
                    else float(row["price_mean"])
                    - float(row["manifest_price_mean_fetch_window"])
                ),
            }
        )
    agree = [r for r in rows if r["equal"]]
    unexplained = [r for r in rows if r["explained_by_boundary_hours"] is False]
    deltas = [abs(r["price_mean_delta"]) for r in rows if r["price_mean_delta"] is not None]
    return {
        "n_zone_years": len(rows),
        "n_negative_counts_identical": len(agree),
        "all_negative_counts_identical": len(agree) == len(rows),
        "n_unexplained_differences": len(unexplained),
        "all_differences_explained_by_boundary_hours": not unexplained,
        "unexplained": unexplained,
        "worst_price_mean_delta_eur_per_mwh": max(deltas, default=None),
        "worst_abs_negative_count_delta": max(
            (abs(r["delta"]) for r in rows if r["delta"] is not None), default=None
        ),
        "window_note": (
            "this cycle counts over the local market days of the year; C1's "
            "manifest counted over the fetched file's window, which starts at "
            "00:00Z on 01-01. The local market year reaches one hour further "
            "back, so a difference of one negative hour is expected exactly "
            "when that hour cleared below zero — which is what "
            "`explained_by_boundary_hours` checks, hour by hour and price by "
            "price, rather than tolerating a mismatch"
        ),
        "rows": rows,
    }


def cutover_status(regime: pd.DataFrame) -> dict[str, Any]:
    """PLAN.md's pre/post 2025-10-01 flag, stated rather than compared."""
    cfg = load_data_config()
    cutover = str(cfg["structural_dates"]["sdac_15min_golive"])
    resolutions = sorted({int(v) for v in regime["manifest_resolution_seconds"].dropna()})
    return {
        "sdac_15min_golive": cutover,
        "main_backtest_end": str(cfg["structural_dates"]["main_backtest_end"]),
        "evaluated_years": sorted(int(y) for y in regime["year"].unique()),
        "last_evaluated_market_day": max(
            f"{int(y)}-12-31" for y in regime["year"].unique()
        ),
        "every_evaluated_row_is_pre_cutover": True,
        "resolution_seconds_seen_in_manifest": resolutions,
        "all_hourly": resolutions == [3600],
        "post_cutover_rows": 0,
        "why_no_comparison": (
            "the cutover falls inside the sealed 2025 holdout, and config/data.yaml "
            "stops fetching at 2024, so there is no post-cutover row in this project "
            "to compare against. The flag is therefore a statement about the "
            "evaluated window, not a split: every price hour behind every number in "
            "C13 was served at 60-minute resolution (manifest "
            "resolution_seconds=3600 on all 54 zone-years) and falls before "
            "2025-10-01. data/contracts.py carries the resolution-change detection "
            "that would catch a post-cutover file if a later cycle fetched one; "
            "PLAN.md C15+ keeps native 15-minute analysis as a labelled stretch "
            "goal that is never blended into these results."
        ),
    }


#: What C13's 2024 column must reproduce from the committed store, as
#: ``(metric, atol, rtol)``. The 2024 per-day rows C13 reads *are* C12's
#: committed artefact, so pooling them over each curve's own days has to give
#: back the number C11/C12 published — and if it does not, the per-year table's
#: 2024 column would be a near neighbour of the published one, which is worse
#: than not having it. The two EUR/MW/yr figures carry C12's relative tolerances
#: for C12's stated reason (C11 formed them as ``sum/span``, the bootstrap needs
#: ``mean x annualisation``).
REPRODUCED_2024: tuple[tuple[str, float, float], ...] = (
    ("capture_rolled_oracle_cash", 5e-9, 0.0),
    ("dispatch_cash_eur_per_mw_year", 0.0, 1e-9),
    ("eur_per_mw_year_lost_vs_oracle", 0.0, 1e-8),
    ("realised_spread_mean_eur_per_mwh", 5e-9, 0.0),
    ("daily_spread_bias_eur_per_mwh", 5e-9, 0.0),
    ("daily_spread_mae_eur_per_mwh", 5e-9, 0.0),
    ("within_day_spearman_mean", 5e-9, 0.0),
    ("rmae_vs_naive_on_dispatched_hours", 5e-9, 0.0),
)

#: The *point-error* metrics live in the store at ``common_hours`` only — C11
#: and C12 scored them on the intersection of every curve of the zone, and in
#: Tier A that intersection is over nine curves, which C13's three-curve basis
#: is deliberately not. In **Tier B** the two are the same set by construction
#: (C11's Tier-B inventory is this cycle's three curves and no others), so the
#: six Tier-B zones give a second, independent reproduction of the published
#: 2024 numbers — including the MAE, the RMSE and the bias — and that is where
#: they are checked.
REPRODUCED_2024_TIER_B_COMMON: tuple[tuple[str, float, float], ...] = (
    ("capture_rolled_oracle_cash", 5e-9, 0.0),
    ("mae_on_dispatched_hours", 5e-9, 0.0),
    ("rmse_on_dispatched_hours", 5e-9, 0.0),
    ("bias_on_dispatched_hours", 5e-9, 0.0),
    ("dispatch_cash_eur_per_mw_year", 0.0, 1e-9),
    ("eur_per_mw_year_lost_vs_oracle", 0.0, 1e-8),
    ("within_day_spearman_mean", 5e-9, 0.0),
    ("daily_spread_mae_eur_per_mwh", 5e-9, 0.0),
    ("rmae_vs_naive_on_dispatched_hours", 5e-9, 0.0),
)

#: How a C13 curve name maps onto the store's own key for the 2024 rows.
STORE_KEY: dict[str, tuple[str, str, str]] = {
    ORACLE_CURVE: (ORACLE_MODEL, ORACLE_VARIANT, ""),
    COMPARABLE_CURVE: ("lear", "price_only", FULL_HISTORY_FROM),
    NAIVE_CURVE: ("naive_last_week", "", FULL_HISTORY_FROM),
}


def check_2024_reproduction(
    points: pd.DataFrame,
    store: pd.DataFrame | None = None,
    store_scope: str = "own_coverage",
    c13_scope: str = "own_coverage",
    metrics: tuple[tuple[str, float, float], ...] = REPRODUCED_2024,
    tiers: tuple[str, ...] = ("A", "B"),
) -> dict[str, Any]:
    """C13's 2024 numbers against the rows C11 and C12 committed.

    Run twice by the analyse phase: once at ``own_coverage``, where each curve
    is pooled over its own days in both cycles and every dispatch metric must
    come back, and once over the **Tier-B** zones at ``common_hours``, where
    C11's curve inventory and C13's are the same three curves so the point-error
    metrics are comparable too.
    """
    from backtest.results_store import RESULTS_PATH

    frame = store if store is not None else pd.read_csv(RESULTS_PATH)
    frame = frame[frame["evaluation_years"].astype(str) == str(VALIDATION_YEAR)]
    frame = frame[frame["scope"] == store_scope]
    checks: list[dict[str, Any]] = []
    own = points[(points["year"] == VALIDATION_YEAR) & (points["scope"] == c13_scope)]
    own = own[own["tier"].astype(str).isin(list(tiers))]
    for _, row in own.iterrows():
        key = STORE_KEY.get(str(row["curve"]))
        if key is None:
            continue
        model, variant, train_from = key
        candidates = frame[(frame["zone"] == row["zone"]) & (frame["model"] == model)]
        variants = candidates["exog_variant"].fillna("").astype(str)
        candidates = candidates[variants == variant]
        if train_from:
            candidates = candidates[
                candidates["train_from"].fillna("").astype(str) == train_from
            ]
        for metric, atol, rtol in metrics:
            committed = candidates[candidates["metric"] == metric]
            recomputed = row.get(metric)
            if committed.empty or recomputed is None or pd.isna(recomputed):
                continue
            if len(committed) != 1:
                raise RegimeError(
                    f"{row['zone']}/{row['curve']}/{metric}: the store carries "
                    f"{len(committed)} matching 2024 own_coverage rows, not one"
                )
            value = float(committed["value"].iloc[0])
            delta = float(recomputed) - value
            tol = atol + rtol * abs(value)
            checks.append(
                {
                    "zone": row["zone"],
                    "curve": row["curve"],
                    "metric": metric,
                    "committed": value,
                    "recomputed": float(recomputed),
                    "abs_delta": abs(delta),
                    "tolerance": tol,
                    "holds": abs(delta) <= tol,
                    "source_cycle": str(committed["cycle"].iloc[0]),
                }
            )
    failures = [c for c in checks if not c["holds"]]
    worst = max((c["abs_delta"] for c in checks), default=0.0)
    return {
        "applicable": bool(checks),
        "store_scope": store_scope,
        "c13_scope": c13_scope,
        "tiers": list(tiers),
        "n_checks": len(checks),
        "n_failures": len(failures),
        "worst_abs_delta": worst,
        "holds": not failures,
        "failures": failures[:20],
        "checks": checks,
    }


def crisis_comparison(
    drawn: dict[int, YearReplicates],
    zones: Sequence[str],
    thin: dict[str, Any] | None = None,
    block: int = HEADLINE_BLOCK,
) -> dict[str, Any]:
    """PLAN.md's "2022 reported separately", as numbers rather than a section.

    Two questions, per zone: how much more *theoretical* flexibility value the
    crisis year held (the oracle's EUR/MW/yr), and whether the *share* of it a
    forecast-driven battery captured moved at all. The first is a price-level
    fact and will be enormous; the second is the one the project is about, and
    it is the one a reader would otherwise assume moved with the first.

    The year-on-year interval is **unpaired** — 2022 and 2023 share no market
    day — so it is wider than any within-year contrast in C12 and is labelled
    that way wherever it is reported.
    """
    if CRISIS_YEAR not in drawn:
        return {"applicable": False, "reason": f"{CRISIS_YEAR} was not evaluated"}
    all_others = [y for y in sorted(drawn) if y != CRISIS_YEAR]
    thin_cells = (
        {(c["zone"], int(c["year"])) for c in (thin or {}).get("cells", [])
         if c["thin_regime"]}
    )
    out: dict[str, Any] = {
        "crisis_year": CRISIS_YEAR,
        "comparison_years": all_others,
        "block_days": block,
        "pairing": "unpaired (two years share no market day)",
        "thin_regime_cells_excluded_from_baselines": sorted(
            f"{z}/{y}" for z, y in thin_cells
        ),
        "baseline_note": (
            "a zone's baseline is the mean of its other evaluated years, with "
            "any thin-regime cell dropped: averaging a capture ratio whose "
            "denominator is a few hundred EUR into a baseline would make the "
            "crisis year look good for the wrong reason"
        ),
        "per_zone": {},
    }
    for zone in zones:
        others = [y for y in all_others if (zone, y) not in thin_cells]
        crisis = drawn[CRISIS_YEAR]
        block_rep = crisis.replicates[block]
        capture_crisis = block_rep[(zone, COMPARABLE_CURVE)]["capture_rolled_oracle_cash"]
        point_crisis = crisis.points[(zone, COMPARABLE_CURVE)]["capture_rolled_oracle_cash"]
        rest = [drawn[y].replicates[block][(zone, COMPARABLE_CURVE)][
            "capture_rolled_oracle_cash"] for y in others]
        rest_points = [
            drawn[y].points[(zone, COMPARABLE_CURVE)]["capture_rolled_oracle_cash"]
            for y in others
        ]
        mean_rest = np.mean(np.column_stack(rest), axis=1)
        point_rest = float(np.mean(rest_points))
        oracle_crisis = crisis.points[(zone, ORACLE_CURVE)]["dispatch_cash_eur_per_mw_year"]
        oracle_rest = float(np.mean([
            drawn[y].points[(zone, ORACLE_CURVE)]["dispatch_cash_eur_per_mw_year"]
            for y in others
        ]))
        out["per_zone"][zone] = {
            "baseline_years": others,
            "capture_2022": point_crisis,
            "capture_mean_other_years": point_rest,
            "capture_delta_pp_vs_other_years": unpaired_difference(
                capture_crisis * 100.0, mean_rest * 100.0,
                (point_crisis - point_rest) * 100.0, block, len(crisis.days),
            ),
            "oracle_eur_per_mw_year_2022": oracle_crisis,
            "oracle_eur_per_mw_year_mean_other_years": oracle_rest,
            "oracle_ratio_2022_over_other_years": (
                None if oracle_rest == 0 else oracle_crisis / oracle_rest
            ),
            "model_eur_per_mw_year_2022": crisis.points[(zone, COMPARABLE_CURVE)][
                "dispatch_cash_eur_per_mw_year"],
            "lost_eur_per_mw_year_2022": crisis.points[(zone, COMPARABLE_CURVE)][
                "eur_per_mw_year_lost_vs_oracle"],
            "lost_eur_per_mw_year_mean_other_years": float(np.mean([
                drawn[y].points[(zone, COMPARABLE_CURVE)]["eur_per_mw_year_lost_vs_oracle"]
                for y in others
            ])),
            "within_day_spearman_2022": crisis.points[(zone, COMPARABLE_CURVE)][
                "within_day_spearman_mean"],
            "within_day_spearman_mean_other_years": float(np.mean([
                drawn[y].points[(zone, COMPARABLE_CURVE)]["within_day_spearman_mean"]
                for y in others
            ])),
        }
    return out


def year_stability(
    drawn: dict[int, YearReplicates], zones: Sequence[str], block: int = HEADLINE_BLOCK
) -> dict[str, Any]:
    """Is a zone's capture ratio a property of the zone or of the year?

    The question C13 exists to answer, and the one NOTE C12-01 needs: a capture
    band measured in one year is only a statement about regimes if a zone's own
    capture is reasonably stable across years. Reported as each zone's spread
    across the evaluated years, against the sampling noise of a single year's
    estimate, plus the rank correlation of the per-zone ordering between every
    pair of years — which is the direct test of "does the cross-zone ranking
    replicate".
    """
    years = sorted(drawn)
    out: dict[str, Any] = {"years": years, "block_days": block, "per_zone": {}}
    for zone in zones:
        values = {
            y: drawn[y].points[(zone, COMPARABLE_CURVE)]["capture_rolled_oracle_cash"]
            for y in years
        }
        sds = {
            y: float(np.std(
                drawn[y].replicates[block][(zone, COMPARABLE_CURVE)][
                    "capture_rolled_oracle_cash"], ddof=1))
            for y in years
        }
        band = max(values.values()) - min(values.values())
        out["per_zone"][zone] = {
            "capture_by_year": {str(y): values[y] for y in years},
            "boot_sd_by_year": {str(y): sds[y] for y in years},
            "across_year_band_pp": band * 100.0,
            "mean_single_year_boot_sd_pp": float(np.mean(list(sds.values()))) * 100.0,
            "band_over_mean_sd": (
                None if np.mean(list(sds.values())) == 0
                else band / float(np.mean(list(sds.values())))
            ),
        }
    ranks: dict[str, Any] = {}
    for i, left in enumerate(years):
        for right in years[i + 1:]:
            a = np.array([drawn[left].points[(z, COMPARABLE_CURVE)][
                "capture_rolled_oracle_cash"] for z in zones], dtype=float)
            b = np.array([drawn[right].points[(z, COMPARABLE_CURVE)][
                "capture_rolled_oracle_cash"] for z in zones], dtype=float)
            ranks[f"{left}_vs_{right}"] = {
                "spearman_capture_ranking": float(
                    spearman_rows(a[None, :], b[None, :])[0]
                ),
                "same_worst_zone": bool(
                    zones[int(np.argmin(a))] == zones[int(np.argmin(b))]
                ),
                "worst_zone_left": zones[int(np.argmin(a))],
                "worst_zone_right": zones[int(np.argmin(b))],
            }
    out["cross_year_ranking"] = ranks
    return out


#: The cell-level predictors of the capture ratio this cycle sets against each
#: other. ``error_over_headroom`` is the one C13 adds; the rest are the ones C11
#: and C12 already tried at one year and nine zones.
CELL_PREDICTORS: tuple[str, ...] = (
    ERROR_OVER_HEADROOM,
    "realised_spread_mean_eur_per_mwh",
    "within_day_spearman_mean",
    "mae_on_dispatched_hours",
)


def spread_capture_analysis(
    drawn: dict[int, YearReplicates],
    zones: Sequence[str],
    thin: dict[str, Any],
) -> dict[str, Any]:
    """Is the capture ratio a property of the zone, or of the day's headroom?

    Five years make this answerable for the first time. The battery's frictions
    are fixed in EUR/MWh — a 2 EUR/MWh throughput cost and a 12% round trip — so
    in a thin year a larger share of the prize is eaten before any forecast error
    is paid, and the capture ratio should fall with the realised daily spread
    *within* a zone as well as across zones. If it does, a cross-zone capture
    band measured in one year is partly a band across spread levels rather than
    across price-formation regimes, which is what FINDING C11-A reads it as.

    Three cuts, with what each one can carry:

    * **per year, across zones** — a paired interval, because the nine zones'
      capture and spread replicates are drawn on the same days.
    * **per zone, across years** — point estimate only. Five years is five
      points and they are not independent draws of a regime.
    * **pooled across cells** — point estimate only, and explicitly descriptive:
      the 45 cells share zones, years, a model and a specification.

    The NO2 residual is the question NOTE C12-02 asks, in the one form five
    years can answer: fit capture on log(spread) over the other eight zones'
    non-thin cells and ask how far below that line NO2 sits. A thin-spread
    mechanism predicts NO2 lands *on* the line; an ordering mechanism predicts
    it stays below it.
    """
    thin_cells = {(c["zone"], int(c["year"])) for c in thin["cells"] if c["thin_regime"]}
    cells: list[dict[str, Any]] = []
    for year in sorted(drawn):
        for zone in zones:
            point = drawn[year].points[(zone, COMPARABLE_CURVE)]
            cells.append(
                {
                    "zone": zone,
                    "year": year,
                    "capture": point["capture_rolled_oracle_cash"],
                    "realised_spread": point["realised_spread_mean_eur_per_mwh"],
                    "within_day_spearman": point["within_day_spearman_mean"],
                    "mae": point["mae_on_dispatched_hours"],
                    "error_over_headroom": point[ERROR_OVER_HEADROOM],
                    "oracle_eur_per_mw_year": drawn[year].points[(zone, ORACLE_CURVE)][
                        "dispatch_cash_eur_per_mw_year"],
                    "thin_regime": (zone, year) in thin_cells,
                }
            )
    usable = [c for c in cells if not c["thin_regime"]]

    per_year: dict[str, Any] = {}
    for year in sorted(drawn):
        kept = [z for z in zones if (z, year) not in thin_cells]
        capture_point = np.array(
            [drawn[year].points[(z, COMPARABLE_CURVE)]["capture_rolled_oracle_cash"]
             for z in kept], dtype=float)
        predictors: dict[str, Any] = {}
        for metric in CELL_PREDICTORS:
            point = np.array(
                [drawn[year].points[(z, COMPARABLE_CURVE)][metric] for z in kept],
                dtype=float,
            )
            block_report: dict[str, Any] = {}
            for block in BLOCK_LADDER:
                capture = np.column_stack(
                    [drawn[year].replicates[block][(z, COMPARABLE_CURVE)][
                        "capture_rolled_oracle_cash"] for z in kept])
                values = np.column_stack(
                    [drawn[year].replicates[block][(z, COMPARABLE_CURVE)][metric]
                     for z in kept])
                rho = spearman_rows(values, capture)
                point_rho = float(
                    spearman_rows(point[None, :], capture_point[None, :])[0]
                )
                spec = BlockBootstrapSpec(
                    n_days=len(drawn[year].days), n_replicates=N_REPLICATES,
                    block_days=block, seed=SEED,
                )
                block_report[f"block_{block}"] = _interval(point_rho, rho, spec).as_dict()
            predictors[metric] = block_report
        per_year[str(year)] = {
            "zones": kept,
            "n_zones": len(kept),
            "spearman_vs_capture": predictors,
            # Kept under its C13-draft name so a reader following the spread
            # story finds it where this cycle first looked for it.
            "spearman_spread_vs_capture": predictors["realised_spread_mean_eur_per_mwh"],
        }

    per_zone: dict[str, Any] = {}
    for zone in zones:
        rows = [c for c in usable if c["zone"] == zone]
        if len(rows) < 3:
            per_zone[zone] = {"n_years": len(rows), "spearman": None,
                              "reason": "fewer than three usable years"}
            continue
        capture = np.array([r["capture"] for r in rows], dtype=float)
        spread = np.array([r["realised_spread"] for r in rows], dtype=float)
        per_zone[zone] = {
            "n_years": len(rows),
            "years": [r["year"] for r in rows],
            "spearman": float(spearman_rows(spread[None, :], capture[None, :])[0]),
            "capture_min": float(capture.min()),
            "capture_max": float(capture.max()),
            "capture_band_pp": float(capture.max() - capture.min()) * 100.0,
            "spread_min": float(spread.min()),
            "spread_max": float(spread.max()),
        }

    pooled_capture_values = np.array([c["capture"] for c in usable], dtype=float)
    pooled_spread = np.array([c["realised_spread"] for c in usable], dtype=float)
    pooled_rho = float(
        spearman_rows(pooled_spread[None, :], pooled_capture_values[None, :])[0]
    )
    pooled_by_predictor = {}
    for key in ("realised_spread", "error_over_headroom", "within_day_spearman",
                "mae", "oracle_eur_per_mw_year"):
        values = np.array([c[key] for c in usable], dtype=float)
        pooled_by_predictor[key] = float(
            spearman_rows(values[None, :], pooled_capture_values[None, :])[0]
        )
    ex_outlier_cells = [c for c in usable if c["zone"] != OUTLIER_ZONE]
    ex_capture = np.array([c["capture"] for c in ex_outlier_cells], dtype=float)
    pooled_by_predictor_ex_outlier = {}
    for key in ("realised_spread", "error_over_headroom", "within_day_spearman",
                "mae", "oracle_eur_per_mw_year"):
        values = np.array([c[key] for c in ex_outlier_cells], dtype=float)
        pooled_by_predictor_ex_outlier[key] = float(
            spearman_rows(values[None, :], ex_capture[None, :])[0]
        )
    year_means = {
        str(year): {
            "capture": float(np.mean([c["capture"] for c in usable if c["year"] == year])),
            "error_over_headroom": float(np.mean(
                [c["error_over_headroom"] for c in usable if c["year"] == year])),
            "realised_spread": float(np.mean(
                [c["realised_spread"] for c in usable if c["year"] == year])),
            "within_day_spearman": float(np.mean(
                [c["within_day_spearman"] for c in usable if c["year"] == year])),
            "n_zones": sum(1 for c in usable if c["year"] == year),
        }
        for year in sorted(drawn)
    }

    # The reference line: the other eight zones' non-thin cells only, so NO2 is
    # measured against a relationship it did not help fit.
    reference = [c for c in usable if c["zone"] != OUTLIER_ZONE]
    design = np.column_stack(
        [np.ones(len(reference)), np.log(np.array([c["realised_spread"] for c in reference]))]
    )
    target = np.array([c["capture"] for c in reference], dtype=float)
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    fitted = design @ coefficients
    residual_sd = float(np.std(target - fitted, ddof=2))
    outlier_rows = [c for c in cells if c["zone"] == OUTLIER_ZONE]
    outlier = {
        str(c["year"]): {
            "capture": c["capture"],
            "realised_spread": c["realised_spread"],
            "predicted_capture_from_eight_zone_line": float(
                coefficients[0] + coefficients[1] * math.log(c["realised_spread"])
            ),
            "residual_pp": float(
                c["capture"]
                - (coefficients[0] + coefficients[1] * math.log(c["realised_spread"]))
            ) * 100.0,
            "residual_in_sd_of_the_line": float(
                (c["capture"]
                 - (coefficients[0] + coefficients[1] * math.log(c["realised_spread"])))
                / residual_sd
            ) if residual_sd > 0 else None,
            "within_day_spearman": c["within_day_spearman"],
            "thin_regime": c["thin_regime"],
        }
        for c in outlier_rows
    }
    return {
        "n_cells": len(cells),
        "n_cells_usable": len(usable),
        "cells": cells,
        "per_year_across_zones": per_year,
        "per_zone_across_years": per_zone,
        "pooled_across_cells": {
            "n": len(usable),
            "spearman_spread_vs_capture": pooled_rho,
            "spearman_vs_capture_by_predictor": pooled_by_predictor,
            "n_ex_outlier": len(ex_outlier_cells),
            "spearman_vs_capture_by_predictor_ex_outlier": pooled_by_predictor_ex_outlier,
            "label": "descriptive only — the cells share zones, years, one model "
                     "and one specification, so this is not an interval-bearing "
                     "statistic",
        },
        "year_means_over_usable_cells": year_means,
        "eight_zone_log_spread_line": {
            "intercept": float(coefficients[0]),
            "slope_per_log_eur_per_mwh": float(coefficients[1]),
            "n": len(reference),
            "residual_sd_pp": residual_sd * 100.0,
            "label": "descriptive least squares over the eight non-outlier zones' "
                     "usable cells; no interval is claimed for the coefficients",
        },
        f"{OUTLIER_ZONE}_against_that_line": outlier,
    }


def invariant_flags() -> dict[str, Any]:
    """The dispatch phase's recorded invariant failures, or an empty block."""
    path = RESULTS_DIR / INVARIANT_FLAGS
    if not path.exists():
        return {"n_flags": 0, "flags": [], "source": None}
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    flags = payload.get("flags", [])
    return {
        "n_flags": len(flags),
        "flags": flags,
        "source": path.name,
        "note": payload.get("note", ""),
    }


def analyse(args: argparse.Namespace) -> int:
    zones = list(selected_zones(args.zones))
    years = sorted(set(args.years) | {VALIDATION_YEAR})
    for year in years:
        assert_not_sealed(year, "C13 analyse phase")
    cfg = load_battery_config()
    spec = BatterySpec.from_config(cfg)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    daily = load_daily_by_year(zones, years)
    daily.to_csv(RESULTS_DIR / "c13_daily_by_year.csv.gz", index=False, float_format="%.10g")
    print(f"per-day frame: {len(daily):,} rows, {len(years)} years, {len(zones)} zones")

    by_year = curve_days_by_year(daily)
    points = point_table(by_year, spec.power_mw)
    points.to_csv(RESULTS_DIR / "c13_per_year_metrics.csv", index=False)

    reproduction = check_2024_reproduction(points)
    tier_b = check_2024_reproduction(
        points,
        store_scope="common_hours",
        c13_scope="common_hours",
        metrics=REPRODUCED_2024_TIER_B_COMMON,
        tiers=("B",),
    )
    for label, block in (("own_coverage", reproduction), ("Tier-B common_hours", tier_b)):
        print(f"2024 reproduction ({label}): {block['n_checks']} check(s), worst "
              f"absolute delta {block['worst_abs_delta']:.3g} "
              f"[{'OK' if block['holds'] else 'FAIL'}]")
        if not block["holds"]:
            raise RegimeError(
                f"C13's 2024 column does not reproduce the committed rows at "
                f"{label}: {block['failures'][:3]}"
            )

    drawn: dict[int, YearReplicates] = {}
    bases: dict[str, Any] = {}
    frames: list[pd.DataFrame] = []
    for year in years:
        drawn[year], bases[str(year)] = year_replicates(by_year, year, zones, spec.power_mw)
        frames.append(interval_rows(drawn[year], zones))

    thin = thin_regime_report(drawn, zones)
    thin_by_year: dict[int, list[str]] = {}
    for cell in thin["cells"]:
        if cell["thin_regime"]:
            thin_by_year.setdefault(int(cell["year"]), []).append(str(cell["zone"]))
    print(f"thin-regime cells (oracle < {thin['floor_eur_per_mw_year']:.0f} EUR/MW/yr): "
          f"{thin['n_thin']} of {thin['n_cells']} — {thin['thin_cells']}")

    cross: dict[str, Any] = {}
    for year in years:
        thin_zones = thin_by_year.get(year, [])
        cross[str(year)] = {
            "nine_zones": cross_zone_by_year(drawn[year], zones),
            "ex_outlier": cross_zone_by_year(drawn[year], zones, exclude=[OUTLIER_ZONE]),
            "thin_regime_zones_excluded": thin_zones,
        }
        if thin_zones:
            # A band computed over a cell whose denominator is noise is not a
            # band about regimes. Both versions are reported; which one a claim
            # may lean on is stated in docs/regime_analysis.md.
            cross[str(year)]["ex_thin_regime"] = cross_zone_by_year(
                drawn[year], zones, exclude=thin_zones
            )
            cross[str(year)]["ex_thin_regime_and_outlier"] = cross_zone_by_year(
                drawn[year], zones, exclude=sorted(set(thin_zones) | {OUTLIER_ZONE})
            )
    for year in years:
        band = cross[str(year)]["nine_zones"][f"block_{HEADLINE_BLOCK}"]
        ex = cross[str(year)]["ex_outlier"][f"block_{HEADLINE_BLOCK}"]
        print(f"  {year}: capture band {band['capture_band_pp']['point']:.2f}pp "
              f"(noise-only p {band['capture_band_vs_noise']['p_value']:.4g}); "
              f"ex-{OUTLIER_ZONE} {ex['capture_band_pp']['point']:.2f}pp "
              f"(p {ex['capture_band_vs_noise']['p_value']:.4g})")
    intervals = pd.concat(frames, ignore_index=True)
    intervals.to_csv(RESULTS_DIR / "c13_year_intervals.csv", index=False)

    crisis = crisis_comparison(drawn, zones, thin)
    stability = year_stability(drawn, zones)
    spread_capture = spread_capture_analysis(drawn, zones, thin)
    pooled = spread_capture["pooled_across_cells"]
    print(f"capture vs cell predictors over {pooled['n']} usable cells: "
          + ", ".join(
              f"{k} {v:+.3f}"
              for k, v in pooled["spearman_vs_capture_by_predictor"].items()
          ))
    regime = regime_price_table(zones, years)
    regime.to_csv(RESULTS_DIR / "c13_regime_table.csv", index=False)
    manifest_check = manifest_cross_check(regime)
    print(f"manifest cross-check: negative-hour counts identical on "
          f"{manifest_check['n_negative_counts_identical']}/"
          f"{manifest_check['n_zone_years']} zone-years; "
          f"{manifest_check['n_unexplained_differences']} unexplained")
    if not manifest_check["all_differences_explained_by_boundary_hours"]:
        raise RegimeError(
            "a negative-hour count differs from the committed manifest by more "
            f"than the boundary hours explain: {manifest_check['unexplained'][:3]}"
        )
    cutover = cutover_status(regime)

    summary = {
        "cycle": "C13",
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "libraries": library_versions(),
        "battery_spec": spec.as_dict(),
        "zones": zones,
        "years": years,
        "new_years_computed_this_cycle": [y for y in years if y != VALIDATION_YEAR],
        "bootstrap": {
            "n_replicates": N_REPLICATES,
            "seed": SEED,
            "block_ladder_days": list(BLOCK_LADDER),
            "headline_block_days": HEADLINE_BLOCK,
            "pairing": "within a year, paired across zones and curves; between "
                       "years, unpaired (no shared days)",
        },
        "cross_zone_bases": bases,
        "reproduction_2024": reproduction,
        "reproduction_2024_tier_b_common_hours": tier_b,
        "cross_zone_by_year": cross,
        "thin_regime": thin,
        "invariant_flags": invariant_flags(),
        "manifest_cross_check": manifest_check,
        "crisis_2022": crisis,
        "year_stability": stability,
        "spread_vs_capture": spread_capture,
        "cutover_status": cutover,
        "note": (
            "PLAN.md C13. The per-year columns for 2020-2023 are this cycle's own "
            "walk-forward runs of the nine-zone comparable arm; the 2024 column is "
            "C12's committed per-day artefact, re-pooled and checked against the "
            "committed store rows. 2020-2023 are PLAN.md training years: the "
            "predictions are out-of-sample but the model configuration was chosen "
            "on 2024, so these years weaken 'one year decides too little' without "
            "being the configuration holdout 2025 will be."
        ),
    }
    with (RESULTS_DIR / "c13_regime_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    with (RESULTS_DIR / "c13_cutover_status.json").open("w", encoding="utf-8") as fh:
        json.dump(cutover, fh, indent=2, default=str)
        fh.write("\n")
    print("analyse phase done")
    return 0


# ---------------------------------------------------------------------------
# Phase 4 — ingest: the per-year rows, append-only
# ---------------------------------------------------------------------------

#: Point metrics written per (zone, year, curve, scope). Long format, so a new
#: evaluation year is new *rows*, never a new column and never a schema change
#: (``docs/results_store.md``).
STORE_METRICS: tuple[str, ...] = (
    "capture_rolled_oracle_cash",
    "dispatch_cash_eur",
    "dispatch_cash_eur_per_mw_year",
    "eur_per_mw_year_lost_vs_oracle",
    "realised_spread_mean_eur_per_mwh",
    "mae_on_dispatched_hours",
    "rmse_on_dispatched_hours",
    "bias_on_dispatched_hours",
    "rmae_vs_naive_on_dispatched_hours",
    "daily_spread_mae_eur_per_mwh",
    "daily_spread_bias_eur_per_mwh",
    "within_day_spearman_mean",
    "within_day_spearman_median",
    "within_day_spearman_p05",
    ERROR_OVER_HEADROOM,
)


def store_rows_for_year(points: pd.DataFrame, intervals: pd.DataFrame) -> list[ResultRow]:
    """Every C13 point metric and its headline-block interval bounds, as rows.

    Only the years this cycle computed are written. The 2024 rows already exist
    (C11 and C12 wrote them) and re-writing them under a new run id would put
    two rows with different provenance behind one number, which is exactly what
    the append-only store is for avoiding.
    """
    rows: list[ResultRow] = []
    bounds = intervals[intervals["block_days"] == HEADLINE_BLOCK]
    for _, row in points.iterrows():
        year = int(row["year"])
        if year == VALIDATION_YEAR:
            continue
        curve = str(row["curve"])
        key = STORE_KEY.get(curve)
        if key is None:
            raise RegimeError(f"no store key for curve {curve!r}")
        model, variant, train_from = key
        common = dict(
            zone=str(row["zone"]),
            tier=str(row["tier"]),
            regime=str(row["regime"]),
            model=model,
            exog_variant=variant,
            vintage="honest",
            train_from=train_from,
            evaluation_years=str(year),
            scope=str(row["scope"]),
            n=str(int(row["n_days"])),
            n_scored=("" if pd.isna(row.get("n_hours")) else str(int(row["n_hours"]))),
            source_cycle="C13",
            source_artefact=(
                C12_DAILY if year == VALIDATION_YEAR
                else dispatch_daily_path(str(row["zone"]), year).name
            ),
        )
        for metric in STORE_METRICS:
            value = row.get(metric)
            if value is None or pd.isna(value):
                continue
            rows.append(ResultRow(metric=metric, value=float(value), **common))
        if str(row["scope"]) != "common_hours":
            continue
        selected = bounds[
            (bounds["zone"] == row["zone"])
            & (bounds["year"] == year)
            & (bounds["curve"] == curve)
        ]
        for _, bound in selected.iterrows():
            metric = str(bound["metric"])
            for suffix, column in (
                ("_ci_low", "ci_low"), ("_ci_high", "ci_high"), ("_boot_sd", "boot_sd")
            ):
                rows.append(
                    ResultRow(
                        metric=f"{metric}{suffix}",
                        value=float(bound[column]),
                        **common,
                    )
                )
    return rows


def ingest(args: argparse.Namespace) -> int:
    points_path = RESULTS_DIR / "c13_per_year_metrics.csv"
    intervals_path = RESULTS_DIR / "c13_year_intervals.csv"
    for path in (points_path, intervals_path):
        if not path.exists():
            raise RegimeError(f"{path.name} is missing — run the analyse phase first")
    points = pd.read_csv(points_path)
    intervals = pd.read_csv(intervals_path)
    rows = store_rows_for_year(points, intervals)
    print(f"{len(rows):,} row(s) to append "
          f"({points['year'].nunique() - 1} new evaluation year(s))")
    if args.no_append:
        print("--no-append: nothing written")
        return 0
    report = append_rows(
        rows,
        cycle="C13",
        git_sha=git_sha(),
        config_hash=config_hash(),
        path=None if args.results_path is None else __import__("pathlib").Path(args.results_path),
        argv=sys.argv,
        note=(
            "C13 regime analysis: the nine-zone comparable arm (C4's LEAR on "
            "price/calendar features, expanding window) walked forward across "
            "2020-2023 one year at a time, dispatched through C5/C6's rolling LP, "
            "and scored with C11's pooled_capture and C12's metric layer. "
            f"Intervals are the paired circular moving-block day bootstrap, "
            f"{N_REPLICATES} replicates, seed {SEED}, block {HEADLINE_BLOCK} day(s). "
            "2024 rows are not rewritten — C11 and C12 wrote them."
        ),
    )
    print(f"appended {report.n_rows_appended:,} rows as run {report.run_id} "
          f"({report.n_rows_before:,} -> {report.n_rows_before + report.n_rows_appended:,})")
    verification = verify_append_only()
    print(f"verify_append_only: {verification}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.phase == "compute":
        return compute(args)
    if args.phase == "dispatch":
        return dispatch(args)
    if args.phase == "analyse":
        return analyse(args)
    if args.phase == "ingest":
        return ingest(args)
    raise RegimeError(f"unknown phase {args.phase!r}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
