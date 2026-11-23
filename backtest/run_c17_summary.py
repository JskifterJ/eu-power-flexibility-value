"""CLI: C17 — the holdout read against the visible years, like for like.

    python -m backtest.run_c17_summary

**This module computes no new result.** It reads committed per-day artefacts —
C13's ``c13_daily_by_year.csv.gz`` for 2020-2024 and the evaluation's own
``c17_holdout_<ZONE>_2025_daily.csv.gz`` — and re-aggregates them. Nothing is
re-fitted, no model is touched, and no row reaches the store. The
pre-registration's stop rule forbids changing a model, a feature, a battery
parameter or a metric definition once the first 2025 number has been seen; it
does not forbid reading the number that was produced, and this is that reading.

Why it exists
-------------

The holdout's capture ratio came out **above every visible year in seven of the
nine zones**. Before that can be written down as a finding, the obvious
confound has to be removed: the holdout window is **273 days ending
2025-09-30**, because PLAN.md ends the main hourly backtest the day before the
SDAC 15-minute go-live. The visible years are full calendar years. If the last
quarter is systematically the hard part of a year, "2025 is the best year" would
be a statement about October-December, not about 2025.

So every visible year is re-aggregated over **January-September only**, from the
same committed per-day rows, and the holdout is compared against *that*. The
Q4 term is reported per (zone, year) rather than asserted, so a reader can see
how big it is instead of taking the correction on trust.

The second thing this answers is the mechanism. FINDING C13-D says capture
tracks ``error_over_headroom`` — the pooled forecast error divided by the daily
spread there is to trade — and not the error on its own. 2025 is the test that
separates them, because the forecast got **worse** in absolute terms while the
spreads grew faster. Both series are written out per (zone, year).

Outputs: ``c17_like_for_like.csv`` (the per-cell table) and ``c17_summary.json``
(the headline fields the README's numbers are bound to, so that C20's claims
phase can re-read them rather than trust the prose).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.results_store import RESULTS_DIR, read_results
from backtest.run_c3_naive import git_sha

#: C13's per-day frame for the visible years, and the holdout's own per-day
#: frames. Identical columns — which is what C17's runner was built to
#: guarantee and what makes this re-aggregation legitimate.
VISIBLE_DAILY = RESULTS_DIR / "c13_daily_by_year.csv.gz"
HOLDOUT_DAILY_GLOB = "c17_holdout_*_2025_daily.csv.gz"

COMPARABLE_CURVE = "lear_full_history"
HOLDOUT_YEAR = 2025

#: The holdout window's last month. Every visible year is cut here too.
LAST_MONTH = 9

LIKE_FOR_LIKE = RESULTS_DIR / "c17_like_for_like.csv"
SUMMARY = RESULTS_DIR / "c17_summary.json"


class SummaryError(RuntimeError):
    """The committed artefacts this reading needs are not all present."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# The per-day rows, visible and held out, in one frame
# ---------------------------------------------------------------------------


def _daily_frames() -> pd.DataFrame:
    if not VISIBLE_DAILY.exists():
        raise SummaryError(f"{VISIBLE_DAILY.name} is missing")
    visible = pd.read_csv(VISIBLE_DAILY)
    held = []
    for path in sorted(RESULTS_DIR.glob(HOLDOUT_DAILY_GLOB)):
        match = re.search(r"c17_holdout_(.+)_2025_daily", path.name)
        if match is None:  # pragma: no cover - the glob guarantees it
            continue
        frame = pd.read_csv(path)
        frame["zone"] = match.group(1)
        frame["year"] = HOLDOUT_YEAR
        held.append(frame)
    if not held:
        raise SummaryError(
            "no c17_holdout_*_2025_daily.csv.gz: the holdout evaluation's "
            "dispatch phase has not run in this working tree"
        )
    both = pd.concat([visible, *held], ignore_index=True)
    both = both[(both["curve"] == COMPARABLE_CURVE) & both["in_common_day_set"]]
    both = both.copy()
    both["market_day"] = pd.to_datetime(both["market_day"])
    both["month"] = both["market_day"].dt.month
    return both


