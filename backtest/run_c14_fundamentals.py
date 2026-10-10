"""CLI: the C14 fundamentals chapter — price against residual load, Tier A.

    python -m backtest.run_c14_fundamentals --phase verify
    python -m backtest.run_c14_fundamentals --phase fundamentals
    python -m backtest.run_c14_fundamentals --phase headroom
    python -m backtest.run_c14_fundamentals --phase ladder-compute
    python -m backtest.run_c14_fundamentals --phase ladder-dispatch
    python -m backtest.run_c14_fundamentals --phase ladder-analyse
    python -m backtest.run_c14_fundamentals --phase ingest

PLAN.md C14: *"Fundamentals chapter: price vs residual load (load - wind -
solar) per Tier-A zone, merit-order commentary."* Plus the two notes C13 handed
forward: NOTE C13-03 (does residual-load forecast error explain
``error_over_headroom``?) and NOTE C13-04 / NOTE C8-01 (the 2023 exogenous
ladder, which needs the same ENTSO-E pull this chapter needs).

Why this cycle is descriptive and the earlier ones were predictive
-----------------------------------------------------------------
Every cycle from C3 to C13 asked *what could a bidder have known*. This one asks
*what set the price*, which is a different question with a different honesty
problem, and the difference decides which vintage is allowed where.

The Art. 14 wind/solar D-1 forecast is published at 18:00 local on D-1 — six
hours **after** day-ahead gate closure (``docs/exogenous_model.md``). That makes
it unusable as a *model input* and it is why C8 built the ``res_persistence``
degradation. It does **not** make it unusable as a *description* of the delivery
day: it is the closest thing this project has to realised wind and solar, and
nothing in this chapter is fed to a model or scored as a forecast.

So the rule this module enforces, in code rather than in prose:

* ``FUNDAMENTALS_VINTAGE`` is ``after_gate_closure`` on every row and every
  artefact this phase writes, and :func:`assert_descriptive_only` refuses to let
  a fundamentals frame reach anything that fits or scores a model.
* The honest label travels with the number: the residual load behind every
  figure here is a **forecast** of residual load, not a measurement of it. An
  ENTSO-E *actuals* pull (A65/A16 realised load, A75 realised generation) would
  be the fix and is **out of PLAN.md's declared scope** for this project
  (``PLAN.md``, "Data sources" — Tier A gets the two D-1 forecast documents and
  nothing else), so the limitation is stated, not engineered around.
* The one place a model-facing vintage question arises — NOTE C13-03's
  residual-load *error* — is answered with the pair of vintages C8 already
  defined: as-published against the previous day's publication. That difference
  is a **revision**, it is a lower bound on the true D-1 forecast error, and
  :data:`RES_ERROR_IS_A_REVISION` is the note carried on every row that uses it.

What "merit order" means here, as a measurement
-----------------------------------------------
Short-run marginal cost rises with residual load: cheap must-run and
zero-marginal-cost wind and solar clear first, then lignite, coal, gas, oil.
That makes the price-against-residual-load curve the empirical supply curve of
the zone, and three things about its shape are the chapter:

1. **Convexity.** The slope at high residual load should exceed the slope at
   low residual load, because the marginal unit moves up a steepening stack.
   Measured as the price difference per GW across residual-load deciles.
2. **Level shifts, not shape changes.** 2022's crisis raised the *fuel cost* of
   the same stack. If the merit-order reading is right, 2022 should sit far
   above 2023/2024 at matched residual load while keeping its shape — the
   quantity axis did not change, the money axis did.
3. **The zero floor fails downward.** Below some residual load the stack runs
   out of units willing to turn down, and the price goes negative. That is the
   fundamental behind C13's negative-hour counts, and it predicts ES's first
   negative hours arriving in 2024 (``FINDING C13`` negative-hour table).

All three are reported per (zone, year) and all three are falsifiable here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from typing import Any, Sequence

import numpy as np
import pandas as pd

from backtest.bootstrap import (
    BlockBootstrapSpec,
    Interval,
    _interval,
    mean_interval,
    ratio_interval,
    replicate_counts,
    spearman_rows,
)
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
    Arm,
    FULL_HISTORY_FROM,
    GBM_FINGERPRINT,
    ORACLE_MODEL,
    ORACLE_VARIANT,
    beats_naive,
    mae_on_days,
    pooled_capture,
)
from data.config import (
    REPO_ROOT,
    config_hash,
    load_battery_config,
    load_data_config,
    load_zones,
    zones_for_tier,
)
from data.energy_charts import PRICE_COLUMN
from data.energy_charts import cached_years as cached_price_years
from data.contracts import payload_fingerprint
from data.energy_charts import read_cached_year as read_cached_price_year
from data.entsoe import cached_years as cached_exog_years
from data.entsoe import read_cached_year as read_cached_exog_year
from data.exog_manifest import EXOG_MANIFEST_CSV, series_fingerprint
from data.exogenous import (
    LOAD_COLUMN,
    RESIDUAL_LOAD_COLUMN,
    SOLAR_COLUMN,
    WIND_COLUMN,
    load_zone_exogenous,
)
from data.holdout import assert_not_sealed
from data.manifest import MANIFEST_CSV
from data.prices import load_zone_series
from dispatch.battery import BatterySpec
from dispatch.curves import (
    Curve,
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

#: The years an exogenous column exists for at all: no archived ENTSO-E D-1
#: forecast vintage exists before 2022 (``PLAN.md``), and 2025 is sealed.
EXOG_YEARS: tuple[int, ...] = (2022, 2023, 2024)

#: The one evaluation year a 2022-aligned exogenous arm can add to C11/C12's
#: 2024 (NOTE C13-04): ``align_train_from`` is 2022-01-01 and the harness needs
#: 365 market days of history, so 2023 is the first year it can score.
LADDER_YEAR = 2023

#: Every row this cycle's descriptive phase writes carries this vintage. The
#: Art. 14 wind/solar forecast is published after gate closure, so a residual
#: load built from it is not an honest model input and must never be filed as
#: one, even when the use is purely descriptive.
FUNDAMENTALS_VINTAGE = "after_gate_closure"

#: Carried on every row derived from the as-published-minus-persistence
#: difference. See the module docstring.
RES_ERROR_IS_A_REVISION = (
    "day-over-day revision of the Art. 14 D-1 publication, used as a lower "
    "bound on residual-load forecast error; no realised-generation series is "
    "in PLAN.md's scope"
)

#: Deciles, per (zone, year), for the empirical supply curve.
N_RESIDUAL_LOAD_BINS = 10

#: The bootstrap settings C12/C13 used, repeated so an interval here means what
#: an interval there means.
N_REPLICATES = 10_000
SEED = 20261010
BLOCK_LADDER: tuple[int, ...] = (1, 7, 14)
HEADLINE_BLOCK = 1

#: C13's per-day artefact: the only thing this cycle reads for price-forecast
#: error, so no walk-forward is re-fitted for the headroom question.
C13_DAILY = "c13_daily_by_year.csv.gz"

#: The perfect-foresight curve's name, as C11/C12/C13 spell it.
ORACLE_CURVE = "oracle"

#: C13's comparable arm — the nine-zone like-for-like curve whose
#: ``error_over_headroom`` FINDING C13-D is about.
COMPARABLE_CURVE = "lear_full_history"

FIGURE_DIR = REPO_ROOT / "docs" / "figures"


class FundamentalsError(RuntimeError):
    """A C14 refusal. Never a swallowed one — CLAUDE.md's flag-not-puzzle rule."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        required=True,
        choices=[
            "verify",
            "fundamentals",
            "headroom",
            "ladder-compute",
            "ladder-dispatch",
            "ladder-analyse",
            "ingest",
        ],
    )
    parser.add_argument("--zones", nargs="*", default=None,
                        help="zone keys (default: every Tier-A zone)")
    parser.add_argument("--years", nargs="*", type=int, default=list(EXOG_YEARS),
                        help="years for the descriptive phases (2025 is sealed)")
    parser.add_argument("--no-figures", action="store_true",
                        help="skip the matplotlib output (tests, headless checks)")
    parser.add_argument("--no-append", action="store_true",
                        help="compute and write artefacts, append nothing to the store")
    parser.add_argument("--results-path", default=None,
                        help="override the store path (tests)")
    return parser.parse_args(argv)


def selected_zones(requested: list[str] | None) -> list[str]:
    """Tier A, in config order, or exactly what was asked for."""
    zones = load_zones()
    if requested is None:
        return [z.key for z in zones_for_tier("A")]
    unknown = [z for z in requested if z not in zones]
    if unknown:
        raise FundamentalsError(f"unknown zone key(s) {unknown}; known: {sorted(zones)}")
    return list(requested)


# ---------------------------------------------------------------------------
# Phase `verify`: the re-pulled cache is the one the committed manifests describe
# ---------------------------------------------------------------------------


def verify_price_cache(zones: Sequence[str]) -> dict[str, Any]:
    """Every re-pulled price file's data fingerprint against C1's committed manifest.

    ``data/raw/`` does not survive a container (NOTE C2-02, now at its 25th
    recurrence), so every cycle that needs prices re-downloads them. That makes
    this the cheapest provenance test in the project.

    It calls **the manifest's own** ``payload_fingerprint`` rather than hashing
    the cached file. That is not a convenience: the cached file embeds a
    ``_fetch_meta.fetched_at_utc`` stamp, so a file hash changes on every
    re-fetch even when the prices are identical, and a check built on it would
    fail every single cycle and teach a reader to ignore it (PROGRESS.md NOTE
    C2-01, the Checkpoint-A decision that replaced exactly that column). The
    fingerprint covers the ``(UTC epoch, price)`` pairs at fixed precision and
    nothing else, so it changes **iff** Energy-Charts returned different prices.
    """
    manifest = pd.read_csv(MANIFEST_CSV)
    cfg = load_data_config()
    rows: list[dict[str, Any]] = []
    for zone in load_zones():
        for year in cached_price_years(zone, cfg):
            frame = read_cached_price_year(zone, int(year), cfg)
            got = payload_fingerprint(frame)
            want_row = manifest[(manifest["zone"] == zone) & (manifest["year"] == year)]
            want = None if want_row.empty else str(want_row["payload_sha256"].iloc[0])
            rows.append(
                {
                    "zone": zone,
                    "year": int(year),
                    "n_points": int(len(frame)),
                    "cached_payload_sha256": got,
                    "manifest_payload_sha256": want,
                    "matches": bool(want is not None and got == want),
                    "in_manifest": bool(not want_row.empty),
                }
            )
    frame_out = pd.DataFrame(rows)
    mismatched = frame_out[~frame_out["matches"]]
    return {
        "n_files": int(len(frame_out)),
        "n_matching": int(frame_out["matches"].sum()),
        "n_mismatched": int(len(mismatched)),
        "mismatched": mismatched.to_dict("records"),
        "holds": bool(len(mismatched) == 0 and len(frame_out) > 0),
        "fingerprint": "data.contracts.payload_fingerprint (UTC epoch, price) pairs",
        "note": (
            "C1 committed these fingerprints; the cache is re-pulled every "
            "container (NOTE C2-02). Identical fingerprints mean the manifest "
            "needs no regeneration, which is C8/C9/C10/C13's precedent."
        ),
    }


def verify_exog_cache(zones: Sequence[str]) -> dict[str, Any]:
    """The same check for C7's 18 ENTSO-E documents, **per series**.

    The exogenous manifest has one row per ``(zone, document, series, year)`` and
    its ``payload_sha256`` is ``series_fingerprint(frame, column)`` — one hash
    per *column*, not per document. So the A69 wind/solar document carries two
    different hashes, and a check keyed on (zone, document, year) would find two
    candidate values and have to pick one. This checks all 27 series rows.
    """
    manifest = pd.read_csv(EXOG_MANIFEST_CSV)
    cfg = load_data_config()
    documents = sorted(manifest["document"].unique())
    rows: list[dict[str, Any]] = []
    for zone in zones:
        for document in documents:
            for year in cached_exog_years(zone, document, cfg):
                frame = read_cached_exog_year(zone, document, int(year), cfg)
                for column in frame.columns:
                    got = series_fingerprint(frame, column)
                    want_rows = manifest[
                        (manifest["zone"] == zone)
                        & (manifest["document"] == document)
                        & (manifest["series"] == column)
                        & (manifest["year"] == year)
                    ]
                    want = (
                        None if want_rows.empty
                        else str(want_rows["payload_sha256"].iloc[0])
                    )
                    rows.append(
                        {
                            "zone": zone,
                            "document": document,
                            "series": column,
                            "year": int(year),
                            "n_points": int(len(frame)),
                            "cached_payload_sha256": got,
                            "manifest_payload_sha256": want,
                            "matches": bool(want is not None and got == want),
                            "in_manifest": bool(not want_rows.empty),
                        }
                    )
    frame_out = pd.DataFrame(rows)
    mismatched = frame_out[~frame_out["matches"]]
    return {
        "n_files": int(frame_out[["zone", "document", "year"]].drop_duplicates().shape[0]),
        "n_series": int(len(frame_out)),
        "n_matching": int(frame_out["matches"].sum()),
        "n_mismatched": int(len(mismatched)),
        "mismatched": mismatched.to_dict("records"),
        "holds": bool(len(mismatched) == 0 and len(frame_out) > 0),
        "fingerprint": "data.exog_manifest.series_fingerprint (UTC epoch, value) pairs, per series",
        "note": (
            "A changed fingerprint here would mean ENTSO-E revised an archived "
            "D-1 forecast vintage, which would invalidate C8's and C9's measured "
            "vintage premium — so it is a FLAG, not a tolerance."
        ),
    }


