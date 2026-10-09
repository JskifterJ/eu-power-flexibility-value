"""C13 — the regime analysis: per-year tables, the crisis year, the cutover flag.

Four things are tested here.

**The per-year machinery is right where it is new.** C13 deliberately reuses
C11's ``pooled_capture`` and C12's metric and bootstrap layer rather than
re-deriving them, so what is genuinely new is small and is tested directly: the
three-curve basis of a zone-year, the *unpaired* year-on-year difference (two
years share no market day, so the pairing that makes C12's contrasts tight is
not available and the interval must be the wider one), the shape table of this
cycle's own prediction artefacts, and the store rows.

**The sealed holdout cannot be reached.** The guard fires on the *year list*
before any path is built, so 2025 cannot arrive as a missing-file message, and
every committed C13 artefact is checked to carry no market day outside the
years the cycle evaluated.

**The 2024 column is the published 2024 number.** C13's per-year table reads
C12's committed per-day artefact for 2024 and re-pools it. The reproduction
check against the committed store rows is therefore load-bearing — a per-year
table whose last column is a near neighbour of the published figure would be
worse than no table — and it is tested for its ability to *fail*.

**The C13 findings are pinned to the committed artefacts**, in C12's precedent,
so a later cycle cannot quietly restate a claim this cycle could not establish.
Tests that need an artefact skip when it is absent (a fresh clone has the
committed files; a half-run working tree may not), and nothing here needs the
price cache, which is gitignored.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.results_store import RESULTS_PATH
from backtest.run_c12_metrics import CurveDays
from backtest.run_c13_regime import (
    BLOCK_LADDER,
    THIN_REGIME_ORACLE_FLOOR_EUR_PER_MW_YEAR as THIN_REGIME_FLOOR,
    COMPARABLE_CURVE,
    CRISIS_YEAR,
    HEADLINE_BLOCK,
    NAIVE_CURVE,
    NEW_YEARS,
    ORACLE_CURVE,
    OUTLIER_ZONE,
    REPRODUCED_2024,
    REPRODUCED_2024_TIER_B_COMMON,
    VALIDATION_YEAR,
    RegimeError,
    check_2024_reproduction,
    comparable_basis,
    cutover_status,
    load_daily_by_year,
    manifest_cross_check,
    regime_price_table,
    shape_table_for,
    store_rows_for_year,
    unpaired_difference,
)
from backtest.run_c3_naive import RESULTS_DIR
from data.holdout import SealedHoldoutError
from data.manifest import MANIFEST_CSV

RESULTS = Path(RESULTS_DIR)
SUMMARY = RESULTS / "c13_regime_summary.json"
POINTS = RESULTS / "c13_per_year_metrics.csv"
INTERVALS = RESULTS / "c13_year_intervals.csv"
REGIME = RESULTS / "c13_regime_table.csv"
DAILY = RESULTS / "c13_daily_by_year.csv.gz"


def _needs(path: Path):
    if not path.exists():
        pytest.skip(f"{path.name} has not been produced in this working tree")


@pytest.fixture(scope="module")
def summary() -> dict:
    _needs(SUMMARY)
    with SUMMARY.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def points() -> pd.DataFrame:
    _needs(POINTS)
    return pd.read_csv(POINTS)


@pytest.fixture(scope="module")
def intervals() -> pd.DataFrame:
    _needs(INTERVALS)
    return pd.read_csv(INTERVALS)


# ---------------------------------------------------------------------------
# The basis of a zone-year
# ---------------------------------------------------------------------------


def _curve_days(curve: str, days: list[str], **columns) -> CurveDays:
    frame = pd.DataFrame(
        {
            "cash": np.linspace(10.0, 20.0, len(days)),
            "oracle_cash": np.linspace(12.0, 22.0, len(days)),
            "lost": np.full(len(days), 2.0),
            "value_added": np.linspace(9.0, 19.0, len(days)),
            "realised_spread": np.full(len(days), 50.0),
            "n_dispatch_hours": np.full(len(days), 24),
            "n_hours": np.full(len(days), 24.0),
            "sum_abs_error": np.full(len(days), 240.0),
            "sum_sq_error": np.full(len(days), 2400.0),
            "sum_error": np.full(len(days), 24.0),
            "realised_spread_forecastwise": np.full(len(days), 50.0),
            "forecast_spread": np.full(len(days), 40.0),
            "spread_error": np.full(len(days), -10.0),
            "abs_spread_error": np.full(len(days), 10.0),
            "spearman": np.full(len(days), 0.8),
            "spearman_contrib": np.full(len(days), 0.8),
            "spearman_defined": np.full(len(days), 1.0),
            **columns,
        },
        index=pd.Index(days, name="market_day"),
    )
    return CurveDays(
        zone="ZZ",
        curve=curve,
        tier="B",
        regime="test",
        model="lear" if curve == COMPARABLE_CURVE else curve,
        exog_variant="price_only",
        vintage="honest",
        train_from="2019-01-01",
        model_fingerprint="",
        frame=frame,
        has_forecast_error=curve != ORACLE_CURVE,
    )


def test_the_basis_of_a_zone_year_is_the_intersection_of_its_three_curves():
    curves = {
        ORACLE_CURVE: _curve_days(ORACLE_CURVE, ["2022-01-01", "2022-01-02", "2022-01-03"]),
        COMPARABLE_CURVE: _curve_days(COMPARABLE_CURVE, ["2022-01-02", "2022-01-03"]),
        NAIVE_CURVE: _curve_days(NAIVE_CURVE, ["2022-01-01", "2022-01-02", "2022-01-03"]),
    }
    assert comparable_basis(curves) == ("2022-01-02", "2022-01-03")


def test_a_zone_year_whose_curves_share_no_day_is_refused_not_pooled():
    curves = {
        ORACLE_CURVE: _curve_days(ORACLE_CURVE, ["2022-01-01"]),
        COMPARABLE_CURVE: _curve_days(COMPARABLE_CURVE, ["2022-01-02"]),
        NAIVE_CURVE: _curve_days(NAIVE_CURVE, ["2022-01-01"]),
    }
    with pytest.raises(RegimeError):
        comparable_basis(curves)


# ---------------------------------------------------------------------------
# The year-on-year difference is unpaired, and says so
# ---------------------------------------------------------------------------


def test_the_year_on_year_difference_is_unpaired_and_centred_on_the_point():
    rng = np.random.default_rng(7)
    left = rng.normal(0.90, 0.02, 4096)
    right = rng.normal(0.88, 0.02, 4096)
    out = unpaired_difference(left, right, 0.02, HEADLINE_BLOCK, 365)
    assert out["pairing"].startswith("unpaired")
    assert out["point"] == pytest.approx(0.02)
    # Two independent draws: the difference's sd is ~sqrt(2) x one arm's, which
    # is exactly what a pairing would have removed. If this ever came back at
    # one arm's sd, the difference would be being treated as paired.
    assert out["boot_sd"] == pytest.approx(math.sqrt(2) * 0.02, rel=0.1)


def test_an_unpaired_difference_of_a_series_with_itself_is_not_zero_width():
    rng = np.random.default_rng(11)
    draws = rng.normal(1.0, 0.05, 2048)
    out = unpaired_difference(draws, draws, 0.0, HEADLINE_BLOCK, 100)
    # Same array, so this one *is* degenerate — the test exists to document that
    # the function does no pairing of its own: identical inputs collapse only
    # because they are identical, never because the function matched them up.
    assert out["boot_sd"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# This cycle's own shape table
# ---------------------------------------------------------------------------


def test_the_shape_table_of_a_hand_made_day_is_what_it_should_be():
    index = pd.date_range("2022-03-01", periods=4, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "market_day": ["2022-03-01"] * 4,
            "y_true": [10.0, 20.0, 30.0, 40.0],
            "y_pred": [12.0, 18.0, 33.0, 37.0],
        },
        index=index,
    )
    table = shape_table_for(frame, "y_pred")
    row = table.loc["2022-03-01"]
    assert row["n_hours"] == 4
    assert row["sum_abs_error"] == pytest.approx(2 + 2 + 3 + 3)
    assert row["realised_spread_forecastwise"] == pytest.approx(30.0)
    assert row["forecast_spread"] == pytest.approx(25.0)
    assert row["spread_error"] == pytest.approx(-5.0)
    assert row["abs_spread_error"] == pytest.approx(5.0)
    # The ordering is preserved exactly, so the within-day rank correlation is 1.
    assert row["spearman"] == pytest.approx(1.0)
    assert row["spearman_defined"] == 1.0


def test_a_flat_forecast_day_has_no_ordering_and_is_counted_not_dropped():
    index = pd.date_range("2022-03-02", periods=3, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "market_day": ["2022-03-02"] * 3,
            "y_true": [10.0, 20.0, 30.0],
            "y_pred": [15.0, 15.0, 15.0],
        },
        index=index,
    )
    row = shape_table_for(frame, "y_pred").loc["2022-03-02"]
    assert not np.isfinite(row["spearman"])
    assert row["spearman_defined"] == 0.0
    assert row["spearman_contrib"] == 0.0


# ---------------------------------------------------------------------------
# The sealed holdout
# ---------------------------------------------------------------------------


def test_a_sealed_year_is_refused_before_any_path_is_built():
    with pytest.raises(SealedHoldoutError):
        load_daily_by_year(["DE-LU"], [2025])


def test_every_committed_c13_artefact_stays_inside_the_evaluated_years():
    _needs(DAILY)
    daily = pd.read_csv(DAILY, dtype={"market_day": str})
    years = {int(d[:4]) for d in daily["market_day"]}
    assert years <= set(NEW_YEARS) | {VALIDATION_YEAR}
    assert 2025 not in years
    assert set(daily["year"].astype(int)) == years


def test_the_c13_store_rows_name_only_unsealed_single_years():
    if not RESULTS_PATH.exists():
        pytest.skip("the results store is not present in this working tree")
    store = pd.read_csv(RESULTS_PATH)
    c13 = store[store["cycle"] == "C13"]
    if c13.empty:
        pytest.skip("C13 has not ingested its rows in this working tree")
    years = {str(v) for v in c13["evaluation_years"]}
    assert years <= {str(y) for y in NEW_YEARS}
    assert "2025" not in years


# ---------------------------------------------------------------------------
# The 2024 column is the published 2024 number
# ---------------------------------------------------------------------------


def test_the_2024_column_reproduces_the_committed_store_rows(summary):
    block = summary["reproduction_2024"]
    assert block["applicable"]
    assert block["holds"]
    assert block["n_failures"] == 0
    assert block["n_checks"] >= 100


def test_the_2024_reproduction_check_can_actually_fail(points):
    if not RESULTS_PATH.exists():
        pytest.skip("the results store is not present in this working tree")
    store = pd.read_csv(RESULTS_PATH)
    assert check_2024_reproduction(points, store)["holds"]
    nudged = points.copy()
    mask = (
        (nudged["year"] == VALIDATION_YEAR)
        & (nudged["scope"] == "own_coverage")
        & (nudged["curve"] == COMPARABLE_CURVE)
    )
    assert mask.any()
    nudged.loc[mask, "capture_rolled_oracle_cash"] += 1e-6
    report = check_2024_reproduction(nudged, store)
    assert not report["holds"]
    assert report["n_failures"] >= 1


def test_every_reproduced_metric_is_actually_checked(summary):
    checked = {c["metric"] for c in summary["reproduction_2024"]["checks"]}
    assert {m for m, _atol, _rtol in REPRODUCED_2024} <= checked


def test_the_tier_b_zones_reproduce_the_published_point_errors_too(summary):
    """In Tier B C11's curve inventory is this cycle's three curves, so the
    common-hours day set is the same one and the MAE, RMSE and bias C11/C12
    published must come back as well — the check Tier A cannot offer."""
    block = summary.get("reproduction_2024_tier_b_common_hours")
    if block is None:
        pytest.skip("the Tier-B reproduction block is not in this summary")
    assert block["applicable"]
    assert block["holds"]
    assert block["tiers"] == ["B"]
    assert block["store_scope"] == "common_hours"
    checked = {c["metric"] for c in block["checks"]}
    assert {m for m, _atol, _rtol in REPRODUCED_2024_TIER_B_COMMON} <= checked
    assert {c["zone"] for c in block["checks"]} == {
        z for z in summary["zones"] if z not in ("DE-LU", "ES", "NO2")
    }


# ---------------------------------------------------------------------------
# The store rows
# ---------------------------------------------------------------------------


def test_store_rows_skip_2024_and_carry_one_year_each(points, intervals):
    rows = store_rows_for_year(points, intervals)
    assert rows
    years = {row.evaluation_years for row in rows}
    assert years <= {str(y) for y in NEW_YEARS}
    assert str(VALIDATION_YEAR) not in years
    for row in rows:
        assert row.evaluation_years.isdigit() and len(row.evaluation_years) == 4
        assert row.source_cycle == "C13"
        assert row.vintage == "honest"


def test_interval_bounds_are_written_only_on_the_comparable_basis(points, intervals):
    rows = store_rows_for_year(points, intervals)
    bounds = [r for r in rows if r.metric.endswith(("_ci_low", "_ci_high", "_boot_sd"))]
    assert bounds
    assert {r.scope for r in bounds} == {"common_hours"}


# ---------------------------------------------------------------------------
# The regime table, the manifest cross-check and the cutover flag
# ---------------------------------------------------------------------------


def test_the_regime_table_agrees_with_the_committed_manifest_on_negative_hours():
    """Agreement is not the assertion — *explained* agreement is.

    This cycle counts negative hours over the local market days of each year;
    C1's manifest counted over the fetched file's window, which begins at
    00:00Z on 01-01. The local market year reaches one hour further back, so a
    difference of exactly one hour is expected in a zone-year whose first local
    hour cleared below zero — which happened in DE-LU, NL and BE on
    2023-01-01 (−5.17, −3.61 and −4.39 EUR/MWh) and nowhere else in the window.
    The check accounts for the difference hour by hour; anything it cannot
    account for fails the analyse phase.
    """
    _needs(REGIME)
    regime = pd.read_csv(REGIME)
    check = manifest_cross_check(regime)
    assert check["n_zone_years"] == len(regime)
    assert check["all_differences_explained_by_boundary_hours"], check["unexplained"][:5]
    assert check["n_unexplained_differences"] == 0
    assert check["worst_abs_negative_count_delta"] <= 1
    manifest = pd.read_csv(MANIFEST_CSV)
    merged = regime.merge(manifest[["zone", "year", "n_negative"]], on=["zone", "year"])
    assert len(merged) == len(regime)
    gap = (merged["n_negative_hours"] - merged["n_negative"]).abs()
    assert (gap <= merged["n_boundary_hours_extra_vs_manifest"]).all()
    # ... and the differences are only ever the boundary hour, never a hour
    # inside the shared window.
    explained = merged["n_boundary_negative_extra_vs_manifest"] - merged[
        "n_boundary_negative_missing_vs_manifest"]
    assert ((merged["n_negative_hours"] - merged["n_negative"]) == explained).all()


def test_the_cutover_flag_says_every_evaluated_row_is_pre_cutover():
    _needs(REGIME)
    status = cutover_status(pd.read_csv(REGIME))
    assert status["sdac_15min_golive"] == "2025-10-01"
    assert status["every_evaluated_row_is_pre_cutover"]
    assert status["post_cutover_rows"] == 0
    assert status["all_hourly"]
    assert status["resolution_seconds_seen_in_manifest"] == [3600]
    assert max(status["evaluated_years"]) <= VALIDATION_YEAR


def test_the_regime_table_refuses_a_sealed_year():
    with pytest.raises(SealedHoldoutError):
        regime_price_table(["DE-LU"], [2025])


# ---------------------------------------------------------------------------
# The findings, pinned to the artefacts this cycle committed
# ---------------------------------------------------------------------------


def test_the_crisis_year_is_reported_separately_for_every_zone(summary):
    crisis = summary["crisis_2022"]
    assert crisis["crisis_year"] == CRISIS_YEAR
    assert crisis["pairing"].startswith("unpaired")
    assert len(crisis["per_zone"]) == len(summary["zones"])
    for zone, block in crisis["per_zone"].items():
        # The crisis year's *theoretical* value is far above the other years'
        # everywhere — that is the price level, and it is the number a reader
        # would otherwise assume the capture ratio follows.
        assert block["oracle_ratio_2022_over_other_years"] > 1.0, zone


def test_the_per_year_table_covers_every_zone_and_every_evaluated_year(points, summary):
    comparable = points[
        (points["scope"] == "common_hours") & (points["curve"] == COMPARABLE_CURVE)
    ]
    years = sorted(set(int(y) for y in comparable["year"]))
    assert years == sorted(set(NEW_YEARS) | {VALIDATION_YEAR})
    assert set(comparable["zone"]) == set(summary["zones"])
    # A capture ratio outside [0, 1] is possible and is not a bug: a curve can
    # settle *negative* cash, and in NO2 2020 — mean price 9.3 EUR/MWh, mean
    # daily spread 3.41 against a 2 EUR/MWh throughput cost — it does. What
    # must hold is that every such cell is a flagged thin-regime cell, so no
    # ratio against a denominator of noise can travel unlabelled.
    outside = comparable[~comparable["capture_rolled_oracle_cash"].between(0.0, 1.0)]
    thin = {
        (c["zone"], int(c["year"]))
        for c in summary["thin_regime"]["cells"] if c["thin_regime"]
    }
    assert {(r.zone, int(r.year)) for r in outside.itertuples()} <= thin
    flagged = {(f["zone"], int(f["year"])) for f in summary["invariant_flags"]["flags"]}
    assert {(r.zone, int(r.year)) for r in outside.itertuples()} <= flagged
    assert comparable[
        ~comparable.apply(lambda r: (r["zone"], int(r["year"])) in thin, axis=1)
    ]["capture_rolled_oracle_cash"].between(0.0, 1.0).all()


def test_every_year_has_its_band_test_at_every_block_length(summary):
    for year, block in summary["cross_zone_by_year"].items():
        for scope in ("nine_zones", "ex_outlier"):
            for length in BLOCK_LADDER:
                rung = block[scope][f"block_{length}"]
                assert "capture_band_vs_noise" in rung, (year, scope, length)
                assert rung["capture_band_vs_noise"]["p_value"] >= 0.0


def test_the_outlier_zone_is_excluded_from_the_eight_zone_band(summary):
    for year, block in summary["cross_zone_by_year"].items():
        ex = block["ex_outlier"][f"block_{HEADLINE_BLOCK}"]
        assert OUTLIER_ZONE not in ex["zones"]
        assert len(ex["zones"]) == len(summary["zones"]) - 1


def test_the_2024_band_still_reproduces_c12(summary):
    """C12 published 30.40pp / p<1e-4 and 8.29pp / p=0.078. Those rows are
    C12's own per-day artefact, so C13 must reproduce them exactly."""
    year = summary["cross_zone_by_year"].get(str(VALIDATION_YEAR))
    if year is None:
        pytest.skip("2024 was not part of this run")
    nine = year["nine_zones"][f"block_{HEADLINE_BLOCK}"]
    ex = year["ex_outlier"][f"block_{HEADLINE_BLOCK}"]
    assert nine["capture_band_pp"]["point"] == pytest.approx(30.40, abs=0.01)
    assert nine["capture_band_vs_noise"]["p_value"] < 1e-3
    assert ex["capture_band_pp"]["point"] == pytest.approx(8.29, abs=0.01)
    assert 0.05 < ex["capture_band_vs_noise"]["p_value"] < 0.12


