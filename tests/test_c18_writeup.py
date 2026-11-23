"""C18's write-up draft, bound to the artefacts it claims to report.

A new test file for new work. Nothing here edits an existing test.

`docs/writeup.md` is prose, so the failure mode is not a crash — it is a number
that drifts away from the artefact it came from, or a required label that a
later edit quietly drops. Three families of check, in order of how much damage
they prevent:

1. **Every headline number is re-derived from a committed artefact** and then
   looked for in the text. A binding that cannot find its number in the
   write-up fails; so does one whose artefact no longer holds that value.
   This is the same discipline C20's `claims` phase applies to the README.
2. **The sections PLAN.md C18 asks for exist**, including the Limits section
   and the "what a desk would additionally need" page.
3. **The labels earlier cycles made mandatory are present** — NOTE C12-03,
   NOTE C13-01, NOTE C14-02, NOTE C14-06, NOTE C15-02, NOTE C15-03, the
   FINDING C15-D limitation and the holdout's own §5 list — and the two claims
   those notes forbid are absent.

The write-up reports a *sealed* year, so there is also a check that it does not
describe a second evaluation of it, and one that the document is still a
document: it must not be able to write a result row, because nothing in `docs/`
should.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WRITEUP = REPO_ROOT / "docs" / "writeup.md"
RESULTS = REPO_ROOT / "backtest" / "results"

ZONES = ("DE-LU", "ES", "NO2", "FR", "NL", "BE", "IT-North", "DK1", "PL")
COMPARABLE = "lear_full_history"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text() -> str:
    """The write-up, with every run of whitespace collapsed to one space.

    The source is hard-wrapped at ~79 columns, so a phrase or a number with a
    thousands separator can straddle a line break. Flattening here means a
    check describes what the document *says* rather than where its lines
    happen to end, and a reflow is not a test failure.
    """
    if not WRITEUP.exists():  # pragma: no cover - the draft is committed
        pytest.fail("docs/writeup.md is missing: C18's deliverable is the write-up")
    raw = WRITEUP.read_text(encoding="utf-8").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", raw)


def _rows(name: str) -> list[dict[str, str]]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} is not present in this working tree")
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _holdout(curve: str = COMPARABLE) -> dict[str, dict[str, str]]:
    rows = _rows("c17_holdout_2025_metrics.csv")
    return {
        r["zone"]: r
        for r in rows
        if r["curve"] == curve and r.get("scope", "common_hours") == "common_hours"
    }


def _per_year(curve: str = COMPARABLE) -> dict[tuple[str, str], dict[str, str]]:
    rows = _rows("c13_per_year_metrics.csv")
    return {
        (r["zone"], r["year"]): r
        for r in rows
        if r["curve"] == curve and r["scope"] == "common_hours"
    }


def _like_for_like() -> dict[tuple[str, str], dict[str, str]]:
    rows = _rows("c17_like_for_like.csv")
    return {(r["zone"], r["year"]): r for r in rows if r["basis"] == "jan_sep_only"}


def _contains_number(text: str, value: float, decimals: int) -> bool:
    """Is this value written in the text, at the precision the write-up uses?

    Thousands are written with a non-breaking space in the document, and the
    minus sign is a typographic one, so both spellings are accepted.
    """
    literal = f"{value:,.{decimals}f}".replace(",", " ")
    candidates = {literal, literal.replace(" ", " "), literal.replace(" ", "")}
    if literal.startswith("-"):
        candidates |= {c.replace("-", "−", 1) for c in set(candidates)}
    return any(c in text for c in candidates)


# ---------------------------------------------------------------------------
# 1. The headline numbers are the artefacts' numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("zone", ZONES)
def test_the_holdout_capture_ratio_in_the_write_up_is_the_committed_one(zone):
    row = _holdout()[zone]
    value = float(row["capture_rolled_oracle_cash"])
    assert _contains_number(_text(), value, 4), (
        f"{zone}'s holdout capture is {value:.4f} in "
        "c17_holdout_2025_metrics.csv and the write-up does not say so"
    )


@pytest.mark.parametrize("zone", ZONES)
def test_the_holdout_cash_and_loss_in_the_write_up_are_the_committed_ones(zone):
    row = _holdout()[zone]
    text = _text()
    for field in ("dispatch_cash_eur_per_mw_year", "eur_per_mw_year_lost_vs_oracle"):
        value = round(float(row[field]))
        assert _contains_number(text, value, 0), (
            f"{zone}'s {field} rounds to {value} and the write-up does not say so"
        )


@pytest.mark.parametrize("zone", ZONES)
def test_the_five_visible_years_of_capture_are_the_committed_ones(zone):
    table = _per_year()
    text = _text()
    for year in ("2020", "2021", "2022", "2023", "2024"):
        value = float(table[(zone, year)]["capture_rolled_oracle_cash"])
        assert _contains_number(text, value, 4), (
            f"{zone} {year} capture is {value:.4f} in c13_per_year_metrics.csv "
            "and the write-up's per-year table does not say so"
        )


def _markdown_rows(section: str) -> dict[str, list[str]]:
    """The rows of the first markdown table after `section`, keyed by zone.

    Read from the raw file rather than the flattened text, because a table is
    a line-oriented structure. Searching for a number anywhere in the document
    cannot catch two zones' values being swapped; this can.
    """
    raw = WRITEUP.read_text(encoding="utf-8").replace("\u00a0", " ")
    body = raw.split(section, 1)[1]
    rows: dict[str, list[str]] = {}
    seen_table = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            seen_table = True
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            zone = cells[0].replace("**", "")
            if zone in ZONES:
                rows[zone] = [c.replace("**", "").replace("\u2212", "-") for c in cells[1:]]
        elif seen_table and not stripped:
            if rows:
                break
    return rows


@pytest.mark.parametrize("zone", ZONES)
def test_the_holdout_table_rows_are_not_transposed_between_zones(zone):
    """Each cell of §3.1's table against that zone's own artefact row."""
    printed = _markdown_rows("### 3.1 The holdout year")[zone]
    row = _holdout()[zone]
    capture, _interval, cash, lost, mae, rmae, spearman = printed
    assert float(capture) == pytest.approx(float(row["capture_rolled_oracle_cash"]), abs=5e-5)
    assert float(cash.replace(" ", "")) == pytest.approx(
        float(row["dispatch_cash_eur_per_mw_year"]), abs=0.5
    )
    assert float(lost.replace(" ", "")) == pytest.approx(
        float(row["eur_per_mw_year_lost_vs_oracle"]), abs=0.5
    )
    assert float(mae) == pytest.approx(float(row["mae_on_dispatched_hours"]), abs=5e-3)
    assert float(rmae) == pytest.approx(
        float(row["rmae_vs_naive_on_dispatched_hours"]), abs=5e-4
    )
    assert float(spearman) == pytest.approx(float(row["within_day_spearman_mean"]), abs=5e-5)


@pytest.mark.parametrize("zone", ZONES)
def test_the_per_year_table_rows_are_not_transposed_between_zones(zone):
    """Each cell of §3.2's table against that (zone, year)'s own artefact row."""
    printed = _markdown_rows("### 3.2 Six years, nine zones")[zone]
    visible = _per_year()
    holdout = _holdout()
    years = ("2020", "2021", "2022", "2023", "2024")
    assert len(printed) == 6, printed
    for cell, year in zip(printed[:5], years):
        assert float(cell) == pytest.approx(
            float(visible[(zone, year)]["capture_rolled_oracle_cash"]), abs=5e-5
        ), f"{zone} {year}"
    assert float(printed[5]) == pytest.approx(
        float(holdout[zone]["capture_rolled_oracle_cash"]), abs=5e-5
    ), f"{zone} 2025"


def test_the_naive_floor_band_quoted_for_the_holdout_is_the_committed_one():
    naive = _holdout("naive")
    captures = {z: float(r["capture_rolled_oracle_cash"]) for z, r in naive.items()}
    low = min(captures.values())
    high = max(captures.values())
    assert min(captures, key=captures.get) == "NO2"
    assert max(captures, key=captures.get) == "ES"
    text = _text()
    assert _contains_number(text, low, 4)
    assert _contains_number(text, high, 4)


def test_the_surprising_findings_direction_counts_are_recomputed_not_asserted():
    """§4's table of "9 of 9" / "7 of 9" counts, from the like-for-like file."""
    table = _like_for_like()
    counts = {"mae_up": 0, "spread_up": 0, "eoh_down": 0, "spearman_up": 0, "capture_up": 0}
    for zone in ZONES:
        before = table[(zone, "2024")]
        after = table[(zone, "2025")]
        f = lambda row, key: float(row[key])  # noqa: E731
        counts["mae_up"] += f(after, "pooled_mae_eur_per_mwh") > f(before, "pooled_mae_eur_per_mwh")
        counts["spread_up"] += f(after, "mean_realised_spread_eur_per_mwh") > f(
            before, "mean_realised_spread_eur_per_mwh"
        )
        counts["eoh_down"] += f(after, "error_over_headroom") < f(before, "error_over_headroom")
        counts["spearman_up"] += f(after, "within_day_spearman_mean") > f(
            before, "within_day_spearman_mean"
        )
        counts["capture_up"] += f(after, "capture") > f(before, "capture")

    assert counts == {
        "mae_up": 9,
        "spread_up": 9,
        "eoh_down": 9,
        "spearman_up": 9,
        "capture_up": 7,
    }, f"the write-up's §4 table claims 9/9/9/9/7 and the artefacts say {counts}"

    text = _text()
    assert "9 of 9" in text and "7 of 9" in text