def verify(args: argparse.Namespace) -> int:
    zones = selected_zones(args.zones)
    prices = verify_price_cache(zones)
    exog = verify_exog_cache(zones)
    report = {
        "cycle": "C14",
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "prices": prices,
        "exogenous": exog,
        "holds": bool(prices["holds"] and exog["holds"]),
    }
    out = RESULTS_DIR / "c14_cache_verification.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
        fh.write("\n")
    print(f"prices:     {prices['n_matching']}/{prices['n_files']} payload fingerprints "
          f"identical to C1's manifest")
    print(f"exogenous:  {exog['n_matching']}/{exog['n_series']} series fingerprints "
          f"identical to C7's manifest ({exog['n_files']} documents)")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    if not report["holds"]:
        print("FLAG C14: a re-pulled payload differs from the committed manifest",
              file=sys.stderr)
        for row in prices["mismatched"] + exog["mismatched"]:
            print(f"  {row}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# The fundamentals frame
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundamentalsFrame:
    """One zone's hourly price beside its D-1 residual-load forecast.

    ``vintage`` is on the dataclass rather than in a comment so that
    :func:`assert_descriptive_only` can refuse the frame by inspecting it.
    """

    zone: str
    frame: pd.DataFrame
    vintage: str
    n_price_hours: int
    n_exog_hours: int
    n_joined_hours: int
    n_dropped_missing_residual_load: int
    years: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "vintage": self.vintage,
            "n_price_hours": self.n_price_hours,
            "n_exog_hours": self.n_exog_hours,
            "n_joined_hours": self.n_joined_hours,
            "n_dropped_missing_residual_load": self.n_dropped_missing_residual_load,
            "years": list(self.years),
            "columns": list(self.frame.columns),
        }


def assert_descriptive_only(frame: FundamentalsFrame) -> None:
    """Refuse a fundamentals frame anywhere a model could be fitted on it.

    The frame holds the as-published Art. 14 vintage, which is six hours late.
    Nothing stops a later cycle importing :func:`fundamentals_frame` and handing
    the result to a feature builder, so the refusal is a callable that the two
    fitting phases of this module call on their own inputs, and a test asserts
    it fires.
    """
    if frame.vintage != FUNDAMENTALS_VINTAGE:
        raise FundamentalsError(
            f"{frame.zone}: a fundamentals frame must be labelled "
            f"{FUNDAMENTALS_VINTAGE!r}, got {frame.vintage!r}"
        )
    raise FundamentalsError(
        f"{frame.zone}: this frame carries the as-published Art. 14 vintage "
        f"(published 18:00 on D-1, six hours after gate closure). It is a "
        f"description of the delivery day, not an information set. Fitting or "
        f"scoring a forecast on it is the leak C8 exists to measure — use "
        f"forecast.exog_features.attach_exogenous with an ExogSpec instead."
    )


def fundamentals_frame(
    zone_key: str, years: Sequence[int] = EXOG_YEARS
) -> FundamentalsFrame:
    """Hourly realised price joined to the D-1 load/wind/solar/residual forecast.

    The join is an inner join on the UTC index and an hour missing *any*
    component is dropped rather than part-filled: ``add_residual_load`` already
    NaNs an hour whose wind or solar is absent (``docs/entsoe_layer.md``), and a
    residual load computed from load alone would be the largest outlier in every
    figure in this chapter.

    ``local_hour`` and ``local_market_day`` are explicit columns, per CLAUDE.md,
    and neither is used to resample or align anything: the index is UTC
    throughout and the aggregation that produced these hours was C7's UTC-hour
    tiling.
    """
    wanted = tuple(sorted(int(y) for y in years))
    assert_not_sealed(set(wanted), f"build the fundamentals frame for {zone_key}")
    tz = zone_timezone(zone_key)

    prices = load_zone_series(zone_key)[PRICE_COLUMN].astype(float)
    # `on_partial="flag"` is C7/C8's standing rule: a partial hour is NaN and
    # reported, never averaged from the sub-hourly rows that did arrive.
    exog = load_zone_exogenous(zone_key, on_partial="flag")
    for column in (LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN, RESIDUAL_LOAD_COLUMN):
        if column not in exog.columns:
            raise FundamentalsError(
                f"{zone_key}: {column} is absent from the cached exogenous frame "
                f"(have {list(exog.columns)}) — run `python -m data.fetch_exogenous`"
            )

    joined = pd.DataFrame({PRICE_COLUMN: prices}).join(
        exog[[LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN, RESIDUAL_LOAD_COLUMN]], how="inner"
    )
    local = pd.DatetimeIndex(joined.index).tz_convert(tz)
    joined["local_market_day"] = market_days(pd.DatetimeIndex(joined.index), tz)
    joined["local_hour"] = local.hour
    joined["weekday"] = local.weekday
    joined["year"] = pd.Series(joined["local_market_day"]).map(lambda d: d.year).to_numpy()
    joined = joined[joined["year"].isin(wanted)]

    before = len(joined)
    complete = joined.dropna(
        subset=[PRICE_COLUMN, LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN, RESIDUAL_LOAD_COLUMN]
    )
    if complete.empty:
        raise FundamentalsError(
            f"{zone_key}: no hour has a price and a complete residual-load forecast "
            f"in {wanted}"
        )
    # Belt and braces: `assert_not_sealed` ran on the *requested* years above,
    # this runs on the years that actually arrived. A sealed year could only get
    # here through a stray cache file, which is exactly what C1's guard says a
    # loader must refuse rather than quietly include.
    seen = sorted({int(y) for y in complete["year"].unique()})
    assert_not_sealed(set(seen), f"describe the fundamentals of {zone_key}")

    return FundamentalsFrame(
        zone=zone_key,
        frame=complete,
        vintage=FUNDAMENTALS_VINTAGE,
        n_price_hours=int(len(prices)),
        n_exog_hours=int(len(exog)),
        n_joined_hours=int(len(complete)),
        n_dropped_missing_residual_load=int(before - len(complete)),
        years=tuple(seen),
    )


# ---------------------------------------------------------------------------
# The bootstrap, reusing C12's construction rather than inventing one
# ---------------------------------------------------------------------------


@lru_cache(maxsize=16)
def block_day_picks(spec: BlockBootstrapSpec) -> np.ndarray:
    """``(n_replicates, n_days)`` of *day indices*, not counts.

    Every statistic C11-C13 bootstrapped is a ratio or a mean of day-additive
    columns, so ``backtest.bootstrap.replicate_counts`` returns a count matrix
    and each statistic is one matmul. A **rank** correlation is not day-additive
    — it needs the resampled sample itself — so this returns the picks.

    It must be the *same* resample, or a C14 interval would not be comparable to
    a C12 or C13 one. Rather than argue that, the function asserts it: the
    per-day draw counts implied by these picks are compared against
    ``replicate_counts(spec)`` element by element, so the two constructions
    cannot drift apart silently.

    Cached on the spec, which is a frozen dataclass and therefore hashable, and
    returned **read-only**: this cycle asks for the same (n_days, block) spec a
    hundred times over and the drift assertion costs two passes over a
    10 000 x 365 matrix each time. A cached array handed out mutable would let
    one caller corrupt every later one, so the writeable flag is cleared.
    """
    rng = np.random.default_rng(spec.seed)
    starts = rng.integers(
        0, spec.n_days, size=(spec.n_replicates, spec.n_blocks), dtype=np.int64
    )
    offsets = np.arange(spec.block_days, dtype=np.int64)
    picks = (starts[:, :, None] + offsets[None, None, :]) % spec.n_days
    picks = picks.reshape(spec.n_replicates, -1)[:, : spec.n_days]

    counts = np.zeros((spec.n_replicates, spec.n_days), dtype=np.float64)
    rows = np.repeat(np.arange(spec.n_replicates, dtype=np.int64), spec.n_days)
    np.add.at(counts, (rows, picks.reshape(-1)), 1.0)
    if not np.array_equal(counts, replicate_counts(spec)):
        raise FundamentalsError(
            "C14's day picks do not reproduce backtest.bootstrap's count matrix "
            "for the same spec — the two resamples have drifted apart and a C14 "
            "interval would not be comparable to a C12/C13 one"
        )
    picks.flags.writeable = False
    return picks


def spearman_interval(
    x: Sequence[float], y: Sequence[float], spec: BlockBootstrapSpec
) -> Interval:
    """Spearman rank correlation of two per-day columns, with a block interval.

    ``spearman_rows`` already handles ties with average ranks and returns NaN
    for a flat row, which is the behaviour wanted here: a replicate that happens
    to draw a constant column contributes no correlation rather than a spurious
    one.
    """
    xs = np.asarray(x, dtype=np.float64)
    ys = np.asarray(y, dtype=np.float64)
    if xs.shape != ys.shape or xs.ndim != 1:
        raise FundamentalsError(f"need two 1-d columns of equal length, got {xs.shape}, {ys.shape}")
    point = float(spearman_rows(xs[None, :], ys[None, :])[0])
    picks = block_day_picks(spec)
    replicates = spearman_rows(xs[picks], ys[picks])
    return _interval(point, replicates, spec)


def _spec(n_days: int, block_days: int = HEADLINE_BLOCK) -> BlockBootstrapSpec:
    return BlockBootstrapSpec(
        n_days=n_days, n_replicates=N_REPLICATES, block_days=block_days, seed=SEED
    )


# ---------------------------------------------------------------------------
# Phase `fundamentals`: the empirical supply curve
# ---------------------------------------------------------------------------


def _year_slice(frame: pd.DataFrame, year: int) -> pd.DataFrame:
    out = frame[frame["year"] == year]
    if len(out) < 24 * 300:
        raise FundamentalsError(
            f"{year}: only {len(out)} complete hours — too few for a merit-order curve"
        )
    return out


def merit_order_table(
    frame: pd.DataFrame, zone: str, year: int, n_bins: int = N_RESIDUAL_LOAD_BINS
) -> pd.DataFrame:
    """Price against residual load, in residual-load quantile bins.

    Quantile bins rather than equal-width ones because the residual-load
    distribution is strongly asymmetric in every zone and an equal-width bin at
    the bottom of DE-LU's range would hold a handful of hours. Each bin reports
    its own residual-load range, so the slope between two bins is a real
    EUR/MWh-per-GW and not an artefact of unequal bin widths.

    The median is the headline statistic, not the mean: the price distribution
    inside a bin is heavily right-skewed (scarcity hours) and the merit-order
    claim is about where the marginal unit sits, not about the tail.
    """
    rows_in = _year_slice(frame, year)
    rl = rows_in[RESIDUAL_LOAD_COLUMN].to_numpy(dtype=float) / 1000.0
    price = rows_in[PRICE_COLUMN].to_numpy(dtype=float)
    bins = pd.qcut(rl, n_bins, labels=False, duplicates="drop")
    table = pd.DataFrame({"bin": bins, "rl_gw": rl, "price": price})
    grouped = table.groupby("bin")
    out = pd.DataFrame(
        {
            "zone": zone,
            "year": year,
            "bin": grouped.size().index.to_numpy(),
            "n_hours": grouped.size().to_numpy(),
            "rl_gw_min": grouped["rl_gw"].min().to_numpy(),
            "rl_gw_median": grouped["rl_gw"].median().to_numpy(),
            "rl_gw_max": grouped["rl_gw"].max().to_numpy(),
            "price_median": grouped["price"].median().to_numpy(),
            "price_mean": grouped["price"].mean().to_numpy(),
            "price_p10": grouped["price"].quantile(0.10).to_numpy(),
            "price_p90": grouped["price"].quantile(0.90).to_numpy(),
            "share_negative": grouped["price"].apply(lambda s: float((s < 0).mean())).to_numpy(),
            "share_zero_or_below": grouped["price"].apply(
                lambda s: float((s <= 0).mean())
            ).to_numpy(),
        }
    )
    # EUR/MWh per GW between this bin's median and the previous bin's. The first
    # bin has no predecessor and is NaN rather than 0 — a slope that does not
    # exist is not a flat one.
    d_price = out["price_median"].diff()
    d_rl = out["rl_gw_median"].diff()
    out["slope_eur_mwh_per_gw"] = d_price / d_rl
    return out


