"""C1 unit tests for the config / holdout-guard / client / manifest layer.

These are unit tests over pure helpers and synthetic payloads — no network, no
real price data. The *data contract* tests (expected rows per day, DST
whitelist, resolution-change detection at the 2025-10-01 cutover, gap report)
are C2's job and live in their own file.

Nothing here may be weakened to make a failure go away: per CLAUDE.md, a red
test in this repo is evidence the code is wrong, and editing a test requires a
FLAG in PROGRESS.md and a stop for human review.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from data import config as config_mod
from data import contracts as contracts_mod
from data import energy_charts as ec
from data import holdout as holdout_mod
from data import manifest as manifest_mod

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_nine_zones_three_tier_a():
    zones = config_mod.load_zones()
    assert len(zones) == 9
    assert [z.key for z in config_mod.zones_for_tier("A")] == ["DE-LU", "ES", "NO2"]
    assert len(config_mod.zones_for_tier("B")) == 6


def test_every_zone_has_a_bzn_and_iana_timezone():
    for zone in config_mod.load_zones().values():
        assert zone.bzn
        assert "/" in zone.local_tz, f"{zone.key}: local_tz must be an IANA name"


def test_fetch_years_overlaps_the_sealed_holdout_now_that_it_is_unsealed():
    """Checkpoint C (2026-10-12): fetch_years was extended to include 2025,
    exactly as docs/checkpoint_c.md §4(b) requires, because entsoe.exogenous_years()
    derives from this list. This is the real repo's actual, permanent post-unseal
    state — holdout.years stays {2025} by declaration; fetch_years including 2025
    is now correct, not a leak, because holdout_is_unsealed() is True. The
    synthetic, config_dir-isolated tests below cover the refuse/allow logic
    itself without depending on this repo's real, one-way PROGRESS.md state.
    """
    cfg = config_mod.load_data_config()
    assert config_mod.sealed_years() == {2025}
    assert set(cfg["fetch_years"]) & config_mod.sealed_years() == {2025}
    assert holdout_mod.holdout_is_unsealed() is True


def _write_minimal_data_yaml(config_dir, *, sealed_year: int, fetch_years: list[int]) -> str:
    """A synthetic, minimal-but-valid data.yaml isolated from the real repo's.

    Returns the marker string, so a test can write it (or not) into its own
    synthetic PROGRESS.md.
    """
    marker = "TEST MARKER — not the real repo's, see config/data.yaml"
    (config_dir / "data.yaml").write_text(
        f"""
splits:
  holdout:
    years: [{sealed_year}]
    sealed: true
fetch_years: {fetch_years}
holdout_unseal_marker: {marker!r}
sources: {{}}
time: {{}}
""",
        encoding="utf-8",
    )
    return marker


def test_load_data_config_refuses_fetch_years_overlap_when_not_unsealed(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_minimal_data_yaml(config_dir, sealed_year=9999, fetch_years=[2020, 9999])
    progress = tmp_path / "PROGRESS.md"
    progress.write_text("### no marker here\n", encoding="utf-8")

    with pytest.raises(config_mod.ConfigError, match="fetch_years overlaps"):
        config_mod.load_data_config(config_dir=config_dir, progress_path=progress)


def test_load_data_config_allows_fetch_years_overlap_when_unsealed(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    marker = _write_minimal_data_yaml(config_dir, sealed_year=9999, fetch_years=[2020, 9999])
    progress = tmp_path / "PROGRESS.md"
    progress.write_text(f"### approved\n{marker}\n", encoding="utf-8")

    cfg = config_mod.load_data_config(config_dir=config_dir, progress_path=progress)
    assert cfg["fetch_years"] == [2020, 9999]


def test_load_data_config_still_refuses_when_marker_only_quoted_in_prose(tmp_path):
    """The same hardening as Checkpoint A's holdout_is_unsealed() fix, duplicated
    here deliberately (see the comment in data/config.py) — the marker embedded
    in a sentence must not count as unsealing the overlap check either."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    marker = _write_minimal_data_yaml(config_dir, sealed_year=9999, fetch_years=[9999])
    progress = tmp_path / "PROGRESS.md"
    progress.write_text(f"The marker is {marker!r}, quoted, not alone.\n", encoding="utf-8")

    with pytest.raises(config_mod.ConfigError, match="fetch_years overlaps"):
        config_mod.load_data_config(config_dir=config_dir, progress_path=progress)


