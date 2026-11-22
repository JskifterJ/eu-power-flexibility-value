"""C17 — the evaluation phase: the run the pre-registration specifies.

``tests/test_c17_preflight.py`` covers the preflight's reasoning. This file
covers the machinery that spends the holdout, and it is written around one
question: *what could go wrong once and never be recoverable?* The answer is
not "a metric is slightly off". It is:

* **the evaluation runs twice**, which makes the second one a number chosen
  after seeing the first;
* **the evaluation runs on part of the question** — three zones, or a window
  that silently includes the 15-minute segment — and is reported as the whole;
* **the evaluation runs in the wrong environment**, so its capture ratio is
  not comparable to the 2024 one it is read against;
* **a 2025 row lands in the store under a key that does not join** the 2020-2024
  rows, which would make every comparison the write-up wants to draw a
  comparison between two different things.

Each of those is a gate in :mod:`backtest.run_c17_holdout`, and each gate is
tested here by making it fail, not by watching it pass. Nothing here fits a
model, dispatches a battery or makes a network request: the expensive path is
exercised by the rehearsal run on the visible 2024 year, whose committed
artefacts the last two tests read.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from backtest import run_c11_dispatch as c11
from backtest import run_c13_regime as c13
from backtest import run_c17_holdout as c17
from data.config import load_zones


@pytest.fixture(scope="module")
def prereg() -> dict:
    return c17.load_preregistration()


@pytest.fixture()
def results_dir(tmp_path, monkeypatch):
    """A scratch results directory, so a test can never touch a committed file."""
    monkeypatch.setattr(c17, "RESULTS_DIR", tmp_path)
    return tmp_path


def _args(**kwargs) -> argparse.Namespace:
    base = dict(
        phase="evaluate", zones=None, year=c17.HOLDOUT_YEAR, out=None,
        refit_every=1, min_train_days=365, train_window_days=None,
        no_append=True, results_path=None,
    )
    base.update(kwargs)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# The pre-registered run is the run that happens
# ---------------------------------------------------------------------------


def test_the_walk_forward_defaults_are_the_preregistered_ones(prereg):
    """A CLI default that drifted would evaluate a model nobody registered."""
    args = c17.parse_args([])
    want = prereg["walk_forward"]
    assert args.refit_every == want["refit_every_days"]
    assert args.min_train_days == want["min_train_days"]
    assert args.train_window_days == want["train_window_days"]
    assert args.year == c17.HOLDOUT_YEAR


def test_the_dispatched_curves_are_the_preregistered_three(prereg):
    registered = set(prereg["curves"])
    assert registered == {c17.ORACLE_CURVE, c17.COMPARABLE_CURVE, c17.NAIVE_CURVE}
    # The oracle is not a forecast and is dispatched separately, so the arm
    # table holds the two forecast curves and nothing else.
    assert {arm[0] for arm in c17.C17_ARMS} == {c17.COMPARABLE_CURVE, c17.NAIVE_CURVE}


def test_the_store_key_is_c11s_taxonomy_so_a_2025_row_joins_a_2024_one():
    """A 2025 row under a different key would not be comparable to anything."""
    assert c17.STORE_KEY == c13.STORE_KEY
    assert c17.STORE_KEY[c17.ORACLE_CURVE] == (c11.ORACLE_MODEL, c11.ORACLE_VARIANT, "")
    assert c17.STORE_KEY[c17.COMPARABLE_CURVE] == (
        "lear", "price_only", c11.FULL_HISTORY_FROM,
    )


def test_the_per_day_columns_and_store_metrics_are_c13s_exactly():
    """C13's table builders read a C17 frame; one renamed column breaks that."""
    assert c17.DAILY_COLUMNS == c13.DAILY_COLUMNS
    assert c17.STORE_METRICS == c13.STORE_METRICS


