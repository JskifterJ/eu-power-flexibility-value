"""C8 tests: exogenous columns at a declared vintage, and the degradation ladder.

All synthetic and offline; no network, no cached file, no sealed year. The
exogenous frames here are built by hand so the *vintage* arithmetic can be
checked against values a human can compute, rather than against whatever
ENTSO-E happened to publish.

The load-bearing tests are not the ones showing that the columns arrive. They
are the ones showing that a post-gate-closure column cannot arrive *quietly*:

* ``test_as_published_res_columns_are_six_hours_late`` and
  ``test_the_declared_clock_is_what_makes_the_leak_visible`` — the Art. 14
  vintage is late, by exactly the amount the committed publication clock
  predicts, and the guard sees it.
* ``test_leak_free_variants_pass_the_plain_guard`` — ``price_only``,
  ``load_only`` and ``res_persistence`` are clean under the *unmodified* C3
  guard. If a later cycle breaks that, this fails.
* ``test_acknowledgement_refuses_an_unrelated_leak``,
  ``test_acknowledgement_refuses_a_column_late_by_the_wrong_amount``,
  ``test_acknowledgement_refuses_a_silent_acknowledgement`` and
  ``test_acknowledgement_refuses_an_undeclared_column`` — the escape hatch is
  narrow. It permits one named, shaped, measured leak and nothing else, which is
  the only reason it is allowed to exist.
* ``test_persistence_vintage_is_blanked_on_the_autumn_dst_long_day`` — the
  24-hour offset is late on exactly one row per autumn DST day, and the mask
  catches it. Nobody would have special-cased this; the clock arithmetic did.
* ``test_a_leading_res_column_is_worth_a_lot_to_lear`` — what the leak is worth,
  measured, so the acknowledgement is not guarding a technicality.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import score
from backtest.walk_forward import WalkForwardSpec, evaluation_days, run_walk_forward
from data.exogenous import (
    LOAD_COLUMN,
    RESIDUAL_LOAD_COLUMN,
    SOLAR_COLUMN,
    WIND_COLUMN,
)
from forecast.exog_features import (
    EXOG_VARIANTS,
    LEAK_FREE_VARIANTS,
    RES_COLUMNS,
    ExogFeatureError,
    ExogSpec,
    assert_only_acknowledged_leakage,
    attach_exogenous,
    column_clock,
    exogenous_feature_names,
    publication_clocks,
    publication_instants,
    variant_is_monotone_in_information,
)
from forecast.features import build_features
from forecast.leakage import LeakageError, find_leakage
from forecast.lear import LearSpec, lear_factory
from forecast.timing import gate_closure_convention, market_days
from tests.test_c3_timing_features import ZONE, _utc_index, _weekly_prices

BERLIN = "Europe/Berlin"
SPEC = WalkForwardSpec(refit_every_days=28, min_train_days=200)
SMALL = LearSpec(min_fit_rows=30)

#: 18:00 published vs 12:00 gate, both on D-1, both Europe/Brussels.
EXPECTED_RES_LATENESS = pd.Timedelta(hours=6)

#: 10:00 published vs 12:00 gate: two hours early, as Art. 6.1.B requires.
EXPECTED_LOAD_LEAD = pd.Timedelta(hours=2)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _exogenous_frame(index: pd.DatetimeIndex, seed: int = 23) -> pd.DataFrame:
    """A synthetic Tier-A exogenous frame on ``index``.

    Load has a daily shape, solar a daytime bell, wind a weekly cycle, each with
    noise — enough structure that a LASSO can find something, and little enough
    that none of them is a disguised copy of the price.
    """
    rng = np.random.default_rng(seed)
    position = ((index - index[0]) // pd.Timedelta(hours=1)) % 168
    load = 50_000.0 + 8_000.0 * np.sin(2 * np.pi * np.asarray(position % 24) / 24.0)
    solar = np.clip(
        20_000.0 * np.sin(np.pi * (np.asarray(index.hour) - 5) / 14.0), 0.0, None
    )
    wind = 12_000.0 + 6_000.0 * np.cos(2 * np.pi * np.asarray(position) / 168.0)
    frame = pd.DataFrame(
        {
            LOAD_COLUMN: load + rng.normal(0.0, 400.0, len(index)),
            WIND_COLUMN: np.clip(wind + rng.normal(0.0, 900.0, len(index)), 0.0, None),
            SOLAR_COLUMN: solar,
        },
        index=index,
    )
    frame[RESIDUAL_LOAD_COLUMN] = (
        frame[LOAD_COLUMN] - frame[WIND_COLUMN] - frame[SOLAR_COLUMN]
    )
    frame.attrs["leakage_status"] = "FLAGGED"
    frame.attrs["flagged_columns"] = [RESIDUAL_LOAD_COLUMN, SOLAR_COLUMN, WIND_COLUMN]
    frame.attrs["unit"] = "MW"
    return frame


@pytest.fixture(scope="module")
def index() -> pd.DatetimeIndex:
    """Two years from 2022-01-01, covering both autumn DST long days."""
    return _utc_index("2022-01-01", 730)


@pytest.fixture(scope="module")
def matrix(index):
    return build_features(_weekly_prices(index), ZONE)


@pytest.fixture(scope="module")
def exog(index):
    return _exogenous_frame(index)


def _attach(matrix, exog, variant, **kwargs):
    return attach_exogenous(matrix, exog, ExogSpec(variant=variant), **kwargs)


# ---------------------------------------------------------------------------
# The publication clock
# ---------------------------------------------------------------------------


def test_every_document_declares_a_publication_clock():
    clocks = publication_clocks()
    assert set(clocks) == {"load_forecast_da", "wind_solar_forecast_da"}
    assert clocks["load_forecast_da"].leakage_status == "safe"
    assert clocks["wind_solar_forecast_da"].leakage_status == "FLAGGED"
    for clock in clocks.values():
        assert clock.day_offset == -1
        assert clock.tz == gate_closure_convention().tz


def test_the_declared_clock_is_what_makes_the_leak_visible():
    """The committed numbers, not prose, put A69 after the gate and A65 before it.

    If a later cycle edits either time in ``config/data.yaml``, this is the test
    that notices — the FLAGGED status stops being an assertion in a comment and
    becomes a six-hour arithmetic fact.
    """
    clocks = publication_clocks()
    convention = gate_closure_convention()
    day = dt.date(2023, 6, 15)
    days = pd.Series([day], index=pd.DatetimeIndex(["2023-06-15T12:00Z"]))

    gate = pd.Timestamp(
        dt.datetime.combine(day - dt.timedelta(days=1), convention.gate_local_time)
    ).tz_localize(convention.tz)
    load_public = publication_instants(days, clocks["load_forecast_da"]).iloc[0]
    res_public = publication_instants(days, clocks["wind_solar_forecast_da"]).iloc[0]

    assert gate - load_public == EXPECTED_LOAD_LEAD, "A65 must be public before the gate"
    assert res_public - gate == EXPECTED_RES_LATENESS, "A69 must be after the gate"


def test_a_document_without_a_clock_fails_closed():
    """A missing declaration is an error, never a convenient default."""
    import copy

    from data.config import load_data_config

    cfg = copy.deepcopy(load_data_config())
    del cfg["sources"]["entsoe"]["documents"]["wind_solar_forecast_da"]["published_local"]
    with pytest.raises(ExogFeatureError, match="publication clock"):
        publication_clocks(cfg)


def test_a_missing_publication_timezone_fails_closed():
    import copy

    from data.config import load_data_config

    cfg = copy.deepcopy(load_data_config())
    del cfg["sources"]["entsoe"]["publication_tz"]
    with pytest.raises(ExogFeatureError, match="publication_tz"):
        publication_clocks(cfg)


def test_column_clock_routes_each_column_to_its_own_document():
    clocks = publication_clocks()
    assert column_clock(LOAD_COLUMN, clocks).document_key == "load_forecast_da"
    for column in RES_COLUMNS:
        assert column_clock(column, clocks).document_key == "wind_solar_forecast_da"


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------


def test_the_ladder_is_declared_in_information_order():
    assert variant_is_monotone_in_information(list(EXOG_VARIANTS))
    assert not variant_is_monotone_in_information(["res_as_published", "load_only"])
    assert set(LEAK_FREE_VARIANTS) == set(EXOG_VARIANTS) - {"res_as_published"}


def test_an_unknown_variant_is_refused():
    with pytest.raises(ExogFeatureError, match="unknown exogenous variant"):
        ExogSpec(variant="res_slightly_degraded")


def test_a_fractional_day_persistence_offset_is_refused():
    """A 12-hour offset would read a different delivery hour, not an older vintage."""
    with pytest.raises(ExogFeatureError, match="whole number of days"):
        ExogSpec(variant="res_persistence", persistence_lag_hours=12)


def test_only_the_as_published_variant_acknowledges_late_columns():
    for variant in LEAK_FREE_VARIANTS:
        assert ExogSpec(variant=variant).acknowledges_late_columns is False
        assert ExogSpec(variant=variant).res_lag_hours in (0, 24)
    late = ExogSpec(variant="res_as_published")
    assert late.acknowledges_late_columns is True
    assert late.res_lag_hours == 0, "the late arm reads the target day's own vintage"
    assert ExogSpec(variant="res_persistence").res_lag_hours == 24


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


def test_price_only_returns_the_matrix_untouched(matrix, exog):
    attached, report = _attach(matrix, exog, "price_only")
    assert attached is matrix
    assert report.exogenous_columns == []
    assert report.acknowledged_late_columns == []


def test_price_only_needs_no_exogenous_frame(matrix):
    attached, _ = attach_exogenous(matrix, None, ExogSpec(variant="price_only"))
    assert attached is matrix


def test_each_variant_adds_exactly_the_columns_it_declares(matrix, exog):
    expected = {
        "price_only": [],
        "load_only": [LOAD_COLUMN],
        "res_persistence": [LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN, RESIDUAL_LOAD_COLUMN],
        "res_as_published": [LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN, RESIDUAL_LOAD_COLUMN],
    }
    for variant, columns in expected.items():
        attached, report = _attach(matrix, exog, variant)
        assert sorted(report.exogenous_columns) == sorted(columns), variant
        assert sorted(set(attached.columns) - set(matrix.columns)) == sorted(columns)
        # The information-time frame never falls behind the feature frame.
        assert list(attached.features.columns) == list(attached.information_times.columns)


def test_a_variant_without_its_source_column_is_refused(matrix, exog):
    with pytest.raises(ExogFeatureError, match="no 'wind_forecast_da_mw'"):
        _attach(matrix, exog.drop(columns=[WIND_COLUMN]), "res_persistence")


def test_a_non_utc_exogenous_index_is_refused(matrix, exog):
    local = exog.copy()
    local.index = exog.index.tz_convert(BERLIN)
    with pytest.raises(ExogFeatureError, match="must be UTC"):
        _attach(matrix, local, "load_only")


def test_a_duplicated_exogenous_timestamp_is_refused(matrix, exog):
    doubled = pd.concat([exog, exog.iloc[[5]]]).sort_index()
    with pytest.raises(ExogFeatureError, match="duplicate timestamps"):
        _attach(matrix, doubled, "load_only")


def test_the_as_published_load_column_is_the_source_value_verbatim(matrix, exog):
    """No lag on load: the target hour's own forecast, which was public in time."""
    attached, _ = _attach(matrix, exog, "load_only")
    built = attached.features[LOAD_COLUMN].reindex(exog.index[200:260])
    source = exog[LOAD_COLUMN].reindex(exog.index[200:260])
    pd.testing.assert_series_equal(built, source, check_names=False)


