"""CLI: the C12 run — the metrics layer, and the block bootstrap that decides C11.

    python -m backtest.run_c12_metrics                    # all nine zones
    python -m backtest.run_c12_metrics --zones DE-LU ES    # a subset
    python -m backtest.run_c12_metrics --replicates 2000   # faster, wider MC error
    python -m backtest.run_c12_metrics --no-append         # compute, write no store rows

PLAN.md C12: *"Metrics layer: MAE, RMSE, rMAE vs naive, daily-spread error,
within-day Spearman; capture ratio; EUR/MW/yr; block-bootstrap CIs over daily
blocks."*

NOTE C11-01 is blunt about which half of that sentence matters: **this is not a
formatting cycle.** Every C11 headline is one validation year and either n = 9
zones or n = 15 paired comparisons, with most capture deltas under one
percentage point, and three specific questions have to be answered before C18
quotes any of them:

(i)   is FINDING C11-A's eight-zone 8.3pp capture band (NO2 excluded) wider
      than noise?
(ii)  is FINDING C11-D's near-zero MAE/capture rank correlation distinguishable
      from a real relationship?
(iii) does the GBM-exogenous capture gain (+2.04 / +2.71pp) survive a CI?

Nothing is re-fitted and nothing is re-dispatched. Every number here is built
from two committed artefacts — C11's per-day dispatch table
(``c11_capture_daily_2024.csv.gz``) and the per-cycle prediction files C4/C8/C9/
C10 committed — so a C12 interval is an interval around a C11 point estimate and
cannot be an interval around a different number. The point estimates are
**reproduction-checked against the store** before any interval is reported: if
C12's recomputed ``capture_rolled_oracle_cash`` and ``mae_on_dispatched_hours``
do not reproduce C11's committed rows, the run fails rather than quietly
reporting a CI around a number nobody published.

What is new, and what is only newly bounded
-------------------------------------------
**New metrics** (PLAN.md's decision-relevant pair, neither of which existed
before this cycle): the daily-spread error — how wrong the forecast was about
the day's trough-to-peak *headroom*, which is the size of the prize — and the
within-day Spearman — whether it put the hours in the right *order*, which is
the only thing the dispatch LP reads off a curve. Both are per-market-day by
construction (:func:`backtest.metrics.daily_shape_table`) and are computed on
**exactly the hours the capture ratio is pooled over**, which is the discipline
C11 imposed on its paired MAE and the only way the comparison is not an artefact
of two samples.

**Newly bounded**: the capture ratio, EUR/MW/yr, the point error and every arm
contrast, each with a daily-block bootstrap interval. See
:mod:`backtest.bootstrap` for the four design decisions that move an interval —
paired draws, circular moving blocks with the block length reported, statistics
built from day-additive columns, and percentile intervals whose approximate
coverage is stated rather than decorated away.

Which scope, and which ratio
----------------------------
FINDING C11-C decided the ratio: the headline is
``capture_rolled_oracle_cash`` — settled cash over the **rolled**
perfect-foresight run's cash on the same days, one denominator per zone and
therefore comparable across curves. ``capture_same_start_pooled`` is the exact
per-day bound and must never rank two curves, so C12 bootstraps the rolled
ratio and leaves the same-start distribution as the per-day artefact C11 already
committed.

NOTE C10-01 decided the scope, and C12 keeps it: the within-zone arm comparison
is read at ``common_hours`` (the intersection of the days every curve of that
zone dispatched), and the cross-zone table at ``own_coverage``. Those are the
two bootstrap bases:

``basis_common[zone]``
    the zone's ``in_common_day_set`` days — 365 in every zone but ES, 357 there
    (ES's exogenous join has 145 missing hours, so its two ``res_*`` arms
    decline eight days the others dispatch).
``basis_cross``
    the 365 days the nine-zone comparable arm dispatched. Verified to be the
    **same calendar days in all nine zones**, which is what lets one draw be
    applied to every zone at once and makes the cross-zone band a paired
    statistic rather than nine independent ones.

ES's 357-day basis is a subset of the 365-day cross-zone basis, so the
FINDING C11-D correlation — which needs one draw spanning all three Tier-A
zones — draws on the 365-day basis and projects onto each zone's own day set.
ES therefore contributes ~357/365 of each replicate's draws, which widens its
own interval slightly and is reported rather than hidden.

Nothing here reads 2025. No price file is opened at all (the realised prices
come from the committed artefacts' ``y_true``), the store refuses a row whose
``evaluation_years`` touches a sealed year, and the run asserts the guard is
armed before and after.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from backtest.bootstrap import (
    BLOCK_LADDER,
    BlockBootstrapSpec,
    BootstrapError,
    DEFAULT_REPLICATES,
    DEFAULT_SEED,
    Interval,
    difference_interval,
    mean_replicates,
    noise_only_spread,
    ratio_replicates,
    replicate_counts,
    spearman_rows,
    _interval,
)
from backtest.metrics import daily_shape_table, shape_scores
from backtest.results_store import (
    ResultRow,
    append_rows,
    latest_results,
    library_versions,
    read_results,
    verify_append_only,
)
from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.run_c11_dispatch import (
    CONTRASTS,
    ORACLE_MODEL,
    ORACLE_VARIANT,
    Arm,
    arms_for,
)
from data.config import (
    REPO_ROOT,
    config_hash,
    load_battery_config,
    load_zones,
    sealed_years,
)
from data.holdout import assert_not_sealed, holdout_is_unsealed

#: C11's per-day dispatch artefact: one row per (zone, curve, dispatched day),
#: with both oracle ceilings, both capture ratios and the realised spread. The
#: file C12 bootstraps over, in the shape a daily-block bootstrap needs.
C11_DAILY = "c11_capture_daily_2024.csv.gz"

#: The curve every capture ratio is a fraction of. Carries no forecast error, so
#: it gets dispatch metrics and no point-error or shape metrics.
ORACLE_CURVE = "oracle"

#: The naive floor: the denominator of every rMAE, in every zone.
NAIVE_CURVE = "naive"

#: The nine-zone like-for-like arm (FINDING C10-B / C11-A's cross-zone table).
COMPARABLE_CURVE = "lear_full_history"

#: The zone FINDING C11-B singles out. The cross-zone band is reported with and
#: without it because C11 found the 30.4pp band is substantially this one zone.
OUTLIER_ZONE = "NO2"

#: FINDING C11-D's honest comparisons: the five of C11's seven contrasts that a
#: bidder could actually have had. The two ``res_as_published`` contrasts measure
#: the Art. 14 leak (FINDING C9-C) and are bootstrapped too, but they never
#: enter the rank correlation — a correlation that included an unachievable arm
#: would not be a statement about model choice.
HONEST_CONTRASTS: tuple[tuple[str, str], ...] = tuple(
    (treatment, baseline)
    for treatment, baseline, _ in CONTRASTS
    if "as_published" not in treatment
)

#: Metrics whose interval is a ratio of two day-additive columns.
RATIO_METRICS: tuple[tuple[str, str, str], ...] = (
    ("capture_rolled_oracle_cash", "cash", "oracle_cash"),
    ("mae_on_dispatched_hours", "sum_abs_error", "n_hours"),
    ("bias_on_dispatched_hours", "sum_error", "n_hours"),
    ("within_day_spearman_mean", "spearman_contrib", "spearman_defined"),
)

#: Metrics whose interval is the mean of a day-additive column, annualised.
ANNUALISED_METRICS: tuple[tuple[str, str], ...] = (
    ("dispatch_cash_eur_per_mw_year", "cash"),
    ("eur_per_mw_year_lost_vs_oracle", "lost"),
)

#: Metrics whose interval is a plain mean of a per-day column.
MEAN_METRICS: tuple[tuple[str, str], ...] = (
    ("daily_spread_mae_eur_per_mwh", "abs_spread_error"),
    ("daily_spread_bias_eur_per_mwh", "spread_error"),
    ("realised_spread_mean_eur_per_mwh", "realised_spread"),
)

#: Point-estimate-only metrics: order statistics of a per-day distribution are
#: not day-additive, so :mod:`backtest.bootstrap` deliberately will not
#: resample them (C11 already persists the distribution in full).
POINT_ONLY_METRICS: tuple[str, ...] = (
    "within_day_spearman_median",
    "within_day_spearman_p05",
    "daily_spread_rmse_eur_per_mwh",
    "n_days_spearman_undefined",
)


class MetricsRunError(RuntimeError):
    """A C12 input does not support the metric or the interval being asked for."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None, help="zone keys (default: all)")
    parser.add_argument("--years", nargs="*", type=int, default=[2024])
    parser.add_argument(
        "--replicates", type=int, default=DEFAULT_REPLICATES,
        help=f"bootstrap replicates (default {DEFAULT_REPLICATES})",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--block-days", type=int, default=None,
        help="headline block length in days (default 1, PLAN.md's 'daily blocks')",
    )
    parser.add_argument(
        "--no-append", action="store_true",
        help="compute and write artefacts but append no store rows",
    )
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# The per-day table: C11's dispatch columns joined to the shape columns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurveDays:
    """One ``(zone, curve)``'s per-day columns, indexed by ``market_day``.

    Every column here is **day-additive**: a pooled metric over any set of these
    days is a ratio of two column sums or the mean of one, which is exactly what
    makes the bootstrap a resample of rows (see :mod:`backtest.bootstrap`). The
    identity of each column is the point — ``sum_abs_error`` rather than a
    per-day MAE, because a mean of per-day MAEs is not the pooled MAE when days
    have different hour counts, and DST days do.
    """

    zone: str
    curve: str
    tier: str
    regime: str
    model: str
    exog_variant: str
    vintage: str
    train_from: str
    model_fingerprint: str
    frame: pd.DataFrame
    has_forecast_error: bool

    @property
    def days(self) -> pd.Index:
        return self.frame.index

    def on(self, days: Sequence[str]) -> pd.DataFrame:
        """Rows for ``days``, in that order. Refuses a day this curve lacks."""
        missing = [d for d in days if d not in self.frame.index]
        if missing:
            raise MetricsRunError(
                f"{self.zone}/{self.curve}: {len(missing)} day(s) of the requested "
                f"basis are not in this curve's dispatched days, first "
                f"{missing[0]}. A statistic pooled over days a curve did not "
                f"dispatch is not a statistic about that curve."
            )
        return self.frame.loc[list(days)]


