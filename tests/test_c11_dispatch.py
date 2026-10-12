"""C11: the nine-zone dispatch — the arm inventory, the two scopes, the pairing.

Offline only. Every test either builds its own market or reads a committed
artefact; nothing reaches the network and nothing touches a sealed year.

What these tests are defending, in order of how badly it would hurt:

1. **A capture ratio must be a ratio of two sums over the same days.** The whole
   NOTE C10-01 decision is which days, and the one way to get it wrong that no
   invariant would catch is to sum the numerator over one day set and the
   denominator over another. :func:`pooled_capture` takes the day set as an
   argument for exactly that reason, and it is tested on a market where the two
   scopes genuinely differ.
2. **The headline capture metric must not be the same-start ratio.** FINDING
   C11-C: the same-start denominator is re-solved from each arm's own opening
   SoC, so it rewards an arm for arriving at a day in a state where little is
   attainable, and it can reorder two arms that settle within pennies of each
   other. The regression test pins that on the committed DE-LU artefact, so a
   later cycle cannot quietly promote it back to the headline.
3. **MAE and capture must be computed over the same hours.** FINDING C11-D is a
   claim about a *paired* comparison. If the point error were re-used from C10's
   own-coverage rows, ES's 145-hour exogenous hole would make it an unpaired one,
   and the finding would be an artefact of two different samples.
4. **The ``after_gate_closure`` label must survive into the store.** FINDING
   C9-C makes an unlabelled late-vintage capture ratio the single most
   misleading number this project could publish.
5. **C11 must reproduce C6.** The ``lear_full_history`` arm is the forecast C6
   dispatched, so the two cycles must agree exactly; the check has to fail when
   a number moves.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from backtest.results_store import RESULTS_PATH, ResultsStoreError, append_rows
from backtest.run_c11_dispatch import (
    ALIGNED_FROM,
    CONTRASTS,
    FULL_HISTORY_FROM,
    GBM_FINGERPRINT,
    METRIC_KEYS,
    QUANTILE_METRICS,
    arms_for,
    beats_naive,
    check_c6_reproduction,
    comparable_table,
    mae_on_days,
    pooled_capture,
    store_rows,
)
from backtest.run_c3_naive import RESULTS_DIR
from dispatch.battery import BatterySpec
from dispatch.curves import Curve, CurveError, same_start_oracle
from dispatch.rolling import run_rolling_dispatch

BERLIN = "Europe/Berlin"
ZONES_A = ("DE-LU", "ES", "NO2")
ZONES_B = ("FR", "NL", "BE", "IT-North", "DK1", "PL")


# ---------------------------------------------------------------------------
# helpers — a small, deterministic market, built here so the test is self-contained
# ---------------------------------------------------------------------------


def spec_like_committed(**overrides) -> BatterySpec:
    fields = dict(
        power_mw=1.0,
        energy_mwh=2.0,
        round_trip_efficiency=0.88,
        throughput_cost_eur_per_mwh=2.0,
        initial_soc_fraction=0.5,
        terminal_mode="trailing_value",
    )
    fields.update(overrides)
    return BatterySpec(**fields)


def price_series(n_days: int = 24, start: str = "2024-02-01", seed: int = 3) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.date_range(f"{start} 00:00", periods=24 * n_days, freq="h", tz="UTC")
    hour = index.hour.to_numpy()
    shape = 60 + 35 * np.sin((hour - 4) / 24 * 2 * np.pi)
    return pd.Series(shape + rng.normal(0, 12, len(index)), index=index, name="price")


def roll(realised, spec, decision=None, curve="oracle", days=None):
    return run_rolling_dispatch(
        "DE-LU", realised, spec, decision_prices=decision, curve=curve,
        days=days, tz=BERLIN,
    )


@pytest.fixture(scope="module")
def market():
    """Realised prices, two forecasts, and the day set every curve can dispatch."""
    realised = price_series()
    rng = np.random.default_rng(11)
    good = realised + rng.normal(0, 8, len(realised))
    poor = realised + rng.normal(0, 30, len(realised))
    days = sorted({d for d in pd.Series(realised.index).dt.tz_convert(BERLIN).dt.date})[2:-1]
    return realised, good, poor, days


@pytest.fixture(scope="module")
def runs(market):
    realised, good, poor, days = market
    spec = spec_like_committed()
    # `poor` declines one day, so the two scopes genuinely differ — which is the
    # only condition under which the NOTE C10-01 decision is testable at all.
    holed = poor.copy()
    hole_day = days[5]
    mask = pd.Series(holed.index).dt.tz_convert(BERLIN).dt.date.to_numpy() == hole_day
    holed[mask] = np.nan
    results = {
        "oracle": roll(realised, spec, None, "oracle", days),
        "good": roll(realised, spec, good, "good", days),
        "holed": roll(realised, spec, holed, "holed", days),
    }
    bounds = {n: same_start_oracle(r, spec) for n, r in results.items()}
    return {
        "spec": spec, "realised": realised, "days": days, "hole_day": hole_day,
        "results": results, "bounds": bounds,
    }


# ---------------------------------------------------------------------------
# 1. the arm inventory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("zone", ZONES_A)
def test_tier_a_has_eight_arms_and_exactly_one_comparable_one(zone):
    arms = arms_for(zone, "A")
    assert len(arms) == 8
    comparable = [a for a in arms if a.is_comparable]
    assert len(comparable) == 1, "the cross-zone table needs exactly one like-for-like arm"
    assert comparable[0].curve == "lear_full_history"
    assert comparable[0].train_from == FULL_HISTORY_FROM


@pytest.mark.parametrize("zone", ZONES_B)
def test_tier_b_has_two_arms_and_the_same_comparable_key_as_tier_a(zone):
    arms = arms_for(zone, "B")
    assert len(arms) == 2
    comparable = [a for a in arms if a.is_comparable]
    assert len(comparable) == 1
    # The key is what makes the nine-zone table like-for-like by construction
    # rather than by assertion (FINDING C10-B's honest statement depends on it).
    a_arm = next(a for a in arms_for("DE-LU", "A") if a.is_comparable)
    assert (comparable[0].model, comparable[0].exog_variant, comparable[0].train_from) == (
        a_arm.model, a_arm.exog_variant, a_arm.train_from
    )


@pytest.mark.parametrize("zone", ZONES_A + ZONES_B)
def test_only_the_res_as_published_arms_are_labelled_after_gate_closure(zone):
    tier = "A" if zone in ZONES_A else "B"
    for arm in arms_for(zone, tier):
        expected = "after_gate_closure" if "as_published" in arm.curve else "honest"
        assert arm.vintage == expected, (
            f"{arm.curve}: FINDING C9-C makes a mislabelled vintage the most "
            f"misleading thing this project could publish"
        )


@pytest.mark.parametrize("zone", ZONES_A)
def test_every_exogenous_arm_sits_on_the_aligned_window(zone):
    """No archived ENTSO-E D-1 forecast vintage exists before 2022 (PLAN.md)."""
    for arm in arms_for(zone, "A"):
        if arm.exog_variant.startswith("res") or arm.exog_variant == "load_only":
            assert arm.train_from == ALIGNED_FROM


@pytest.mark.parametrize("zone", ZONES_A)
def test_every_gbm_arm_carries_the_frozen_config_fingerprint(zone):
    for arm in arms_for(zone, "A"):
        if arm.model == "gbm":
            assert arm.model_fingerprint == GBM_FINGERPRINT
        else:
            assert arm.model_fingerprint == ""


def test_an_unknown_tier_is_refused():
    with pytest.raises(CurveError, match="tier"):
        arms_for("DE-LU", "C")


def test_every_contrast_names_arms_that_exist():
    names = {a.curve for a in arms_for("DE-LU", "A")}
    for left, right, _ in CONTRASTS:
        assert left in names and right in names


# ---------------------------------------------------------------------------
# 2. pooled_capture — a ratio of two sums over one day set
# ---------------------------------------------------------------------------


def test_pooled_capture_sums_numerator_and_denominator_over_the_same_days(runs):
    result, bound = runs["results"]["good"], runs["bounds"]["good"]
    days = sorted(result.days)[:7]
    block = pooled_capture(result, bound, runs["results"]["oracle"], days,
                           runs["spec"].power_mw)
    assert block["n_days"] == 7
    wanted_num = sum(result.valuations[d].value_added_eur for d in days)
    wanted_den = sum(bound[d].value_added_eur for d in days)
    assert block["value_added_eur"] == pytest.approx(wanted_num)
    assert block["same_start_oracle_value_added_eur"] == pytest.approx(wanted_den)
    assert block["capture_same_start_pooled"] == pytest.approx(wanted_num / wanted_den)


def test_the_pooled_ratio_is_not_the_mean_of_the_daily_ratios(runs):
    """Both are reported; they are different numbers and must not be conflated.

    Power-price value is concentrated in a few days, so a ratio of sums and a
    mean of per-day ratios disagree systematically. PLAN.md asks for the
    distribution as well as the mean, which only means something if the two are
    kept apart.
    """
    result, bound = runs["results"]["good"], runs["bounds"]["good"]
    block = pooled_capture(result, bound, runs["results"]["oracle"],
                           result.days, runs["spec"].power_mw)
    assert block["capture_same_start_pooled"] != pytest.approx(
        block["capture_same_start_mean_daily"], abs=1e-9
    )


def test_the_two_scopes_differ_when_one_curve_declines_a_day(runs):
    """The condition the NOTE C10-01 decision exists to handle, made concrete."""
    own = set(runs["results"]["holed"].days)
    everyone = set.intersection(*(set(r.days) for r in runs["results"].values()))
    assert runs["hole_day"] not in own, "the holed curve should have skipped its hole"
    oracle_own = set(runs["results"]["oracle"].days)
    assert runs["hole_day"] in oracle_own, "the oracle has no hole"
    assert everyone < oracle_own, "the intersection must be strictly smaller"

    oracle, bound = runs["results"]["oracle"], runs["bounds"]["oracle"]
    at_own = pooled_capture(oracle, bound, oracle, oracle_own, 1.0)
    at_common = pooled_capture(oracle, bound, oracle, everyone, 1.0)
    assert at_own["n_days"] > at_common["n_days"]
    assert at_own["cash_eur"] != pytest.approx(at_common["cash_eur"])


def test_pooled_capture_refuses_a_denominator_that_does_not_cover_the_numerator(runs):
    """A capture ratio whose oracle skipped the candidate's days is meaningless."""
    candidate = runs["results"]["oracle"]
    short = roll(runs["realised"], runs["spec"], None, "oracle",
                 sorted(candidate.days)[:4])
    with pytest.raises(CurveError, match="no rolled-oracle valuation"):
        pooled_capture(candidate, runs["bounds"]["oracle"], short,
                       candidate.days, 1.0)