def test_the_holdout_and_rehearsal_artefacts_can_never_collide():
    assert c17.run_tag(c17.HOLDOUT_YEAR) == "c17_holdout"
    assert c17.run_tag(c17.REHEARSAL_YEAR) == "c17_rehearsal"
    for builder in (
        c17.predictions_path, c17.daily_path, c17.dispatch_summary_path,
        c17.compute_summary_path,
    ):
        holdout = builder("DE-LU", c17.HOLDOUT_YEAR).name
        rehearsal = builder("DE-LU", c17.REHEARSAL_YEAR).name
        assert holdout != rehearsal
        assert holdout.startswith("c17_holdout_")
        assert rehearsal.startswith("c17_rehearsal_")


# ---------------------------------------------------------------------------
# The window: hourly, and over before the SDAC cutover
# ---------------------------------------------------------------------------


def _mixed_resolution_series() -> pd.Series:
    """Hourly up to the cutover, then 15-minute — the real 2025 price file."""
    hourly = pd.date_range("2025-09-30T00:00Z", "2025-09-30T21:00:00Z", freq="h")
    quarter = pd.date_range("2025-09-30T22:00:00Z", "2025-10-01T02:00:00Z", freq="15min")
    index = hourly.append(quarter)
    series = pd.Series(np.arange(len(index), dtype=float), index=index)
    series.attrs = {"stitch_report": None}
    return series


def test_the_cutover_truncation_keeps_every_hourly_row_and_no_quarter_hour():
    kept = c17.hourly_through_cutover(_mixed_resolution_series(), "DE-LU")
    assert len(kept) == 22
    assert pd.DatetimeIndex(kept.index).max() < c17.CUTOVER_UTC
    # The truncation happens before the feature build, so no 15-minute row can
    # reach a lag, a rolling mean or a target.
    deltas = pd.DatetimeIndex(kept.index).to_series().diff().dropna().unique()
    assert list(deltas) == [pd.Timedelta(hours=1)]


def test_a_non_hourly_row_inside_the_window_is_a_flag_not_a_resample():
    """The pre-registration asserts resolution_seconds == 3600 on every
    evaluated row. A 15-minute segment *before* the cutover would mean the
    cutover is not where PLAN.md says it is, which is a finding, not something
    to aggregate away."""
    index = pd.date_range("2025-03-01T00:00Z", periods=8, freq="15min")
    series = pd.Series(np.arange(8, dtype=float), index=index)
    series.attrs = {}
    with pytest.raises(c17.HoldoutRunError, match="not hourly"):
        c17.hourly_through_cutover(series, "DE-LU")


def test_the_holdout_window_must_be_the_preregistered_273_days(monkeypatch):
    """Fail-ability: a window of a different length is refused, not evaluated."""
    monkeypatch.setattr(
        c17, "evaluation_days",
        lambda matrix, years: [dt.date(2025, 1, 1), dt.date(2025, 1, 2)],
    )
    monkeypatch.setattr(c17, "load_zone_series", lambda zone: _mixed_resolution_series())
    monkeypatch.setattr(c17, "build_features", lambda prices, zone: object())
    with pytest.raises(c17.HoldoutRunError, match="not the pre-registered 273"):
        c17.window_for("DE-LU", c17.HOLDOUT_YEAR)


def test_assembling_a_day_after_the_cutover_is_refused(results_dir):
    frame = pd.DataFrame(
        {
            "zone": ["DE-LU"],
            "curve": [c17.ORACLE_CURVE],
            "market_day": ["2025-10-02"],
            "cash": [1.0],
        }
    )
    frame.to_csv(c17.daily_path("DE-LU", c17.HOLDOUT_YEAR), index=False)
    with pytest.raises(c17.HoldoutRunError, match="on or after the SDAC cutover"):
        c17.assemble_daily(["DE-LU"], c17.HOLDOUT_YEAR)


