"""CLI: the C6 run — commit-then-settle, all three curves, DE-LU. **CHECKPOINT B.**

    python -m backtest.run_c6_curves                  # DE-LU, 2024, figures on
    python -m backtest.run_c6_curves --no-figures     # numbers only
    python -m backtest.run_c6_curves --no-milp-variant

Writes, per zone, into ``backtest/results/``:

* ``c6_curves_<ZONE>_<YEARS>_daily.csv`` — one row per (curve, market day): the
  settled cash, both oracle ceilings and the two capture ratios. The artefact
  C11/C12 aggregate and the one a reviewer can recompute from.
* ``c6_curves_<ZONE>_<YEARS>_schedule.csv.gz`` — every dispatched hour of every
  curve, with the decision price *and* the realised price side by side, so the
  commit-then-settle split is visible in the data and not just in the code.
* ``c6_curves_<ZONE>_<YEARS>_summary.json`` — the pooled comparison, every
  invariant result, the NOTE C4-02 measurement, the FLAG C5-01 restatement, and
  the git SHA plus config hash.
* ``docs/figures/c6_dispatch_week_<ZONE>_<START>.png`` — **Checkpoint B's own
  required output**: a week of dispatch drawn against the price plot, three
  curves, so a human can eyeball one zone end to end before anything scales out
  to nine.

What this cycle adds to C5
--------------------------
C5 built the LP, the rolling horizon and the settlement, and ran the oracle
curve only. C6 runs the **model** (LEAR, from C4's committed walk-forward
artefact) and the **naive** floor through the same machinery, and checks the
ordering PLAN.md requires:

* **Pooled**: ``oracle >= model >= naive``, over the day set every curve
  dispatched. CLAUDE.md states the ``model >= naive`` half as an average and not
  a per-day claim, so the per-day win rate is reported beside it.
* **Per day, exact**: ``value(curve @ realised) <= value(same-start oracle)`` on
  **every** dispatched day, for both the model and the naive curve. The
  same-start oracle is re-solved from the candidate run's own opening SoC against
  its own mark, which is what makes the bound a theorem rather than a hope; see
  ``docs/battery_lp.md`` and :mod:`dispatch.curves`.
* **No read-backs**: no non-oracle run may report a valuation taken at its own
  decision prices. Checked from the schedules, not from the flag alone.
* **"Doing nothing is feasible"**, asserted about the problem it is a theorem
  about. C5 asserts ``value_added >= 0`` on the oracle, where the decision prices
  *are* the realised prices. For a forecast curve that does not transfer — a
  schedule frozen on a wrong forecast can lose money at realised prices, which is
  the quantity this project measures — so the theorem is asserted on the decision
  prices for every curve, C5's realised-price form stays asserted unchanged on
  the oracle, and the realised-price losses are *reported* as a result. See
  FINDING C6-A in ``PROGRESS.md``.

The forecast is read from C4's committed predictions artefact rather than
re-fitted, so this cycle dispatches exactly the forecast that was scored in C4
and the two cycles cannot drift apart.

NOTE C4-02, decided here
------------------------
One hour a year has no LEAR forecast under the committed ``nan_policy="decline"``
(the autumn DST hour whose 24-hour lag the gate-closure mask blanks), and the LP
needs a complete vector. C5 built the mechanism — a day with a hole is skipped
and counted, never patched — and left C6 the choice. **This cycle excludes the
day and reports it excluded**, and pools every curve over the common day set so
that the exclusion cannot quietly compare a 366-day total against a 365-day one.
The alternative is measured rather than argued away: ``--measure-impute`` re-runs
that single fold under ``nan_policy="impute"``, dispatches the day from the
imputed vector, and records what the excluded day would have been worth. See the
PROGRESS.md C6 entry for the reasoning and the number.

FLAG C5-01 is restated, not decided
-----------------------------------
Simultaneous charge/discharge at deeply negative prices is still open (a human
picks MILP / stated-limitation / single-inverter constraint). The committed pure
LP is the default here, unchanged, and the MILP variant is run across all three
curves so the review can see whether the *capture ratio* — the actual result —
moves at all under the alternative. It does not materially; the number is in the
summary.

Sealed-holdout years are refused by :mod:`data.holdout` before a price file is
opened. Nothing here reads 2025.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

import numpy as np
import pandas as pd

from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.run_c5_oracle_lp import (
    check_day_lengths,
    check_value_added_non_negative,
    load_realised,
    simultaneity_flag,
)
from data.config import REPO_ROOT, config_hash, load_battery_config, load_zones
from data.holdout import assert_not_sealed
from dispatch.battery import BatterySpec
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
    pooled_comparison,
    report_realised_losses,
    same_start_oracle,
)
from dispatch.rolling import RollingResult, run_rolling_dispatch
from forecast.timing import market_days, zone_timezone

#: C4's committed artefact, and the columns in it this cycle dispatches.
PREDICTIONS_TEMPLATE = "c4_lear_{zone}_{years}_predictions.csv.gz"
MODEL_COLUMN = "y_pred_lear_aic"
NAIVE_COLUMN = "y_pred_naive_last_week"
TRUTH_COLUMN = "y_true"

FIGURE_DIR = REPO_ROOT / "docs" / "figures"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=["DE-LU"], help="zone keys")
    parser.add_argument("--years", nargs="*", type=int, default=[2024],
                        help="market-delivery years to dispatch (2025 is sealed)")
    parser.add_argument("--no-milp-variant", action="store_true",
                        help="skip the forbid_simultaneous MILP comparison")
    parser.add_argument("--no-figures", action="store_true",
                        help="skip the Checkpoint B dispatch-week figures")
    parser.add_argument("--measure-impute", action="store_true", default=True,
                        help="re-run the one declined fold under nan_policy='impute' "
                             "to price the NOTE C4-02 decision")
    parser.add_argument("--no-measure-impute", dest="measure_impute",
                        action="store_false")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# curves, from C4's committed artefact
# ---------------------------------------------------------------------------


def load_prediction_curves(
    zone_key: str, years: list[int], realised: pd.Series
) -> tuple[dict[str, Curve], dict[str, Any]]:
    """Read C4's predictions artefact into decision-price curves, with alignment checks.

    Three things are asserted here rather than assumed, because each one would
    show up as skill if it were wrong:

    * the artefact's ``y_true`` matches the realised series this run will settle
      against, hour for hour (an off-by-one index is a leak that looks like a
      model);
    * every forecast timestamp exists in the realised series;
    * the evaluation hours cover whole market days, so a day is never dispatched
      from a partial forecast vector.
    """
    tag = "-".join(str(y) for y in years)
    path = RESULTS_DIR / PREDICTIONS_TEMPLATE.format(zone=zone_key, years=tag)
    if not path.exists():
        raise CurveError(
            f"C4's predictions artefact is missing: {path}. C6 dispatches the "
            f"forecast C4 scored; it does not re-fit one."
        )
    frame = pd.read_csv(path)
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
    frame = frame.set_index(index).sort_index()
    for column in (TRUTH_COLUMN, MODEL_COLUMN, NAIVE_COLUMN):
        if column not in frame.columns:
            raise CurveError(f"{path.name} has no column {column!r}")

    aligned_realised = realised.reindex(frame.index)
    if aligned_realised.isna().any():
        n = int(aligned_realised.isna().sum())
        raise CurveError(
            f"{n} forecast timestamp(s) have no realised price in the loaded "
            f"series — the artefact and the price cache disagree on the grid."
        )
    truth_gap = float(
        np.nanmax(
            np.abs(
                frame[TRUTH_COLUMN].to_numpy(dtype=float)
                - aligned_realised.to_numpy(dtype=float)
            )
        )
    )
    if truth_gap > 1e-6:
        raise CurveError(
            f"{path.name}'s y_true differs from the realised price series by up to "
            f"{truth_gap:.6g} EUR/MWh. One of the two is not what C4 scored."
        )

    curves = {
        "model": Curve(
            name="model",
            prices=frame[MODEL_COLUMN].astype(float),
            source=f"{path.name}:{MODEL_COLUMN} (LEAR, committed selector)",
        ),
        "naive": Curve(
            name="naive",
            prices=frame[NAIVE_COLUMN].astype(float),
            source=f"{path.name}:{NAIVE_COLUMN} (same hour last week)",
        ),
    }
    report = {
        "artefact": path.name,
        "n_hours": int(len(frame)),
        "first_ts_utc": frame.index[0].isoformat(),
        "last_ts_utc": frame.index[-1].isoformat(),
        "y_true_matches_realised": True,
        "max_y_true_vs_realised_gap": round(truth_gap, 10),
        "curves": {name: curve.as_dict() for name, curve in curves.items()},
        "alignment": {
            name: assert_curve_aligns(curve, realised) for name, curve in curves.items()
        },
    }
    return curves, report


# ---------------------------------------------------------------------------
# the per-curve run
# ---------------------------------------------------------------------------


def dispatch_curve(
    zone_key: str,
    realised: pd.Series,
    spec: BatterySpec,
    curve: Curve | None,
    name: str,
    wanted_days: set[dt.date],
    roll_kwargs: dict[str, Any],
) -> RollingResult:
    """One curve, rolled across ``wanted_days``, settled at realised prices.

    ``curve=None`` is the oracle: ``run_rolling_dispatch`` then uses the realised
    series as its own decision prices, which is the one legitimate case, and
    stamps the valuations accordingly.
    """
    return run_rolling_dispatch(
        zone_key,
        realised,
        spec,
        decision_prices=None if curve is None else curve.prices,
        curve=name,
        days=wanted_days,
        **roll_kwargs,
    )


def curve_block(
    result: RollingResult,
    rolled_oracle: RollingResult,
    spec: BatterySpec,
    zone_key: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Every invariant and every capture number for one curve."""
    is_oracle = result is rolled_oracle
    bound = same_start_oracle(result, spec)
    frame = capture_frame(result, rolled_oracle, bound)
    invariants = {
        "day_lengths_match_local_calendar": check_day_lengths(result, zone_key),
        "settlement_is_not_a_decision_price_readback":
            assert_settlement_is_not_a_readback(result),
        # The theorem, stated about the problem it is a theorem about (see
        # dispatch.curves.check_decision_value_added_non_negative).
        "decision_value_added_non_negative":
            check_decision_value_added_non_negative(result, spec),
    }
    if is_oracle:
        # For the oracle the decision prices ARE the realised prices, so C5's
        # realised-price form of the same statement must also hold, and it stays
        # asserted here exactly as C5 asserted it.
        invariants["value_added_non_negative_at_realised"] = (
            check_value_added_non_negative(result)
        )
    else:
        invariants["same_start_oracle_dominates_every_day"] = check_per_day_dominance(
            result, bound
        )
    block = {
        "summary": result.summary(),
        "invariants": invariants,
        # Reported, not asserted: a forecast schedule may lose money at realised
        # prices. For the oracle this is empty by the theorem above, which is
        # itself worth persisting rather than assuming.
        "realised_losses": report_realised_losses(result),
        "capture": capture_summary(frame),
        "simultaneity": simultaneity_flag(result, spec),
        "skipped_days": [s.as_dict() for s in result.skipped],
    }
    return block, frame


