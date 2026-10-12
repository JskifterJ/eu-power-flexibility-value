"""C7 tests: the ENTSO-E client, the exogenous loader, manifest and contracts.

All offline. No test here makes a network request, reads a real cached payload,
or touches a sealed year — every payload is synthetic XML built by
:func:`gl_document`, and the sealed-holdout tests assert that the guard *fires*.

Deliberately **no existing test file is modified** by this cycle, and neither
:mod:`data.contracts` nor :mod:`forecast.leakage` is touched: CLAUDE.md forbids
editing a data-contract or leakage-assertion file without flagging and stopping
first. The C7 contract layer (:mod:`data.exog_contracts`) is additive and
imports the C2 primitives rather than changing them.

The centre of gravity is :func:`data.entsoe.expand_points`. Every real ENTSO-E
response in C7 is ``curveType A03`` — a variable-sized block curve whose
positions are *sparse*, where an omitted position means "the previous value
still holds". Parsing such a curve position-by-row silently drops the repeated
blocks and shifts everything after them. So the A03 cases below are
hand-computed rather than round-tripped.
"""

from __future__ import annotations

import gzip
import json

import pandas as pd
import pytest

from data import entsoe as ec
from data.config import load_data_config
from data.contracts import DataContractViolation
from data.exog_contracts import build_exog_contract_report, series_may_be_negative
from data.exog_manifest import series_fingerprint
from data.exogenous import (
    LOAD_COLUMN,
    RESIDUAL_LOAD_COLUMN,
    SOLAR_COLUMN,
    WIND_COLUMN,
    add_residual_load,
    column_leakage_status,
    load_zone_document,
)
from data.holdout import SealedHoldoutError

NS = "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"
LOAD_DOC = "load_forecast_da"
WS_DOC = "wind_solar_forecast_da"


# ---------------------------------------------------------------------------
# Synthetic payload builders
# ---------------------------------------------------------------------------


def period_xml(start: str, end: str, resolution: str, points: list[tuple[int, float]]) -> str:
    body = "".join(
        f"<Point><position>{p}</position><quantity>{q}</quantity></Point>"
        for p, q in points
    )
    return (
        f"<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval>"
        f"<resolution>{resolution}</resolution>{body}</Period>"
    )


def series_xml(
    business_type: str,
    periods: list[str],
    psr_type: str | None = None,
    unit: str = "MAW",
    curve_type: str = "A03",
) -> str:
    psr = (
        f"<MktPSRType><psrType>{psr_type}</psrType></MktPSRType>"
        if psr_type
        else ""
    )
    return (
        f"<TimeSeries><mRID>1</mRID><businessType>{business_type}</businessType>"
        f"<quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name>"
        f"<curveType>{curve_type}</curveType>{psr}{''.join(periods)}</TimeSeries>"
    )


def gl_document(
    series: list[str], document_type: str = "A65", process_type: str = "A01"
) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<GL_MarketDocument xmlns="{NS}">'
        f"<mRID>test</mRID><type>{document_type}</type>"
        f"<process.processType>{process_type}</process.processType>"
        f"{''.join(series)}</GL_MarketDocument>"
    ).encode("utf-8")


def ack_document(code: str = "999", text: str = "No matching data found") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Acknowledgement_MarketDocument '
        'xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:7:0">'
        f"<mRID>x</mRID><Reason><code>{code}</code><text>{text}</text></Reason>"
        "</Acknowledgement_MarketDocument>"
    ).encode("utf-8")


def one_day_load(day: str = "2024-01-01", value: float = 1000.0) -> bytes:
    """A65, one hourly day, curveType A03 with a single leading point."""
    nxt = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return gl_document(
        [series_xml("A04", [period_xml(f"{day}T00:00Z", f"{nxt}T00:00Z", "PT60M",
                                      [(1, value)])])]
    )


# ---------------------------------------------------------------------------
# Config-driven document specs
# ---------------------------------------------------------------------------


def test_both_planned_documents_are_configured():
    docs = ec.load_documents()
    assert set(docs) == {LOAD_DOC, WS_DOC}
    assert docs[LOAD_DOC].document_type == "A65"
    assert docs[WS_DOC].document_type == "A69"
    # Day-ahead vintage for both: another processType would change the leakage
    # status of the feature.
    assert {d.process_type for d in docs.values()} == {"A01"}


def test_leakage_status_is_declared_and_matches_plan():
    docs = ec.load_documents()
    assert docs[LOAD_DOC].leakage_status == "safe"
    assert docs[WS_DOC].leakage_status == "FLAGGED"