def test_assembling_a_foreign_year_is_refused(results_dir):
    frame = pd.DataFrame(
        {
            "zone": ["DE-LU"],
            "curve": [c17.ORACLE_CURVE],
            "market_day": ["2024-05-02"],
            "cash": [1.0],
        }
    )
    frame.to_csv(c17.daily_path("DE-LU", c17.HOLDOUT_YEAR), index=False)
    with pytest.raises(c17.HoldoutRunError, match="not only 2025"):
        c17.assemble_daily(["DE-LU"], c17.HOLDOUT_YEAR)


# ---------------------------------------------------------------------------
# It runs once
# ---------------------------------------------------------------------------


def test_a_completed_holdout_entry_refuses_a_second_evaluation(results_dir, prereg):
    c17.write_ledger(
        {
            "cycle": "C17",
            "evaluations": [
                {
                    "year": c17.HOLDOUT_YEAR,
                    "status": "completed",
                    "finished_at_utc": "2026-11-22T12:00:00+00:00",
                    "git_sha": "deadbee",
                }
            ],
        }
    )
    with pytest.raises(c17.HoldoutRunError, match="SECOND evaluation"):
        c17.open_ledger_entry(c17.HOLDOUT_YEAR, prereg)


def test_there_is_no_flag_that_overrides_the_once_only_ledger():
    """A bypass an unattended cycle could reach is not a safeguard."""
    args = vars(c17.parse_args([]))
    assert not any(
        "second" in name or "force" in name or "again" in name for name in args
    )


def test_an_interrupted_evaluation_resumes_rather_than_restarting(results_dir, prereg):
    """A crash between phases must not become either a silent restart or a
    permanent block: the entry stays open, the resume is stamped, and the
    phases already finished are recorded."""
    c17.write_ledger(
        {
            "cycle": "C17",
            "evaluations": [
                {
                    "year": c17.HOLDOUT_YEAR,
                    "status": "in_progress",
                    "started_at_utc": "2026-11-22T10:00:00+00:00",
                    "phases_completed": ["compute"],
                    "resumptions": [],
                }
            ],
        }
    )
    _, entry = c17.open_ledger_entry(c17.HOLDOUT_YEAR, prereg)
    assert entry["status"] == "in_progress"
    assert entry["phases_completed"] == ["compute"]
    assert len(entry["resumptions"]) == 1
    assert entry["resumptions"][0]["phases_already_completed"] == ["compute"]


def test_a_completed_rehearsal_does_not_block_another_rehearsal(results_dir, prereg):
    c17.write_ledger(
        {
            "cycle": "C17",
            "evaluations": [
                {"year": c17.REHEARSAL_YEAR, "status": "completed",
                 "finished_at_utc": "2026-11-22T10:00:00+00:00"}
            ],
        }
    )
    _, entry = c17.open_ledger_entry(c17.REHEARSAL_YEAR, prereg)
    assert entry["status"] == "in_progress"
    assert entry["is_the_sealed_holdout"] is False


def test_the_ledger_records_the_environment_the_numbers_were_made_in(results_dir, prereg):
    _, entry = c17.open_ledger_entry(c17.HOLDOUT_YEAR, prereg)
    assert entry["library_fingerprint"]
    assert entry["library_versions"]["python"]
    assert entry["preregistration_git_sha"] == prereg["git_sha"]
    assert entry["is_the_sealed_holdout"] is True


# ---------------------------------------------------------------------------
# It runs whole, and in the registered environment
# ---------------------------------------------------------------------------


def test_the_holdout_may_not_be_narrowed_to_a_few_zones():
    """Spending the once-only evaluation on three zones answers a third of the
    question and cannot be undone.

    No scratch results directory here on purpose: the refusal has to come
    *before* the gate and before any artefact is written, so it must fire with
    the committed pre-registration in place."""
    with pytest.raises(c17.HoldoutRunError, match="whole or not at all"):
        c17.evaluate(_args(zones=["DE-LU", "ES"], year=c17.HOLDOUT_YEAR))


