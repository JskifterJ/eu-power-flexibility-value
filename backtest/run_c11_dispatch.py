"""CLI: the C11 run — the battery LP across all nine zones and every curve.

    python -m backtest.run_c11_dispatch                      # all 9 zones
    python -m backtest.run_c11_dispatch --zones DE-LU ES      # a subset
    python -m backtest.run_c11_dispatch --no-append           # compute, write no store rows

PLAN.md C11: *"LP across all 9 zones x all curves; persist per-day capture
ratios."* C6 built the commit-then-settle machinery and ran three curves on
DE-LU; this cycle runs **every committed forecast curve of every zone** through
it and persists the per-day capture ratios that C12's block bootstrap and C13's
regime tables are computed from.

Nothing is re-fitted. Every forecast dispatched here is read from the artefact
the cycle that scored it committed, so the dispatch and the point-error metrics
in ``backtest/results/results.csv`` are about the *same numbers* and cannot
drift apart. The curve inventory is in :data:`ARMS`:

* **Tier A** (DE-LU, ES, NO2) — eight forecast curves. The nine-zone comparable
  LEAR (``price_only`` on the full 2019+ history, C8's
  ``full_history_reference``), the three 2022-aligned LEAR arms and the three
  2022-aligned GBM arms from C8/C9, and the naive floor. The two
  ``res_as_published`` arms are labelled ``after_gate_closure`` and travel only
  as the measurement of FINDING C9-C's leak — never as a capture ratio a bidder
  could have had.
* **Tier B** (FR, NL, BE, IT-North, DK1, PL) — the comparable LEAR and the
  naive floor, from C10's artefacts.
* **Every zone** — the oracle, which is the denominator of every capture ratio
  and is dispatched over the union of the zone's wanted days.

What C11 decides, and why
-------------------------
**NOTE C10-01, the NaN policy** (committed): the dispatched LEAR curve is the
``nan_policy="decline"`` series every earlier cycle scored, and a market day
whose forecast vector has a hole is **skipped and counted**, never patched. This
is C6's NOTE C4-02 decision carried to all nine zones unchanged. It costs one
autumn-DST day a year in every zone, and in ES it also costs the days the
``res_*`` arms decline (ES's exogenous join has 145 missing hours, FINDING
C8-*). Every skip is in the per-zone summary with its reason.

**NOTE C10-01, the capture-ratio scope** (decided here, once, for the whole
project): a capture ratio is a **ratio of two sums**, so its numerator and its
denominator must run over the same days, and two arms' capture ratios are only
comparable if they do too. So both scopes the store already knows are written
and they mean for a dispatch metric exactly what they mean for a point-error
one — the vocabulary is about *coverage*, not about the time unit:

``own_coverage``
    Each curve pooled over the days **it** dispatched, with its same-start
    oracle denominator taken over those same days. Internally consistent per
    curve; across curves it mixes a 365-day total with a 366-day one.
``common_hours``
    Every curve of that zone re-pooled over the **intersection of the days every
    one of that zone's C11 curves dispatched**. Exactly C10's definition. This
    is the scope a within-zone arm comparison must be read at, and it is where
    the NOTE C8-01 question (does ``res_persistence`` buy capture?) is settled.

The cross-zone table is built from ``own_coverage``, as C10's was, because the
two tiers' intersections are over different curve sets (nine curves in Tier A,
three in Tier B) and a Tier-A intersection shrunk by an arm that is not even in
the cross-zone comparison would silently re-scope Tier B's neighbours. The risk
in that choice is not argued away but **measured**: ``scope_sensitivity`` in
every zone's summary reports the gap between the two scopes for every curve, so
a reader can see whether the decision moves the result at all.

Invariants (CLAUDE.md, run on every curve of every zone)
--------------------------------------------------------
* ``value(curve @ realised) <= value(same-start oracle @ realised)`` on **every**
  dispatched day of **every** curve — the exact per-day bound, re-solved from the
  candidate's own opening SoC and its own mark.
* ``value(naive @ realised) <= value(forecast @ realised)`` pooled, for each
  forecast curve against the naive floor. Pooled, not per day: CLAUDE.md says
  per-day violations there are real and expected, so the per-day win rate is
  reported beside it.
* No settlement is a read-back of a curve's own decision prices, checked from
  the schedules rather than from the flag.
* ``value_added >= 0`` on each curve's **own decision prices** (a theorem there,
  not at realised prices for a forecast curve), and at realised prices on the
  oracle.
* Day lengths match the local calendar, DST days included.

A failing invariant exits non-zero after the artefacts are written, so the
evidence survives the failure. That is a FLAG, not something to work around.

Nothing here reads 2025: :mod:`data.holdout` refuses a sealed year before a
price file is opened, and the results store refuses a row whose
``evaluation_years`` touches one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backtest.results_store import (
    RESULTS_PATH,
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
from data.config import REPO_ROOT, config_hash, load_battery_config, load_zones
from data.holdout import assert_not_sealed
from dispatch.battery import BatterySpec, DayValuation
from dispatch.curves import (
    Curve,
    CurveError,
    assert_curve_aligns,
    assert_settlement_is_not_a_readback,
    capture_frame,
    capture_summary,
    check_decision_value_added_non_negative,
    check_per_day_dominance,
    common_days,
    report_realised_losses,
    same_start_oracle,
)
from dispatch.rolling import RollingResult, run_rolling_dispatch
from forecast.timing import market_days, zone_timezone

#: The GBM config C9 froze. Carried onto every GBM row so a config change is
#: visible in the store (PLAN.md forbids a hyperparameter search across cycles).
GBM_FINGERPRINT = "a366a760e269bba6"

#: ``train_from`` for the nine-zone comparable arm and the naive floor that
#: accompanies it. The naive forecast needs no training window at all; the field
#: records the run it belongs to, which is what makes its key line up with the
#: comparable arm's.
FULL_HISTORY_FROM = "2019-01-01"
#: ``train_from`` for every arm with an exogenous block: no archived ENTSO-E D-1
#: forecast vintage exists before this date (PLAN.md, ``features.yaml``).
ALIGNED_FROM = "2022-01-01"

#: The oracle's own labels. It is not a forecast and has no training window.
ORACLE_MODEL = "oracle"
ORACLE_VARIANT = "perfect_foresight"


@dataclass(frozen=True)
class Arm:
    """One dispatchable forecast curve, and where it was committed.

    ``curve`` is the name used inside this run (and in the per-day artefact);
    the store key is ``(model, exog_variant, vintage, train_from)``, chosen to
    match C10's taxonomy exactly so a capture ratio and the MAE of the same
    forecast join on it.
    """

    curve: str
    model: str
    exog_variant: str
    artefact: str
    column: str
    train_from: str = ALIGNED_FROM
    vintage: str = "honest"
    model_fingerprint: str = ""

    @property
    def is_comparable(self) -> bool:
        """Part of the like-for-like nine-zone set (PLAN.md's cross-zone claim)."""
        return (
            self.model == "lear"
            and self.exog_variant == "price_only"
            and self.train_from == FULL_HISTORY_FROM
        )


def _tier_a_arms(zone: str) -> list[Arm]:
    c8 = f"c8_exog_{zone}_2024_predictions.csv.gz"
    c9 = f"c9_gbm_{zone}_2024_predictions.csv.gz"
    return [
        # The nine-zone comparable arm: C8's full_history_reference, the only
        # Tier-A series that can sit beside Tier B's (FINDING C10-B).
        Arm("lear_full_history", "lear", "price_only", c8,
            "y_pred_price_only_full_history", FULL_HISTORY_FROM),
        # The 2022-aligned ladder: the only window where the exogenous block can
        # be measured at all.
        Arm("lear_price_only", "lear", "price_only", c8, "y_pred_price_only"),
        Arm("lear_res_persistence", "lear", "res_persistence", c8,
            "y_pred_res_persistence"),
        Arm("lear_res_as_published", "lear", "res_as_published", c8,
            "y_pred_res_as_published", vintage="after_gate_closure"),
        Arm("gbm_price_only", "gbm", "price_only", c9, "y_pred_gbm_price_only",
            model_fingerprint=GBM_FINGERPRINT),
        Arm("gbm_res_persistence", "gbm", "res_persistence", c9,
            "y_pred_gbm_res_persistence", model_fingerprint=GBM_FINGERPRINT),
        Arm("gbm_res_as_published", "gbm", "res_as_published", c9,
            "y_pred_gbm_res_as_published", vintage="after_gate_closure",
            model_fingerprint=GBM_FINGERPRINT),
        Arm("naive", "naive_last_week", "", c8, "y_pred_naive_last_week",
            FULL_HISTORY_FROM),
    ]


def _tier_b_arms(zone: str) -> list[Arm]:
    c10 = f"c10_tierb_{zone}_2024_predictions.csv.gz"
    return [
        Arm("lear_full_history", "lear", "price_only", c10,
            "y_pred_lear_price_only", FULL_HISTORY_FROM),
        Arm("naive", "naive_last_week", "", c10, "y_pred_naive_last_week",
            FULL_HISTORY_FROM),
    ]


def arms_for(zone: str, tier: str) -> list[Arm]:
    """Every forecast curve C11 dispatches for ``zone``. The oracle is separate."""
    if tier == "A":
        return _tier_a_arms(zone)
    if tier == "B":
        return _tier_b_arms(zone)
    raise CurveError(f"{zone}: unknown tier {tier!r}")


#: Pairs of Tier-A arms whose *difference* answers an open question in
#: PROGRESS.md. Reported per zone as ``arm_contrasts``.
CONTRASTS: tuple[tuple[str, str, str], ...] = (
    ("lear_res_persistence", "lear_price_only",
     "NOTE C8-01: does the honest exogenous block buy capture ratio (LEAR)?"),
    ("gbm_res_persistence", "gbm_price_only",
     "NOTE C8-01: does the honest exogenous block buy capture ratio (GBM)?"),
    ("gbm_price_only", "lear_price_only",
     "model class at an honest vintage, price-only"),
    ("gbm_res_persistence", "lear_res_persistence",
     "model class at an honest vintage, with the exogenous block"),
    ("lear_full_history", "lear_price_only",
     "FINDING C10-B: three extra years of price history, in capture terms"),
    ("lear_res_as_published", "lear_res_persistence",
     "FINDING C9-C's vintage premium in capture terms — NOT achievable (LEAR)"),
    ("gbm_res_as_published", "gbm_res_persistence",
     "FINDING C9-C's vintage premium in capture terms — NOT achievable (GBM)"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None, help="zone keys (default: all)")
    parser.add_argument("--years", nargs="*", type=int, default=[2024],
                        help="market-delivery years to dispatch (2025 is sealed)")
    parser.add_argument("--no-append", action="store_true",
                        help="compute and write artefacts, append nothing to the store")
    parser.add_argument("--results-path", default=None,
                        help="override the store path (tests)")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Curves, from the committed artefacts
# ---------------------------------------------------------------------------


def load_arm_curves(
    zone: str, arms: Iterable[Arm], years: list[int], realised: pd.Series
) -> tuple[dict[str, Curve], dict[str, Any]]:
    """Read every arm's committed prediction column into a decision-price curve.

    Three provenance checks, each of which would otherwise show up as skill:

    * every artefact's ``y_true`` must equal the realised series this run
      settles against, hour for hour (an off-by-one index is a leak that looks
      like a model, and the per-day bound would catch it only afterwards);
    * every forecast timestamp must exist in the realised series
      (:func:`dispatch.curves.assert_curve_aligns`);
    * where two artefacts carry the *same* forecast — C9 re-committed C8's LEAR
      columns alongside its GBM ones — they must agree exactly, which is the
      cheap check that this cycle is reading the pair C10 verified.
    """
    tag = "-".join(str(y) for y in years)
    del tag  # the artefact names already carry the year; kept for symmetry
    frames: dict[str, pd.DataFrame] = {}
    truth_gaps: dict[str, float] = {}
    for arm in arms:
        if arm.artefact in frames:
            continue
        path = RESULTS_DIR / arm.artefact
        if not path.exists():
            raise CurveError(
                f"{zone}: the artefact {arm.artefact} is missing. C11 dispatches "
                f"forecasts earlier cycles committed; it does not re-fit one."
            )
        frame = pd.read_csv(path)
        index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
        frame = frame.set_index(index).sort_index()
        aligned = realised.reindex(frame.index)
        if aligned.isna().any():
            raise CurveError(
                f"{zone}/{arm.artefact}: {int(aligned.isna().sum())} forecast "
                f"timestamp(s) have no realised price — the artefact and the "
                f"price cache disagree on the grid."
            )
        gap = float(
            np.nanmax(
                np.abs(
                    frame["y_true"].to_numpy(dtype=float)
                    - aligned.to_numpy(dtype=float)
                )
            )
        )
        if gap > 1e-6:
            raise CurveError(
                f"{zone}/{arm.artefact}: y_true differs from the realised price "
                f"series by up to {gap:.6g} EUR/MWh. One of the two is not what "
                f"that cycle scored."
            )
        truth_gaps[arm.artefact] = gap
        frames[arm.artefact] = frame

    curves: dict[str, Curve] = {}
    for arm in arms:
        frame = frames[arm.artefact]
        if arm.column not in frame.columns:
            raise CurveError(f"{arm.artefact} has no column {arm.column!r}")
        curves[arm.curve] = Curve(
            name=arm.curve,
            prices=frame[arm.column].astype(float),
            source=f"{arm.artefact}:{arm.column}",
        )

    cross = _cross_artefact_agreement(frames)
    report = {
        "artefacts": {
            name: {
                "n_hours": int(len(frame)),
                "first_ts_utc": frame.index[0].isoformat(),
                "last_ts_utc": frame.index[-1].isoformat(),
                "max_y_true_vs_realised_gap": round(truth_gaps[name], 10),
            }
            for name, frame in frames.items()
        },
        "cross_artefact_agreement": cross,
        "curves": {
            arm.curve: {
                **curves[arm.curve].as_dict(),
                "model": arm.model,
                "exog_variant": arm.exog_variant,
                "vintage": arm.vintage,
                "train_from": arm.train_from,
                "source": curves[arm.curve].source,
                "is_comparable_nine_zone_arm": arm.is_comparable,
            }
            for arm in arms
        },
        "alignment": {
            arm.curve: assert_curve_aligns(curves[arm.curve], realised)
            for arm in arms
        },
    }
    return curves, report


#: Columns that C8 and C9 both committed for the same forecast. C10 verified
#: them equal; C11 re-checks, because reading the wrong one of a drifted pair is
#: exactly the failure the store's provenance fields exist to make visible.
SHARED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("y_pred_price_only", "y_pred_lear_price_only"),
    ("y_pred_res_persistence", "y_pred_lear_res_persistence"),
    ("y_pred_res_as_published", "y_pred_lear_res_as_published"),
    ("y_pred_naive_last_week", "y_pred_naive_last_week"),
)


def _cross_artefact_agreement(frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Where two artefacts carry one forecast, they must agree exactly."""
    c8 = next((f for n, f in frames.items() if n.startswith("c8_")), None)
    c9 = next((f for n, f in frames.items() if n.startswith("c9_")), None)
    if c8 is None or c9 is None:
        return {"applicable": False, "reason": "only one artefact in play"}
    if not c8.index.equals(c9.index):
        raise CurveError(
            "C8's and C9's prediction indices differ — the two cycles did not "
            "evaluate the same hours, and C11 will not realign them."
        )
    gaps: dict[str, float] = {}
    for left, right in SHARED_COLUMNS:
        if left in c8.columns and right in c9.columns:
            diff = np.abs(
                c8[left].to_numpy(dtype=float) - c9[right].to_numpy(dtype=float)
            )
            gaps[f"{left} vs {right}"] = float(np.nanmax(diff)) if len(diff) else 0.0
    worst = max(gaps.values(), default=0.0)
    if worst > 1e-9:
        raise CurveError(
            f"C8 and C9 disagree about a shared forecast column by up to {worst:.6g}: "
            f"{gaps}. C10 verified these equal; something has drifted."
        )
    return {
        "applicable": True,
        "indices_equal": True,
        "max_gap_per_column": {k: round(v, 12) for k, v in gaps.items()},
        "holds": True,
    }


# ---------------------------------------------------------------------------
# Pooling a capture ratio over an explicit day set
# ---------------------------------------------------------------------------


def pooled_capture(
    result: RollingResult,
    same_start: dict[dt.date, DayValuation],
    rolled_oracle: RollingResult,
    days: Iterable[dt.date],
    power_mw: float,
) -> dict[str, Any]:
    """Every pooled dispatch number for one curve over one explicit day set.

    The day set is an argument rather than a property of the run because that is
    the whole of the NOTE C10-01 decision: the same curve is reported at two
    scopes, and the only difference between them is which days are summed.
    Numerator and denominator always run over the *same* days — a ratio of sums
    taken over different day sets is not a ratio of anything.
    """
    days = sorted(days)
    if not days:
        return {"n_days": 0}
    orphans = [d for d in days if d not in rolled_oracle.valuations]
    if orphans:
        raise CurveError(
            f"{result.curve}: {len(orphans)} dispatched day(s) have no rolled-oracle "
            f"valuation, first {orphans[0].isoformat()} — the denominator does not "
            f"cover the numerator and the ratio would be meaningless."
        )
    value_added = float(sum(result.valuations[d].value_added_eur for d in days))
    cash = float(sum(result.valuations[d].cash_eur for d in days))
    bound = float(sum(same_start[d].value_added_eur for d in days))
    oracle_cash = float(sum(rolled_oracle.valuations[d].cash_eur for d in days))
    oracle_added = float(sum(rolled_oracle.valuations[d].value_added_eur for d in days))
    discharged = float(sum(result.valuations[d].energy_discharged_mwh for d in days))
    span = (days[-1] - days[0]).days + 1
    per_mw_year = cash / power_mw / span * 365.25 if span > 0 else float("nan")
    lost = oracle_cash - cash
    daily = np.array(
        [
            result.valuations[d].value_added_eur / same_start[d].value_added_eur
            if abs(same_start[d].value_added_eur) > 1e-9
            else np.nan
            for d in days
        ],
        dtype=float,
    )
    defined = np.isfinite(daily)
    quantiles = (
        {
            f"p{int(q * 100):02d}": float(np.quantile(daily[defined], q))
            for q in (0.05, 0.25, 0.5, 0.75, 0.95)
        }
        if defined.any()
        else {}
    )
    return {
        "n_days": len(days),
        "first_day": days[0].isoformat(),
        "last_day": days[-1].isoformat(),
        "cash_eur": cash,
        "value_added_eur": value_added,
        "same_start_oracle_value_added_eur": bound,
        "rolled_oracle_cash_eur": oracle_cash,
        "rolled_oracle_value_added_eur": oracle_added,
        "cash_eur_per_mw_year": per_mw_year,
        "capture_same_start_pooled": (
            value_added / bound if abs(bound) > 1e-9 else None
        ),
        "capture_rolled_oracle_cash": (
            cash / oracle_cash if abs(oracle_cash) > 1e-9 else None
        ),
        "eur_per_mw_year_lost_vs_oracle": (
            lost / power_mw / span * 365.25 if span > 0 else None
        ),
        "n_days_capture_defined": int(defined.sum()),
        "capture_same_start_mean_daily": (
            float(np.mean(daily[defined])) if defined.any() else None
        ),
        "capture_same_start_quantiles_daily": quantiles,
        "n_days_capture_above_one": int((daily[defined] > 1 + 1e-9).sum()),
        "n_days_value_added_negative": int(
            sum(1 for d in days if result.valuations[d].value_added_eur < -1e-6)
        ),
        "share_of_days_value_added_negative": float(
            sum(1 for d in days if result.valuations[d].value_added_eur < -1e-6)
        )
        / len(days),
        "n_days_with_simultaneity": int(
            sum(1 for d in days if result.valuations[d].simultaneity.found)
        ),
        "share_of_days_with_simultaneity": float(
            sum(1 for d in days if result.valuations[d].simultaneity.found)
        )
        / len(days),
        "equivalent_full_cycles": discharged / float(result.spec.energy_mwh),
        "realised_spread_mean_eur_per_mwh": float(
            np.mean(
                [
                    np.max(result.realised_prices[d]) - np.min(result.realised_prices[d])
                    for d in days
                ]
            )
        ),
        "realised_spread_median_eur_per_mwh": float(
            np.median(
                [
                    np.max(result.realised_prices[d]) - np.min(result.realised_prices[d])
                    for d in days
                ]
            )
        ),
    }


def beats_naive(
    result: RollingResult, naive: RollingResult, days: Iterable[dt.date]
) -> dict[str, Any]:
    """CLAUDE.md's ``naive <= forecast`` half, pooled, with the per-day rate beside it.

    Pooled is the assertion; per day is a *reported* rate, because CLAUDE.md
    says per-day violations here are real and expected and a number beats a
    reassurance.
    """
    days = sorted(days)
    if not days:
        return {"applicable": False}
    model_cash = float(sum(result.valuations[d].cash_eur for d in days))
    naive_cash = float(sum(naive.valuations[d].cash_eur for d in days))
    wins = sum(
        1
        for d in days
        if result.valuations[d].value_added_eur
        > naive.valuations[d].value_added_eur + 1e-9
    )
    return {
        "applicable": True,
        "holds": model_cash >= naive_cash - 1e-6,
        "n_days": len(days),
        "model_cash_eur": round(model_cash, 4),
        "naive_cash_eur": round(naive_cash, 4),
        "margin_eur": round(model_cash - naive_cash, 4),
        "per_day_beats_naive_days": wins,
        "per_day_beats_naive_share": round(wins / len(days), 6),
    }


# ---------------------------------------------------------------------------
# Point error on exactly the hours the capture ratio is computed over
# ---------------------------------------------------------------------------


def mae_on_days(
    curve: Curve, realised: pd.Series, days: Iterable[dt.date], tz: str
) -> dict[str, float] | None:
    """MAE of a forecast over the hours of ``days``, and nothing else.

    C11's whole point is to set a point-error metric beside a dispatch metric,
    and that comparison is only honest if both are computed over **the same
    rows**. C10's committed MAE figures are over each arm's own evaluation
    coverage, which for ES differs from the dispatched-day hour set by ~145
    hours (the exogenous join's holes), so reusing them here would pair a
    capture delta with an MAE delta measured on a different sample. This
    recomputes the point error on the dispatched days instead — same hours, same
    arm, same realised series.
    """
    days = set(days)
    if not days:
        return None
    index = curve.prices.index
    labels = pd.Series(index).dt.tz_convert(tz).dt.date.to_numpy()
    mask = np.isin(labels, np.array(sorted(days), dtype=object))
    forecast = curve.prices.to_numpy(dtype=float)[mask]
    actual = realised.reindex(index[mask]).to_numpy(dtype=float)
    finite = np.isfinite(forecast) & np.isfinite(actual)
    if not finite.any():
        return None
    error = forecast[finite] - actual[finite]
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "bias": float(np.mean(error)),
        "n_hours": int(finite.sum()),
    }


# ---------------------------------------------------------------------------
# Cross-cycle reproduction: C6's committed DE-LU numbers
# ---------------------------------------------------------------------------

#: C6 dispatched C4's ``y_pred_lear_aic`` on DE-LU. That column is
#: byte-identical to C8's ``y_pred_price_only_full_history``, which is C11's
#: ``lear_full_history`` arm — so C11 must reproduce C6's committed numbers
#: exactly, not approximately. The tolerance is C6's own JSON precision (six
#: decimals on a ratio, four on a euro figure), not a margin chosen to let a
#: disagreement pass.
C6_SUMMARY = "c6_curves_DE-LU_2024_summary.json"


def check_c6_reproduction(
    zone: str, pooled: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Assert C11 reproduces C6's committed DE-LU dispatch numbers.

    Each number is compared at the scope C6 computed it at, which is itself the
    point: C6's pooled cash figures are over the common day set and its per-curve
    capture summaries are over each curve's own days, so a naive comparison of
    "C6's naive capture" against C11's ``common_hours`` row disagrees in the
    fourth decimal for a reason that is a scope and not an error. Getting this
    right is the first real test of the NOTE C10-01 decision.
    """
    path = RESULTS_DIR / C6_SUMMARY
    if zone != "DE-LU" or not path.exists():
        return {"applicable": False, "reason": f"no {C6_SUMMARY} for {zone}"}
    with path.open("r", encoding="utf-8") as fh:
        c6 = json.load(fh)
    want = c6["pooled_comparison"]
    checks = [
        ("oracle_pooled_cash_eur", want["pooled"]["oracle"]["cash_eur"],
         pooled["oracle"]["common_hours"]["cash_eur"], 5e-4),
        ("model_pooled_cash_eur", want["pooled"]["model"]["cash_eur"],
         pooled["lear_full_history"]["common_hours"]["cash_eur"], 5e-4),
        ("naive_pooled_cash_eur", want["pooled"]["naive"]["cash_eur"],
         pooled["naive"]["common_hours"]["cash_eur"], 5e-4),
        ("model_capture_rolled_cash", want["capture_ratio_rolled_cash"],
         pooled["lear_full_history"]["common_hours"]["capture_rolled_oracle_cash"], 5e-7),
        ("naive_capture_rolled_cash", want["naive_capture_ratio_rolled_cash"],
         pooled["naive"]["common_hours"]["capture_rolled_oracle_cash"], 5e-7),
        ("model_capture_same_start_own_coverage",
         c6["curves"]["model"]["capture"]["pooled_capture_same_start"],
         pooled["lear_full_history"]["own_coverage"]["capture_same_start_pooled"], 5e-7),
        ("naive_capture_same_start_own_coverage",
         c6["curves"]["naive"]["capture"]["pooled_capture_same_start"],
         pooled["naive"]["own_coverage"]["capture_same_start_pooled"], 5e-7),
        ("n_common_days", float(want["n_common_days"]),
         float(pooled["lear_full_history"]["common_hours"]["n_days"]), 0.0),
    ]
    results = []
    for name, committed, recomputed, tol in checks:
        delta = abs(float(committed) - float(recomputed))
        results.append({
            "check": name,
            "c6_committed": committed,
            "c11_recomputed": round(float(recomputed), 10),
            "abs_delta": round(delta, 12),
            "tolerance": tol,
            "holds": delta <= tol,
        })
    return {
        "applicable": True,
        "holds": all(r["holds"] for r in results),
        "source": C6_SUMMARY,
        "source_cycle": "C6",
        "n_checks": len(results),
        "worst_abs_delta": max(r["abs_delta"] for r in results),
        "checks": results,
        "note": (
            "C6 dispatched C4's y_pred_lear_aic; C11's lear_full_history arm "
            "reads C8's y_pred_price_only_full_history, which is the same "
            "column to 0 EUR/MWh. The two cycles must therefore agree exactly."
        ),
    }


# ---------------------------------------------------------------------------
# One zone
# ---------------------------------------------------------------------------


def run_zone(
    zone: str,
    tier: str,
    regime: str,
    spec: BatterySpec,
    years: list[int],
    cfg: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame, list[ResultRow]]:
    """Dispatch every curve of one zone and return (summary, per-day frame, rows)."""
    terminal = cfg.get("terminal") or {}
    tz = zone_timezone(zone)
    arms = arms_for(zone, tier)
    realised = load_realised(zone, years)
    curves, curve_report = load_arm_curves(zone, arms, years, realised)

    roll_kwargs = dict(
        trailing_days=int(terminal.get("trailing_days", 7)),
        trailing_quantile=float(terminal.get("trailing_quantile", 0.5)),
        min_trailing_days=int(terminal.get("min_trailing_days", 1)),
        tz=tz,
    )
    # The dispatch window is the union of the days *some* committed forecast
    # covers, so the oracle's trajectory spans every day any arm can be compared
    # on, and no arm is scored against an oracle that skipped its days.
    forecast_days: set[dt.date] = set()
    for curve in curves.values():
        forecast_days |= set(
            market_days(pd.DatetimeIndex(curve.prices.index), tz).tolist()
        )
    labels = pd.Series(realised.index).dt.tz_convert(tz).dt.date
    wanted = {d for d in labels if d.year in set(years)} & forecast_days
    if not wanted:
        raise CurveError(f"{zone}: no market day is both in {years} and forecast")

    print(f"\n=== {zone} (tier {tier}, {regime}) — {len(arms)} forecast curve(s) "
          f"+ oracle over {len(wanted)} market days "
          f"{min(wanted)} .. {max(wanted)} ===")

    results: dict[str, RollingResult] = {
        "oracle": run_rolling_dispatch(
            zone, realised, spec, decision_prices=None, curve="oracle",
            days=wanted, **roll_kwargs
        )
    }
    for arm in arms:
        results[arm.curve] = run_rolling_dispatch(
            zone, realised, spec, decision_prices=curves[arm.curve].prices,
            curve=arm.curve, days=wanted, **roll_kwargs
        )

    bounds = {name: same_start_oracle(res, spec) for name, res in results.items()}

    # --- the two scopes (NOTE C10-01) ------------------------------------
    own = {name: set(res.days) for name, res in results.items()}
    shared = common_days(results)
    print(f"  dispatched days per curve: "
          + ", ".join(f"{n}={len(d)}" for n, d in sorted(own.items())))
    print(f"  common to every curve: {len(shared)}")

    pooled: dict[str, dict[str, Any]] = {}
    for name, res in results.items():
        pooled[name] = {
            "own_coverage": pooled_capture(
                res, bounds[name], results["oracle"], own[name], spec.power_mw
            ),
            "common_hours": pooled_capture(
                res, bounds[name], results["oracle"], shared, spec.power_mw
            ),
        }

    # --- point error on exactly the dispatched hours ---------------------
    point_error = {
        arm.curve: mae_on_days(curves[arm.curve], realised, shared, tz)
        for arm in arms
    }

    # --- invariants, every curve -----------------------------------------
    invariants: dict[str, dict[str, Any]] = {}
    for name, res in results.items():
        block = {
            "day_lengths_match_local_calendar": check_day_lengths(res, zone),
            "settlement_is_not_a_decision_price_readback":
                assert_settlement_is_not_a_readback(res),
            "decision_value_added_non_negative":
                check_decision_value_added_non_negative(res, spec),
        }
        if name == "oracle":
            block["value_added_non_negative_at_realised"] = (
                check_value_added_non_negative(res)
            )
        else:
            block["same_start_oracle_dominates_every_day"] = check_per_day_dominance(
                res, bounds[name]
            )
            block["beats_naive_pooled_common_days"] = beats_naive(
                res, results["naive"], shared
            ) if name != "naive" else {"applicable": False,
                                       "reason": "this is the naive floor"}
            # The pooled half of the oracle bound. The per-day version above is
            # the theorem; this is the one the capture ratio is actually read
            # off, and a ratio above 1 would mean the headline is nonsense.
            arm_cash = pooled[name]["common_hours"]["cash_eur"]
            oracle_cash = pooled["oracle"]["common_hours"]["cash_eur"]
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

    reproduction = check_c6_reproduction(zone, pooled)
    if reproduction.get("applicable"):
        print(f"  C6 reproduction: {reproduction['n_checks']} check(s), worst "
              f"absolute delta {reproduction['worst_abs_delta']:.3g} "
              f"[{'OK' if reproduction['holds'] else 'FAIL'}]")

    failures = [
        f"{name}.{check}"
        for name, block in invariants.items()
        for check, outcome in block.items()
        if outcome.get("applicable", True) and not outcome.get("holds", True)
    ]
    if reproduction.get("applicable") and not reproduction["holds"]:
        failures.append("cross_cycle.c6_reproduction")
    for name in sorted(results):
        dominance = invariants[name].get("same_start_oracle_dominates_every_day")
        mark = "OK " if not any(f.startswith(f"{name}.") for f in failures) else "FAIL"
        block = pooled[name]["common_hours"]
        rolled = block["capture_rolled_oracle_cash"]
        same = block["capture_same_start_pooled"]
        print(f"  [{mark}] {name:<22} cash {block['cash_eur']:>11,.0f} EUR  "
              f"{block['cash_eur_per_mw_year']:>9,.0f} EUR/MW/yr  "
              f"capture {'  n/a ' if rolled is None else f'{rolled:.4f}'} "
              f"(same-start {'n/a' if same is None else f'{same:.4f}'})"
              + (f"  worst per-day excess {dominance['worst_excess_eur']:+.2e}"
                 if dominance else ""))

    # --- per-day artefact -------------------------------------------------
    frames = []
    for name, res in results.items():
        frame = capture_frame(res, results["oracle"], bounds[name])
        if frame.empty:
            continue
        arm = next((a for a in arms if a.curve == name), None)
        frame["tier"] = tier
        frame["regime"] = regime
        frame["model"] = ORACLE_MODEL if arm is None else arm.model
        frame["exog_variant"] = ORACLE_VARIANT if arm is None else arm.exog_variant
        frame["vintage"] = "honest" if arm is None else arm.vintage
        frame["train_from"] = "" if arm is None else arm.train_from
        frame["in_common_day_set"] = [
            day in set(d.isoformat() for d in shared) for day in frame["market_day"]
        ]
        frames.append(frame)
    daily = pd.concat(frames, ignore_index=True)

    # --- contrasts and scope sensitivity ---------------------------------
    contrasts = []
    for left, right, question in CONTRASTS:
        if left not in pooled or right not in pooled:
            continue
        a = pooled[left]["common_hours"]
        b = pooled[right]["common_hours"]
        if a.get("capture_same_start_pooled") is None or b.get("capture_same_start_pooled") is None:
            continue
        pe_a, pe_b = point_error.get(left), point_error.get(right)
        mae_gain_pct = (
            None
            if not pe_a or not pe_b or pe_b["mae"] == 0
            else round(100 * (pe_b["mae"] - pe_a["mae"]) / pe_b["mae"], 4)
        )
        contrasts.append({
            "question": question,
            "arm": left,
            "baseline": right,
            "scope": "common_hours",
            "n_days": a["n_days"],
            # MAE over the *same* hours the capture ratio is computed over, so
            # the two deltas below are a paired comparison by construction
            # (FINDING C11-D). Positive = the arm has the lower MAE.
            "mae_arm": None if not pe_a else round(pe_a["mae"], 6),
            "mae_baseline": None if not pe_b else round(pe_b["mae"], 6),
            "mae_gain_pct": mae_gain_pct,
            "n_hours_point_error": None if not pe_a else pe_a["n_hours"],
            "sign_agrees": (
                None
                if mae_gain_pct is None
                else bool(
                    np.sign(mae_gain_pct)
                    == np.sign(
                        a["capture_rolled_oracle_cash"] - b["capture_rolled_oracle_cash"]
                    )
                )
            ),
            # The headline is the rolled-oracle ratio: one denominator for
            # every arm of the zone, so a difference is a difference in the
            # arm. The same-start ratio rides along because it is the exact
            # per-day bound, but FINDING C11-C makes it unfit to *compare*
            # arms on — its denominator moves with the arm's own opening SoC.
            "capture_rolled_arm": round(a["capture_rolled_oracle_cash"], 6),
            "capture_rolled_baseline": round(b["capture_rolled_oracle_cash"], 6),
            "capture_rolled_delta_pp": round(
                100 * (a["capture_rolled_oracle_cash"] - b["capture_rolled_oracle_cash"]), 4
            ),
            "capture_arm": round(a["capture_same_start_pooled"], 6),
            "capture_baseline": round(b["capture_same_start_pooled"], 6),
            "capture_delta_pp": round(
                100 * (a["capture_same_start_pooled"] - b["capture_same_start_pooled"]), 4
            ),
            "eur_per_mw_year_delta": round(
                a["cash_eur_per_mw_year"] - b["cash_eur_per_mw_year"], 2
            ),
            "both_honest": not (
                "as_published" in left or "as_published" in right
            ),
        })
    def _gap(name: str, key: str) -> dict[str, Any]:
        own = pooled[name]["own_coverage"].get(key)
        common = pooled[name]["common_hours"].get(key)
        return {
            "own": None if own is None else round(own, 6),
            "common": None if common is None else round(common, 6),
            "gap_pp": (
                None
                if own is None or common is None
                else round(100 * (own - common), 4)
            ),
        }

    # Both ratios, because the NOTE C10-01 decision has to be auditable on the
    # metric it is actually read off. `capture_rolled` is the headline
    # (FINDING C11-C); `capture_same_start` is the exact per-day bound.
    scope_sensitivity = {
        name: {
            "n_days_own": pooled[name]["own_coverage"]["n_days"],
            "n_days_common": pooled[name]["common_hours"]["n_days"],
            "capture_rolled": _gap(name, "capture_rolled_oracle_cash"),
            "capture_same_start": _gap(name, "capture_same_start_pooled"),
            "cash_eur": _gap(name, "cash_eur"),
        }
        for name in sorted(results)
    }

    summary = {
        "cycle": "C11",
        "zone": zone,
        "tier": tier,
        "regime": regime,
        "years": years,
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "battery_spec": spec.as_dict(),
        "n_market_days_wanted": len(wanted),
        "curve_sources": curve_report,
        "dispatched_days_per_curve": {n: len(d) for n, d in sorted(own.items())},
        "n_common_days": len(shared),
        "skipped_days_per_curve": {
            name: [s.as_dict() for s in res.skipped] for name, res in results.items()
        },
        "pooled": pooled,
        "invariants": invariants,
        "realised_losses": {
            name: report_realised_losses(res) for name, res in results.items()
        },
        "simultaneity": {
            name: simultaneity_flag(res, spec) for name, res in results.items()
        },
        "arm_contrasts": contrasts,
        "point_error_on_dispatched_hours": point_error,
        "scope_sensitivity": scope_sensitivity,
        "c6_reproduction": reproduction,
        "invariant_failures": failures,
        "nan_policy": {
            "policy": "decline",
            "decision": "a market day whose forecast vector has a hole is skipped "
                        "and counted, never patched (NOTE C4-02 / NOTE C10-01)",
        },
        "capture_scope_decision": {
            "own_coverage": "each curve pooled over the days it dispatched; "
                            "same-start denominator over those same days",
            "common_hours": "every curve of this zone re-pooled over the "
                            "intersection of the days every C11 curve of this "
                            "zone dispatched",
            "headline_for_within_zone_arm_comparison": "common_hours",
            "headline_for_cross_zone_table": "own_coverage",
            "why": "the two tiers' intersections are over different curve sets "
                   "(9 vs 3), so a Tier-A intersection shrunk by an arm that is "
                   "not in the cross-zone comparison would re-scope Tier B's "
                   "neighbours; scope_sensitivity reports what the choice costs",
        },
    }

    rows = store_rows(zone, tier, regime, arms, pooled, years, spec, point_error)
    return summary, daily, rows


# ---------------------------------------------------------------------------
# Store rows
# ---------------------------------------------------------------------------

#: Metric name -> the key in a :func:`pooled_capture` block it reads. Long
#: format makes the metric name the extension point, so none of this needs a
#: schema change or a test edit (``docs/results_store.md``).
METRIC_KEYS: tuple[tuple[str, str], ...] = (
    ("dispatch_cash_eur", "cash_eur"),
    ("dispatch_value_added_eur", "value_added_eur"),
    ("dispatch_cash_eur_per_mw_year", "cash_eur_per_mw_year"),
    ("capture_same_start_pooled", "capture_same_start_pooled"),
    ("capture_same_start_mean_daily", "capture_same_start_mean_daily"),
    ("capture_rolled_oracle_cash", "capture_rolled_oracle_cash"),
    ("eur_per_mw_year_lost_vs_oracle", "eur_per_mw_year_lost_vs_oracle"),
    ("share_of_days_value_added_negative", "share_of_days_value_added_negative"),
    ("share_of_days_with_simultaneity", "share_of_days_with_simultaneity"),
    ("equivalent_full_cycles", "equivalent_full_cycles"),
    ("realised_spread_mean_eur_per_mwh", "realised_spread_mean_eur_per_mwh"),
    ("realised_spread_median_eur_per_mwh", "realised_spread_median_eur_per_mwh"),
)

#: The per-day capture distribution PLAN.md asks for ("the full distribution,
#: not just the mean"), as quantile metrics.
QUANTILE_METRICS: tuple[str, ...] = ("p05", "p25", "p50", "p75", "p95")


def store_rows(
    zone: str,
    tier: str,
    regime: str,
    arms: list[Arm],
    pooled: dict[str, dict[str, Any]],
    years: list[int],
    spec: BatterySpec,
    point_error: dict[str, dict[str, float] | None] | None = None,
) -> list[ResultRow]:
    """One row per (curve, scope, metric). ``n`` carries the day count.

    The ``*_on_dispatched_hours`` metrics are the point error recomputed over
    exactly the hours the ``common_hours`` capture ratio is computed over, so a
    later cycle can pair the two without re-deriving the sample (FINDING C11-D).
    """
    eval_years = ",".join(str(y) for y in years)
    by_curve = {arm.curve: arm for arm in arms}
    rows: list[ResultRow] = []
    for curve, scopes in pooled.items():
        arm = by_curve.get(curve)
        model = ORACLE_MODEL if arm is None else arm.model
        variant = ORACLE_VARIANT if arm is None else arm.exog_variant
        vintage = "honest" if arm is None else arm.vintage
        train_from = "" if arm is None else arm.train_from
        fingerprint = "" if arm is None else arm.model_fingerprint
        for scope, block in scopes.items():
            if not block.get("n_days"):
                continue
            common = dict(
                zone=zone,
                tier=tier,
                regime=regime,
                model=model,
                exog_variant=variant,
                vintage=vintage,
                train_from=train_from,
                model_fingerprint=fingerprint,
                evaluation_years=eval_years,
                scope=scope,
                n=str(block["n_days"]),
                n_scored=str(block["n_days_capture_defined"]),
                source_cycle="C11",
            )
            for metric, key in METRIC_KEYS:
                value = block.get(key)
                if value is None or not np.isfinite(float(value)):
                    continue
                rows.append(ResultRow(metric=metric, value=float(value), **common))
            for name in QUANTILE_METRICS:
                value = block["capture_same_start_quantiles_daily"].get(name)
                if value is None or not np.isfinite(float(value)):
                    continue
                rows.append(
                    ResultRow(
                        metric=f"capture_same_start_{name}_daily",
                        value=float(value),
                        **common,
                    )
                )
            if scope == "common_hours" and point_error and point_error.get(curve):
                errors = point_error[curve]
                for metric, key in (
                    ("mae_on_dispatched_hours", "mae"),
                    ("rmse_on_dispatched_hours", "rmse"),
                    ("bias_on_dispatched_hours", "bias"),
                ):
                    rows.append(
                        ResultRow(
                            metric=metric,
                            value=float(errors[key]),
                            **{**common, "n_scored": str(errors["n_hours"])},
                        )
                    )
    return rows


# ---------------------------------------------------------------------------
# Cross-zone table
# ---------------------------------------------------------------------------


def comparable_table(
    summaries: dict[str, dict[str, Any]], scope: str = "own_coverage"
) -> pd.DataFrame:
    """The nine-zone like-for-like capture table (PLAN.md's cross-zone claim).

    Only the comparable LEAR arm, the naive floor and the oracle, all three of
    which exist on the same terms in every zone: price-history features only,
    trained from 2019-01-01. An arm on the 2022-aligned window cannot enter —
    it does not exist for Tier B — and neither can an ``after_gate_closure``
    one.

    ``capture_model`` is the **rolled-oracle** ratio: settled cash over the
    rolled perfect-foresight run's cash on the same days. That denominator is
    one number per zone, identical for every curve, which is what makes the
    column comparable across curves and across zones. The same-start ratio is
    carried beside it as ``capture_model_same_start`` because it is the exact
    per-day bound the invariant is stated on — but it is **not** the headline:
    its denominator is re-solved from each curve's own opening SoC, so it
    rewards a curve for arriving at a day in a state where little is attainable
    (FINDING C11-C).
    """
    rows = []
    for zone, summary in summaries.items():
        pooled = summary["pooled"]
        oracle = pooled["oracle"][scope]
        model = pooled["lear_full_history"][scope]
        naive = pooled["naive"][scope]
        rows.append({
            "zone": zone,
            "tier": summary["tier"],
            "regime": summary["regime"],
            "n_days_model": model["n_days"],
            "oracle_eur_per_mw_year": oracle["cash_eur_per_mw_year"],
            "model_eur_per_mw_year": model["cash_eur_per_mw_year"],
            "naive_eur_per_mw_year": naive["cash_eur_per_mw_year"],
            "capture_model": model["capture_rolled_oracle_cash"],
            "capture_naive": naive["capture_rolled_oracle_cash"],
            "capture_model_same_start": model["capture_same_start_pooled"],
            "capture_naive_same_start": naive["capture_same_start_pooled"],
            "eur_per_mw_year_lost": model["eur_per_mw_year_lost_vs_oracle"],
            "mean_daily_spread": oracle["realised_spread_mean_eur_per_mwh"],
            "equivalent_full_cycles_oracle": oracle["equivalent_full_cycles"],
            "share_days_model_loses_money": model["share_of_days_value_added_negative"],
        })
    frame = pd.DataFrame(rows)
    return frame.sort_values("capture_model", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    zones = load_zones()
    selected = args.zones or list(zones)
    unknown = [z for z in selected if z not in zones]
    if unknown:
        raise SystemExit(f"unknown zone key(s): {unknown}")
    for year in args.years:
        assert_not_sealed(year, "run the C11 nine-zone dispatch")

    store_path = None if args.results_path is None else __import__("pathlib").Path(args.results_path)
    if (store_path or RESULTS_PATH).exists():
        # Raises on the first mismatch; the boolean is belt-and-braces.
        verification = verify_append_only(store_path)
        print(f"results store: {verification['n_rows']} existing row(s), "
              f"append-only verification "
              f"{'OK' if verification['verified'] else 'FAILED'}")
        if not verification["verified"]:
            raise SystemExit(
                f"the results store does not verify as append-only: {verification}. "
                f"This is a FLAG — do not append on top of it."
            )

    cfg = load_battery_config()
    spec = BatterySpec.from_config(cfg)
    years = list(args.years)
    print(f"battery: {spec.power_mw} MW / {spec.energy_mwh} MWh "
          f"({spec.duration_hours:g}h), eta_leg={spec.eta_leg:.6f}, "
          f"k={spec.throughput_cost_eur_per_mwh} EUR/MWh, "
          f"terminal {spec.terminal_mode}")

    summaries: dict[str, dict[str, Any]] = {}
    all_rows: list[ResultRow] = []
    all_daily: list[pd.DataFrame] = []
    failures: dict[str, list[str]] = {}
    for zone in selected:
        meta = zones[zone]
        summary, daily, rows = run_zone(
            zone, meta.tier, meta.regime or "", spec, years, cfg
        )
        summaries[zone] = summary
        all_rows.extend(rows)
        all_daily.append(daily)
        if summary["invariant_failures"]:
            failures[zone] = summary["invariant_failures"]

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        tag = f"{zone}_{'-'.join(str(y) for y in years)}"
        daily_path = RESULTS_DIR / f"c11_dispatch_{tag}_daily.csv.gz"
        daily.to_csv(daily_path, index=False, float_format="%.6f")
        summary_path = RESULTS_DIR / f"c11_dispatch_{tag}_summary.json"
        with summary_path.open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
            fh.write("\n")
        print(f"  wrote {daily_path.relative_to(REPO_ROOT)} "
              f"({daily_path.stat().st_size / 1024:.0f} KiB) and "
              f"{summary_path.name}")

    # --- the pooled per-day artefact C12 bootstraps over ------------------
    pooled_daily = pd.concat(all_daily, ignore_index=True)
    pooled_path = RESULTS_DIR / f"c11_capture_daily_{'-'.join(str(y) for y in years)}.csv.gz"
    pooled_daily.to_csv(pooled_path, index=False, float_format="%.6f")

    table = comparable_table(summaries) if len(summaries) == len(zones) else None
    if table is not None:
        print("\n=== nine-zone comparable capture (own_coverage, LEAR price-only, "
              "trained from 2019-01-01) ===")
        print(table.to_string(
            index=False,
            formatters={
                "capture_model": "{:.4f}".format,
                "capture_naive": "{:.4f}".format,
                "oracle_eur_per_mw_year": "{:,.0f}".format,
                "model_eur_per_mw_year": "{:,.0f}".format,
                "naive_eur_per_mw_year": "{:,.0f}".format,
                "eur_per_mw_year_lost": "{:,.0f}".format,
                "mean_daily_spread": "{:.2f}".format,
                "equivalent_full_cycles_oracle": "{:.1f}".format,
                "share_days_model_loses_money": "{:.4f}".format,
            },
        ))
        table_path = RESULTS_DIR / "c11_comparable_capture.csv"
        table.to_csv(table_path, index=False, float_format="%.6f")
        print(f"  wrote {table_path.relative_to(REPO_ROOT)}")

    run_summary: dict[str, Any] = {
        "cycle": "C11",
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_versions": library_versions(),
        "library_fingerprint": library_fingerprint(),
        "zones": selected,
        "years": years,
        "battery_spec": spec.as_dict(),
        "n_store_rows_built": len(all_rows),
        "invariant_failures": failures,
        "comparable_table": (
            None if table is None else table.to_dict(orient="records")
        ),
        "per_zone": {
            zone: {
                "tier": s["tier"],
                "regime": s["regime"],
                "n_common_days": s["n_common_days"],
                "dispatched_days_per_curve": s["dispatched_days_per_curve"],
                "arm_contrasts": s["arm_contrasts"],
                "scope_sensitivity": s["scope_sensitivity"],
                "invariant_failures": s["invariant_failures"],
            }
            for zone, s in summaries.items()
        },
    }

    if args.no_append:
        print(f"\n--no-append: {len(all_rows)} row(s) built, none written")
        run_summary["append_report"] = {"appended": False}
    elif failures:
        print(f"\nNOT appending to the store: {failures}")
    else:
        report = append_rows(
            all_rows,
            cycle="C11",
            git_sha=git_sha(),
            config_hash=config_hash(),
            path=store_path,
            argv=["python", "-m", "backtest.run_c11_dispatch", *(argv or [])],
            note="C11: battery LP across all nine zones and every committed "
                 "curve; per-day capture ratios persisted alongside.",
        )
        print(f"\nappended {report.n_rows_appended} row(s) to {report.path} "
              f"({report.n_rows_before} -> {report.n_rows_after}), "
              f"run {report.run_id}")
        run_summary["append_report"] = report.as_dict()
        verification = verify_append_only(store_path)
        run_summary["append_only_verified"] = verification["verified"]
        print(f"append-only verification after the write: "
              f"{'OK' if verification['verified'] else 'FAILED'} "
              f"({verification['n_rows']} rows, {verification['n_runs']} runs)")

    # The store's own record of what is in it, independent of whether this
    # particular invocation appended — so a re-run of the analysis cannot make
    # the artefact look as though nothing was ever written.
    try:
        final = verify_append_only(store_path)
        run_summary["results_store"] = {
            "n_rows": final["n_rows"],
            "n_runs": final["n_runs"],
            "runs": final["runs"],
            "verified": final["verified"],
        }
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
        run_summary["results_store"] = {"verified": False, "error": str(exc)}
        print(f"WARNING: the results store did not verify after this run: {exc}")

    run_path = RESULTS_DIR / "c11_dispatch_summary.json"
    with run_path.open("w", encoding="utf-8") as fh:
        json.dump(run_summary, fh, indent=2, default=str)
        fh.write("\n")
    print(f"wrote {run_path.relative_to(REPO_ROOT)} and "
          f"{pooled_path.relative_to(REPO_ROOT)} "
          f"({pooled_path.stat().st_size / 1024:.0f} KiB, {len(pooled_daily)} rows)")

    if failures:
        raise SystemExit(
            f"C11 invariant(s) failed: {failures}. See the per-zone summaries; "
            f"this is a FLAG, not something to work around."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