# ---------------------------------------------------------------------------
# FINDINGs C13-A..C13-F, pinned
# ---------------------------------------------------------------------------


def test_finding_c13_a_a_zone_moves_across_years_as_much_as_the_zones_differ(summary):
    """The within-zone across-year band is 2.3-5.4x a single year's noise, and
    the same size as the eight-zone band within a year. If a later cycle ever
    reads the cross-zone band as a regime effect, this is the number that says
    it cannot."""
    stability = summary["year_stability"]["per_zone"]
    ratios = {
        zone: block["band_over_mean_sd"]
        for zone, block in stability.items()
        if zone != OUTLIER_ZONE
    }
    assert len(ratios) == 8
    assert min(ratios.values()) > 2.0, ratios
    bands = [block["across_year_band_pp"] for z, block in stability.items()
             if z != OUTLIER_ZONE]
    assert min(bands) > 9.0 and max(bands) < 21.0, bands
    within_year = [
        summary["cross_zone_by_year"][str(y)]["ex_outlier"][f"block_{HEADLINE_BLOCK}"][
            "capture_band_pp"]["point"]
        for y in summary["years"]
    ]
    # The two kinds of band overlap: neither dominates the other.
    assert min(within_year) < max(bands) and max(within_year) > min(bands)


def test_finding_c13_b_the_eight_zone_band_is_not_established(summary):
    """One of five years clears 5% at PLAN.md's daily block. C12 called this
    'at the edge' from one year; five years keep it there, and a later cycle
    must not quote the eight-zone band as established."""
    clears = {}
    for year in summary["years"]:
        rung = summary["cross_zone_by_year"][str(year)]["ex_outlier"][
            f"block_{HEADLINE_BLOCK}"]
        clears[year] = rung["capture_band_vs_noise"]["p_value"] < 0.05
    assert sum(clears.values()) <= 1, clears
    # The nine-zone band, by contrast, is significant in most years.
    nine = {
        year: summary["cross_zone_by_year"][str(year)]["nine_zones"][
            f"block_{HEADLINE_BLOCK}"]["capture_band_vs_noise"]["p_value"] < 0.05
        for year in summary["years"]
    }
    assert sum(nine.values()) >= 4, nine