# ---------------------------------------------------------------------------
# NOTE C4-02: what the excluded day would have been worth
# ---------------------------------------------------------------------------


def measure_impute_alternative(
    zone_key: str,
    realised: pd.Series,
    spec: BatterySpec,
    skipped_days: list[dt.date],
    roll_kwargs: dict[str, Any],
    model_result: RollingResult,
) -> dict[str, Any]:
    """Price the NOTE C4-02 decision: dispatch the declined day from ``impute``.

    Re-runs **only the skipped folds** under ``nan_policy="impute"`` — one fold a
    year, so this costs one LEAR fit rather than 366 — then dispatches those days
    from the imputed vector, opening at the SoC the committed model run actually
    carried into them. The output is what excluding the day costs (or saves), in
    euros, so the choice this cycle made is a measured one.
    """
    if not skipped_days:
        return {"applicable": False, "reason": "no day was skipped for a forecast hole"}
    # Imported here: this is a measurement of the alternative, not part of the
    # dispatch path, and C6 should not pay the forecast stack's import cost when
    # --no-measure-impute is passed.
    from backtest.walk_forward import WalkForwardSpec, run_walk_forward
    from forecast.features import build_features
    from forecast.lear import LearSpec, lear_factory
    from data.prices import load_zone_series

    matrix = build_features(load_zone_series(zone_key), zone_key)
    run = run_walk_forward(
        matrix,
        lear_factory(LearSpec(selector="aic", nan_policy="impute"), name="lear_impute"),
        skipped_days,
        WalkForwardSpec(refit_every_days=1, min_train_days=365),
    )
    imputed = run.predictions["y_pred"].astype(float)
    if imputed.isna().any():
        return {
            "applicable": True,
            "holds": False,
            "reason": "the impute variant still has a hole on the skipped day",
        }
    # Open at the SoC the committed model run actually carried into the day.
    before = [d for d in model_result.days if d < min(skipped_days)]
    soc_in = (
        model_result.schedules[max(before)].soc_end_mwh
        if before
        else spec.initial_soc_mwh
    )
    run_days = set(skipped_days)
    patched = run_rolling_dispatch(
        zone_key,
        realised,
        spec,
        decision_prices=imputed,
        curve="model_impute_one_day",
        days=run_days,
        initial_soc_mwh=soc_in,
        **roll_kwargs,
    )
    bound = same_start_oracle(patched, spec)
    dominance = check_per_day_dominance(patched, bound)
    return {
        "applicable": True,
        "decision_taken": "exclude the day and report it excluded",
        "days": [d.isoformat() for d in sorted(skipped_days)],
        "n_days": len(skipped_days),
        "soc_carried_in_mwh": round(soc_in, 6),
        "impute_run": {
            "n_days_dispatched": patched.n_days,
            "cash_eur": round(patched.total_cash_eur, 4),
            "value_added_eur": round(patched.total_value_added_eur, 4),
            "same_start_oracle_value_added_eur": round(
                float(sum(v.value_added_eur for v in bound.values())), 4
            ),
            "capture_same_start": capture_summary(
                capture_frame(patched, patched, bound)
            ).get("pooled_capture_same_start"),
            "per_day_dominance": dominance,
        },
        "note": (
            "What the excluded day would have contributed had it been dispatched "
            "from the imputed forecast vector. Reported so the exclusion is a "
            "measured choice; the committed run still excludes it, and every "
            "pooled number is computed over the common day set."
        ),
    }


