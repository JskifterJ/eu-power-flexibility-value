"""C3 tests: decision-time arithmetic and the feature matrix.

All synthetic and offline — no network, no cached files, no real price data, and
nothing here touches a sealed year. The series used are hand-built hourly UTC
indexes over real CET/CEST market days, so the DST transitions they contain are
genuine rather than mocked.

Written before any real model exists, per PLAN.md: the question "what did a
bidder know when they had to bid?" has to be answerable, and wrong, before there
is a metric anyone wants to look good.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from data.config import load_feature_config
from data.energy_charts import PRICE_COLUMN
from forecast.features import (
    FeatureError,
    build_features,
    shift_feature_matrix,
)
from forecast.leakage import find_leakage
from forecast.timing import (
    GateClosureConvention,
    TimingError,
    gate_closure_convention,
    gate_closure_utc,
    market_days,
    price_available_at,
    publication_utc,
    zone_timezone,
)

BERLIN = "Europe/Berlin"
ZONE = "DE-LU"


def _utc_index(start_local: str, n_local_days: int, tz: str = BERLIN) -> pd.DatetimeIndex:
    """Hourly UTC index spanning ``n_local_days`` whole local market days."""
    start = pd.Timestamp(f"{start_local} 00:00", tz=tz)
    end = start + pd.DateOffset(days=n_local_days)
    return pd.date_range(
        start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left"
    )


def _weekly_prices(index: pd.DatetimeIndex, seed: int = 7, noise: float = 2.0) -> pd.DataFrame:
    """A deliberately week-periodic price series plus small noise.

    Week-periodic so that the naive same-hour-last-week baseline has real skill and
    a one-day misalignment visibly destroys it — which is what the PLAN.md leakage
    assertions measure.
    """
    rng = np.random.default_rng(seed)
    position = ((index - index[0]) // pd.Timedelta(hours=1)) % 168
    shape = (
        60.0
        + 25.0 * np.sin(2 * np.pi * np.asarray(position % 24) / 24.0)
        + 15.0 * np.cos(2 * np.pi * np.asarray(position) / 168.0)
    )
    values = shape + rng.normal(0.0, noise, size=len(index))
    return pd.DataFrame({PRICE_COLUMN: values}, index=index)


def _random_walk_prices(index: pd.DatetimeIndex, seed: int = 19) -> pd.DataFrame:
    """A persistence-dominated price series: an hourly random walk around 60.

    The complement of :func:`_weekly_prices`. Here tomorrow's price is close to
    today's and last week's is a week of drift away, so a 24-hour *lead* feature is
    worth far more than the honest weekly lag — which is what makes it the right
    series for measuring what a leak would buy.
    """
    rng = np.random.default_rng(seed)
    values = 60.0 + np.cumsum(rng.normal(0.0, 3.0, size=len(index)))
    return pd.DataFrame({PRICE_COLUMN: values}, index=index)


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    """~2.2 years of synthetic hourly prices, covering four DST transitions."""
    return _weekly_prices(_utc_index("2021-01-01", 800))


# ---------------------------------------------------------------------------
# The decision clock
# ---------------------------------------------------------------------------


def test_gate_closure_is_noon_brussels_on_the_day_before():
    assert gate_closure_utc(dt.date(2024, 1, 16)) == pd.Timestamp("2024-01-15T11:00Z")
    assert gate_closure_utc(dt.date(2024, 7, 16)) == pd.Timestamp("2024-07-15T10:00Z")


def test_publication_falls_after_its_own_gate_closure_and_before_the_next():
    """The whole leakage model rests on this ordering, so assert it on real days.

    Prices for delivery day D are published after bids for day D have closed and
    before bids for day D+1 close. If that ever stopped holding, every "safe" lag
    in the project would silently become unsafe.
    """
    day = dt.date(2024, 1, 1)
    while day < dt.date(2025, 1, 1):
        gate = gate_closure_utc(day)
        published = publication_utc(day)
        assert gate < published, day
        assert published < gate_closure_utc(day + dt.timedelta(days=1)), day
        day += dt.timedelta(days=1)


def test_convention_refuses_a_publication_time_before_gate_closure():
    with pytest.raises(TimingError, match="published AFTER"):
        GateClosureConvention(
            tz="Europe/Brussels",
            gate_local_time=dt.time(13, 0),
            publication_local_time=dt.time(12, 0),
        )


def test_committed_convention_is_the_sdac_day_ahead_clock():
    conv = gate_closure_convention()
    assert conv.tz == "Europe/Brussels"
    assert conv.gate_local_time == dt.time(12, 0)
    assert conv.publication_local_time > conv.gate_local_time


def test_market_days_are_local_calendar_days_and_keep_dst_day_lengths():
    index = _utc_index("2024-10-25", 5)
    days = market_days(index, BERLIN)
    counts = days.value_counts()
    assert counts[dt.date(2024, 10, 27)] == 25, "autumn transition day is 25 hours long"
    assert counts[dt.date(2024, 10, 26)] == 24
    spring = market_days(_utc_index("2024-03-30", 3), BERLIN).value_counts()
    assert spring[dt.date(2024, 3, 31)] == 23, "spring transition day is 23 hours long"


def test_market_days_requires_a_tz_aware_index():
    with pytest.raises(TimingError, match="tz-aware"):
        market_days(pd.DatetimeIndex(["2024-01-01 00:00"]), BERLIN)


def test_local_midnight_belongs_to_the_next_market_day_and_is_published_later():
    """The one-hour fact that makes a UTC-day window leak.

    ``2024-01-15T23:00Z`` is local midnight on the 16th: it is market day *16*'s
    first hour, published at noon on the 15th — after gate closure for the 15th.
    Any feature that scoops it up while predicting the 16th is using the 16th's
    own auction result.
    """
    index = pd.DatetimeIndex(["2024-01-15T22:00Z", "2024-01-15T23:00Z"])
    days = market_days(index, BERLIN)
    assert list(days) == [dt.date(2024, 1, 15), dt.date(2024, 1, 16)]
    available = price_available_at(index, BERLIN)
    assert available.iloc[1] == publication_utc(dt.date(2024, 1, 16))
    assert available.iloc[1] > gate_closure_utc(dt.date(2024, 1, 16))


def test_zone_timezone_rejects_an_unknown_zone():
    with pytest.raises(TimingError, match="unknown zone"):
        zone_timezone("ATLANTIS")


# ---------------------------------------------------------------------------
# The feature matrix
# ---------------------------------------------------------------------------


def test_feature_columns_are_exactly_what_the_committed_spec_declares(prices):
    spec = load_feature_config()
    expected = [
        entry["name"]
        for block in ("price_history", "calendar")
        for entry in spec[block]
        if entry.get("status") != "deferred"
    ]
    matrix = build_features(prices, ZONE)
    assert matrix.columns == expected
    assert "is_public_holiday" in matrix.report.deferred_columns


def test_lag_features_are_exact_utc_offsets_not_row_shifts(prices):
    """A gap must make a lag NaN, never silently hand back the neighbouring hour.

    ``.shift(24)`` counts rows; across a missing hour it returns the price from 25
    hours earlier and calls it a 24-hour lag. That is a modelling bug which looks
    exactly like clean data, so it is asserted against directly.
    """
    gap_at = prices.index[500]
    punched = prices.drop(index=[gap_at])
    matrix = build_features(punched, ZONE)
    lag = matrix.features["price_lag_24h"]

    orphan = gap_at + pd.Timedelta(hours=24)
    assert np.isnan(lag.loc[orphan]), "the hour whose lag fell in the gap must be NaN"
    unaffected = gap_at + pd.Timedelta(hours=48)
    assert lag.loc[unaffected] == pytest.approx(
        punched[PRICE_COLUMN].loc[unaffected - pd.Timedelta(hours=24)]
    )


def test_the_plain_24h_lag_leaks_on_the_autumn_dst_day_and_is_masked(prices):
    """C3's first real finding: ``t - 24h`` reaches into the target's own market day.

    On the 25-hour autumn transition day, the 25th hour's ``t - 24h`` lands on that
    same market day's first hour — a price published after the bidding deadline for
    the very day being predicted. One cell per zone per year, invisible in any plot.
    """
    unmasked = build_features(prices, ZONE, mask=False, check=False)
    violations = find_leakage(
        unmasked.features,
        unmasked.information_times,
        unmasked.gate_closure,
        unmasked.deterministic,
    )
    assert [v.column for v in violations] == ["price_lag_24h"]
    leak = violations[0]
    assert leak.kind == "after_gate_closure"
    assert leak.n_rows == 2, "one leaking hour per autumn transition in this window"
    assert leak.worst_lateness == pd.Timedelta(hours=1)

    offenders = unmasked.index[
        unmasked.information_times["price_lag_24h"] > unmasked.gate_closure
    ]
    assert [ts.date() for ts in offenders] == [dt.date(2021, 10, 31), dt.date(2022, 10, 30)]

    masked = build_features(prices, ZONE)
    assert masked.report.mask.masked_per_column == {"price_lag_24h": 2}
    assert masked.features["price_lag_24h"].loc[offenders].isna().all()
    assert len(masked.index) == len(unmasked.index), "masking blanks cells, never drops rows"


def test_longer_lags_never_reach_into_the_target_market_day(prices):
    """168h is weekday-aligned and 48/72h are far enough back: nothing to mask."""
    unmasked = build_features(prices, ZONE, mask=False, check=False)
    for column in ("price_lag_48h", "price_lag_72h", "price_lag_168h"):
        late = unmasked.information_times[column] > unmasked.gate_closure
        assert not bool(late.any()), column


def test_daily_aggregates_use_the_last_fully_public_utc_day(prices):
    """NOTE C3-01: the window is UTC day ``D-2``, and emphatically not ``D-1``.

    UTC day ``D-1`` ends at ``D-1 23:00Z`` — local midnight on ``D`` — so a
    "yesterday's UTC day" mean embeds market day ``D``'s first cleared price on
    almost every row.
    """
    matrix = build_features(prices, ZONE)
    target_day = dt.date(2022, 6, 15)
    rows = matrix.index[(matrix.market_day == target_day).to_numpy()]
    assert len(rows) == 24

    price = prices[PRICE_COLUMN]
    by_utc_date = price.groupby(price.index.date)
    expected = by_utc_date.mean()[target_day - dt.timedelta(days=2)]
    forbidden = by_utc_date.mean()[target_day - dt.timedelta(days=1)]

    values = matrix.features["price_daily_mean_lag_24h"].loc[rows]
    assert values.nunique() == 1, "one daily summary per market day, not per hour"
    assert values.iloc[0] == pytest.approx(expected)
    assert values.iloc[0] != pytest.approx(forbidden)

    for column, how in (("price_daily_min_lag_24h", "min"), ("price_daily_max_lag_24h", "max")):
        want = getattr(by_utc_date, how)()[target_day - dt.timedelta(days=2)]
        assert matrix.features[column].loc[rows].iloc[0] == pytest.approx(want)


def test_daily_aggregates_are_nan_for_an_incomplete_utc_day(prices):
    """A mean over 23 hours is not a daily mean. It is NaN, and it is counted."""
    short_day = dt.date(2022, 3, 2)
    drop = [ts for ts in prices.index if ts.date() == short_day][5:6]
    punched = prices.drop(index=drop)
    matrix = build_features(punched, ZONE)
    assert matrix.report.n_incomplete_utc_days >= 1

    sourcing = matrix.index[
        (matrix.market_day == short_day + dt.timedelta(days=2)).to_numpy()
    ]
    assert matrix.features["price_daily_mean_lag_24h"].loc[sourcing].isna().all()


def test_calendar_features_do_not_depend_on_prices(prices):
    """Deterministic columns must be functions of the clock alone.

    Rebuilt on shuffled prices they have to come back bit-identical; if they do
    not, something price-derived is hiding in a column declared as carrying no
    market information, and the guard would wave it through.
    """
    rng = np.random.default_rng(3)
    shuffled = prices.copy()
    shuffled[PRICE_COLUMN] = rng.permutation(shuffled[PRICE_COLUMN].to_numpy())

    first = build_features(prices, ZONE)
    second = build_features(shuffled, ZONE)
    for column in first.deterministic:
        pd.testing.assert_series_equal(first.features[column], second.features[column])
    assert first.information_times[list(first.deterministic)].isna().all().all()


def test_local_hour_feature_tracks_the_wall_clock_across_a_dst_transition():
    """``hour_of_day_local`` is a feature column, and it is genuinely local."""
    index = _utc_index("2024-10-26", 2)
    matrix = build_features(_weekly_prices(index), ZONE)
    local = matrix.features["hour_of_day_local"]
    assert local.loc[pd.Timestamp("2024-10-26T22:00Z")] == 0, "local midnight, CEST"
    assert local.loc[pd.Timestamp("2024-10-26T23:00Z")] == 1
    # The repeated 02:00 local hour on the autumn transition day appears twice.
    transition = matrix.index[(matrix.market_day == dt.date(2024, 10, 27)).to_numpy()]
    assert int((local.loc[transition] == 2).sum()) == 2
    assert int(matrix.features["hour_of_day_utc"].loc[transition].nunique()) == 24


def test_build_rejects_a_non_utc_unsorted_or_duplicated_index(prices):
    local = prices.tz_convert(BERLIN)
    with pytest.raises(FeatureError, match="must be UTC"):
        build_features(local, ZONE)
    with pytest.raises(FeatureError, match="must be sorted"):
        build_features(prices.iloc[::-1], ZONE)
    doubled = pd.concat([prices.iloc[:48], prices.iloc[:48]]).sort_index()
    with pytest.raises(FeatureError, match="duplicate"):
        build_features(doubled, ZONE)
    with pytest.raises(FeatureError, match=PRICE_COLUMN):
        build_features(prices.rename(columns={PRICE_COLUMN: "other"}), ZONE)


def test_an_unknown_aggregate_or_calendar_feature_is_an_error_not_a_skip(prices):
    """A spec this module cannot honour must fail loudly, not quietly build less."""
    spec = load_feature_config()
    bad_aggregate = {
        "target": spec["target"],
        "price_history": [
            {"name": "price_weird", "lag_hours": 24, "aggregate": "median_over_lunar_month"}
        ],
        "calendar": [],
    }
    with pytest.raises(FeatureError, match="median_over_lunar_month"):
        build_features(prices, ZONE, feature_config=bad_aggregate)

    bad_calendar = {
        "target": spec["target"],
        "price_history": [{"name": "price_lag_24h", "lag_hours": 24}],
        "calendar": [{"name": "phase_of_moon"}],
    }
    with pytest.raises(FeatureError, match="phase_of_moon"):
        build_features(prices, ZONE, feature_config=bad_calendar)

    no_lag = {
        "target": spec["target"],
        "price_history": [{"name": "price_lag_mystery"}],
        "calendar": [],
    }
    with pytest.raises(FeatureError, match="no lag_hours"):
        build_features(prices, ZONE, feature_config=no_lag)


def test_shifting_the_matrix_moves_price_features_but_not_the_clock(prices):
    """``shift_feature_matrix`` must misalign only what a forecaster cannot choose.

    The hour and weekday being bid for are always known; misaligning them would
    measure clock arithmetic instead of feature alignment.
    """
    matrix = build_features(prices, ZONE)
    shifted = shift_feature_matrix(matrix, 1)
    assert shifted.index.equals(matrix.index)
    for column in matrix.deterministic:
        pd.testing.assert_series_equal(shifted.features[column], matrix.features[column])
    probe = matrix.index[400]
    assert shifted.features["price_lag_168h"].loc[probe] == pytest.approx(
        matrix.features["price_lag_168h"].loc[probe - pd.Timedelta(days=1)]
    )
    assert shift_feature_matrix(matrix, 0) is matrix
