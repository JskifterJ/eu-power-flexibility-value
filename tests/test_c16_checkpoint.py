"""C16 — tests for Checkpoint C's seal verification and pre-registration.

Two things are under test, and they are different in kind.

The **seal verification** must fail loudly in every world where the holdout is
reachable: a bare marker line, a required module with its guard deleted, an
entry point that answers instead of refusing, a committed artefact carrying a
2025 row. Those are tested by constructing each of those worlds, because a check
that has never been seen to fail is not evidence of anything.

The **pre-registration** must say exactly what the committed configuration says
— not a paraphrase of it. Every number in it is therefore checked against the
config file or the module constant it comes from, so that the frozen spec cannot
drift away from the code that will execute it between now and the unseal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest import run_c16_checkpoint as c16
from backtest.bootstrap import BLOCK_LADDER, DEFAULT_REPLICATES, DEFAULT_SEED
from backtest.results_store import ResultRow, read_results
from data.config import REPO_ROOT, config_hash, load_battery_config, load_zones
from data.holdout import SealedHoldoutError, holdout_is_unsealed, unseal_marker

RESULTS_DIR = REPO_ROOT / "backtest" / "results"


# ---------------------------------------------------------------------------
# The marker
# ---------------------------------------------------------------------------


def test_the_real_progress_file_does_not_unseal_the_holdout():
    """The seal, on the committed PROGRESS.md. If this fails, stop everything."""
    assert holdout_is_unsealed() is False
    audit = c16.marker_audit()
    assert audit["seal_intact"] is True
    assert audit["holdout_is_unsealed"] is False
    assert audit["n_bare_marker_lines"] == 0


def test_the_checkpoint_entry_quotes_the_marker_without_unsealing_it():
    """C16 has to *describe* the marker. Describing it must not be writing it."""
    audit = c16.marker_audit()
    assert audit["n_lines_mentioning_marker_in_prose"] >= 1
    assert audit["n_bare_marker_lines"] == 0


def test_marker_audit_raises_on_a_bare_marker_line(tmp_path: Path):
    progress = tmp_path / "PROGRESS.md"
    progress.write_text(
        f"# Progress\n\nblah\n{unseal_marker()}\nmore\n", encoding="utf-8"
    )
    with pytest.raises(c16.CheckpointError, match="line of its own"):
        c16.marker_audit(progress)


def test_marker_audit_accepts_the_marker_quoted_in_prose(tmp_path: Path):
    progress = tmp_path / "PROGRESS.md"
    progress.write_text(
        f"The human writes `{unseal_marker()}` on its own line to approve.\n",
        encoding="utf-8",
    )
    audit = c16.marker_audit(progress)
    assert audit["seal_intact"] is True
    assert audit["n_lines_mentioning_marker_in_prose"] == 1
    assert audit["n_bare_marker_lines"] == 0


def test_marker_audit_catches_an_indented_bare_marker(tmp_path: Path):
    """``holdout_is_unsealed`` strips, so an indented marker unseals. So must this."""
    progress = tmp_path / "PROGRESS.md"
    progress.write_text(f"   {unseal_marker()}   \n", encoding="utf-8")
    with pytest.raises(c16.CheckpointError):
        c16.marker_audit(progress)


# ---------------------------------------------------------------------------
# The declared split
# ---------------------------------------------------------------------------


def test_split_audit_matches_the_committed_config():
    audit = c16.split_audit()
    assert audit["sealed_years"] == [2025]
    assert audit["fetch_years_intersect_sealed"] == []
    assert audit["splits"]["validate"] == [2024]
    assert audit["splits"]["holdout"] == [2025]
    assert audit["main_backtest_end"] == "2025-09-30"
    assert audit["sdac_15min_golive"] == "2025-10-01"


def test_the_window_stops_the_day_before_the_15_minute_cutover():
    audit = c16.split_audit()
    assert c16.HOLDOUT_LAST_DAY == audit["main_backtest_end"]
    assert (
        pd.Timestamp(c16.HOLDOUT_LAST_DAY) + pd.Timedelta(days=1)
    ) == pd.Timestamp(audit["sdac_15min_golive"])


# ---------------------------------------------------------------------------
# The static guard census
# ---------------------------------------------------------------------------


def test_every_module_that_can_reach_sealed_data_calls_the_guard():
    census = c16.guard_census()
    assert census["required_modules_missing_a_guard"] == []
    for module in c16.REQUIRED_GUARD_MODULES:
        assert census["guard_calls_by_module"].get(module), module
    assert census["n_guard_calls"] >= 20


def test_guard_calls_counts_calls_not_imports(tmp_path: Path):
    path = tmp_path / "mod.py"
    path.write_text(
        "from data.holdout import assert_not_sealed\n"
        "def f(y):\n"
        "    assert_not_sealed(y, 'x')\n"
        "    holdout.assert_range_not_sealed(y, y, 'x')\n",
        encoding="utf-8",
    )
    assert c16._guard_calls(path) == [3, 4]


def test_guard_census_raises_when_a_required_module_loses_its_guard(tmp_path: Path):
    """The failure mode this census exists for: a guard call quietly deleted."""
    for module in c16.REQUIRED_GUARD_MODULES:
        target = tmp_path / module
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (REPO_ROOT / module).read_text(encoding="utf-8")
        if module == "data/prices.py":
            source = source.replace("assert_not_sealed(", "pass  # (")
        target.write_text(source, encoding="utf-8")
    for directory in c16.CENSUS_DIRS:
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    with pytest.raises(c16.CheckpointError, match="data/prices.py"):
        c16.guard_census(tmp_path)


# ---------------------------------------------------------------------------
# The live refusal probes
# ---------------------------------------------------------------------------


def test_every_entry_point_refuses_a_2025_request():
    report = c16._probe_report()
    assert report["n_probes"] == report["n_refused"] >= 8
    for probe in report["probes"]:
        assert probe["refused"] is True, probe
        assert probe["raised"] == "SealedHoldoutError"


def test_the_probe_session_cannot_reach_the_network():
    """A probe that finds the guard missing must still download nothing."""
    with pytest.raises(c16.CheckpointError, match="reached the network"):
        c16._RefusingSession().get("https://api.energy-charts.info/price")


def test_run_probes_raises_when_an_entry_point_answers():
    good = c16.Probe("stub", "answer a sealed request", lambda: "a 2025 price")
    with pytest.raises(c16.CheckpointError, match="did NOT refuse"):
        c16.run_probes([good])


def test_run_probes_raises_when_the_refusal_comes_from_somewhere_else():
    """A FileNotFoundError is not a seal: it means the guard was not what stopped it."""

    def boom() -> None:
        raise FileNotFoundError("no cached file")

    probe = c16.Probe("stub", "read a sealed file", boom)
    with pytest.raises(c16.CheckpointError, match="instead of"):
        c16.run_probes([probe])


def test_the_synthetic_cache_holds_a_sealed_year_and_nothing_else(tmp_path: Path):
    with c16.synthetic_sealed_cache() as cfg:
        price_dir = Path(cfg["sources"]["energy_charts"]["cache_dir"]) / "DE-LU"
        names = sorted(p.name for p in price_dir.glob("*.json"))
        assert names == ["2024.json", "2025.json"]
        # Placeholders: year discovery needs the name, not the contents.
        assert price_dir.joinpath("2025.json").read_text(encoding="utf-8") == "{}"
        exog = Path(cfg["sources"]["entsoe"]["cache_dir"]) / "load_forecast_da" / "DE-LU"
        assert sorted(p.name for p in exog.glob("*.xml.gz")) == [
            "2024.xml.gz",
            "2025.xml.gz",
        ]
        assert exog.joinpath("2025.xml.gz").read_bytes() == b""


def test_the_synthetic_cache_does_not_move_the_committed_cache(tmp_path: Path):
    from data.energy_charts import cache_dir

    committed = cache_dir()
    with c16.synthetic_sealed_cache():
        assert cache_dir() == committed


def test_the_store_refuses_to_write_a_2025_metric(tmp_path: Path):
    from backtest.results_store import append_rows

    row = ResultRow(
        zone="DE-LU", tier="A", model="lear", metric="mae_eur_per_mwh",
        value=1.0, evaluation_years="2025",
    )
    with pytest.raises(SealedHoldoutError):
        append_rows(
            [row], cycle="C16probe", git_sha="x", config_hash="y",
            path=tmp_path / "results.csv", runs_path=tmp_path / "runs.json",
        )
    assert not (tmp_path / "results.csv").exists()


def test_the_runners_refuse_a_sealed_year_end_to_end():
    report = c16.run_cli_probes()
    assert report["n_cli_probes"] == len(c16.CLI_PROBES)
    for probe in report["cli_probes"]:
        assert probe["refused"] is True, probe
        assert probe["returncode"] != 0
        assert probe["mentions_sealed_holdout"] is True


# ---------------------------------------------------------------------------
# The artefact scan
# ---------------------------------------------------------------------------


def test_no_committed_artefact_carries_a_2025_row():
    report = c16.artefact_scan()
    assert report["clean"] is True
    assert report["artefacts_naming_the_holdout"] == {}
    assert 2025 not in report["evaluation_years_in_store"]
    assert report["n_tables_scanned"] > 100


def test_the_results_store_has_never_held_a_sealed_year():
    frame = read_results()
    years: set[int] = set()
    for spelling in frame["evaluation_years"].dropna().astype(str).unique():
        years |= c16._years_in(spelling)
    assert years and 2025 not in years


def test_artefact_scan_finds_a_planted_2025_table_row(tmp_path: Path):
    pd.DataFrame({"zone": ["DE-LU"], "year": [2025], "value": [1.0]}).to_csv(
        tmp_path / "planted.csv", index=False
    )
    with pytest.raises(c16.CheckpointError, match="planted.csv"):
        c16.artefact_scan(tmp_path)


def test_artefact_scan_finds_a_planted_2025_date_column(tmp_path: Path):
    pd.DataFrame({"day": ["2025-03-04"], "cash_eur": [1.0]}).to_csv(
        tmp_path / "planted_daily.csv", index=False
    )
    with pytest.raises(c16.CheckpointError, match="planted_daily.csv"):
        c16.artefact_scan(tmp_path)


def test_artefact_scan_finds_a_planted_2025_summary_key(tmp_path: Path):
    (tmp_path / "planted.json").write_text(
        json.dumps({"zone": "DE-LU", "last_day": "2025-09-30"}), encoding="utf-8"
    )
    with pytest.raises(c16.CheckpointError, match="planted.json"):
        c16.artefact_scan(tmp_path)


def test_artefact_scan_allows_the_structural_2025_dates(tmp_path: Path):
    """``main_backtest_end`` is *supposed* to say 2025-09-30."""
    (tmp_path / "cutover.json").write_text(
        json.dumps(
            {
                "sdac_15min_golive": "2025-10-01",
                "main_backtest_end": "2025-09-30",
                "sealed_years": [2025],
                "evaluated_years": [2020, 2021, 2022, 2023, 2024],
            }
        ),
        encoding="utf-8",
    )
    report = c16.artefact_scan(tmp_path)
    assert report["clean"] is True


# ---------------------------------------------------------------------------
# The download record
# ---------------------------------------------------------------------------


def test_the_download_record_names_no_sealed_year():
    report = c16.manifest_scan()
    assert report["clean"] is True
    assert report["sealed_years_found"] == []
    assert report["years_in_manifests"]["prices_manifest.csv"] == [
        2019, 2020, 2021, 2022, 2023, 2024
    ]
    assert report["years_in_manifests"]["exogenous_manifest.csv"] == [2022, 2023, 2024]
    assert report["raw_files_naming_a_sealed_year"] == []


def test_manifest_scan_finds_a_fetched_sealed_year(tmp_path: Path):
    pd.DataFrame(
        {"zone": ["DE-LU", "DE-LU"], "year": [2024, 2025],
         "first_ts_utc": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
         "last_ts_utc": ["2024-12-31T22:00:00+00:00", "2025-09-30T22:00:00+00:00"]}
    ).to_csv(tmp_path / "prices_manifest.csv", index=False)
    with pytest.raises(c16.CheckpointError, match="prices_manifest.csv"):
        c16.manifest_scan(tmp_path)


def test_manifest_scan_finds_a_sealed_coverage_timestamp(tmp_path: Path):
    """A 2025 coverage timestamp is a fetch even if the year column says 2024."""
    pd.DataFrame(
        {"zone": ["DE-LU"], "first_ts_utc": ["2024-01-01T00:00:00+00:00"],
         "last_ts_utc": ["2025-03-01T22:00:00+00:00"]}
    ).to_csv(tmp_path / "contract_report.csv", index=False)
    with pytest.raises(c16.CheckpointError, match="last_ts_utc"):
        c16.manifest_scan(tmp_path)


def test_manifest_scan_is_explicit_that_an_absent_raw_cache_is_not_evidence():
    """`data/raw/` is gitignored, so zero raw hits must not read as verified."""
    report = c16.manifest_scan()
    assert "raw_cache_present" in report
    assert report["raw_cache_present"] == (REPO_ROOT / "data" / "raw").exists()


# ---------------------------------------------------------------------------
# The pre-registration
# ---------------------------------------------------------------------------


def test_the_preregistered_window_is_the_whole_pre_cutover_year():
    doc = c16.preregistration()
    assert doc["window"]["first_market_day"] == "2025-01-01"
    assert doc["window"]["last_market_day"] == "2025-09-30"
    assert doc["window"]["n_market_days"] == 273


def test_the_preregistration_covers_every_zone_in_config():
    doc = c16.preregistration()
    zones = load_zones()
    assert doc["zones"]["tier_a"] == [k for k, z in zones.items() if z.tier == "A"]
    assert doc["zones"]["tier_b"] == [k for k, z in zones.items() if z.tier == "B"]
    assert len(doc["zones"]["tier_a"]) + len(doc["zones"]["tier_b"]) == len(zones)


def test_the_preregistered_dispatch_is_the_committed_battery():
    doc = c16.preregistration()
    cfg = load_battery_config()
    for key in (
        "power_mw",
        "duration_hours",
        "round_trip_efficiency",
        "throughput_cost_eur_per_mwh",
        "initial_soc_fraction",
    ):
        assert doc["dispatch"][key] == pytest.approx(float(cfg["battery"][key]))
    assert doc["dispatch"]["terminal_mode"] == cfg["terminal"]["mode"]
    assert doc["dispatch"]["commit_then_settle"] is True


def test_the_preregistered_intervals_are_the_committed_bootstrap():
    intervals = c16.preregistration()["metrics"]["intervals"]
    assert intervals["block_days_ladder"] == list(BLOCK_LADDER)
    assert intervals["n_replicates"] == DEFAULT_REPLICATES
    assert intervals["seed"] == DEFAULT_SEED


def test_the_preregistration_excludes_the_after_gate_closure_vintage():
    """PLAN.md's Art. 14 leak is reported in C8/C9, not dispatched on a holdout."""
    arms = c16.preregistration()["arms"]["tier_a_exogenous"]
    assert arms["excluded"] == "res_as_published"
    assert "res_as_published" not in arms["variants"]
    assert "after gate closure" in arms["why_excluded"]