# ---------------------------------------------------------------------------
# Checkpoint B's figure: a week of dispatch against the price plot
# ---------------------------------------------------------------------------

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
GRID = "#d8d7d2"
C_REALISED = "#0b0b0b"
C_ORACLE = "#2a78d6"
C_MODEL = "#e08a1e"
C_NAIVE = "#8a8a86"
ZERO = "#e34948"
CURVE_COLOUR = {"oracle": C_ORACLE, "model": C_MODEL, "naive": C_NAIVE}


def _pick_weeks(
    frames: dict[str, pd.DataFrame], results: dict[str, RollingResult]
) -> dict[str, dt.date]:
    """Three weeks worth eyeballing, chosen by rule rather than by taste.

    * ``typical`` — the week whose mean daily spread is closest to the year's.
    * ``high_spread`` — the week with the most oracle value. Where the money is.
    * ``worst_capture`` — the week containing the model's worst same-start capture
      day. If the chain is wrong anywhere, it is most visible here.
    """
    oracle_daily = frames["oracle"].copy()
    oracle_daily["day"] = pd.to_datetime(oracle_daily["market_day"]).dt.date
    oracle_daily["week"] = pd.to_datetime(oracle_daily["market_day"]).dt.to_period("W")
    by_week = oracle_daily.groupby("week").agg(
        value=("cash_eur", "sum"),
        spread=("realised_spread", "mean"),
        n=("market_day", "size"),
        start=("day", "min"),
    )
    full = by_week[by_week["n"] == 7]
    if full.empty:
        full = by_week
    picks: dict[str, dt.date] = {
        "typical": full.iloc[
            int((full["spread"] - oracle_daily["realised_spread"].mean()).abs().argmin())
        ]["start"],
        "high_spread": full.iloc[int(full["value"].argmax())]["start"],
    }
    model = frames["model"]
    defined = model[np.isfinite(model["capture_same_start"].to_numpy(dtype=float))]
    if not defined.empty:
        worst_day = pd.to_datetime(
            defined.loc[defined["capture_same_start"].idxmin(), "market_day"]
        ).date()
        picks["worst_capture"] = worst_day - dt.timedelta(days=worst_day.weekday())
    return picks