#: The columns :class:`CurveDays` carries, and where each one comes from.
SHAPE_COLUMNS: tuple[str, ...] = (
    "n_hours",
    "sum_abs_error",
    "sum_sq_error",
    "sum_error",
    "realised_spread_forecastwise",
    "forecast_spread",
    "spread_error",
    "abs_spread_error",
    "spearman",
    "spearman_contrib",
    "spearman_defined",
)


def load_c11_daily(path: str | None = None) -> pd.DataFrame:
    """C11's per-day dispatch artefact, with the sealed-year check re-asserted.

    The ``market_day`` column is read as a string throughout C12: it is a label
    on a row, never arithmetic, and keeping it a string makes a day set a set of
    labels that cannot silently acquire a timezone.
    """
    source = RESULTS_DIR / (path or C11_DAILY)
    if not source.exists():
        raise MetricsRunError(
            f"{source} is missing. C12 bootstraps C11's committed per-day "
            f"artefact; it does not re-dispatch the LP."
        )
    frame = pd.read_csv(source, dtype={"market_day": str})
    years = {int(d[:4]) for d in frame["market_day"]}
    assert_not_sealed(years, f"read {C11_DAILY} for the C12 metrics layer")
    return frame


def curve_days_for_zone(
    zone: str,
    tier: str,
    regime: str,
    daily: pd.DataFrame,
    power_mw: float,
) -> dict[str, CurveDays]:
    """Build every curve's per-day table for one zone.

    The dispatch columns come from C11's artefact. The shape columns are
    recomputed from the prediction artefact the cycle that scored each arm
    committed — the *same* artefact and column C11's :data:`Arm` inventory
    names, imported rather than re-declared, so a C12 spread error and a C11
    capture ratio cannot be about different forecasts.
    """
    zone_daily = daily[daily["zone"] == zone]
    if zone_daily.empty:
        raise MetricsRunError(f"{C11_DAILY} has no rows for {zone}")
    arms = {arm.curve: arm for arm in arms_for(zone, tier)}
    shapes = _shape_tables(zone, arms)

    out: dict[str, CurveDays] = {}
    for curve, group in zone_daily.groupby("curve", sort=True):
        block = group.set_index("market_day").sort_index()
        frame = pd.DataFrame(index=block.index)
        frame["cash"] = block["cash_eur"].astype(float)
        frame["oracle_cash"] = block["rolled_oracle_cash_eur"].astype(float)
        frame["lost"] = frame["oracle_cash"] - frame["cash"]
        frame["value_added"] = block["value_added_eur"].astype(float)
        frame["realised_spread"] = block["realised_spread"].astype(float)
        frame["in_common_day_set"] = block["in_common_day_set"].astype(bool)
        frame["n_dispatch_hours"] = block["n_hours"].astype(int)

        arm = arms.get(curve)
        if arm is None:
            if curve != ORACLE_CURVE:
                raise MetricsRunError(
                    f"{zone}: {C11_DAILY} carries a curve {curve!r} that is not in "
                    f"C11's arm inventory and is not the oracle"
                )
            for column in SHAPE_COLUMNS:
                frame[column] = np.nan
            has_error = False
        else:
            shape = shapes[curve]
            aligned = shape.reindex(frame.index)
            if aligned["n_hours"].isna().any():
                absent = aligned.index[aligned["n_hours"].isna()].tolist()
                raise MetricsRunError(
                    f"{zone}/{curve}: {len(absent)} dispatched day(s) have no "
                    f"hourly forecast rows in {arm.artefact}, first {absent[0]} — "
                    f"the dispatch artefact and the prediction artefact disagree "
                    f"about which days exist."
                )
            for column in SHAPE_COLUMNS:
                frame[column] = aligned[column].to_numpy(dtype=float)
            has_error = True

        out[curve] = CurveDays(
            zone=zone,
            curve=curve,
            tier=tier,
            regime=regime,
            model=ORACLE_MODEL if arm is None else arm.model,
            exog_variant=ORACLE_VARIANT if arm is None else arm.exog_variant,
            vintage="honest" if arm is None else arm.vintage,
            train_from="" if arm is None else arm.train_from,
            model_fingerprint="" if arm is None else arm.model_fingerprint,
            frame=frame,
            has_forecast_error=has_error,
        )
    return out


def _shape_tables(zone: str, arms: dict[str, Arm]) -> dict[str, pd.DataFrame]:
    """Per-day shape tables for every arm of ``zone``, from its own artefact.

    Reads each prediction file once and asserts the two things that would
    otherwise show up as skill: that ``market_day`` is present (C3's committed
    local-calendar label, which is what every dispatched day set is expressed
    in), and that the artefacts agreeing on ``y_true`` is checked rather than
    assumed — two files for the same zone must carry the same realised series,
    hour for hour, or one of them is not what that cycle scored.
    """
    frames: dict[str, pd.DataFrame] = {}
    for arm in arms.values():
        if arm.artefact in frames:
            continue
        path = RESULTS_DIR / arm.artefact
        if not path.exists():
            raise MetricsRunError(
                f"{zone}: {arm.artefact} is missing. C12 reads the forecasts "
                f"earlier cycles committed; it does not re-fit one."
            )
        frame = pd.read_csv(path, dtype={"market_day": str})
        for column in ("timestamp_utc", "market_day", "y_true"):
            if column not in frame.columns:
                raise MetricsRunError(f"{arm.artefact} has no {column!r} column")
        index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
        frames[arm.artefact] = frame.set_index(index).sort_index()

    names = sorted(frames)
    for other in names[1:]:
        left, right = frames[names[0]], frames[other]
        if not left.index.equals(right.index):
            raise MetricsRunError(
                f"{zone}: {names[0]} and {other} do not cover the same hours — "
                f"C12 will not realign two cycles' artefacts."
            )
        gap = float(
            np.nanmax(
                np.abs(
                    left["y_true"].to_numpy(dtype=float)
                    - right["y_true"].to_numpy(dtype=float)
                )
            )
        )
        if gap > 1e-6:
            raise MetricsRunError(
                f"{zone}: {names[0]} and {other} disagree about the realised "
                f"price by up to {gap:.6g} EUR/MWh."
            )

    out: dict[str, pd.DataFrame] = {}
    for curve, arm in arms.items():
        frame = frames[arm.artefact]
        if arm.column not in frame.columns:
            raise MetricsRunError(f"{arm.artefact} has no column {arm.column!r}")
        table = daily_shape_table(
            frame["y_true"], frame[arm.column], frame["market_day"].to_numpy()
        )
        table = table.rename(columns={"realised_spread": "realised_spread_forecastwise"})
        table["abs_spread_error"] = table["spread_error"].abs()
        defined = np.isfinite(table["spearman"].to_numpy(dtype=float))
        table["spearman_defined"] = defined.astype(float)
        table["spearman_contrib"] = np.where(
            defined, table["spearman"].to_numpy(dtype=float), 0.0
        )
        out[curve] = table
    return out


# ---------------------------------------------------------------------------
# A bootstrap basis: one ordered day list, one count matrix per block length
# ---------------------------------------------------------------------------