def explanatory_power(frame: pd.DataFrame, zone: str, year: int) -> dict[str, Any]:
    """How much of the hourly price does residual load alone account for?

    Five specifications, all fitted on the whole (zone, year) — this is a
    *description* of the year, not an out-of-sample forecast, and nothing here is
    scored as one. Two of the five are chosen so that the comparisons are
    **nested**, which is what makes the two "gain" columns interpretable:

    * ``linear`` — price on residual load. Two parameters. The textbook reading,
      and the one that understates a convex stack.
    * ``binned`` — price on a 20-quantile-bin step function. Twenty parameters.
      This is the fit the decile figure draws, and it is reported for that
      reason, but it is **not** an upper bound on what residual load can explain:
      a step function throws away the variation *inside* each bin, so on a smooth
      relationship it scores *below* the straight line. On an exactly linear
      synthetic zone it comes back at 0.995, not 1.0, and DE-LU 2024 is the real
      case where ``binned`` sits below ``linear``.
    * ``piecewise_linear`` — a separate intercept **and slope** per bin. Forty
      parameters, and it **nests** ``linear``, so its R^2 can never be lower and
      ``nonlinearity_gain`` is a clean measure of curvature rather than curvature
      minus discretisation loss. This is the one to read as "the best a function
      of residual load alone does on these hours".
    * ``calendar`` — hour-of-day and weekday dummies, **additively**. Thirty
      parameters. The control: residual load is itself strongly diurnal, so a
      residual-load R^2 that does not beat this is not telling us anything a
      clock would not.
    * ``residual_load_plus_calendar`` — the piecewise-linear residual-load block
      plus the same calendar dummies, additively, which nests ``calendar``. Its
      gain over ``calendar`` is the part of the price residual load explains that
      the clock cannot.

    The calendar block is deliberately **additive** rather than an hour x weekday
    x bin interaction. A full interaction would be ~3 400 cells on ~8 760 hours,
    about 2.6 observations each, and its in-sample R^2 would be an artefact of
    the cell count rather than a statement about the price. ``n_parameters_*`` is
    reported for every specification so that the in-sample caveat is a number a
    reader can check, not a disclaimer.

    An R^2 here is in-sample by construction and is reported as a descriptive
    share of variance, never as skill.
    """
    rows_in = _year_slice(frame, year)
    price = rows_in[PRICE_COLUMN].to_numpy(dtype=float)
    rl = rows_in[RESIDUAL_LOAD_COLUMN].to_numpy(dtype=float) / 1000.0
    total = float(((price - price.mean()) ** 2).sum())
    if total <= 0:
        raise FundamentalsError(f"{zone} {year}: the price is constant")

    def _r2(design: np.ndarray) -> float:
        """R^2 of a least-squares fit, with the intercept already in ``design``."""
        coefficients, *_ = np.linalg.lstsq(design, price, rcond=None)
        return float(1.0 - ((price - design @ coefficients) ** 2).sum() / total)

    ones = np.ones((len(price), 1))
    bins = pd.qcut(rl, 20, labels=False, duplicates="drop").astype("int64")
    n_bins = int(bins.max()) + 1
    bin_dummies = np.zeros((len(price), n_bins))
    bin_dummies[np.arange(len(price)), bins] = 1.0
    # A slope per bin: the bin indicator times residual load. Together with the
    # bin intercepts this is a piecewise-linear (discontinuous) fit that nests
    # the global straight line.
    bin_slopes = bin_dummies * rl[:, None]

    hour = rows_in["local_hour"].to_numpy(dtype="int64")
    weekday = rows_in["weekday"].to_numpy(dtype="int64")
    hour_dummies = np.zeros((len(price), 24))
    hour_dummies[np.arange(len(price)), hour] = 1.0
    weekday_dummies = np.zeros((len(price), 7))
    weekday_dummies[np.arange(len(price)), weekday] = 1.0
    calendar = np.column_stack([ones, hour_dummies, weekday_dummies])

    designs = {
        "linear": np.column_stack([ones, rl]),
        "binned_20": np.column_stack([ones, bin_dummies]),
        "piecewise_linear_20": np.column_stack([ones, bin_dummies, bin_slopes]),
        "calendar_only": calendar,
        "residual_load_plus_calendar": np.column_stack(
            [calendar, bin_dummies, bin_slopes]
        ),
    }
    r2 = {name: _r2(design) for name, design in designs.items()}

    # Nesting is a theorem, so a violation beyond floating point is a wrong
    # design matrix, not a finding. Checked rather than asserted in prose.
    for larger, smaller in (
        ("piecewise_linear_20", "linear"),
        ("residual_load_plus_calendar", "calendar_only"),
    ):
        if r2[larger] < r2[smaller] - 1e-9:
            raise FundamentalsError(
                f"{zone} {year}: {larger} (R2 {r2[larger]:.8f}) nests {smaller} "
                f"(R2 {r2[smaller]:.8f}) and cannot score lower — the design "
                f"matrix is wrong"
            )

    out: dict[str, Any] = {
        "zone": zone,
        "year": year,
        "n_hours": int(len(rows_in)),
        "n_residual_load_bins": n_bins,
        "spearman_price_residual_load": round(
            float(pd.Series(rl).corr(pd.Series(price), method="spearman")), 6
        ),
        "pearson_price_residual_load": round(float(np.corrcoef(rl, price)[0, 1]), 6),
    }
    for name, design in designs.items():
        out[f"r2_{name}"] = round(r2[name], 6)
        out[f"n_parameters_{name}"] = int(np.linalg.matrix_rank(design))
    out["nonlinearity_gain"] = round(r2["piecewise_linear_20"] - r2["linear"], 6)
    out["gain_over_calendar"] = round(
        r2["residual_load_plus_calendar"] - r2["calendar_only"], 6
    )
    out["discretisation_loss_of_the_step_fit"] = round(
        r2["piecewise_linear_20"] - r2["binned_20"], 6
    )
    return out


def convexity(table: pd.DataFrame) -> dict[str, Any]:
    """Is the empirical supply curve steeper at the top than in the middle?

    The merit-order prediction is a *convex* stack: the marginal unit at high
    residual load is a peaking plant with a high fuel cost, so the slope there
    should exceed the slope through the middle of the distribution.

    Measured on the decile medians, three slopes:

    * ``slope_low`` — deciles 1 to 4. This one is **not** the merit-order claim.
      In a zone with surplus RES it is dominated by the turn-down cliff where
      prices fall through zero, which is a different mechanism (inflexible
      must-run paying to stay on) and can make the bottom of the curve steeper
      than the top. Reported so that the two are not confused.
    * ``slope_mid`` — deciles 4 to 7, the comparison baseline.
    * ``slope_high`` — deciles 7 to 10, the merit-order claim.

    ``convex_at_the_top`` is ``slope_high > slope_mid``. A zone-year that fails
    it is a finding about that zone's price formation, not a bug.
    """
    if len(table) < 10:
        raise FundamentalsError(f"convexity needs 10 bins, got {len(table)}")
    median = table["price_median"].to_numpy(dtype=float)
    rl = table["rl_gw_median"].to_numpy(dtype=float)

    def _slope(lo: int, hi: int) -> float:
        return float((median[hi] - median[lo]) / (rl[hi] - rl[lo]))

    low, mid, high = _slope(0, 3), _slope(3, 6), _slope(6, 9)
    return {
        "zone": str(table["zone"].iloc[0]),
        "year": int(table["year"].iloc[0]),
        "slope_low_eur_mwh_per_gw": round(low, 4),
        "slope_mid_eur_mwh_per_gw": round(mid, 4),
        "slope_high_eur_mwh_per_gw": round(high, 4),
        # The ratio is only a convexity measure when both slopes are positive.
        # NO2 2022 is the live case: both are *negative*, so their ratio comes
        # out at +1.78 and would read as "steeply convex" when what it actually
        # says is "steeper downward at the top". The flag beside it is what a
        # reader must check before quoting the ratio; `convex_at_the_top`
        # compares the slopes directly and is correct either way.
        "high_over_mid": round(high / mid, 4) if mid != 0 else None,
        "slopes_are_positive": bool(mid > 0 and high > 0),
        "high_over_mid_is_a_convexity_ratio": bool(mid > 0 and high > 0),
        "convex_at_the_top": bool(high > mid),
        "monotone_decile_medians": bool(np.all(np.diff(median) >= 0)),
        "n_decile_decreases": int(int(np.sum(np.diff(median) < 0))),
        "price_median_bottom_decile": round(float(median[0]), 4),
        "price_median_top_decile": round(float(median[-1]), 4),
        "decile_range_eur_mwh": round(float(median[-1] - median[0]), 4),
    }


def negative_price_concentration(
    frame: pd.DataFrame, zone: str, year: int, table: pd.DataFrame
) -> dict[str, Any]:
    """Are a zone's negative hours a low-residual-load phenomenon?

    The merit-order reading of a negative price is specific: wind and solar have
    pushed residual load so low that the units still running would rather pay to
    stay on than cycle off. If that is the mechanism, the negative hours must
    pile up in the bottom of the residual-load distribution.

    ``share_of_negatives_in_bottom_decile`` is the test, and 10% is the number to
    compare against — that is what the share would be if negative hours fell
    uniformly across the residual-load distribution. A zone whose negative hours
    are spread uniformly has negative prices for some *other* reason, and this
    chapter should say so rather than assume the textbook mechanism everywhere.
    """
    rows_in = _year_slice(frame, year)
    rl = rows_in[RESIDUAL_LOAD_COLUMN].to_numpy(dtype=float) / 1000.0
    price = rows_in[PRICE_COLUMN].to_numpy(dtype=float)
    negative = price < 0
    n_negative = int(negative.sum())
    bins = pd.qcut(rl, N_RESIDUAL_LOAD_BINS, labels=False, duplicates="drop")
    n_bins = int(bins.max()) + 1
    uniform_share = 1.0 / n_bins

    if n_negative:
        in_bottom = float((bins[negative] == 0).mean())
        in_bottom_two = float((bins[negative] <= 1).mean())
        worst_rl = float(rl[negative].max())
    else:
        in_bottom = in_bottom_two = worst_rl = float("nan")

    # The residual load below which a negative price is more likely than not.
    share = table.set_index("bin")["share_negative"]
    crossing = [b for b in share.index if share.loc[b] >= 0.5]
    threshold_gw = (
        float(table.loc[table["bin"] == max(crossing), "rl_gw_max"].iloc[0])
        if crossing else None
    )
    return {
        "zone": zone,
        "year": year,
        "n_hours": int(len(rows_in)),
        "n_negative_hours": n_negative,
        "share_negative_hours": round(float(negative.mean()), 6),
        "n_bins": n_bins,
        "uniform_share": round(uniform_share, 6),
        "share_of_negatives_in_bottom_decile": (
            None if n_negative == 0 else round(in_bottom, 6)
        ),
        "share_of_negatives_in_bottom_two_deciles": (
            None if n_negative == 0 else round(in_bottom_two, 6)
        ),
        "concentration_vs_uniform": (
            None if n_negative == 0 else round(in_bottom / uniform_share, 4)
        ),
        "highest_residual_load_with_a_negative_price_gw": (
            None if n_negative == 0 else round(worst_rl, 4)
        ),
        "residual_load_gw_below_which_negative_is_more_likely_than_not": (
            None if threshold_gw is None else round(threshold_gw, 4)
        ),
        "mechanism_consistent_with_res_surplus": (
            None if n_negative == 0 else bool(in_bottom >= 2.0 * uniform_share)
        ),
    }


def _ols(design: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float]:
    """Least squares with an intercept, returning coefficients and R^2."""
    augmented = np.column_stack([np.ones(len(design)), design])
    coefficients, *_ = np.linalg.lstsq(augmented, target, rcond=None)
    fitted = augmented @ coefficients
    total = float(((target - target.mean()) ** 2).sum())
    r2 = float(1.0 - ((target - fitted) ** 2).sum() / total) if total > 0 else float("nan")
    return coefficients, r2


def residual_load_sufficiency(frame: pd.DataFrame, zone: str, year: int) -> dict[str, Any]:
    """Is ``load - wind - solar`` a sufficient statistic, or do the three differ?

    The merit-order story says only the *residual* matters: a GW of load and a
    GW less wind are the same displacement up the stack, so a regression on the
    three components separately should return coefficients of roughly
    ``(+b, -b, -b)``.

    Two ways that can fail, both economically real and both reported rather than
    assumed away:

    * **Solar and wind are not interchangeable.** Solar arrives in a fixed
      midday block, so a GW of solar lands on a different part of the stack than
      a GW of wind, which can arrive at any hour. If ``|b_solar| > |b_wind|``,
      the zone is showing the self-cannibalisation effect.
    * **The restriction is simply rejected.** ``r2_components`` minus
      ``r2_residual_only`` is how much is lost by imposing it. A large gap says
      residual load is a summary, not a sufficient statistic.

    A zone with no solar fleet at all (NO2) returns a NaN solar coefficient
    rather than a fitted zero — the column is identically zero there, so the
    coefficient is not identified and pretending otherwise would put a
    meaningless number in a table.
    """
    rows_in = _year_slice(frame, year)
    price = rows_in[PRICE_COLUMN].to_numpy(dtype=float)
    load = rows_in[LOAD_COLUMN].to_numpy(dtype=float) / 1000.0
    wind = rows_in[WIND_COLUMN].to_numpy(dtype=float) / 1000.0
    solar = rows_in[SOLAR_COLUMN].to_numpy(dtype=float) / 1000.0
    residual = rows_in[RESIDUAL_LOAD_COLUMN].to_numpy(dtype=float) / 1000.0

    solar_identified = bool(np.ptp(solar) > 1e-9)
    columns = [load, wind] + ([solar] if solar_identified else [])
    coefficients, r2_components = _ols(np.column_stack(columns), price)
    _, r2_residual = _ols(residual[:, None], price)

    b_load = float(coefficients[1])
    b_wind = float(coefficients[2])
    b_solar = float(coefficients[3]) if solar_identified else float("nan")

    # Two contrasts worth an interval, because both are sign claims and a sign
    # claim without one is an anecdote. Resampled by *market day* with the same
    # circular moving-block construction C12/C13 used, so an interval here is
    # the same kind of object as an interval there. The refit inside a replicate
    # is a 3-column least squares on ~8 760 rows, which is cheap enough to do
    # 10 000 times only because it is a normal-equations solve; the loop below
    # builds the per-day cross-products once and sums the *drawn* ones.
    days = pd.Series(rows_in["local_market_day"].to_numpy())
    day_codes, day_index = pd.factorize(days, sort=True)
    n_days = len(day_index)
    design = np.column_stack([np.ones(len(price))] + columns)
    k = design.shape[1]
    # Per-day X'X and X'y, so a replicate's fit is a weighted sum of them.
    xtx_by_day = np.zeros((n_days, k, k))
    xty_by_day = np.zeros((n_days, k))
    np.add.at(xtx_by_day, day_codes, design[:, :, None] * design[:, None, :])
    np.add.at(xty_by_day, day_codes, design * price[:, None])

    intervals: dict[str, Interval | None] = {}
    if n_days >= 2:
        spec = _spec(n_days, HEADLINE_BLOCK)
        counts = replicate_counts(spec)
        xtx = np.tensordot(counts, xtx_by_day, axes=(1, 0))
        xty = np.tensordot(counts, xty_by_day, axes=(1, 0))
        drawn = np.linalg.solve(xtx, xty[:, :, None])[:, :, 0]
        cancel = drawn[:, 1] + drawn[:, 2]
        intervals["wind_plus_load_cancels"] = _interval(b_load + b_wind, cancel, spec)
        if solar_identified:
            intervals["solar_minus_wind_coefficient"] = _interval(
                b_solar - b_wind, drawn[:, 3] - drawn[:, 2], spec
            )

    # A per-GW slope is not comparable across zones of different size: NO2's
    # mean load is 4 GW and DE-LU's is 54, so the same *relative* displacement
    # is 13x the GW in DE-LU. The normalised figure is EUR/MWh per 10% of that
    # zone-year's own mean load, which is the number a cross-zone sentence may
    # legitimately use.
    mean_load_gw = float(load.mean())
    scale = mean_load_gw / 10.0
    out: dict[str, Any] = {
        "zone": zone,
        "year": year,
        "n_hours": int(len(rows_in)),
        "n_market_days": int(n_days),
        "mean_load_gw": round(mean_load_gw, 4),
        "solar_coefficient_identified": solar_identified,
        "coef_load_eur_mwh_per_gw": round(b_load, 4),
        "coef_wind_eur_mwh_per_gw": round(b_wind, 4),
        "coef_solar_eur_mwh_per_gw": (None if not solar_identified else round(b_solar, 4)),
        "coef_load_eur_mwh_per_10pct_mean_load": round(b_load * scale, 4),
        "coef_wind_eur_mwh_per_10pct_mean_load": round(b_wind * scale, 4),
        "coef_solar_eur_mwh_per_10pct_mean_load": (
            None if not solar_identified else round(b_solar * scale, 4)
        ),
        "r2_components": round(r2_components, 6),
        "r2_residual_load_only": round(r2_residual, 6),
        "r2_lost_by_imposing_residual_load": round(r2_components - r2_residual, 6),
        "wind_plus_load_cancels": round(b_load + b_wind, 4),
        "solar_minus_wind_coefficient": (
            None if not solar_identified else round(b_solar - b_wind, 4)
        ),
        "solar_cannibalises_more_than_wind": (
            None if not solar_identified else bool(abs(b_solar) > abs(b_wind))
        ),
    }
    for name, interval in intervals.items():
        if interval is None:
            continue
        out[f"{name}_ci_low"] = round(interval.ci_low, 4)
        out[f"{name}_ci_high"] = round(interval.ci_high, 4)
        out[f"{name}_excludes_zero"] = interval.excludes_zero
        out[f"{name}_boot_sd"] = round(interval.boot_sd, 4)
    return out