def test_finding_c13_c_the_outlier_zone_is_bottom_in_every_year(points, summary):
    comparable = points[
        (points["scope"] == "common_hours") & (points["curve"] == COMPARABLE_CURVE)
    ]
    for year, group in comparable.groupby("year"):
        worst = group.loc[group["capture_rolled_oracle_cash"].idxmin(), "zone"]
        assert worst == OUTLIER_ZONE, (year, worst)
        lowest_rho = group.loc[group["within_day_spearman_mean"].idxmin(), "zone"]
        assert lowest_rho == OUTLIER_ZONE, (year, lowest_rho)
    ranking = summary["year_stability"]["cross_year_ranking"]
    assert all(v["same_worst_zone"] for v in ranking.values())
    assert all(v["spearman_capture_ranking"] > 0 for v in ranking.values())


def test_finding_c13_d_error_over_headroom_beats_mae_and_the_spread(summary):
    pooled = summary["spread_vs_capture"]["pooled_across_cells"][
        "spearman_vs_capture_by_predictor"]
    assert pooled["error_over_headroom"] < -0.6
    assert abs(pooled["mae"]) < 0.2
    assert abs(pooled["realised_spread"]) < abs(pooled["error_over_headroom"])
    assert abs(pooled["within_day_spearman"]) < abs(pooled["error_over_headroom"])
    # And it survives dropping the outlier zone, which is what every
    # spread-based correlate C11 tried did not.
    ex = summary["spread_vs_capture"]["pooled_across_cells"][
        "spearman_vs_capture_by_predictor_ex_outlier"]
    assert ex["error_over_headroom"] < -0.6