def test_wind_rolls_up_offshore_and_onshore_solar_is_b16():
    spec = ec.document_spec(WS_DOC)
    mapping = spec.psr_to_series
    assert mapping["B16"] == SOLAR_COLUMN
    assert mapping["B18"] == WIND_COLUMN
    assert mapping["B19"] == WIND_COLUMN


def test_load_document_carries_no_psr_type():
    assert ec.document_spec(LOAD_DOC).carries_psr_type is False
    assert ec.document_spec(WS_DOC).carries_psr_type is True


def test_exogenous_years_start_in_2022_and_now_include_the_unsealed_holdout():
    """Was ...and_exclude_the_holdout. exogenous_years() derives from fetch_years
    (data/config.py), which Checkpoint C (2026-10-12) extended to include 2025
    on approval (docs/checkpoint_c.md §4(b)) — exactly so this would be true."""
    years = ec.exogenous_years()
    assert min(years) == 2022, "PLAN.md: no archived D-1 forecast vintage before 2022"
    assert 2021 not in years
    assert 2025 in years, "C17 needs this to fetch the holdout's exogenous features"


def test_column_leakage_status_including_the_derived_column():
    assert column_leakage_status(LOAD_COLUMN) == "safe"
    assert column_leakage_status(WIND_COLUMN) == "FLAGGED"
    assert column_leakage_status(SOLAR_COLUMN) == "FLAGGED"
    # FLAGGED by inheritance: two of its three inputs are the Art. 14 vintage.
    assert column_leakage_status(RESIDUAL_LOAD_COLUMN) == "FLAGGED"


# ---------------------------------------------------------------------------
# Token hygiene — the token must never reach disk, a log line or an exception
# ---------------------------------------------------------------------------


def test_redact_removes_the_literal_token():
    assert "s3cr3t" not in ec.redact("...s3cr3t...", "s3cr3t")


def test_redact_removes_a_security_token_query_parameter_even_when_unknown():
    url = "https://web-api.tp.entsoe.eu/api?securityToken=abc123&documentType=A65"
    out = ec.redact(url)
    assert "abc123" not in out
    assert "documentType=A65" in out


def test_document_request_does_not_contain_the_token():
    zone = ec.load_zones()["DE-LU"]
    url, params = ec.document_request(zone, LOAD_DOC, 2024)
    assert "securityToken" not in params
    assert "securityToken" not in url
    assert params["outBiddingZone_Domain"] == zone.entsoe_domain