def test_the_persistence_vintage_is_the_value_24_hours_earlier(matrix, exog):
    """Checked against an explicit UTC offset, not against ``.shift``."""
    attached, _ = _attach(matrix, exog, "res_persistence")
    sample = exog.index[400:460]
    for column in RES_COLUMNS:
        built = attached.features[column].reindex(sample).to_numpy()
        expected = exog[column].reindex(sample - pd.Timedelta(hours=24)).to_numpy()
        np.testing.assert_allclose(built, expected, rtol=0, atol=0)


def test_residual_load_is_derived_after_degradation_not_before(matrix, exog):
    """``load(t) - wind(t-24h) - solar(t-24h)``: a quantity the bidder could compute.

    Lagging C7's already-derived residual-load column by 24 hours would instead
    throw away the load forecast the bidder *did* hold, and would differ from this
    by the day-on-day change in load — which is exactly the part of residual load
    that a day-ahead bidder knows.
    """
    attached, _ = _attach(matrix, exog, "res_persistence")
    sample = exog.index[400:460]
    built = attached.features[RESIDUAL_LOAD_COLUMN].reindex(sample).to_numpy()

    load_now = exog[LOAD_COLUMN].reindex(sample).to_numpy()
    lagged = sample - pd.Timedelta(hours=24)
    wind_then = exog[WIND_COLUMN].reindex(lagged).to_numpy()
    solar_then = exog[SOLAR_COLUMN].reindex(lagged).to_numpy()
    np.testing.assert_allclose(built, load_now - wind_then - solar_then, rtol=0, atol=1e-9)

    naive_lag = exog[RESIDUAL_LOAD_COLUMN].reindex(lagged).to_numpy()
    assert not np.allclose(built, naive_lag), (
        "deriving after degradation must differ from lagging the derived column — "
        "otherwise the load forecast is being discarded"
    )


