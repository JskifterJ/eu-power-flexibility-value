"""C17's like-for-like reading of the holdout against the visible years.

A new test file for new code. Nothing here edits an existing test.

The module re-aggregates committed per-day rows, so the tests that matter are
about whether the re-aggregation is the same definition the published numbers
use, and whether the seasonal correction it exists for is actually applied:

1. **It reproduces the published capture exactly** on the full-window basis.
   If this drifts, every comparison the write-up makes is between two different
   definitions of capture and the correction is noise.
2. **The like-for-like basis really is cut at the holdout's last month**, and
   holds strictly fewer days for a full visible year than the full basis does.
3. **It writes no result rows**, the same property C20's gate and C17's figure
   module are held to.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from backtest import run_c17_holdout as c17
from backtest import run_c17_summary as summary
from backtest.results_store import RESULTS_DIR


def _table():
    try:
        return summary.like_for_like()
    except summary.SummaryError as exc:
        pytest.skip(f"the per-day artefacts are not all present here: {exc}")


# ---------------------------------------------------------------------------
# It produces no result rows
# ---------------------------------------------------------------------------


def test_the_summary_module_cannot_write_to_the_results_store():
    source = Path(inspect.getfile(summary)).read_text(encoding="utf-8")
    for forbidden in ("append_rows", "ResultRow", "rows_from_scores"):
        assert forbidden not in source, (
            f"{forbidden} appears in the summary module: a reading of the "
            f"holdout must not be able to append a number to the store"
        )


# ---------------------------------------------------------------------------
# It is the same capture the store published
# ---------------------------------------------------------------------------


def test_the_full_window_basis_reproduces_the_published_capture():
    """The re-aggregation is checked against the committed numbers, not trusted.

    Tolerance is 1e-9: this is the same arithmetic over the same rows, so
    anything above floating-point noise means the definition has drifted.
    """
    import pandas as pd

    table = _table()
    metrics_path = RESULTS_DIR / "c17_holdout_2025_metrics.csv"
    if not metrics_path.exists():
        pytest.skip("the holdout has not been evaluated in this working tree")
    published = pd.read_csv(metrics_path)
    published = published[
        (published["curve"] == summary.COMPARABLE_CURVE)
        & (published["scope"] == "common_hours")
    ].set_index("zone")
    mine = table[
        (table["basis"] == "full_window") & (table["year"] == summary.HOLDOUT_YEAR)
    ].set_index("zone")
    assert set(mine.index) == set(published.index)
    for zone in published.index:
        assert mine.loc[zone, "capture"] == pytest.approx(
            float(published.loc[zone, "capture_rolled_oracle_cash"]), abs=1e-9
        ), zone


def test_the_holdout_rows_cover_the_preregistered_window():
    table = _table()
    held = table[
        (table["basis"] == "full_window") & (table["year"] == summary.HOLDOUT_YEAR)
    ]
    if held.empty:
        pytest.skip("the holdout has not been evaluated in this working tree")
    assert set(held["n_days"]) == {c17.EXPECTED_MARKET_DAYS}


# ---------------------------------------------------------------------------
# The seasonal correction is actually applied
# ---------------------------------------------------------------------------


def test_the_like_for_like_basis_is_cut_at_the_holdouts_last_month():
    assert summary.LAST_MONTH == c17.LAST_MARKET_DAY.month


def test_a_full_visible_year_loses_days_on_the_like_for_like_basis():
    table = _table()
    full = table[(table["basis"] == "full_window") & (table["year"] == 2024)]
    cut = table[(table["basis"] == "jan_sep_only") & (table["year"] == 2024)]
    if full.empty or cut.empty:
        pytest.skip("2024 is not in the committed per-day frame here")
    merged = full.merge(cut, on="zone", suffixes=("_full", "_cut"))
    assert (merged["n_days_cut"] < merged["n_days_full"]).all()
    # The basis matches *calendar months*, not day counts: January-September of
    # the leap year 2024 is 274 days against the holdout's 273, and a zone that
    # lost a day from the common day set has one fewer again. Asserting equality
    # with 273 would be asserting that 2024 was not a leap year.
    assert merged["n_days_cut"].between(
        c17.EXPECTED_MARKET_DAYS - 2, c17.EXPECTED_MARKET_DAYS + 1
    ).all(), merged[["zone", "n_days_full", "n_days_cut"]].to_string()


def test_the_holdout_is_unchanged_by_the_cut_because_it_already_ends_in_september():
    table = _table()
    held_full = table[
        (table["basis"] == "full_window") & (table["year"] == summary.HOLDOUT_YEAR)
    ].set_index("zone")
    held_cut = table[
        (table["basis"] == "jan_sep_only") & (table["year"] == summary.HOLDOUT_YEAR)
    ].set_index("zone")
    if held_full.empty:
        pytest.skip("the holdout has not been evaluated in this working tree")
    for zone in held_full.index:
        assert held_cut.loc[zone, "capture"] == pytest.approx(
            held_full.loc[zone, "capture"], abs=1e-12
        )


# ---------------------------------------------------------------------------
# The summary says what the table says
# ---------------------------------------------------------------------------


def test_the_summary_counts_agree_with_the_table_it_was_built_from():
    table = _table()
    try:
        payload = summary.build_summary(table)
    except (summary.SummaryError, FileNotFoundError) as exc:
        pytest.skip(f"the holdout has not been evaluated here: {exc}")
    for basis, key in (("full_window", "full_window_basis"),
                       ("jan_sep_only", "jan_sep_like_for_like_basis")):
        block = payload["against_the_visible_years"][key]
        recount = sum(
            1 for v in summary._verdicts(table, basis).values()
            if v["verdict"] == "above_every_visible_year"
        )
        assert block["n_zones_above_every_visible_year"] == recount


def test_the_committed_summary_states_the_holdout_is_in_the_store():
    path = RESULTS_DIR / summary.SUMMARY.name
    if not path.exists():
        pytest.skip("the summary has not been produced in this working tree")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["store"]["holdout_year_present"] is True
    assert payload["writes_no_result_rows"] is True