def _aggregate(frame: pd.DataFrame) -> pd.DataFrame:
    """Capture, pooled MAE, spread and ordering, per (zone, year).

    Every column is a re-aggregation of committed per-day rows by the same
    definition C12/C13 use: capture is the ratio of summed cash to summed
    rolled oracle cash, the pooled MAE is the summed absolute error over the
    summed hour count, and ``error_over_headroom`` is that MAE over the mean
    realised daily spread.
    """
    rows: list[dict[str, Any]] = []
    for (zone, year), group in frame.groupby(["zone", "year"], sort=True):
        oracle_cash = float(group["oracle_cash"].sum())
        hours = float(group["n_hours"].sum())
        spread = float(group["realised_spread"].mean())
        mae = float(group["sum_abs_error"].sum()) / hours if hours else float("nan")
        defined = group[group["spearman_defined"] == 1]
        rows.append(
            {
                "zone": str(zone),
                "year": int(year),
                "n_days": int(len(group)),
                "capture": float(group["cash"].sum()) / oracle_cash if oracle_cash else float("nan"),
                "dispatch_cash_eur": float(group["cash"].sum()),
                "oracle_cash_eur": oracle_cash,
                "pooled_mae_eur_per_mwh": mae,
                "mean_realised_spread_eur_per_mwh": spread,
                "error_over_headroom": mae / spread if spread else float("nan"),
                "within_day_spearman_mean": float(defined["spearman"].mean())
                if len(defined) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def like_for_like() -> pd.DataFrame:
    """One row per (zone, year, basis): the full year, and January-September."""
    daily = _daily_frames()
    full = _aggregate(daily).assign(basis="full_window")
    jansep = _aggregate(daily[daily["month"] <= LAST_MONTH]).assign(
        basis="jan_sep_only"
    )
    table = pd.concat([full, jansep], ignore_index=True)
    return table.sort_values(["basis", "zone", "year"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# What the table says
# ---------------------------------------------------------------------------


def _verdicts(table: pd.DataFrame, basis: str) -> dict[str, Any]:
    """Per zone: is the holdout above every visible year on this basis?"""
    sub = table[table["basis"] == basis]
    wide = sub.pivot(index="zone", columns="year", values="capture")
    if HOLDOUT_YEAR not in wide.columns:
        raise SummaryError("the table carries no holdout year")
    visible_years = [y for y in wide.columns if y != HOLDOUT_YEAR]
    out: dict[str, Any] = {}
    for zone in wide.index:
        visible = wide.loc[zone, visible_years]
        held = float(wide.loc[zone, HOLDOUT_YEAR])
        out[str(zone)] = {
            "holdout": held,
            "visible_min": float(visible.min()),
            "visible_max": float(visible.max()),
            "verdict": (
                "above_every_visible_year" if held > visible.max()
                else "below_every_visible_year" if held < visible.min()
                else "inside_the_visible_range"
            ),
        }
    return out


def _direction_counts(table: pd.DataFrame, basis: str,
                      previous_year: int) -> dict[str, Any]:
    """How many zones moved which way against the year before, on this basis."""
    sub = table[table["basis"] == basis]
    counts: dict[str, Any] = {}
    for column in ("capture", "pooled_mae_eur_per_mwh", "error_over_headroom",
                   "within_day_spearman_mean", "mean_realised_spread_eur_per_mwh"):
        wide = sub.pivot(index="zone", columns="year", values=column)
        if previous_year not in wide.columns or HOLDOUT_YEAR not in wide.columns:
            continue
        delta = wide[HOLDOUT_YEAR] - wide[previous_year]
        counts[column] = {
            "n_zones_up": int((delta > 0).sum()),
            "n_zones_down": int((delta < 0).sum()),
            "n_zones": int(delta.notna().sum()),
        }
    return counts


def _store_facts() -> dict[str, Any]:
    frame = read_results()
    years = sorted({
        y for cell in frame["evaluation_years"].astype(str)
        for y in re.findall(r"\b(20\d{2})\b", cell)
    })
    return {
        "n_rows_in_results_csv": int(len(frame)),
        "n_runs_in_results_csv": int(frame["run_id"].nunique()),
        "evaluation_years_present": years,
        "holdout_year_present": str(HOLDOUT_YEAR) in years,
    }


def build_summary(table: pd.DataFrame) -> dict[str, Any]:
    held = table[(table["basis"] == "full_window") & (table["year"] == HOLDOUT_YEAR)]
    if held.empty:
        raise SummaryError("no holdout rows in the table")
    evaluation = json.loads(
        (RESULTS_DIR / "c17_holdout_2025_evaluation.json").read_text(encoding="utf-8")
    )
    lost = {
        zone: float(block["eur_per_mw_year_lost_vs_oracle"])
        for zone, block in evaluation["headline"].items()
    }
    full = _verdicts(table, "full_window")
    jansep = _verdicts(table, "jan_sep_only")
    return {
        "cycle": "C17",
        "phase": "summary",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "holdout_year": HOLDOUT_YEAR,
        "n_market_days": int(evaluation["window"]["n_days_in_cross_zone_basis"]),
        "window": {
            "first_market_day": evaluation["window"]["first_market_day"],
            "last_market_day": evaluation["window"]["last_market_day"],
        },
        "capture": {
            "min": float(held["capture"].min()),
            "max": float(held["capture"].max()),
            "min_zone": str(held.loc[held["capture"].idxmin(), "zone"]),
            "max_zone": str(held.loc[held["capture"].idxmax(), "zone"]),
            "band_pp": float((held["capture"].max() - held["capture"].min()) * 100),
        },
        "eur_per_mw_year_lost_vs_oracle": {
            "min": min(lost.values()),
            "max": max(lost.values()),
            "min_zone": min(lost, key=lambda z: lost[z]),
            "max_zone": max(lost, key=lambda z: lost[z]),
        },
        "against_the_visible_years": {
            "full_window_basis": {
                "n_zones_above_every_visible_year": sum(
                    1 for v in full.values()
                    if v["verdict"] == "above_every_visible_year"
                ),
                "per_zone": full,
            },
            "jan_sep_like_for_like_basis": {
                "n_zones_above_every_visible_year": sum(
                    1 for v in jansep.values()
                    if v["verdict"] == "above_every_visible_year"
                ),
                "per_zone": jansep,
                "why": (
                    "the holdout window is 273 days ending 2025-09-30, so every "
                    "visible year is cut to January-September before the "
                    "comparison. This is the honest basis; the full-window one "
                    "is reported beside it so the correction is visible."
                ),
            },
        },
        "direction_against_2024": {
            "full_window_basis": _direction_counts(table, "full_window", 2024),
            "jan_sep_like_for_like_basis": _direction_counts(
                table, "jan_sep_only", 2024
            ),
        },
        # The exact strings the README quotes. They live here, rounded, so that
        # C20's claims phase binds a README number to an artefact *field*
        # rather than to a number somebody typed: the file decides what the
        # sentence may say, and a reworded sentence fails the gate.
        "readme_display": {
            "capture_min": f"{held['capture'].min():.3f}",
            "capture_max": f"{held['capture'].max():.3f}",
            "capture_min_zone": str(held.loc[held["capture"].idxmin(), "zone"]),
            "capture_max_zone": str(held.loc[held["capture"].idxmax(), "zone"]),
            "lost_min_eur_per_mw_year": round(min(lost.values())),
            "lost_max_eur_per_mw_year": round(max(lost.values())),
            "n_market_days": int(evaluation["window"]["n_days_in_cross_zone_basis"]),
            "n_rows_in_results_csv": _store_facts()["n_rows_in_results_csv"],
            "n_zones_above_every_visible_year_jan_sep": sum(
                1 for v in jansep.values()
                if v["verdict"] == "above_every_visible_year"
            ),
        },
        "store": _store_facts(),
        "invariant_flags": int(evaluation["n_invariant_flags"]),
        "reads": [
            VISIBLE_DAILY.name,
            HOLDOUT_DAILY_GLOB,
            "c17_holdout_2025_evaluation.json",
            "results.csv",
        ],
        "writes_no_result_rows": True,
        "note": (
            "a re-aggregation of committed per-day rows. Nothing is re-fitted "
            "and no model, feature, battery parameter or metric definition is "
            "touched, which is what the pre-registration's stop rule forbids "
            "after the first 2025 number."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    table = like_for_like()
    table.to_csv(LIKE_FOR_LIKE, index=False, float_format="%.10g")
    summary = build_summary(table)
    with SUMMARY.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")

    capture = summary["capture"]
    print(f"holdout capture {capture['min']:.4f} ({capture['min_zone']}) .. "
          f"{capture['max']:.4f} ({capture['max_zone']})")
    for basis, label in (("full_window_basis", "full window"),
                         ("jan_sep_like_for_like_basis", "Jan-Sep like for like")):
        block = summary["against_the_visible_years"][basis]
        print(f"  above every visible year, {label}: "
              f"{block['n_zones_above_every_visible_year']} of {len(block['per_zone'])}")
    for basis in ("full_window_basis", "jan_sep_like_for_like_basis"):
        counts = summary["direction_against_2024"][basis]
        if not counts:
            continue
        print(f"  against 2024, {basis}:")
        for metric, block in counts.items():
            print(f"    {metric:34s} up in {block['n_zones_up']} of {block['n_zones']}")
    print(f"  -> {LIKE_FOR_LIKE}")
    print(f"  -> {SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