def test_derived_residual_load_inherits_its_latest_input_s_information_time(matrix, exog):
    """A derived value is knowable only once its last input is."""
    attached, _ = _attach(matrix, exog, "res_as_published", mask=False, check=False)
    info = attached.information_times
    inputs = info[[LOAD_COLUMN, WIND_COLUMN, SOLAR_COLUMN]].max(axis=1)
    pd.testing.assert_series_equal(
        info[RESIDUAL_LOAD_COLUMN], inputs, check_names=False
    )


def test_a_gap_in_the_exogenous_series_stays_a_gap(matrix, exog):
    """Nothing is filled: a missing source hour becomes NaN, and is counted."""
    holed = exog.copy()
    victim = exog.index[1000]
    holed.loc[victim, :] = np.nan
    attached, report = _attach(matrix, holed, "load_only")
    assert pd.isna(attached.features.loc[victim, LOAD_COLUMN])
    assert report.coverage_per_column[LOAD_COLUMN] < 1.0


def test_rows_outside_the_exogenous_window_are_nan_not_dropped(exog):
    """The exogenous series starts in 2022; earlier rows keep their price features."""
    wide_index = _utc_index("2021-06-01", 400)
    wide = build_features(_weekly_prices(wide_index), ZONE)
    attached, report = attach_exogenous(
        wide, exog, ExogSpec(variant="load_only")
    )
    assert len(attached.index) == len(wide.index), "no row may be dropped"
    before = attached.features.loc[attached.index < exog.index[0], LOAD_COLUMN]
    assert before.isna().all()
    assert 0.0 < report.coverage_per_column[LOAD_COLUMN] < 1.0