def test_missing_credential_message_names_the_variable_not_a_value(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    assert ec.api_key_is_set() is False
    with pytest.raises(ec.MissingCredential, match="ENTSOE_API_KEY"):
        ec.api_token()


# ---------------------------------------------------------------------------
# The request window: periodEnd is exclusive
# ---------------------------------------------------------------------------


def test_period_bounds_name_the_exclusive_next_year_boundary():
    start, end = ec.period_bounds(2024)
    assert start == "202401010000"
    # Verified live in C7: an end of Y-12-31T23:00 returns 92 of that day's 96
    # quarter-hours, so the exclusive boundary is the only complete spelling.
    assert end == "202501010000"


# ---------------------------------------------------------------------------
# curveType A03 block expansion — the thing that would silently corrupt this
# ---------------------------------------------------------------------------


def test_a03_omitted_positions_carry_the_previous_value_forward():
    # Hand-computed: 8 slots, points at 1 -> 5.0 and 5 -> 9.0.
    # A03 means positions 2,3,4 are 5.0 and positions 6,7,8 are 9.0.
    dense = ec.expand_points([1, 5], [5.0, 9.0], 8, "A03", "ctx")
    assert dense == [5.0, 5.0, 5.0, 5.0, 9.0, 9.0, 9.0, 9.0]


def test_a03_single_point_fills_the_whole_period():
    # The real NO2 case: one point of 0.0 meaning "zero all year".
    assert ec.expand_points([1], [0.0], 4, "A03", "ctx") == [0.0, 0.0, 0.0, 0.0]


def test_a03_trailing_block_runs_to_the_end_of_the_period():
    assert ec.expand_points([1, 3], [1.0, 2.0], 4, "A03", "ctx") == [1.0, 1.0, 2.0, 2.0]


def test_a03_without_position_one_raises_rather_than_guessing():
    with pytest.raises(ec.UnexpectedResponse, match="not 1"):
        ec.expand_points([2, 3], [1.0, 2.0], 4, "A03", "ctx")


def test_position_beyond_the_periods_slots_raises():
    with pytest.raises(ec.UnexpectedResponse, match="exceeds"):
        ec.expand_points([1, 9], [1.0, 2.0], 4, "A03", "ctx")


def test_non_increasing_positions_raise():
    with pytest.raises(ec.UnexpectedResponse, match="strictly increasing"):
        ec.expand_points([1, 3, 2], [1.0, 2.0, 3.0], 4, "A03", "ctx")


def test_empty_period_raises():
    with pytest.raises(ec.UnexpectedResponse, match="no Point"):
        ec.expand_points([], [], 4, "A03", "ctx")


def test_a01_requires_every_position_present():
    assert ec.expand_points([1, 2, 3, 4], [1.0, 2.0, 3.0, 4.0], 4, "A01", "ctx") == [
        1.0, 2.0, 3.0, 4.0
    ]
    with pytest.raises(ec.UnexpectedResponse, match="fixed-size"):
        ec.expand_points([1, 2], [1.0, 2.0], 4, "A01", "ctx")


def test_unknown_curve_type_raises():
    with pytest.raises(ec.UnexpectedResponse, match="curveType"):
        ec.expand_points([1], [1.0], 4, "A99", "ctx")


def test_a03_expansion_reaches_the_parsed_frame():
    payload = gl_document(
        [series_xml("A04", [period_xml("2024-01-01T00:00Z", "2024-01-01T04:00Z",
                                       "PT60M", [(1, 10.0), (3, 30.0)])])]
    )
    frame = ec.parse_document(payload, LOAD_DOC, "ctx")
    assert list(frame[LOAD_COLUMN]) == [10.0, 10.0, 30.0, 30.0]
    assert len(frame) == 4, "sparse points must expand, not stay sparse"


# ---------------------------------------------------------------------------
# A 404 / Acknowledgement / unexpected response is a FLAG, not a puzzle
# ---------------------------------------------------------------------------


def test_acknowledgement_is_detected_and_carries_the_reason_code():
    assert ec.acknowledgement_reason(ack_document("999", "too big")) == (
        "999", "too big"
    )
    assert ec.acknowledgement_reason(one_day_load()) is None


def test_parse_rejects_an_acknowledgement_with_its_reason_code():
    with pytest.raises(ec.UnexpectedResponse) as exc:
        ec.parse_document(ack_document("999", "No matching data"), LOAD_DOC, "ctx")
    assert "999" in str(exc.value)
    assert "No matching data" in str(exc.value)
    assert "PROGRESS.md" in str(exc.value)


def test_parse_rejects_a_wrong_document_type():
    with pytest.raises(ec.UnexpectedResponse, match="document type"):
        ec.parse_document(one_day_load(), WS_DOC, "ctx")


def test_parse_rejects_a_non_day_ahead_process_type():
    payload = gl_document(
        [series_xml("A04", [period_xml("2024-01-01T00:00Z", "2024-01-01T01:00Z",
                                       "PT60M", [(1, 1.0)])])],
        process_type="A16",  # realised, not day-ahead
    )
    with pytest.raises(ec.UnexpectedResponse, match="processType"):
        ec.parse_document(payload, LOAD_DOC, "ctx")


def test_parse_rejects_an_unexpected_unit():
    payload = gl_document(
        [series_xml("A04", [period_xml("2024-01-01T00:00Z", "2024-01-01T01:00Z",
                                       "PT60M", [(1, 1.0)])], unit="MWH")]
    )
    with pytest.raises(ec.UnexpectedResponse, match="unit"):
        ec.parse_document(payload, LOAD_DOC, "ctx")


def test_parse_rejects_an_unmapped_psr_type_rather_than_dropping_it():
    # A new generation type appearing in A69 is a FLAG, not something to ignore.
    payload = gl_document(
        [series_xml("A93", [period_xml("2024-01-01T00:00Z", "2024-01-01T01:00Z",
                                       "PT60M", [(1, 1.0)])], psr_type="B99")],
        document_type="A69",
    )
    with pytest.raises(ec.UnexpectedResponse, match="B99"):
        ec.parse_document(payload, WS_DOC, "ctx")


def test_parse_rejects_an_unexpected_business_type():
    payload = gl_document(
        [series_xml("A99", [period_xml("2024-01-01T00:00Z", "2024-01-01T01:00Z",
                                       "PT60M", [(1, 1.0)])])]
    )
    with pytest.raises(ec.UnexpectedResponse, match="businessType"):
        ec.parse_document(payload, LOAD_DOC, "ctx")


def test_parse_rejects_an_empty_document():
    with pytest.raises(ec.UnexpectedResponse, match="no TimeSeries"):
        ec.parse_document(gl_document([]), LOAD_DOC, "ctx")


def test_parse_rejects_malformed_xml():
    with pytest.raises(ec.UnexpectedResponse, match="well-formed"):
        ec.parse_document(b"<GL_MarketDocument><unclosed>", LOAD_DOC, "ctx")


def test_parse_rejects_a_non_utc_time_interval():
    payload = gl_document(
        [series_xml("A04", [period_xml("2024-01-01T00:00", "2024-01-01T01:00",
                                       "PT60M", [(1, 1.0)])])]
    )
    with pytest.raises(ec.UnexpectedResponse, match="not.*UTC"):
        ec.parse_document(payload, LOAD_DOC, "ctx")


def test_parse_rejects_an_unsupported_resolution():
    payload = gl_document(
        [series_xml("A04", [period_xml("2024-01-01T00:00Z", "2024-01-02T00:00Z",
                                       "PT7M", [(1, 1.0)])])]
    )
    with pytest.raises(ec.UnexpectedResponse, match="resolution"):
        ec.parse_document(payload, LOAD_DOC, "ctx")


def test_parse_rejects_overlapping_periods_within_one_psr_type():
    overlapping = series_xml(
        "A04",
        [
            period_xml("2024-01-01T00:00Z", "2024-01-01T02:00Z", "PT60M", [(1, 1.0)]),
            period_xml("2024-01-01T01:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 2.0)]),
        ],
    )
    with pytest.raises(ec.UnexpectedResponse, match="duplicate timestamp"):
        ec.parse_document(gl_document([overlapping]), LOAD_DOC, "ctx")


# ---------------------------------------------------------------------------
# Summing psrTypes: NaN for a real missing component, zero for a non-existent one
# ---------------------------------------------------------------------------


def wind_solar_payload(
    solar: list[tuple[str, str, str, list[tuple[int, float]]]],
    offshore: list[tuple[str, str, str, list[tuple[int, float]]]],
    onshore: list[tuple[str, str, str, list[tuple[int, float]]]],
) -> bytes:
    def build(business, psr, periods):
        if not periods:
            return None
        return series_xml(
            business, [period_xml(*p) for p in periods], psr_type=psr
        )

    series = [
        s
        for s in (
            build("A94", "B16", solar),
            build("A93", "B18", offshore),
            build("A93", "B19", onshore),
        )
        if s
    ]
    return gl_document(series, document_type="A69")


def test_wind_is_the_sum_of_offshore_and_onshore():
    day = ("2024-01-01T00:00Z", "2024-01-01T02:00Z", "PT60M")
    payload = wind_solar_payload(
        solar=[(*day, [(1, 0.0)])],
        offshore=[(*day, [(1, 100.0)])],
        onshore=[(*day, [(1, 900.0)])],
    )
    frame = ec.parse_document(payload, WS_DOC, "ctx")
    assert list(frame[WIND_COLUMN]) == [1000.0, 1000.0]
    assert list(frame[SOLAR_COLUMN]) == [0.0, 0.0]


def test_a_real_component_missing_an_interval_makes_the_sum_nan_not_a_partial():
    # The DE-LU DST-day case: onshore wind absent for one hour that offshore has.
    # Treating the absence as zero would understate wind by the onshore fleet.
    payload = wind_solar_payload(
        solar=[("2024-01-01T00:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 0.0)])],
        offshore=[("2024-01-01T00:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 100.0)])],
        onshore=[
            ("2024-01-01T00:00Z", "2024-01-01T01:00Z", "PT60M", [(1, 900.0)]),
            ("2024-01-01T02:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 900.0)]),
        ],
    )
    frame = ec.parse_document(payload, WS_DOC, "ctx")
    wind = frame[WIND_COLUMN]
    assert wind.iloc[0] == 1000.0
    assert pd.isna(wind.iloc[1]), "a missing real component must not become zero"
    assert wind.iloc[2] == 1000.0
    assert frame.attrs["n_partial_psr_intervals"] == 1


def test_a_component_that_is_zero_wherever_published_is_treated_as_structurally_zero():
    # The NO2 case: offshore wind is published for a sliver of the span and is
    # 0.0 at every point, because NO2 has no offshore fleet. Without this, a
    # stray all-zero stub would NaN out a whole Tier-A zone's wind feature.
    payload = wind_solar_payload(
        solar=[("2024-01-01T00:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 0.0)])],
        offshore=[("2024-01-01T01:00Z", "2024-01-01T02:00Z", "PT60M", [(1, 0.0)])],
        onshore=[("2024-01-01T00:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 500.0)])],
    )
    frame = ec.parse_document(payload, WS_DOC, "ctx")
    assert list(frame[WIND_COLUMN]) == [500.0, 500.0, 500.0]
    assert frame.attrs["zero_components"] == {WIND_COLUMN: ["B18"]}
    assert frame.attrs["n_partial_psr_intervals"] == 0


def test_a_component_with_any_nonzero_value_is_not_treated_as_structurally_zero():
    payload = wind_solar_payload(
        solar=[("2024-01-01T00:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 0.0)])],
        offshore=[("2024-01-01T01:00Z", "2024-01-01T02:00Z", "PT60M", [(1, 0.1)])],
        onshore=[("2024-01-01T00:00Z", "2024-01-01T03:00Z", "PT60M", [(1, 500.0)])],
    )
    frame = ec.parse_document(payload, WS_DOC, "ctx")
    wind = frame[WIND_COLUMN]
    assert pd.isna(wind.iloc[0]) and pd.isna(wind.iloc[2])
    assert wind.iloc[1] == pytest.approx(500.1)
    assert frame.attrs["zero_components"] == {}


# ---------------------------------------------------------------------------
# Per-row interval lengths: a resolution change is not a gap
# ---------------------------------------------------------------------------


def test_interval_seconds_are_carried_per_row_from_each_period():
    # The ES 2022 shape: PT60M for a stretch, then PT15M.
    payload = gl_document(
        [
            series_xml(
                "A04",
                [
                    period_xml("2024-01-01T00:00Z", "2024-01-01T02:00Z", "PT60M",
                               [(1, 10.0)]),
                    period_xml("2024-01-01T02:00Z", "2024-01-01T03:00Z", "PT15M",
                               [(1, 20.0)]),
                ],
            )
        ]
    )
    frame = ec.parse_document(payload, LOAD_DOC, "ctx")
    assert frame.attrs["interval_seconds"] == (3600, 3600, 900, 900, 900, 900)
    assert len(frame) == 6


def test_interval_seconds_survive_year_truncation():
    payload = gl_document(
        [series_xml("A04", [period_xml("2023-12-31T22:00Z", "2024-01-01T02:00Z",
                                       "PT60M", [(1, 7.0)])])]
    )
    frame = ec.payload_to_frame(payload, LOAD_DOC, 2024, "ctx")
    assert len(frame) == len(frame.attrs["interval_seconds"]) == 2
    assert frame.attrs["n_out_of_window"] == 2


def test_conflicting_resolutions_for_one_timestamp_raise():
    payload = wind_solar_payload(
        solar=[("2024-01-01T00:00Z", "2024-01-01T01:00Z", "PT15M", [(1, 0.0)])],
        offshore=[],
        onshore=[("2024-01-01T00:00Z", "2024-01-01T01:00Z", "PT60M", [(1, 5.0)])],
    )
    with pytest.raises(ec.UnexpectedResponse, match="two\n?.*different resolutions"):
        ec.parse_document(payload, WS_DOC, "ctx")


# ---------------------------------------------------------------------------
# The sealed holdout — asserted positively, not argued
# ---------------------------------------------------------------------------


def test_a_response_containing_a_sealed_year_timestamp_is_refused():
    # periodEnd is meant to be exclusive, so this must never happen; the parser
    # checks rather than trusting it.
    payload = gl_document(
        [series_xml("A04", [period_xml("2025-01-01T00:00Z", "2025-01-01T02:00Z",
                                       "PT60M", [(1, 1.0)])])]
    )
    with pytest.raises(ec.UnexpectedResponse, match="SEALED"):
        ec.parse_document(payload, LOAD_DOC, "ctx")


def test_fetching_2025_now_passes_the_holdout_guard():
    """Was test_fetching_a_sealed_year_raises_before_any_request. The holdout
    guard (checked first, before exogenous_years, caching, or the token) no
    longer refuses 2025. What's left is this local environment genuinely having
    no ENTSOE_API_KEY set (api_token() is called before any network request,
    per data/entsoe.py's fetch_year) — MissingCredential, not SealedHoldoutError,
    is the proof the guard passed; CLAUDE.md's own instruction for a missing
    credential is to flag and continue rather than block, which is exactly what
    this environment difference is."""
    with pytest.raises(ec.MissingCredential, match="ENTSOE_API_KEY"):
        ec.fetch_year("DE-LU", LOAD_DOC, 2025)


def test_reading_a_cached_2025_year_now_passes_the_holdout_guard():
    """Was test_reading_a_cached_sealed_year_raises. No 2025 ENTSO-E file has
    ever been cached (C17 hasn't run), so past the now-passing holdout guard
    this correctly reaches 'no such file', not 'sealed'."""
    with pytest.raises(FileNotFoundError):
        ec.read_cached_year("DE-LU", LOAD_DOC, 2025)


def test_a_year_before_the_declared_vintage_window_is_refused():
    # The API answers for 2019-2021; PLAN.md says there is no archived D-1
    # forecast vintage there, so the bound is enforced in code.
    with pytest.raises(ec.UnexpectedResponse, match="2022"):
        ec.fetch_year("DE-LU", LOAD_DOC, 2021)


# ---------------------------------------------------------------------------
# Fetch behaviour: cache, retries, and what never touches the disk
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, content: bytes, url: str = "https://x/?securityToken=t"):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", "replace")
        self.url = url


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def temp_cache_config(tmp_path, monkeypatch):
    """A config whose ENTSO-E cache lives in tmp_path, with no sleeps."""
    monkeypatch.setenv("ENTSOE_API_KEY", "test-token-0123456789")
    cfg = json.loads(json.dumps(load_data_config()))
    cfg["sources"]["entsoe"]["cache_dir"] = str(tmp_path / "entsoe")
    cfg["sources"]["entsoe"]["request"]["sleep_between_requests_seconds"] = 0
    cfg["sources"]["entsoe"]["request"]["retry_backoff_seconds"] = [0, 0, 0]
    return cfg


def test_a_cached_file_is_never_refetched(temp_cache_config, monkeypatch):
    path = ec.cache_path("DE-LU", LOAD_DOC, 2024, temp_cache_config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(one_day_load())
    session = FakeSession([FakeResponse(200, one_day_load())])
    returned, downloaded = ec.fetch_year(
        "DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session
    )
    assert downloaded is False
    assert returned == path
    assert session.calls == 0, "CLAUDE.md: never re-download cached data"


def test_a_successful_fetch_caches_the_payload_and_a_redacted_meta(temp_cache_config):
    session = FakeSession([FakeResponse(200, one_day_load())])
    path, downloaded = ec.fetch_year(
        "DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session
    )
    assert downloaded is True and path.exists()
    meta = json.loads(
        ec.meta_path("DE-LU", LOAD_DOC, 2024, temp_cache_config).read_text()
    )
    assert "securityToken=<REDACTED>" in meta["url_redacted"]
    assert "test-token-0123456789" not in json.dumps(meta)
    assert meta["leakage_status"] == "safe"
    assert meta["period_end"] == "202501010000"


def test_an_acknowledgement_is_not_retried_and_not_cached(temp_cache_config):
    session = FakeSession([FakeResponse(400, ack_document("999", "too big"))])
    with pytest.raises(ec.UnexpectedResponse, match="999"):
        ec.fetch_year("DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session)
    assert session.calls == 1, "a 4xx is a FLAG, not a transient"
    assert not ec.cache_path("DE-LU", LOAD_DOC, 2024, temp_cache_config).exists()


def test_a_404_is_not_retried(temp_cache_config):
    session = FakeSession([FakeResponse(404, b"not found")])
    with pytest.raises(ec.UnexpectedResponse, match="404"):
        ec.fetch_year("DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session)
    assert session.calls == 1


def test_a_schema_violating_200_is_never_written_to_the_cache(temp_cache_config):
    session = FakeSession([FakeResponse(200, gl_document([]))])
    with pytest.raises(ec.UnexpectedResponse):
        ec.fetch_year("DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session)
    assert not ec.cache_path("DE-LU", LOAD_DOC, 2024, temp_cache_config).exists()
    assert not ec.meta_path("DE-LU", LOAD_DOC, 2024, temp_cache_config).exists()


def test_a_5xx_is_retried_then_gives_up_as_fetch_failed(temp_cache_config):
    session = FakeSession([FakeResponse(503, b"busy")])
    with pytest.raises(ec.FetchFailed, match="503"):
        ec.fetch_year("DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session)
    assert session.calls == temp_cache_config["sources"]["entsoe"]["request"]["max_retries"]


def test_a_transport_error_is_retried_and_its_message_is_redacted(temp_cache_config):
    import requests

    session = FakeSession([requests.ConnectionError("failed for securityToken=abc")])
    with pytest.raises(ec.FetchFailed) as exc:
        ec.fetch_year("DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session)
    assert "abc" not in str(exc.value)


def test_round_trip_through_the_cache_reproduces_the_frame(temp_cache_config):
    session = FakeSession([FakeResponse(200, one_day_load(value=1234.5))])
    ec.fetch_year("DE-LU", LOAD_DOC, 2024, temp_cache_config, session=session)
    frame = ec.read_cached_year("DE-LU", LOAD_DOC, 2024, temp_cache_config)
    assert len(frame) == 24
    assert (frame[LOAD_COLUMN] == 1234.5).all()
    assert ec.cached_years("DE-LU", LOAD_DOC, temp_cache_config) == [2024]


# ---------------------------------------------------------------------------
# Hourly aggregation of a mixed-resolution series
# ---------------------------------------------------------------------------


def _cache_payload(cfg, zone, document, year, payload):
    path = ec.cache_path(zone, document, year, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(payload)


def test_hourly_aggregation_handles_a_mid_series_resolution_change(temp_cache_config):
    # Two UTC hours at PT60M, then one hour of PT15M whose mean is the hourly
    # value. Against a single modal resolution the PT60M hours would be read as
    # partial and lost — which is what cost ES 3408 hours of 2022 before this.
    payload = gl_document(
        [
            series_xml(
                "A04",
                [
                    period_xml("2024-03-01T00:00Z", "2024-03-01T02:00Z", "PT60M",
                               [(1, 100.0), (2, 200.0)]),
                    period_xml("2024-03-01T02:00Z", "2024-03-01T03:00Z", "PT15M",
                               [(1, 10.0), (2, 20.0), (3, 30.0), (4, 40.0)]),
                ],
            )
        ]
    )
    _cache_payload(temp_cache_config, "DE-LU", LOAD_DOC, 2024, payload)
    hourly = load_zone_document(
        "DE-LU", LOAD_DOC, [2024], temp_cache_config, hourly=True
    )
    assert list(hourly[LOAD_COLUMN]) == [100.0, 200.0, 25.0]


def test_a_partially_covered_hour_is_nan_not_a_partial_mean(temp_cache_config):
    # Three of four quarter-hours present: the hour is unknown, not 3/4 known.
    payload = gl_document(
        [
            series_xml(
                "A04",
                [
                    period_xml("2024-03-01T00:00Z", "2024-03-01T00:45Z", "PT15M",
                               [(1, 10.0), (2, 20.0), (3, 30.0)]),
                    period_xml("2024-03-01T01:00Z", "2024-03-01T02:00Z", "PT15M",
                               [(1, 40.0)]),
                ],
            )
        ]
    )
    _cache_payload(temp_cache_config, "DE-LU", LOAD_DOC, 2024, payload)
    hourly = load_zone_document(
        "DE-LU", LOAD_DOC, [2024], temp_cache_config, hourly=True, on_partial="flag"
    )
    assert pd.isna(hourly[LOAD_COLUMN].iloc[0]), "a partial hour must not be averaged"
    assert hourly[LOAD_COLUMN].iloc[1] == 40.0


def test_a_partially_covered_hour_raises_by_default(temp_cache_config):
    payload = gl_document(
        [series_xml("A04", [period_xml("2024-03-01T00:00Z", "2024-03-01T00:45Z",
                                       "PT15M", [(1, 10.0)]),
                            period_xml("2024-03-01T01:00Z", "2024-03-01T02:00Z",
                                       "PT15M", [(1, 40.0)])])]
    )
    _cache_payload(temp_cache_config, "DE-LU", LOAD_DOC, 2024, payload)
    with pytest.raises(DataContractViolation, match="not tiled"):
        load_zone_document("DE-LU", LOAD_DOC, [2024], temp_cache_config, hourly=True)


def test_native_load_is_not_aggregated(temp_cache_config):
    payload = gl_document(
        [series_xml("A04", [period_xml("2024-03-01T00:00Z", "2024-03-01T01:00Z",
                                       "PT15M", [(1, 10.0), (2, 20.0),
                                                 (3, 30.0), (4, 40.0)])])]
    )
    _cache_payload(temp_cache_config, "DE-LU", LOAD_DOC, 2024, payload)
    native = load_zone_document(
        "DE-LU", LOAD_DOC, [2024], temp_cache_config, hourly=False
    )
    assert list(native[LOAD_COLUMN]) == [10.0, 20.0, 30.0, 40.0]


# ---------------------------------------------------------------------------
# Residual load
# ---------------------------------------------------------------------------


def test_residual_load_is_load_minus_wind_minus_solar():
    frame = pd.DataFrame(
        {LOAD_COLUMN: [1000.0, 500.0], WIND_COLUMN: [200.0, 400.0],
         SOLAR_COLUMN: [100.0, 300.0]},
        index=pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC"),
    )
    out = add_residual_load(frame)
    assert list(out[RESIDUAL_LOAD_COLUMN]) == [700.0, -200.0]


def test_residual_load_goes_negative_when_res_exceeds_load_and_that_is_not_a_violation():
    # This is the condition that drives negative prices and the subject of
    # PLAN.md's C14 chapter — flagging it would flag the signal itself.
    assert series_may_be_negative(RESIDUAL_LOAD_COLUMN) is True
    assert series_may_be_negative(LOAD_COLUMN) is False
    assert series_may_be_negative(WIND_COLUMN) is False
    assert series_may_be_negative(SOLAR_COLUMN) is False


def test_residual_load_is_nan_when_any_input_is_missing():
    frame = pd.DataFrame(
        {LOAD_COLUMN: [1000.0], WIND_COLUMN: [float("nan")], SOLAR_COLUMN: [100.0]},
        index=pd.date_range("2024-01-01", periods=1, freq="h", tz="UTC"),
    )
    out = add_residual_load(frame)
    assert pd.isna(out[RESIDUAL_LOAD_COLUMN].iloc[0]), (
        "a residual load computed from load alone would be the biggest outlier "
        "in the fundamentals chapter"
    )


def test_residual_load_inherits_the_flagged_status():
    frame = pd.DataFrame(
        {LOAD_COLUMN: [1.0], WIND_COLUMN: [1.0], SOLAR_COLUMN: [1.0]},
        index=pd.date_range("2024-01-01", periods=1, freq="h", tz="UTC"),
    )
    frame.attrs["flagged_columns"] = [WIND_COLUMN, SOLAR_COLUMN]
    out = add_residual_load(frame)
    assert RESIDUAL_LOAD_COLUMN in out.attrs["flagged_columns"]


# ---------------------------------------------------------------------------
# The exogenous contract layer
# ---------------------------------------------------------------------------


def _hourly_frame(values, column=LOAD_COLUMN, start="2024-01-01"):
    index = pd.date_range(start, periods=len(values), freq="h", tz="UTC")
    return pd.DataFrame({column: values}, index=index)


def test_a_negative_load_forecast_is_a_contract_violation():
    frame = _hourly_frame([100.0] * 23 + [-5.0])
    report = build_exog_contract_report("DE-LU", LOAD_COLUMN, frame)
    assert report.ok is False
    assert any("negative" in v for v in report.violations)


def test_a_negative_residual_load_is_a_note_not_a_violation():
    frame = _hourly_frame([100.0] * 23 + [-5.0], column=RESIDUAL_LOAD_COLUMN)
    report = build_exog_contract_report("DE-LU", RESIDUAL_LOAD_COLUMN, frame)
    assert report.ok is True
    assert report.n_negative_values == 1
    assert any("negative" in n for n in report.notes)


def test_a_short_day_is_reported_as_a_completeness_note_not_a_failure():
    # 23 of 24 hours on a UTC day: a gap, which this source really has at the
    # autumn DST boundary. Reported, never filled.
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC").delete(5)
    frame = pd.DataFrame({LOAD_COLUMN: [100.0] * 23}, index=index)
    report = build_exog_contract_report("DE-LU", LOAD_COLUMN, frame)
    assert report.ok is True, "a known source gap must not discard a training year"
    assert report.n_missing_intervals == 1
    assert any("fewer rows" in n for n in report.notes)


def test_a_duplicate_timestamp_is_a_violation():
    index = pd.DatetimeIndex(
        list(pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC"))
        + [pd.Timestamp("2024-01-01T02:00Z")]
    ).sort_values()
    frame = pd.DataFrame({LOAD_COLUMN: [100.0] * 6}, index=index)
    report = build_exog_contract_report("DE-LU", LOAD_COLUMN, frame)
    assert report.ok is False
    assert any("duplicate" in v for v in report.violations)


def test_a_constant_series_is_reported_not_failed():
    # NO2 solar really is 0.0 for every hour of every year.
    frame = _hourly_frame([0.0] * 48, column=SOLAR_COLUMN)
    report = build_exog_contract_report("NO2", SOLAR_COLUMN, frame)
    assert report.ok is True
    assert report.is_constant is True
    assert report.constant_value == 0.0


def test_the_report_carries_the_declared_leakage_status():
    frame = _hourly_frame([100.0] * 48, column=WIND_COLUMN)
    report = build_exog_contract_report("DE-LU", WIND_COLUMN, frame)
    assert report.leakage_status == "FLAGGED"
    assert report.document == WS_DOC


# ---------------------------------------------------------------------------
# Manifest fingerprinting
# ---------------------------------------------------------------------------


def test_series_fingerprint_is_stable_and_value_dependent():
    frame = _hourly_frame([1.0, 2.0, 3.0])
    first = series_fingerprint(frame, LOAD_COLUMN)
    assert first == series_fingerprint(frame, LOAD_COLUMN)
    changed = _hourly_frame([1.0, 2.0, 3.5])
    assert series_fingerprint(changed, LOAD_COLUMN) != first


def test_series_fingerprint_depends_on_the_timestamps_too():
    a = _hourly_frame([1.0, 2.0], start="2024-01-01")
    b = _hourly_frame([1.0, 2.0], start="2024-02-01")
    assert series_fingerprint(a, LOAD_COLUMN) != series_fingerprint(b, LOAD_COLUMN)
