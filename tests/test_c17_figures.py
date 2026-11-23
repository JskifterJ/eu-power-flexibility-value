"""C17's figure module: it must draw committed numbers and produce none.

A new test file for new code, which is every previous cycle's practice. Nothing
here edits an existing test.

The module is small, so the tests are about the two properties that matter and
cannot be seen by looking at a PNG:

1. **It computes no result.** No ``append_rows``, no ``ResultRow``, no write to
   the store. A figure phase that grew into a producer of result rows would be a
   quiet way to put an unreviewed number into ``results.csv``; C20's gate
   asserts the same thing about its own phases, statically, for the same reason.
2. **It draws the arm the holdout was evaluated on**, not a neighbouring one —
   the comparable LEAR at an honest vintage, which is the arm every cross-zone
   number in C10-C15 is built on and the one ``c16_preregistration.json`` names.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from backtest import run_c13_regime as c13
from backtest import run_c17_figures as figs
from backtest import run_c17_holdout as c17
from data.config import load_data_config


# ---------------------------------------------------------------------------
# It produces no result rows
# ---------------------------------------------------------------------------


def test_the_figure_module_cannot_write_to_the_results_store():
    source = Path(inspect.getfile(figs)).read_text(encoding="utf-8")
    for forbidden in ("append_rows", "ResultRow", "rows_from_scores"):
        assert forbidden not in source, (
            f"{forbidden} appears in the figure module: a figure phase must not "
            f"be able to append a number to the store"
        )


def test_the_figure_module_declares_that_it_writes_no_result_rows():
    assert "writes_no_result_rows" in inspect.getsource(figs.main)


# ---------------------------------------------------------------------------
# It draws the pre-registered arm, at the pre-registered block
# ---------------------------------------------------------------------------


def test_the_comparable_arm_is_c13s_and_the_preregistrations():
    prereg = c17.load_preregistration()
    headline = prereg["arms"]["headline_comparable"]
    assert figs.COMPARABLE_MODEL == headline["model"]
    assert figs.COMPARABLE_VARIANT == headline["exog_variant"]
    assert figs.COMPARABLE_TRAIN_FROM == headline["train_from"]


def test_the_headline_block_is_c13s():
    assert figs.HEADLINE_BLOCK == c13.HEADLINE_BLOCK


def test_the_outlier_zone_and_holdout_year_match_the_rest_of_the_project():
    assert figs.OUTLIER_ZONE == c13.OUTLIER_ZONE
    assert figs.HOLDOUT_YEAR == c17.HOLDOUT_YEAR


def test_every_figure_carries_the_attribution_declared_in_the_config():
    declared = load_data_config()["sources"]["energy_charts"]["attribution"]
    assert figs.ATTRIBUTION == declared
    source = inspect.getfile(figs)
    text = Path(source).read_text(encoding="utf-8")
    # One ``fig.text(... ATTRIBUTION ...)`` per figure function, so a figure
    # added later without one is visible in this count.
    assert text.count("fig.text(") == 3
    for name in ("plot_capture_by_year", "plot_holdout_vs_baseline",
                 "plot_headroom_out_of_sample"):
        body = inspect.getsource(getattr(figs, name))
        assert "ATTRIBUTION" in body, f"{name} draws no attribution"


# ---------------------------------------------------------------------------
# It refuses rather than inventing when the holdout has not been evaluated
# ---------------------------------------------------------------------------


def test_the_interval_reader_refuses_a_missing_holdout_interval_file(monkeypatch,
                                                                     tmp_path):
    monkeypatch.setattr(figs, "HOLDOUT_INTERVALS", tmp_path / "absent.csv")
    with pytest.raises(figs.FigureError) as excinfo:
        figs.holdout_interval("capture_rolled_oracle_cash")
    assert "analyse" in str(excinfo.value)


def test_an_empty_store_is_an_error_not_an_empty_figure(monkeypatch):
    import pandas as pd

    monkeypatch.setattr(figs, "honest_rows", lambda: pd.DataFrame())
    with pytest.raises(figs.FigureError):
        figs.comparable_cells("capture_rolled_oracle_cash")


def test_a_store_without_the_holdout_year_refuses_the_capture_figure(monkeypatch,
                                                                     tmp_path):
    import pandas as pd

    cells = pd.DataFrame(
        {"zone": ["DE-LU", "DE-LU"], "year": [2023, 2024], "value": [0.9, 0.92]}
    )
    monkeypatch.setattr(figs, "comparable_cells", lambda metric: cells)
    with pytest.raises(figs.FigureError) as excinfo:
        figs.plot_capture_by_year(tmp_path)
    assert "ingest" in str(excinfo.value)


# ---------------------------------------------------------------------------
# And, when the holdout has been evaluated, it draws
# ---------------------------------------------------------------------------


def test_the_three_figures_draw_from_what_is_committed(tmp_path):
    try:
        cells = figs.comparable_cells("capture_rolled_oracle_cash")
    except figs.FigureError as exc:  # pragma: no cover - depends on the tree
        pytest.skip(f"the store is not readable in this working tree: {exc}")
    if figs.HOLDOUT_YEAR not in set(cells["year"]):
        pytest.skip("the holdout has not been evaluated in this working tree")
    if not figs.HOLDOUT_INTERVALS.exists():
        pytest.skip("the holdout interval file is not present in this working tree")
    written = [
        figs.plot_capture_by_year(tmp_path),
        figs.plot_holdout_vs_baseline(tmp_path),
        figs.plot_headroom_out_of_sample(tmp_path),
    ]
    for path in written:
        assert path.exists() and path.stat().st_size > 10_000