# ---------------------------------------------------------------------------
# The guard: leak-free variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", LEAK_FREE_VARIANTS)
def test_leak_free_variants_pass_the_plain_guard(matrix, exog, variant):
    """The *unmodified* C3 guard, with no acknowledgement of any kind."""
    attached, report = _attach(matrix, exog, variant)
    assert report.acknowledged_late_columns == []
    attached.assert_clean(f"{variant} must be clean under the plain guard")
    assert find_leakage(
        attached.features,
        attached.information_times,
        attached.gate_closure,
        attached.deterministic,
    ) == []


def test_the_load_column_is_public_before_every_row_s_gate_closure(matrix, exog):
    attached, _ = _attach(matrix, exog, "load_only")
    info = attached.information_times[LOAD_COLUMN]
    present = attached.features[LOAD_COLUMN].notna()
    assert (info[present] <= attached.gate_closure[present]).all()
    assert (attached.gate_closure[present] - info[present] == EXPECTED_LOAD_LEAD).all()


def test_persistence_vintage_is_blanked_on_the_autumn_dst_long_day(matrix, exog):
    """One row a year, found by clock arithmetic rather than by special-casing.

    On the autumn DST day the local market day has 25 hours, so its *last* hour
    minus 24 hours is its own *first* hour — whose RES forecast was published at
    18:00 on D-1, after the gate. The mask catches exactly those rows and nothing
    else, and ``res_persistence`` therefore still passes the plain guard.
    """
    attached, report = _attach(matrix, exog, "res_persistence")
    assert report.persistence_masked_dst_rows == 2, (
        "two autumn DST long days in a 2022-2023 window, one blanked row each"
    )
    blanked = pd.DatetimeIndex(report.persistence_masked_dst_timestamps)
    local_days = market_days(blanked, BERLIN)
    for timestamp, day in local_days.items():
        hours_in_day = (market_days(exog.index, BERLIN) == day).sum()
        assert hours_in_day == 25, f"{day} should be a 25-hour local day"
        assert timestamp == max(
            ts for ts, d in market_days(exog.index, BERLIN).items() if d == day
        ), "the blanked row is the long day's last hour"
    for column in RES_COLUMNS:
        assert attached.features.loc[blanked, column].isna().all()
    attached.assert_clean("res_persistence stays clean after masking")


