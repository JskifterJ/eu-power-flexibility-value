"""C10 tests: the scale-out's ingest guards and its row-labelling rules.

Offline. Nothing here reads a cached price file, fits a model or touches the
committed store; the artefact-reading paths are exercised against synthetic
artefacts written into ``tmp_path``.

The ingest phase's job is narrow and the ways it can go wrong are specific:

* it can write a number that disagrees with the artefact it cites — so
  :func:`backtest.run_c10_scale._check` is the thing that must fail loudly, and
  its tolerance must be the artefact's own ``%.4f`` precision and not a margin
  chosen to make a disagreement pass;
* it can silently realign two cycles' predictions onto each other, which would
  turn "C8 and C9 evaluated different hours" into an invisible comparison;
* it can let the Art. 14 ``res_as_published`` arm into the store without its
  ``vintage`` label, which FINDING C9-C makes the single most misleading thing
  this project could publish;
* it can build the nine-zone table out of rows that are not like-for-like — a
  Tier-A row trained from 2022 beside a Tier-B row trained from 2019.

Each of those has a test below.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backtest import run_c10_scale as scale
from backtest.run_c10_scale import ScaleError


# ---------------------------------------------------------------------------
# The recomputed-vs-committed cross-check
# ---------------------------------------------------------------------------


def test_the_cross_check_tolerance_is_the_artefact_s_own_precision():
    """The artefacts are written with ``%.4f``; the tolerance is that, not a margin."""
    assert scale.RECOMPUTE_TOLERANCE == pytest.approx(5e-4)


def test_a_recomputed_number_within_the_artefact_s_precision_passes():
    checks: list[dict] = []
    scale._check("lear_price_only", "mae", 23.5251, 23.525, checks)
    assert checks[0]["abs_delta"] < scale.RECOMPUTE_TOLERANCE


def test_a_recomputed_number_that_disagrees_with_the_committed_one_raises():
    checks: list[dict] = []
    with pytest.raises(ScaleError, match="must not carry a number that disagrees"):
        scale._check("gbm_res_persistence", "mae", 22.556, 23.556, checks)


def test_a_missing_committed_number_is_skipped_rather_than_invented():
    checks: list[dict] = []
    scale._check("naive_last_week", "rmae_vs_naive", 1.0, None, checks)
    assert checks == []


def test_every_check_is_recorded_so_the_summary_can_show_its_own_working():
    checks: list[dict] = []
    scale._check("a", "mae", 1.0, 1.0, checks)
    scale._check("b", "rmse", 2.0, 2.0, checks)
    assert [c["series"] for c in checks] == ["a", "b"]
    assert all({"recomputed", "committed", "abs_delta"} <= set(c) for c in checks)


# ---------------------------------------------------------------------------
# Labelling: the vintage, and the arms it applies to
# ---------------------------------------------------------------------------


def test_the_late_arm_is_the_only_one_labelled_after_gate_closure():
    assert scale.LATE_ARMS == frozenset({"res_as_published"})
    assert set(scale.EXOG_ARMS) - scale.LATE_ARMS == {
        "price_only", "load_only", "res_persistence"
    }


def _rows_for(variant: str):
    return scale._series_rows(
        zone_key="DE-LU", tier="A", regime="thermal-RES-mixed", model="gbm",
        variant=variant, train_from=scale.ALIGNED_TRAIN_FROM, years=[2024],
        spec={"refit_every_days": 1, "min_train_days": 365, "train_window_days": None},
        n_folds=366, scope="own_coverage",
        scores={"mae": 1.0, "rmse": 2.0, "bias": 0.5, "coverage": 1.0,
                "n": 8784, "n_scored": 8784},
        extra={"rmae_vs_naive": 0.5},
        source={"artefact": "x.csv.gz", "cycle": "C9", "git_sha": "abc"},
        model_fingerprint="a366a760e269bba6",
    )


def test_the_res_as_published_rows_carry_the_leakage_label():
    rows = _rows_for("res_as_published")
    assert rows
    assert {r.vintage for r in rows} == {"after_gate_closure"}


@pytest.mark.parametrize("variant", ["price_only", "load_only", "res_persistence"])
def test_the_leak_free_arms_are_labelled_honest(variant):
    assert {r.vintage for r in _rows_for(variant)} == {"honest"}


def test_a_series_row_set_carries_the_model_s_own_config_fingerprint():
    rows = _rows_for("res_persistence")
    assert {r.model_fingerprint for r in rows} == {"a366a760e269bba6"}


def test_a_series_row_set_cites_the_artefact_it_came_from():
    rows = _rows_for("price_only")
    assert {r.source_artefact for r in rows} == {"x.csv.gz"}
    assert {r.source_cycle for r in rows} == {"C9"}


def test_an_expanding_window_is_recorded_as_blank_not_as_zero():
    """A ``train_window_days`` of 0 would read as "a zero-day window"."""
    rows = _rows_for("price_only")
    assert {r.train_window_days for r in rows} == {""}


def test_every_metric_of_a_series_is_one_row():
    rows = _rows_for("price_only")
    assert sorted(r.metric for r in rows) == [
        "bias", "coverage", "mae", "rmae_vs_naive", "rmse"
    ]


# ---------------------------------------------------------------------------
# The common-hours mask
# ---------------------------------------------------------------------------


def _series(values):
    index = pd.date_range("2024-01-01", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=index, dtype="float64")


def test_the_common_mask_is_the_intersection_of_every_series():
    y_true = _series([1.0, 2.0, 3.0, 4.0])
    mask = scale._common_mask(
        y_true,
        {"a": _series([1.0, np.nan, 3.0, 4.0]), "b": _series([1.0, 2.0, np.nan, 4.0])},
    )
    assert list(mask) == [True, False, False, True]


def test_a_missing_realised_price_drops_the_hour_too():
    y_true = _series([1.0, np.nan])
    mask = scale._common_mask(y_true, {"a": _series([1.0, 1.0])})
    assert list(mask) == [True, False]


# ---------------------------------------------------------------------------
# The nine-zone comparable table
# ---------------------------------------------------------------------------


def _comparable_rows():
    rows = []
    for zone, tier, naive_mae, lear_mae in (
        ("DE-LU", "A", 32.791, 22.864),
        ("FR", "B", 20.0, 15.0),
    ):
        rows.extend(scale._series_rows(
            zone_key=zone, tier=tier, regime="r", model="naive_last_week", variant="",
            train_from=scale.FULL_HISTORY_TRAIN_FROM, years=[2024],
            spec={"refit_every_days": 1}, n_folds=366, scope="own_coverage",
            scores={"mae": naive_mae, "n": 8784, "n_scored": 8784}, extra={},
            source={"artefact": "a", "cycle": "C10", "git_sha": "s"},
        ))
        rows.extend(scale._series_rows(
            zone_key=zone, tier=tier, regime="r", model="lear", variant="price_only",
            train_from=scale.FULL_HISTORY_TRAIN_FROM, years=[2024],
            spec={"refit_every_days": 1}, n_folds=366, scope="own_coverage",
            scores={"mae": lear_mae, "n": 8784, "n_scored": 8783}, extra={},
            source={"artefact": "a", "cycle": "C10", "git_sha": "s"},
        ))
    return rows


def test_the_comparable_table_pairs_the_naive_floor_with_the_full_history_lear():
    table = scale._comparable_table(_comparable_rows())
    assert set(table["zones"]) == {"DE-LU", "FR"}
    assert table["zones"]["DE-LU"]["lear_price_only_mae"] == pytest.approx(22.864)
    assert table["zones"]["DE-LU"]["lear_mae_as_fraction_of_naive"] == pytest.approx(
        22.864 / 32.791, rel=1e-6
    )


def test_the_comparable_table_refuses_a_row_trained_from_a_different_date():
    """A Tier-A arm aligned to 2022 is not like-for-like with a 2019 Tier-B row."""
    rows = _comparable_rows()
    rows.extend(scale._series_rows(
        zone_key="ES", tier="A", regime="solar-dominated", model="lear",
        variant="price_only", train_from=scale.ALIGNED_TRAIN_FROM, years=[2024],
        spec={"refit_every_days": 1}, n_folds=366, scope="own_coverage",
        scores={"mae": 18.126, "n": 8784, "n_scored": 8783}, extra={},
        source={"artefact": "a", "cycle": "C8", "git_sha": "s"},
    ))
    table = scale._comparable_table(rows)
    assert "lear_price_only_mae" not in table["zones"].get("ES", {})


def test_the_comparable_table_ignores_common_hours_rows():
    rows = _comparable_rows()
    for row in rows:
        object.__setattr__(row, "scope", "common_hours")
    assert scale._comparable_table(rows)["zones"] == {}


def test_the_comparable_table_keeps_n_scored_beside_the_number():
    """LEAR declines one hour a year; the table must show that, not hide it."""
    table = scale._comparable_table(_comparable_rows())
    entry = table["zones"]["FR"]
    assert entry["naive_last_week_n_scored"] == 8784
    assert entry["lear_price_only_n_scored"] == 8783


# ---------------------------------------------------------------------------
# Artefact provenance guards
# ---------------------------------------------------------------------------


def _write_artefact(path, index, columns):
    frame = pd.DataFrame(columns, index=index)
    frame.index.name = "timestamp_utc"
    frame.to_csv(path, float_format="%.4f")
    return frame


def test_two_cycles_evaluated_on_different_hours_are_refused_not_realigned(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(scale, "RESULTS_DIR", tmp_path)
    index = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    y = np.arange(48, dtype="float64")
    _write_artefact(
        tmp_path / "c8_exog_DE-LU_2024_predictions.csv.gz", index,
        {"market_day": index.date, "y_true": y, "y_pred_price_only": y,
         "y_pred_price_only_full_history": y},
    )
    # C9's artefact covers one hour fewer.
    _write_artefact(
        tmp_path / "c9_gbm_DE-LU_2024_predictions.csv.gz", index[:47],
        {"market_day": index[:47].date, "y_true": y[:47],
         "y_pred_gbm_price_only": y[:47], "y_pred_naive_last_week": y[:47]},
    )
    for name in ("c8_exog_DE-LU_2024_summary.json", "c9_gbm_DE-LU_2024_summary.json"):
        (tmp_path / name).write_text(json.dumps({"walk_forward_spec": {}}), encoding="utf-8")

    with pytest.raises(ScaleError, match="did not evaluate the same hours"):
        scale.ingest_tier_a_zone("DE-LU", [2024])


def test_a_disagreement_between_two_cycles_realised_prices_is_refused(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(scale, "RESULTS_DIR", tmp_path)
    index = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    y = np.arange(48, dtype="float64")
    moved = y.copy()
    moved[7] += 5.0
    _write_artefact(
        tmp_path / "c8_exog_DE-LU_2024_predictions.csv.gz", index,
        {"market_day": index.date, "y_true": y, "y_pred_price_only": y,
         "y_pred_price_only_full_history": y},
    )
    _write_artefact(
        tmp_path / "c9_gbm_DE-LU_2024_predictions.csv.gz", index,
        {"market_day": index.date, "y_true": moved,
         "y_pred_gbm_price_only": moved, "y_pred_naive_last_week": moved},
    )
    for name in ("c8_exog_DE-LU_2024_summary.json", "c9_gbm_DE-LU_2024_summary.json"):
        (tmp_path / name).write_text(json.dumps({"walk_forward_spec": {}}), encoding="utf-8")

    with pytest.raises(ScaleError, match="committed realised prices disagree"):
        scale.ingest_tier_a_zone("DE-LU", [2024])


def test_a_missing_tier_b_artefact_says_to_run_the_compute_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(scale, "RESULTS_DIR", tmp_path)
    with pytest.raises(ScaleError, match="--phase compute"):
        scale.ingest_tier_b_zone("FR", [2024])


def test_a_missing_tier_a_artefact_says_to_rerun_that_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(scale, "RESULTS_DIR", tmp_path)
    with pytest.raises(ScaleError, match="rather than refitting here"):
        scale.ingest_tier_a_zone("DE-LU", [2024])


def test_the_compute_phase_refuses_a_tier_a_zone():
    """Tier A is ingested from committed artefacts; refitting it here would drift."""
    args = scale.parse_args(["--phase", "compute"])
    with pytest.raises(ScaleError, match="Tier-B only"):
        scale.compute_tier_b_zone("DE-LU", args)


def test_the_evaluation_years_default_to_the_visible_validation_year_only():
    assert scale.parse_args([]).years == [2024]


def test_the_two_training_windows_are_the_ones_the_artefacts_actually_used():
    assert scale.ALIGNED_TRAIN_FROM == "2022-01-01"
    assert scale.FULL_HISTORY_TRAIN_FROM == "2019-01-01"