@dataclass
class Basis:
    """An ordered day list and the replicate draws taken over it.

    One basis per comparison, shared by every series in it. That sharing *is*
    the pairing: replicate ``b`` of DE-LU's capture and replicate ``b`` of DK1's
    capture are the same calendar days, so their difference carries none of the
    year's common variation. Drawing the counts once and reusing them is
    therefore not an optimisation, it is the method.
    """

    name: str
    days: tuple[str, ...]
    n_replicates: int
    seed: int
    _counts: dict[int, np.ndarray] = field(default_factory=dict, repr=False)

    def spec(self, block_days: int) -> BlockBootstrapSpec:
        return BlockBootstrapSpec(
            n_days=len(self.days),
            n_replicates=self.n_replicates,
            block_days=block_days,
            seed=self.seed,
        )

    def counts(self, block_days: int) -> np.ndarray:
        if block_days not in self._counts:
            self._counts[block_days] = replicate_counts(self.spec(block_days))
        return self._counts[block_days]

    def restricted(self, days: Sequence[str], block_days: int) -> np.ndarray:
        """This basis's draws, projected onto a subset of its days.

        Used for ES, whose nine-curve intersection is 357 of the cross-zone
        basis's 365 days: the replicate is the *same* draw, with the days ES
        could not dispatch removed. ES therefore contributes slightly fewer
        effective days per replicate (its interval is a little wider), and the
        pairing across the three Tier-A zones survives — which is what the
        FINDING C11-D correlation needs.
        """
        wanted = set(days)
        missing = wanted - set(self.days)
        if missing:
            raise MetricsRunError(
                f"basis {self.name}: {len(missing)} requested day(s) are not in "
                f"it, first {sorted(missing)[0]} — a restriction can only narrow "
                f"a basis, never extend it"
            )
        mask = np.array([d in wanted for d in self.days], dtype=bool)
        return self.counts(block_days)[:, mask]


def basis_days(curve_days: dict[str, CurveDays], scope: str) -> tuple[str, ...]:
    """The ordered day list for one zone at one scope (NOTE C10-01's two scopes)."""
    if scope == "common_hours":
        frame = curve_days[COMPARABLE_CURVE].frame
        return tuple(frame.index[frame["in_common_day_set"].to_numpy(dtype=bool)])
    if scope == "own_coverage":
        raise MetricsRunError(
            "own_coverage is per curve, not per zone — ask the curve for its days"
        )
    raise MetricsRunError(f"unknown scope {scope!r}")


# ---------------------------------------------------------------------------
# Point estimates
# ---------------------------------------------------------------------------


def point_metrics(curve: CurveDays, days: Sequence[str], power_mw: float) -> dict[str, Any]:
    """Every C12 metric for one curve over one explicit day set.

    The annualisation deserves a note. C11 reported EUR/MW/yr as
    ``cash / power / calendar_span * 365.25`` — a day the curve declined counts
    as a day the battery earned nothing, which is the right economic reading and
    is *not* the same as the mean of the days it did dispatch. To put an
    interval around the number C11 published rather than around a near neighbour
    of it, the statistic here is ``mean(daily cash) * annualisation`` with
    ``annualisation = n_days * 365.25 / (power * span)`` held fixed across
    replicates. On the full sample that reproduces C11's figure exactly; on a
    resample it scales the resampled mean by the same constant.
    """
    frame = curve.on(days)
    n_days = len(frame)
    if n_days == 0:
        raise MetricsRunError(f"{curve.zone}/{curve.curve}: empty day set")
    span = (
        dt.date.fromisoformat(frame.index[-1]) - dt.date.fromisoformat(frame.index[0])
    ).days + 1
    annualisation = n_days * 365.25 / (power_mw * span)
    out: dict[str, Any] = {
        "zone": curve.zone,
        "curve": curve.curve,
        "n_days": n_days,
        "span_days": span,
        "first_day": frame.index[0],
        "last_day": frame.index[-1],
        "annualisation": annualisation,
        "capture_rolled_oracle_cash": float(
            frame["cash"].sum() / frame["oracle_cash"].sum()
        ),
        "dispatch_cash_eur": float(frame["cash"].sum()),
        "dispatch_cash_eur_per_mw_year": float(frame["cash"].mean() * annualisation),
        "eur_per_mw_year_lost_vs_oracle": float(frame["lost"].mean() * annualisation),
        "realised_spread_mean_eur_per_mwh": float(frame["realised_spread"].mean()),
    }
    if not curve.has_forecast_error:
        return out
    scores = shape_scores(
        frame.rename(columns={"realised_spread_forecastwise": "realised_spread"})
    )
    out.update(
        {
            "n_hours": scores.n_hours,
            "mae_on_dispatched_hours": scores.mae,
            "rmse_on_dispatched_hours": scores.rmse,
            "bias_on_dispatched_hours": scores.bias,
            "daily_spread_mae_eur_per_mwh": scores.spread_mae,
            "daily_spread_bias_eur_per_mwh": scores.spread_bias,
            "daily_spread_rmse_eur_per_mwh": scores.spread_rmse,
            "within_day_spearman_mean": scores.spearman_mean,
            "within_day_spearman_median": scores.spearman_median,
            "within_day_spearman_p05": scores.spearman_p05,
            "n_days_spearman_undefined": scores.n_days_spearman_undefined,
        }
    )
    return out


def rmae_point(
    curve: CurveDays, naive: CurveDays, days: Sequence[str]
) -> float | None:
    """``MAE(curve) / MAE(naive)`` on the same days. ``< 1`` beats the floor.

    PLAN.md's relative metric, recomputed here on the **dispatched** day set
    rather than reused from C10's own-coverage rows. That is the same correction
    C11 made to its paired MAE deltas and for the same reason: FINDING C11-A
    sets this ratio beside the capture ratio, and a comparison of two numbers
    computed over different samples is a comparison of two samples.
    """
    if not curve.has_forecast_error or curve.curve == NAIVE_CURVE:
        return None
    left, right = curve.on(days), naive.on(days)
    floor = float(right["sum_abs_error"].sum() / right["n_hours"].sum())
    if floor <= 0.0:
        return None
    return float(left["sum_abs_error"].sum() / left["n_hours"].sum()) / floor


# ---------------------------------------------------------------------------
# Replicates for one curve on one basis
# ---------------------------------------------------------------------------


def curve_replicates(
    curve: CurveDays, days: Sequence[str], counts: np.ndarray, annualisation: float
) -> dict[str, np.ndarray]:
    """Every bootstrappable metric of one curve, as replicate arrays.

    Keyed by the same metric names the point estimates and the store use, so a
    caller never has to remember which formula produced which number.
    """
    frame = curve.on(days)
    out: dict[str, np.ndarray] = {
        "capture_rolled_oracle_cash": ratio_replicates(
            frame["cash"].to_numpy(dtype=float),
            frame["oracle_cash"].to_numpy(dtype=float),
            counts,
        ),
        "dispatch_cash_eur_per_mw_year": mean_replicates(
            frame["cash"].to_numpy(dtype=float), counts
        )
        * annualisation,
        "eur_per_mw_year_lost_vs_oracle": mean_replicates(
            frame["lost"].to_numpy(dtype=float), counts
        )
        * annualisation,
        "realised_spread_mean_eur_per_mwh": mean_replicates(
            frame["realised_spread"].to_numpy(dtype=float), counts
        ),
    }
    if not curve.has_forecast_error:
        return out
    hours = frame["n_hours"].to_numpy(dtype=float)
    out["mae_on_dispatched_hours"] = ratio_replicates(
        frame["sum_abs_error"].to_numpy(dtype=float), hours, counts
    )
    out["bias_on_dispatched_hours"] = ratio_replicates(
        frame["sum_error"].to_numpy(dtype=float), hours, counts
    )
    out["rmse_on_dispatched_hours"] = np.sqrt(
        ratio_replicates(frame["sum_sq_error"].to_numpy(dtype=float), hours, counts)
    )
    out["daily_spread_mae_eur_per_mwh"] = mean_replicates(
        frame["abs_spread_error"].to_numpy(dtype=float), counts
    )
    out["daily_spread_bias_eur_per_mwh"] = mean_replicates(
        frame["spread_error"].to_numpy(dtype=float), counts
    )
    out["within_day_spearman_mean"] = ratio_replicates(
        frame["spearman_contrib"].to_numpy(dtype=float),
        frame["spearman_defined"].to_numpy(dtype=float),
        counts,
    )
    return out


# ---------------------------------------------------------------------------
# The reproduction check: C12's point estimates against C11's committed rows
# ---------------------------------------------------------------------------

