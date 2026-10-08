"""C10 tests: the append-only results store, and the scale-out's ingest guards.

Offline. No network, no cached price file, no sealed year. Every test here runs
against a temporary store in ``tmp_path``, so the committed
``backtest/results/results.csv`` is never written by the suite.

The store's whole value is one promise — *an earlier cycle's number may be
superseded by a later row, never changed in place* — so most of these tests are
attempts to break that promise and watch it hold. The rest pin the provenance
PLAN.md C10 requires on every row (git SHA, config hash) plus the library
fingerprint the C9 entry asked for, and the ``vintage`` label that keeps
FINDING C9-C's late-arm numbers from being read as achievable.

Note on what is *not* pinned here: the column list. Long format makes the metric
name the extension point, so C11's capture ratios and C12's spread/Spearman/CI
metrics need no schema change and no edit to this file — which matters, because
CLAUDE.md makes editing a test a flag-and-stop event and a schema frozen by test
would turn a routine later cycle into a blocked one. What *is* asserted is that
the required provenance columns exist and that a header change is refused rather
than silently migrated.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from backtest import results_store as rs
from backtest.results_store import ResultRow, ResultsStoreError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def a_row(**overrides) -> ResultRow:
    """A minimal valid measurement row. Overridden per test."""
    base = dict(
        zone="DE-LU",
        tier="A",
        model="lear",
        metric="mae",
        value=23.525,
        scope="own_coverage",
        vintage="honest",
        evaluation_years="2024",
        exog_variant="price_only",
        train_from="2022-01-01",
        n="8784",
        n_scored="8783",
    )
    base.update(overrides)
    return ResultRow(**base)


def store(tmp_path):
    return tmp_path / "results.csv", tmp_path / "results_runs.json"


def append(tmp_path, rows, cycle="C10", git_sha="deadbeef", config_hash="cfg0123456789ab",
           now=None):
    results, runs = store(tmp_path)
    return rs.append_rows(
        rows, cycle=cycle, git_sha=git_sha, config_hash=config_hash,
        path=results, runs_path=runs, now=now,
    )


# ---------------------------------------------------------------------------
# Provenance — PLAN.md C10's actual requirement
# ---------------------------------------------------------------------------


def test_plan_md_s_required_provenance_columns_are_in_the_schema():
    """PLAN.md C10: "each row tagged with git SHA + config hash"."""
    for column in ("git_sha", "config_hash"):
        assert column in rs.SCHEMA
    # The C9 entry's closing suggestion: the GBM fingerprint pins what we set,
    # not what the installed LightGBM defaults to.
    assert "library_fingerprint" in rs.SCHEMA


def test_every_appended_row_carries_the_run_s_provenance(tmp_path):
    report = append(tmp_path, [a_row(), a_row(model="gbm", value=22.787)])
    frame = rs.read_results(store(tmp_path)[0])
    assert len(frame) == 2
    assert set(frame["git_sha"]) == {"deadbeef"}
    assert set(frame["config_hash"]) == {"cfg0123456789ab"}
    assert set(frame["run_id"]) == {report.run_id}
    assert set(frame["cycle"]) == {"C10"}
    assert frame["library_fingerprint"].nunique() == 1
    assert len(frame["library_fingerprint"].iloc[0]) == 16


def test_a_caller_cannot_forge_the_provenance_of_a_row(tmp_path):
    """Whatever a row claims, the store stamps its own run's provenance on it."""
    append(tmp_path, [a_row(git_sha="not-the-real-sha", run_id="handwritten")])
    frame = rs.read_results(store(tmp_path)[0])
    assert frame["git_sha"].iloc[0] == "deadbeef"
    assert frame["run_id"].iloc[0] != "handwritten"


def test_the_library_versions_recorded_include_the_ones_that_can_move_a_number():
    versions = rs.library_versions()
    assert "python" in versions
    for name in rs.TRACKED_LIBRARIES:
        assert name in versions, f"{name} is untracked, so a version bump would be invisible"