def test_error_over_headroom_is_literally_mae_over_the_mean_spread(points):
    rows = points[(points["curve"] == COMPARABLE_CURVE) & (points["scope"] == "common_hours")]
    assert not rows.empty
    expected = (
        rows["mae_on_dispatched_hours"] / rows["realised_spread_mean_eur_per_mwh"]
    )
    assert np.allclose(rows["error_over_headroom"], expected, rtol=0, atol=1e-12)


def test_finding_c13_e_the_outlier_stays_below_the_eight_zone_spread_line(summary):
    """NOTE C12-02: conditioning on the realised spread removes almost none of
    NO2's capture deficit, so the thin-spread mechanism does not explain it."""
    block = summary["spread_vs_capture"][f"{OUTLIER_ZONE}_against_that_line"]
    usable = {y: b for y, b in block.items() if not b["thin_regime"]}
    assert len(usable) >= 4
    for year, row in usable.items():
        assert row["residual_pp"] < -15.0, (year, row["residual_pp"])
        assert row["residual_in_sd_of_the_line"] < -2.5, year


def test_finding_c13_f_the_crisis_moved_the_levels_not_the_share(summary):
    crisis = summary["crisis_2022"]["per_zone"]
    lower = [z for z, b in crisis.items()
             if b["capture_delta_pp_vs_other_years"]["point"] < 0]
    decided = [z for z, b in crisis.items()
               if b["capture_delta_pp_vs_other_years"]["excludes_zero"]]
    assert len(lower) >= 7, lower
    assert len(decided) <= 2, decided
    for zone, block in crisis.items():
        assert block["oracle_ratio_2022_over_other_years"] > 1.5, zone
        assert (
            block["lost_eur_per_mw_year_2022"]
            > 2.0 * block["lost_eur_per_mw_year_mean_other_years"]
        ), zone