def test_the_holdout_is_above_every_visible_year_in_six_zones_like_for_like():
    table = _like_for_like()
    above = [
        zone
        for zone in ZONES
        if float(table[(zone, "2025")]["capture"])
        > max(
            float(table[(zone, year)]["capture"])
            for year in ("2020", "2021", "2022", "2023", "2024")
        )
    ]
    assert len(above) == 6, f"six zones, like for like, not {len(above)}: {above}"
    assert set(ZONES) - set(above) == {"FR", "IT-North", "PL"}
    text = _text()
    assert "**six** of nine zones" in text
    assert "FR, IT-North, PL" in text


def test_the_no2_like_for_like_capture_move_is_the_committed_one():
    table = _like_for_like()
    delta_pp = 100 * (
        float(table[("NO2", "2025")]["capture"]) - float(table[("NO2", "2024")]["capture"])
    )
    assert _contains_number(_text(), round(delta_pp, 1), 1), (
        f"NO2 moves {delta_pp:.2f}pp like for like and the write-up does not say so"
    )


def test_the_sensitivity_ladder_numbers_are_the_committed_ones():
    rows = [
        r
        for r in _rows("c15_lever_summary.csv")
        if r["leg"] == "main" and r["curve"] == COMPARABLE and r["block_days"] == "1"
    ]
    by_rung = {r["rung"]: r for r in rows}
    text = _text()
    for rung in ("duration_4h", "soc_daily_reset", "soc_no_terminal", "throughput_0", "throughput_5"):
        cash = round(float(by_rung[rung]["mean_delta_eur_per_mw_year"]))
        assert _contains_number(text, abs(cash), 0), (
            f"{rung} moves {cash} EUR/MW/yr and the write-up's lever table does not say so"
        )
        pp = float(by_rung[rung]["mean_delta_capture_pp"])
        assert _contains_number(text, abs(round(pp, 2)), 2), (
            f"{rung} moves {pp:.2f}pp of capture and the write-up does not say so"
        )