# ---------------------------------------------------------------------------
# The guard: the acknowledged late arm
# ---------------------------------------------------------------------------


def test_as_published_res_columns_are_six_hours_late(matrix, exog):
    """The leak is real, named, and exactly the size the clock predicts."""
    attached, report = _attach(matrix, exog, "res_as_published")
    assert sorted(report.acknowledged_late_columns) == sorted(
        [RESIDUAL_LOAD_COLUMN, SOLAR_COLUMN, WIND_COLUMN]
    )
    assert report.acknowledged_violations, "the arm must record what it permitted"
    for violation in report.acknowledged_violations:
        assert violation["kind"] == "after_gate_closure"
        assert violation["column"] in report.acknowledged_late_columns
        assert violation["worst_lateness_seconds"] == EXPECTED_RES_LATENESS.total_seconds()


def test_the_as_published_arm_would_fail_the_plain_guard(matrix, exog):
    """It is not clean, and it never claims to be."""
    attached, _ = _attach(matrix, exog, "res_as_published")
    with pytest.raises(LeakageError, match="after_gate_closure"):
        attached.assert_clean("as-published arm is knowingly late")


def test_the_as_published_load_column_is_not_acknowledged(matrix, exog):
    """Only the Art. 14 columns are late; the Art. 6 load forecast stays checked."""
    _, report = _attach(matrix, exog, "res_as_published")
    assert LOAD_COLUMN not in report.acknowledged_late_columns


def test_acknowledgement_refuses_an_unrelated_leak(matrix, exog):
    """A late price lag cannot hide behind the RES acknowledgement."""
    attached, report = _attach(matrix, exog, "res_as_published")
    tampered_info = attached.information_times.copy()
    tampered_info["price_lag_24h"] = attached.gate_closure + pd.Timedelta(hours=1)
    tampered = attached.with_features(attached.features, tampered_info)
    with pytest.raises(LeakageError, match="price_lag_24h"):
        assert_only_acknowledged_leakage(
            tampered, report.acknowledged_late_columns, publication_clocks()
        )