def test_pooled_capture_on_an_empty_day_set_reports_nothing_rather_than_dividing(runs):
    block = pooled_capture(runs["results"]["good"], runs["bounds"]["good"],
                           runs["results"]["oracle"], [], 1.0)
    assert block == {"n_days": 0}


def test_the_oracle_captures_exactly_one_of_itself(runs):
    block = pooled_capture(runs["results"]["oracle"], runs["bounds"]["oracle"],
                           runs["results"]["oracle"], runs["results"]["oracle"].days, 1.0)
    assert block["capture_rolled_oracle_cash"] == pytest.approx(1.0)
    assert block["capture_same_start_pooled"] == pytest.approx(1.0)


def test_a_better_forecast_captures_more_than_a_worse_one(runs):
    """Sanity: the metric has to be monotone in forecast quality on average."""
    days = sorted(set(runs["results"]["good"].days) & set(runs["results"]["holed"].days))
    good = pooled_capture(runs["results"]["good"], runs["bounds"]["good"],
                          runs["results"]["oracle"], days, 1.0)
    poor = pooled_capture(runs["results"]["holed"], runs["bounds"]["holed"],
                          runs["results"]["oracle"], days, 1.0)
    assert good["capture_rolled_oracle_cash"] > poor["capture_rolled_oracle_cash"]