def test_the_results_store_row_count_quoted_in_the_provenance_is_the_real_one():
    path = RESULTS / "results.csv"
    if not path.exists():
        pytest.skip("results.csv is not present in this working tree")
    with path.open(encoding="utf-8") as handle:
        n_rows = sum(1 for _ in csv.DictReader(handle))
    assert _contains_number(_text(), n_rows, 0), (
        f"results.csv holds {n_rows} rows and the write-up's §7 does not say so"
    )


def test_the_holdout_evaluation_timestamp_matches_the_committed_ledger():
    path = RESULTS / "c17_holdout_run_ledger.json"
    if not path.exists():
        pytest.skip("the holdout ledger is not present in this working tree")
    ledger = json.loads(path.read_text(encoding="utf-8"))
    blob = json.dumps(ledger)
    text = _text()
    stamps = set(re.findall(r"\d{4}-\d{2}-\d{2}T?\d{0,2}:?\d{0,2}:?\d{0,2}Z?", blob))
    assert any(
        stamp.startswith("2026-11-23") for stamp in stamps
    ), "the ledger does not record a 2026-11-23 evaluation; the write-up says it does"
    assert "2026-11-23" in text


# ---------------------------------------------------------------------------
# 2. PLAN.md C18's required sections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "## 1. Executive summary",
        "## 2. Method",
        "## 3. Results",
        "## 4. The surprising finding",
        "## 5. Limits",
        "## 6. What a desk would additionally need",
    ],
)
def test_plan_md_c18_sections_are_all_present(heading):
    assert heading in _text(), f"PLAN.md C18 requires a section: {heading}"