# ---------------------------------------------------------------------------
# The thin-regime guard and the recorded flag
# ---------------------------------------------------------------------------


def test_the_thin_regime_floor_labels_one_cell_and_the_choice_does_not_matter(summary):
    thin = summary["thin_regime"]
    assert thin["n_thin"] == 1
    assert thin["thin_cells"] == [f"{OUTLIER_ZONE}/2020"]
    # An order of magnitude of daylight between the flagged cell and the next
    # thinnest, so the declared floor is not doing the work.
    assert thin["oracle_eur_per_mw_year_second_min"] > 4 * thin[
        "oracle_eur_per_mw_year_min"]
    counts = {float(k): v for k, v in thin["label_count_by_floor"].items()}
    assert counts[1000.0] == counts[2000.0] == counts[5000.0] == 1


def test_the_pooled_naive_invariant_failure_is_recorded_with_its_numbers(summary):
    """FLAG C13-01. The assertion was not relaxed: it still reports holds=false,
    and the cell it fails on is the one with no headroom to trade."""
    flags = summary["invariant_flags"]["flags"]
    assert len(flags) == 1
    flag = flags[0]
    assert (flag["zone"], int(flag["year"])) == (OUTLIER_ZONE, 2020)
    assert flag["check"] == "beats_naive_pooled_common_days"
    assert flag["detail"]["holds"] is False
    assert flag["detail"]["margin_eur"] < 0
    assert flag["curve_eur_per_mw_year"] < 0
    assert flag["oracle_eur_per_mw_year"] < THIN_REGIME_FLOOR
    assert flag["realised_spread_mean_eur_per_mwh"] < 5.0


def test_the_per_day_oracle_bound_held_everywhere_it_was_checked():
    """The invariant that *is* a theorem. If this ever fails, the LP is wrong
    and no finding in this cycle survives."""
    summaries = sorted(RESULTS.glob("c13_dispatch_*_summary.json"))
    if not summaries:
        pytest.skip("no C13 dispatch summary in this working tree")
    checked = failures = 0
    worst = -float("inf")
    for path in summaries:
        with path.open(encoding="utf-8") as fh:
            block = json.load(fh)
        for curve, checks in block["invariants"].items():
            dominance = checks.get("same_start_oracle_dominates_every_day")
            if not dominance:
                continue
            checked += dominance["n_days_checked"]
            failures += dominance["n_failures"]
            worst = max(worst, dominance["worst_excess_eur"])
    assert checked > 20_000
    assert failures == 0
    assert worst <= 1e-9, worst