def test_beats_naive_is_pooled_and_reports_the_per_day_rate_beside_it(runs):
    days = sorted(set(runs["results"]["good"].days) & set(runs["results"]["holed"].days))
    report = beats_naive(runs["results"]["good"], runs["results"]["holed"], days)
    assert report["holds"] is True
    assert report["margin_eur"] == pytest.approx(
        report["model_cash_eur"] - report["naive_cash_eur"]
    )
    # The per-day rate is a *reported* count, not an assertion, so it must equal
    # a direct count rather than being derived from the pooled totals.
    wanted = sum(
        1 for d in days
        if runs["results"]["good"].valuations[d].value_added_eur
        > runs["results"]["holed"].valuations[d].value_added_eur + 1e-9
    )
    assert report["per_day_beats_naive_days"] == wanted
    assert report["per_day_beats_naive_share"] == pytest.approx(wanted / len(days))


def test_the_pooled_half_can_hold_while_the_per_day_half_fails(runs):
    """CLAUDE.md states ``naive <= forecast`` as an average, not a per-day claim.

    So the machinery has to be able to report a pooled pass alongside per-day
    losses. Two forecasts of comparable quality produce exactly that, and if the
    per-day rate were ever asserted instead of reported this would fail.
    """
    rng = np.random.default_rng(23)
    realised = runs["realised"]
    a = realised + rng.normal(0, 14, len(realised))
    b = realised + rng.normal(0, 16, len(realised))
    days = runs["days"]
    run_a = roll(realised, runs["spec"], a, "a", days)
    run_b = roll(realised, runs["spec"], b, "b", days)
    shared = sorted(set(run_a.days) & set(run_b.days))
    report = beats_naive(run_a, run_b, shared)
    assert report["holds"] is True, "the better forecast must win pooled"
    assert report["per_day_beats_naive_share"] < 1.0, (
        "and must still lose on some individual days"
    )