def test_an_absent_library_is_recorded_as_absent_not_omitted():
    """An omitted key would silently change the fingerprint's meaning."""
    versions = dict(rs.library_versions())
    assert all(v for v in versions.values())
    assert rs.library_fingerprint(versions) == rs.library_fingerprint(versions)
    moved = dict(versions)
    moved["lightgbm"] = "absent"
    assert rs.library_fingerprint(moved) != rs.library_fingerprint(versions)


def test_the_library_fingerprint_moves_when_any_tracked_version_moves():
    base = rs.library_versions()
    for name in base:
        bumped = dict(base)
        bumped[name] = bumped[name] + ".999"
        assert rs.library_fingerprint(bumped) != rs.library_fingerprint(base), name


def test_the_run_manifest_keeps_the_full_version_dict_not_just_the_hash(tmp_path):
    append(tmp_path, [a_row()])
    manifest = json.loads(store(tmp_path)[1].read_text(encoding="utf-8"))
    run = manifest["runs"][-1]
    assert run["libraries"]["python"]
    assert set(rs.TRACKED_LIBRARIES) <= set(run["libraries"])


# ---------------------------------------------------------------------------
# Append-only — the one promise
# ---------------------------------------------------------------------------


def test_appending_leaves_every_earlier_byte_untouched(tmp_path):
    results, _ = store(tmp_path)
    append(tmp_path, [a_row()])
    first = results.read_bytes()
    append(tmp_path, [a_row(value=23.6)])
    second = results.read_bytes()
    assert second.startswith(first)
    assert len(second) > len(first)


def test_a_later_run_supersedes_rather_than_overwrites(tmp_path):
    """Both values survive; ``latest_results`` picks the newer one."""
    t0 = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.timezone.utc)
    append(tmp_path, [a_row(value=23.5)], now=t0)
    append(tmp_path, [a_row(value=99.0)], now=t0 + dt.timedelta(hours=1))
    frame = rs.read_results(store(tmp_path)[0])
    assert sorted(frame["value"]) == [23.5, 99.0]
    latest = rs.latest_results(frame)
    assert len(latest) == 1
    assert latest["value"].iloc[0] == 99.0


def test_verify_append_only_passes_on_an_honestly_grown_store(tmp_path):
    results, runs = store(tmp_path)
    t0 = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.timezone.utc)
    for i in range(3):
        append(tmp_path, [a_row(value=20.0 + i)], now=t0 + dt.timedelta(hours=i))
    report = rs.verify_append_only(results, runs)
    assert report["verified"] is True
    assert report["n_runs"] == 3
    assert report["n_rows"] == 3


def test_verify_append_only_catches_an_edited_earlier_row(tmp_path):
    """The failure mode the store exists to prevent: a number changed in place."""
    results, runs = store(tmp_path)
    t0 = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.timezone.utc)
    append(tmp_path, [a_row(value=23.525)], now=t0)
    append(tmp_path, [a_row(zone="ES", value=18.126)], now=t0 + dt.timedelta(hours=1))
    text = results.read_text(encoding="utf-8")
    results.write_text(text.replace("23.525", "11.111"), encoding="utf-8")
    with pytest.raises(ResultsStoreError, match="has been edited"):
        rs.verify_append_only(results, runs)


def test_verify_append_only_catches_a_deleted_row(tmp_path):
    results, runs = store(tmp_path)
    t0 = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.timezone.utc)
    append(tmp_path, [a_row(), a_row(zone="ES")], now=t0)
    append(tmp_path, [a_row(zone="NO2")], now=t0 + dt.timedelta(hours=1))
    lines = results.read_text(encoding="utf-8").splitlines(keepends=True)
    results.write_text("".join(lines[:1] + lines[2:]), encoding="utf-8")
    with pytest.raises(ResultsStoreError):
        rs.verify_append_only(results, runs)


