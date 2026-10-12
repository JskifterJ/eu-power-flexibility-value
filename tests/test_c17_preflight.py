"""C17 — the preflight that found the holdout evaluation could not run.

The cycle this covers produced no 2025 number, so there is no result to pin.
What there *is* to test is the preflight's own reasoning, and three of its
pieces are load-bearing enough to deserve it.

**The constants must not drift from the pre-registration.** The module carries
``LAST_MARKET_DAY`` and ``EXPECTED_MARKET_DAYS`` as literals so the window
check is readable. A literal that quietly disagreed with
``c16_preregistration.json`` would turn the preflight's "all nine zones match
the pre-registered window" into a statement about nothing.

**The spec comparison must be able to fail.** Its whole value is detecting
drift between the live code and the registered model, so it is fed a doctored
pre-registration and must report the disagreement.

**The ENTSO-E probe must be truthful in both directions.** It is the evidence
behind FLAG C17-01, and the fix for that flag will flip its answer. So the
tests assert the probe's *internal consistency* under either outcome rather
than the outcome itself: if the parser refuses, the refusal must be the
sealed-year one and must coexist with an unsealed holdout (which is exactly
the contradiction the flag describes); if it accepts, it must have parsed the
three points it was given. Both branches are real assertions, and neither goes
red merely because the blocker was fixed.

Nothing here makes a network request, and nothing needs the price cache except
the window test, which skips when ``data/raw/`` is absent (it is gitignored and
does not survive a container).
"""

from __future__ import annotations

import copy
import datetime as dt

import pandas as pd
import pytest

from backtest import run_c17_holdout as c17
from backtest.results_store import library_fingerprint
from data.config import load_zones, sealed_years
from data.holdout import holdout_is_unsealed
from data.prices import cached_years


@pytest.fixture(scope="module")
def prereg() -> dict:
    return c17.load_preregistration()


# ---------------------------------------------------------------------------
# The constants agree with the pre-registration
# ---------------------------------------------------------------------------


def test_the_window_constants_match_the_committed_preregistration(prereg):
    window = prereg["window"]
    assert c17.HOLDOUT_YEAR == window["year"]
    assert c17.LAST_MARKET_DAY == dt.date.fromisoformat(window["last_market_day"])
    assert c17.EXPECTED_MARKET_DAYS == window["n_market_days"]


def test_the_cutover_constant_is_midnight_local_on_the_sdac_golive():
    """2025-10-01 00:00 CEST, expressed in UTC. The window must end before it."""
    local = c17.CUTOVER_UTC.tz_convert("Europe/Brussels")
    assert (local.year, local.month, local.day) == (2025, 10, 1)
    assert (local.hour, local.minute) == (0, 0)
    assert c17.CUTOVER_UTC > pd.Timestamp(c17.LAST_MARKET_DAY, tz="UTC")


# ---------------------------------------------------------------------------
# The unseal state reports both answers, and they are different questions
# ---------------------------------------------------------------------------


def test_unseal_state_separates_the_declaration_from_the_approval():
    """The distinction FLAG C17-01 turns on, asserted rather than described.

    ``sealed_years()`` naming 2025 after approval is correct and permanent;
    ``holdout_is_unsealed()`` is what overrides it. A guard reading only the
    first is the bug.
    """
    state = c17.unseal_state()
    assert state["holdout_is_unsealed"] == holdout_is_unsealed()
    assert state["sealed_years_declaration"] == sorted(int(y) for y in sealed_years())
    assert c17.HOLDOUT_YEAR in state["sealed_years_declaration"]


# ---------------------------------------------------------------------------
# The spec comparison, and its ability to fail
# ---------------------------------------------------------------------------


def test_every_frozen_spec_agrees_with_the_preregistration(prereg):
    report = c17.spec_agreement(prereg)
    assert report["all_agree"], report["disagreements"]
    assert report["n_checked"] == len(report["checked"]) >= 15


def test_the_spec_comparison_catches_a_doctored_preregistration(prereg):
    """Fail-ability: a registered model that the live code no longer matches."""
    doctored = copy.deepcopy(prereg)
    doctored["models_frozen"]["gbm"]["fingerprint"] = "0000000000000000"
    doctored["dispatch"]["throughput_cost_eur_per_mwh"] = 99.0
    report = c17.spec_agreement(doctored)
    assert not report["all_agree"]
    assert set(report["disagreements"]) == {"gbm_fingerprint", "battery_throughput_cost"}


def test_the_library_fingerprint_must_match_the_one_every_2024_number_used(prereg):
    """A 2025 number under different libraries is not comparable to its baseline."""
    report = c17.provenance(prereg)
    assert report["library_fingerprint_live"] == library_fingerprint()
    assert report["library_fingerprint_matches"], report["library_versions"]


def test_the_config_hash_is_allowed_to_move_and_says_why(prereg):
    """``fetch_years`` gained 2025 at the approval, which changes the hash.

    checkpoint_c.md §4(b) predicted it by name, so the preflight must report
    the difference without treating it as drift.
    """
    report = c17.provenance(prereg)
    assert report["config_hash_preregistered"] == prereg["config_hash"]
    assert "fetch_years" in report["config_hash_note"]