# ---------------------------------------------------------------------------
# 3. the pairing: MAE over exactly the dispatched hours
# ---------------------------------------------------------------------------


def test_mae_on_days_uses_exactly_the_hours_of_those_days(market):
    realised, good, _, days = market
    curve = Curve(name="good", prices=good, source="test")
    chosen = days[3:6]
    got = mae_on_days(curve, realised, chosen, BERLIN)
    labels = pd.Series(good.index).dt.tz_convert(BERLIN).dt.date.to_numpy()
    mask = np.isin(labels, np.array(chosen, dtype=object))
    assert got["n_hours"] == int(mask.sum()) == 72
    wanted = np.mean(np.abs(good.to_numpy()[mask] - realised.to_numpy()[mask]))
    assert got["mae"] == pytest.approx(wanted)


def test_mae_on_days_ignores_hours_outside_the_day_set(market):
    """The point of recomputing rather than re-using C10's number."""
    realised, good, _, days = market
    curve = Curve(name="good", prices=good, source="test")
    narrow = mae_on_days(curve, realised, days[:2], BERLIN)
    wide = mae_on_days(curve, realised, days, BERLIN)
    assert narrow["n_hours"] < wide["n_hours"]
    assert narrow["mae"] != pytest.approx(wide["mae"])


def test_mae_on_days_skips_holes_rather_than_scoring_them(market):
    realised, good, _, days = market
    holed = good.copy()
    day = days[0]
    labels = pd.Series(holed.index).dt.tz_convert(BERLIN).dt.date.to_numpy()
    in_day = np.flatnonzero(labels == day)
    assert len(in_day) == 24
    holed.iloc[in_day[:5]] = np.nan
    got = mae_on_days(Curve(name="h", prices=holed, source="t"), realised, [day], BERLIN)
    assert got["n_hours"] == 24 - 5
    # and the score is the score of the hours that survived, not of a filled vector
    kept = in_day[5:]
    wanted = np.mean(
        np.abs(good.to_numpy()[kept] - realised.to_numpy()[kept])
    )
    assert got["mae"] == pytest.approx(wanted)


def test_mae_on_an_empty_day_set_is_none_not_nan(market):
    realised, good, _, _ = market
    assert mae_on_days(Curve(name="g", prices=good, source="t"), realised, [], BERLIN) is None


# ---------------------------------------------------------------------------
# 4. store rows
# ---------------------------------------------------------------------------


@pytest.fixture
def pooled_for_rows(runs):
    """A ``pooled`` mapping shaped exactly as ``run_zone`` builds one."""
    shared = sorted(set.intersection(*(set(r.days) for r in runs["results"].values())))
    out = {}
    for name, result in runs["results"].items():
        out[name] = {
            "own_coverage": pooled_capture(result, runs["bounds"][name],
                                           runs["results"]["oracle"], result.days, 1.0),
            "common_hours": pooled_capture(result, runs["bounds"][name],
                                           runs["results"]["oracle"], shared, 1.0),
        }
    return out


def _arms_for_rows():
    return [
        a for a in arms_for("DE-LU", "A")
        if a.curve in ("lear_full_history", "lear_res_as_published")
    ]


def test_store_rows_are_accepted_by_the_store_unchanged(tmp_path, pooled_for_rows, runs):
    """The real test of the row shape: the store's own validation must accept it."""
    arms = _arms_for_rows()
    renamed = {
        "lear_full_history": pooled_for_rows["good"],
        "lear_res_as_published": pooled_for_rows["holed"],
        "oracle": pooled_for_rows["oracle"],
    }
    rows = store_rows("DE-LU", "A", "thermal-RES-mixed", arms, renamed, [2024],
                      runs["spec"], None)
    assert rows
    report = append_rows(
        rows, cycle="C11-test", git_sha="deadbeef", config_hash="cafe",
        path=tmp_path / "results.csv", runs_path=tmp_path / "runs.json",
    )
    assert report.n_rows_appended == len(rows)