def test_acknowledgement_refuses_a_column_late_by_the_wrong_amount(matrix, exog):
    """Later than the declared clock is a different, unexamined leak."""
    attached, report = _attach(matrix, exog, "res_as_published")
    tampered_info = attached.information_times.copy()
    tampered_info[WIND_COLUMN] = tampered_info[WIND_COLUMN] + pd.Timedelta(hours=3)
    tampered = attached.with_features(attached.features, tampered_info)
    with pytest.raises(LeakageError, match="worst lateness of exactly"):
        assert_only_acknowledged_leakage(
            tampered, report.acknowledged_late_columns, publication_clocks()
        )


def test_acknowledgement_refuses_a_silent_acknowledgement(matrix, exog):
    """Acknowledging a leak that does not appear means measuring something else."""
    attached, _ = _attach(matrix, exog, "load_only")
    with pytest.raises(LeakageError, match="produced no after_gate_closure"):
        assert_only_acknowledged_leakage(
            attached, [LOAD_COLUMN], publication_clocks()
        )


def test_acknowledgement_refuses_an_undeclared_column(matrix, exog):
    """An undeclared information time is never acknowledgeable: nobody knows what for."""
    attached, report = _attach(matrix, exog, "res_as_published")
    features = attached.features.copy()
    features["mystery_column"] = 1.0
    tampered = attached.with_features(features, attached.information_times)
    with pytest.raises(LeakageError, match="mystery_column"):
        assert_only_acknowledged_leakage(
            tampered, report.acknowledged_late_columns, publication_clocks()
        )


def test_acknowledgement_refuses_a_column_that_is_not_in_the_matrix(matrix, exog):
    attached, _ = _attach(matrix, exog, "load_only")
    with pytest.raises(LeakageError, match="not in the matrix"):
        assert_only_acknowledged_leakage(attached, ["not_a_column"])


def test_acknowledgement_refuses_a_malformed_information_time(matrix, exog):
    """A tz-naive declaration cannot be checked, so it cannot be acknowledged."""
    attached, report = _attach(matrix, exog, "res_as_published")
    tampered_info = attached.information_times.copy()
    tampered_info[WIND_COLUMN] = attached.information_times[WIND_COLUMN].dt.tz_localize(
        None
    )
    tampered = attached.with_features(attached.features, tampered_info)
    with pytest.raises(LeakageError, match="malformed_information_time"):
        assert_only_acknowledged_leakage(
            tampered, report.acknowledged_late_columns, publication_clocks()
        )


def test_the_whole_matrix_check_implies_every_row_subset_s(matrix, exog):
    """Why one pass on the arm matrix can replace the harness's per-fold check.

    The guard is a per-(row, column) predicate, so any violation in a subset is a
    violation of the whole. Asserted on real subsets rather than argued.
    """
    attached, report = _attach(matrix, exog, "res_as_published")
    whole = {
        (v.kind, v.column)
        for v in find_leakage(
            attached.features,
            attached.information_times,
            attached.gate_closure,
            attached.deterministic,
        )
    }
    days = sorted(set(attached.market_day))
    for block in (days[:30], days[200:230], days[-30:]):
        subset = attached.select_days(block)
        found = {
            (v.kind, v.column)
            for v in find_leakage(
                subset.features,
                subset.information_times,
                subset.gate_closure,
                subset.deterministic,
            )
        }
        assert found <= whole, f"subset {block[0]}..{block[-1]} found something new"
        assert_only_acknowledged_leakage(
            subset, report.acknowledged_late_columns, publication_clocks()
        )


# ---------------------------------------------------------------------------
# What the vintage is worth
# ---------------------------------------------------------------------------


def test_the_harness_runs_every_leak_free_arm_through_lear(matrix, exog):
    """End to end on the real harness, with its per-fold guard on."""
    days = evaluation_days(matrix, [2023])[:56]
    for variant in LEAK_FREE_VARIANTS:
        attached, _ = _attach(matrix, exog, variant)
        result = run_walk_forward(
            attached, lear_factory(SMALL, name=f"lear_{variant}"), days, SPEC
        )
        scores = score(result.y_true, result.y_pred)
        assert scores.n_scored > 0
        assert np.isfinite(scores.mae)