def plot_dispatch_week(
    zone_key: str,
    start: dt.date,
    results: dict[str, RollingResult],
    curves: dict[str, Curve],
    label: str,
    frames: dict[str, pd.DataFrame],
) -> Any:
    """Checkpoint B's figure: one week — prices, inventory, and cumulative cash.

    Three panels on one x-axis, because the question a reviewer is actually
    asking at Checkpoint B is "did it buy low and sell high, and where did
    forecast error make it trade at the wrong hour":

    * **prices** — realised against both forecasts, so the error is visible as
      the gap that causes everything below;
    * **SoC** — the inventory each curve actually carried, including across
      midnight, which is where a daily reset would show up as a sawtooth;
    * **cumulative settled cash** — every curve's money at *realised* prices,
      running. Three near-parallel lines that separate on particular days is the
      end-to-end result in one panel, and it is far easier to read than three
      overlapping ±1 MW instruction traces.

    Prices and SoC are drawn as steps: an hourly product is flat across its hour,
    and a smooth line through hour centres would imply a ramp the auction never
    cleared. The cash panel is settled cash only — marks on closing inventory are
    excluded, so what is plotted is money, not a model output.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_SOFT,
            "axes.titlecolor": INK,
            "text.color": INK,
            "xtick.color": INK_SOFT,
            "ytick.color": INK_SOFT,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 9,
            "figure.dpi": 130,
        }
    )
    days = [start + dt.timedelta(days=i) for i in range(7)]
    oracle = results["oracle"]
    present = [d for d in days if d in oracle.schedules]
    if not present:
        return None
    index = pd.DatetimeIndex(
        np.concatenate([oracle.schedules[d].index.to_numpy() for d in present])
    ).tz_convert("UTC")
    realised = pd.Series(
        np.concatenate([oracle.realised_prices[d] for d in present]), index=index
    )

    fig, axes = plt.subplots(
        3, 1, figsize=(11, 8.0), sharex=True, height_ratios=[3, 2, 2],
        constrained_layout=True,
    )
    ax_p, ax_s, ax_c = axes

    ax_p.axhline(0, color=ZERO, linewidth=0.8, zorder=1)
    ax_p.step(realised.index, realised.to_numpy(), where="post", color=C_REALISED,
              linewidth=1.6, label="realised (= oracle decision price)", zorder=4)
    for name in ("model", "naive"):
        curve = curves[name].prices.reindex(index)
        ax_p.step(index, curve.to_numpy(dtype=float), where="post",
                  color=CURVE_COLOUR[name], linewidth=1.1, alpha=0.95,
                  label=f"{name} forecast (decision price)", zorder=3)
    ax_p.set_ylabel("EUR/MWh")
    ax_p.legend(loc="upper left", frameon=False, ncols=3, fontsize=8)

    # The week's own numbers go in the title, not a box over the data.
    per_curve = {}
    for name in ("oracle", "model", "naive"):
        block = frames[name]
        block = block[block["market_day"].isin([d.isoformat() for d in present])]
        per_curve[name] = float(block["cash_eur"].sum()) if not block.empty else 0.0
    shares = "   ".join(
        f"{name} {per_curve[name]:,.0f} EUR"
        + (
            f" ({per_curve[name] / per_curve['oracle']:.0%})"
            if name != "oracle" and per_curve["oracle"]
            else ""
        )
        for name in ("oracle", "model", "naive")
    )
    ax_p.set_title(
        f"{zone_key} — a week of dispatch ({label}), {present[0]} .. {present[-1]}\n"
        f"commit on the decision price, settle at realised   |   {shares}",
        loc="left", fontsize=10,
    )

    spec = results["oracle"].spec
    for name, result in results.items():
        soc_parts, cash_parts, idx_parts = [], [], []
        for day in present:
            schedule = result.schedules.get(day)
            if schedule is None:
                continue
            dt_h = schedule.interval_hours
            realised_day = np.asarray(result.realised_prices[day], dtype=float)
            hourly_cash = dt_h * (
                realised_day * schedule.discharge_mw
                - realised_day * schedule.charge_mw
                - spec.throughput_cost_eur_per_mwh * schedule.discharge_mw
            )
            soc_parts.append(schedule.soc_mwh)
            cash_parts.append(hourly_cash)
            idx_parts.append(schedule.index.to_numpy())
        if not soc_parts:
            continue
        idx = pd.DatetimeIndex(np.concatenate(idx_parts)).tz_convert("UTC")
        ax_s.step(idx, np.concatenate(soc_parts), where="post",
                  color=CURVE_COLOUR[name], linewidth=1.3, label=name)
        ax_c.step(idx, np.cumsum(np.concatenate(cash_parts)), where="post",
                  color=CURVE_COLOUR[name], linewidth=1.5, label=name)
    ax_s.set_ylabel("SoC, MWh")
    ax_s.set_ylim(-0.05 * spec.energy_mwh, 1.30 * spec.energy_mwh)
    ax_s.legend(loc="upper left", frameon=False, ncols=3, fontsize=8)
    ax_c.axhline(0, color=GRID, linewidth=0.8)
    ax_c.set_ylabel("cumulative settled\ncash, EUR")
    ax_c.set_xlabel("UTC")
    ax_c.legend(loc="upper left", frameon=False, ncols=3, fontsize=8)
    ax_c.xaxis.set_major_locator(mdates.DayLocator())
    ax_c.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    fig.text(0.005, 0.002, "Data: Energy-Charts (Fraunhofer ISE), CC BY 4.0",
             fontsize=7, color=INK_SOFT)

    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / f"c6_dispatch_week_{zone_key}_{present[0].isoformat()}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


def run_zone(zone_key: str, args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_battery_config()
    terminal = cfg.get("terminal") or {}
    spec = BatterySpec.from_config(cfg)
    tz = zone_timezone(zone_key)
    years = list(args.years)
    print(f"\n=== {zone_key} — commit-then-settle, three curves, years {years} ===")
    print(f"  battery: {spec.power_mw} MW / {spec.energy_mwh} MWh "
          f"({spec.duration_hours:g}h), eta_leg={spec.eta_leg:.6f}, "
          f"k={spec.throughput_cost_eur_per_mwh} EUR/MWh discharged, "
          f"terminal {spec.terminal_mode}")

    realised = load_realised(zone_key, years)
    print(f"  realised: {len(realised)} hours "
          f"{realised.index[0].isoformat()} .. {realised.index[-1].isoformat()}")

    curves, curve_report = load_prediction_curves(zone_key, years, realised)
    print(f"  curves from {curve_report['artefact']}: "
          + ", ".join(
              f"{name} ({curve.n_missing} missing hour(s))"
              for name, curve in curves.items()
          ))

    roll_kwargs = dict(
        trailing_days=int(terminal.get("trailing_days", 7)),
        trailing_quantile=float(terminal.get("trailing_quantile", 0.5)),
        min_trailing_days=int(terminal.get("min_trailing_days", 1)),
        tz=tz,
    )
    # The evaluation days are exactly the market days C4 forecast, so the
    # dispatch window and the forecast window cannot drift apart.
    forecast_days = set(
        market_days(pd.DatetimeIndex(curves["model"].prices.index), tz).tolist()
    )
    labels = pd.Series(realised.index).dt.tz_convert(tz).dt.date
    wanted_days = {d for d in labels if d.year in set(years)} & forecast_days
    print(f"  dispatching {len(wanted_days)} market days "
          f"{min(wanted_days)} .. {max(wanted_days)}")

    results: dict[str, RollingResult] = {
        "oracle": dispatch_curve(
            zone_key, realised, spec, None, "oracle", wanted_days, roll_kwargs
        ),
        "model": dispatch_curve(
            zone_key, realised, spec, curves["model"], "model", wanted_days, roll_kwargs
        ),
        "naive": dispatch_curve(
            zone_key, realised, spec, curves["naive"], "naive", wanted_days, roll_kwargs
        ),
    }
    for name, result in results.items():
        print(f"  {name:<7} dispatched {result.n_days:>3} day(s), "
              f"skipped {len(result.skipped)}, "
              f"cash {result.total_cash_eur:>12,.2f} EUR "
              f"({result.summary()['cash_eur_per_mw_year']:>9,.0f} EUR/MW/yr)")
        for skip in result.skipped:
            print(f"    SKIP {skip.day} [{skip.reason}] {skip.detail}")

    blocks: dict[str, Any] = {}
    frames: dict[str, pd.DataFrame] = {}
    for name, result in results.items():
        blocks[name], frames[name] = curve_block(
            result, results["oracle"], spec, zone_key
        )

    pooled = pooled_comparison(results)
    print(f"\n  pooled over {pooled['n_common_days']} common day(s):")
    for check, outcome in pooled["checks"].items():
        print(f"    [{'OK ' if outcome['holds'] else 'FAIL'}] {check} "
              f"margin {outcome['margin_eur']:,.2f} EUR")
    print(f"    capture ratio (model cash / oracle cash) "
          f"{pooled['capture_ratio_rolled_cash']:.4f}; "
          f"naive {pooled['naive_capture_ratio_rolled_cash']:.4f}; "
          f"EUR lost to forecast error {pooled['eur_lost_to_forecast_error']:,.0f}")
    print(f"    model beats naive on {pooled['per_day_model_beats_naive_days']} of "
          f"{pooled['n_common_days']} days "
          f"({pooled['per_day_model_beats_naive_share']:.1%})")
    for name in ("model", "naive"):
        capture = blocks[name]["capture"]
        print(f"    {name:<7} pooled same-start capture "
              f"{capture['pooled_capture_same_start']:.4f}, "
              f"median daily "
              f"{capture['quantiles_daily_capture_same_start'].get('p50')}")
    print("  committed schedules that lost money at realised prices "
          "(reported, not an invariant):")
    for name, block in blocks.items():
        loss = block["realised_losses"]
        print(f"    {name:<7} {loss['n_days_value_added_negative_at_realised']:>3} of "
              f"{loss['n_days_checked']} day(s), "
              f"{loss['total_eur']:>10,.2f} EUR in total")

    invariant_failures = [
        f"{name}.{check}"
        for name, block in blocks.items()
        for check, outcome in block["invariants"].items()
        if not outcome.get("holds")
    ]
    if not pooled["holds"]:
        invariant_failures += [
            f"pooled.{check}"
            for check, outcome in pooled["checks"].items()
            if not outcome["holds"]
        ]

    out: dict[str, Any] = {
        "cycle": "C6",
        "checkpoint": "B",
        "zone": zone_key,
        "years": years,
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "battery_config": cfg,
        "curve_sources": curve_report,
        "curves": blocks,
        "pooled_comparison": pooled,
        "invariant_failures": invariant_failures,
    }

    skipped_for_holes = sorted(
        {
            s.day
            for s in results["model"].skipped
            if s.reason == "incomplete"
        }
    )
    out["note_c4_02"] = (
        measure_impute_alternative(
            zone_key, realised, spec, skipped_for_holes, roll_kwargs, results["model"]
        )
        if args.measure_impute
        else {"applicable": bool(skipped_for_holes), "measured": False}
    )
    if out["note_c4_02"].get("applicable") and out["note_c4_02"].get("impute_run"):
        print(f"\n  NOTE C4-02: excluded {out['note_c4_02']['n_days']} day(s) "
              f"{out['note_c4_02']['days']}; dispatching them from the imputed "
              f"forecast would have earned "
              f"{out['note_c4_02']['impute_run']['cash_eur']:,.2f} EUR "
              f"(capture {out['note_c4_02']['impute_run']['capture_same_start']})")

    if not args.no_milp_variant:
        print("\n  MILP variant (forbid_simultaneous=True), all three curves — "
              "FLAG C5-01 material, default unchanged ...")
        milp_spec = BatterySpec.from_config(cfg, forbid_simultaneous=True)
        milp_results = {
            name: dispatch_curve(
                zone_key,
                realised,
                milp_spec,
                None if name == "oracle" else curves[name],
                name,
                wanted_days,
                roll_kwargs,
            )
            for name in ("oracle", "model", "naive")
        }
        milp_pooled = pooled_comparison(milp_results)
        out["milp_variant"] = {
            "pooled_comparison": milp_pooled,
            "n_days_with_simultaneity": {
                name: result.n_simultaneity_days
                for name, result in milp_results.items()
            },
            "capture_ratio_shift_vs_lp": round(
                (milp_pooled["capture_ratio_rolled_cash"] or 0)
                - (pooled["capture_ratio_rolled_cash"] or 0),
                6,
            ),
            "cash_gap_vs_lp_eur": {
                name: round(
                    results[name].total_cash_eur - milp_results[name].total_cash_eur, 2
                )
                for name in milp_results
            },
            "no_simultaneity_remains": {
                "holds": all(
                    result.n_simultaneity_days == 0 for result in milp_results.values()
                )
            },
            "note": (
                "FLAG C5-01 is restated, not decided: the committed default is "
                "still the pure LP. This measures whether the *result* — the "
                "capture ratio — moves under the alternative."
            ),
        }
        print(f"    capture ratio under MILP "
              f"{milp_pooled['capture_ratio_rolled_cash']:.4f} "
              f"(shift {out['milp_variant']['capture_ratio_shift_vs_lp']:+.6f}); "
              f"simultaneity intervals remaining: "
              f"{out['milp_variant']['no_simultaneity_remains']['holds']}")

    # -- artefacts ---------------------------------------------------------
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{zone_key}_{'-'.join(str(y) for y in years)}"
    daily = pd.concat(frames.values(), ignore_index=True)
    daily_path = RESULTS_DIR / f"c6_curves_{tag}_daily.csv"
    daily.to_csv(daily_path, index=False, float_format="%.6f")

    schedule_parts = []
    for name, result in results.items():
        block = result.schedule_frame()
        if not block.empty:
            block["curve"] = name
            schedule_parts.append(block)
    schedule_path = RESULTS_DIR / f"c6_curves_{tag}_schedule.csv.gz"
    pd.concat(schedule_parts).to_csv(schedule_path, float_format="%.8f")

    figures: list[str] = []
    if not args.no_figures:
        for label, start in _pick_weeks(frames, results).items():
            path = plot_dispatch_week(
                zone_key, start, results, curves, label, frames
            )
            if path is not None:
                figures.append(str(path.relative_to(REPO_ROOT)))
                print(f"  wrote {path.relative_to(REPO_ROOT)} "
                      f"({path.stat().st_size / 1024:.0f} KiB) [{label}]")
    out["figures"] = figures

    summary_path = RESULTS_DIR / f"c6_curves_{tag}_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
        fh.write("\n")
    for path in (daily_path, schedule_path, summary_path):
        print(f"  wrote {path.relative_to(REPO_ROOT)} "
              f"({path.stat().st_size / 1024:.0f} KiB)")

    if invariant_failures:
        raise SystemExit(
            f"C6 invariant(s) failed for {zone_key}: {invariant_failures}. "
            f"See {summary_path.name}; this is a FLAG, not something to work around."
        )
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    zones = load_zones()
    unknown = [z for z in args.zones if z not in zones]
    if unknown:
        raise SystemExit(f"unknown zone key(s): {unknown}")
    for year in args.years:
        assert_not_sealed(year, "run the C6 three-curve dispatch")
    for zone_key in args.zones:
        run_zone(zone_key, args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