def test_a_standing_blocker_stops_the_holdout_evaluation(monkeypatch, prereg):
    monkeypatch.setattr(
        c17, "collect_preflight",
        lambda prereg, zones, verbose=True: {
            "blockers_standing": ["library_fingerprint_moved"],
            "provenance": {"library_fingerprint_live": "x", "config_hash_live": "y"},
        },
    )
    with pytest.raises(c17.HoldoutRunError, match="library_fingerprint_moved"):
        c17.evaluation_gate(prereg, c17.HOLDOUT_YEAR, list(load_zones()))


def test_the_same_blocker_does_not_stop_a_rehearsal(monkeypatch, prereg):
    """The rehearsal exists to exercise this code in whatever container is at
    hand; it writes nothing to the store, so the comparability gate is not its
    gate."""
    monkeypatch.setattr(
        c17, "collect_preflight",
        lambda prereg, zones, verbose=True: {
            "blockers_standing": ["library_fingerprint_moved"],
            "provenance": {"library_fingerprint_live": "x", "config_hash_live": "y"},
        },
    )
    report = c17.evaluation_gate(prereg, c17.REHEARSAL_YEAR, list(load_zones()))
    assert report["gated"] is False


def test_the_gate_is_the_preflights_own_conjunction(prereg):
    """Not a second copy of it: the evaluation must be gated on exactly what
    the preflight reports, including the library fingerprint."""
    seen: dict = {}

    def fake(prereg_arg, zones, verbose=True):
        seen["called"] = True
        return {"blockers_standing": [],
                "provenance": {"library_fingerprint_live": "f", "config_hash_live": "c"}}

    import backtest.run_c17_holdout as module
    original = module.collect_preflight
    module.collect_preflight = fake
    try:
        module.evaluation_gate(prereg, c17.HOLDOUT_YEAR, list(load_zones()))
    finally:
        module.collect_preflight = original
    assert seen.get("called")


def test_the_library_fingerprint_is_one_of_the_gated_blockers():
    """Pins the conjunction itself: a later edit that dropped this key would
    let a 2025 number be produced under libraries no 2024 number used."""
    source = (c17.__file__)
    text = open(source, encoding="utf-8").read()
    assert '"library_fingerprint_moved": not prov["library_fingerprint_matches"]' in text


# ---------------------------------------------------------------------------
# Commit-then-settle and the realised-price check
# ---------------------------------------------------------------------------


def test_a_prediction_artefact_that_disagrees_with_the_price_cache_is_refused(
    results_dir,
):
    """An off-by-one index is a leak that looks like skill; the per-day oracle
    bound would only catch it afterwards."""
    index = pd.date_range("2025-03-01T00:00Z", periods=4, freq="h")
    frame = pd.DataFrame(
        {
            "timestamp_utc": index,
            "market_day": ["2025-03-01"] * 4,
            "y_true": [10.0, 11.0, 12.0, 13.0],
            c17.LEAR_COLUMN: [10.0, 11.0, 12.0, 13.0],
            c17.NAIVE_COLUMN: [10.0, 11.0, 12.0, 13.0],
        }
    )
    frame.to_csv(c17.predictions_path("DE-LU", c17.HOLDOUT_YEAR), index=False)
    realised = pd.Series([10.0, 11.0, 12.0, 99.0], index=index)
    with pytest.raises(c17.HoldoutRunError, match="is not what was scored"):
        c17.load_prediction_frame("DE-LU", c17.HOLDOUT_YEAR, realised)


def test_a_prediction_hour_with_no_realised_price_is_refused(results_dir):
    index = pd.date_range("2025-03-01T00:00Z", periods=4, freq="h")
    frame = pd.DataFrame(
        {
            "timestamp_utc": index,
            "market_day": ["2025-03-01"] * 4,
            "y_true": [10.0, 11.0, 12.0, 13.0],
            c17.LEAR_COLUMN: [10.0, 11.0, 12.0, 13.0],
            c17.NAIVE_COLUMN: [10.0, 11.0, 12.0, 13.0],
        }
    )
    frame.to_csv(c17.predictions_path("DE-LU", c17.HOLDOUT_YEAR), index=False)
    realised = pd.Series([10.0, 11.0, 12.0], index=index[:3])
    with pytest.raises(c17.HoldoutRunError, match="no realised price"):
        c17.load_prediction_frame("DE-LU", c17.HOLDOUT_YEAR, realised)