def test_the_late_vintage_label_survives_into_the_rows(pooled_for_rows, runs):
    arms = _arms_for_rows()
    renamed = {
        "lear_full_history": pooled_for_rows["good"],
        "lear_res_as_published": pooled_for_rows["holed"],
    }
    rows = store_rows("DE-LU", "A", "r", arms, renamed, [2024], runs["spec"], None)
    late = {r.vintage for r in rows if r.model == "lear"
            and r.exog_variant == "res_as_published"}
    honest = {r.vintage for r in rows if r.exog_variant == "price_only"}
    assert late == {"after_gate_closure"}
    assert honest == {"honest"}


def test_the_oracle_rows_are_labelled_as_perfect_foresight_not_as_a_model(
    pooled_for_rows, runs
):
    rows = store_rows("DE-LU", "A", "r", [], {"oracle": pooled_for_rows["oracle"]},
                      [2024], runs["spec"], None)
    assert {r.model for r in rows} == {"oracle"}
    assert {r.exog_variant for r in rows} == {"perfect_foresight"}
    assert {r.train_from for r in rows} == {""}, "perfect foresight has no training window"


def test_the_paired_point_error_is_written_only_at_the_scope_it_was_measured_at(
    pooled_for_rows, runs
):
    """FINDING C11-D's pairing: the MAE belongs to the common-hours day set."""
    arms = [a for a in arms_for("DE-LU", "A") if a.curve == "lear_full_history"]
    rows = store_rows(
        "DE-LU", "A", "r", arms, {"lear_full_history": pooled_for_rows["good"]},
        [2024], runs["spec"],
        {"lear_full_history": {"mae": 12.5, "rmse": 20.0, "bias": 1.0, "n_hours": 8759}},
    )
    paired = [r for r in rows if r.metric == "mae_on_dispatched_hours"]
    assert len(paired) == 1
    assert paired[0].scope == "common_hours"
    assert paired[0].value == pytest.approx(12.5)
    assert paired[0].n_scored == "8759"


def test_no_row_is_written_for_a_metric_that_could_not_be_computed(
    pooled_for_rows, runs
):
    """A store row is a measurement; an absent one is absence, never a NaN."""
    block = {k: dict(v) for k, v in pooled_for_rows["good"].items()}
    block["own_coverage"]["capture_same_start_pooled"] = None
    block["common_hours"]["capture_rolled_oracle_cash"] = float("nan")
    arms = [a for a in arms_for("DE-LU", "A") if a.curve == "lear_full_history"]
    rows = store_rows("DE-LU", "A", "r", arms, {"lear_full_history": block},
                      [2024], runs["spec"], None)
    by = {(r.scope, r.metric) for r in rows}
    assert ("own_coverage", "capture_same_start_pooled") not in by
    assert ("common_hours", "capture_rolled_oracle_cash") not in by
    assert ("common_hours", "capture_same_start_pooled") in by


def test_a_capture_ratio_against_2025_can_now_be_written(
    tmp_path, pooled_for_rows, runs
):
    """Was test_a_capture_ratio_against_a_sealed_year_cannot_be_written. The
    store's own tripwire (tests/test_c10_results_store.py) now permits 2025,
    unsealed at Checkpoint C (2026-10-12); re-asserted here for a dispatch
    metric specifically."""
    arms = [a for a in arms_for("DE-LU", "A") if a.curve == "lear_full_history"]
    rows = store_rows("DE-LU", "A", "r", arms,
                      {"lear_full_history": pooled_for_rows["good"]},
                      [2025], runs["spec"], None)
    append_rows(rows, cycle="C11-test", git_sha="x", config_hash="y",
                path=tmp_path / "r.csv", runs_path=tmp_path / "runs.json")  # does not raise


def test_every_metric_name_this_cycle_writes_is_snake_case_and_in_range():
    from backtest.results_store import METRIC_NAME
    names = [m for m, _ in METRIC_KEYS]
    names += [f"capture_same_start_{q}_daily" for q in QUANTILE_METRICS]
    names += ["mae_on_dispatched_hours", "rmse_on_dispatched_hours",
              "bias_on_dispatched_hours"]
    assert len(set(names)) == len(names), "a duplicated metric name collides in the store"
    for name in names:
        assert METRIC_NAME.match(name), name