def level_versus_shape(tables: dict[int, pd.DataFrame], zone: str) -> dict[str, Any]:
    """Did the 2022 crisis move the supply curve up, or bend it?

    The merit-order reading of a fuel-cost shock is specific and falsifiable: the
    *quantity* axis did not change (the same plants, in the same order, at the
    same capacities) while the *money* axis was multiplied. So the decile curve
    should shift up roughly proportionally and keep its shape.

    Two measurements, per year pair:

    * **Level** — the ratio of the two years' median-decile prices. This is the
      fuel-cost shock, and it is the thing no model in this project has as a
      feature (PLAN.md excluded the gas-price proxy for being sign-unstable, see
      ``docs/audit.md``).
    * **Shape** — the Spearman correlation of the ten decile medians between the
      two years, and the correlation of the *normalised* curve (each year's
      decile medians divided by that year's decile-5 median). A high shape
      correlation with a large level ratio is the clean "shifted, not bent"
      signature.

    Spearman over ten points is a weak instrument and is reported as such; the
    normalised-curve comparison is the one that can distinguish a parallel shift
    from a steepening, because a monotone curve has a perfect rank correlation
    with any other monotone curve.
    """
    years = sorted(tables)
    pairs: list[dict[str, Any]] = []
    for i, early in enumerate(years):
        for late in years[i + 1:]:
            a, b = tables[early], tables[late]
            if len(a) != len(b):
                raise FundamentalsError(
                    f"{zone}: {early} has {len(a)} bins and {late} has {len(b)}"
                )
            ma = a["price_median"].to_numpy(dtype=float)
            mb = b["price_median"].to_numpy(dtype=float)
            mid_a, mid_b = float(ma[4]), float(mb[4])
            normalised_a = ma / mid_a if mid_a != 0 else np.full_like(ma, np.nan)
            normalised_b = mb / mid_b if mid_b != 0 else np.full_like(mb, np.nan)
            finite = np.isfinite(normalised_a) & np.isfinite(normalised_b)
            pairs.append(
                {
                    "zone": zone,
                    "early_year": early,
                    "late_year": late,
                    "level_ratio_mid_decile": (
                        round(mid_b / mid_a, 4) if mid_a != 0 else None
                    ),
                    "level_difference_mid_decile_eur_mwh": round(mid_b - mid_a, 4),
                    "shape_spearman_decile_medians": round(
                        float(pd.Series(ma).corr(pd.Series(mb), method="spearman")), 6
                    ),
                    "shape_pearson_normalised": (
                        round(float(np.corrcoef(normalised_a[finite], normalised_b[finite])[0, 1]), 6)
                        if finite.sum() >= 3 else None
                    ),
                    "normalised_curve_max_abs_difference": (
                        round(float(np.max(np.abs(normalised_a[finite] - normalised_b[finite]))), 4)
                        if finite.sum() >= 3 else None
                    ),
                    "residual_load_overlap_gw": round(
                        float(
                            min(a["rl_gw_max"].max(), b["rl_gw_max"].max())
                            - max(a["rl_gw_min"].min(), b["rl_gw_min"].min())
                        ),
                        4,
                    ),
                }
            )
    return {"zone": zone, "pairs": pairs}


# ---------------------------------------------------------------------------
# Phase `headroom`: NOTE C13-03
# ---------------------------------------------------------------------------

#: The three per-day correlations NOTE C13-03 reduces to. Each is a
#: ``(fundamental column, outcome column, what it would mean)``.
HEADROOM_QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("residual_load_revision_mae_mw", "error_over_headroom",
     "NOTE C13-03 as asked: does a harder RES day make a harder day to capture?"),
    ("residual_load_revision_mae_mw", "price_mae_eur_mwh",
     "the numerator on its own: does an RES revision move the price error?"),
    ("residual_load_range_gw", "realised_spread_eur_mwh",
     "the denominator on its own: does the RES *shape* set the day's headroom?"),
)


def headroom_frame(zone: str, years: Sequence[int] = EXOG_YEARS) -> pd.DataFrame:
    """One row per market day: the day's fundamentals beside its dispatch outcome.

    The fundamentals come from this cycle's own pull; the dispatch outcome comes
    from **C13's committed per-day artefact** for the nine-zone comparable arm,
    so no walk-forward and no LP is re-run to answer NOTE C13-03 and the
    ``error_over_headroom`` here is arithmetically the one FINDING C13-D is
    about (``pooled MAE / mean realised daily spread``, taken per day).

    ``error_over_headroom`` here is the **per-day** ratio ``MAE_d / spread_d``,
    not that day's contribution to FINDING C13-D's pooled cell statistic. A
    ratio of means is not a mean of ratios, so the two are different numbers for
    the same name; the cell version is what :func:`headroom` writes to
    ``c14_headroom_cells.csv`` and the per-day version is the only one a per-day
    correlation can use. A day whose realised spread is not positive is NaN, not
    infinite, and is dropped from the correlation rather than winsorised.

    ``residual_load_revision_mae_mw`` is the day-over-day revision of the
    as-published Art. 14 residual load: the mean over the day's hours of
    ``|RL(h) - RL(h - 24h)|``. It is a **proxy** for residual-load forecast
    error and a conservative one — see :data:`RES_ERROR_IS_A_REVISION`. It is
    exactly the quantity C8's ``res_persistence`` arm has to live with, which is
    what makes it the relevant one: a bidder at gate closure holds yesterday's
    RES publication, so yesterday-to-today is the error they actually carry.
    """
    wanted = tuple(sorted(int(y) for y in years))
    assert_not_sealed(set(wanted), f"build the headroom frame for {zone}")
    bundle = fundamentals_frame(zone, wanted)
    hourly = bundle.frame.copy()
    hourly["rl_gw"] = hourly[RESIDUAL_LOAD_COLUMN] / 1000.0

    # The revision is computed on the *UTC* index with a 24-hour offset, not on
    # a local-day groupby: a 24-hour offset is 24 hours in every zone, while
    # "yesterday's same local hour" is 23 or 25 hours twice a year. The day
    # labels below are local, and only for grouping.
    series = hourly[RESIDUAL_LOAD_COLUMN]
    revision = (series - series.shift(freq="24h")).abs()
    hourly["revision_mw"] = revision.reindex(hourly.index)

    grouped = hourly.groupby("local_market_day")
    day = pd.DataFrame(
        {
            "n_fundamental_hours": grouped.size(),
            "residual_load_mean_gw": grouped["rl_gw"].mean(),
            "residual_load_min_gw": grouped["rl_gw"].min(),
            "residual_load_max_gw": grouped["rl_gw"].max(),
            "residual_load_range_gw": grouped["rl_gw"].max() - grouped["rl_gw"].min(),
            "residual_load_revision_mae_mw": grouped["revision_mw"].mean(),
            "n_revision_hours": grouped["revision_mw"].apply(lambda s: int(s.notna().sum())),
        }
    )

    dispatch = pd.read_csv(
        RESULTS_DIR / C13_DAILY, parse_dates=["market_day"]
    )
    dispatch = dispatch[(dispatch["zone"] == zone) & (dispatch["curve"] == COMPARABLE_CURVE)]
    if dispatch.empty:
        raise FundamentalsError(
            f"{zone}: {C13_DAILY} holds no {COMPARABLE_CURVE} rows — C13's artefact "
            f"is the only dispatch source this phase reads"
        )
    dispatch = dispatch.assign(
        market_day=[ts.date() for ts in dispatch["market_day"]]
    ).set_index("market_day")

    joined = day.join(
        dispatch[["sum_abs_error", "n_hours", "realised_spread", "cash", "oracle_cash",
                  "spearman", "spearman_defined"]],
        how="inner",
    )
    joined["price_mae_eur_mwh"] = joined["sum_abs_error"] / joined["n_hours"]
    joined["realised_spread_eur_mwh"] = joined["realised_spread"]
    with np.errstate(divide="ignore", invalid="ignore"):
        joined["error_over_headroom"] = np.where(
            joined["realised_spread_eur_mwh"].to_numpy() > 0,
            joined["price_mae_eur_mwh"].to_numpy()
            / joined["realised_spread_eur_mwh"].to_numpy(),
            np.nan,
        )
    joined["zone"] = zone
    joined["year"] = [d.year for d in joined.index]
    joined.index.name = "market_day"
    return joined


def headroom_correlations(frame: pd.DataFrame, zone: str, year: int | None) -> list[dict[str, Any]]:
    """Each of :data:`HEADROOM_QUESTIONS` as a Spearman with a block interval.

    ``year=None`` pools the years for one zone, and **the per-year rows are the
    headline, not the pooled one**. Pooling a rank correlation across years does
    not average the per-year correlations: if both columns shift level between
    years — and FINDING C13-A says they do — the pooled rank correlation picks up
    that between-year co-movement on top of the within-year relationship, which
    can make it larger than every per-year value or smaller than all of them. It
    is reported because a reader will want it, and labelled because it is the
    weaker number. NO2 is the live case: its pooled ``range -> spread`` row
    excludes zero while all three of its per-year rows contain it.
    """
    rows_in = frame if year is None else frame[frame["year"] == year]
    out: list[dict[str, Any]] = []
    for fundamental, outcome, question in HEADROOM_QUESTIONS:
        usable = rows_in.dropna(subset=[fundamental, outcome])
        if len(usable) < 30:
            out.append(
                {
                    "zone": zone,
                    "year": "pooled" if year is None else year,
                    "fundamental": fundamental,
                    "outcome": outcome,
                    "question": question,
                    "n_days": int(len(usable)),
                    "skipped": "fewer than 30 usable days",
                }
            )
            continue
        row: dict[str, Any] = {
            "zone": zone,
            "year": "pooled" if year is None else year,
            "fundamental": fundamental,
            "outcome": outcome,
            "question": question,
            "n_days": int(len(usable)),
            "fundamental_mean": round(float(usable[fundamental].mean()), 4),
            "outcome_mean": round(float(usable[outcome].mean()), 6),
        }
        for block in BLOCK_LADDER:
            if block >= len(usable):
                continue
            spec = _spec(len(usable), block)
            interval = spearman_interval(
                usable[fundamental].to_numpy(dtype=float),
                usable[outcome].to_numpy(dtype=float),
                spec,
            )
            prefix = "" if block == HEADLINE_BLOCK else f"block{block}_"
            row[f"{prefix}spearman"] = round(interval.point, 6)
            row[f"{prefix}ci_low"] = round(interval.ci_low, 6)
            row[f"{prefix}ci_high"] = round(interval.ci_high, 6)
            row[f"{prefix}excludes_zero"] = interval.excludes_zero
            row[f"{prefix}boot_sd"] = round(interval.boot_sd, 6)
        out.append(row)
    return out


def cross_cell_headroom(per_cell: pd.DataFrame) -> dict[str, Any]:
    """NOTE C13-03 at the (zone, year) level, the way FINDING C13-D was measured.

    FINDING C13-D is a **cross-cell** rank correlation: one number per (zone,
    year), nine zones x five years, 44 usable cells, ``error_over_headroom``
    against capture. The Tier-A exogenous window gives only 3 zones x 3 years =
    **9 cells**, so this is reported as a point estimate with no interval and the
    honest statement attached: nine cells cannot establish a cross-cell
    correlation. The per-day correlations above are where this cycle's power is.
    """
    usable = per_cell.dropna(subset=["residual_load_revision_mae_mw", "error_over_headroom"])
    out: dict[str, Any] = {
        "n_cells": int(len(usable)),
        "n_zones": int(usable["zone"].nunique()) if len(usable) else 0,
        "n_years": int(usable["year"].nunique()) if len(usable) else 0,
        "honest_label": (
            "nine (zone, year) cells. FINDING C13-D rests on 44. A cross-cell "
            "rank correlation on nine points has a sampling sd of roughly 0.38 "
            "under independence, so a cross-cell claim from this window is "
            "**not established**; the per-day columns are this cycle's evidence. "
            "Read the sign carefully: the cross-cell correlation of a RES "
            "predictor against error_over_headroom is NEGATIVE while every "
            "per-day within-cell one is POSITIVE, and that is not a scale "
            "artefact — it survives normalising by each cell's own mean residual "
            "load (*_over_mean). The two measure different things. BETWEEN "
            "cells, a zone-year with a larger relative RES swing has a wider "
            "price spread and so more headroom, which makes it easier. WITHIN a "
            "cell, a day whose RES publication was revised more than usual is "
            "harder. Use the *_over_mean columns for any cross-zone sentence "
            "anyway: the raw-MW ones are also size proxies (NO2's mean residual "
            "load is 3.6 GW against DE-LU's 30.0)."
        ),
    }
    if len(usable) >= 4:
        for fundamental in (
            "residual_load_revision_mae_mw",
            "residual_load_range_gw",
            "residual_load_mean_gw",
            "residual_load_range_over_mean",
            "residual_load_revision_over_mean",
        ):
            for outcome in ("error_over_headroom", "price_mae_eur_mwh",
                            "realised_spread_eur_mwh"):
                out[f"spearman_{fundamental}_vs_{outcome}"] = round(
                    float(usable[fundamental].corr(usable[outcome], method="spearman")), 6
                )
    return out


