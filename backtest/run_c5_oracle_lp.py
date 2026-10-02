"""CLI: the C5 oracle dispatch run — battery LP v1, DE-LU, perfect foresight only.

    python -m backtest.run_c5_oracle_lp                     # DE-LU, 2024
    python -m backtest.run_c5_oracle_lp --no-milp-variant    # skip the MILP compare
    python -m backtest.run_c5_oracle_lp --no-per-year        # skip 2019-2023 context

Writes, per zone, into ``backtest/results/``:

* ``c5_oracle_<ZONE>_<YEARS>_daily.csv`` — one row per dispatched market day:
  opening/closing SoC, the trailing mark, cash, the three value fields, energy in
  and out, and the simultaneity count. This is what C11/C12 aggregate.
* ``c5_oracle_<ZONE>_<YEARS>_schedule.csv.gz`` — every dispatched hour, with the
  realised price beside the instruction.
* ``c5_oracle_<ZONE>_<YEARS>_summary.json`` — the run summary, the invariant
  results, the simultaneity FLAG material, the MILP comparison, and the git SHA
  plus config hash.

**This is the oracle curve only**, as PLAN.md scopes C5: the decision prices *are*
the realised prices, so the LP's objective and the settlement coincide. They still
go through :func:`dispatch.battery.value_schedule` separately, and every valuation
is stamped ``prices_are_decision_prices``, because C6 adds the forecast and naive
curves through the same code and the one thing that must not happen then is an
objective value reported as a result.

The invariants this run checks every day
----------------------------------------
* ``value_added >= 0`` — standing still is feasible, so the optimum cannot lose.
* The solver's objective equals an independent recomputation of cash plus the
  terminal mark (asserted inside :func:`dispatch.battery.solve_day`, every solve).
* **Perfect foresight dominates**: on a sampled subset of days, a schedule
  committed against a deliberately wrong price vector, settled at realised prices
  from the same opening SoC, never beats the oracle. This is CLAUDE.md's per-day
  invariant; the oracle-vs-model-vs-naive version of it is C6's, because there is
  no model curve yet.
* Every dispatched day's hour count matches its local calendar length (23/24/25).

The two-stage upper bound and why only part of it belongs to C5 is set out in
``docs/battery_lp.md``.

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
from data.config import REPO_ROOT, config_hash, load_battery_config, load_zones
from data.energy_charts import PRICE_COLUMN
from data.holdout import assert_not_sealed
from data.prices import load_zone_series
from dispatch.battery import (
    BatterySpec,
    assert_oracle_dominates,
    solve_day,
    value_schedule,
)
from dispatch.rolling import RollingResult, run_rolling_dispatch
from forecast.timing import zone_timezone


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=["DE-LU"], help="zone keys")
    parser.add_argument(
        "--years",
        nargs="*",
        type=int,
        default=[2024],
        help="market-delivery years to dispatch (2025 is sealed)",
    )
    parser.add_argument(
        "--no-milp-variant",
        action="store_true",
        help="skip the forbid_simultaneous MILP comparison",
    )
    parser.add_argument(
        "--no-per-year",
        action="store_true",
        help="skip the descriptive per-year oracle table over the cached years",
    )
    parser.add_argument(
        "--dominance-sample",
        type=int,
        default=60,
        help="market days on which to re-check the per-day oracle bound",
    )
    parser.add_argument("--seed", type=int, default=5, help="sampling seed")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def load_realised(zone_key: str, years: list[int]) -> pd.Series:
    """Hourly realised prices covering ``years`` plus enough run-in for the mark.

    The trailing terminal reference looks back up to 7 market days, so the file
    for the year before the first dispatched year is loaded too when it is
    cached. Energy-Charts' request window is in local time, so the file for year
    ``Y`` already starts at local midnight on ``Y-01-01`` — the first market day
    of ``Y`` is complete without reaching back — but the *reference* for that day
    is not, and a day without a reference is skipped rather than marked at a
    number nobody chose.
    """
    for year in years:
        assert_not_sealed(year, f"dispatch {zone_key} {year}")
    wanted = sorted({y - 1 for y in years} | set(years))
    frame = load_zone_series(zone_key, years=None)
    series = frame[PRICE_COLUMN]
    local_year = series.index.tz_convert(zone_timezone(zone_key)).year
    keep = np.isin(np.asarray(local_year), np.asarray(wanted))
    return series[keep]


def market_year(day: dt.date) -> int:
    return day.year


# ---------------------------------------------------------------------------
# invariants
# ---------------------------------------------------------------------------


def check_value_added_non_negative(result: RollingResult) -> dict[str, Any]:
    """Doing nothing is always feasible, so no day may add negative value."""
    offenders = {
        day.isoformat(): round(val.value_added_eur, 8)
        for day, val in result.valuations.items()
        if val.value_added_eur < -1e-6
    }
    return {
        "holds": not offenders,
        "n_days_checked": result.n_days,
        "worst_day_eur": round(
            min((v.value_added_eur for v in result.valuations.values()), default=0.0), 8
        ),
        "offenders": offenders,
    }


def check_day_lengths(result: RollingResult, zone_key: str) -> dict[str, Any]:
    """Every dispatched block is exactly as long as its local calendar day."""
    from data.contracts import local_day_hours

    tz = zone_timezone(zone_key)
    counts: dict[int, int] = {}
    bad: list[str] = []
    for day, valuation in result.valuations.items():
        counts[valuation.n_intervals] = counts.get(valuation.n_intervals, 0) + 1
        if valuation.n_intervals != local_day_hours(day, tz):
            bad.append(day.isoformat())
    return {
        "holds": not bad,
        "hours_per_day_histogram": {str(k): v for k, v in sorted(counts.items())},
        "mismatched_days": bad,
    }


def check_oracle_dominance(
    result: RollingResult,
    spec: BatterySpec,
    zone_key: str,
    n_sample: int,
    seed: int,
) -> dict[str, Any]:
    """CLAUDE.md's per-day invariant, on a sample of real days.

    For each sampled day, commit a schedule against a deliberately wrong price
    vector (the realised vector shuffled, which is a feasible schedule chosen
    without foresight), settle it at realised prices from the oracle's own
    opening SoC and the same mark, and assert it does not beat the oracle. The
    sample is a cost control: the bound is exact by LP optimality, so this is
    checking the implementation, not the mathematics.
    """
    if not result.days or n_sample <= 0:
        return {"holds": True, "n_days_checked": 0, "note": "nothing to check"}
    rng = np.random.default_rng(seed)
    days = list(result.days)
    chosen = (
        days
        if len(days) <= n_sample
        else [days[i] for i in sorted(rng.choice(len(days), n_sample, replace=False))]
    )
    worst_margin = 0.0
    failures: list[str] = []
    for day in chosen:
        schedule = result.schedules[day]
        oracle_value = result.valuations[day]
        realised = pd.Series(result.realised_prices[day], index=schedule.index)
        wrong = pd.Series(
            rng.permutation(result.realised_prices[day]), index=schedule.index
        )
        committed = solve_day(
            wrong,
            spec,
            soc_start_mwh=schedule.soc_start_mwh,
            index=schedule.index,
            reference_price=result.reference_prices.get(day),
        )
        settled = value_schedule(committed, realised, spec)
        worst_margin = max(
            worst_margin, settled.value_added_eur - oracle_value.value_added_eur
        )
        try:
            assert_oracle_dominates(settled, oracle_value, label=day.isoformat())
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised by caller
            failures.append(f"{day.isoformat()}: {exc}")
    return {
        "holds": not failures,
        "n_days_checked": len(chosen),
        "worst_excess_eur": round(worst_margin, 8),
        "failures": failures,
    }


def simultaneity_flag(result: RollingResult, spec: BatterySpec) -> dict[str, Any]:
    """PLAN.md's required check, aggregated into FLAG material."""
    days = [
        (day, val) for day, val in result.valuations.items() if val.simultaneity.found
    ]
    worst = sorted(
        days, key=lambda pair: -pair[1].simultaneity.energy_burned_mwh
    )[:5]
    total_cash = result.total_cash_eur
    overlap_cash = float(
        sum(v.simultaneity.cash_from_overlap_eur for _, v in days)
    )
    return {
        "flag_required": bool(days),
        "price_threshold_eur_per_mwh": (
            None
            if not np.isfinite(spec.simultaneity_price_threshold)
            else round(spec.simultaneity_price_threshold, 4)
        ),
        "n_days_affected": len(days),
        "n_days_total": result.n_days,
        "n_intervals_affected": int(
            sum(v.simultaneity.n_intervals for _, v in days)
        ),
        "n_intervals_at_negative_price": int(
            sum(v.simultaneity.n_intervals_negative_price for _, v in days)
        ),
        "energy_burned_mwh": round(
            float(sum(v.simultaneity.energy_burned_mwh for _, v in days)), 4
        ),
        "cash_from_overlap_eur": round(overlap_cash, 2),
        "cash_from_overlap_share_of_total": (
            round(overlap_cash / total_cash, 6) if total_cash else None
        ),
        "worst_days": [
            {
                "market_day": day.isoformat(),
                "n_intervals": val.simultaneity.n_intervals,
                "energy_burned_mwh": round(val.simultaneity.energy_burned_mwh, 4),
                "min_price": val.simultaneity.min_price_with_overlap,
                "cash_from_overlap_eur": round(
                    val.simultaneity.cash_from_overlap_eur, 2
                ),
            }
            for day, val in worst
        ],
    }