# ---------------------------------------------------------------------------
# 5. FINDING C11-C — the headline capture must be the rolled-oracle ratio
# ---------------------------------------------------------------------------


def test_the_comparable_table_quotes_the_rolled_oracle_ratio(runs, pooled_for_rows):
    summaries = {
        "DE-LU": {
            "tier": "A", "regime": "thermal-RES-mixed",
            "pooled": {
                "oracle": pooled_for_rows["oracle"],
                "lear_full_history": pooled_for_rows["good"],
                "naive": pooled_for_rows["holed"],
            },
        }
    }
    table = comparable_table(summaries, scope="own_coverage")
    row = table.iloc[0]
    assert row["capture_model"] == pytest.approx(
        pooled_for_rows["good"]["own_coverage"]["capture_rolled_oracle_cash"]
    )
    # and the same-start ratio is carried, but not as the headline
    assert row["capture_model_same_start"] == pytest.approx(
        pooled_for_rows["good"]["own_coverage"]["capture_same_start_pooled"]
    )
    assert row["capture_model"] != pytest.approx(row["capture_model_same_start"])


@pytest.mark.skipif(
    not (RESULTS_DIR / "c11_dispatch_DE-LU_2024_summary.json").exists(),
    reason="needs C11's committed DE-LU artefact",
)
def test_finding_c11_c_the_same_start_ratio_reorders_arms_the_rolled_one_ties():
    """The measurement FINDING C11-C rests on, pinned against the artefact.

    On DE-LU the two ``res_*`` LEAR arms settle within 0.4 EUR of each other over
    365 days, yet their same-start capture ratios differ by ~4pp — entirely
    because their opening SoC trajectories differ. If a later cycle promotes the
    same-start ratio back to the headline, this fails.
    """
    with (RESULTS_DIR / "c11_dispatch_DE-LU_2024_summary.json").open() as fh:
        summary = json.load(fh)
    a = summary["pooled"]["lear_res_persistence"]["common_hours"]
    b = summary["pooled"]["lear_res_as_published"]["common_hours"]
    assert abs(a["cash_eur"] - b["cash_eur"]) < 1.0, "the arms settle within 1 EUR"
    rolled_gap = abs(a["capture_rolled_oracle_cash"] - b["capture_rolled_oracle_cash"])
    same_gap = abs(a["capture_same_start_pooled"] - b["capture_same_start_pooled"])
    assert rolled_gap < 1e-4, "one denominator per zone: the ratios must tie"
    assert same_gap > 0.03, "the same-start denominator moves with the arm's own SoC"


@pytest.mark.skipif(
    not (RESULTS_DIR / "c11_dispatch_DE-LU_2024_summary.json").exists(),
    reason="needs C11's committed DE-LU artefact",
)
def test_every_committed_zone_summary_reports_no_invariant_failure():
    for zone in ZONES_A + ZONES_B:
        path = RESULTS_DIR / f"c11_dispatch_{zone}_2024_summary.json"
        if not path.exists():
            continue
        with path.open() as fh:
            summary = json.load(fh)
        assert summary["invariant_failures"] == [], f"{zone}: {summary['invariant_failures']}"
        # and the per-day oracle bound really was checked on every day, not a sample
        for curve, block in summary["invariants"].items():
            dominance = block.get("same_start_oracle_dominates_every_day")
            if dominance:
                assert dominance["n_days_checked"] == summary["dispatched_days_per_curve"][curve]


# ---------------------------------------------------------------------------
# 6. the C6 cross-cycle reproduction check must be able to fail
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (RESULTS_DIR / "c6_curves_DE-LU_2024_summary.json").exists(),
    reason="needs C6's committed artefact",
)
def test_the_c6_reproduction_check_fails_when_a_number_moves():
    with (RESULTS_DIR / "c11_dispatch_DE-LU_2024_summary.json").open() as fh:
        pooled = json.load(fh)["pooled"]
    assert check_c6_reproduction("DE-LU", pooled)["holds"] is True

    nudged = {k: {s: dict(b) for s, b in v.items()} for k, v in pooled.items()}
    nudged["lear_full_history"]["common_hours"]["cash_eur"] += 0.01
    report = check_c6_reproduction("DE-LU", nudged)
    assert report["holds"] is False
    assert any(
        c["check"] == "model_pooled_cash_eur" and not c["holds"]
        for c in report["checks"]
    )


def test_the_c6_reproduction_check_is_scoped_to_the_zone_c6_ran():
    assert check_c6_reproduction("PL", {})["applicable"] is False