def test_data_config_and_holdout_module_agree_on_the_marker_check(tmp_path):
    """load_data_config()'s inline marker check (data/config.py) and
    data.holdout.holdout_is_unsealed() are two independent implementations of
    the same rule, kept that way only to avoid the recursive import described in
    data/config.py's comment. This test is what keeps them from drifting apart.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    marker = _write_minimal_data_yaml(config_dir, sealed_year=9999, fetch_years=[9999])

    sealed = tmp_path / "sealed.md"
    sealed.write_text("no marker\n", encoding="utf-8")
    assert holdout_mod.holdout_is_unsealed(progress_path=sealed, config_dir=config_dir) is False
    with pytest.raises(config_mod.ConfigError):
        config_mod.load_data_config(config_dir=config_dir, progress_path=sealed)

    unsealed = tmp_path / "unsealed.md"
    unsealed.write_text(f"{marker}\n", encoding="utf-8")
    assert holdout_mod.holdout_is_unsealed(progress_path=unsealed, config_dir=config_dir) is True
    config_mod.load_data_config(config_dir=config_dir, progress_path=unsealed)  # does not raise


def test_config_hash_is_stable_and_short():
    first = config_mod.config_hash()
    assert first == config_mod.config_hash()
    assert len(first) == 16


# ---------------------------------------------------------------------------
# sealed-holdout guard
# ---------------------------------------------------------------------------


def test_non_sealed_year_passes_guard():
    holdout_mod.assert_not_sealed(2024, "test")


@pytest.mark.parametrize("years", [2025, {2024, 2025}, [2025, 2026]])
def test_sealed_year_is_refused_when_not_unsealed(years, tmp_path):
    """Checkpoint C (2026-10-12) unsealed the real repo's 2025 holdout, so this
    no longer refuses against the default (real) PROGRESS.md — see
    test_sealed_year_is_permitted_now_that_the_holdout_is_unsealed below for
    that. The refuse mechanism itself is still real and still tested here,
    against a synthetic "not yet unsealed" PROGRESS.md so coverage of it does
    not depend on this repo's own, now one-way, unseal event.
    """
    still_sealed = tmp_path / "PROGRESS.md"
    still_sealed.write_text("### no marker here\n", encoding="utf-8")
    with pytest.raises(holdout_mod.SealedHoldoutError):
        holdout_mod.assert_not_sealed(years, "test", progress_path=still_sealed)


def test_sealed_year_is_permitted_now_that_the_holdout_is_unsealed():
    """The flip side of the test above, against the real (now unsealed)
    PROGRESS.md: this must NOT raise, because C17 depends on it not raising."""
    holdout_mod.assert_not_sealed(2025, "test")  # does not raise


def test_range_spanning_into_the_holdout_is_refused_when_not_unsealed(tmp_path):
    still_sealed = tmp_path / "PROGRESS.md"
    still_sealed.write_text("### no marker here\n", encoding="utf-8")
    with pytest.raises(holdout_mod.SealedHoldoutError):
        holdout_mod.assert_range_not_sealed(
            dt.date(2024, 12, 20), dt.date(2025, 1, 3), "test", progress_path=still_sealed
        )


def test_range_spanning_into_the_holdout_is_permitted_now_that_unsealed():
    holdout_mod.assert_range_not_sealed(
        dt.date(2024, 12, 20), dt.date(2025, 1, 3), "test"
    )  # does not raise


def test_repo_progress_file_now_unseals_the_holdout():
    """Was the Checkpoint A/B/C16-era tripwire: 'this must stay False until a
    human writes the marker at C16.' A human did, at Checkpoint C, 2026-10-12
    — see the "Checkpoint C — approved, holdout unsealed" entry in PROGRESS.md.
    This now asserts the marker is present and recognised, the mirror image of
    the old tripwire, so a future accidental removal of that line is still
    caught."""
    assert holdout_mod.holdout_is_unsealed() is True


def test_guard_opens_only_when_the_exact_marker_is_present(tmp_path):
    marker = holdout_mod.unseal_marker()
    almost = tmp_path / "almost.md"
    almost.write_text(
        "### C16\n- checkpoint c approved, holdout unsealed maybe\n", encoding="utf-8"
    )
    with pytest.raises(holdout_mod.SealedHoldoutError):
        holdout_mod.assert_not_sealed(2025, "test", progress_path=almost)

    approved = tmp_path / "approved.md"
    # Explicit encoding: holdout_is_unsealed() reads as UTF-8, and Path.write_text
    # without one uses the platform locale encoding (cp1252 on Windows), which
    # cannot round-trip the em-dash below — this broke only on a Windows runner.
    approved.write_text(f"### C16 — human review\n{marker}\n", encoding="utf-8")
    holdout_mod.assert_not_sealed(2025, "test", progress_path=approved)


def test_guard_stays_shut_when_the_marker_is_only_quoted_in_prose(tmp_path):
    """Checkpoint A hardening: the marker must stand alone on its own line.

    Before this hardening, holdout_is_unsealed() was a plain substring search,
    so a cycle writing a log entry that *mentions* the marker string — exactly
    what this test file and PROGRESS.md itself both have reason to do — could
    unseal the holdout by accident. This is that near-miss, made permanent.
    """
    marker = holdout_mod.unseal_marker()
    quoted_in_prose = tmp_path / "quoted.md"
    quoted_in_prose.write_text(
        "### C2 checkpoint\n"
        f"The unseal marker is the exact string {marker!r}, which only a human "
        "writes, on its own line, after Checkpoint C.\n",
        encoding="utf-8",
    )
    assert holdout_mod.holdout_is_unsealed(progress_path=quoted_in_prose) is False
    with pytest.raises(holdout_mod.SealedHoldoutError):
        holdout_mod.assert_not_sealed(2025, "test", progress_path=quoted_in_prose)

    # Same marker, but with leading/trailing whitespace on its own line, still
    # counts — the check strips the line before comparing.
    padded = tmp_path / "padded.md"
    padded.write_text(f"### C16\n   {marker}   \n")
    assert holdout_mod.holdout_is_unsealed(progress_path=padded) is True


# ---------------------------------------------------------------------------
# client: request shape, validation, parsing
# ---------------------------------------------------------------------------


def test_request_never_names_a_date_outside_the_requested_year():
    zone = config_mod.load_zones()["DE-LU"]
    url, params = ec.price_request(zone, 2024)
    assert url.endswith("/price")
    assert params == {"bzn": "DE-LU", "start": "2024-01-01", "end": "2024-12-31"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        "Acknowledgement_MarketDocument",
        {"price": [1.0]},
        {"unix_seconds": [1704067200]},
        {"unix_seconds": [], "price": []},
        {"unix_seconds": [1704067200, 1704070800], "price": [1.0]},
        {"unix_seconds": [1704070800, 1704067200], "price": [1.0, 2.0]},
        {"unix_seconds": [1704067200, 1704067200], "price": [1.0, 2.0]},
        {"unix_seconds": ["1704067200"], "price": [1.0]},
        {"unix_seconds": [1704067200], "price": ["cheap"]},
        {"unix_seconds": [1704067200], "price": [1.0], "deprecated": True},
        {"unix_seconds": [1704067200], "price": [1.0], "unit": "ct/kWh"},
    ],
)
def test_malformed_payloads_are_flagged_not_swallowed(payload):
    with pytest.raises(ec.UnexpectedResponse):
        ec.validate_payload(payload, "test")


def test_well_formed_payload_parses_to_utc_index_and_keeps_negative_prices():
    payload = {
        "unix_seconds": [1704067200, 1704070800, 1704074400],
        "price": [10.0, -5.5, 0.0],
        "unit": "EUR / MWh",
        "deprecated": False,
    }
    frame = ec.payload_to_frame(payload, 2024, "test")
    assert str(frame.index.tz) == "UTC"
    assert frame.index[0] == pd.Timestamp("2024-01-01T00:00:00Z")
    assert list(frame[ec.PRICE_COLUMN]) == [10.0, -5.5, 0.0]
    assert frame.attrs["n_out_of_window"] == 0


def test_points_outside_the_requested_year_are_dropped_by_timestamp_and_counted():
    payload = {
        "unix_seconds": [1704067200, 1735689600],  # 2024-01-01T00Z, 2025-01-01T00Z
        "price": [10.0, 999.0],
        "unit": "EUR / MWh",
    }
    frame = ec.payload_to_frame(payload, 2024, "test")
    assert len(frame) == 1
    assert frame.attrs["n_out_of_window"] == 1
    assert frame.index.max() < pd.Timestamp("2025-01-01T00:00:00Z")


def test_payload_with_nothing_inside_the_year_is_flagged():
    payload = {"unix_seconds": [1735689600], "price": [1.0], "unit": "EUR / MWh"}
    with pytest.raises(ec.UnexpectedResponse):
        ec.payload_to_frame(payload, 2024, "test")


# ---------------------------------------------------------------------------
# client: cache behaviour (no real network anywhere)
# ---------------------------------------------------------------------------


class _ExplodingSession:
    """Any HTTP call is a test failure."""

    def get(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("fetch_year made a request for an already-cached file")


class _StubResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.url = "https://api.energy-charts.info/price?stub=1"

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _StubSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def _config_with_cache(tmp_path):
    cfg = json.loads(json.dumps(config_mod.load_data_config()))
    cfg["sources"]["energy_charts"]["cache_dir"] = str(tmp_path / "cache")
    cfg["sources"]["energy_charts"]["request"]["sleep_between_requests_seconds"] = 0
    cfg["sources"]["energy_charts"]["request"]["retry_backoff_seconds"] = [0, 0, 0]
    return cfg


def test_cached_file_is_never_refetched(tmp_path):
    cfg = _config_with_cache(tmp_path)
    path = ec.cache_path("DE-LU", 2024, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"unix_seconds": [1704067200], "price": [1.0], "unit": "EUR / MWh"}
    ))
    returned, downloaded = ec.fetch_year("DE-LU", 2024, cfg, session=_ExplodingSession())
    assert returned == path
    assert downloaded is False


def test_404_raises_immediately_without_retrying(tmp_path):
    cfg = _config_with_cache(tmp_path)
    session = _StubSession(_StubResponse(404, text="Not Found"))
    with pytest.raises(ec.UnexpectedResponse):
        ec.fetch_year("DE-LU", 2024, cfg, session=session)
    assert session.calls == 1
    assert not ec.cache_path("DE-LU", 2024, cfg).exists()


def test_server_error_is_retried_then_reported_as_a_failure(tmp_path):
    cfg = _config_with_cache(tmp_path)
    session = _StubSession(_StubResponse(503, text="busy"))
    with pytest.raises(ec.FetchFailed):
        ec.fetch_year("DE-LU", 2024, cfg, session=session)
    assert session.calls == cfg["sources"]["energy_charts"]["request"]["max_retries"]


def test_a_bad_payload_is_never_written_to_the_cache(tmp_path):
    cfg = _config_with_cache(tmp_path)
    session = _StubSession(_StubResponse(200, payload={"unix_seconds": [1], "price": []}))
    with pytest.raises(ec.UnexpectedResponse):
        ec.fetch_year("DE-LU", 2024, cfg, session=session)
    assert not ec.cache_path("DE-LU", 2024, cfg).exists()


def test_successful_fetch_writes_cache_with_provenance(tmp_path):
    cfg = _config_with_cache(tmp_path)
    payload = {"unix_seconds": [1704067200, 1704070800], "price": [7.0, -1.0],
               "unit": "EUR / MWh", "deprecated": False, "license_info": "CC BY 4.0"}
    session = _StubSession(_StubResponse(200, payload=payload))
    path, downloaded = ec.fetch_year("DE-LU", 2024, cfg, session=session,
                                    sleep_after=False)
    assert downloaded is True
    stored = json.loads(path.read_text())
    assert stored["_fetch_meta"]["zone_key"] == "DE-LU"
    assert stored["_fetch_meta"]["year"] == 2024
    assert stored["_fetch_meta"]["fetched_at_utc"].endswith("+00:00")
    frame = ec.read_cached_year("DE-LU", 2024, cfg)
    assert list(frame[ec.PRICE_COLUMN]) == [7.0, -1.0]


def test_fetching_2025_now_succeeds_past_the_holdout_guard(tmp_path):
    """Was test_fetching_a_sealed_year_is_refused_before_any_request. fetch_year
    and read_cached_year call holdout.assert_not_sealed() with no progress_path
    override, so they always check this repo's real PROGRESS.md and cannot be
    pointed at a synthetic one — unlike the lower-level guard tests above, this
    one can only test against real state, and that state changed at Checkpoint C
    (2026-10-12). Rather than only prove the guard no longer blocks (which the
    weaker version of this fix would do by hitting _ExplodingSession's trap),
    this runs a complete, successful fetch of 2025 — the thing C17 actually
    needs to work, with a stub session rather than the real network, mirroring
    test_fetch_year_caches_a_successful_response above it for 2024.
    """
    cfg = _config_with_cache(tmp_path)
    payload = {"unix_seconds": [1735689600, 1735693200], "price": [3.0, -2.0],
               "unit": "EUR / MWh", "deprecated": False, "license_info": "CC BY 4.0"}
    session = _StubSession(_StubResponse(200, payload=payload))
    path, downloaded = ec.fetch_year("DE-LU", 2025, cfg, session=session, sleep_after=False)
    assert downloaded is True
    stored = json.loads(path.read_text())
    assert stored["_fetch_meta"]["year"] == 2025
    frame = ec.read_cached_year("DE-LU", 2025, cfg)
    assert list(frame[ec.PRICE_COLUMN]) == [3.0, -2.0]


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "year,resolution,expected",
    [(2019, 3600, 8760), (2020, 3600, 8784), (2024, 3600, 8784),
     (2023, 3600, 8760), (2024, 900, 35136), (2019, 900, 35040)],
)
def test_expected_points_matches_utc_year_length(year, resolution, expected):
    assert manifest_mod.expected_points(year, resolution) == expected


def _synthetic_year(tmp_path, zone="DE-LU", year=2023, n_negative=5, n_nan=3):
    """Write a full hourly year of synthetic prices into a temp cache."""
    cfg = _config_with_cache(tmp_path)
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    n = manifest_mod.expected_points(year, 3600)
    seconds = [int((start + pd.Timedelta(hours=i)).timestamp()) for i in range(n)]
    prices: list[float | None] = [50.0 + (i % 24) for i in range(n)]
    for i in range(n_negative):
        prices[100 + i] = -10.0 - i
    for i in range(n_nan):
        prices[500 + i] = None
    prices[900] = 0.0
    path = ec.cache_path(zone, year, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "_fetch_meta": {"url": "https://api.energy-charts.info/price?stub=1",
                        "fetched_at_utc": "2026-01-01T00:00:00+00:00"},
        "unix_seconds": seconds, "price": prices, "unit": "EUR / MWh",
    }))
    return cfg, path, n


def test_manifest_row_counts_negatives_nans_and_coverage(tmp_path):
    cfg, path, n = _synthetic_year(tmp_path)
    row = manifest_mod.summarise_year("DE-LU", 2023, cfg)
    assert row["zone"] == "DE-LU" and row["tier"] == "A" and row["year"] == 2023
    assert row["n_points"] == n == 8760
    assert row["n_expected_points"] == 8760
    assert row["coverage_ratio"] == 1.0
    assert row["resolution_seconds"] == 3600
    assert row["n_gap_intervals"] == 0
    assert row["n_negative"] == 5
    assert row["n_nan"] == 3
    assert row["n_zero"] == 1
    assert row["price_min"] == -14.0
    assert row["first_ts_utc"].startswith("2023-01-01T00:00:00")
    assert row["last_ts_utc"].startswith("2023-12-31T23:00:00")
    # Checkpoint A fix (NOTE C2-01): payload_sha256 hashes the (epoch, price)
    # data via the same function as the C2 contract report, not the cached
    # file, so it is reproducible across re-fetches of identical data.
    frame = ec.read_cached_year("DE-LU", 2023, cfg)
    assert row["payload_sha256"] == contracts_mod.payload_fingerprint(frame)
    assert len(row["payload_sha256"]) == 64


def test_manifest_flags_a_gap_rather_than_filling_it(tmp_path):
    cfg, path, n = _synthetic_year(tmp_path, year=2023)
    payload = json.loads(path.read_text())
    # drop three consecutive hours in March
    del payload["unix_seconds"][2000:2003]
    del payload["price"][2000:2003]
    path.write_text(json.dumps(payload))

    row = manifest_mod.summarise_year("DE-LU", 2023, cfg)
    assert row["n_points"] == n - 3
    assert row["coverage_ratio"] < 1.0
    assert row["n_gap_intervals"] == 1
    assert row["max_gap_hours"] == 4.0


def test_build_and_write_manifest_round_trip(tmp_path):
    cfg, _, _ = _synthetic_year(tmp_path, year=2023)
    frame = manifest_mod.build_manifest(["DE-LU"], None, cfg)
    assert list(frame.columns) == manifest_mod.COLUMNS
    assert len(frame) == 1

    csv_path, json_path = manifest_mod.write_manifest(
        frame, manifest_dir=tmp_path / "manifest", config=cfg
    )
    reread = pd.read_csv(csv_path)
    assert len(reread) == 1 and reread.loc[0, "zone"] == "DE-LU"
    doc = json.loads(json_path.read_text())
    assert doc["sealed_holdout_years"] == [2025]
    assert doc["n_rows"] == 1
    assert doc["rows"][0]["n_negative"] == 5
    assert doc["config_hash"] == config_mod.config_hash()


def test_manifest_now_includes_2025_now_that_it_is_unsealed(tmp_path):
    """Was test_manifest_cannot_include_a_sealed_year_even_if_cached ('belt and
    braces: a stray sealed-year cache file must still not be read'). Checkpoint C
    (2026-10-12) unsealed 2025, and build_manifest calling the real, default-args
    holdout guard (like fetch_year above, it threads no progress_path override)
    means this now has to succeed and produce a real row — exactly what C17's
    manifest rebuild depends on."""
    cfg = _config_with_cache(tmp_path)
    path = ec.cache_path("DE-LU", 2025, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"unix_seconds": [1735689600], "price": [123.0], "unit": "EUR / MWh"}
    ))
    assert ec.cached_years("DE-LU", cfg) == [2025]
    frame = manifest_mod.build_manifest(["DE-LU"], None, cfg)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["zone"] == "DE-LU" and row["year"] == 2025
    assert row["price_mean"] == 123.0