# ---------------------------------------------------------------------------
# The store rows
# ---------------------------------------------------------------------------


def _point_row(**kwargs) -> dict:
    row = {
        "zone": "DE-LU", "curve": c17.COMPARABLE_CURVE, "scope": "common_hours",
        "tier": "A", "regime": "thermal-RES-mixed", "n_days": 273, "n_hours": 6550,
        "capture_rolled_oracle_cash": 0.9, "dispatch_cash_eur": 1234.5,
        "dispatch_cash_eur_per_mw_year": 50000.0,
        "eur_per_mw_year_lost_vs_oracle": 5000.0,
        "mae_on_dispatched_hours": 20.0,
    }
    row.update(kwargs)
    return row


def test_store_rows_tag_every_value_with_the_evaluation_year_and_cycle():
    points = pd.DataFrame([_point_row()])
    intervals = pd.DataFrame(
        [
            {"zone": "DE-LU", "year": 2025, "curve": c17.COMPARABLE_CURVE,
             "metric": "capture_rolled_oracle_cash", "block_days": c13.HEADLINE_BLOCK,
             "ci_low": 0.88, "ci_high": 0.92, "boot_sd": 0.01},
        ]
    )
    rows = c17.store_rows(points, intervals, 2025)
    assert rows, "no rows produced"
    assert {r.evaluation_years for r in rows} == {"2025"}
    assert {r.source_cycle for r in rows} == {"C17"}
    assert {r.model for r in rows} == {"lear"}
    assert {r.train_from for r in rows} == {c11.FULL_HISTORY_FROM}
    assert {r.vintage for r in rows} == {"honest"}
    names = {r.metric for r in rows}
    assert "capture_rolled_oracle_cash" in names
    assert "capture_rolled_oracle_cash_ci_low" in names
    assert "capture_rolled_oracle_cash_boot_sd" in names


def test_interval_bounds_are_only_written_at_the_common_hours_basis():
    """``own_coverage`` and ``common_hours`` are different day sets; an interval
    drawn on one must not be filed against the other."""
    points = pd.DataFrame([_point_row(scope="own_coverage")])
    intervals = pd.DataFrame(
        [
            {"zone": "DE-LU", "year": 2025, "curve": c17.COMPARABLE_CURVE,
             "metric": "capture_rolled_oracle_cash", "block_days": c13.HEADLINE_BLOCK,
             "ci_low": 0.88, "ci_high": 0.92, "boot_sd": 0.01},
        ]
    )
    rows = c17.store_rows(points, intervals, 2025)
    assert rows
    assert not any(r.metric.endswith("_ci_low") for r in rows)


def test_an_unknown_curve_cannot_reach_the_store():
    points = pd.DataFrame([_point_row(curve="something_new")])
    with pytest.raises(c17.HoldoutRunError, match="no store key"):
        c17.store_rows(points, pd.DataFrame(columns=["block_days"]), 2025)


def test_the_rehearsal_year_appends_nothing(results_dir, capsys):
    points = pd.DataFrame([_point_row()])
    points.to_csv(c17.metrics_path(c17.REHEARSAL_YEAR), index=False)
    pd.DataFrame(
        columns=["zone", "year", "curve", "metric", "block_days", "ci_low",
                 "ci_high", "boot_sd"]
    ).to_csv(c17.intervals_path(c17.REHEARSAL_YEAR), index=False)
    rc = c17.ingest(_args(year=c17.REHEARSAL_YEAR, no_append=False))
    assert rc == 0
    assert "nothing is appended" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The 2024 comparison comes from the sealed-era pre-registration
# ---------------------------------------------------------------------------