def headroom(args: argparse.Namespace) -> int:
    """Answer NOTE C13-03 and write the per-day artefact later cycles can reuse."""
    zones = selected_zones(args.zones)
    years = tuple(sorted(int(y) for y in args.years))
    assert_not_sealed(set(years), "answer NOTE C13-03 over")

    daily: list[pd.DataFrame] = []
    correlations: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for zone in zones:
        frame = headroom_frame(zone, years)
        daily.append(frame.reset_index())
        print(f"\n=== {zone} — {len(frame)} market days joined "
              f"({frame.index.min()} .. {frame.index.max()}) ===")
        for year in list(years) + [None]:
            rows = headroom_correlations(frame, zone, year)
            correlations.extend(rows)
            for row in rows:
                if "spearman" not in row:
                    print(f"  {row['year']:>6} {row['fundamental']:<34} "
                          f"{row['outcome']:<26} skipped: {row.get('skipped')}")
                    continue
                mark = "*" if row["excludes_zero"] else " "
                print(f"  {str(row['year']):>6} {row['fundamental']:<34} "
                      f"{row['outcome']:<26} rho {row['spearman']:+.3f} "
                      f"[{row['ci_low']:+.3f}, {row['ci_high']:+.3f}]{mark} "
                      f"n={row['n_days']}")
        for year in years:
            block = frame[frame["year"] == year]
            if block.empty:
                continue
            cells.append(
                {
                    "zone": zone,
                    "year": year,
                    "n_days": int(len(block)),
                    "residual_load_revision_mae_mw": float(
                        block["residual_load_revision_mae_mw"].mean()
                    ),
                    "residual_load_range_gw": float(block["residual_load_range_gw"].mean()),
                    "residual_load_mean_gw": float(block["residual_load_mean_gw"].mean()),
                    # Both of the above are in MW/GW and so are *not* comparable
                    # across a 4 GW and a 54 GW zone — the same scale artefact
                    # §7 of docs/fundamentals.md reports for the supply-curve
                    # slopes. These two normalise by the zone-year's own mean
                    # residual load, and they are the figures a cross-zone
                    # sentence may use.
                    "residual_load_range_over_mean": float(
                        block["residual_load_range_gw"].mean()
                        / block["residual_load_mean_gw"].mean()
                    ),
                    "residual_load_revision_over_mean": float(
                        block["residual_load_revision_mae_mw"].mean()
                        / (1000.0 * block["residual_load_mean_gw"].mean())
                    ),
                    "price_mae_eur_mwh": float(
                        block["sum_abs_error"].sum() / block["n_hours"].sum()
                    ),
                    "realised_spread_eur_mwh": float(block["realised_spread_eur_mwh"].mean()),
                    # The cell-level ratio FINDING C13-D defines: pooled MAE over
                    # the mean realised daily spread, not the mean of the per-day
                    # ratios (which is a different and noisier statistic).
                    "error_over_headroom": float(
                        (block["sum_abs_error"].sum() / block["n_hours"].sum())
                        / block["realised_spread_eur_mwh"].mean()
                    ),
                    "capture_rolled_oracle_cash": float(
                        block["cash"].sum() / block["oracle_cash"].sum()
                    ),
                }
            )

    daily_frame = pd.concat(daily, ignore_index=True)
    cell_frame = pd.DataFrame(cells)
    correlation_frame = pd.DataFrame(correlations)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    daily_path = RESULTS_DIR / "c14_headroom_daily.csv.gz"
    daily_frame.to_csv(daily_path, index=False, float_format="%.6f")
    cell_path = RESULTS_DIR / "c14_headroom_cells.csv"
    cell_frame.to_csv(cell_path, index=False, float_format="%.6f")
    correlation_path = RESULTS_DIR / "c14_headroom_correlations.csv"
    correlation_frame.to_csv(correlation_path, index=False)

    summary = {
        "cycle": "C14",
        "question": "NOTE C13-03 — does residual-load forecast error explain error_over_headroom?",
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "vintage": FUNDAMENTALS_VINTAGE,
        "residual_load_error_caveat": RES_ERROR_IS_A_REVISION,
        "zones": list(zones),
        "years": list(years),
        "bootstrap": _spec(365, HEADLINE_BLOCK).as_dict(),
        "block_ladder": list(BLOCK_LADDER),
        "dispatch_source": C13_DAILY,
        "dispatch_curve": COMPARABLE_CURVE,
        "n_days": int(len(daily_frame)),
        "cross_cell": cross_cell_headroom(cell_frame),
        "cells": cell_frame.to_dict("records"),
        "correlations": correlations,
    }
    figures: list[str] = []
    if not args.no_figures:
        figures.append(str(plot_headroom(daily_frame).relative_to(REPO_ROOT)))
    summary["figures"] = figures
    summary_path = RESULTS_DIR / "c14_headroom_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    for path in (daily_path, cell_path, correlation_path, summary_path):
        print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size / 1024:.0f} KiB)")
    for figure in figures:
        print(f"wrote {figure}")
    return 0


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
GRID = "#d8d7d2"
NEGATIVE = "#e34948"
#: One colour per year, dark to light, so a reader can see the 2022 level shift
#: without reading the legend.
YEAR_COLOURS = {2022: "#1b3f73", 2023: "#2a78d6", 2024: "#7fb3ea"}

ATTRIBUTION = (
    "Prices: Energy-Charts (Fraunhofer ISE), CC BY 4.0 — "
    "Residual load: ENTSO-E Transparency Platform D-1 forecast (Art. 6 + Art. 14)"
)


def _figure_style() -> None:
    import matplotlib

    matplotlib.use("Agg")  # headless container
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
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 9,
            "figure.dpi": 130,
        }
    )


def plot_merit_order(
    bundles: dict[str, FundamentalsFrame],
    tables: dict[tuple[str, int], pd.DataFrame],
    years: Sequence[int],
) -> Any:
    """One panel per zone: the empirical supply curve, one line per year.

    The hourly cloud is drawn once per zone at low alpha (all years together, so
    the panel shows the range the curves are summarising) and the decile medians
    are drawn on top, one line per year. The y axis is symlog because the same
    panel has to show -500 and +700 EUR/MWh without the negative tail swallowing
    the part of the curve the chapter is about.
    """
    _figure_style()
    import matplotlib.pyplot as plt

    zones = list(bundles)
    # `sharey` because the chapter compares price *levels* across the three
    # zones (FINDING C14-C's x2.6-2.7 crisis shift); three independent price
    # axes would make a 143 EUR/MWh line and a 316 EUR/MWh line look alike. The
    # x axes stay independent — NO2's residual load spans 2-6 GW and DE-LU's
    # spans -13 to 69, and forcing those to share would reduce NO2 to a smear.
    fig, axes = plt.subplots(
        1, len(zones), figsize=(4.2 * len(zones), 4.4), sharey=True,
        constrained_layout=True,
    )
    axes = np.atleast_1d(axes)
    for ax, zone in zip(axes, zones):
        hourly = bundles[zone].frame
        ax.scatter(
            hourly[RESIDUAL_LOAD_COLUMN] / 1000.0,
            hourly[PRICE_COLUMN],
            s=1.0,
            alpha=0.06,
            color=INK_SOFT,
            linewidths=0,
            rasterized=True,
        )
        ax.axhline(0.0, color=NEGATIVE, linewidth=0.8, zorder=2)
        for year in years:
            table = tables.get((zone, year))
            if table is None:
                continue
            ax.plot(
                table["rl_gw_median"],
                table["price_median"],
                marker="o",
                markersize=3.2,
                linewidth=1.6,
                color=YEAR_COLOURS.get(year, INK),
                label=str(year),
                zorder=3,
            )
        ax.set_yscale("symlog", linthresh=50)
        # Clipped to roughly the 0.1st-99.9th percentile of the pooled Tier-A
        # price. The full range runs to -500 (DE-LU) and +936, and letting it
        # set the axis spends two thirds of the panel on a handful of hours
        # while compressing every decile curve into a band. The clipped hours
        # are counted in §6 of docs/fundamentals.md, not hidden.
        ax.set_ylim(-150, 1000)
        ax.set_title(f"{zone}", color=INK)
        ax.set_xlabel("D-1 forecast residual load (GW)")
    axes[0].set_ylabel("day-ahead price (EUR/MWh, symlog)")
    # One legend: the three panels share it, and repeating it three times cost
    # NO2 the corner of its panel the 2022 curve sits in.
    axes[0].legend(frameon=False, title="decile medians", fontsize=8, title_fontsize=8)
    fig.suptitle(
        "The empirical supply curve: price against residual load, Tier A",
        color=INK,
        fontsize=11,
    )
    fig.text(0.5, -0.02, ATTRIBUTION, ha="center", color=INK_SOFT, fontsize=7)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / "c14_merit_order_tier_a.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_negative_price_probability(
    tables: dict[tuple[str, int], pd.DataFrame], years: Sequence[int]
) -> Any:
    """P(price < 0) by residual-load decile — the turn-down cliff, per zone."""
    _figure_style()
    import matplotlib.pyplot as plt

    zones = sorted({zone for zone, _ in tables})
    fig, axes = plt.subplots(
        1, len(zones), figsize=(4.2 * len(zones), 3.4), sharey=True,
        constrained_layout=True,
    )
    axes = np.atleast_1d(axes)
    for ax, zone in zip(axes, zones):
        for year in years:
            table = tables.get((zone, year))
            if table is None:
                continue
            ax.plot(
                table["bin"] + 1,
                table["share_negative"],
                marker="o",
                markersize=3.2,
                linewidth=1.6,
                color=YEAR_COLOURS.get(year, INK),
                label=str(year),
            )
        ax.axhline(
            1.0 / N_RESIDUAL_LOAD_BINS * 0,  # the zero line, not the uniform share
            color=GRID, linewidth=0.8,
        )
        ax.set_title(zone, color=INK)
        ax.set_xlabel("residual-load decile (1 = lowest)")
        ax.set_xticks(range(1, N_RESIDUAL_LOAD_BINS + 1))
        ax.legend(frameon=False, fontsize=8)
    axes[0].set_ylabel("P(price < 0)")
    fig.suptitle(
        "Negative prices are a bottom-decile phenomenon — except where they are not",
        color=INK, fontsize=11,
    )
    fig.text(0.5, -0.04, ATTRIBUTION, ha="center", color=INK_SOFT, fontsize=7)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / "c14_negative_price_by_decile.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _binned_median(x: np.ndarray, y: np.ndarray, n_bins: int = 10):
    """Median ``y`` in deciles of ``x`` — the trend line a dense cloud hides.

    A scatter of 1 090 days is a blob; the eye cannot read a rank correlation of
    +0.5 off one. The binned median is the same statistic the merit-order figure
    draws and it makes the reported number visible rather than asking the reader
    to take it on trust.
    """
    usable = np.isfinite(x) & np.isfinite(y)
    x, y = x[usable], y[usable]
    if len(x) < n_bins * 5:
        return np.array([]), np.array([])
    bins = pd.qcut(x, n_bins, labels=False, duplicates="drop")
    frame = pd.DataFrame({"x": x, "y": y, "b": bins}).groupby("b")
    return frame["x"].median().to_numpy(), frame["y"].median().to_numpy()


def plot_headroom(daily: pd.DataFrame) -> Any:
    """NOTE C13-03, two rows: the numerator's driver and the denominator's.

    The top row is the question as NOTE C13-03 asked it — the day's RES revision
    against the day's error-over-headroom. The bottom row is the one that
    carries FINDING C14-F: the day's residual-load **range** against the day's
    realised price **spread**, which is strongly positive in DE-LU and ES and
    flat at zero in NO2. Putting them in one figure is the point, because the
    contrast between the two rows in the NO2 column *is* the mechanism.

    A binned-median line is drawn over each cloud. Without it the panels are
    1 090-point blobs and the reported correlations are invisible.
    """
    _figure_style()
    import matplotlib.pyplot as plt

    zones = sorted(daily["zone"].unique())
    rows = (
        ("residual_load_revision_mae_mw", "error_over_headroom", 1e-3,
         "residual-load D-1 revision, daily MAE (GW)",
         "error / headroom\n(price MAE ÷ realised spread)", True),
        ("residual_load_range_gw", "realised_spread_eur_mwh", 1.0,
         "residual-load daily range (GW)",
         "realised price spread\n(EUR/MWh)", False),
    )
    fig, axes = plt.subplots(
        len(rows), len(zones), figsize=(4.0 * len(zones), 3.3 * len(rows)),
        constrained_layout=True,
    )
    axes = np.atleast_2d(axes)
    for r, (xcol, ycol, xscale, xlabel, ylabel, logy) in enumerate(rows):
        for c, zone in enumerate(zones):
            ax = axes[r, c]
            block = daily[daily["zone"] == zone]
            for year in sorted(block["year"].unique()):
                piece = block[block["year"] == year].dropna(subset=[xcol, ycol])
                ax.scatter(
                    piece[xcol] * xscale, piece[ycol],
                    s=5, alpha=0.40, linewidths=0,
                    color=YEAR_COLOURS.get(int(year), INK),
                    label=str(int(year)) if r == 0 and c == 0 else None,
                )
            usable = block.dropna(subset=[xcol, ycol])
            bx, by = _binned_median(
                usable[xcol].to_numpy(dtype=float) * xscale,
                usable[ycol].to_numpy(dtype=float),
            )
            if len(bx):
                ax.plot(bx, by, color=NEGATIVE, linewidth=1.8, marker="o",
                        markersize=3.4, zorder=5,
                        label="decile median" if r == 0 and c == 0 else None)
            if logy:
                ax.set_yscale("log")
            ax.set_xlabel(xlabel)
            if r == 0:
                ax.set_title(zone, color=INK)
            if c == 0:
                ax.set_ylabel(ylabel)
    axes[0, 0].legend(frameon=False, fontsize=8, markerscale=2.2)
    fig.suptitle(
        "NOTE C13-03: a harder RES day is a harder day (top) — but in NO2 the "
        "RES swing does not set the spread at all (bottom)",
        color=INK, fontsize=11,
    )
    fig.text(0.5, -0.02, ATTRIBUTION, ha="center", color=INK_SOFT, fontsize=7)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / "c14_headroom_vs_res_revision.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Phase `fundamentals` driver
