"""C2 tests: the stitching loader, the data contracts, the hourly aggregation.

All synthetic and offline — no network, no real price data, and nothing here
reads a sealed year's data. A few tests build a synthetic index dated 2025 in
order to exercise the 2025-10-01 resolution-cutover detector that PLAN.md
requires; that is a hand-made index of made-up numbers, not sealed-holdout
*data*, and the holdout guard (which governs fetching and loading real 2025
files) is separately asserted to be closed by
``test_c1_data_layer.py::test_repo_progress_file_does_not_yet_unseal_the_holdout``.

Written in C2 *before* any model exists, per PLAN.md: the contracts must be able
to fail on bad data before there is a metric anyone wants to look good.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from data.aggregate import to_hourly
from data.contracts import (
    HOURLY_SECONDS,
    QUARTER_HOURLY_SECONDS,
    DataContractViolation,
    assert_contract,
    build_contract_report,
    check_local_day_counts,
    check_resolution_cutover,
    check_utc_day_counts,
    cutover_instant_utc,
    detect_resolution_changes,
    dst_transition_days,
    expected_intervals_for_local_day,
    expected_intervals_for_utc_day,
    gap_report,
    index_is_utc,
    local_day_counts,
    local_day_hours,
    modal_resolution_seconds,
    resolution_segments,
    utc_day_counts,
)
from data.energy_charts import PRICE_COLUMN
from data.holdout import SealedHoldoutError
from data.prices import PriceDataError, load_zone_series, wide_prices

PRICE = PRICE_COLUMN


# ---------------------------------------------------------------------------
# Helpers: synthetic cache files, so the loader can be tested without network
# ---------------------------------------------------------------------------


def _local_year_payload(year: int, tz: str = "Europe/Berlin", resolution: int = 3600) -> dict:
    """A payload shaped like Energy-Charts': one full *local* year, UTC epochs.

    This reproduces the convention NOTE C1-02 established — the window is a local
    year, so in UTC the file spans ``[Y-1-12-31T23:00Z, Y-12-31T22:00Z]`` for a
    CET zone — which is the thing the stitching loader has to get right.
    """
    start = pd.Timestamp(f"{year}-01-01 00:00", tz=tz).tz_convert("UTC")
    end = pd.Timestamp(f"{year + 1}-01-01 00:00", tz=tz).tz_convert("UTC")
    index = pd.date_range(start, end, freq=f"{resolution}s", inclusive="left")
    return {
        "unix_seconds": [int(t.timestamp()) for t in index],
        "price": [float(i % 97) - 10.0 for i in range(len(index))],
        "unit": "EUR / MWh",
        "deprecated": False,
        "license_info": "CC BY 4.0",
    }


def _write_cache(tmp_path, zone_key: str, year: int, payload: dict) -> None:
    directory = tmp_path / "data" / "raw" / "energy_charts" / "price" / zone_key
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{year}.json").open("w", encoding="utf-8") as fh:
        json.dump({"_fetch_meta": {"fetched_at_utc": "2026-01-01T00:00:00+00:00"}, **payload},
                  fh)


@pytest.fixture
def cache_config(tmp_path, monkeypatch):
    """A data config whose cache_dir points at tmp_path, for loader tests."""
    from data.config import load_data_config
    import data.energy_charts as ec

    cfg = json.loads(json.dumps(load_data_config()))  # deep copy
    monkeypatch.setattr(
        ec, "cache_dir",
        lambda config=None: tmp_path / "data" / "raw" / "energy_charts" / "price",
    )
    import data.prices as prices_mod
    monkeypatch.setattr(prices_mod, "cache_path",
                        lambda z, y, config=None: ec.cache_dir() / z / f"{y}.json")
    return cfg


def _hourly_index(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="h", tz="UTC")


def _frame(index: pd.DatetimeIndex, values=None) -> pd.DataFrame:
    return pd.DataFrame(
        {PRICE: values if values is not None else [float(i) for i in range(len(index))]},
        index=index,
    )


# ---------------------------------------------------------------------------
# The DST whitelist is derived from the tz database, and is right
# ---------------------------------------------------------------------------


def test_local_day_hours_knows_the_eu_transition_days():
    assert local_day_hours(dt.date(2024, 3, 31), "Europe/Berlin") == 23
    assert local_day_hours(dt.date(2024, 10, 27), "Europe/Berlin") == 25
    assert local_day_hours(dt.date(2024, 6, 1), "Europe/Berlin") == 24
    assert local_day_hours(dt.date(2024, 1, 1), "Europe/Berlin") == 24


def test_dst_whitelist_has_exactly_two_transition_days_per_year_per_zone():
    for tz in ("Europe/Berlin", "Europe/Madrid", "Europe/Oslo", "Europe/Warsaw"):
        whitelist = dst_transition_days(tz, [2019, 2020, 2021, 2022, 2023, 2024])
        assert len(whitelist) == 12, tz
        assert sorted(whitelist.values()) == [23] * 6 + [25] * 6
        # EU transitions are the last Sunday of March and of October.
        for day, hours in whitelist.items():
            assert day.weekday() == 6, (tz, day)
            assert day.month == (3 if hours == 23 else 10), (tz, day)
            assert (day + dt.timedelta(days=7)).month != day.month, (tz, day)


def test_all_nine_zones_share_the_same_transition_calendar():
    """Every zone in scope is CET/CEST, so one whitelist covers the panel.

    If a non-CET zone is ever added this test fails, which is the point: the
    per-zone local-day contract would then no longer be interchangeable.
    """
    from data.config import load_zones

    calendars = {
        zone.key: sorted(dst_transition_days(zone.local_tz, [2019, 2024]).items())
        for zone in load_zones().values()
    }
    distinct = {tuple(v) for v in calendars.values()}
    assert len(distinct) == 1, calendars


def test_expected_intervals_per_local_day_scales_with_resolution():
    spring = dt.date(2024, 3, 31)
    autumn = dt.date(2024, 10, 27)
    assert expected_intervals_for_local_day(spring, "Europe/Berlin", HOURLY_SECONDS) == 23
    assert expected_intervals_for_local_day(autumn, "Europe/Berlin", HOURLY_SECONDS) == 25
    assert expected_intervals_for_local_day(spring, "Europe/Berlin", QUARTER_HOURLY_SECONDS) == 92
    assert expected_intervals_for_local_day(autumn, "Europe/Berlin", QUARTER_HOURLY_SECONDS) == 100


def test_expected_intervals_per_utc_day_is_constant_and_dst_free():
    assert expected_intervals_for_utc_day(HOURLY_SECONDS) == 24
    assert expected_intervals_for_utc_day(QUARTER_HOURLY_SECONDS) == 96
    with pytest.raises(DataContractViolation):
        expected_intervals_for_utc_day(7000)


# ---------------------------------------------------------------------------
# UTC days vs local days: the two contracts genuinely differ
# ---------------------------------------------------------------------------


def test_utc_days_stay_24_hours_across_a_dst_transition():
    """The transition that shortens a local day leaves every UTC day at 24."""
    index = pd.date_range("2024-03-29", "2024-04-02", freq="h", tz="UTC", inclusive="left")
    counts = utc_day_counts(index)
    assert set(counts.values) == {24}
    violations, n_checked, _ = check_utc_day_counts(index)
    assert violations == []
    assert n_checked == 4


def test_local_day_counts_see_23_and_25_hour_days_and_accept_them():
    index = pd.date_range("2024-03-29", "2024-04-02", freq="h", tz="UTC", inclusive="left")
    counts = local_day_counts(index, "Europe/Berlin")
    assert counts.loc[dt.date(2024, 3, 31)] == 23
    violations, n_checked, n_dst = check_local_day_counts(index, "Europe/Berlin")
    assert violations == []
    assert n_dst == 1
    assert n_checked >= 3


def test_local_day_contract_rejects_a_23_hour_day_that_is_not_a_transition():
    """A short local day on an ordinary date is a violation, not a DST day.

    This is the whitelist working in the direction that matters: dropping an
    hour of real data must not be excused as "probably DST".
    """
    index = pd.date_range("2024-06-01", "2024-06-05", freq="h", tz="UTC", inclusive="left")
    # Drop 2024-06-03 10:00 local (08:00Z), an ordinary 24h local day.
    index = index.delete(index.get_loc(pd.Timestamp("2024-06-03T08:00Z")))
    violations, _, _ = check_local_day_counts(index, "Europe/Berlin")
    assert len(violations) == 1
    assert violations[0].day == dt.date(2024, 6, 3)
    assert (violations[0].expected, violations[0].actual) == (24, 23)
    assert "DST transition" not in violations[0].note


def test_utc_day_contract_catches_a_dropped_hour():
    index = _hourly_index("2024-06-01", 96)
    index = index.delete(index.get_loc(pd.Timestamp("2024-06-02T05:00Z")))
    violations, _, _ = check_utc_day_counts(index)
    assert [v.day for v in violations] == [dt.date(2024, 6, 2)]
    assert (violations[0].expected, violations[0].actual) == (24, 23)


def test_boundary_days_are_reported_not_counted_as_violations():
    """A series starting mid-UTC-day must not report that day as short."""
    index = pd.date_range("2024-06-01T05:00Z", "2024-06-04T00:00Z", freq="h", tz="UTC")
    violations, n_checked, boundary = check_utc_day_counts(index)
    assert violations == []
    assert "2024-06-01" in boundary
    assert n_checked == 2


def test_leap_year_february_29_is_present_and_checked():
    index = pd.date_range("2020-02-28", "2020-03-02", freq="h", tz="UTC", inclusive="left")
    counts = utc_day_counts(index)
    assert counts.loc[dt.date(2020, 2, 29)] == 24
    assert check_utc_day_counts(index)[0] == []


def test_index_is_utc_rejects_naive_and_local_indices():
    assert index_is_utc(_hourly_index("2024-01-01", 24))
    assert not index_is_utc(pd.date_range("2024-01-01", periods=24, freq="h"))
    assert not index_is_utc(
        pd.date_range("2024-01-01", periods=24, freq="h", tz="Europe/Berlin")
    )


# ---------------------------------------------------------------------------
# Gap report
# ---------------------------------------------------------------------------


def test_gap_report_is_empty_on_a_clean_series():
    gaps, n_missing, max_hours = gap_report(_hourly_index("2024-01-01", 500))
    assert (gaps, n_missing, max_hours) == ([], 0, 0.0)


def test_gap_report_counts_missing_intervals_and_locates_them():
    index = _hourly_index("2024-01-01", 100)
    keep = index.delete([10, 11, 12])          # a 3-hour hole
    gaps, n_missing, max_hours = gap_report(keep)
    assert n_missing == 3
    assert len(gaps) == 1
    assert gaps[0].after_utc == index[9]
    assert gaps[0].before_utc == index[13]
    assert gaps[0].missing_intervals == 3
    assert max_hours == 4.0


def test_gap_report_does_not_call_the_15min_cutover_one_huge_gap():
    """A legitimate resolution change must not be reported as missing data."""
    cutover = pd.Timestamp("2025-09-30T22:00Z")
    hourly = pd.date_range(pd.Timestamp("2025-09-29T00:00Z"), cutover, freq="h")
    quarter = pd.date_range(cutover, periods=200, freq="15min")
    index = hourly.union(quarter)
    gaps, n_missing, _ = gap_report(index)
    assert gaps == []
    assert n_missing == 0


def test_duplicate_timestamps_are_detected():
    index = _hourly_index("2024-01-01", 48)
    doubled = index.append(pd.DatetimeIndex([index[5]])).sort_values()
    report = build_contract_report("DE-LU", _frame(doubled))
    assert report.n_duplicate_timestamps == 1
    assert not report.ok
    assert any("duplicate" in v for v in report.violations)


# ---------------------------------------------------------------------------
# Resolution segments, changes, and the 2025-10-01 cutover
# ---------------------------------------------------------------------------


def test_modal_resolution_and_single_segment_on_clean_hourly_data():
    index = _hourly_index("2024-01-01", 1000)
    assert modal_resolution_seconds(index) == 3600
    segments = resolution_segments(index)
    assert len(segments) == 1
    assert (segments[0].seconds, segments[0].n_intervals) == (3600, 999)
    assert detect_resolution_changes(index) == []


def test_resolution_change_at_the_cutover_is_detected_with_the_right_instant():
    """Synthetic hourly -> 15-minute step at the SDAC go-live (local midnight)."""
    cutover = cutover_instant_utc("Europe/Berlin", "2025-10-01")
    assert cutover == pd.Timestamp("2025-09-30T22:00:00Z")  # CEST = UTC+2

    hourly = pd.date_range(pd.Timestamp("2025-09-20T00:00Z"), cutover, freq="h",
                           inclusive="left")
    quarter = pd.date_range(cutover, periods=480, freq="15min")
    index = hourly.append(quarter)

    changes = detect_resolution_changes(index)
    assert len(changes) == 1
    assert changes[0].at_utc == cutover
    assert (changes[0].from_seconds, changes[0].to_seconds) == (3600, 900)

    problems, _ = check_resolution_cutover(index, "Europe/Berlin")
    assert problems == []


def test_a_resolution_change_before_the_cutover_is_a_violation():
    early = pd.Timestamp("2024-06-01T00:00Z")
    hourly = pd.date_range(pd.Timestamp("2024-05-20T00:00Z"), early, freq="h",
                           inclusive="left")
    quarter = pd.date_range(early, periods=480, freq="15min")
    index = hourly.append(quarter)
    problems, changes = check_resolution_cutover(index, "Europe/Berlin")
    assert len(changes) == 1
    assert len(problems) == 1
    assert "2024-06-01T00:00:00+00:00" in problems[0]
    assert "SDAC 15-minute go-live" in problems[0]


def test_a_single_missing_hour_is_not_mistaken_for_a_resolution_change():
    index = _hourly_index("2024-01-01", 200).delete(50)
    assert detect_resolution_changes(index) == []
    assert gap_report(index)[1] == 1


def test_cutover_instant_is_local_midnight_not_utc_midnight():
    """The market time unit changes on a market *day*, which is local."""
    assert cutover_instant_utc("Europe/Berlin", "2025-10-01") == pd.Timestamp("2025-09-30T22:00Z")
    assert cutover_instant_utc("Europe/Madrid", "2025-10-01") == pd.Timestamp("2025-09-30T22:00Z")
    # A winter date, to show the offset is read from the tz database, not fixed.
    assert cutover_instant_utc("Europe/Berlin", "2025-01-15") == pd.Timestamp("2025-01-14T23:00Z")


def test_full_contract_report_passes_on_a_clean_synthetic_year_and_names_failures():
    clean = pd.date_range("2024-01-01", "2025-01-01", freq="h", tz="UTC", inclusive="left")
    report = build_contract_report("DE-LU", _frame(clean))
    assert report.ok, report.violations
    assert report.n_utc_days_checked == 366          # 2024 is a leap year
    assert report.n_dst_days_seen == 2
    assert_contract(report)                           # must not raise

    broken = build_contract_report("DE-LU", _frame(clean.delete([100, 101])))
    assert not broken.ok
    with pytest.raises(DataContractViolation) as excinfo:
        assert_contract(broken)
    assert "missing interval" in str(excinfo.value)


def test_nan_prices_are_a_contract_violation():
    index = _hourly_index("2024-01-01", 72)
    values = [1.0] * 72
    values[30] = float("nan")
    report = build_contract_report("DE-LU", _frame(index, values))
    assert report.n_nan_prices == 1
    assert not report.ok
    assert report.nan_timestamps_utc == [index[30].isoformat()]


def test_contract_report_round_trips_through_json():
    index = _hourly_index("2024-01-01", 100)
    report = build_contract_report("DE-LU", _frame(index))
    restored = json.loads(json.dumps(report.as_dict()))
    assert restored["zone"] == "DE-LU"
    assert restored["modal_resolution_seconds"] == 3600
    assert isinstance(restored["dst_whitelist_days"], dict)


# ---------------------------------------------------------------------------
# The stitching loader
# ---------------------------------------------------------------------------


def test_stitching_two_local_year_files_closes_the_year_boundary_hour(cache_config, tmp_path):
    """The whole point of NOTE C1-02: 2023-12-31T23:00Z lives in the 2024 file.

    Per-UTC-year truncation would leave a one-hour hole at every year boundary;
    stitching the untruncated files must not.
    """
    _write_cache(tmp_path, "DE-LU", 2023, _local_year_payload(2023))
    _write_cache(tmp_path, "DE-LU", 2024, _local_year_payload(2024))

    frame = load_zone_series("DE-LU", [2023, 2024], cache_config)
    assert frame.index[0] == pd.Timestamp("2022-12-31T23:00Z")
    assert frame.index[-1] == pd.Timestamp("2024-12-31T22:00Z")
    assert pd.Timestamp("2023-12-31T23:00Z") in frame.index
    deltas = pd.Series(frame.index).diff().dropna().dt.total_seconds().unique()
    assert list(deltas) == [3600.0]

    report = build_contract_report("DE-LU", frame)
    assert report.ok, report.violations
    assert report.n_missing_intervals == 0


def test_stitched_series_passes_the_contract_for_a_dst_heavy_span(cache_config, tmp_path):
    for year in (2023, 2024):
        _write_cache(tmp_path, "DE-LU", year, _local_year_payload(year))
    frame = load_zone_series("DE-LU", [2023, 2024], cache_config)
    report = build_contract_report("DE-LU", frame)
    assert report.n_dst_days_seen == 4          # two years x two transitions
    assert report.local_day_violations == []
    assert report.utc_day_violations == []


def test_loader_refuses_a_year_that_is_not_cached(cache_config, tmp_path):
    _write_cache(tmp_path, "DE-LU", 2024, _local_year_payload(2024))
    with pytest.raises(PriceDataError, match="not cached"):
        load_zone_series("DE-LU", [2023, 2024], cache_config)


def test_loader_refuses_an_unknown_zone(cache_config, tmp_path):
    _write_cache(tmp_path, "DE-LU", 2024, _local_year_payload(2024))
    with pytest.raises(PriceDataError, match="unknown zone"):
        load_zone_series("ZZ-NOPE", [2024], cache_config)


def test_loader_refuses_to_load_a_sealed_year(cache_config, tmp_path):
    """Even with a sealed-year file sitting in the cache, the loader says no."""
    _write_cache(tmp_path, "DE-LU", 2024, _local_year_payload(2024))
    _write_cache(tmp_path, "DE-LU", 2025, _local_year_payload(2025))
    with pytest.raises(SealedHoldoutError):
        load_zone_series("DE-LU", [2024, 2025], cache_config)


def test_loader_never_fills_a_gap_it_finds(cache_config, tmp_path):
    """A hole in the source must survive loading, so the contract can see it."""
    payload = _local_year_payload(2024)
    del payload["unix_seconds"][100:103]
    del payload["price"][100:103]
    _write_cache(tmp_path, "DE-LU", 2024, payload)
    frame = load_zone_series("DE-LU", [2024], cache_config)
    report = build_contract_report("DE-LU", frame)
    assert report.n_missing_intervals == 3
    assert not report.ok


def test_duplicate_timestamps_with_conflicting_prices_raise(cache_config, tmp_path):
    a = _local_year_payload(2024)
    overlap = {
        "unix_seconds": a["unix_seconds"][:5],
        "price": [p + 999.0 for p in a["price"][:5]],
        "unit": "EUR / MWh",
        "deprecated": False,
    }
    _write_cache(tmp_path, "DE-LU", 2024, a)
    _write_cache(tmp_path, "DE-LU", 2023, overlap)
    with pytest.raises(PriceDataError, match="different prices"):
        load_zone_series("DE-LU", [2023, 2024], cache_config)


def test_identical_overlapping_timestamps_are_collapsed_quietly(cache_config, tmp_path):
    a = _local_year_payload(2024)
    overlap = {
        "unix_seconds": a["unix_seconds"][:5],
        "price": a["price"][:5],
        "unit": "EUR / MWh",
        "deprecated": False,
    }
    _write_cache(tmp_path, "DE-LU", 2024, a)
    _write_cache(tmp_path, "DE-LU", 2023, overlap)
    frame = load_zone_series("DE-LU", [2023, 2024], cache_config)
    assert frame.index.is_unique
    assert frame.attrs["stitch_report"].n_duplicate_timestamps == 5


def test_utc_years_only_trims_to_whole_utc_years(cache_config, tmp_path):
    _write_cache(tmp_path, "DE-LU", 2024, _local_year_payload(2024))
    frame = load_zone_series("DE-LU", [2024], cache_config, utc_years_only=True)
    assert frame.index[0] == pd.Timestamp("2024-01-01T00:00Z")
    assert frame.index[-1] == pd.Timestamp("2024-12-31T22:00Z")  # 23:00Z is in file 2025


def test_wide_prices_aligns_zones_on_one_utc_index(cache_config, tmp_path):
    _write_cache(tmp_path, "DE-LU", 2024, _local_year_payload(2024))
    _write_cache(tmp_path, "NO2", 2024, _local_year_payload(2024, tz="Europe/Oslo"))
    panel = {
        "DE-LU": load_zone_series("DE-LU", [2024], cache_config),
        "NO2": load_zone_series("NO2", [2024], cache_config),
    }
    wide = wide_prices(panel)
    assert list(wide.columns) == ["DE-LU", "NO2"]
    assert wide.index.tz is not None
    assert wide.notna().all().all()


# ---------------------------------------------------------------------------
# Hourly aggregation
# ---------------------------------------------------------------------------


def test_hourly_aggregation_is_the_mean_of_the_four_quarter_hours():
    index = pd.date_range("2025-10-01T00:00Z", periods=8, freq="15min", tz="UTC")
    frame = pd.DataFrame({PRICE: [10.0, 20.0, 30.0, 40.0, -5.0, -5.0, 5.0, 5.0]}, index=index)
    hourly = to_hourly(frame)
    assert list(hourly.index) == [
        pd.Timestamp("2025-10-01T00:00Z"),
        pd.Timestamp("2025-10-01T01:00Z"),
    ]
    assert hourly[PRICE].tolist() == [25.0, 0.0]
    report = hourly.attrs["aggregation_report"]
    assert report.intervals_per_hour == 4
    assert report.volume_weighted is False
    assert "NOT volume-weighted" in report.method


def test_hourly_aggregation_is_idempotent_on_hourly_input():
    index = _hourly_index("2024-01-01", 48)
    frame = _frame(index)
    hourly = to_hourly(frame)
    pd.testing.assert_frame_equal(hourly, frame)
    assert hourly.attrs["aggregation_report"].intervals_per_hour == 1


def test_aggregation_refuses_a_partial_hour_by_default():
    index = pd.date_range("2025-10-01T00:00Z", periods=7, freq="15min", tz="UTC")
    frame = pd.DataFrame({PRICE: [1.0] * 7}, index=index)
    with pytest.raises(DataContractViolation, match="partial hour"):
        to_hourly(frame)
    flagged = to_hourly(frame, on_partial="flag")
    assert flagged[PRICE].isna().sum() == 1
    assert flagged.attrs["aggregation_report"].n_partial_hours == 1


def test_volume_weighted_aggregation_uses_the_supplied_weights():
    index = pd.date_range("2025-10-01T00:00Z", periods=4, freq="15min", tz="UTC")
    frame = pd.DataFrame({PRICE: [0.0, 0.0, 0.0, 100.0]}, index=index)
    volume = pd.Series([1.0, 1.0, 1.0, 3.0], index=index)
    assert to_hourly(frame)[PRICE].iloc[0] == 25.0                 # unweighted
    assert to_hourly(frame, volume=volume)[PRICE].iloc[0] == 50.0  # 300/6


def test_volume_weighting_refuses_incomplete_or_zero_volumes():
    index = pd.date_range("2025-10-01T00:00Z", periods=4, freq="15min", tz="UTC")
    frame = pd.DataFrame({PRICE: [1.0, 2.0, 3.0, 4.0]}, index=index)
    partial = pd.Series([1.0, 1.0, 1.0], index=index[:3])
    with pytest.raises(DataContractViolation, match="does not cover"):
        to_hourly(frame, volume=partial)
    with pytest.raises(DataContractViolation, match="zero total volume"):
        to_hourly(frame, volume=pd.Series([0.0] * 4, index=index))


def test_aggregation_groups_by_utc_hour_across_a_dst_transition():
    """Local time must never be the resampling key (CLAUDE.md)."""
    index = pd.date_range("2025-10-26T00:00Z", periods=16, freq="15min", tz="UTC")
    frame = pd.DataFrame({PRICE: [float(i) for i in range(16)]}, index=index)
    hourly = to_hourly(frame)
    assert len(hourly) == 4
    assert list(hourly.index) == list(pd.date_range("2025-10-26T00:00Z", periods=4,
                                                    freq="h", tz="UTC"))
    assert hourly[PRICE].tolist() == [1.5, 5.5, 9.5, 13.5]


def test_aggregation_rejects_naive_indices_and_non_dividing_resolutions():
    naive = pd.DataFrame({PRICE: [1.0, 2.0]},
                         index=pd.date_range("2024-01-01", periods=2, freq="15min"))
    with pytest.raises(DataContractViolation, match="tz-aware"):
        to_hourly(naive)
    odd = pd.DataFrame(
        {PRICE: [1.0] * 5},
        index=pd.date_range("2024-01-01", periods=5, freq="7min", tz="UTC"),
    )
    with pytest.raises(DataContractViolation, match="does not divide an hour"):
        to_hourly(odd)


def test_payload_fingerprint_is_reproducible_and_price_sensitive():
    """The fingerprint tracks the data, not the file (see the C2 note on raw_sha256)."""
    from data.contracts import payload_fingerprint

    index = _hourly_index("2024-01-01", 48)
    base = _frame(index)
    assert payload_fingerprint(base) == payload_fingerprint(_frame(index))

    nudged = base.copy()
    nudged.iloc[10, 0] += 0.001
    assert payload_fingerprint(nudged) != payload_fingerprint(base)

    shifted = base.copy()
    shifted.index = index + pd.Timedelta(hours=1)
    assert payload_fingerprint(shifted) != payload_fingerprint(base)

    with_nan = base.copy()
    with_nan.iloc[5, 0] = float("nan")
    assert payload_fingerprint(with_nan) == payload_fingerprint(with_nan.copy())
