"""CLI: the C15 sensitivities — the same forecasts, dispatched under six batteries.

PLAN.md calls this cycle "where the honest findings live", and lists four
sensitivities: **throughput cost 0 / 2 / 5 EUR/MWh**, **daily-reset vs
rolling-horizon SoC**, **RES-forecast degradation**, and **2h vs 4h duration**.

Nothing is re-fitted
--------------------
Every forecast dispatched here is read from a committed prediction artefact —
C13's 36 per-year files for 2020-2023, C8's and C10's for 2024, C8's and C9's for
the RES-degradation leg — exactly as C11 and C13 read them, and every artefact's
``y_true`` is re-checked hour-for-hour against the price cache before it is used.
A sensitivity is a change to the *battery*, not to the model, so a cycle that
re-fits anything here would be measuring two things at once. NOTE C14-06 settles
the one case where that could have been tempting: NOTE C8-01 is closed and the
honest exogenous block buys nothing, so C15 adds **no new model arm**.

The ladder is one-at-a-time, and its first rung is the published result
-----------------------------------------------------------------------
Six rungs, each a single declared departure from ``config/battery.yaml``:

=========================  ================================================
``base``                   1 MW / 2h, k = 2 EUR/MWh, SoC carries, end-of-day
                           inventory marked at the trailing reference. The
                           committed spec — identical to C11's and C13's.
``throughput_0``           k = 0: all friction removed.
``throughput_5``           k = 5: PLAN.md's upper end.
``duration_4h``            4h of storage at the same 1 MW.
``soc_daily_reset``        Every market day opens *and* closes at half full:
                           no carryover, each day an independent problem.
``soc_no_terminal``        SoC carries but closing inventory is worth nothing
                           — the trap ``config/battery.yaml`` warns about.
=========================  ================================================

``base`` is not a seventh experiment: it is re-run from scratch here and its
per-day settled cash is checked against the rows C11 and C13 committed
(:func:`check_baseline_reproduction`). A ladder whose zero rung does not
reproduce the published number is measuring its own re-implementation.

Comparability across rungs is a day-set problem, and it is not cosmetic
----------------------------------------------------------------------
``dispatch.rolling`` skips a day with reason ``no_reference`` only when the
terminal mode is ``trailing_value``, so the rungs that switch the terminal
condition off can dispatch *more* days than ``base`` does. A capture ratio
summed over one day set against a denominator summed over another is not a
ratio of anything (C11's rule), so every cross-rung number here is reported on
the **ladder-common day set**: the days every rung of every curve of that
(zone, year) dispatched. That is C11's ``common_hours`` definition applied to a
larger run set, and it is why ``scope`` needs no new value.

What NOTE C14-01 actually asks, and the honest answer
-----------------------------------------------------
C14 handed this cycle a prediction: *NO2's within-day ordering will not improve
at any rung.* C15 reports it — and reports that **in this ladder the prediction
cannot fail**. The within-day Spearman is a function of the forecast and the
realised prices alone; no rung of this ladder touches either, so the number is
identical at every rung by construction, and C15 asserts that identity rather
than presenting it as evidence. The substantive form of the prediction *is*
testable and is tested: if NO2's capture deficit were friction, removing the
friction (``throughput_0``) would close it. See ``docs/sensitivities.md``.

Phases
------
``verify``    the re-pulled price cache against C1's committed fingerprints.
``dispatch``  every rung x curve x (zone, year); per-day artefacts + invariants.
``analyse``   pooled tables, paired daily-block intervals on every lever delta,
              the NO2 ordering table, figures, and the store rows.

An invariant failure writes ``c15_invariant_flags.json`` and the dispatch phase
exits non-zero *after* the artefacts are written, so a FLAG is a line to copy
into PROGRESS.md rather than a lost run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from backtest.bootstrap import (
    BLOCK_LADDER,
    BlockBootstrapSpec,
    DEFAULT_REPLICATES,
    DEFAULT_SEED,
    _interval,
    ratio_replicates,
    replicate_counts,
)
from backtest.metrics import daily_shape_table
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
    ALIGNED_FROM,
    FULL_HISTORY_FROM,
    GBM_FINGERPRINT,
    ORACLE_MODEL,
    ORACLE_VARIANT,
    beats_naive,
    mae_on_days,
    pooled_capture,
)
from backtest.run_c13_regime import (
    LEAR_COLUMN,
    NAIVE_COLUMN,
    OUTLIER_ZONE,
    THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR,
)
from backtest.run_c14_fundamentals import verify_price_cache
from data.config import config_hash, load_battery_config, load_zones
from data.holdout import assert_not_sealed
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
from forecast.timing import market_days, zone_timezone

ORACLE_CURVE = "oracle"
NAIVE_CURVE = "naive"
COMPARABLE_CURVE = "lear_full_history"

#: The evaluation years of the main ladder. The same five C13 reported, so a
#: rung's effect can be read against FINDING C13-A's year-to-year movement
#: rather than against one year's noise. 2025 is sealed.
LADDER_YEARS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024)

#: The RES-degradation leg's years: the only two for which an as-published and a
#: persistence vintage of the same model both exist (no archived ENTSO-E D-1
#: vintage before 2022, plus 365 days of required history).
RES_YEARS: tuple[int, ...] = (2023, 2024)

#: The two legs. ``main`` is the nine-zone comparable set the cross-zone claims
#: are built on; ``res`` is PLAN.md's RES-forecast degradation sensitivity,
#: Tier A only, measured as the *dispatch* value of an Art. 14 publication
#: timestamp at each rung.
MAIN_LEG = "main"
RES_LEG = "res"


class SensitivityError(RuntimeError):
    """The ladder cannot be built or compared as asked."""


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rung:
    """One battery, and the single thing about it that differs from ``base``."""

    name: str
    lever: str
    label: str
    overrides: dict[str, Any] = field(default_factory=dict)
    soc_policy: str = "carry"

    @property
    def is_base(self) -> bool:
        return self.lever == "baseline"

    def spec(self, cfg: dict[str, Any]) -> BatterySpec:
        return BatterySpec.from_config(cfg, **dict(self.overrides))

    def as_dict(self) -> dict[str, Any]:
        return {
            "rung": self.name,
            "lever": self.lever,
            "label": self.label,
            "overrides": dict(self.overrides),
            "soc_policy": self.soc_policy,
        }


LADDER: tuple[Rung, ...] = (
    Rung("base", "baseline", "config/battery.yaml as committed: 2h, k=2, SoC carries"),
    Rung("throughput_0", "throughput_cost", "throughput cost 0 EUR/MWh",
         {"throughput_cost_eur_per_mwh": 0.0}),
    Rung("throughput_5", "throughput_cost", "throughput cost 5 EUR/MWh",
         {"throughput_cost_eur_per_mwh": 5.0}),
    Rung("duration_4h", "duration", "4 hours of storage at the same 1 MW",
         {"duration_hours": 4.0}),
    Rung("soc_daily_reset", "soc_policy",
         "each market day opens and closes half full — no carryover",
         {"terminal_mode": "floor", "terminal_floor_fraction": 0.5}, soc_policy="reset"),
    Rung("soc_no_terminal", "soc_policy",
         "SoC carries but closing inventory is unvalued",
         {"terminal_mode": "none"}),
)

RUNGS_BY_NAME: dict[str, Rung] = {rung.name: rung for rung in LADDER}
BASE_RUNG = "base"


def rungs_for(requested: Sequence[str] | None) -> list[Rung]:
    """The requested rungs, always including ``base`` (every delta is against it)."""
    if not requested:
        return list(LADDER)
    unknown = sorted(set(requested) - set(RUNGS_BY_NAME))
    if unknown:
        raise SensitivityError(
            f"unknown rung(s) {unknown}; known: {sorted(RUNGS_BY_NAME)}"
        )
    chosen = {BASE_RUNG, *requested}
    return [rung for rung in LADDER if rung.name in chosen]


# ---------------------------------------------------------------------------
# The curves, from the committed artefacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurveSpec:
    """A dispatchable forecast curve: where it was committed, and its store key."""

    curve: str
    model: str
    exog_variant: str
    artefact: str
    column: str
    train_from: str
    vintage: str = "honest"
    model_fingerprint: str = ""


def main_curves(zone: str, tier: str, year: int) -> list[CurveSpec]:
    """The comparable LEAR and the naive floor, from whichever cycle committed them.

    2020-2023 come from C13's own per-year artefacts; 2024 comes from the files
    C11 dispatched (C8's for Tier A, C10's for Tier B), so the ``base`` rung is
    reading exactly the rows the published 2024 numbers were computed from.
    """
    if year in (2020, 2021, 2022, 2023):
        artefact = f"c13_year_{zone}_{year}_predictions.csv.gz"
        lear_column = LEAR_COLUMN
    elif year == 2024:
        if tier == "A":
            artefact = f"c8_exog_{zone}_2024_predictions.csv.gz"
            lear_column = "y_pred_price_only_full_history"
        else:
            artefact = f"c10_tierb_{zone}_2024_predictions.csv.gz"
            lear_column = LEAR_COLUMN
    else:
        raise SensitivityError(f"{zone} {year}: no committed artefact for this year")
    return [
        CurveSpec(COMPARABLE_CURVE, "lear", "price_only", artefact, lear_column,
                  FULL_HISTORY_FROM),
        CurveSpec(NAIVE_CURVE, "naive_last_week", "", artefact, NAIVE_COLUMN,
                  FULL_HISTORY_FROM),
    ]


def res_curves(zone: str, year: int) -> list[CurveSpec]:
    """PLAN.md's RES-forecast degradation pair, in both model classes.

    ``res_persistence`` is the leak-free vintage a bidder could actually have had
    at gate closure; ``res_as_published`` is the Art. 14 series as the platform
    carries it, which is published *after* gate closure. The second is labelled
    ``after_gate_closure`` everywhere and is never an achievable result — it is
    the measurement of a leak (FINDING C9-C).
    """
    c8 = f"c8_exog_{zone}_{year}_predictions.csv.gz"
    c9 = f"c9_gbm_{zone}_{year}_predictions.csv.gz"
    return [
        CurveSpec("lear_res_persistence", "lear", "res_persistence", c8,
                  "y_pred_res_persistence", ALIGNED_FROM),
        CurveSpec("lear_res_as_published", "lear", "res_as_published", c8,
                  "y_pred_res_as_published", ALIGNED_FROM,
                  vintage="after_gate_closure"),
        CurveSpec("gbm_res_persistence", "gbm", "res_persistence", c9,
                  "y_pred_gbm_res_persistence", ALIGNED_FROM,
                  model_fingerprint=GBM_FINGERPRINT),
        CurveSpec("gbm_res_as_published", "gbm", "res_as_published", c9,
                  "y_pred_gbm_res_as_published", ALIGNED_FROM,
                  vintage="after_gate_closure", model_fingerprint=GBM_FINGERPRINT),
    ]


def curves_for(leg: str, zone: str, tier: str, year: int) -> list[CurveSpec]:
    if leg == MAIN_LEG:
        return main_curves(zone, tier, year)
    if leg == RES_LEG:
        return res_curves(zone, year)
    raise SensitivityError(f"unknown leg {leg!r}")


#: The lever deltas the analyse phase gives an interval. Each is
#: ``(rung, baseline rung, question)`` and every one is a single-lever move.
LEVER_CONTRASTS: tuple[tuple[str, str, str], ...] = (
    ("throughput_0", BASE_RUNG,
     "how much of the capture ratio is friction (NOTE C13-02)?"),
    ("throughput_5", BASE_RUNG,
     "PLAN.md's upper throughput cost: how fast does the value go?"),
    ("duration_4h", BASE_RUNG,
     "does a longer battery capture a larger *share* of its own larger prize?"),
    ("soc_daily_reset", BASE_RUNG,
     "what is PLAN.md's rolling-horizon SoC carryover worth?"),
    ("soc_no_terminal", BASE_RUNG,
     "what does the end-of-day inventory mark do to realised cash?"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["verify", "dispatch", "analyse", "all"])
    parser.add_argument("--zones", nargs="*", default=None, help="zone keys (default: all)")
    parser.add_argument("--years", nargs="*", type=int, default=None,
                        help=f"evaluation years (default: {list(LADDER_YEARS)})")
    parser.add_argument("--rungs", nargs="*", default=None,
                        help=f"ladder rungs (default: all; base is always included)")
    parser.add_argument("--legs", nargs="*", default=[MAIN_LEG, RES_LEG],
                        choices=[MAIN_LEG, RES_LEG])
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--no-append", action="store_true",
                        help="compute and write artefacts, append nothing to the store")
    parser.add_argument("--results-path", default=None, help="override the store path (tests)")
    parser.add_argument("--runs-path", default=None, help="override the run manifest (tests)")
    return parser.parse_args(argv)


def selected_zones(requested: list[str] | None) -> dict[str, Any]:
    zones = load_zones()
    if not requested:
        return zones
    unknown = sorted(set(requested) - set(zones))
    if unknown:
        raise SensitivityError(f"unknown zone key(s) {unknown}; known: {sorted(zones)}")
    return {z: zones[z] for z in requested}


def artefact_tag(leg: str, zone: str, year: int) -> str:
    return f"c15_{leg}_{zone}_{year}"


def daily_path(leg: str, zone: str, year: int):
    return RESULTS_DIR / f"{artefact_tag(leg, zone, year)}_daily.csv.gz"


def summary_path(leg: str, zone: str, year: int):
    return RESULTS_DIR / f"{artefact_tag(leg, zone, year)}_summary.json"


# ---------------------------------------------------------------------------
# Phase `verify`: the re-pulled cache is the one C1 committed
# ---------------------------------------------------------------------------


def verify(args: argparse.Namespace) -> int:
    """``data/raw/`` does not survive a container (NOTE C2-02), so re-check it.

    C14's check is imported rather than re-written: it fingerprints the
    ``(UTC epoch, price)`` pairs, not the cached file, because the file embeds a
    fetch timestamp and a hash of it would fail every cycle.
    """
    zones = list(selected_zones(args.zones))
    block = verify_price_cache(zones)
    out = RESULTS_DIR / "c15_cache_verification.json"
    out.write_text(json.dumps(
        {
            "cycle": "C15",
            "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
            "git_sha": git_sha(),
            "prices": block,
            "note": (
                "C15 needs no ENTSO-E pull: NOTE C14-06 closed NOTE C8-01, so this "
                "cycle adds no model arm and the RES-degradation leg re-dispatches "
                "C8's and C9's already-committed forecasts."
            ),
        },
        indent=2,
    ) + "\n")
    print(f"price cache: {block['n_matching']}/{block['n_files']} files match C1's "
          f"manifest fingerprints -> {out.name}")
    if not block["holds"]:
        print("FLAG: the re-pulled price cache does not match the committed manifest",
              file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Phase `dispatch`
# ---------------------------------------------------------------------------

#: The per-day artefact's columns. Everything a later cycle needs to re-pool a
#: rung without re-solving an LP, and every dispatch column is day-additive so
#: ``backtest.bootstrap`` takes the file directly.
DAILY_COLUMNS: tuple[str, ...] = (
    "leg", "rung", "lever", "soc_policy", "zone", "year", "curve", "market_day",
    "n_dispatch_hours", "cash", "oracle_cash", "lost", "value_added",
    "same_start_oracle_value_added", "terminal_value", "opening_value",
    "charged_mwh", "discharged_mwh", "throughput_cost_eur",
    "soc_start_mwh", "soc_end_mwh", "soc_reset_discarded_mwh",
    "n_simultaneous_intervals", "simultaneity_energy_burned_mwh",
    "realised_spread", "realised_price_min", "realised_price_max",
    "reference_price", "in_ladder_common_day_set",
    "n_hours", "sum_abs_error", "sum_sq_error", "sum_error", "forecast_spread",
    "spread_error", "abs_spread_error", "spearman", "spearman_contrib",
    "spearman_defined",
    "model", "exog_variant", "vintage", "train_from", "tier", "regime",
)

#: Where an invariant failure is recorded. Written by the dispatch phase, read
#: and labelled by the analyse phase; the dispatch phase exits non-zero whenever
#: it is non-empty, so a FLAG cannot be lost to a zero exit code.
INVARIANT_FLAGS = "c15_invariant_flags.json"


def load_prediction_frame(
    zone: str, year: int, artefact: str, columns: Sequence[str], realised: pd.Series
) -> pd.DataFrame:
    """A committed artefact, checked against the realised series hour for hour.

    The same provenance check C11 and C13 run: every forecast timestamp must
    exist in the price cache and the artefact's own ``y_true`` must equal it. An
    off-by-one index is a leak that looks like skill and the per-day oracle bound
    would only catch it afterwards.
    """
    path = RESULTS_DIR / artefact
    if not path.exists():
        raise SensitivityError(
            f"{zone} {year}: {artefact} is missing — C15 dispatches committed "
            f"forecasts and never re-fits one"
        )
    frame = pd.read_csv(path, dtype={"market_day": str})
    for column in ("timestamp_utc", "market_day", "y_true", *columns):
        if column not in frame.columns:
            raise SensitivityError(f"{artefact} has no {column!r} column")
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
    frame = frame.set_index(index).sort_index()
    aligned = realised.reindex(frame.index)
    if aligned.isna().any():
        raise SensitivityError(
            f"{zone} {year}/{artefact}: {int(aligned.isna().sum())} forecast "
            f"timestamp(s) have no realised price — the artefact and the price "
            f"cache disagree about the grid"
        )
    gap = float(np.nanmax(np.abs(
        frame["y_true"].to_numpy(dtype=float) - aligned.to_numpy(dtype=float)
    )))
    if gap > 1e-6:
        raise SensitivityError(
            f"{zone} {year}/{artefact}: y_true differs from the realised price "
            f"series by up to {gap:.6g} EUR/MWh — one of the two is not what was "
            f"scored"
        )
    frame.attrs["max_y_true_vs_realised_gap"] = gap
    return frame


def shape_table_for(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """C12's per-day forecast-shape table, in C12's spelling.

    Identical to C13's helper on purpose: the Spearman and spread columns in a
    C15 artefact are then the *same numbers* as the ones already in
    ``c13_daily_by_year.csv.gz``, which is what makes NOTE C14-01's
    rung-invariance check an assertion rather than a comparison of near
    neighbours.
    """
    table = daily_shape_table(frame["y_true"], frame[column], frame["market_day"].to_numpy())
    table = table.drop(columns=["realised_spread"])
    table["abs_spread_error"] = table["spread_error"].abs()
    defined = np.isfinite(table["spearman"].to_numpy(dtype=float))
    table["spearman_defined"] = defined.astype(float)
    table["spearman_contrib"] = np.where(
        defined, table["spearman"].to_numpy(dtype=float), 0.0
    )
    return table


def check_reset_conserves_energy(
    result: RollingResult, spec: BatterySpec
) -> dict[str, Any]:
    """The daily reset may discard stored energy, never create it.

    ``dispatch.rolling`` refuses the unsafe combinations up front; this is the
    *outcome* check on the run that was actually produced, because the guard is
    an argument about the spec and this is a statement about 365 solved days.
    Every day must open at exactly the configured SoC, and every discard must be
    non-negative.
    """
    if result.soc_policy != "reset":
        return {"applicable": False, "reason": "this run carries SoC"}
    opening = spec.initial_soc_mwh
    wrong = {
        day.isoformat(): round(soc, 10)
        for day, soc in result.soc_opening.items()
        if abs(soc - opening) > 1e-9
    }
    created = {
        day.isoformat(): round(mwh, 10)
        for day, mwh in result.soc_reset_discarded.items()
        if mwh < -1e-9
    }
    return {
        "holds": not wrong and not created,
        "opening_soc_mwh": round(opening, 8),
        "n_days_checked": result.n_days,
        "n_days_opening_soc_wrong": len(wrong),
        "days_opening_soc_wrong": dict(sorted(wrong.items())[:10]),
        "n_days_energy_created": len(created),
        "total_discarded_mwh": round(result.soc_reset_discarded_mwh, 8),
        "n_days_discarding": len(result.soc_reset_discarded),
    }


def dispatch_cell(
    leg: str,
    zone_key: str,
    year: int,
    rungs: Sequence[Rung],
    cfg: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Every rung x curve for one (leg, zone, year), with the invariants.

    One realised series and one set of committed forecasts are loaded once and
    then dispatched under each battery, which is the whole design: a rung-to-rung
    difference cannot be a difference in the data.
    """
    assert_not_sealed(year, f"C15 dispatch {leg} {zone_key} {year}")
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
    specs = curves_for(leg, zone_key, zone.tier, year)
    by_artefact: dict[str, list[CurveSpec]] = {}
    for spec_ in specs:
        by_artefact.setdefault(spec_.artefact, []).append(spec_)
    frames: dict[str, pd.DataFrame] = {}
    for artefact, group in by_artefact.items():
        frames[artefact] = load_prediction_frame(
            zone_key, year, artefact, [s.column for s in group], realised
        )
    truth_gaps = {a: f.attrs["max_y_true_vs_realised_gap"] for a, f in frames.items()}

    curves = {
        s.curve: Curve(
            name=s.curve,
            prices=frames[s.artefact][s.column].astype(float),
            source=f"{s.artefact}:{s.column}",
        )
        for s in specs
    }
    shapes = {s.curve: shape_table_for(frames[s.artefact], s.column) for s in specs}

    forecast_days: set[dt.date] = set()
    for curve in curves.values():
        forecast_days |= set(market_days(pd.DatetimeIndex(curve.prices.index), tz).tolist())
    labels = pd.Series(realised.index).dt.tz_convert(tz).dt.date
    wanted = {d for d in labels if d.year == year} & forecast_days
    if not wanted:
        raise SensitivityError(
            f"{leg}/{zone_key} {year}: no market day is both in the year and forecast"
        )

    print(f"\n=== {leg} {zone_key} {year} (tier {zone.tier}, {zone.regime}) — "
          f"{len(rungs)} rung(s) x {len(curves)} curve(s) + oracle over "
          f"{len(wanted)} market days ===", flush=True)

    # --- solve every rung ------------------------------------------------
    runs: dict[str, dict[str, RollingResult]] = {}
    bounds: dict[str, dict[str, dict[dt.date, Any]]] = {}
    battery: dict[str, BatterySpec] = {}
    for rung in rungs:
        spec = rung.spec(cfg)
        battery[rung.name] = spec
        per_curve: dict[str, RollingResult] = {
            ORACLE_CURVE: run_rolling_dispatch(
                zone_key, realised, spec, decision_prices=None, curve=ORACLE_CURVE,
                days=wanted, soc_policy=rung.soc_policy, **roll_kwargs
            )
        }
        for s in specs:
            per_curve[s.curve] = run_rolling_dispatch(
                zone_key, realised, spec, decision_prices=curves[s.curve].prices,
                curve=s.curve, days=wanted, soc_policy=rung.soc_policy, **roll_kwargs
            )
        runs[rung.name] = per_curve
        bounds[rung.name] = {
            name: same_start_oracle(res, spec) for name, res in per_curve.items()
        }
        print(f"  solved {rung.name:<16} "
              f"days {min(len(r.days) for r in per_curve.values())}"
              f"..{max(len(r.days) for r in per_curve.values())}", flush=True)

    # --- the ladder-common day set ---------------------------------------
    # Every cross-rung number is summed over exactly these days. The rungs that
    # switch the terminal condition off dispatch days `base` skips for want of a
    # reference price, so without this the denominators would not match.
    per_rung_shared = {name: set(common_days(per_curve)) for name, per_curve in runs.items()}
    ladder_shared = sorted(set.intersection(*per_rung_shared.values()))
    if not ladder_shared:
        raise SensitivityError(
            f"{leg}/{zone_key} {year}: the rungs share no dispatched market day"
        )
    shared_labels = {d.isoformat() for d in ladder_shared}

    # --- pooled numbers, per rung and curve ------------------------------
    pooled: dict[str, dict[str, dict[str, Any]]] = {}
    for rung in rungs:
        spec = battery[rung.name]
        per_curve = runs[rung.name]
        pooled[rung.name] = {
            name: {
                "own_coverage": pooled_capture(
                    res, bounds[rung.name][name], per_curve[ORACLE_CURVE],
                    set(res.days), spec.power_mw
                ),
                "common_hours": pooled_capture(
                    res, bounds[rung.name][name], per_curve[ORACLE_CURVE],
                    ladder_shared, spec.power_mw
                ),
            }
            for name, res in per_curve.items()
        }

    # --- invariants (CLAUDE.md), every rung and curve ---------------------
    invariants: dict[str, dict[str, dict[str, Any]]] = {}
    for rung in rungs:
        spec = battery[rung.name]
        per_curve = runs[rung.name]
        naive = per_curve.get(NAIVE_CURVE)
        block_for_rung: dict[str, dict[str, Any]] = {}
        for name, res in per_curve.items():
            block: dict[str, Any] = {
                "day_lengths_match_local_calendar": check_day_lengths(res, zone_key),
                "settlement_is_not_a_decision_price_readback":
                    assert_settlement_is_not_a_readback(res),
                "decision_value_added_non_negative":
                    check_decision_value_added_non_negative(res, spec),
                "daily_reset_conserves_energy": check_reset_conserves_energy(res, spec),
            }
            if name == ORACLE_CURVE:
                block["value_added_non_negative_at_realised"] = (
                    check_value_added_non_negative(res)
                )
            else:
                block["same_start_oracle_dominates_every_day"] = check_per_day_dominance(
                    res, bounds[rung.name][name]
                )
                block["beats_naive_pooled_common_days"] = (
                    {"applicable": False, "reason": "this is the naive floor"}
                    if name == NAIVE_CURVE
                    else {"applicable": False,
                          "reason": "this leg carries no naive floor"}
                    if naive is None
                    else beats_naive(res, naive, ladder_shared)
                )
                arm_cash = pooled[rung.name][name]["common_hours"]["cash_eur"]
                oracle_cash = pooled[rung.name][ORACLE_CURVE]["common_hours"]["cash_eur"]
                block["oracle_dominates_pooled_common_days"] = {
                    "holds": oracle_cash >= arm_cash - 1e-6,
                    "oracle_cash_eur": round(oracle_cash, 4),
                    "arm_cash_eur": round(arm_cash, 4),
                    "margin_eur": round(oracle_cash - arm_cash, 4),
                    "capture_rolled_oracle_cash": _round_or_none(
                        pooled[rung.name][name]["common_hours"]
                        ["capture_rolled_oracle_cash"]
                    ),
                }
            block_for_rung[name] = block
        invariants[rung.name] = block_for_rung

    failures = [
        f"{rung}.{name}.{check}"
        for rung, per_curve in invariants.items()
        for name, block in per_curve.items()
        for check, outcome in block.items()
        if outcome.get("applicable", True) and not outcome.get("holds", True)
    ]
    for rung in rungs:
        for name in sorted(runs[rung.name]):
            block = pooled[rung.name][name]["common_hours"]
            rolled = block["capture_rolled_oracle_cash"]
            mark = "OK " if not any(
                f.startswith(f"{rung.name}.{name}.") for f in failures
            ) else "FAIL"
            print(f"  [{mark}] {rung.name:<16} {name:<22} "
                  f"cash {block['cash_eur']:>10,.0f} EUR  "
                  f"{block['cash_eur_per_mw_year']:>9,.0f} EUR/MW/yr  "
                  f"capture {'  n/a ' if rolled is None else f'{rolled:.4f}'}",
                  flush=True)

    # --- the per-day artefact --------------------------------------------
    by_curve = {s.curve: s for s in specs}
    blocks: list[pd.DataFrame] = []
    for rung in rungs:
        for name, res in runs[rung.name].items():
            captured = capture_frame(res, runs[rung.name][ORACLE_CURVE],
                                     bounds[rung.name][name])
            if captured.empty:
                continue
            daily = res.daily_frame().set_index("market_day")
            out = pd.DataFrame(index=pd.Index(captured["market_day"], name="market_day"))
            out["leg"], out["rung"] = leg, rung.name
            out["lever"], out["soc_policy"] = rung.lever, rung.soc_policy
            out["zone"], out["year"], out["curve"] = zone_key, year, name
            out["n_dispatch_hours"] = captured["n_hours"].to_numpy(dtype=int)
            out["cash"] = captured["cash_eur"].to_numpy(dtype=float)
            out["oracle_cash"] = captured["rolled_oracle_cash_eur"].to_numpy(dtype=float)
            out["lost"] = out["oracle_cash"] - out["cash"]
            out["value_added"] = captured["value_added_eur"].to_numpy(dtype=float)
            out["same_start_oracle_value_added"] = (
                captured["same_start_oracle_value_added_eur"].to_numpy(dtype=float)
            )
            aligned_daily = daily.reindex(out.index)
            for source, target in (
                ("terminal_value_eur", "terminal_value"),
                ("opening_value_eur", "opening_value"),
                ("charged_mwh", "charged_mwh"),
                ("discharged_mwh", "discharged_mwh"),
                ("throughput_cost_eur", "throughput_cost_eur"),
                ("soc_start_mwh", "soc_start_mwh"),
                ("soc_end_mwh", "soc_end_mwh"),
                ("n_simultaneous_intervals", "n_simultaneous_intervals"),
                ("simultaneity_energy_burned_mwh", "simultaneity_energy_burned_mwh"),
            ):
                out[target] = aligned_daily[source].to_numpy(dtype=float)
            out["soc_reset_discarded_mwh"] = [
                float(res.soc_reset_discarded.get(dt.date.fromisoformat(d), 0.0))
                for d in out.index
            ]
            out["realised_spread"] = captured["realised_spread"].to_numpy(dtype=float)
            for column in ("realised_price_min", "realised_price_max",
                           "reference_price"):
                out[column] = captured[column].to_numpy(dtype=float)
            out["in_ladder_common_day_set"] = [d in shared_labels for d in out.index]
            shape_columns = (
                "n_hours", "sum_abs_error", "sum_sq_error", "sum_error",
                "forecast_spread", "spread_error", "abs_spread_error", "spearman",
                "spearman_contrib", "spearman_defined",
            )
            if name == ORACLE_CURVE:
                for column in shape_columns:
                    out[column] = np.nan
                out["model"], out["exog_variant"] = ORACLE_MODEL, ORACLE_VARIANT
                out["vintage"], out["train_from"] = "honest", ""
            else:
                shape = shapes[name].reindex(out.index)
                if shape["n_hours"].isna().any():
                    absent = shape.index[shape["n_hours"].isna()].tolist()
                    raise SensitivityError(
                        f"{leg}/{zone_key} {year}/{name}: {len(absent)} dispatched "
                        f"day(s) have no hourly forecast rows, first {absent[0]} — "
                        f"the dispatch and the prediction artefact disagree about "
                        f"which days exist"
                    )
                for column in shape_columns:
                    out[column] = shape[column].to_numpy(dtype=float)
                arm = by_curve[name]
                out["model"], out["exog_variant"] = arm.model, arm.exog_variant
                out["vintage"], out["train_from"] = arm.vintage, arm.train_from
            out["tier"], out["regime"] = zone.tier, zone.regime
            blocks.append(out.reset_index())
    frame_out = pd.concat(blocks, ignore_index=True)[list(DAILY_COLUMNS)]

    summary = {
        "cycle": "C15",
        "leg": leg,
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "year": year,
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "rungs": {rung.name: {**rung.as_dict(), "battery_spec": battery[rung.name].as_dict()}
                  for rung in rungs},
        "n_market_days_wanted": len(wanted),
        "n_ladder_common_days": len(ladder_shared),
        "dispatched_days": {
            rung.name: {n: len(r.days) for n, r in sorted(runs[rung.name].items())}
            for rung in rungs
        },
        "common_days_per_rung": {n: len(d) for n, d in sorted(per_rung_shared.items())},
        "skipped_days": {
            rung.name: {
                n: [s.as_dict() for s in r.skipped] for n, r in sorted(runs[rung.name].items())
            }
            for rung in rungs
        },
        "curve_sources": {
            s.curve: {
                **curves[s.curve].as_dict(),
                "source": curves[s.curve].source,
                "model": s.model,
                "exog_variant": s.exog_variant,
                "vintage": s.vintage,
                "train_from": s.train_from,
                "model_fingerprint": s.model_fingerprint,
                "alignment": assert_curve_aligns(curves[s.curve], realised),
            }
            for s in specs
        },
        "max_y_true_vs_realised_gap": truth_gaps,
        "pooled": pooled,
        "invariants": invariants,
        "invariant_failures": failures,
        "realised_losses": {
            rung.name: {n: report_realised_losses(r) for n, r in runs[rung.name].items()}
            for rung in rungs
        },
        "simultaneity": {
            rung.name: {
                n: simultaneity_flag(r, battery[rung.name])
                for n, r in runs[rung.name].items()
            }
            for rung in rungs
        },
        "soc_reset_discarded_mwh": {
            rung.name: {n: round(r.soc_reset_discarded_mwh, 8)
                        for n, r in runs[rung.name].items()}
            for rung in rungs
        },
        "point_error_on_ladder_common_days": {
            s.curve: mae_on_days(curves[s.curve], realised, ladder_shared, tz)
            for s in specs
        },
        "comparability_note": (
            "every cross-rung number is summed over the ladder-common day set — the "
            "days every rung of every curve dispatched — because a rung that "
            "switches the terminal condition off has no 'no_reference' skip and "
            "therefore dispatches days `base` does not"
        ),
    }
    return summary, frame_out


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def dispatch(args: argparse.Namespace) -> int:
    """Every (leg, zone, year) cell, writing the per-day artefact as it goes."""
    zones = selected_zones(args.zones)
    rungs = rungs_for(args.rungs)
    cfg = load_battery_config()
    flags: dict[str, list[str]] = {}
    written: list[str] = []
    for leg in args.legs:
        years = args.years or (LADDER_YEARS if leg == MAIN_LEG else RES_YEARS)
        for zone_key, zone in zones.items():
            if leg == RES_LEG and zone.tier != "A":
                continue
            for year in years:
                if leg == RES_LEG and year not in RES_YEARS:
                    continue
                summary, daily = dispatch_cell(leg, zone_key, year, rungs, cfg)
                daily.to_csv(daily_path(leg, zone_key, year), index=False)
                summary_path(leg, zone_key, year).write_text(
                    json.dumps(summary, indent=2, default=str) + "\n"
                )
                written.append(artefact_tag(leg, zone_key, year))
                if summary["invariant_failures"]:
                    flags[artefact_tag(leg, zone_key, year)] = summary["invariant_failures"]

    out = RESULTS_DIR / INVARIANT_FLAGS
    out.write_text(json.dumps(
        {
            "cycle": "C15",
            "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
            "git_sha": git_sha(),
            "n_cells": len(written),
            "cells": written,
            "n_cells_with_failures": len(flags),
            "failures": flags,
            "note": (
                "CLAUDE.md's invariants, run on every rung of every curve of every "
                "cell. A non-empty `failures` block is a FLAG for PROGRESS.md and "
                "the dispatch phase exits non-zero; it is never a reason to relax a "
                "check. FLAG C13-01 and FLAG C14-01 are the two already-explained "
                "pooled naive-dominance failures this project carries, and a rung "
                "that reproduces one of them is reproducing a known regime fact."
            ),
        },
        indent=2,
    ) + "\n")
    print(f"\n{len(written)} cell(s) dispatched; {len(flags)} with invariant "
          f"failures -> {out.name}")
    if flags:
        for cell, items in sorted(flags.items()):
            print(f"FLAG {cell}: {', '.join(items)}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Phase `analyse`
# ---------------------------------------------------------------------------

#: The block lengths every interval is reported at (C12's ladder). A wider block
#: does **not** mean a wider interval at n = 365 — see C12's warning — so this is
#: a robustness check, not an ordering, and the rung least favourable to the
#: claim being made is the one to read.
HEADLINE_BLOCK = 1

#: C12's seed, deliberately: the ``base`` rung's 2024 columns are then drawn
#: exactly as C12 drew them.
SEED = DEFAULT_SEED


@lru_cache(maxsize=8)
def _counts(n_days: int, n_replicates: int, block_days: int) -> np.ndarray:
    """The replicate count matrix, memoised.

    ``backtest.bootstrap.replicate_counts`` is a pure function of
    ``(n_days, n_replicates, block_days, seed)``, and C15 asks for the same
    matrix ~1 600 times (every cell x curve x contrast x block). Memoising it
    does not change a single number — the draw is already identical by
    construction, which is what makes every contrast here paired — it just stops
    the cycle spending twenty minutes rebuilding the same 29 MB array.
    """
    spec = BlockBootstrapSpec(
        n_days=n_days, n_replicates=n_replicates, block_days=block_days, seed=SEED,
    )
    return replicate_counts(spec)


def bootstrap_spec(n_days: int, n_replicates: int, block_days: int
                   ) -> tuple[BlockBootstrapSpec, np.ndarray]:
    spec = BlockBootstrapSpec(
        n_days=n_days, n_replicates=n_replicates, block_days=block_days, seed=SEED,
    )
    return spec, _counts(n_days, n_replicates, block_days)


def load_ladder(legs: Sequence[str], zones: Sequence[str], years: Sequence[int] | None
                ) -> pd.DataFrame:
    """Every per-day C15 artefact as one frame. Read, never recomputed."""
    found: list[pd.DataFrame] = []
    missing: list[str] = []
    for leg in legs:
        leg_years = years or (LADDER_YEARS if leg == MAIN_LEG else RES_YEARS)
        for zone in zones:
            for year in leg_years:
                path = daily_path(leg, zone, year)
                if path.exists():
                    found.append(pd.read_csv(path, dtype={"market_day": str}))
                elif leg == MAIN_LEG:
                    missing.append(path.name)
    if not found:
        raise SensitivityError(
            "no C15 per-day artefact found — run the dispatch phase first"
        )
    if missing:
        raise SensitivityError(
            f"{len(missing)} main-leg artefact(s) missing, first {missing[0]} — "
            f"a cross-zone table built on a partial ladder is not a cross-zone table"
        )
    return pd.concat(found, ignore_index=True)


def check_baseline_reproduction(
    ladder: pd.DataFrame, atol: float = 1e-6
) -> dict[str, Any]:
    """The ``base`` rung against the per-day cash C11 and C13 committed.

    This is the check that makes the whole ladder readable. ``base`` is the
    committed battery, dispatched here from the committed forecasts, so its
    settled cash must equal — not approximate — the rows already in
    ``c13_daily_by_year.csv.gz`` (which carry C11's 2024 column unchanged). If it
    does not, every delta in this cycle is a delta against a re-implementation.
    """
    source = RESULTS_DIR / "c13_daily_by_year.csv.gz"
    if not source.exists():
        raise SensitivityError(
            f"{source.name} is missing — it is C15's reproduction reference"
        )
    want = pd.read_csv(source, dtype={"market_day": str})
    mine = ladder[(ladder["leg"] == MAIN_LEG) & (ladder["rung"] == BASE_RUNG)]
    keys = ["zone", "year", "curve", "market_day"]
    merged = mine[keys + ["cash", "oracle_cash"]].merge(
        want[keys + ["cash", "oracle_cash"]], on=keys, how="inner",
        suffixes=("_c15", "_committed"),
    )
    if merged.empty:
        raise SensitivityError(
            "the base rung and c13_daily_by_year share no (zone, year, curve, day) row"
        )
    cash_gap = (merged["cash_c15"] - merged["cash_committed"]).abs()
    oracle_gap = (merged["oracle_cash_c15"] - merged["oracle_cash_committed"]).abs()
    worst = merged.loc[cash_gap.idxmax()] if len(merged) else None
    return {
        "holds": bool(cash_gap.max() <= atol and oracle_gap.max() <= atol),
        "n_rows_compared": int(len(merged)),
        "n_rows_in_base_rung": int(len(mine)),
        "n_rows_in_committed": int(len(want)),
        "worst_abs_cash_gap_eur": float(cash_gap.max()),
        "worst_abs_oracle_cash_gap_eur": float(oracle_gap.max()),
        "atol_eur": atol,
        "worst_row": None if worst is None else {
            k: (worst[k] if not isinstance(worst[k], (np.integer, np.floating))
                else float(worst[k])) for k in keys
        },
        "reference": source.name,
        "note": (
            "C13's file carries C11's 2024 column unchanged, so one check binds "
            "C15's base rung to both cycles' published numbers."
        ),
    }


def check_res_leg_reproduction(
    ladder: pd.DataFrame, atol: float = 1e-6
) -> dict[str, Any]:
    """The RES leg's ``base`` rung against C11's own committed 2024 per-day cash.

    ``c13_daily_by_year.csv.gz`` carries only the three comparable curves, so the
    main-leg check cannot reach the exogenous arms. C11's artefact can, for 2024.
    Without this, the RES leg's zero rung would be unbound — and the leak's
    dispatch value is a *difference between two arms at the base rung*, so the
    base rung is exactly where an error would hide.
    """
    source = RESULTS_DIR / "c11_capture_daily_2024.csv.gz"
    if not source.exists():
        raise SensitivityError(
            f"{source.name} is missing — it is the RES leg's reproduction reference"
        )
    want = pd.read_csv(source, dtype={"market_day": str})
    want = want.rename(columns={"cash_eur": "cash"})
    mine = ladder[
        (ladder["leg"] == RES_LEG) & (ladder["rung"] == BASE_RUNG)
        & (ladder["year"] == 2024)
    ]
    if mine.empty:
        return {"applicable": False, "reason": "the RES leg was not dispatched for 2024"}
    keys = ["zone", "curve", "market_day"]
    merged = mine[keys + ["cash"]].merge(
        want[keys + ["cash"]], on=keys, how="inner", suffixes=("_c15", "_committed")
    )
    if merged.empty:
        raise SensitivityError(
            "the RES leg's base rung and C11's artefact share no (zone, curve, day) row"
        )
    gap = (merged["cash_c15"] - merged["cash_committed"]).abs()
    return {
        "applicable": True,
        "holds": bool(gap.max() <= atol),
        "n_rows_compared": int(len(merged)),
        "n_curves_compared": int(merged["curve"].nunique()),
        "worst_abs_cash_gap_eur": float(gap.max()),
        "atol_eur": atol,
        "reference": source.name,
    }


def _cell_frame(ladder: pd.DataFrame, leg: str, zone: str, year: int, rung: str,
                curve: str) -> pd.DataFrame:
    """One (rung, curve) cell's ladder-common days, sorted by day."""
    mask = (
        (ladder["leg"] == leg) & (ladder["zone"] == zone) & (ladder["year"] == year)
        & (ladder["rung"] == rung) & (ladder["curve"] == curve)
        & ladder["in_ladder_common_day_set"]
    )
    return ladder[mask].sort_values("market_day").reset_index(drop=True)


def point_row(cell: pd.DataFrame, oracle: pd.DataFrame) -> dict[str, Any]:
    """Every pooled number for one (rung, zone, year, curve), over its own rows.

    Each one is a ratio or a mean of day-additive columns, which is what lets the
    bootstrap recompute it by the same formula from a resampled day multiset.
    """
    n_days = len(cell)
    span = (
        dt.date.fromisoformat(cell["market_day"].iloc[-1])
        - dt.date.fromisoformat(cell["market_day"].iloc[0])
    ).days + 1
    cash = float(cell["cash"].sum())
    oracle_cash = float(oracle["cash"].sum())
    scale = 365.25 / span if span > 0 else float("nan")
    defined = cell["spearman_defined"].to_numpy(dtype=float)
    n_defined = float(np.nansum(defined))
    hours = float(cell["n_hours"].sum()) if cell["n_hours"].notna().any() else float("nan")
    mean_spread = float(cell["realised_spread"].mean())
    mae = (
        float(cell["sum_abs_error"].sum() / hours)
        if np.isfinite(hours) and hours > 0 else float("nan")
    )
    return {
        "n_days": n_days,
        "first_day": cell["market_day"].iloc[0],
        "last_day": cell["market_day"].iloc[-1],
        "cash_eur": cash,
        "cash_eur_per_mw_year": cash * scale,
        "oracle_cash_eur": oracle_cash,
        "oracle_cash_eur_per_mw_year": oracle_cash * scale,
        "capture": cash / oracle_cash if abs(oracle_cash) > 1e-9 else float("nan"),
        "eur_per_mw_year_lost": (oracle_cash - cash) * scale,
        "discharged_mwh": float(cell["discharged_mwh"].sum()),
        "equivalent_full_cycles": float("nan"),  # filled by the caller (needs capacity)
        "mean_realised_spread": mean_spread,
        "mae": mae,
        "error_over_headroom": mae / mean_spread if mean_spread > 1e-9 else float("nan"),
        "mean_spearman": (
            float(np.nansum(cell["spearman_contrib"].to_numpy(dtype=float)) / n_defined)
            if n_defined > 0 else float("nan")
        ),
        "n_days_spearman_defined": int(n_defined),
        "mean_abs_spread_error": float(cell["abs_spread_error"].mean()),
        "n_days_cash_negative": int((cell["value_added"] < -1e-6).sum()),
        "n_days_with_simultaneity": int((cell["n_simultaneous_intervals"] > 0).sum()),
        "simultaneity_energy_burned_mwh": float(
            cell["simultaneity_energy_burned_mwh"].sum()
        ),
        "soc_reset_discarded_mwh": float(cell["soc_reset_discarded_mwh"].sum()),
    }


def capacity_for(rung: str, cfg: dict[str, Any]) -> float:
    return RUNGS_BY_NAME[rung].spec(cfg).energy_mwh


def point_table(ladder: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Every (leg, zone, year, rung, curve) cell's pooled numbers, one row each."""
    rows: list[dict[str, Any]] = []
    for (leg, zone, year, rung), group in ladder.groupby(
        ["leg", "zone", "year", "rung"], sort=True
    ):
        oracle = _cell_frame(ladder, leg, zone, year, rung, ORACLE_CURVE)
        if oracle.empty:
            raise SensitivityError(
                f"{leg}/{zone} {year}/{rung}: no oracle rows on the ladder-common days"
            )
        capacity = capacity_for(rung, cfg)
        for curve in sorted(group["curve"].unique()):
            cell = _cell_frame(ladder, leg, zone, year, rung, curve)
            if cell.empty:
                continue
            if list(cell["market_day"]) != list(oracle["market_day"]):
                raise SensitivityError(
                    f"{leg}/{zone} {year}/{rung}/{curve}: the curve and the oracle "
                    f"do not cover the same ladder-common days"
                )
            row = point_row(cell, oracle)
            row["equivalent_full_cycles"] = row["discharged_mwh"] / capacity
            rows.append({
                "leg": leg, "zone": zone, "year": int(year), "rung": rung,
                "lever": RUNGS_BY_NAME[rung].lever, "curve": curve,
                "tier": cell["tier"].iloc[0], "regime": cell["regime"].iloc[0],
                "model": cell["model"].iloc[0],
                "exog_variant": cell["exog_variant"].iloc[0],
                "vintage": cell["vintage"].iloc[0],
                "train_from": cell["train_from"].iloc[0],
                "capacity_mwh": capacity,
                **row,
            })
    return pd.DataFrame(rows)


def lever_contrast_rows(
    ladder: pd.DataFrame,
    contrasts: Sequence[tuple[str, str, str]],
    n_replicates: int,
    blocks: Sequence[int] = BLOCK_LADDER,
) -> pd.DataFrame:
    """Paired daily-block intervals on every single-lever capture delta.

    Paired in the strongest sense available here: the two rungs are the *same
    forecast on the same days*, so one draw of a day multiset is applied to both
    and the difference distribution carries none of the year-to-year or
    zone-to-zone variation they share. A capture ratio is a ratio of two day
    sums, so each replicate recomputes it by the same formula as the point
    estimate (``backtest.bootstrap.ratio_replicates``).
    """
    rows: list[dict[str, Any]] = []
    for (leg, zone, year), group in ladder.groupby(["leg", "zone", "year"], sort=True):
        available = set(group["rung"].unique())
        for curve in sorted(group["curve"].unique()):
            if curve == ORACLE_CURVE:
                continue
            for rung, baseline, question in contrasts:
                if rung not in available or baseline not in available:
                    continue
                treat = _cell_frame(ladder, leg, zone, year, rung, curve)
                base = _cell_frame(ladder, leg, zone, year, baseline, curve)
                treat_oracle = _cell_frame(ladder, leg, zone, year, rung, ORACLE_CURVE)
                base_oracle = _cell_frame(ladder, leg, zone, year, baseline, ORACLE_CURVE)
                days = list(base["market_day"])
                if not (list(treat["market_day"]) == days
                        == list(treat_oracle["market_day"]) == list(base_oracle["market_day"])):
                    raise SensitivityError(
                        f"{leg}/{zone} {year}/{curve}: {rung} and {baseline} do not "
                        f"cover the same ladder-common days — the pairing would be "
                        f"between different samples"
                    )
                n_days = len(days)
                span = (
                    dt.date.fromisoformat(days[-1]) - dt.date.fromisoformat(days[0])
                ).days + 1
                scale = 365.25 / span if span > 0 else float("nan")
                point_capture = (
                    treat["cash"].sum() / treat_oracle["cash"].sum()
                    - base["cash"].sum() / base_oracle["cash"].sum()
                )
                point_cash = float((treat["cash"].sum() - base["cash"].sum()) * scale)
                for block_days in blocks:
                    spec, counts = bootstrap_spec(
                        n_days, n_replicates, block_days
                    )
                    treat_rep = ratio_replicates(
                        treat["cash"].to_numpy(dtype=float),
                        treat_oracle["cash"].to_numpy(dtype=float), counts,
                    )
                    base_rep = ratio_replicates(
                        base["cash"].to_numpy(dtype=float),
                        base_oracle["cash"].to_numpy(dtype=float), counts,
                    )
                    interval = _interval(
                        float(point_capture), treat_rep - base_rep, spec
                    )
                    cash_rep = (
                        counts @ treat["cash"].to_numpy(dtype=float)
                        - counts @ base["cash"].to_numpy(dtype=float)
                    ) * scale
                    cash_interval = _interval(point_cash, cash_rep, spec)
                    rows.append({
                        "leg": leg, "zone": zone, "year": int(year), "curve": curve,
                        "rung": rung, "baseline": baseline,
                        "lever": RUNGS_BY_NAME[rung].lever, "question": question,
                        "block_days": block_days, "n_days": n_days,
                        "delta_capture_pp": 100.0 * interval.point,
                        "ci_low_pp": 100.0 * interval.ci_low,
                        "ci_high_pp": 100.0 * interval.ci_high,
                        "boot_sd_pp": 100.0 * interval.boot_sd,
                        "prob_le_zero": interval.prob_le_zero,
                        "excludes_zero": bool(
                            interval.ci_low > 0.0 or interval.ci_high < 0.0
                        ),
                        "delta_eur_per_mw_year": cash_interval.point,
                        "cash_ci_low": cash_interval.ci_low,
                        "cash_ci_high": cash_interval.ci_high,
                        "cash_excludes_zero": bool(
                            cash_interval.ci_low > 0.0 or cash_interval.ci_high < 0.0
                        ),
                    })
    return pd.DataFrame(rows)


def friction_decomposition(points: pd.DataFrame) -> pd.DataFrame:
    """NOTE C13-02's question: how much of the capture shortfall is friction?

    For one (zone, year, curve) the base rung's shortfall is ``1 - capture``.
    Removing the throughput cost removes the part of it that was a *cost of
    trading*; what is left is the part that is the forecast putting the hours in
    the wrong order, which no battery parameter can fix. The share is reported
    as a share of the shortfall rather than of the capture, because that is the
    quantity a desk would be deciding about.

    Cells whose perfect-foresight battery earns less than C13's declared thin-
    regime floor are marked, not dropped: a shortfall share with a near-zero
    denominator is not a share of anything (FLAG C13-01, NO2 2020).
    """
    wide = points[points["curve"] != ORACLE_CURVE].pivot_table(
        index=["leg", "zone", "year", "curve"], columns="rung",
        values=["capture", "oracle_cash_eur_per_mw_year", "cash_eur_per_mw_year",
                "equivalent_full_cycles"],
        aggfunc="first",
    )
    rows: list[dict[str, Any]] = []
    for key, row in wide.iterrows():
        leg, zone, year, curve = key
        base = row.get(("capture", BASE_RUNG), float("nan"))
        k0 = row.get(("capture", "throughput_0"), float("nan"))
        k5 = row.get(("capture", "throughput_5"), float("nan"))
        shortfall = 1.0 - base
        oracle_base = row.get(("oracle_cash_eur_per_mw_year", BASE_RUNG), float("nan"))
        rows.append({
            "leg": leg, "zone": zone, "year": int(year), "curve": curve,
            "capture_base": base, "capture_throughput_0": k0,
            "capture_throughput_5": k5,
            "shortfall_base_pp": 100.0 * shortfall,
            "friction_pp": 100.0 * (k0 - base),
            "friction_share_of_shortfall": (
                (k0 - base) / shortfall if abs(shortfall) > 1e-9 else float("nan")
            ),
            "residual_shortfall_at_zero_friction_pp": 100.0 * (1.0 - k0),
            "oracle_eur_per_mw_year_base": oracle_base,
            "oracle_eur_per_mw_year_throughput_0": row.get(
                ("oracle_cash_eur_per_mw_year", "throughput_0"), float("nan")
            ),
            "cycles_base": row.get(("equivalent_full_cycles", BASE_RUNG), float("nan")),
            "cycles_throughput_0": row.get(
                ("equivalent_full_cycles", "throughput_0"), float("nan")
            ),
            "thin_regime": bool(
                np.isfinite(oracle_base)
                and oracle_base < THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR
            ),
        })
    return pd.DataFrame(rows)


def no2_ordering_table(points: pd.DataFrame) -> dict[str, Any]:
    """NOTE C14-01, reported *and* labelled for what it can and cannot show.

    C14 predicted that NO2's within-day ordering would not improve at any rung.
    It cannot: the within-day Spearman is a function of the forecast and the
    realised prices, and no rung of this ladder touches either. So the
    invariance is **asserted** here (it is a property of the design, and a
    non-zero movement would mean the day sets had silently diverged, which is a
    bug), and the prediction's substantive form is tested instead: *if NO2's
    capture deficit were friction, removing the friction would close it.*
    """
    comparable = points[
        (points["leg"] == MAIN_LEG) & (points["curve"] == COMPARABLE_CURVE)
    ]
    if comparable.empty:
        raise SensitivityError("no comparable-curve rows: cannot answer NOTE C14-01")
    rows: list[dict[str, Any]] = []
    spearman_drift = 0.0
    for year in sorted(comparable["year"].unique()):
        year_rows = comparable[comparable["year"] == year]
        base_spearman = year_rows[
            (year_rows["zone"] == OUTLIER_ZONE) & (year_rows["rung"] == BASE_RUNG)
        ]["mean_spearman"]
        for rung in [r.name for r in LADDER if r.name in set(year_rows["rung"])]:
            no2 = year_rows[(year_rows["zone"] == OUTLIER_ZONE)
                            & (year_rows["rung"] == rung)]
            others = year_rows[(year_rows["zone"] != OUTLIER_ZONE)
                               & (year_rows["rung"] == rung)]
            if no2.empty or others.empty:
                continue
            thin = others["oracle_cash_eur_per_mw_year"] >= (
                THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR
            )
            no2_capture = float(no2["capture"].iloc[0])
            no2_spearman = float(no2["mean_spearman"].iloc[0])
            if not base_spearman.empty:
                spearman_drift = max(
                    spearman_drift, abs(no2_spearman - float(base_spearman.iloc[0]))
                )
            rows.append({
                "year": int(year), "rung": rung,
                "lever": RUNGS_BY_NAME[rung].lever,
                "no2_is_thin_regime": bool(
                    float(no2["oracle_cash_eur_per_mw_year"].iloc[0])
                    < THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR
                ),
                "no2_capture": no2_capture,
                "no2_mean_spearman": no2_spearman,
                "others_mean_capture": float(others.loc[thin, "capture"].mean()),
                "others_min_capture": float(others.loc[thin, "capture"].min()),
                "others_mean_spearman": float(others.loc[thin, "mean_spearman"].mean()),
                "capture_gap_pp": 100.0 * (
                    no2_capture - float(others.loc[thin, "capture"].mean())
                ),
                "spearman_gap": no2_spearman - float(
                    others.loc[thin, "mean_spearman"].mean()
                ),
                "no2_is_last_on_capture": bool(
                    no2_capture < float(others.loc[thin, "capture"].min())
                ),
                "no2_is_last_on_spearman": bool(
                    no2_spearman < float(others.loc[thin, "mean_spearman"].min())
                ),
                "n_other_zones_counted": int(thin.sum()),
            })
    table = pd.DataFrame(
        rows,
        columns=[
            "year", "rung", "lever", "no2_capture", "no2_mean_spearman",
            "others_mean_capture", "others_min_capture", "others_mean_spearman",
            "capture_gap_pp", "spearman_gap", "no2_is_last_on_capture",
            "no2_is_last_on_spearman", "n_other_zones_counted",
            "no2_is_thin_regime",
        ],
    )
    if table.empty:
        # A subset run (one zone, or a run without NO2) cannot answer NOTE
        # C14-01. Saying so beats inventing a row, and the full run always can.
        return {
            "table": table,
            "spearman_is_rung_invariant": {
                "applicable": False,
                "reason": f"{OUTLIER_ZONE} and at least one other zone are needed",
            },
            "note_c14_01": {
                "applicable": False,
                "reason": f"this run does not carry {OUTLIER_ZONE} beside other zones",
            },
        }
    # NO2's own thin-regime years are excluded from every mean below. In NO2
    # 2020 the perfect-foresight battery earns 769 EUR/MW/yr, the comparable arm
    # settles negative and capture is -0.52 (FLAG C13-01), so a *mean* gap that
    # includes it is reporting that one cell. Both versions are given.
    usable = table[~table["no2_is_thin_regime"]]
    base_gap = usable[usable["rung"] == BASE_RUNG]["capture_gap_pp"]
    k0_gap = usable[usable["rung"] == "throughput_0"]["capture_gap_pp"]
    all_base = table[table["rung"] == BASE_RUNG]["capture_gap_pp"]
    all_k0 = table[table["rung"] == "throughput_0"]["capture_gap_pp"]
    per_year = (
        usable[usable["rung"].isin([BASE_RUNG, "throughput_0"])]
        .pivot_table(index="year", columns="rung", values="capture_gap_pp")
    )
    closed_by_year = (
        (per_year["throughput_0"] - per_year[BASE_RUNG])
        if {BASE_RUNG, "throughput_0"} <= set(per_year.columns) else pd.Series(dtype=float)
    )
    share_by_year = (
        (closed_by_year / per_year[BASE_RUNG].abs())
        if not closed_by_year.empty else pd.Series(dtype=float)
    )
    return {
        "table": table,
        "spearman_is_rung_invariant": {
            "holds": bool(spearman_drift <= 1e-9),
            "worst_drift": float(spearman_drift),
            "why_it_cannot_fail": (
                "the within-day Spearman is computed from the forecast and the "
                "realised prices on the ladder-common days; no rung changes either, "
                "so a non-zero drift would mean two rungs were pooled over different "
                "day sets — a bug, not a result"
            ),
        },
        "note_c14_01": {
            "prediction_as_written": (
                "NO2's within-day ordering will not improve at any rung"
            ),
            "verdict": "untestable by this ladder, and asserted instead",
            "substantive_form_tested": (
                "if NO2's capture deficit were friction, removing the friction "
                "(throughput_0) would close it"
            ),
            "thin_regime_years_excluded_from_the_means": sorted(
                {int(y) for y in table.loc[table["no2_is_thin_regime"], "year"]}
            ),
            "mean_capture_gap_pp_at_base": float(base_gap.mean()) if len(base_gap) else None,
            "mean_capture_gap_pp_at_zero_friction": (
                float(k0_gap.mean()) if len(k0_gap) else None
            ),
            "gap_closed_pp": (
                float(k0_gap.mean() - base_gap.mean())
                if len(base_gap) and len(k0_gap) else None
            ),
            "share_of_the_gap_closed_by_removing_all_friction": (
                float((k0_gap.mean() - base_gap.mean()) / abs(base_gap.mean()))
                if len(base_gap) and len(k0_gap) and abs(base_gap.mean()) > 1e-9
                else None
            ),
            "gap_closed_pp_by_year": {
                int(y): float(v) for y, v in closed_by_year.items()
            },
            "share_of_the_gap_closed_by_year": {
                int(y): float(v) for y, v in share_by_year.items()
            },
            "mean_capture_gap_pp_at_base_including_thin_years": (
                float(all_base.mean()) if len(all_base) else None
            ),
            "gap_closed_pp_including_thin_years": (
                float(all_k0.mean() - all_base.mean())
                if len(all_base) and len(all_k0) else None
            ),
            "n_years": int(table["year"].nunique()) if not table.empty else 0,
            "n_usable_years": int(usable["year"].nunique()) if not usable.empty else 0,
            "n_rows_no2_last_on_capture": int(table["no2_is_last_on_capture"].sum()),
            "n_rows_no2_last_on_within_day_spearman": int(
                table["no2_is_last_on_spearman"].sum()
            ),
            "n_rows": int(len(table)),
            "n_years_no2_last_on_capture_at_zero_friction": int(
                table[(table["rung"] == "throughput_0")]["no2_is_last_on_capture"].sum()
            ),
        },
    }


#: PLAN.md's RES-forecast degradation contrast, in both model classes. The
#: direction is fixed: ``as_published`` minus ``persistence`` is the value of an
#: Art. 14 publication timestamp, and it is **not achievable** (FINDING C9-C).
RES_CONTRASTS: tuple[tuple[str, str, str], ...] = (
    ("lear_res_as_published", "lear_res_persistence",
     "PLAN.md's RES-forecast degradation, LEAR: what the Art. 14 vintage is worth"),
    ("gbm_res_as_published", "gbm_res_persistence",
     "PLAN.md's RES-forecast degradation, GBM: what the Art. 14 vintage is worth"),
)


def res_degradation_rows(
    ladder: pd.DataFrame, n_replicates: int, blocks: Sequence[int] = BLOCK_LADDER
) -> pd.DataFrame:
    """PLAN.md's RES-degradation sensitivity, at every rung of the ladder.

    The *curve* contrast (as-published minus persistence) is C8's and C9's
    experiment; what C15 adds is the same contrast measured in dispatch terms at
    each battery. The question it answers is narrow and worth stating plainly:
    *does the value of the Art. 14 leak depend on the friction, the duration or
    the SoC policy?* A leak worth nothing at every rung is a stronger version of
    FINDING C14-G than a leak worth nothing at one.
    """
    rows: list[dict[str, Any]] = []
    res = ladder[ladder["leg"] == RES_LEG]
    if res.empty:
        return pd.DataFrame(rows)
    for (zone, year, rung), group in res.groupby(["zone", "year", "rung"], sort=True):
        present = set(group["curve"].unique())
        oracle = _cell_frame(ladder, RES_LEG, zone, year, rung, ORACLE_CURVE)
        for late, honest, question in RES_CONTRASTS:
            if late not in present or honest not in present:
                continue
            a = _cell_frame(ladder, RES_LEG, zone, year, rung, late)
            b = _cell_frame(ladder, RES_LEG, zone, year, rung, honest)
            days = list(b["market_day"])
            if not (list(a["market_day"]) == days == list(oracle["market_day"])):
                raise SensitivityError(
                    f"{zone} {year}/{rung}: {late} and {honest} do not cover the "
                    f"same ladder-common days"
                )
            den = float(oracle["cash"].sum())
            point = (float(a["cash"].sum()) - float(b["cash"].sum())) / den
            hours_a = float(a["n_hours"].sum())
            hours_b = float(b["n_hours"].sum())
            for block_days in blocks:
                spec, counts = bootstrap_spec(
                    len(days), n_replicates, block_days
                )
                rep = (
                    ratio_replicates(a["cash"].to_numpy(dtype=float),
                                     oracle["cash"].to_numpy(dtype=float), counts)
                    - ratio_replicates(b["cash"].to_numpy(dtype=float),
                                       oracle["cash"].to_numpy(dtype=float), counts)
                )
                interval = _interval(point, rep, spec)
                rows.append({
                    "zone": zone, "year": int(year), "rung": rung,
                    "lever": RUNGS_BY_NAME[rung].lever,
                    "late_curve": late, "honest_curve": honest, "question": question,
                    "block_days": block_days, "n_days": len(days),
                    "delta_capture_pp": 100.0 * interval.point,
                    "ci_low_pp": 100.0 * interval.ci_low,
                    "ci_high_pp": 100.0 * interval.ci_high,
                    "boot_sd_pp": 100.0 * interval.boot_sd,
                    "prob_le_zero": interval.prob_le_zero,
                    "excludes_zero": bool(
                        interval.ci_low > 0.0 or interval.ci_high < 0.0
                    ),
                    "mae_late": float(a["sum_abs_error"].sum() / hours_a)
                    if hours_a > 0 else float("nan"),
                    "mae_honest": float(b["sum_abs_error"].sum() / hours_b)
                    if hours_b > 0 else float("nan"),
                    "mean_spearman_late": float(
                        np.nansum(a["spearman_contrib"]) / np.nansum(a["spearman_defined"])
                    ),
                    "mean_spearman_honest": float(
                        np.nansum(b["spearman_contrib"]) / np.nansum(b["spearman_defined"])
                    ),
                    "vintage_premium_pct_of_mae": (
                        100.0 * (float(b["sum_abs_error"].sum() / hours_b)
                                 - float(a["sum_abs_error"].sum() / hours_a))
                        / float(b["sum_abs_error"].sum() / hours_b)
                        if hours_a > 0 and hours_b > 0 else float("nan")
                    ),
                })
    return pd.DataFrame(rows)


def boundary_inventory_check(
    ladder: pd.DataFrame, cfg: dict[str, Any]
) -> pd.DataFrame:
    """The one objection every SoC-lever result has to answer before it is a result.

    The rungs end the year in different states: ``soc_no_terminal`` ends it empty,
    ``soc_daily_reset`` ends it half full, and ``base`` ends it holding whatever
    the trailing mark told the LP to hold. So part of any cash difference between
    two rungs is just inventory one run still owns and the other has already
    sold. This bounds that part generously — the net stored-energy difference
    valued at the **highest realised price of the whole evaluation year**, which
    is strictly more than it could ever have fetched — and puts it beside the
    measured difference. A difference that is an order of magnitude above the
    bound is not a boundary artefact; one that is not must be reported as
    inconclusive rather than as a finding.

    Reported for every non-base rung, not only the SoC ones: the throughput and
    duration rungs also end the year in their own states, and a reader should not
    have to take on trust that it does not matter there either.
    """
    del cfg  # the bound needs only the dispatched rows
    rows: list[dict[str, Any]] = []
    common = ladder[ladder["in_ladder_common_day_set"]]
    for (leg, zone, year, curve), group in common.groupby(
        ["leg", "zone", "year", "curve"], sort=True
    ):
        if curve == ORACLE_CURVE:
            continue
        rungs = {r: g.sort_values("market_day") for r, g in group.groupby("rung")}
        if BASE_RUNG not in rungs:
            continue
        base = rungs[BASE_RUNG]
        base_net = float(base["soc_end_mwh"].iloc[-1] - base["soc_start_mwh"].iloc[0])
        last_day_price = float(max(base["realised_price_max"].iloc[-1], 0.0))
        for name, other in sorted(rungs.items()):
            if name == BASE_RUNG:
                continue
            max_price = float(max(base["realised_price_max"].max(),
                                  other["realised_price_max"].max(), 0.0))
            other_net = float(
                other["soc_end_mwh"].iloc[-1] - other["soc_start_mwh"].iloc[0]
            )
            gap_mwh = abs(base_net - other_net)
            bound = gap_mwh * max_price
            # The tighter of the two bounds, and the natural one: the inventory
            # difference is realised (or not) at the *end* of the run, so the
            # last dispatched day's highest price is what it could have fetched.
            # The year's maximum is kept beside it as the strictly generous
            # version, and both are reported rather than one being chosen here.
            bound_last_day = gap_mwh * last_day_price
            delta = float(other["cash"].sum() - base["cash"].sum())
            rows.append({
                "leg": leg, "zone": zone, "year": int(year), "curve": curve,
                "rung": name, "lever": RUNGS_BY_NAME[name].lever,
                "cash_delta_eur": delta,
                "base_net_stored_mwh": base_net,
                "rung_net_stored_mwh": other_net,
                "inventory_gap_mwh": gap_mwh,
                "max_realised_price_eur_per_mwh": max_price,
                "last_day_max_price_eur_per_mwh": last_day_price,
                "boundary_inventory_bound_eur": bound,
                "boundary_inventory_bound_last_day_eur": bound_last_day,
                "delta_over_bound": (
                    abs(delta) / bound if bound > 1e-9 else float("inf")
                ),
                "delta_over_bound_last_day": (
                    abs(delta) / bound_last_day
                    if bound_last_day > 1e-9 else float("inf")
                ),
                "survives_boundary_objection": bool(abs(delta) > 10.0 * bound),
                "survives_boundary_objection_last_day": bool(
                    abs(delta) > 10.0 * bound_last_day
                ),
            })
    return pd.DataFrame(rows)


#: NOTE C13-02 names this cell as the throughput ladder's stress test: the
#: perfect-foresight battery earns 769 EUR/MW/yr there, the mean realised daily
#: spread is 3.41 EUR/MWh against a 2 EUR/MWh throughput cost, and the
#: comparable arm settles negative (FLAG C13-01). If a friction lever is ever
#: going to matter anywhere, it is here.
STRESS_CELL: tuple[str, int] = (OUTLIER_ZONE, 2020)


def stress_cell_report(points: pd.DataFrame) -> dict[str, Any]:
    """NOTE C13-02's named stress cell, every rung, every curve.

    Reported on its own rather than folded into a mean, because a capture ratio
    over a 769 EUR/MW/yr prize is not a draw from the same process as one over a
    74 000 EUR/MW/yr prize — which is the whole reason C13 declared a thin-regime
    floor instead of discovering one per table.
    """
    zone, year = STRESS_CELL
    cell = points[
        (points["leg"] == MAIN_LEG) & (points["zone"] == zone)
        & (points["year"] == year) & (points["curve"] != ORACLE_CURVE)
    ]
    if cell.empty:
        return {"applicable": False, "reason": f"{zone} {year} was not dispatched"}
    columns = [
        "rung", "lever", "curve", "capture", "cash_eur_per_mw_year",
        "oracle_cash_eur_per_mw_year", "eur_per_mw_year_lost",
        "equivalent_full_cycles", "mean_realised_spread", "mean_spearman",
        "n_days_cash_negative",
    ]
    base = cell[cell["rung"] == BASE_RUNG]
    k0 = cell[cell["rung"] == "throughput_0"]
    return {
        "applicable": True,
        "zone": zone, "year": year,
        "note_c13_02": (
            "the stress cell for the friction ladder: the thinnest market in the "
            "sample, below C13's declared thin-regime floor, and the cell that "
            "raised FLAG C13-01"
        ),
        "is_below_the_thin_regime_floor": bool(
            not base.empty
            and base["oracle_cash_eur_per_mw_year"].iloc[0]
            < THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR
        ),
        "rows": cell[columns].sort_values(["curve", "rung"]).to_dict("records"),
        "comparable_capture_base": (
            float(base[base["curve"] == COMPARABLE_CURVE]["capture"].iloc[0])
            if not base[base["curve"] == COMPARABLE_CURVE].empty else None
        ),
        "comparable_capture_at_zero_friction": (
            float(k0[k0["curve"] == COMPARABLE_CURVE]["capture"].iloc[0])
            if not k0[k0["curve"] == COMPARABLE_CURVE].empty else None
        ),
        "best_capture_over_every_rung": (
            float(cell[cell["curve"] == COMPARABLE_CURVE]["capture"].max())
            if not cell[cell["curve"] == COMPARABLE_CURVE].empty else None
        ),
        "best_rung_for_the_comparable_arm": (
            str(cell[cell["curve"] == COMPARABLE_CURVE]
                .sort_values("capture", ascending=False)["rung"].iloc[0])
            if not cell[cell["curve"] == COMPARABLE_CURVE].empty else None
        ),
    }


def contrast_summary(contrasts: pd.DataFrame, block_days: int = HEADLINE_BLOCK
                     ) -> pd.DataFrame:
    """Per lever contrast: the cross-cell spread and how many cells decide a sign."""
    if contrasts.empty:
        return pd.DataFrame()
    at_block = contrasts[contrasts["block_days"] == block_days]
    rows: list[dict[str, Any]] = []
    for (leg, curve, rung), group in at_block.groupby(
        ["leg", "curve", "rung"], sort=True
    ):
        rows.append({
            "leg": leg, "curve": curve, "rung": rung,
            "lever": RUNGS_BY_NAME[rung].lever,
            "block_days": block_days,
            "n_cells": int(len(group)),
            "mean_delta_capture_pp": float(group["delta_capture_pp"].mean()),
            "median_delta_capture_pp": float(group["delta_capture_pp"].median()),
            "min_delta_capture_pp": float(group["delta_capture_pp"].min()),
            "max_delta_capture_pp": float(group["delta_capture_pp"].max()),
            "n_cells_excluding_zero": int(group["excludes_zero"].sum()),
            "n_cells_positive": int((group["delta_capture_pp"] > 0).sum()),
            "mean_delta_eur_per_mw_year": float(group["delta_eur_per_mw_year"].mean()),
            "n_cells_cash_excluding_zero": int(group["cash_excludes_zero"].sum()),
            "median_abs_delta_over_sd": float(
                (group["delta_capture_pp"].abs() / group["boot_sd_pp"]).median()
            ),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

FIGURES_DIR = RESULTS_DIR.parent.parent / "docs" / "figures"


def write_figures(points: pd.DataFrame, friction: pd.DataFrame) -> list[str]:
    """Three figures, each answering one of PLAN.md's four sensitivities."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    comparable = points[
        (points["leg"] == MAIN_LEG) & (points["curve"] == COMPARABLE_CURVE)
    ]
    zones_sorted = sorted(comparable["zone"].unique())

    # (1) capture against the throughput cost, one line per zone, one panel per year
    cost_of = {
        BASE_RUNG: 2.0, "throughput_0": 0.0, "throughput_5": 5.0,
    }
    years = sorted(comparable["year"].unique())
    fig, axes = plt.subplots(1, len(years), figsize=(3.1 * len(years), 3.6),
                             sharey=True)
    axes = np.atleast_1d(axes)
    for ax, year in zip(axes, years):
        for zone in zones_sorted:
            sub = comparable[(comparable["year"] == year)
                             & (comparable["zone"] == zone)
                             & comparable["rung"].isin(cost_of)]
            if sub.empty:
                continue
            sub = sub.assign(k=sub["rung"].map(cost_of)).sort_values("k")
            style = dict(marker="o", ms=3.5, lw=1.4)
            if zone == OUTLIER_ZONE:
                style.update(color="black", lw=2.2, zorder=5)
            ax.plot(sub["k"], sub["capture"], label=zone, **style)
        ax.set_title(str(year), fontsize=10)
        ax.set_xlabel("throughput cost (EUR/MWh)")
        ax.set_xticks([0, 2, 5])
        ax.grid(alpha=0.25, lw=0.5)
        # NO2 2020's capture runs from -1.07 to +0.11 (the thin-regime cell,
        # FLAG C13-01). On a shared axis it flattens the other four panels into
        # a line, so the axis is clipped and the off-scale points are named
        # rather than dropped — the panel must not look like it has fewer zones.
        ax.set_ylim(0.0, 1.0)
        below = comparable[(comparable["year"] == year)
                           & comparable["rung"].isin(cost_of)
                           & (comparable["capture"] < 0.0)]
        if not below.empty:
            names = ", ".join(sorted(below["zone"].unique()))
            ax.annotate(
                f"{names} below axis\n(min {below['capture'].min():.2f})",
                xy=(0.04, 0.04), xycoords="axes fraction", fontsize=7,
                color="black",
            )
    axes[0].set_ylabel("capture ratio (settled / rolled oracle cash)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=9, fontsize=7.5,
               frameon=False, bbox_to_anchor=(0.5, -0.03))
    fig.suptitle(
        "C15: the capture ratio against the throughput cost — the comparable LEAR, "
        "nine zones\n(NO2 in black; the y axis is clipped to [0, 1] and the "
        "thin-regime cell NO2 2020, which runs to −1.07, is named in its panel)",
        fontsize=9)
    fig.tight_layout(rect=(0, 0.06, 1, 0.92))
    path = FIGURES_DIR / "c15_capture_vs_throughput_cost.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    written.append(path.name)

    # (2) every rung's capture delta against base, per zone, pooled over years.
    # Thin-regime (zone, year) cells are excluded, exactly as they are from every
    # other band statistic in this cycle: NO2 2020's capture runs from -1.07 to
    # +0.11, so leaving it in would draw a chart about one cell.
    thin_cells = {
        (row["zone"], int(row["year"]))
        for _, row in friction[(friction["leg"] == MAIN_LEG)
                               & friction["thin_regime"]].iterrows()
    }
    deltas = []
    for rung in [r.name for r in LADDER if not r.is_base]:
        for zone in zones_sorted:
            base = comparable[(comparable["zone"] == zone)
                              & (comparable["rung"] == BASE_RUNG)]
            other = comparable[(comparable["zone"] == zone)
                               & (comparable["rung"] == rung)]
            joined = base.merge(other, on=["zone", "year"], suffixes=("_b", "_r"))
            joined = joined[[
                (z, int(y)) not in thin_cells
                for z, y in zip(joined["zone"], joined["year"])
            ]]
            if joined.empty:
                continue
            deltas.append({
                "rung": rung, "zone": zone,
                "delta_pp": 100.0 * float(
                    (joined["capture_r"] - joined["capture_b"]).mean()
                ),
            })
    frame = pd.DataFrame(deltas)
    fig, ax = plt.subplots(figsize=(9.5, 4.0))
    rung_names = [r.name for r in LADDER if not r.is_base]
    width = 0.8 / max(len(zones_sorted), 1)
    for i, zone in enumerate(zones_sorted):
        sub = frame[frame["zone"] == zone].set_index("rung").reindex(rung_names)
        ax.bar(np.arange(len(rung_names)) + i * width - 0.4 + width / 2,
               sub["delta_pp"].to_numpy(dtype=float), width=width, label=zone)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(np.arange(len(rung_names)))
    ax.set_xticklabels(rung_names, fontsize=8)
    ax.set_ylabel("mean capture delta vs base (pp)")
    ax.grid(axis="y", alpha=0.25, lw=0.5)
    ax.legend(ncol=9, fontsize=7.5, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.12))
    ax.set_title(
        "C15: each lever's effect on the capture ratio, mean over 2020-2024 — "
        "the comparable LEAR\n(thin-regime cells excluded, so NO2 is a four-year "
        "mean; cash effects are in c15_lever_summary.csv)", fontsize=9)
    fig.tight_layout()
    path = FIGURES_DIR / "c15_lever_effects.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    written.append(path.name)

    # (3) the friction share of the shortfall
    usable = friction[(friction["leg"] == MAIN_LEG)
                      & (friction["curve"] == COMPARABLE_CURVE)
                      & ~friction["thin_regime"]]
    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    for zone in zones_sorted:
        sub = usable[usable["zone"] == zone].sort_values("year")
        if sub.empty:
            continue
        style = dict(marker="o", ms=4, lw=1.4)
        if zone == OUTLIER_ZONE:
            style.update(color="black", lw=2.2, zorder=5)
        ax.plot(sub["year"], 100.0 * sub["friction_share_of_shortfall"],
                label=zone, **style)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("friction share of the capture shortfall (%)")
    ax.set_xlabel("evaluation year")
    ax.set_xticks(sorted(usable["year"].unique()))
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(ncol=9, fontsize=7.5, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.14))
    ax.set_title(
        "C15: how much of the capture shortfall disappears when the throughput "
        "cost is removed\n(NOTE C13-02; thin-regime cells excluded)", fontsize=10)
    fig.tight_layout()
    path = FIGURES_DIR / "c15_friction_share_of_shortfall.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    written.append(path.name)
    return written


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

#: The per-rung level metrics, as ``(column, metric stem)``. The rung goes in the
#: metric *name* because ``scope`` is a closed list and the store's extension
#: point is the metric name (``docs/results_store.md``) — so a C15 row needs no
#: schema change, exactly as C11's, C12's and C13's did not.
LEVEL_METRICS: tuple[tuple[str, str], ...] = (
    ("capture", "capture"),
    ("cash_eur_per_mw_year", "eur_per_mw_year"),
    ("eur_per_mw_year_lost", "eur_per_mw_year_lost"),
    ("equivalent_full_cycles", "cycles"),
    ("mean_spearman", "within_day_spearman"),
)

#: The delta metrics, written for every lever contrast at the headline block.
DELTA_METRICS: tuple[tuple[str, str], ...] = (
    ("delta_capture_pp", "capture_pp"),
    ("ci_low_pp", "capture_pp_ci_low"),
    ("ci_high_pp", "capture_pp_ci_high"),
    ("delta_eur_per_mw_year", "eur_per_mw_year"),
)


def store_rows(points: pd.DataFrame, contrasts: pd.DataFrame) -> list[ResultRow]:
    """Long-format rows: one per (zone, curve, year, rung, metric).

    Levels for every rung, deltas against ``base`` for every lever. The metric
    name carries the rung, which keeps ``ResultRow.key()`` unique without a new
    column — a new rung is a new metric name, never a migration.
    """
    rows: list[ResultRow] = []
    for _, row in points.iterrows():
        if row["curve"] == ORACLE_CURVE:
            continue
        for column, stem in LEVEL_METRICS:
            value = row[column]
            if not np.isfinite(value):
                continue
            rows.append(ResultRow(
                zone=row["zone"], tier=row["tier"], model=row["model"],
                metric=f"c15_{row['rung']}_{stem}", value=float(value),
                scope="common_hours", vintage=row["vintage"],
                evaluation_years=str(int(row["year"])), regime=row["regime"],
                exog_variant=row["exog_variant"],
                train_from=str(row["train_from"]),
                n=str(int(row["n_days"])),
                source_artefact=daily_path(row["leg"], row["zone"],
                                           int(row["year"])).name,
                source_cycle="C15",
            ))
    at_block = contrasts[contrasts["block_days"] == HEADLINE_BLOCK]
    for _, row in at_block.iterrows():
        point = points[
            (points["leg"] == row["leg"]) & (points["zone"] == row["zone"])
            & (points["year"] == row["year"]) & (points["rung"] == row["rung"])
            & (points["curve"] == row["curve"])
        ]
        if point.empty:
            continue
        meta = point.iloc[0]
        for column, stem in DELTA_METRICS:
            value = row[column]
            if not np.isfinite(value):
                continue
            rows.append(ResultRow(
                zone=row["zone"], tier=meta["tier"], model=meta["model"],
                metric=f"c15_d_{row['rung']}_{stem}", value=float(value),
                scope="common_hours", vintage=meta["vintage"],
                evaluation_years=str(int(row["year"])), regime=meta["regime"],
                exog_variant=meta["exog_variant"],
                train_from=str(meta["train_from"]),
                n=str(int(row["n_days"])),
                source_artefact="c15_lever_contrasts.csv",
                source_cycle="C15",
            ))
    return rows


# ---------------------------------------------------------------------------
# Phase `analyse`
# ---------------------------------------------------------------------------


def analyse(args: argparse.Namespace) -> int:
    zones = list(selected_zones(args.zones))
    cfg = load_battery_config()
    ladder = load_ladder(args.legs, zones, args.years)
    print(f"ladder: {len(ladder):,} per-day rows, "
          f"{ladder['rung'].nunique()} rung(s), {ladder['zone'].nunique()} zone(s), "
          f"{ladder['year'].nunique()} year(s), {ladder['curve'].nunique()} curve(s)")

    reproduction = check_baseline_reproduction(ladder)
    print(f"base-rung reproduction: {reproduction['n_rows_compared']:,} rows, worst "
          f"cash gap {reproduction['worst_abs_cash_gap_eur']:.3g} EUR, "
          f"holds={reproduction['holds']}")
    if not reproduction["holds"]:
        raise SensitivityError(
            f"the base rung does not reproduce the committed per-day cash (worst "
            f"{reproduction['worst_abs_cash_gap_eur']:.6g} EUR) — every delta in "
            f"this cycle would be a delta against a re-implementation"
        )

    res_reproduction = check_res_leg_reproduction(ladder)
    if res_reproduction.get("applicable", True):
        print(f"RES-leg reproduction: {res_reproduction['n_rows_compared']:,} rows over "
              f"{res_reproduction['n_curves_compared']} curve(s), worst cash gap "
              f"{res_reproduction['worst_abs_cash_gap_eur']:.3g} EUR, "
              f"holds={res_reproduction['holds']}")
        if not res_reproduction["holds"]:
            raise SensitivityError(
                f"the RES leg's base rung does not reproduce C11's committed per-day "
                f"cash (worst {res_reproduction['worst_abs_cash_gap_eur']:.6g} EUR)"
            )

    points = point_table(ladder, cfg)
    points.to_csv(RESULTS_DIR / "c15_rung_points.csv", index=False)
    contrasts = lever_contrast_rows(ladder, LEVER_CONTRASTS, args.replicates)
    contrasts.to_csv(RESULTS_DIR / "c15_lever_contrasts.csv", index=False)
    summary_table = contrast_summary(contrasts)
    summary_table.to_csv(RESULTS_DIR / "c15_lever_summary.csv", index=False)
    friction = friction_decomposition(points)
    friction.to_csv(RESULTS_DIR / "c15_friction_decomposition.csv", index=False)
    res = res_degradation_rows(ladder, args.replicates)
    if not res.empty:
        res.to_csv(RESULTS_DIR / "c15_res_degradation.csv", index=False)
    no2 = no2_ordering_table(points)
    no2["table"].to_csv(RESULTS_DIR / "c15_no2_ordering.csv", index=False)
    boundary = boundary_inventory_check(ladder, cfg)
    boundary.to_csv(RESULTS_DIR / "c15_boundary_inventory.csv", index=False)
    stress = stress_cell_report(points)

    comparable = friction[(friction["leg"] == MAIN_LEG)
                          & (friction["curve"] == COMPARABLE_CURVE)
                          & ~friction["thin_regime"]]
    print("\nfriction share of the capture shortfall, comparable LEAR, "
          f"{len(comparable)} usable (zone, year) cells:")
    print(f"  mean {comparable['friction_share_of_shortfall'].mean():.3f}  "
          f"median {comparable['friction_share_of_shortfall'].median():.3f}  "
          f"range [{comparable['friction_share_of_shortfall'].min():.3f}, "
          f"{comparable['friction_share_of_shortfall'].max():.3f}]")
    print("\nlever summary at the headline (1-day) block, comparable LEAR:")
    for _, row in summary_table[
        (summary_table["leg"] == MAIN_LEG)
        & (summary_table["curve"] == COMPARABLE_CURVE)
    ].iterrows():
        print(f"  {row['rung']:<16} mean {row['mean_delta_capture_pp']:+7.2f}pp  "
              f"range [{row['min_delta_capture_pp']:+7.2f}, "
              f"{row['max_delta_capture_pp']:+7.2f}]  "
              f"{int(row['n_cells_excluding_zero'])}/{int(row['n_cells'])} cells "
              f"exclude zero  mean {row['mean_delta_eur_per_mw_year']:+9,.0f} EUR/MW/yr")

    figures = write_figures(points, friction)
    flags_path = RESULTS_DIR / INVARIANT_FLAGS
    flags = json.loads(flags_path.read_text()) if flags_path.exists() else {}

    summary = {
        "cycle": "C15",
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "library_versions": library_versions(),
        "ladder": [rung.as_dict() for rung in LADDER],
        "battery_specs": {
            rung.name: rung.spec(cfg).as_dict() for rung in LADDER
        },
        "legs": list(args.legs),
        "years": {MAIN_LEG: list(LADDER_YEARS), RES_LEG: list(RES_YEARS)},
        "n_per_day_rows": int(len(ladder)),
        "n_cells": int(ladder.groupby(["leg", "zone", "year"]).ngroups),
        "bootstrap": {
            "n_replicates": int(args.replicates), "seed": SEED,
            "block_ladder": list(BLOCK_LADDER), "headline_block_days": HEADLINE_BLOCK,
            "pairing": (
                "one day multiset per replicate, applied to both rungs of a "
                "contrast — the two rungs are the same forecast on the same days, "
                "so the difference distribution carries none of the variation they "
                "share"
            ),
            "warning": (
                "a wider block does not mean a wider interval at n = 365 (C12); the "
                "ladder is a robustness check, not an ordering — read the rung least "
                "favourable to the claim"
            ),
        },
        "baseline_reproduction": reproduction,
        "res_leg_reproduction": res_reproduction,
        "friction": {
            "note_c13_02": (
                "the throughput-cost ladder is a friction measurement, not NO2's "
                "mechanism test — FINDING C13-E settled that"
            ),
            "n_usable_cells": int(len(comparable)),
            "mean_friction_share_of_shortfall": float(
                comparable["friction_share_of_shortfall"].mean()
            ),
            "median_friction_share_of_shortfall": float(
                comparable["friction_share_of_shortfall"].median()
            ),
            "min_friction_share_of_shortfall": float(
                comparable["friction_share_of_shortfall"].min()
            ),
            "max_friction_share_of_shortfall": float(
                comparable["friction_share_of_shortfall"].max()
            ),
            "mean_residual_shortfall_at_zero_friction_pp": float(
                comparable["residual_shortfall_at_zero_friction_pp"].mean()
            ),
            "thin_regime_cells_excluded": friction[
                (friction["leg"] == MAIN_LEG)
                & (friction["curve"] == COMPARABLE_CURVE)
                & friction["thin_regime"]
            ][["zone", "year", "oracle_eur_per_mw_year_base"]].to_dict("records"),
            "thin_regime_floor_eur_per_mw_year": (
                THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR
            ),
        },
        "lever_summary": summary_table.to_dict("records"),
        "stress_cell": stress,
        "boundary_inventory": {
            "why": (
                "two rungs end the year in different states — `soc_no_terminal` "
                "empty, `soc_daily_reset` half full, `base` holding whatever the "
                "trailing mark told it to hold — so part of any cash difference is "
                "inventory one run still owns. This bounds that part at the year's "
                "highest realised price, which is strictly generous."
            ),
            "n_cells": int(len(boundary)),
            "n_cells_surviving": int(boundary["survives_boundary_objection"].sum())
            if not boundary.empty else 0,
            "per_rung": (
                boundary.groupby("rung").agg(
                    n_cells=("delta_over_bound", "size"),
                    n_surviving=("survives_boundary_objection", "sum"),
                    median_delta_over_bound=("delta_over_bound", "median"),
                    min_delta_over_bound=("delta_over_bound", "min"),
                    n_surviving_last_day=(
                        "survives_boundary_objection_last_day", "sum"
                    ),
                    median_delta_over_bound_last_day=(
                        "delta_over_bound_last_day", "median"
                    ),
                    min_delta_over_bound_last_day=(
                        "delta_over_bound_last_day", "min"
                    ),
                ).reset_index().to_dict("records")
                if not boundary.empty else []
            ),
            "median_delta_over_bound": float(
                boundary.loc[np.isfinite(boundary["delta_over_bound"]),
                             "delta_over_bound"].median()
            ) if not boundary.empty else None,
            "min_delta_over_bound": float(
                boundary.loc[np.isfinite(boundary["delta_over_bound"]),
                             "delta_over_bound"].min()
            ) if not boundary.empty else None,
        },
        "no2_ordering": {
            "spearman_is_rung_invariant": no2["spearman_is_rung_invariant"],
            "note_c14_01": no2["note_c14_01"],
        },
        "res_degradation": {
            "n_rows": int(len(res)),
            "note_c14_06": (
                "NOTE C8-01 is closed (FINDING C14-G), so C15 adds no exogenous "
                "model arm; this leg re-dispatches C8's and C9's committed "
                "forecasts to ask whether the Art. 14 leak's *dispatch* value "
                "depends on the battery"
            ),
            "headline": (
                res[(res["block_days"] == HEADLINE_BLOCK)]
                [["zone", "year", "rung", "late_curve", "delta_capture_pp",
                  "ci_low_pp", "ci_high_pp", "excludes_zero"]].to_dict("records")
                if not res.empty else []
            ),
        },
        "invariant_flags": flags,
        "figures": figures,
        "artefacts": [
            "c15_rung_points.csv", "c15_lever_contrasts.csv", "c15_lever_summary.csv",
            "c15_friction_decomposition.csv", "c15_no2_ordering.csv",
            "c15_boundary_inventory.csv",
            *(["c15_res_degradation.csv"] if not res.empty else []),
        ],
    }
    out = RESULTS_DIR / "c15_sensitivity_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"\nsummary -> {out.name}; figures: {', '.join(figures)}")

    if args.no_append:
        print("--no-append: the results store was not touched")
        return 0
    rows = store_rows(points, contrasts)
    before = verify_append_only(
        path=args.results_path, runs_path=args.runs_path
    )
    print(f"verify_append_only (before): {before['n_runs']} run(s), "
          f"{before['n_rows']:,} row(s), verified={before['verified']}")
    if not before["verified"]:
        raise SensitivityError(
            f"the results store is not append-only as committed: {before}"
        )
    report = append_rows(
        rows, cycle="C15", git_sha=git_sha(), config_hash=config_hash(),
        path=args.results_path, runs_path=args.runs_path,
        argv=sys.argv, note="C15 sensitivities: six batteries, one set of forecasts",
    )
    print(f"store: appended {report.n_rows_appended:,} row(s) "
          f"({report.n_rows_before:,} -> {report.n_rows_before + report.n_rows_appended:,})"
          f" as run {report.run_id}")
    after = verify_append_only(path=args.results_path, runs_path=args.runs_path)
    print(f"verify_append_only (after): {after['n_runs']} run(s), "
          f"{after['n_rows']:,} row(s), verified={after['verified']}")
    if not after["verified"]:
        raise SensitivityError(f"the append broke the append-only guarantee: {after}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.phase == "verify":
        return verify(args)
    if args.phase == "dispatch":
        return dispatch(args)
    if args.phase == "analyse":
        return analyse(args)
    status = verify(args)
    if status:
        return status
    status = dispatch(args)
    if status:
        return status
    return analyse(args)


if __name__ == "__main__":
    raise SystemExit(main())