# ---------------------------------------------------------------------------


def fundamentals(args: argparse.Namespace) -> int:
    zones = selected_zones(args.zones)
    years = tuple(sorted(int(y) for y in args.years))
    assert_not_sealed(set(years), "describe the fundamentals of")

    bundles: dict[str, FundamentalsFrame] = {}
    tables: dict[tuple[str, int], pd.DataFrame] = {}
    power: list[dict[str, Any]] = []
    shapes: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    sufficiency: list[dict[str, Any]] = []
    level_shape: list[dict[str, Any]] = []

    for zone in zones:
        bundle = fundamentals_frame(zone, years)
        bundles[zone] = bundle
        print(f"\n=== {zone} — {bundle.n_joined_hours} hours with a price and a "
              f"complete residual-load forecast, {bundle.n_dropped_missing_residual_load} "
              f"dropped incomplete, years {list(bundle.years)} ===")
        per_year: dict[int, pd.DataFrame] = {}
        for year in bundle.years:
            table = merit_order_table(bundle.frame, zone, year)
            tables[(zone, year)] = table
            per_year[year] = table
            shape = convexity(table)
            shapes.append(shape)
            metrics = explanatory_power(bundle.frame, zone, year)
            power.append(metrics)
            negatives.append(negative_price_concentration(bundle.frame, zone, year, table))
            sufficiency.append(residual_load_sufficiency(bundle.frame, zone, year))
            print(f"  {year}: r2_piecewise {metrics['r2_piecewise_linear_20']:.3f} "
                  f"(linear {metrics['r2_linear']:.3f}, step {metrics['r2_binned_20']:.3f}, "
                  f"calendar-only {metrics['r2_calendar_only']:.3f}, "
                  f"gain over calendar {metrics['gain_over_calendar']:+.3f}), "
                  f"spearman {metrics['spearman_price_residual_load']:+.3f}; "
                  f"slopes low/mid/high "
                  f"{shape['slope_low_eur_mwh_per_gw']:.2f} / "
                  f"{shape['slope_mid_eur_mwh_per_gw']:.2f} / "
                  f"{shape['slope_high_eur_mwh_per_gw']:.2f} EUR/MWh/GW, "
                  f"convex_at_the_top={shape['convex_at_the_top']}")
        level_shape.append(level_versus_shape(per_year, zone))

    merit_frame = pd.concat(list(tables.values()), ignore_index=True)
    power_frame = pd.DataFrame(power)
    shape_frame = pd.DataFrame(shapes)
    negative_frame = pd.DataFrame(negatives)
    sufficiency_frame = pd.DataFrame(sufficiency)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for frame, name in (
        (merit_frame, "c14_merit_order_deciles.csv"),
        (power_frame, "c14_explanatory_power.csv"),
        (shape_frame, "c14_supply_curve_slopes.csv"),
        (negative_frame, "c14_negative_price_mechanism.csv"),
        (sufficiency_frame, "c14_residual_load_sufficiency.csv"),
    ):
        path = RESULTS_DIR / name
        frame.to_csv(path, index=False, float_format="%.6f")
        paths.append(path)

    figures: list[str] = []
    if not args.no_figures:
        figures.append(str(plot_merit_order(bundles, tables, years).relative_to(REPO_ROOT)))
        figures.append(
            str(plot_negative_price_probability(tables, years).relative_to(REPO_ROOT))
        )

    summary = {
        "cycle": "C14",
        "scope": "PLAN.md C14 — price vs residual load (load - wind - solar), Tier A",
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "vintage": FUNDAMENTALS_VINTAGE,
        "vintage_note": (
            "Residual load here is the ENTSO-E D-1 *forecast* (Art. 6 load + Art. 14 "
            "wind/solar). The Art. 14 part is published 18:00 local on D-1, six hours "
            "after gate closure, so it is the closest thing in PLAN.md's scope to "
            "realised residual load and is used descriptively only. No model in this "
            "project is fitted or scored on this frame; assert_descriptive_only() "
            "refuses it."
        ),
        "zones": {zone: bundle.as_dict() for zone, bundle in bundles.items()},
        "years": list(years),
        "n_residual_load_bins": N_RESIDUAL_LOAD_BINS,
        "explanatory_power": power,
        "supply_curve_slopes": shapes,
        "negative_price_mechanism": negatives,
        "residual_load_sufficiency": sufficiency,
        "level_versus_shape": level_shape,
        "figures": figures,
    }
    summary_path = RESULTS_DIR / "c14_fundamentals_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    paths.append(summary_path)
    for path in paths:
        print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size / 1024:.0f} KiB)")
    for figure in figures:
        print(f"wrote {figure}")
    return 0


# ---------------------------------------------------------------------------
# Phases `ladder-*`: NOTE C13-04 / NOTE C8-01, the second evaluation year
# ---------------------------------------------------------------------------