#: What C12 must reproduce, and where C11 wrote it, as
#: ``(metric, scope, atol, rtol)``. A CI around a number nobody published is
#: worse than no CI, so this runs before any interval is reported and a failure
#: is a non-zero exit, not a warning.
#:
#: The tolerances are not a margin chosen to let a disagreement pass; they are
#: float64 association error and nothing else. A ratio in [0, 1] is compared at
#: 5e-9 absolute and the point errors at 5e-9, and in practice they come back at
#: exactly 0.0. The two EUR/MW/yr figures are of order 1e5 and *must* carry a
#: relative tolerance: C11 formed them as ``sum(cash) / span * 365.25`` while
#: C12 forms them as ``mean(cash) * (n_days * 365.25 / span)`` — algebraically
#: the same number, summed in a different order, so they agree to about 1e-9
#: *relative* and cannot agree to 5e-6 absolute. Recomposing them C11's way to
#: dodge that would give up the resampled-mean form the bootstrap needs. The
#: lost-value figure carries one further order of magnitude because it is a
#: *difference* of two ~70 000 EUR sums that is itself only ~6 000 EUR, so the
#: cancellation turns a 1e-10 relative error on the sums into ~3e-9 on the
#: difference. At 1e-8 relative that is 6e-5 EUR/MW/yr — seven orders of
#: magnitude below anything this project reports, and still tight enough that a
#: genuinely different number could not slip through.
REPRODUCED_METRICS: tuple[tuple[str, str, float, float], ...] = (
    ("capture_rolled_oracle_cash", "common_hours", 5e-9, 0.0),
    ("dispatch_cash_eur_per_mw_year", "common_hours", 0.0, 1e-9),
    ("eur_per_mw_year_lost_vs_oracle", "common_hours", 0.0, 1e-8),
    ("mae_on_dispatched_hours", "common_hours", 5e-9, 0.0),
    ("rmse_on_dispatched_hours", "common_hours", 5e-9, 0.0),
    ("bias_on_dispatched_hours", "common_hours", 5e-9, 0.0),
    ("realised_spread_mean_eur_per_mwh", "common_hours", 5e-9, 0.0),
)


def check_c11_reproduction(
    points: pd.DataFrame, store: pd.DataFrame | None = None
) -> dict[str, Any]:
    """Assert every C12 point estimate equals the C11 row it is an interval for.

    Joins on the store's own key — ``(zone, model, exog_variant, vintage,
    train_from, evaluation_years, scope, metric)`` — rather than on the curve
    name, because the curve name is C11's internal label and the key is what the
    two cycles actually share. A metric present in C12 and absent from C11 is
    reported as ``new`` rather than as a pass: C12 adds the spread error and the
    Spearman, and they have nothing to reproduce.
    """
    rows = latest_results() if store is None else store
    c11 = rows[rows["source_cycle"] == "C11"] if "source_cycle" in rows else rows
    checks: list[dict[str, Any]] = []
    for metric, scope, atol, rtol in REPRODUCED_METRICS:
        want = c11[(c11["metric"] == metric) & (c11["scope"] == scope)]
        if want.empty:
            checks.append({"metric": metric, "scope": scope, "status": "absent_in_store"})
            continue
        keyed = {
            (r.zone, r.model, r.exog_variant, r.vintage, r.train_from): float(r.value)
            for r in want.itertuples()
        }
        mine = points[points["scope"] == scope]
        worst_abs = 0.0
        worst_rel = 0.0
        matched = 0
        failures: list[str] = []
        unmatched: list[str] = []
        for row in mine.itertuples():
            value = getattr(row, metric, None)
            if value is None or not np.isfinite(float(value)):
                continue
            key = (row.zone, row.model, row.exog_variant, row.vintage, row.train_from)
            if key not in keyed:
                unmatched.append(f"{row.zone}/{row.curve}")
                continue
            matched += 1
            committed = keyed[key]
            delta = abs(float(value) - committed)
            worst_abs = max(worst_abs, delta)
            if committed != 0.0:
                worst_rel = max(worst_rel, delta / abs(committed))
            if delta > atol + rtol * abs(committed):
                failures.append(f"{row.zone}/{row.curve}:{delta:.3g}")
        checks.append(
            {
                "metric": metric,
                "scope": scope,
                "n_matched": matched,
                "n_unmatched_in_c11": len(unmatched),
                "unmatched": unmatched[:5],
                "worst_abs_delta": round(worst_abs, 12),
                "worst_rel_delta": float(f"{worst_rel:.3g}"),
                "atol": atol,
                "rtol": rtol,
                "n_over_tolerance": len(failures),
                "over_tolerance": failures[:5],
                "holds": matched > 0 and not failures and not unmatched,
            }
        )
    applicable = [c for c in checks if "holds" in c]
    return {
        "holds": bool(applicable) and all(c["holds"] for c in applicable),
        "n_checks": len(applicable),
        "worst_abs_delta": max((c["worst_abs_delta"] for c in applicable), default=None),
        "checks": checks,
        "note": (
            "C12 computes no new dispatch and no new forecast. Every interval it "
            "reports is an interval around a number C11 committed, so the point "
            "estimates must agree to numerical precision or the interval is "
            "about something else."
        ),
    }


# ---------------------------------------------------------------------------
# Arm contrasts, paired, with intervals
# ---------------------------------------------------------------------------

#: The five numbers reported for every contrast. ``mae_pct_gain`` matches the
#: sign convention of C11's FINDING C11-D table — positive means the treatment
#: arm is *better* — so a sign disagreement between columns is visible directly.
CONTRAST_METRICS: tuple[str, ...] = (
    "capture_delta_pp",
    "eur_per_mw_year_delta",
    "mae_pct_gain",
    "daily_spread_mae_delta",
    "within_day_spearman_delta",
)