def test_the_preregistration_carries_the_three_curves_the_invariants_relate():
    doc = c16.preregistration()
    assert doc["curves"] == ["oracle", "lear_full_history", "naive"]


def test_the_preregistration_states_the_per_day_and_pooled_invariants():
    text = " ".join(c16.preregistration()["assertions_that_must_hold"]).lower()
    assert "every dispatched day" in text
    assert "on average, not per day" in text
    assert "commit-then-settle" in text


def test_the_preregistration_forbids_changing_anything_after_the_first_number():
    rules = " ".join(c16.preregistration()["stop_rules"]).lower()
    assert "runs once" in rules
    assert "second evaluation" in rules
    assert "flag" in rules


def test_the_preregistration_names_the_two_preconditions_a_cycle_cannot_meet():
    pre = c16.preregistration()["preconditions"]
    assert "human_writes_the_unseal_marker" in pre
    assert "fetch_years" in pre["config_data_yaml_fetch_years_must_add_2025"]
    assert "entsoe_api_key" in pre


def test_the_2024_baseline_matches_the_committed_c13_table():
    doc = c16.preregistration()
    baseline = doc["baseline_2024_for_comparison"]
    frame = pd.read_csv(RESULTS_DIR / "c13_per_year_metrics.csv")
    rows = frame[(frame["year"] == 2024) & (frame["curve"] == "lear_full_history")]
    assert set(baseline) == set(rows["zone"])
    for _, row in rows.iterrows():
        got = baseline[str(row["zone"])]
        assert got["capture_rolled_oracle_cash"] == pytest.approx(
            float(row["capture_rolled_oracle_cash"]), abs=1e-6
        )
        assert got["dispatch_cash_eur_per_mw_year"] == pytest.approx(
            float(row["dispatch_cash_eur_per_mw_year"]), abs=5e-3
        )