def test_the_harness_refuses_the_as_published_arm_with_its_guard_on(matrix, exog):
    """The late arm cannot be run by accident — only through the acknowledged path."""
    attached, _ = _attach(matrix, exog, "res_as_published")
    days = evaluation_days(matrix, [2023])[:28]
    with pytest.raises(LeakageError, match="after_gate_closure"):
        run_walk_forward(attached, lear_factory(SMALL), days, SPEC)


def test_a_leading_res_column_is_worth_a_lot_to_lear(matrix, exog):
    """What a RES leak buys, so the acknowledgement is not guarding a technicality.

    A wind column that is a clean function of the target hour's own price is the
    extreme case of a late vintage. It must improve MAE sharply — if it did not,
    the guard would be protecting nothing and the whole degradation experiment
    would be measuring noise.
    """
    days = evaluation_days(matrix, [2023])[:56]

    honest, _ = _attach(matrix, exog, "load_only")
    honest_result = run_walk_forward(
        honest, lear_factory(SMALL, name="lear_honest"), days, SPEC
    )
    honest_mae = score(honest_result.y_true, honest_result.y_pred).mae

    leaking_exog = exog.copy()
    leaking_exog[WIND_COLUMN] = (
        matrix.target.reindex(exog.index).to_numpy() * 100.0
    )
    leaking_exog[RESIDUAL_LOAD_COLUMN] = (
        leaking_exog[LOAD_COLUMN] - leaking_exog[WIND_COLUMN] - leaking_exog[SOLAR_COLUMN]
    )
    leaking, report = _attach(matrix, leaking_exog, "res_as_published")
    leaking_result = run_walk_forward(
        leaking, lear_factory(SMALL, name="lear_leaking"), days, SPEC, check_leakage=False
    )
    leaking_mae = score(leaking_result.y_true, leaking_result.y_pred).mae

    assert report.acknowledged_late_columns, "the leak must still be acknowledged"
    assert leaking_mae < honest_mae * 0.5, (
        f"a target-derived RES column should slash MAE (honest {honest_mae:.3f}, "
        f"leaking {leaking_mae:.3f}); if it does not, the guard protects nothing"
    )


# ---------------------------------------------------------------------------
# The two config files still agree
# ---------------------------------------------------------------------------


def test_the_feature_spec_and_the_built_columns_still_map_onto_each_other():
    """NOTE C7-01's mapping, derived rather than written down twice."""
    mapping = exogenous_feature_names()
    assert mapping == {
        "load_forecast_da": LOAD_COLUMN,
        "wind_forecast_da": WIND_COLUMN,
        "solar_forecast_da": SOLAR_COLUMN,
        "residual_load_forecast": RESIDUAL_LOAD_COLUMN,
    }


def test_the_feature_spec_still_declares_the_art_14_columns_flagged():
    """The FLAGGED status is what forces the degradation arm to exist."""
    from data.config import load_feature_config

    declared = {
        entry["name"]: entry.get("leakage_status")
        for entry in load_feature_config()["exogenous"]
    }
    assert declared["load_forecast_da"] == "safe"
    for name in ("wind_forecast_da", "solar_forecast_da", "residual_load_forecast"):
        assert declared[name] == "FLAGGED", name


# ---------------------------------------------------------------------------
# The sealed holdout
# ---------------------------------------------------------------------------


def test_no_arm_can_be_evaluated_against_a_sealed_year(matrix, exog):
    from data.config import sealed_years
    from data.holdout import SealedHoldoutError

    sealed = sorted(sealed_years())
    assert sealed == [2025], "C8 must still find 2025 sealed"
    attached, _ = _attach(matrix, exog, "load_only")
    with pytest.raises(SealedHoldoutError):
        evaluation_days(attached, sealed)