def test_verify_append_only_catches_rows_appended_without_a_manifest_entry(tmp_path):
    """A hand-appended row has no provenance, so the chain must refuse it."""
    results, runs = store(tmp_path)
    append(tmp_path, [a_row()])
    with results.open("a", encoding="utf-8") as fh:
        fh.write("," * (len(rs.SCHEMA) - 1) + "\n")
    with pytest.raises(ResultsStoreError, match="without a manifest entry"):
        rs.verify_append_only(results, runs)


def test_a_header_change_is_refused_as_a_migration_not_accepted_silently(tmp_path):
    results, _ = store(tmp_path)
    append(tmp_path, [a_row()])
    lines = results.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = lines[0].replace("config_hash", "cfg_hash")
    results.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(ResultsStoreError, match="migration"):
        append(tmp_path, [a_row(value=1.0)])


def test_the_run_manifest_records_the_row_count_before_and_after(tmp_path):
    first = append(tmp_path, [a_row(), a_row(zone="ES")])
    second = append(tmp_path, [a_row(zone="NO2")])
    assert (first.n_rows_before, first.n_rows_after) == (0, 2)
    assert (second.n_rows_before, second.n_rows_after) == (2, 3)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_row_missing_required_provenance_is_refused(tmp_path):
    with pytest.raises(ResultsStoreError, match="missing"):
        append(tmp_path, [a_row(evaluation_years="")])


def test_a_nan_value_is_refused(tmp_path):
    with pytest.raises(ResultsStoreError, match="NaN"):
        append(tmp_path, [a_row(value=float("nan"))])


def test_a_duplicate_measurement_within_one_run_is_refused(tmp_path):
    with pytest.raises(ResultsStoreError, match="repeats"):
        append(tmp_path, [a_row(value=1.0), a_row(value=2.0)])


def test_rows_that_differ_in_any_key_are_not_duplicates(tmp_path):
    report = append(tmp_path, [
        a_row(),
        a_row(scope="common_hours"),
        a_row(model="gbm"),
        a_row(exog_variant="load_only"),
        a_row(train_from="2019-01-01"),
        a_row(metric="rmse", value=37.4),
        a_row(zone="ES"),
    ])
    assert report.n_rows_appended == 7


def test_an_unlabelled_vintage_is_refused(tmp_path):
    with pytest.raises(ResultsStoreError, match="vintage"):
        append(tmp_path, [a_row(vintage="maybe")])


def test_an_unknown_scope_is_refused(tmp_path):
    with pytest.raises(ResultsStoreError, match="scope"):
        append(tmp_path, [a_row(scope="whatever")])


@pytest.mark.parametrize("metric", ["MAE", "mae!", "x", "mae ", "2mae"])
def test_a_metric_name_that_is_not_snake_case_is_refused(tmp_path, metric):
    with pytest.raises(ResultsStoreError, match="snake_case"):
        append(tmp_path, [a_row(metric=metric)])


@pytest.mark.parametrize(
    "metric",
    ["mae", "rmse", "bias", "coverage", "rmae_vs_naive", "capture_ratio",
     "daily_spread_mae", "within_day_spearman", "eur_per_mw_per_year",
     "capture_ratio_ci_low"],
)
def test_the_metrics_c11_and_c12_will_write_need_no_schema_change(tmp_path, metric):
    """The long format's point: a new metric is a new value, not a new column."""
    report = append(tmp_path, [a_row(metric=metric, value=0.9187)])
    assert report.n_rows_appended == 1


# ---------------------------------------------------------------------------
# The sealed holdout
# ---------------------------------------------------------------------------


def test_a_metric_against_the_sealed_year_cannot_be_written(tmp_path):
    from data.holdout import SealedHoldoutError

    with pytest.raises(SealedHoldoutError):
        append(tmp_path, [a_row(evaluation_years="2025")])