def test_the_preregistration_is_stamped_with_this_commit_and_config():
    doc = c16.preregistration()
    assert doc["config_hash"] == config_hash()
    assert doc["status"].startswith("AWAITING HUMAN APPROVAL")


def test_prereg_refuses_to_write_after_an_unseal(monkeypatch: pytest.MonkeyPatch):
    """A pre-registration written once the holdout is visible is not one."""
    monkeypatch.setattr(c16, "holdout_is_unsealed", lambda *a, **k: True)
    with pytest.raises(c16.CheckpointError, match="not a pre-registration"):
        c16.prereg(write=False)


# ---------------------------------------------------------------------------
# The committed artefacts, and the whole report
# ---------------------------------------------------------------------------


def test_verify_passes_on_the_repository_as_committed():
    report = c16.verify(write=False)
    assert report["seal_intact"] is True
    assert report["holdout_year_touched_by_this_cycle"] is False
    assert report["refusal_probes"]["n_refused"] == report["refusal_probes"]["n_probes"]
    assert report["artefacts"]["clean"] is True
    assert report["download_record"]["clean"] is True


def test_the_committed_seal_verification_says_the_seal_held():
    path = RESULTS_DIR / "c16_seal_verification.json"
    assert path.exists(), "C16 must commit its verification"
    with path.open("r", encoding="utf-8") as fh:
        report = json.load(fh)
    assert report["seal_intact"] is True
    assert report["marker"]["holdout_is_unsealed"] is False
    assert report["marker"]["n_bare_marker_lines"] == 0
    assert report["split"]["sealed_years"] == [2025]
    assert report["refusal_probes"]["n_refused"] == report["refusal_probes"]["n_probes"]
    assert report["artefacts"]["clean"] is True
    assert report["download_record"]["clean"] is True


def test_the_committed_preregistration_still_matches_the_code_and_config():
    """If this fails, something moved after the spec was frozen — say so, loudly."""
    path = RESULTS_DIR / "c16_preregistration.json"
    assert path.exists(), "C16 must commit its pre-registration"
    with path.open("r", encoding="utf-8") as fh:
        committed = json.load(fh)
    fresh = json.loads(json.dumps(c16.preregistration(), default=str))
    for doc in (committed, fresh):
        doc.pop("written_at_utc", None)
        doc.pop("git_sha", None)
    assert committed == fresh