#: The 2023 arms, named exactly as C11 named their 2024 counterparts so a
#: capture ratio joins on ``(model, exog_variant, vintage, train_from)`` across
#: the two years. The artefact names carry 2023 instead of 2024, which is the
#: only difference and the reason this cannot simply call C11's ``arms_for``.
def ladder_arms(zone: str) -> list[Arm]:
    c8 = f"c8_exog_{zone}_{LADDER_YEAR}_predictions.csv.gz"
    c9 = f"c9_gbm_{zone}_{LADDER_YEAR}_predictions.csv.gz"
    return [
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


#: The contrasts NOTE C8-01 and FINDING C12-E are about. A subset of C11's
#: :data:`CONTRASTS`, restricted to the ones a second year can actually settle.
LADDER_CONTRASTS: tuple[tuple[str, str, str], ...] = (
    ("gbm_res_persistence", "gbm_price_only",
     "NOTE C8-01 as re-opened by C12: is the honest exogenous block worth "
     "having under the booster, outside ES?"),
    ("lear_res_persistence", "lear_price_only",
     "the same question under the LASSO, which C11 found ~0 in 2024"),
    ("gbm_price_only", "lear_price_only",
     "FINDING C12-E's one established contrast, re-measured in a second year"),
    ("gbm_res_as_published", "gbm_res_persistence",
     "FINDING C9-C's vintage premium in capture terms — NOT achievable (GBM)"),
    ("lear_res_as_published", "lear_res_persistence",
     "the same leak under the LASSO — NOT achievable"),
)


def ladder_predictions_frame(
    zone: str, arms: list[Arm], realised: pd.Series
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """The 2023 C8/C9 artefacts, joined and checked against the realised series.

    The same provenance discipline C11 and C13 use: every artefact's own
    ``y_true`` must equal the freshly re-pulled realised price hour for hour, and
    the two artefacts must cover the *same* index. A reindex here would hide
    exactly the off-by-one that reads as skill.
    """
    frames: dict[str, pd.DataFrame] = {}
    for artefact in sorted({arm.artefact for arm in arms}):
        path = RESULTS_DIR / artefact
        if not path.exists():
            raise FundamentalsError(
                f"{zone}: {artefact} is missing — run the ladder-compute phase "
                f"(`python -m backtest.run_c8_exogenous --years {LADDER_YEAR}` then "
                f"`python -m backtest.run_c9_gbm --years {LADDER_YEAR}`) first"
            )
        frame = pd.read_csv(path, index_col=0, parse_dates=[0])
        frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
        frames[artefact] = frame.sort_index()

    indexes = list(frames.values())
    reference = indexes[0].index
    for artefact, frame in frames.items():
        if not frame.index.equals(reference):
            raise FundamentalsError(
                f"{zone}: {artefact} is indexed on {len(frame)} hours "
                f"({frame.index[0]}..{frame.index[-1]}), the first artefact on "
                f"{len(reference)} ({reference[0]}..{reference[-1]}). The two "
                f"cycles did not evaluate the same hours; refusing to compare them."
            )
    aligned = realised.reindex(reference)
    if aligned.isna().any():
        raise FundamentalsError(
            f"{zone}: {int(aligned.isna().sum())} forecast timestamp(s) have no "
            f"realised price — the artefacts and the price cache disagree on the grid"
        )
    worst = 0.0
    for artefact, frame in frames.items():
        gap = float(
            np.nanmax(np.abs(frame["y_true"].to_numpy(dtype=float)
                             - aligned.to_numpy(dtype=float)))
        )
        worst = max(worst, gap)
        # C8/C9 wrote y_true with %.4f, so the artefact's own precision is the
        # only tolerance allowed; anything larger means the cache changed.
        if gap > 5e-4:
            raise FundamentalsError(
                f"{zone}: {artefact}'s y_true differs from the re-pulled realised "
                f"price by up to {gap} EUR/MWh — a provenance problem, not rounding"
            )

    combined = pd.DataFrame({"y_true": aligned}, index=reference)
    for arm in arms:
        frame = frames[arm.artefact]
        if arm.column not in frame.columns:
            raise FundamentalsError(
                f"{zone}: {arm.artefact} has no {arm.column!r} column "
                f"(have {sorted(frame.columns)})"
            )
        combined[arm.curve] = frame[arm.column].astype(float)
    provenance = {
        "artefacts": sorted(frames),
        "n_rows": int(len(combined)),
        "first_ts_utc": reference[0].isoformat(),
        "last_ts_utc": reference[-1].isoformat(),
        "worst_y_true_vs_repulled_price_eur_mwh": round(worst, 8),
    }
    return combined, provenance


def ladder_dispatch_zone(zone: str) -> tuple[dict[str, Any], pd.DataFrame]:
    """Every 2023 ladder arm plus the oracle, through C5/C6's rolling LP.

    C11's ``pooled_capture``, ``same_start_oracle`` and the CLAUDE.md invariant
    checks are *imported*, not re-derived, which is what makes a 2023 capture
    ratio the same statistic as the 2024 one already in ``results.csv``.
    """
    assert_not_sealed(LADDER_YEAR, f"dispatch the C14 ladder for {zone}")
    cfg = load_battery_config()
    spec = BatterySpec.from_config(cfg)
    tz = zone_timezone(zone)
    terminal = cfg.get("terminal") or {}
    roll_kwargs = dict(
        trailing_days=int(terminal.get("trailing_days", 7)),
        trailing_quantile=float(terminal.get("trailing_quantile", 0.5)),
        min_trailing_days=int(terminal.get("min_trailing_days", 1)),
        tz=tz,
    )
    arms = ladder_arms(zone)
    realised = load_realised(zone, [LADDER_YEAR])
    frame, provenance = ladder_predictions_frame(zone, arms, realised)

    curves = {
        arm.curve: Curve(
            name=arm.curve,
            prices=frame[arm.curve].astype(float),
            source=f"{arm.artefact}:{arm.column}",
        )
        for arm in arms
    }
    forecast_days: set[dt.date] = set()
    for curve in curves.values():
        forecast_days |= set(market_days(pd.DatetimeIndex(curve.prices.index), tz).tolist())
    labels = pd.Series(realised.index).dt.tz_convert(tz).dt.date
    wanted = {d for d in labels if d.year == LADDER_YEAR} & forecast_days
    if not wanted:
        raise FundamentalsError(f"{zone}: no market day is both in {LADDER_YEAR} and forecast")

    print(f"\n=== {zone} {LADDER_YEAR} — {len(curves)} forecast curve(s) + oracle "
          f"over {len(wanted)} market days {min(wanted)} .. {max(wanted)} ===", flush=True)

    results: dict[str, RollingResult] = {
        ORACLE_CURVE: run_rolling_dispatch(
            zone, realised, spec, decision_prices=None, curve=ORACLE_CURVE,
            days=wanted, **roll_kwargs
        )
    }
    for arm in arms:
        results[arm.curve] = run_rolling_dispatch(
            zone, realised, spec, decision_prices=curves[arm.curve].prices,
            curve=arm.curve, days=wanted, **roll_kwargs
        )
    bounds = {name: same_start_oracle(res, spec) for name, res in results.items()}
    shared = common_days(results)
    own = {name: set(res.days) for name, res in results.items()}

    pooled = {
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

    invariants: dict[str, dict[str, Any]] = {}
    for name, res in results.items():
        block: dict[str, Any] = {
            "day_lengths_match_local_calendar": check_day_lengths(res, zone),
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
                if name == "naive"
                else beats_naive(res, results["naive"], shared)
            )
            arm_cash = pooled[name]["common_hours"]["cash_eur"]
            oracle_cash = pooled[ORACLE_CURVE]["common_hours"]["cash_eur"]
            block["oracle_dominates_pooled_common_days"] = {
                "holds": bool(oracle_cash >= arm_cash - 1e-6),
                "oracle_cash_eur": round(oracle_cash, 4),
                "arm_cash_eur": round(arm_cash, 4),
                "margin_eur": round(oracle_cash - arm_cash, 4),
            }
        block["simultaneous_charge_and_discharge"] = simultaneity_flag(res, spec)
        invariants[name] = block

    daily = pd.concat(
        [
            capture_frame(res, results[ORACLE_CURVE], bounds[name]).assign(
                in_common_day_set=lambda f: [
                    dt.date.fromisoformat(d) in shared for d in f["market_day"]
                ]
            )
            for name, res in results.items()
        ],
        ignore_index=True,
    )
    daily["year"] = LADDER_YEAR
    summary = {
        "zone": zone,
        "year": LADDER_YEAR,
        "n_market_days_dispatched": len(wanted),
        "n_common_days": len(shared),
        "battery": spec.as_dict() if hasattr(spec, "as_dict") else str(spec),
        "provenance": provenance,
        "arms": [
            {
                "curve": arm.curve, "model": arm.model, "exog_variant": arm.exog_variant,
                "vintage": arm.vintage, "train_from": arm.train_from,
                "artefact": arm.artefact, "column": arm.column,
                "model_fingerprint": arm.model_fingerprint,
                "mae_on_dispatched_days": mae_on_days(
                    curves[arm.curve], realised, shared, tz
                ),
            }
            for arm in arms
        ],
        "pooled": pooled,
        "invariants": invariants,
        "realised_losses": {
            name: report_realised_losses(res) for name, res in results.items()
        },
    }
    return summary, daily


#: C8 writes this column only when its full-history reference arm runs. C13
#: computed the *same* forecast for 2023 — C4's committed LEAR on price and
#: calendar features, expanding window from 2019 — from a different runner, in a
#: different container, off a different re-pull of the price cache. So where both
#: exist they are an end-to-end reproducibility check, and it is free.
C8_FULL_HISTORY_COLUMN = "y_pred_price_only_full_history"
C13_COMPARABLE_COLUMN = "y_pred_lear_price_only"


def cross_check_full_history_against_c13(zone: str) -> dict[str, Any]:
    """Does C8's full-history arm reproduce C13's comparable arm for 2023?

    This is the reproducibility check PLAN.md schedules for C20, obtained as a
    by-product: two runners, two containers, two independent re-pulls of the
    Energy-Charts cache, one configuration. A disagreement would mean one of the
    two cycles' committed forecasts is not what its code produces today, which
    is a provenance failure and not a tolerance question — so the comparison is
    exact to the artefacts' own ``%.4f`` precision and nothing wider.

    Returns a ``skipped`` report rather than raising when either artefact is
    absent: C8's column only exists for the zones whose full-history reference
    arm was run, and the check is a bonus, not a precondition.
    """
    c8_path = RESULTS_DIR / f"c8_exog_{zone}_{LADDER_YEAR}_predictions.csv.gz"
    c13_path = RESULTS_DIR / f"c13_year_{zone}_{LADDER_YEAR}_predictions.csv.gz"
    if not c8_path.exists() or not c13_path.exists():
        return {"zone": zone, "skipped": "one of the two artefacts is absent"}
    c8 = pd.read_csv(c8_path, index_col=0, parse_dates=[0])
    if C8_FULL_HISTORY_COLUMN not in c8.columns:
        return {
            "zone": zone,
            "skipped": (
                f"{c8_path.name} has no {C8_FULL_HISTORY_COLUMN} column — its "
                f"full-history reference arm was not run for this zone"
            ),
        }
    c13 = pd.read_csv(c13_path, index_col=0, parse_dates=[0])
    joined = pd.concat(
        [c8[C8_FULL_HISTORY_COLUMN], c13[C13_COMPARABLE_COLUMN]], axis=1, join="inner"
    ).dropna()
    if joined.empty:
        raise FundamentalsError(
            f"{zone}: C8's and C13's {LADDER_YEAR} artefacts share no hour with a "
            f"prediction in both — they cannot be the same configuration"
        )
    worst = float((joined.iloc[:, 0] - joined.iloc[:, 1]).abs().max())
    return {
        "zone": zone,
        "year": LADDER_YEAR,
        "n_hours_compared": int(len(joined)),
        "worst_abs_difference_eur_mwh": worst,
        "holds": bool(worst <= 5e-4),
        "c8_artefact": c8_path.name,
        "c13_artefact": c13_path.name,
        "note": (
            "Two runners (run_c8_exogenous here, run_c13_regime in C13), two "
            "containers, two independent Energy-Charts re-pulls, one committed "
            "LearSpec. The tolerance is the artefacts' own %.4f precision."
        ),
    }


def ladder_daily_path(zone: str):
    return RESULTS_DIR / f"c14_ladder_{zone}_{LADDER_YEAR}_daily.csv.gz"


def ladder_summary_path(zone: str):
    return RESULTS_DIR / f"c14_ladder_{zone}_{LADDER_YEAR}_summary.json"


def ladder_compute(args: argparse.Namespace) -> int:
    """Say what must be run, and refuse to pretend it has been.

    The two fits this phase needs are C8's and C9's own runners, unchanged, with
    ``--years 2023``. They are **not** wrapped or re-implemented here: a second
    evaluation year is only comparable to the first if it came out of the same
    code, and a copy of that code in this module is the one way to lose that
    guarantee silently.
    """
    zones = selected_zones(args.zones)
    missing: list[str] = []
    for zone in zones:
        for artefact in sorted({arm.artefact for arm in ladder_arms(zone)}):
            if not (RESULTS_DIR / artefact).exists():
                missing.append(artefact)
    print(f"ladder year: {LADDER_YEAR}; zones: {zones}")
    if not missing:
        print("every C8/C9 artefact for the ladder year is present")
        return 0
    print(f"{len(missing)} artefact(s) missing:")
    for artefact in missing:
        print(f"  {artefact}")
    print("\nRun, in this order (both are the committed C8/C9 runners, unmodified):")
    print(f"  python -m backtest.run_c8_exogenous --years {LADDER_YEAR}")
    print(f"  python -m backtest.run_c9_gbm --years {LADDER_YEAR}")
    return 3


def ladder_dispatch(args: argparse.Namespace) -> int:
    zones = selected_zones(args.zones)
    flags: dict[str, Any] = {}
    failures = 0
    for zone in zones:
        summary, daily = ladder_dispatch_zone(zone)
        daily.to_csv(ladder_daily_path(zone), index=False, float_format="%.6f")
        with ladder_summary_path(zone).open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
            fh.write("\n")
        # The CLAUDE.md invariants, recorded rather than swallowed and rather
        # than aborting the zones that do not depend on this one (C13's
        # precedent for FLAG C13-01).
        for curve, block in summary["invariants"].items():
            for check, result in block.items():
                if not isinstance(result, dict):
                    continue
                if result.get("applicable") is False:
                    continue
                if result.get("holds") is False:
                    failures += 1
                    flags.setdefault(zone, []).append(
                        {"curve": curve, "check": check, "detail": result}
                    )
        print(f"  wrote {ladder_daily_path(zone).name} and {ladder_summary_path(zone).name}")
    path = RESULTS_DIR / "c14_ladder_invariant_flags.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "cycle": "C14",
                "year": LADDER_YEAR,
                "n_failures": failures,
                "flags": flags,
                "note": (
                    "A failure here is recorded and the remaining zones still run "
                    "(C13's precedent); the process exits non-zero so a cycle "
                    "cannot mistake a flagged run for a clean one."
                ),
            },
            fh, indent=2, default=str,
        )
        fh.write("\n")
    print(f"wrote {path.relative_to(REPO_ROOT)} — {failures} invariant failure(s)")
    return 1 if failures else 0


def ladder_contrast_intervals(zone: str) -> list[dict[str, Any]]:
    """Each :data:`LADDER_CONTRASTS` pair as a paired capture delta with intervals.

    The denominator is **FINDING C11-C's**: the rolled perfect-foresight run's
    cash on the same days, one denominator per zone, so the ratio is comparable
    across curves. ``capture_same_start`` is deliberately not used to rank two
    curves — FINDING C11-C shows it scores a curve arriving with a fuller
    battery against an easier ceiling.
    """
    daily = pd.read_csv(ladder_daily_path(zone))
    common = daily[daily["in_common_day_set"].astype(bool)]
    days = sorted(common[common["curve"] == ORACLE_CURVE]["market_day"].unique())
    if len(days) < 30:
        raise FundamentalsError(f"{zone}: only {len(days)} common days in the ladder year")

    def _column(curve: str, column: str) -> np.ndarray:
        block = common[common["curve"] == curve].set_index("market_day")
        if not set(days) <= set(block.index):
            raise FundamentalsError(f"{zone}: {curve} is missing days in the common set")
        return block.loc[days, column].to_numpy(dtype=float)

    oracle_cash = _column(ORACLE_CURVE, "cash_eur")
    spec = None
    rows: list[dict[str, Any]] = []
    for treatment, baseline, question in LADDER_CONTRASTS:
        point_t = float(_column(treatment, "cash_eur").sum() / oracle_cash.sum())
        point_b = float(_column(baseline, "cash_eur").sum() / oracle_cash.sum())
        row: dict[str, Any] = {
            "zone": zone,
            "year": LADDER_YEAR,
            "treatment": treatment,
            "baseline": baseline,
            "question": question,
            "n_days": len(days),
            "capture_treatment": round(point_t, 6),
            "capture_baseline": round(point_b, 6),
            "delta_pp": round(100.0 * (point_t - point_b), 4),
        }
        for block in BLOCK_LADDER:
            spec = _spec(len(days), block)
            counts = replicate_counts(spec)
            num_t = counts @ _column(treatment, "cash_eur")
            num_b = counts @ _column(baseline, "cash_eur")
            den = counts @ oracle_cash
            replicates = 100.0 * (num_t - num_b) / den
            interval = _interval(100.0 * (point_t - point_b), replicates, spec)
            prefix = "" if block == HEADLINE_BLOCK else f"block{block}_"
            row[f"{prefix}ci_low_pp"] = round(interval.ci_low, 4)
            row[f"{prefix}ci_high_pp"] = round(interval.ci_high, 4)
            row[f"{prefix}excludes_zero"] = interval.excludes_zero
            row[f"{prefix}boot_sd_pp"] = round(interval.boot_sd, 4)
            row[f"{prefix}prob_le_zero"] = round(interval.prob_le_zero, 6)
        rows.append(row)
    return rows


def ladder_analyse(args: argparse.Namespace) -> int:
    """The 2023 column of NOTE C8-01's table, beside C11/C12's 2024 column."""
    zones = selected_zones(args.zones)
    contrasts: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    for zone in zones:
        contrasts.extend(ladder_contrast_intervals(zone))
        summary = json.loads(ladder_summary_path(zone).read_text(encoding="utf-8"))
        for curve, scopes in summary["pooled"].items():
            block = scopes["common_hours"]
            arm = next((a for a in summary["arms"] if a["curve"] == curve), None)
            captures.append(
                {
                    "zone": zone,
                    "year": LADDER_YEAR,
                    "curve": curve,
                    "model": (arm or {}).get("model", ORACLE_MODEL),
                    "exog_variant": (arm or {}).get("exog_variant", ORACLE_VARIANT),
                    "vintage": (arm or {}).get("vintage", "honest"),
                    "train_from": (arm or {}).get("train_from", ""),
                    "n_days": block.get("n_days"),
                    "cash_eur": block.get("cash_eur"),
                    "capture_rolled_oracle_cash": block.get("capture_rolled_oracle_cash"),
                    "eur_per_mw_year_lost_vs_oracle": block.get(
                        "eur_per_mw_year_lost_vs_oracle"
                    ),
                    "mae_on_dispatched_days": (
                        ((arm or {}).get("mae_on_dispatched_days") or {}).get("mae")
                    ),
                }
            )

    contrast_frame = pd.DataFrame(contrasts)
    capture_frame_out = pd.DataFrame(captures)

    # The contrasts re-pool the per-day artefact; the capture table comes from
    # the dispatch phase's own `pooled_capture`. They are two code paths to one
    # number, so they must agree, and a disagreement means the contrast
    # denominator is not the one the headline capture used — which is exactly
    # the FINDING C11-C mistake (scoring two curves against different
    # ceilings), and it would be invisible in the published table.
    published = {
        (row["zone"], row["curve"]): row["capture_rolled_oracle_cash"]
        for row in captures
        if row["capture_rolled_oracle_cash"] is not None
    }
    worst = 0.0
    n_checked = 0
    for row in contrasts:
        for side in ("treatment", "baseline"):
            key = (row["zone"], row[side])
            if key not in published:
                continue
            delta = abs(float(row[f"capture_{side}"]) - float(published[key]))
            worst = max(worst, delta)
            n_checked += 1
    if worst > 1e-6:
        raise FundamentalsError(
            f"a contrast's capture disagrees with the dispatch phase's pooled "
            f"capture by up to {worst:.3g} — the two are not using the same "
            f"denominator, which is the FINDING C11-C failure mode"
        )
    print(f"  capture cross-check: {n_checked} comparisons, worst delta {worst:.3g}")
    contrast_path = RESULTS_DIR / "c14_ladder_contrasts.csv"
    contrast_frame.to_csv(contrast_path, index=False)
    capture_path = RESULTS_DIR / "c14_ladder_capture.csv"
    capture_frame_out.to_csv(capture_path, index=False, float_format="%.6f")

    # The 2024 column, read from the committed store rather than recomputed.
    store = pd.read_csv(RESULTS_DIR / "results.csv")
    prior = store[
        (store["metric"] == "capture_rolled_oracle_cash")
        & (store["scope"] == "common_hours")
        & (store["evaluation_years"].astype(str) == "2024")
        & (store["zone"].isin(zones))
    ]

    summary = {
        "cycle": "C14",
        "question": (
            "NOTE C13-04 / NOTE C8-01 — is the honest exogenous block worth having "
            "under the booster outside ES? A second evaluation year."
        ),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "gbm_fingerprint": GBM_FINGERPRINT,
        "year": LADDER_YEAR,
        "zones": list(zones),
        "denominator": (
            "capture_rolled_oracle_cash (FINDING C11-C): settled cash over the "
            "rolled perfect-foresight run's cash on the same days"
        ),
        "bootstrap": _spec(365, HEADLINE_BLOCK).as_dict(),
        "block_ladder": list(BLOCK_LADDER),
        "contrasts": contrasts,
        "capture": captures,
        "n_store_2024_rows_read": int(len(prior)),
        "capture_cross_check": {
            "n_comparisons": n_checked,
            "worst_absolute_delta": worst,
            "note": (
                "The contrast table re-pools the per-day artefact; the capture "
                "table comes from the dispatch phase's pooled_capture. Two code "
                "paths, one number."
            ),
        },
        "full_history_reproducibility": [
            cross_check_full_history_against_c13(zone) for zone in zones
        ],
        "honest_label": (
            f"{LADDER_YEAR} is a PLAN.md *training* year. The forecasts are genuine "
            f"expanding-window walk-forward predictions, but the LEAR spec and the "
            f"frozen GBM config were both chosen while looking at 2024, so this is a "
            f"second prediction year and not a second configuration test. The sealed "
            f"2025 holdout is the only clean one."
        ),
    }
    summary_path = RESULTS_DIR / "c14_ladder_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")

    for row in contrasts:
        mark = "*" if row.get("excludes_zero") else " "
        print(f"  {row['zone']:<8} {row['treatment']:<22} - {row['baseline']:<22} "
              f"{row['delta_pp']:+7.2f}pp [{row['ci_low_pp']:+7.2f}, "
              f"{row['ci_high_pp']:+7.2f}]{mark}")
    for path in (contrast_path, capture_path, summary_path):
        print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size / 1024:.0f} KiB)")
    return 0