@pytest.mark.parametrize(
    "limit",
    [
        "Art. 14",            # the RES-forecast vintage caveat
        "Day-ahead only",     # no intraday
        "ancillary services",
        "grid fees",          # no per-zone grid fees
        "Price-taker",
        "reservoir",          # no reservoir data for the hydro zones
        "Hourly resolution",  # hourly aggregation and the cutover
        "Structural breaks",  # zone structural breaks
    ],
)
def test_plan_md_c18s_named_limits_are_each_stated(limit):
    assert limit in _text(), f"PLAN.md C18's Limits list requires: {limit!r}"


@pytest.mark.parametrize(
    "item",
    ["position limits", "curve", "credit", "REMIT"],
)
def test_plan_md_c18s_named_desk_requirements_are_each_stated(item):
    desk = _text().split("## 6. What a desk would additionally need", 1)[1]
    assert item.lower() in desk.lower(), f"PLAN.md C18's desk page requires: {item!r}"


# ---------------------------------------------------------------------------
# 3. The labels earlier cycles made mandatory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "note,phrase",
    [
        # NOTE C12-03 / NOTE C13-01
        ("C13-01", "not established"),
        ("C13-01", "not a regime effect"),
        ("C12-03", "undetermined"),
        ("C12-03", "indistinguishable from constant"),
        ("C12-03", "within-day Spearman"),
        ("C13-01", "most favourable of the five visible years"),
        # NOTE C14-02
        ("C14-02", "has to carry the zone"),
        ("C14-02", "crisis year degrades"),
        # NOTE C14-06 / NOTE C8-01
        ("C14-06", "no exogenous gain claim"),
        # NOTE C15-02
        ("C15-02", "EUR/MW/yr"),
        ("C15-02", "friction explains"),
        # NOTE C15-03
        ("C15-03", "worth more than everything else in the ladder"),
        # FINDING C15-D as a stated limitation (NOTE C15-01 is still open)
        ("C15-01", "NOTE C15-01"),
        ("C15-01", "74–77% of days empty"),
        # FLAG C5-01
        ("C5-01", "simultaneous charge and discharge"),
        # The holdout's own §5 list
        ("holdout", "unpaired"),
        ("holdout", "expanding window confounds"),
        ("holdout", "price-only"),
    ],
)
def test_a_required_label_is_carried(note, phrase):
    assert phrase in _text(), f"{note} requires the write-up to say {phrase!r}"


@pytest.mark.parametrize(
    "forbidden",
    [
        # NOTE C12-03: the eight-zone band must never be quoted as established
        "the eight-zone band is established",
        "established eight-zone band",
        # NOTE C14-06: no exogenous gain may be claimed
        "the exogenous block improves",
        "exogenous features improve",
        # The holdout may not be described as repeatable
        "evaluated twice",
        "re-ran the holdout",
        "second evaluation of the holdout",
    ],
)
def test_a_forbidden_claim_is_absent(forbidden):
    assert forbidden.lower() not in _text().lower(), (
        f"the write-up must not claim {forbidden!r}"
    )


def test_the_write_up_states_the_holdout_ran_exactly_once():
    text = _text()
    assert "once" in text
    assert "pre-registered" in text
    assert "commit-then-settle" in text.lower()


def test_the_write_up_discloses_the_approved_environment_deviation():
    text = _text()
    assert "CPython patch release" in text
    assert "library fingerprint" in text


def test_the_write_up_carries_both_required_data_attributions():
    text = _text()
    assert "Energy-Charts" in text and "CC BY 4.0" in text
    assert "ENTSO-E" in text and "Transparency Platform" in text


def test_the_write_up_is_a_document_and_not_a_runner():
    """Nothing in `docs/` may write a result row; C17's figure module is held
    to the same property. A write-up that computed a number would be a number
    nobody could reproduce from the store."""
    text = _text()
    for forbidden in ("append_rows(", "ResultRow(", "rows_from_scores("):
        assert forbidden not in text