def test_a_sealed_year_hidden_in_a_multi_year_spelling_is_still_caught(tmp_path):
    from data.holdout import SealedHoldoutError

    with pytest.raises(SealedHoldoutError):
        append(tmp_path, [a_row(evaluation_years="2024-2025")])


def test_an_evaluation_years_spelling_the_guard_cannot_read_is_refused(tmp_path):
    """Better to refuse an unparseable label than to let the guard see no year."""
    with pytest.raises(ResultsStoreError, match="four-digit year"):
        append(tmp_path, [a_row(evaluation_years="validation")])


def test_nothing_is_written_when_a_row_is_refused(tmp_path):
    results, runs = store(tmp_path)
    from data.holdout import SealedHoldoutError

    with pytest.raises(SealedHoldoutError):
        append(tmp_path, [a_row(), a_row(zone="ES", evaluation_years="2025")])
    assert not results.exists()
    assert not runs.exists()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_honest_rows_drops_the_late_vintage_arm():
    frame = pd.DataFrame(
        {
            "vintage": ["honest", "after_gate_closure", "honest"],
            "value": [1.0, 2.0, 3.0],
            "metric": ["mae"] * 3,
        }
    )
    kept = rs.honest_rows(frame)
    assert list(kept["value"]) == [1.0, 3.0]


def test_reading_an_absent_store_gives_an_empty_frame_with_the_schema(tmp_path):
    frame = rs.read_results(tmp_path / "nothing.csv")
    assert frame.empty
    assert list(frame.columns) == list(rs.SCHEMA)


def test_latest_results_keeps_one_row_per_measurement_across_many_runs(tmp_path):
    t0 = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.timezone.utc)
    append(tmp_path, [a_row(value=1.0), a_row(zone="ES", value=2.0)], now=t0)
    append(tmp_path, [a_row(value=10.0)], now=t0 + dt.timedelta(hours=1))
    latest = rs.latest_results(rs.read_results(store(tmp_path)[0]))
    assert len(latest) == 2
    by_zone = dict(zip(latest["zone"], latest["value"]))
    assert by_zone == {"DE-LU": 10.0, "ES": 2.0}


def test_pivot_metric_gives_a_zone_by_series_table(tmp_path):
    t0 = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.timezone.utc)
    rows = []
    for zone, naive, lear in (("DE-LU", 32.8, 23.5), ("ES", 27.0, 18.1)):
        rows.append(a_row(zone=zone, model="naive_last_week", exog_variant="",
                          scope="common_hours", value=naive))
        rows.append(a_row(zone=zone, model="lear", scope="common_hours", value=lear))
    append(tmp_path, rows, now=t0)
    table = rs.pivot_metric("mae", rs.read_results(store(tmp_path)[0]))
    assert set(table.columns) == {"naive_last_week", "lear_price_only"}
    assert table.loc["ES", "lear_price_only"] == 18.1


def test_rows_from_scores_turns_one_scores_dict_into_one_row_per_metric():
    from backtest.metrics import Scores

    scores = Scores(n=100, n_scored=99, n_missing_prediction=1, mae=1.5,
                    rmse=2.0, bias=-0.25).as_dict()
    rows = rs.rows_from_scores(
        scores, zone="FR", tier="B", model="lear",
        evaluation_years="2024", scope="own_coverage", vintage="honest",
    )
    assert [r.metric for r in rows] == ["mae", "rmse", "bias", "coverage"]
    assert [r.value for r in rows] == [1.5, 2.0, -0.25, pytest.approx(0.99)]
    assert all(r.n == "100" and r.n_scored == "99" for r in rows)


def test_a_run_id_says_which_cycle_wrote_it_and_sorts_by_time():
    early = rs.make_run_id("C10", dt.datetime(2026, 10, 8, 1, 0, tzinfo=dt.timezone.utc))
    late = rs.make_run_id("C10", dt.datetime(2026, 10, 8, 2, 0, tzinfo=dt.timezone.utc))
    assert early.startswith("C10-") and late.startswith("C10-")
    assert early < late