def contrast_intervals(
    treatment: CurveDays,
    baseline: CurveDays,
    days: Sequence[str],
    counts: np.ndarray,
    annualisation: float,
    block_days: int,
    spec: BlockBootstrapSpec,
    power_mw: float = 1.0,
) -> dict[str, Any]:
    """Paired deltas for one (treatment, baseline) pair, with their intervals.

    Both arms' replicates come from the same draws, so each delta distribution
    is a distribution of *differences within a replicate*. That is what makes a
    sub-one-percentage-point capture delta decidable at all: the year-to-year
    variation the two arms share cancels, and what is left is the disagreement
    between the two schedules.
    """
    left = curve_replicates(treatment, days, counts, annualisation)
    right = curve_replicates(baseline, days, counts, annualisation)
    point_left = point_metrics(treatment, days, power_mw)
    point_right = point_metrics(baseline, days, power_mw)

    def _pct_gain(base: np.ndarray, treat: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(np.abs(base) > 1e-12, (base - treat) / base * 100.0, np.nan)

    deltas = {
        "capture_delta_pp": (
            (left["capture_rolled_oracle_cash"] - right["capture_rolled_oracle_cash"]) * 100.0,
            (point_left["capture_rolled_oracle_cash"] - point_right["capture_rolled_oracle_cash"]) * 100.0,
        ),
        "eur_per_mw_year_delta": (
            left["dispatch_cash_eur_per_mw_year"] - right["dispatch_cash_eur_per_mw_year"],
            point_left["dispatch_cash_eur_per_mw_year"] - point_right["dispatch_cash_eur_per_mw_year"],
        ),
        "mae_pct_gain": (
            _pct_gain(right["mae_on_dispatched_hours"], left["mae_on_dispatched_hours"]),
            (point_right["mae_on_dispatched_hours"] - point_left["mae_on_dispatched_hours"])
            / point_right["mae_on_dispatched_hours"] * 100.0,
        ),
        "daily_spread_mae_delta": (
            right["daily_spread_mae_eur_per_mwh"] - left["daily_spread_mae_eur_per_mwh"],
            point_right["daily_spread_mae_eur_per_mwh"] - point_left["daily_spread_mae_eur_per_mwh"],
        ),
        "within_day_spearman_delta": (
            left["within_day_spearman_mean"] - right["within_day_spearman_mean"],
            point_left["within_day_spearman_mean"] - point_right["within_day_spearman_mean"],
        ),
    }
    out: dict[str, Any] = {
        "zone": treatment.zone,
        "treatment": treatment.curve,
        "baseline": baseline.curve,
        "vintage": treatment.vintage,
        "n_days": len(days),
        "block_days": block_days,
        "honest": (treatment.curve, baseline.curve) in HONEST_CONTRASTS,
    }
    for name, (replicates, point) in deltas.items():
        out[name] = _interval(point, replicates, spec).as_dict()
    out["_replicates"] = {name: rep for name, (rep, _) in deltas.items()}
    return out


# ---------------------------------------------------------------------------
# FINDING C11-A: is the cross-zone capture band wider than noise?
# ---------------------------------------------------------------------------


def _cv_replicates(columns: np.ndarray) -> np.ndarray:
    """Coefficient of variation across the group axis, per replicate."""
    return np.std(columns, axis=1, ddof=1) / np.mean(columns, axis=1)


#: The point-forecast metrics set beside the capture ratio across the nine
#: zones, and the sign a "regime differences reach flexibility value through
#: forecastability" story predicts for each one's correlation with capture.
#: ``rmae`` is the metric FINDING C11-A used; the other four are what C12 adds,
#: and the point of listing them together is that the finding is about *which*
#: point-forecast metric tracks a dispatch metric, not about one of them.
CANDIDATE_METRICS: tuple[tuple[str, int], ...] = (
    ("rmae_vs_naive_on_dispatched_hours", -1),
    ("mae_on_dispatched_hours", -1),
    ("within_day_spearman_mean", +1),
    ("daily_spread_mae_eur_per_mwh", -1),
    ("daily_spread_bias_eur_per_mwh", +1),
)


def cross_zone_analysis(
    zones: Sequence[str],
    capture_point: np.ndarray,
    capture: np.ndarray,
    candidates: dict[str, tuple[np.ndarray, np.ndarray]],
    spec: BlockBootstrapSpec,
) -> dict[str, Any]:
    """The FINDING C11-A test, generalised over the forecast metric.

    FINDING C11-A is two claims, and they need different tests.

    *The bands are unequal.* A band is a max minus a min, so it is positively
    biased and its own interval never contains zero — which is why the question
    "is this band wider than noise?" is put to
    :func:`backtest.bootstrap.noise_only_spread`, which builds the band's
    distribution under "every zone really has the same value of this metric, and
    differs only by the sampling noise the bootstrap measured for it". The
    scale-free comparison *between* two metrics is the ratio of their
    coefficients of variation, bootstrapped paired (same draws, both metrics),
    which is the interval on C11's "capture's CV is 3.0x rMAE's" claim.

    *The rankings do not line up.* Spearman between each forecast metric and
    capture across the zones, per replicate. C11 ran this for rMAE alone and
    flagged the result as not significant (+0.58, p=0.099). C12 runs it for
    every metric in :data:`CANDIDATE_METRICS`, because the interesting question
    turns out not to be whether *rMAE* tracks capture but whether *any*
    point-forecast metric does — and the within-day rank correlation, which is
    the closest of them to what the dispatch LP reads off a curve, is not the
    same answer as MAE.

    ``expected_sign`` records the direction a forecastability story predicts, so
    a correlation that is significant with the *wrong* sign is not read as
    support for it.
    """
    capture_band = capture.max(axis=1) - capture.min(axis=1)
    point_capture_band = float(capture_point.max() - capture_point.min())
    cv_capture = _cv_replicates(capture)
    point_cv_capture = float(np.std(capture_point, ddof=1) / np.mean(capture_point))

    out: dict[str, Any] = {
        "zones": list(zones),
        "n_zones": len(zones),
        "block_days": spec.block_days,
        "capture_point": [round(float(v), 10) for v in capture_point],
        "capture_band_pp": _interval(
            point_capture_band * 100.0, capture_band * 100.0, spec
        ).as_dict(),
        "capture_cv": _interval(point_cv_capture, cv_capture, spec).as_dict(),
        "capture_band_vs_noise": noise_only_spread(
            capture_point, capture, observed_band=point_capture_band
        ),
        "per_zone_capture_ci": {
            zone: _interval(float(capture_point[i]), capture[:, i], spec).as_dict()
            for i, zone in enumerate(zones)
        },
        "n_disjoint_zone_pairs": _count_disjoint_pairs(
            zones, capture_point, capture, spec
        ),
        "forecast_metrics": {},
    }
    for metric, expected_sign in CANDIDATE_METRICS:
        if metric not in candidates:
            continue
        point, replicates = candidates[metric]
        band = replicates.max(axis=1) - replicates.min(axis=1)
        point_band = float(point.max() - point.min())
        cv = _cv_replicates(replicates)
        point_cv = float(np.std(point, ddof=1) / np.mean(point))
        rho = spearman_rows(replicates, capture)
        point_rho = float(spearman_rows(point[None, :], capture_point[None, :])[0])
        interval_rho = _interval(point_rho, rho, spec)
        out["forecast_metrics"][metric] = {
            "point": [round(float(v), 10) for v in point],
            "expected_sign_if_forecastability_drives_capture": expected_sign,
            "band": _interval(point_band, band, spec).as_dict(),
            "cv": _interval(point_cv, cv, spec).as_dict(),
            "cv_ratio_capture_over_metric": _interval(
                point_cv_capture / point_cv, cv_capture / cv, spec
            ).as_dict(),
            "band_vs_noise": noise_only_spread(point, replicates, observed_band=point_band),
            "spearman_vs_capture": interval_rho.as_dict(),
            "spearman_has_expected_sign": bool(
                np.sign(point_rho) == expected_sign
            ),
            "spearman_excludes_zero": interval_rho.excludes_zero,
        }
    # Kept at the top level under their C11 names so a reader comparing against
    # the C11 entry finds them where that entry left them.
    rmae_block = out["forecast_metrics"].get("rmae_vs_naive_on_dispatched_hours")
    if rmae_block is not None:
        out["rmae_point"] = rmae_block["point"]
        out["rmae_band_pp"] = {
            **rmae_block["band"],
            "point": rmae_block["band"]["point"] * 100.0,
            "ci_low": rmae_block["band"]["ci_low"] * 100.0,
            "ci_high": rmae_block["band"]["ci_high"] * 100.0,
        }
        out["rmae_cv"] = rmae_block["cv"]
        out["cv_ratio_capture_over_rmae"] = rmae_block["cv_ratio_capture_over_metric"]
        out["rmae_band_vs_noise"] = rmae_block["band_vs_noise"]
        out["spearman_rmae_vs_capture"] = rmae_block["spearman_vs_capture"]
    return out


def _count_disjoint_pairs(
    zones: Sequence[str], point: np.ndarray, replicates: np.ndarray, spec: BlockBootstrapSpec
) -> dict[str, Any]:
    """How many zone pairs have a paired capture difference excluding zero.

    The directly interpretable version of "the band is wider than noise": the
    days are paired across zones, so the difference between two zones' capture
    ratios has its own interval, and counting how many of the pairs separate is
    a statement a reader can check against the per-zone table. Reported beside
    the band test because the two can disagree — a band driven by one zone
    separates few pairs.
    """
    total = 0
    separated: list[str] = []
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            total += 1
            interval = _interval(
                float(point[i] - point[j]), replicates[:, i] - replicates[:, j], spec
            )
            if interval.excludes_zero:
                separated.append(f"{zones[i]}-{zones[j]}")
    return {
        "n_pairs": total,
        "n_pairs_excluding_zero": len(separated),
        "share": round(len(separated) / total, 6) if total else None,
        "pairs": separated,
    }


# ---------------------------------------------------------------------------
# FINDING C11-D: does MAE predict capture across the honest comparisons?
# ---------------------------------------------------------------------------


def mae_vs_capture_correlation(
    items: Sequence[dict[str, Any]], spec: BlockBootstrapSpec
) -> dict[str, Any]:
    """The interval on FINDING C11-D's rank correlation and sign agreement.

    ``items`` are the honest contrasts, each carrying its ``mae_pct_gain`` and
    ``capture_delta_pp`` replicate arrays from the *same* draws. Per replicate
    the whole table is recomputed and the rank correlation across its rows
    taken, so the reported interval accounts for the fact that the fifteen rows
    are not independent — they share zones, share arms and share days.

    The sign-agreement count is reported beside the correlation because it is
    the form C11 stated the finding in ("agree nine times out of fifteen, a coin
    flip") and because it survives a non-monotone relationship that a Spearman
    would miss.
    """
    if len(items) < 3:
        raise MetricsRunError(
            f"a rank correlation across {len(items)} comparisons is not one"
        )
    mae = np.column_stack([item["mae_pct_gain"] for item in items])
    capture = np.column_stack([item["capture_delta_pp"] for item in items])
    point_mae = np.array([item["mae_pct_gain_point"] for item in items], dtype=float)
    point_capture = np.array([item["capture_delta_pp_point"] for item in items], dtype=float)

    rho = spearman_rows(mae, capture)
    point_rho = float(spearman_rows(point_mae[None, :], point_capture[None, :])[0])
    agree = (np.sign(mae) == np.sign(capture)).sum(axis=1).astype(float)
    point_agree = float((np.sign(point_mae) == np.sign(point_capture)).sum())
    # Pearson, for continuity with the C11 entry, which reported both.
    centred_mae = mae - mae.mean(axis=1, keepdims=True)
    centred_capture = capture - capture.mean(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        pearson = (centred_mae * centred_capture).sum(axis=1) / np.sqrt(
            (centred_mae**2).sum(axis=1) * (centred_capture**2).sum(axis=1)
        )
    pm = point_mae - point_mae.mean()
    pc = point_capture - point_capture.mean()
    point_pearson = float(
        (pm * pc).sum() / np.sqrt((pm**2).sum() * (pc**2).sum())
    )
    return {
        "n_comparisons": len(items),
        "block_days": spec.block_days,
        "labels": [f"{i['zone']}:{i['treatment']}-{i['baseline']}" for i in items],
        "spearman": _interval(point_rho, rho, spec).as_dict(),
        "pearson": _interval(point_pearson, pearson, spec).as_dict(),
        "n_sign_agreements": _interval(point_agree, agree, spec).as_dict(),
        "expected_sign_agreements_if_independent": len(items) / 2.0,
        "note": (
            "The fifteen rows are not independent — they share zones, arms and "
            "days — which is exactly why the correlation is recomputed inside "
            "each replicate rather than bootstrapped over the rows."
        ),
    }


# ---------------------------------------------------------------------------
# Store rows
# ---------------------------------------------------------------------------

#: The new per-curve metrics C12 contributes as point estimates, at both scopes.
NEW_POINT_METRICS: tuple[str, ...] = (
    "daily_spread_mae_eur_per_mwh",
    "daily_spread_bias_eur_per_mwh",
    "daily_spread_rmse_eur_per_mwh",
    "within_day_spearman_mean",
    "within_day_spearman_median",
    "within_day_spearman_p05",
    "rmae_vs_naive_on_dispatched_hours",
)

#: The metrics whose interval bounds are written. Deliberately a subset: a
#: ``_ci_low``/``_ci_high`` pair for every metric at every block length would
#: triple the store for numbers the artefacts already carry in full. These are
#: the ones a later cycle reports.
INTERVAL_METRICS: tuple[str, ...] = (
    "capture_rolled_oracle_cash",
    "dispatch_cash_eur_per_mw_year",
    "eur_per_mw_year_lost_vs_oracle",
    "mae_on_dispatched_hours",
    "daily_spread_mae_eur_per_mwh",
    "within_day_spearman_mean",
)


def store_rows(
    points: pd.DataFrame,
    intervals: dict[tuple[str, str, str, str], Interval],
    contrasts: Sequence[dict[str, Any]],
    curve_index: dict[tuple[str, str], CurveDays],
    years: Sequence[int],
    headline_block_days: int,
) -> list[ResultRow]:
    """Long-format rows: the new metrics, their interval bounds, the contrasts.

    The store's extension point is the metric name, so none of this needs a
    schema change — ``docs/results_store.md`` promised that in C10 and C11
    tested it. Three naming conventions are used and all three are mechanical:

    * ``<metric>`` — a new point estimate.
    * ``<metric>_ci_low`` / ``_ci_high`` / ``_boot_sd`` — the interval around it
      at the headline block length. The block length, the replicate count and
      the seed are in the run note and in the artefacts, not in the metric name:
      a metric name that encoded them would make the ladder unreadable.
    * ``<quantity>_delta_vs_<baseline curve>`` (and its bounds) — a paired
      contrast, written on the **treatment** row. The baseline is in the name
      because the store's key identifies one series, and a difference is about
      two.
    """
    eval_years = ",".join(str(y) for y in years)
    rows: list[ResultRow] = []

    def _common(zone: str, curve: str, scope: str, n_days: Any, n_scored: Any) -> dict[str, Any]:
        days = curve_index[(zone, curve)]
        return dict(
            zone=zone,
            tier=days.tier,
            regime=days.regime,
            model=days.model,
            exog_variant=days.exog_variant,
            vintage=days.vintage,
            train_from=days.train_from,
            model_fingerprint=days.model_fingerprint,
            evaluation_years=eval_years,
            scope=scope,
            n=str(int(n_days)),
            n_scored="" if n_scored is None or not np.isfinite(float(n_scored)) else str(int(n_scored)),
            source_cycle="C12",
        )

    for row in points.itertuples():
        common = _common(
            row.zone, row.curve, row.scope, row.n_days, getattr(row, "n_hours", None)
        )
        for metric in NEW_POINT_METRICS:
            value = getattr(row, metric, None)
            if value is None or not np.isfinite(float(value)):
                continue
            rows.append(ResultRow(metric=metric, value=float(value), **common))

    for (zone, curve, scope, metric), interval in sorted(intervals.items()):
        if metric not in INTERVAL_METRICS:
            continue
        match = points[
            (points["zone"] == zone) & (points["curve"] == curve) & (points["scope"] == scope)
        ]
        if match.empty:
            continue
        n_days = int(match.iloc[0]["n_days"])
        common = _common(zone, curve, scope, n_days, None)
        for suffix, value in (
            ("ci_low", interval.ci_low),
            ("ci_high", interval.ci_high),
            ("boot_sd", interval.boot_sd),
        ):
            rows.append(
                ResultRow(metric=f"{metric}_{suffix}", value=float(value), **common)
            )

    for contrast in contrasts:
        if contrast["block_days"] != headline_block_days:
            continue
        zone, treatment, baseline = contrast["zone"], contrast["treatment"], contrast["baseline"]
        common = _common(zone, treatment, "common_hours", contrast["n_days"], None)
        for quantity in ("capture_delta_pp", "mae_pct_gain"):
            stem = f"{_delta_stem(quantity)}_vs_{baseline}"
            block = contrast[quantity]
            for suffix, key in (("", "point"), ("_ci_low", "ci_low"), ("_ci_high", "ci_high")):
                rows.append(
                    ResultRow(
                        metric=f"{stem}{suffix}",
                        value=float(block[key]),
                        **common,
                    )
                )
    return rows


def _delta_stem(quantity: str) -> str:
    return {
        "capture_delta_pp": "capture_delta_pp",
        "mae_pct_gain": "mae_pct_gain",
    }[quantity]


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Compute the whole C12 layer. Returns ``(exit_code, summary)``."""
    args = parse_args(argv)
    headline_block = args.block_days or BLOCK_LADDER[0]
    ladder = tuple(dict.fromkeys((headline_block, *BLOCK_LADDER)))
    years = list(args.years)
    assert_not_sealed(set(years), "run the C12 metrics layer")

    guard_before = _holdout_state()
    zones_cfg = load_zones()
    battery = load_battery_config()
    power_mw = float(battery["battery"]["power_mw"])
    wanted = list(args.zones) if args.zones else list(zones_cfg)
    unknown = [z for z in wanted if z not in zones_cfg]
    if unknown:
        raise MetricsRunError(f"unknown zone(s) {unknown}")

    daily = load_c11_daily()
    curves: dict[str, dict[str, CurveDays]] = {}
    for zone in wanted:
        cfg = zones_cfg[zone]
        curves[zone] = curve_days_for_zone(
            zone, cfg.tier, cfg.regime, daily, power_mw
        )

    # --- point estimates, both scopes -------------------------------------
    point_rows: list[dict[str, Any]] = []
    for zone in wanted:
        common = basis_days(curves[zone], "common_hours")
        naive = curves[zone][NAIVE_CURVE]
        for curve_name, curve in sorted(curves[zone].items()):
            for scope, days in (
                ("own_coverage", tuple(curve.frame.index)),
                ("common_hours", common),
            ):
                block = point_metrics(curve, days, power_mw)
                block["scope"] = scope
                block["model"] = curve.model
                block["exog_variant"] = curve.exog_variant
                block["vintage"] = curve.vintage
                block["train_from"] = curve.train_from
                block["tier"] = curve.tier
                block["regime"] = curve.regime
                ratio = rmae_point(curve, naive, days)
                if ratio is not None:
                    block["rmae_vs_naive_on_dispatched_hours"] = ratio
                point_rows.append(block)
    points = pd.DataFrame(point_rows)

    reproduction = check_c11_reproduction(points)

    # --- intervals, per zone, at common_hours, across the block ladder ----
    intervals: dict[tuple[str, str, str, str], Interval] = {}
    ladder_table: list[dict[str, Any]] = []
    for zone in wanted:
        common = basis_days(curves[zone], "common_hours")
        basis = Basis(
            name=f"{zone}:common_hours",
            days=common,
            n_replicates=args.replicates,
            seed=args.seed,
        )
        naive = curves[zone][NAIVE_CURVE]
        for block_days in ladder:
            counts = basis.counts(block_days)
            spec = basis.spec(block_days)
            naive_rep = curve_replicates(naive, common, counts, 1.0)
            for curve_name, curve in sorted(curves[zone].items()):
                annualisation = point_metrics(curve, common, power_mw)["annualisation"]
                replicates = curve_replicates(curve, common, counts, annualisation)
                point = point_metrics(curve, common, power_mw)
                for metric, series in replicates.items():
                    interval = _interval(float(point[metric]), series, spec)
                    if block_days == headline_block:
                        intervals[(zone, curve_name, "common_hours", metric)] = interval
                    ladder_table.append(
                        {
                            "zone": zone,
                            "curve": curve_name,
                            "scope": "common_hours",
                            "metric": metric,
                            "block_days": block_days,
                            **interval.as_dict(),
                        }
                    )
                if curve.has_forecast_error and curve_name != NAIVE_CURVE:
                    ratio_rep = (
                        replicates["mae_on_dispatched_hours"]
                        / naive_rep["mae_on_dispatched_hours"]
                    )
                    ratio_point = rmae_point(curve, naive, common)
                    interval = _interval(float(ratio_point), ratio_rep, spec)
                    if block_days == headline_block:
                        intervals[
                            (zone, curve_name, "common_hours", "rmae_vs_naive_on_dispatched_hours")
                        ] = interval
                    ladder_table.append(
                        {
                            "zone": zone,
                            "curve": curve_name,
                            "scope": "common_hours",
                            "metric": "rmae_vs_naive_on_dispatched_hours",
                            "block_days": block_days,
                            **interval.as_dict(),
                        }
                    )

    # --- arm contrasts (Tier A only: Tier B has one forecast arm) ---------
    contrasts: list[dict[str, Any]] = []
    honest_items: dict[int, list[dict[str, Any]]] = {b: [] for b in ladder}
    cross_basis = _cross_zone_basis(curves, wanted, args.replicates, args.seed)
    for zone in wanted:
        available = curves[zone]
        pairs = [
            (t, b)
            for t, b, _ in CONTRASTS
            if t in available and b in available
        ]
        if not pairs:
            continue
        common = basis_days(available, "common_hours")
        for block_days in ladder:
            counts = (
                cross_basis.restricted(common, block_days)
                if cross_basis is not None
                else Basis(f"{zone}:common_hours", common, args.replicates, args.seed).counts(block_days)
            )
            spec = BlockBootstrapSpec(
                n_days=len(common),
                n_replicates=args.replicates,
                block_days=min(block_days, len(common)),
                seed=args.seed,
            )
            annualisation = point_metrics(available[COMPARABLE_CURVE], common, power_mw)["annualisation"]
            for treatment, baseline in pairs:
                block = contrast_intervals(
                    available[treatment],
                    available[baseline],
                    common,
                    counts,
                    annualisation,
                    block_days,
                    spec,
                    power_mw,
                )
                replicates = block.pop("_replicates")
                if block["honest"]:
                    honest_items[block_days].append(
                        {
                            "zone": zone,
                            "treatment": treatment,
                            "baseline": baseline,
                            "mae_pct_gain": replicates["mae_pct_gain"],
                            "capture_delta_pp": replicates["capture_delta_pp"],
                            "mae_pct_gain_point": block["mae_pct_gain"]["point"],
                            "capture_delta_pp_point": block["capture_delta_pp"]["point"],
                        }
                    )
                contrasts.append(block)

    # --- FINDING C11-D: the correlation across the honest comparisons -----
    correlation: dict[int, dict[str, Any]] = {}
    for block_days, items in honest_items.items():
        if len(items) < 3:
            continue
        correlation[block_days] = mae_vs_capture_correlation(
            items,
            BlockBootstrapSpec(
                n_days=len(cross_basis.days) if cross_basis else 365,
                n_replicates=args.replicates,
                block_days=block_days,
                seed=args.seed,
            ),
        )

    # --- FINDING C11-A: the cross-zone band ------------------------------
    cross_zone: dict[int, dict[str, Any]] = {}
    if cross_basis is not None and len(wanted) >= 3:
        cross_zone = _cross_zone_blocks(
            curves, wanted, cross_basis, ladder, power_mw, args.replicates, args.seed
        )

    guard_after = _holdout_state()
    summary = {
        "cycle": "C12",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "libraries": library_versions(),
        "zones": wanted,
        "evaluation_years": years,
        "power_mw": power_mw,
        "bootstrap": {
            "n_replicates": args.replicates,
            "seed": args.seed,
            "headline_block_days": headline_block,
            "block_ladder": list(ladder),
            "method": "circular moving-block, percentile interval, paired draws",
        },
        "c11_reproduction": reproduction,
        "cross_zone_basis": {
            "n_days": len(cross_basis.days) if cross_basis else 0,
            "first_day": cross_basis.days[0] if cross_basis else None,
            "last_day": cross_basis.days[-1] if cross_basis else None,
            "identical_across_zones": cross_basis is not None,
        },
        "cross_zone": {str(k): v for k, v in cross_zone.items()},
        "mae_vs_capture": {str(k): v for k, v in correlation.items()},
        "decidability": {
            str(b): decidability(contrasts, b) for b in ladder
        },
        "holdout_guard": {"before": guard_before, "after": guard_after},
    }
    exit_code = 0 if reproduction["holds"] else 1
    return exit_code, {
        "summary": summary,
        "points": points,
        "intervals": intervals,
        "ladder": pd.DataFrame(ladder_table),
        "contrasts": contrasts,
        "curves": curves,
        "headline_block_days": headline_block,
        "years": years,
        "no_append": bool(args.no_append),
        "out_dir": args.out_dir,
    }


def _holdout_state() -> dict[str, Any]:
    """The sealed-holdout guard's state, recorded before and after the work."""
    return {
        "sealed_years": sorted(sealed_years()),
        "holdout_is_unsealed": bool(holdout_is_unsealed()),
    }


def _cross_zone_basis(
    curves: dict[str, dict[str, CurveDays]],
    zones: Sequence[str],
    replicates: int,
    seed: int,
) -> Basis | None:
    """The comparable arm's day set, asserted identical in every zone.

    If it is not identical the cross-zone band is not a paired statistic and
    this returns ``None`` rather than silently resampling nine different day
    sets — which would inflate every cross-zone interval by the amount of
    common variation it failed to remove.
    """
    sets = {
        zone: tuple(curves[zone][COMPARABLE_CURVE].frame.index) for zone in zones
    }
    first = sets[zones[0]]
    if any(sets[zone] != first for zone in zones):
        return None
    return Basis(
        name="cross_zone:comparable_arm", days=first, n_replicates=replicates, seed=seed
    )


def _cross_zone_blocks(
    curves: dict[str, dict[str, CurveDays]],
    zones: Sequence[str],
    basis: Basis,
    ladder: Sequence[int],
    power_mw: float,
    replicates: int,
    seed: int,
) -> dict[int, dict[str, Any]]:
    """The FINDING C11-A analysis at every block length, with and without NO2.

    Zones are ordered by capture descending so the band's endpoints are the
    first and last rows of every table, and every forecast metric in
    :data:`CANDIDATE_METRICS` is carried through the same draws as capture — the
    pairing that makes a rank correlation between two of them a statement about
    nine zones rather than about eighteen independent samples.
    """
    out: dict[int, dict[str, Any]] = {}
    ordered = sorted(
        zones,
        key=lambda z: -point_metrics(
            curves[z][COMPARABLE_CURVE], basis.days, power_mw
        )["capture_rolled_oracle_cash"],
    )
    for block_days in ladder:
        counts = basis.counts(block_days)
        spec = basis.spec(block_days)
        capture_cols: list[np.ndarray] = []
        capture_pt: list[float] = []
        metric_cols: dict[str, list[np.ndarray]] = {m: [] for m, _ in CANDIDATE_METRICS}
        metric_pt: dict[str, list[float]] = {m: [] for m, _ in CANDIDATE_METRICS}
        for zone in ordered:
            comparable = curves[zone][COMPARABLE_CURVE]
            naive = curves[zone][NAIVE_CURVE]
            rep = curve_replicates(comparable, basis.days, counts, 1.0)
            naive_rep = curve_replicates(naive, basis.days, counts, 1.0)
            point = point_metrics(comparable, basis.days, power_mw)
            capture_cols.append(rep["capture_rolled_oracle_cash"])
            capture_pt.append(point["capture_rolled_oracle_cash"])
            rep["rmae_vs_naive_on_dispatched_hours"] = (
                rep["mae_on_dispatched_hours"] / naive_rep["mae_on_dispatched_hours"]
            )
            point["rmae_vs_naive_on_dispatched_hours"] = rmae_point(
                comparable, naive, basis.days
            )
            for metric, _ in CANDIDATE_METRICS:
                metric_cols[metric].append(rep[metric])
                metric_pt[metric].append(float(point[metric]))
        capture = np.column_stack(capture_cols)
        capture_point = np.array(capture_pt, dtype=float)
        candidates = {
            metric: (
                np.array(metric_pt[metric], dtype=float),
                np.column_stack(metric_cols[metric]),
            )
            for metric, _ in CANDIDATE_METRICS
        }
        block: dict[str, Any] = {
            "all_zones": cross_zone_analysis(
                ordered, capture_point, capture, candidates, spec
            )
        }
        if OUTLIER_ZONE in ordered and len(ordered) >= 4:
            keep = [i for i, z in enumerate(ordered) if z != OUTLIER_ZONE]
            block[f"excluding_{OUTLIER_ZONE}"] = cross_zone_analysis(
                [ordered[i] for i in keep],
                capture_point[keep],
                capture[:, keep],
                {
                    metric: (point[keep], rep[:, keep])
                    for metric, (point, rep) in candidates.items()
                },
                spec,
            )
        out[block_days] = block
    return out


# ---------------------------------------------------------------------------
# Artefacts and the CLI
# ---------------------------------------------------------------------------

#: One row per (zone, curve, dispatched day) with the dispatch columns joined to
#: the shape columns. The artefact C13's regime tables and C15's sensitivities
#: should read rather than rebuilding this join.
C12_DAILY_ARTEFACT = "c12_daily_metrics_2024.csv.gz"


def daily_artefact(curves: dict[str, dict[str, CurveDays]]) -> pd.DataFrame:
    """The long per-day table, every zone and curve, in one file."""
    frames: list[pd.DataFrame] = []
    for zone in sorted(curves):
        for curve_name, curve in sorted(curves[zone].items()):
            block = curve.frame.reset_index()
            block.insert(0, "zone", zone)
            block.insert(1, "curve", curve_name)
            block["model"] = curve.model
            block["exog_variant"] = curve.exog_variant
            block["vintage"] = curve.vintage
            block["train_from"] = curve.train_from
            block["tier"] = curve.tier
            block["regime"] = curve.regime
            frames.append(block)
    return pd.concat(frames, ignore_index=True)


def contrasts_frame(contrasts: Sequence[dict[str, Any]]) -> pd.DataFrame:
    """Flatten the contrast blocks into one printable/committable table."""
    rows: list[dict[str, Any]] = []
    for block in contrasts:
        row = {
            "zone": block["zone"],
            "treatment": block["treatment"],
            "baseline": block["baseline"],
            "vintage": block["vintage"],
            "honest": block["honest"],
            "n_days": block["n_days"],
            "block_days": block["block_days"],
        }
        for metric in CONTRAST_METRICS:
            interval = block[metric]
            row[f"{metric}"] = interval["point"]
            row[f"{metric}_ci_low"] = interval["ci_low"]
            row[f"{metric}_ci_high"] = interval["ci_high"]
            row[f"{metric}_boot_sd"] = interval["boot_sd"]
            row[f"{metric}_excludes_zero"] = interval["excludes_zero"]
            row[f"{metric}_prob_le_zero"] = interval["prob_le_zero"]
        rows.append(row)
    return pd.DataFrame(rows)


def decidability(
    contrasts: Sequence[dict[str, Any]], block_days: int
) -> dict[str, Any]:
    """How many honest contrasts each metric can actually decide, and how loudly.

    This is the question FINDING C11-D turns out to rest on, and C11 could not
    ask it. "MAE and capture disagree about which arm is better" has two very
    different explanations: the two metrics really rank arms differently, or one
    of them cannot rank them at all at this sample size. The diagnostic is the
    same for both — the share of contrasts whose interval excludes zero, and the
    point estimate in units of its own bootstrap standard deviation, which is
    scale-free and therefore comparable between a percentage of MAE and a
    percentage point of capture.

    A metric that decides few contrasts is not thereby a worse metric. It means
    a year of daily blocks does not resolve the differences it is being asked
    about, and that the honest report of a disagreement between the two is
    "undetermined", not "contradicted".
    """
    honest = [c for c in contrasts if c["honest"] and c["block_days"] == block_days]
    if not honest:
        return {"n_honest_contrasts": 0}
    out: dict[str, Any] = {"n_honest_contrasts": len(honest), "block_days": block_days}
    for metric in CONTRAST_METRICS:
        intervals = [c[metric] for c in honest]
        ratios = [
            abs(i["point"]) / i["boot_sd"] if i["boot_sd"] > 0 else float("nan")
            for i in intervals
        ]
        finite = [r for r in ratios if np.isfinite(r)]
        decided = [i for i in intervals if i["excludes_zero"]]
        out[metric] = {
            "n_excluding_zero": len(decided),
            "share_excluding_zero": round(len(decided) / len(intervals), 6),
            "median_abs_point_over_boot_sd": (
                round(float(np.median(finite)), 6) if finite else None
            ),
            "max_abs_point_over_boot_sd": (
                round(float(np.max(finite)), 6) if finite else None
            ),
            "median_boot_sd": round(float(np.median([i["boot_sd"] for i in intervals])), 6),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    exit_code, result = run(argv)
    summary = result["summary"]
    out_dir = REPO_ROOT / result["out_dir"] if result["out_dir"] else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    points: pd.DataFrame = result["points"]
    ladder: pd.DataFrame = result["ladder"]
    contrasts = result["contrasts"]
    curves = result["curves"]

    daily = daily_artefact(curves)
    daily.to_csv(out_dir / C12_DAILY_ARTEFACT, index=False)
    points.to_csv(out_dir / "c12_metrics_table.csv", index=False)
    ladder.to_csv(out_dir / "c12_intervals.csv", index=False)
    contrast_table = contrasts_frame(contrasts)
    contrast_table.to_csv(out_dir / "c12_contrasts.csv", index=False)
    summary["artefacts"] = {
        "daily": C12_DAILY_ARTEFACT,
        "n_daily_rows": int(len(daily)),
        "metrics_table": "c12_metrics_table.csv",
        "n_metric_rows": int(len(points)),
        "intervals": "c12_intervals.csv",
        "n_interval_rows": int(len(ladder)),
        "contrasts": "c12_contrasts.csv",
        "n_contrast_rows": int(len(contrast_table)),
    }

    if not result["no_append"]:
        verify_append_only()
        curve_index = {
            (zone, name): curve
            for zone, block in curves.items()
            for name, curve in block.items()
        }
        rows = store_rows(
            points,
            result["intervals"],
            contrasts,
            curve_index,
            result["years"],
            result["headline_block_days"],
        )
        report = append_rows(
            rows,
            cycle="C12",
            git_sha=summary["git_sha"],
            config_hash=summary["config_hash"],
            argv=argv if argv is not None else [],
            note=(
                "C12 metrics layer: daily-spread error, within-day Spearman, "
                "rMAE on dispatched hours, and daily-block bootstrap intervals "
                f"({summary['bootstrap']['n_replicates']} replicates, seed "
                f"{summary['bootstrap']['seed']}, block_days="
                f"{summary['bootstrap']['headline_block_days']}, circular "
                "moving-block, percentile)."
            ),
        )
        summary["store"] = report.as_dict()
        summary["store"]["verified_after"] = verify_append_only()
    else:
        summary["store"] = {"skipped": True}

    with (out_dir / "c12_metrics_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")

    print(json.dumps(_console(summary), indent=2, default=str))
    if exit_code:
        print(
            "\nFAIL: C12's point estimates do not reproduce C11's committed rows. "
            "No interval below is about a published number. See "
            "c12_metrics_summary.json -> c11_reproduction.",
        )
    return exit_code


def _console(summary: dict[str, Any]) -> dict[str, Any]:
    """The short form printed to stdout; the JSON on disk is the full record."""
    headline = str(summary["bootstrap"]["headline_block_days"])
    cross = summary.get("cross_zone", {}).get(headline, {})
    correlation = summary.get("mae_vs_capture", {}).get(headline, {})
    out: dict[str, Any] = {
        "cycle": summary["cycle"],
        "zones": summary["zones"],
        "bootstrap": summary["bootstrap"],
        "c11_reproduction": {
            "holds": summary["c11_reproduction"]["holds"],
            "n_checks": summary["c11_reproduction"]["n_checks"],
            "worst_abs_delta": summary["c11_reproduction"]["worst_abs_delta"],
        },
        "artefacts": summary.get("artefacts"),
        "store": {
            k: v for k, v in summary.get("store", {}).items() if k != "libraries"
        },
    }
    for label, block in cross.items():
        out[f"cross_zone::{label}"] = {
            "n_zones": block["n_zones"],
            "capture_band_pp": block["capture_band_pp"],
            "rmae_band_pp": block["rmae_band_pp"],
            "cv_ratio_capture_over_rmae": block["cv_ratio_capture_over_rmae"],
            "capture_band_vs_noise_p": block["capture_band_vs_noise"]["p_value"],
            "rmae_band_vs_noise_p": block["rmae_band_vs_noise"]["p_value"],
            "capture_between_over_within": block["capture_band_vs_noise"]["between_over_within"],
            "rmae_between_over_within": block["rmae_band_vs_noise"]["between_over_within"],
            "spearman_rmae_vs_capture": block["spearman_rmae_vs_capture"],
            "zone_pairs_separated": block["n_disjoint_zone_pairs"]["n_pairs_excluding_zero"],
            "of_pairs": block["n_disjoint_zone_pairs"]["n_pairs"],
        }
    decided = summary.get("decidability", {}).get(headline)
    if decided:
        out["decidability"] = decided
    if correlation:
        out["mae_vs_capture"] = {
            "n_comparisons": correlation["n_comparisons"],
            "spearman": correlation["spearman"],
            "pearson": correlation["pearson"],
            "n_sign_agreements": correlation["n_sign_agreements"],
        }
    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