# ---------------------------------------------------------------------------
# The download record
# ---------------------------------------------------------------------------


def test_the_download_record_now_carries_every_zone_for_2025():
    """Post-approval this is the expected state, and the inverse of C16's check."""
    record = c17.download_record()
    assert c17.HOLDOUT_YEAR in record["years_present"]
    assert record["n_2025_rows"] == len(load_zones())
    assert set(record["zones_with_a_2025_row"]) == set(load_zones())


def test_the_download_record_does_not_restate_the_holdout_price_level():
    """A blocked cycle has no business publishing the holdout's price statistics."""
    record = c17.download_record()
    for block in record["per_zone"].values():
        assert not [k for k in block if k.startswith("price_") or k.startswith("mw_")]


# ---------------------------------------------------------------------------
# The window, when the cache is present
# ---------------------------------------------------------------------------


def test_the_window_is_273_hourly_market_days_ending_before_the_cutover():
    zone = "DE-LU"
    if not cached_years(zone):
        pytest.skip("the price cache is not present in this working tree")
    report = c17.window_report([zone])
    block = report["per_zone"][zone]
    assert block["n_evaluation_days"] == c17.EXPECTED_MARKET_DAYS
    assert block["last_market_day"] == c17.LAST_MARKET_DAY.isoformat()
    assert block["every_pre_cutover_row_is_hourly"]
    assert block["n_resolution_segments_before_cutover"] == 1
    assert block["matches_preregistered_window"]


def test_the_cutover_is_detected_where_plan_md_says_it_is():
    zone = "DE-LU"
    if not cached_years(zone):
        pytest.skip("the price cache is not present in this working tree")
    changes = c17.window_report([zone])["per_zone"][zone]["resolution_changes"]
    assert len(changes) == 1, changes
    assert changes[0]["at_utc"] == c17.CUTOVER_UTC.isoformat()
    assert (changes[0]["from_seconds"], changes[0]["to_seconds"]) == (3600, 900)


# ---------------------------------------------------------------------------
# The probe behind FLAG C17-01
# ---------------------------------------------------------------------------


def test_the_entsoe_probe_is_consistent_whichever_way_it_answers():
    """Evidence about the code, and still an assertion after the flag is fixed.

    Refused -> it must be the sealed-year refusal, and it must be happening
    while the holdout is unsealed: that pair *is* FLAG C17-01. Accepted -> the
    parser must have read the three points it was handed, which is what proves
    the probe exercises the real path rather than failing early for some
    unrelated reason.
    """
    probe = c17.entsoe_parse_guard_probe()
    assert probe["holdout_is_unsealed_at_probe_time"] == holdout_is_unsealed()
    if probe["parser_accepts_an_unsealed_2025_document"]:
        assert probe["raised"] is None
        assert probe["n_rows"] == 3
    else:
        assert probe["raised"] == "UnexpectedResponse"
        assert "SEALED year(s)" in probe["message"]
        assert str(c17.HOLDOUT_YEAR) in probe["message"]
        assert probe["holdout_is_unsealed_at_probe_time"] is True


def test_the_probe_document_is_dated_inside_the_evaluation_window():
    """A probe dated outside the window would not test what the flag claims."""
    assert "2025-03-01T00:00Z" in c17.SYNTHETIC_A65
    stamp = dt.date(2025, 3, 1)
    assert dt.date(2025, 1, 1) <= stamp <= c17.LAST_MARKET_DAY


def test_the_blocked_diagnosis_names_the_arms_it_costs_and_the_ones_it_does_not(prereg):
    report = c17.exogenous_path(prereg)
    if not report["tier_a_2025_pull_is_blocked"]:
        pytest.skip("FLAG C17-01 has been fixed; there is no diagnosis to check")
    scope = report["diagnosis"]["scope_of_the_consequence"]
    assert "lear_load_only" in scope["blocked"]
    assert "gbm_res_persistence" in scope["blocked"]
    assert not any("price_only" in arm for arm in scope["blocked"])
    assert any("Tier-B" in line for line in scope["not_blocked"])


# ---------------------------------------------------------------------------
# The verdict gates on every precondition, not just the one that failed
# ---------------------------------------------------------------------------


def test_the_committed_preflight_artefact_names_exactly_one_standing_blocker():
    """A drifted spec or a moved library would be as disqualifying as the
    blocker C17 actually hit, and far easier to miss, so the verdict is a
    conjunction. This pins what the committed artefact found."""
    import json

    path = c17.RESULTS_DIR / c17.PREFLIGHT
    if not path.exists():
        pytest.skip(f"{c17.PREFLIGHT} has not been produced in this working tree")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert set(report["blockers"]) == {
        "holdout_not_unsealed",
        "frozen_spec_drift",
        "library_fingerprint_moved",
        "tier_a_2025_pull_blocked",
        "evaluation_window_mismatch",
    }
    assert report["blockers_standing"] == ["tier_a_2025_pull_blocked"]
    assert report["status"].startswith("BLOCKED")
    assert report["provenance"]["library_fingerprint_live"] == "856fb19ac0c4eecd"
    assert report["evaluation_window"]["all_zones_match_the_preregistered_window"]