def ladder(args: argparse.Namespace) -> int:
    if args.phase == "ladder-compute":
        return ladder_compute(args)
    if args.phase == "ladder-dispatch":
        return ladder_dispatch(args)
    return ladder_analyse(args)


# ---------------------------------------------------------------------------
# Phase `ingest`: the store rows
# ---------------------------------------------------------------------------

#: The store key C11/C13 use for the nine-zone comparable arm, repeated so the
#: fundamentals rows attach to the same (zone, model, arm) the headroom question
#: is about rather than inventing a new identity for a descriptive metric.
COMPARABLE_STORE_KEY = ("lear", "price_only", FULL_HISTORY_FROM)

#: The descriptive metrics worth a store row. Every one of them is a property of
#: a (zone, year) *market*, not of a forecast, which is why they all go in under
#: the ``oracle`` / ``perfect_foresight`` identity: there is no model behind them.
FUNDAMENTALS_METRICS: tuple[str, ...] = (
    "r2_price_on_residual_load_piecewise",
    "r2_price_on_residual_load_linear",
    "r2_price_on_calendar_only",
    "r2_gain_of_residual_load_over_calendar",
    "spearman_price_residual_load",
    "supply_curve_slope_mid_eur_mwh_per_gw",
    "supply_curve_slope_high_eur_mwh_per_gw",
    "negative_hours_concentration_vs_uniform",
    "r2_lost_by_imposing_residual_load",
)


def fundamentals_store_rows() -> list[ResultRow]:
    """The descriptive chapter's numbers, as store rows.

    Two deliberate choices, both about not misfiling a description as a result:

    * **Vintage.** Every row is ``after_gate_closure``. These numbers are built
      on the Art. 14 vintage, and the store's ``vintage`` column exists exactly
      so that a later cycle filtering for ``honest`` rows does not sweep them up.
      ``backtest.results_store.honest_rows`` therefore excludes all of them,
      which is the correct default for a results table.
    * **Identity.** They go in under the oracle's ``(model, exog_variant)``,
      because there is no forecast behind an R^2 of the realised price on the
      realised-ish residual load. Filing them under a model's key would make
      them join to that model's MAE as though they described it.
    """
    zones = load_zones()
    power = pd.read_csv(RESULTS_DIR / "c14_explanatory_power.csv")
    slopes = pd.read_csv(RESULTS_DIR / "c14_supply_curve_slopes.csv")
    negatives = pd.read_csv(RESULTS_DIR / "c14_negative_price_mechanism.csv")
    sufficiency = pd.read_csv(RESULTS_DIR / "c14_residual_load_sufficiency.csv")

    keyed = {
        "power": power.set_index(["zone", "year"]),
        "slopes": slopes.set_index(["zone", "year"]),
        "negatives": negatives.set_index(["zone", "year"]),
        "sufficiency": sufficiency.set_index(["zone", "year"]),
    }
    mapping = {
        "r2_price_on_residual_load_piecewise": ("power", "r2_piecewise_linear_20"),
        "r2_price_on_residual_load_linear": ("power", "r2_linear"),
        "r2_price_on_calendar_only": ("power", "r2_calendar_only"),
        "r2_gain_of_residual_load_over_calendar": ("power", "gain_over_calendar"),
        "spearman_price_residual_load": ("power", "spearman_price_residual_load"),
        "supply_curve_slope_mid_eur_mwh_per_gw": ("slopes", "slope_mid_eur_mwh_per_gw"),
        "supply_curve_slope_high_eur_mwh_per_gw": ("slopes", "slope_high_eur_mwh_per_gw"),
        "negative_hours_concentration_vs_uniform": (
            "negatives", "concentration_vs_uniform"
        ),
        "r2_lost_by_imposing_residual_load": (
            "sufficiency", "r2_lost_by_imposing_residual_load"
        ),
    }
    rows: list[ResultRow] = []
    for (zone, year), block in keyed["power"].iterrows():
        zone_cfg = zones[zone]
        common = dict(
            zone=zone,
            tier=zone_cfg.tier,
            regime=zone_cfg.regime,
            model=ORACLE_MODEL,
            exog_variant=ORACLE_VARIANT,
            vintage=FUNDAMENTALS_VINTAGE,
            train_from="",
            evaluation_years=str(int(year)),
            scope="own_coverage",
            n=str(int(block["n_hours"])),
            source_cycle="C14",
            source_artefact="c14_fundamentals_summary.json",
        )
        for metric in FUNDAMENTALS_METRICS:
            table, column = mapping[metric]
            frame = keyed[table]
            if (zone, year) not in frame.index:
                continue
            value = frame.loc[(zone, year), column]
            if value is None or pd.isna(value):
                continue
            rows.append(ResultRow(metric=metric, value=float(value), **common))
    return rows


def headroom_store_rows() -> list[ResultRow]:
    """NOTE C13-03's three per-year correlations, with their interval bounds.

    These *are* about the comparable forecast arm — the outcome columns are its
    error and its dispatch headroom — so they are filed under its store key, and
    the ``vintage`` is still ``after_gate_closure`` because the predictor is the
    Art. 14 revision. The arm itself is honest; this measurement of it is not,
    and the row has to say which.
    """
    zones = load_zones()
    frame = pd.read_csv(RESULTS_DIR / "c14_headroom_correlations.csv")
    model, variant, train_from = COMPARABLE_STORE_KEY
    rows: list[ResultRow] = []
    for _, row in frame.iterrows():
        if str(row["year"]) == "pooled" or "spearman" not in frame.columns:
            continue
        if pd.isna(row.get("spearman")):
            continue
        zone_cfg = zones[str(row["zone"])]
        short = {
            "residual_load_revision_mae_mw": "res_revision",
            "residual_load_range_gw": "res_range",
        }[str(row["fundamental"])]
        outcome = {
            "error_over_headroom": "error_over_headroom",
            "price_mae_eur_mwh": "price_mae",
            "realised_spread_eur_mwh": "realised_spread",
        }[str(row["outcome"])]
        base = f"spearman_{short}_vs_{outcome}"
        common = dict(
            zone=str(row["zone"]),
            tier=zone_cfg.tier,
            regime=zone_cfg.regime,
            model=model,
            exog_variant=variant,
            vintage=FUNDAMENTALS_VINTAGE,
            train_from=train_from,
            evaluation_years=str(int(row["year"])),
            scope="own_coverage",
            n=str(int(row["n_days"])),
            source_cycle="C14",
            source_artefact="c14_headroom_correlations.csv",
        )
        rows.append(ResultRow(metric=base, value=float(row["spearman"]), **common))
        for suffix, column in (("_ci_low", "ci_low"), ("_ci_high", "ci_high"),
                               ("_boot_sd", "boot_sd")):
            if pd.isna(row.get(column)):
                continue
            rows.append(
                ResultRow(metric=f"{base}{suffix}", value=float(row[column]), **common)
            )
    return rows


def ladder_store_rows() -> list[ResultRow]:
    """The 2023 capture ratios and the NOTE C8-01 contrast deltas.

    The capture rows carry each arm's own ``(model, exog_variant, vintage,
    train_from)``, so a 2023 row and C11's 2024 row for the same arm are two
    rows of one series. The contrast rows are a *difference*, which has no single
    arm identity, so they are filed under the treatment arm with the baseline in
    the metric name — the same shape C12 used for its contrasts.
    """
    capture_path = RESULTS_DIR / "c14_ladder_capture.csv"
    contrast_path = RESULTS_DIR / "c14_ladder_contrasts.csv"
    if not capture_path.exists() or not contrast_path.exists():
        return []
    zones = load_zones()
    capture = pd.read_csv(capture_path)
    contrasts = pd.read_csv(contrast_path)
    rows: list[ResultRow] = []
    for _, row in capture.iterrows():
        zone_cfg = zones[str(row["zone"])]
        common = dict(
            zone=str(row["zone"]),
            tier=zone_cfg.tier,
            regime=zone_cfg.regime,
            model=str(row["model"]),
            exog_variant=str(row["exog_variant"]),
            vintage=str(row["vintage"]) or "honest",
            train_from=("" if pd.isna(row["train_from"]) else str(row["train_from"])),
            evaluation_years=str(int(row["year"])),
            scope="common_hours",
            n=("" if pd.isna(row["n_days"]) else str(int(row["n_days"]))),
            model_fingerprint=(GBM_FINGERPRINT if str(row["model"]) == "gbm" else ""),
            source_cycle="C14",
            source_artefact=f"c14_ladder_{row['zone']}_{int(row['year'])}_daily.csv.gz",
        )
        for metric, column in (
            ("capture_rolled_oracle_cash", "capture_rolled_oracle_cash"),
            ("eur_per_mw_year_lost_vs_oracle", "eur_per_mw_year_lost_vs_oracle"),
            ("mae", "mae_on_dispatched_days"),
        ):
            value = row.get(column)
            if value is None or pd.isna(value):
                continue
            rows.append(ResultRow(metric=metric, value=float(value), **common))

    arms = {a.curve: a for a in ladder_arms("DE-LU")}
    for _, row in contrasts.iterrows():
        arm = arms[str(row["treatment"])]
        zone_cfg = zones[str(row["zone"])]
        base = f"capture_delta_pp_vs_{row['baseline']}"
        common = dict(
            zone=str(row["zone"]),
            tier=zone_cfg.tier,
            regime=zone_cfg.regime,
            model=arm.model,
            exog_variant=arm.exog_variant,
            vintage=arm.vintage,
            train_from=arm.train_from,
            evaluation_years=str(int(row["year"])),
            scope="common_hours",
            n=str(int(row["n_days"])),
            model_fingerprint=arm.model_fingerprint,
            source_cycle="C14",
            source_artefact="c14_ladder_contrasts.csv",
        )
        rows.append(ResultRow(metric=base, value=float(row["delta_pp"]), **common))
        for suffix, column in (("_ci_low", "ci_low_pp"), ("_ci_high", "ci_high_pp"),
                               ("_boot_sd", "boot_sd_pp")):
            rows.append(
                ResultRow(metric=f"{base}{suffix}", value=float(row[column]), **common)
            )
    return rows


def ingest(args: argparse.Namespace) -> int:
    required = (
        RESULTS_DIR / "c14_explanatory_power.csv",
        RESULTS_DIR / "c14_headroom_correlations.csv",
    )
    for path in required:
        if not path.exists():
            raise FundamentalsError(
                f"{path.name} is missing — run the fundamentals and headroom phases first"
            )
    rows = fundamentals_store_rows() + headroom_store_rows() + ladder_store_rows()
    print(f"{len(rows):,} row(s) to append")
    if args.no_append:
        print("--no-append: nothing written")
        return 0
    report = append_rows(
        rows,
        cycle="C14",
        git_sha=git_sha(),
        config_hash=config_hash(),
        path=None if args.results_path is None else Path(args.results_path),
        argv=sys.argv,
        note=(
            "C14 fundamentals: price against the ENTSO-E D-1 forecast residual "
            "load for Tier A, 2022-2024, plus NOTE C13-03's per-day correlations "
            "and the 2023 exogenous ladder (NOTE C13-04 / NOTE C8-01). Every "
            f"descriptive row is vintage '{FUNDAMENTALS_VINTAGE}': the Art. 14 "
            "wind/solar forecast is published six hours after gate closure, so "
            "these numbers describe the delivery day and are not an information "
            "set. Intervals are the paired circular moving-block day bootstrap, "
            f"{N_REPLICATES} replicates, seed {SEED}, block {HEADLINE_BLOCK} day(s)."
        ),
    )
    print(f"appended {report.n_rows_appended:,} rows as run {report.run_id} "
          f"({report.n_rows_before:,} -> {report.n_rows_before + report.n_rows_appended:,})")
    verification = verify_append_only()
    print(f"verify_append_only: {verification}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.phase == "verify":
        return verify(args)
    if args.phase == "fundamentals":
        return fundamentals(args)
    if args.phase == "headroom":
        return headroom(args)
    if args.phase in {"ladder-compute", "ladder-dispatch", "ladder-analyse"}:
        return ladder(args)
    if args.phase == "ingest":
        return ingest(args)
    raise FundamentalsError(f"unreachable phase {args.phase!r}")


if __name__ == "__main__":
    raise SystemExit(main())