def test_the_baseline_is_the_committed_preregistered_one(prereg):
    """Not a number chosen after seeing the holdout: the baseline was written
    and committed while 2025 was still sealed."""
    points = pd.DataFrame([_point_row(capture_rolled_oracle_cash=0.5)])
    table = c17.baseline_comparison(points, prereg)
    row = table[table["metric"] == "capture_rolled_oracle_cash"].iloc[0]
    assert row["preregistered_2024"] == pytest.approx(
        prereg["baseline_2024_for_comparison"]["DE-LU"]["capture_rolled_oracle_cash"]
    )
    assert row["holdout_2025"] == pytest.approx(0.5)
    assert row["delta"] == pytest.approx(
        0.5 - prereg["baseline_2024_for_comparison"]["DE-LU"]["capture_rolled_oracle_cash"]
    )


def test_a_doctored_baseline_changes_the_comparison(prereg):
    """Fail-ability for the test above."""
    doctored = copy.deepcopy(prereg)
    doctored["baseline_2024_for_comparison"]["DE-LU"]["capture_rolled_oracle_cash"] = 0.1
    table = c17.baseline_comparison(pd.DataFrame([_point_row()]), doctored)
    row = table[table["metric"] == "capture_rolled_oracle_cash"].iloc[0]
    assert row["preregistered_2024"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# The post-unseal state of the download record
# ---------------------------------------------------------------------------


def test_the_real_download_record_now_refuses_because_2025_was_fetched():
    """The other half of ``tests/test_c16_checkpoint.py``'s two manifest-scan
    tests, which were moved onto a controlled directory when C17's 2025 pull
    filled the real one.

    C16's scan exists to prove a sealed year was *not* fetched. 2025 has now
    been fetched, under the human's approval, so on the real tree the scan must
    refuse — and it must refuse by naming the thing it found, not by going
    quiet. Skipped where ``data/raw/`` is absent, which is most containers:
    it is gitignored and does not survive one.
    """
    from pathlib import Path

    from backtest import run_c16_checkpoint as c16
    from data.config import REPO_ROOT

    if not (Path(REPO_ROOT) / "data" / "raw").exists():
        pytest.skip("data/raw/ is absent in this container (gitignored)")
    with pytest.raises(c16.CheckpointError) as caught:
        c16.manifest_scan()
    message = str(caught.value)
    assert "sealed year" in message
    assert "2025" in message


# ---------------------------------------------------------------------------
# The rehearsal's committed artefacts
# ---------------------------------------------------------------------------


def _rehearsal_report():
    path = c17.evaluation_report_path(c17.REHEARSAL_YEAR)
    if not path.exists():
        pytest.skip("the 2024 rehearsal has not been run in this working tree")
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_rehearsal_ran_on_the_visible_validation_year():
    report = _rehearsal_report()
    assert report["year"] == c17.REHEARSAL_YEAR
    assert report["is_the_sealed_holdout"] is False
    assert report["window"]["last_market_day"] < "2025-01-01"


def test_the_rehearsal_reproduces_the_published_2024_capture_ratios():
    """The strongest available check that this runner is the same experiment:
    its 2024 headline must land on the numbers C11/C12 published, which
    ``c16_preregistration.json`` recorded while the holdout was still sealed.

    The tolerance is 0.005 of a capture ratio, not equality: C11 dispatched a
    nine-curve Tier-A intersection and C17 dispatches a three-curve one, so the
    common-day basis is not always the identical day set (PROGRESS.md's
    ``scope`` note). A disagreement larger than that would mean the two runs
    are not the same experiment."""
    report = _rehearsal_report()
    baseline = c17.load_preregistration()["baseline_2024_for_comparison"]
    checked = 0
    for zone, metrics in report["headline"].items():
        want = baseline.get(zone)
        if not want:
            continue
        got = metrics["capture_rolled_oracle_cash"]
        assert got == pytest.approx(want["capture_rolled_oracle_cash"], abs=0.005), zone
        checked += 1
    assert checked >= 1