def flat_day_report(result: RollingResult) -> dict[str, Any]:
    """How often an exactly-flat day — where the LP optimum is degenerate — occurs.

    The flat-curve tests note that at ``p_ref == p`` holding and liquidating are
    worth the same to the penny, so the LP's choice of cycling on such a day is
    arbitrary. This counts them so the claim "measure zero on real prices" is a
    measurement rather than a hope.
    """
    n_flat = 0
    n_at_mark = 0
    for day in result.days:
        prices = result.realised_prices[day]
        if float(prices.max() - prices.min()) < 1e-9:
            n_flat += 1
            if abs(float(prices[0]) - result.reference_prices.get(day, np.nan)) < 1e-9:
                n_at_mark += 1
    return {"n_flat_days": n_flat, "n_flat_days_at_the_mark": n_at_mark}


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


def run_zone(zone_key: str, args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_battery_config()
    terminal = cfg.get("terminal") or {}
    spec = BatterySpec.from_config(cfg)
    tz = zone_timezone(zone_key)
    print(f"\n=== {zone_key} — oracle dispatch, years {args.years} ===")
    print(f"  battery: {spec.power_mw} MW / {spec.energy_mwh} MWh "
          f"({spec.duration_hours:g}h), eta_leg={spec.eta_leg:.6f}, "
          f"k={spec.throughput_cost_eur_per_mwh} EUR/MWh discharged")
    print(f"  terminal: {spec.terminal_mode}, "
          f"{terminal.get('trailing_days')}-day q{terminal.get('trailing_quantile')} "
          f"trailing mark")

    realised = load_realised(zone_key, list(args.years))
    print(f"  loaded {len(realised)} hourly prices "
          f"{realised.index[0].isoformat()} .. {realised.index[-1].isoformat()}")

    roll_kwargs = dict(
        trailing_days=int(terminal.get("trailing_days", 7)),
        trailing_quantile=float(terminal.get("trailing_quantile", 0.5)),
        min_trailing_days=int(terminal.get("min_trailing_days", 1)),
        tz=tz,
    )

    def days_in(years: list[int]) -> set[dt.date]:
        labels = pd.Series(realised.index).dt.tz_convert(tz).dt.date
        return {d for d in labels if d.year in set(years)}

    wanted_days = days_in(list(args.years))
    result = run_rolling_dispatch(
        zone_key, realised, spec, days=wanted_days, curve="oracle", **roll_kwargs
    )
    summary = result.summary()
    print(f"  dispatched {result.n_days} market days, skipped {len(result.skipped)}")
    for skip in result.skipped:
        print(f"    SKIP {skip.day} [{skip.reason}] {skip.detail}")
    print(f"  oracle cash {result.total_cash_eur:,.2f} EUR "
          f"({summary['cash_eur_per_mw_year']:,.0f} EUR/MW/yr), "
          f"{result.equivalent_full_cycles:.1f} equivalent full cycles")

    invariants = {
        "value_added_non_negative": check_value_added_non_negative(result),
        "day_lengths_match_local_calendar": check_day_lengths(result, zone_key),
        "oracle_dominates_a_foresight_free_schedule": check_oracle_dominance(
            result, spec, zone_key, args.dominance_sample, args.seed
        ),
    }
    for name, outcome in invariants.items():
        state = "OK " if outcome.get("holds") else "FAIL"
        print(f"  [{state}] {name}")
    broken = [name for name, outcome in invariants.items() if not outcome.get("holds")]
    if broken:
        raise SystemExit(
            f"LP invariant(s) failed for {zone_key}: {broken}. "
            f"See the summary JSON; this is a FLAG, not something to work around."
        )

    simultaneity = simultaneity_flag(result, spec)
    if simultaneity["flag_required"]:
        print(f"  FLAG simultaneous charge/discharge on "
              f"{simultaneity['n_days_affected']}/{result.n_days} days, "
              f"{simultaneity['energy_burned_mwh']:.1f} MWh burned, "
              f"{simultaneity['cash_from_overlap_eur']:,.0f} EUR "
              f"({simultaneity['cash_from_overlap_share_of_total']:.2%} of cash)")
    else:
        print("  no simultaneous charge/discharge found")

    out: dict[str, Any] = {
        "cycle": "C5",
        "zone": zone_key,
        "years": list(args.years),
        "curve": "oracle",
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "battery_config": cfg,
        "oracle_lp": summary,
        "invariants": invariants,
        "simultaneity": simultaneity,
        "flat_days": flat_day_report(result),
        "skipped_days": [s.as_dict() for s in result.skipped],
    }

    if not args.no_milp_variant:
        print("  MILP variant (forbid_simultaneous=True) ...")
        milp_spec = BatterySpec.from_config(cfg, forbid_simultaneous=True)
        milp_result = run_rolling_dispatch(
            zone_key,
            realised,
            milp_spec,
            days=wanted_days,
            curve="oracle_no_simultaneous",
            **roll_kwargs,
        )
        milp_summary = milp_result.summary()
        lp_cash = result.total_cash_eur
        gap = lp_cash - milp_result.total_cash_eur
        out["milp_variant"] = {
            "summary": milp_summary,
            "cash_gap_vs_lp_eur": round(gap, 2),
            "cash_gap_share_of_lp": round(gap / lp_cash, 6) if lp_cash else None,
            "n_days_with_simultaneity": milp_result.n_simultaneity_days,
            "invariants": {
                "value_added_non_negative": check_value_added_non_negative(milp_result),
                "no_simultaneity_remains": {
                    "holds": milp_result.n_simultaneity_days == 0
                },
                "milp_cannot_beat_lp": {
                    "holds": bool(
                        milp_result.total_value_added_eur
                        <= result.total_value_added_eur + 1e-6
                    ),
                    "lp_value_added_eur": round(result.total_value_added_eur, 4),
                    "milp_value_added_eur": round(
                        milp_result.total_value_added_eur, 4
                    ),
                },
            },
        }
        print(f"    MILP cash {milp_result.total_cash_eur:,.2f} EUR "
              f"({milp_summary['cash_eur_per_mw_year']:,.0f} EUR/MW/yr), "
              f"gap {gap:,.0f} EUR ({gap / lp_cash:.2%})" if lp_cash else "")
        milp_frame = milp_result.daily_frame()
    else:
        milp_frame = pd.DataFrame()

    if not args.no_per_year:
        print("  descriptive per-year oracle value over the cached years ...")
        per_year = []
        # Every cached (non-sealed) year, as one continuous roll: the oracle is a
        # property of the realised price series alone, so this costs nothing but a
        # few thousand more LP solves and gives C13 its regime context early.
        all_prices = load_zone_series(zone_key, years=None)[PRICE_COLUMN]
        full = run_rolling_dispatch(
            zone_key, all_prices, spec, curve="oracle", **roll_kwargs
        )
        frame = full.daily_frame()
        if not frame.empty:
            frame["year"] = pd.to_datetime(frame["market_day"]).dt.year
            for year, block in frame.groupby("year"):
                per_year.append(
                    {
                        "year": int(year),
                        "n_days": int(len(block)),
                        "cash_eur": round(float(block["cash_eur"].sum()), 2),
                        "cash_eur_per_mw_year": round(
                            float(block["cash_eur"].sum())
                            / spec.power_mw
                            / len(block)
                            * 365.25,
                            1,
                        ),
                        "discharged_mwh": round(float(block["discharged_mwh"].sum()), 2),
                        "equivalent_full_cycles": round(
                            float(block["discharged_mwh"].sum()) / spec.energy_mwh, 1
                        ),
                        "mean_daily_spread_eur_per_mwh": round(
                            float(
                                (
                                    block["realised_price_max"]
                                    - block["realised_price_min"]
                                ).mean()
                            ),
                            2,
                        ),
                        "n_days_with_simultaneity": int(
                            (block["n_simultaneous_intervals"] > 0).sum()
                        ),
                    }
                )
        out["per_year_descriptive"] = {
            "n_days_skipped": len(full.skipped),
            "skipped": [sk.as_dict() for sk in full.skipped],
            "note": (
                "Descriptive context only, not a result: the oracle is a property "
                "of the realised price series, so no model and no forecast is "
                "involved. One continuous roll over every cached year, so SoC "
                "carries across year boundaries and the first day of the series "
                "has no trailing mark and is skipped."
            ),
            "rows": per_year,
        }
        for row in per_year:
            print(f"    {row['year']}  {row['cash_eur_per_mw_year']:>9,.0f} EUR/MW/yr  "
                  f"{row['equivalent_full_cycles']:>5.1f} cycles  "
                  f"spread {row['mean_daily_spread_eur_per_mwh']:>6.2f}  "
                  f"sim-days {row['n_days_with_simultaneity']}")

    # -- artefacts ---------------------------------------------------------
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{zone_key}_{'-'.join(str(y) for y in args.years)}"
    daily = result.daily_frame()
    if not milp_frame.empty:
        daily = pd.concat([daily, milp_frame], ignore_index=True)
    daily_path = RESULTS_DIR / f"c5_oracle_{tag}_daily.csv"
    daily.to_csv(daily_path, index=False, float_format="%.6f")
    schedule_path = RESULTS_DIR / f"c5_oracle_{tag}_schedule.csv.gz"
    result.schedule_frame().to_csv(schedule_path, float_format="%.8f")
    summary_path = RESULTS_DIR / f"c5_oracle_{tag}_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
        fh.write("\n")
    for path in (daily_path, schedule_path, summary_path):
        print(f"  wrote {path.relative_to(REPO_ROOT)} "
              f"({path.stat().st_size / 1024:.0f} KiB)")
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    zones = load_zones()
    unknown = [z for z in args.zones if z not in zones]
    if unknown:
        raise SystemExit(f"unknown zone key(s): {unknown}")
    for year in args.years:
        assert_not_sealed(year, "run the C5 oracle dispatch")
    for zone_key in args.zones:
        run_zone(zone_key, args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
