"""C20 — the pre-public gate.

Every gate in ``backtest/run_c20_gate.py`` is tested by **making it fail**. A
secret scan that has only ever been run on a clean repository has not been
shown to detect anything, and "no findings" from such a scanner is
indistinguishable from "the scanner does not work". So the behavioural tests
here build small throwaway git repositories, plant the thing the gate is
supposed to catch, and assert it is caught — including inside a gzipped blob,
and including a secret that was committed and then deleted, which is the case a
working-tree scan misses and a public repository still exposes.

The integration tests that read *this* repository's object graph are skipped on
a shallow clone, with the reason stated: containers arrive at ``--depth 50`` and
a scan of 50 of 181 commits that reported "clean" would be a false negative
dressed as a pass. The gate refuses that case rather than answering it, and
that refusal is itself tested.
"""

from __future__ import annotations

import gzip
import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from backtest import run_c20_gate as c20

REPO_ROOT = Path(__file__).resolve().parent.parent

needs_full_clone = pytest.mark.skipif(
    c20.is_shallow(),
    reason=(
        "this checkout is a shallow clone; the history gates refuse to answer "
        "on 50 of 181 commits. Run `git fetch --unshallow` first."
    ),
)


# ---------------------------------------------------------------------------
# Helpers: a throwaway repository with a planted secret
# ---------------------------------------------------------------------------


def _init_repo(root: Path) -> None:
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "test"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True,
                       capture_output=True, text=True)


def _commit(root: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, check=True,
                   capture_output=True)


# ---------------------------------------------------------------------------
# The secret scan
# ---------------------------------------------------------------------------


PLANTED_TOKEN = "5f2c1b7e-44aa-4c3d-9e01-8b7d6a5f4e32"  # an ENTSO-E-shaped token


def test_a_committed_then_deleted_secret_is_still_found(tmp_path: Path) -> None:
    """The case the gate exists for: deleting the file does not unpublish it."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "settings.py").write_text(f'ENTSOE_API_KEY = "{PLANTED_TOKEN}"\n')
    _commit(root, "oops")
    (root / "settings.py").unlink()
    _commit(root, "remove it again")

    report = c20.scan_history_for_secrets(cwd=root)
    assert report["holds"] is False
    assert report["n_findings"] >= 1
    patterns = {f["pattern"] for f in report["findings"]}
    assert "uuid_token" in patterns
    assert all(f["path"] == "settings.py" for f in report["findings"])


def test_a_secret_inside_a_gzipped_artefact_is_found(tmp_path: Path) -> None:
    """108 committed artefacts are gzipped; a scanner that reads the compressed
    bytes would report this repository clean while shipping the key."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    payload = f"zone,note\nDE-LU,token {PLANTED_TOKEN}\n".encode()
    (root / "daily.csv.gz").write_bytes(gzip.compress(payload))
    _commit(root, "artefact")

    report = c20.scan_history_for_secrets(cwd=root)
    assert report["holds"] is False
    assert {f["pattern"] for f in report["findings"]} == {"uuid_token"}


def test_the_template_allowance_is_pinned_to_its_path(tmp_path: Path) -> None:
    """``ENTSOE_API_KEY=`` is allowed in ``.env.example`` and nowhere else."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / ".env.example").write_text("ENTSOE_API_KEY=\nAGSI_API_KEY=\n")
    _commit(root, "template only")
    assert c20.scan_history_for_secrets(cwd=root)["holds"] is True

    (root / "deploy.sh").write_text(f"ENTSOE_API_KEY={PLANTED_TOKEN}\n")
    _commit(root, "the same text, a different file")
    report = c20.scan_history_for_secrets(cwd=root)
    assert report["holds"] is False
    assert {f["path"] for f in report["findings"]} == {"deploy.sh"}


def test_a_finding_never_prints_the_whole_credential(tmp_path: Path) -> None:
    """A gate artefact that quoted the key in full would be the leak."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    long_key = "ghp_" + "A" * 60
    (root / "ci.yml").write_text(f"token: {long_key}\n")
    _commit(root, "ci")
    report = c20.scan_history_for_secrets(cwd=root)
    assert report["n_findings"] >= 1
    for finding in report["findings"]:
        assert len(finding["match_prefix"]) <= 24
        assert long_key not in json.dumps(report)


def test_the_history_scan_refuses_a_shallow_clone(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "a.txt").write_text("hello\n")
    _commit(root, "one")
    (root / ".git" / "shallow").write_text("deadbeef\n")
    assert c20.is_shallow(root) is True
    with pytest.raises(c20.GateError, match="shallow"):
        c20.scan_history_for_secrets(cwd=root)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("z" * 64, False),            # 64 characters, but not hex
        ("0" * 64, True),             # SHA-256
        ("7058c8b104418682f7e048b25eac34ac9152cf54", True),   # a git SHA
        ("856fb19ac0c4eecd", True),   # a library fingerprint
        ("7058c8b", True),            # an abbreviated SHA
        (PLANTED_TOKEN, False),       # a UUID is not hash-shaped (it has dashes)
        ("AKIAIOSFODNN7EXAMPLE", False),
    ],
)
def test_hash_shapes_are_recognised(value: str, expected: bool) -> None:
    assert c20._is_hash_shaped(value) is expected


def test_a_high_entropy_string_that_is_not_hash_shaped_stays_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The triage must not be "entropy findings are fine"."""
    sandbox = tmp_path / "tree"
    (sandbox / "backtest" / "results").mkdir(parents=True)
    target = sandbox / "backtest" / "results" / "x.json"
    # Assembled rather than written out: a literal fake credential in this file
    # would be a finding in the repository's own secret scan, and silencing that
    # by allowing `tests/` is exactly the exemption a real leak would hide behind.
    planted = "xo" + "xb-9999-" + "a" * 24
    target.write_text('{"key": "%s"}\n' % planted)
    monkeypatch.setattr(c20, "REPO_ROOT", sandbox)
    verdict = c20._classify_detect_secrets(
        "backtest/results/x.json",
        {"type": "Base64 High Entropy String", "line_number": 1},
    )
    assert verdict == "unresolved"


def test_a_committed_sha256_at_a_results_path_is_expected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = tmp_path / "tree"
    (sandbox / "data" / "manifest").mkdir(parents=True)
    target = sandbox / "data" / "manifest" / "prices_manifest.json"
    target.write_text('{"payload_sha256": "%s"}\n' % ("ab12cd34" * 8))
    monkeypatch.setattr(c20, "REPO_ROOT", sandbox)
    verdict = c20._classify_detect_secrets(
        "data/manifest/prices_manifest.json",
        {"type": "Hex High Entropy String", "line_number": 1},
    )
    assert verdict == "expected_hash"


@needs_full_clone
def test_this_repository_has_no_secret_in_any_commit() -> None:
    report = c20.scan_history_for_secrets()
    assert report["holds"] is True, report["findings"][:5]
    assert report["n_commits"] >= 181
    assert report["n_blobs_scanned"] > 500


# ---------------------------------------------------------------------------
# Size and raw data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected_rule",
    [
        ("data/raw/energy_charts/price/DE-LU/2024.json", "raw_data_cache"),
        ("prices.parquet", "parquet_bulk"),
        (".env", "dotenv"),
        ("deploy/.env.production", "dotenv"),
        ("data/manifest/fetch_failures.json", "fetch_failure_artefact"),
    ],
)
def test_forbidden_paths_are_matched(path: str, expected_rule: str) -> None:
    hits = {rule for rule, rx in c20.FORBIDDEN_PATH_RULES if rx.search(path)}
    assert expected_rule in hits


@pytest.mark.parametrize(
    "path", [".env.example", "data/manifest/prices_manifest.csv", "README.md"]
)
def test_allowed_paths_are_not_matched(path: str) -> None:
    assert not any(rx.search(path) for _, rx in c20.FORBIDDEN_PATH_RULES)


def test_the_gitignore_probe_reads_a_negation_as_kept() -> None:
    """``!.env.example`` is the one rule a naive reading of ``check-ignore``
    inverts, and it is the rule that decides whether the key template ships."""
    probe = c20._gitignore_probe()
    assert probe["holds"] is True, probe
    assert probe["matching_rule"][".env.example"].startswith("!")
    assert probe["matching_rule"][".env"] == ".env"


@needs_full_clone
def test_no_raw_data_was_ever_committed() -> None:
    report = c20.size_phase(write=False)
    assert report["raw_data_check"]["holds"] is True
    assert report["raw_data_check"]["violations"] == []
    assert report["raw_data_check"]["n_paths_ever_added"] > 100


@needs_full_clone
def test_no_committed_file_reaches_githubs_file_size_warning() -> None:
    report = c20.size_phase(write=False)
    assert report["github_thresholds"]["n_files_at_or_over_warn"] == 0
    assert report["github_thresholds"]["head_tree_under_recommended"] is True


def test_the_artefact_size_question_is_answered_not_merely_measured() -> None:
    """NOTE C15-04 handed C20 a decision; an artefact that only measured the
    size would leave it open for a cycle that no longer remembers it was asked."""
    decision = c20.ARTEFACT_SIZE_DECISION
    assert decision["decision"].startswith("no")
    assert len(decision["reasons"]) >= 3
    assert decision["revisit_if"]


# ---------------------------------------------------------------------------
# Licence and attribution
# ---------------------------------------------------------------------------


def test_every_committed_figure_has_a_known_producing_module() -> None:
    """An unowned figure cannot be checked at all, which is worse than failing."""
    figures = c20._figure_attribution_check({})
    assert figures["figures_with_no_known_producer"] == []
    assert figures["n_figures"] >= 20


def test_every_committed_figure_carries_the_data_attribution() -> None:
    from data.config import load_data_config

    sources = load_data_config().get("sources", {})
    figures = c20._figure_attribution_check(sources)
    assert figures["figures_whose_module_omits_attribution"] == []
    assert figures["n_attributed"] == figures["n_figures"]


def test_a_module_that_drops_one_token_fails_the_figure_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check must fail on a *partial* attribution, not only on none at all."""
    sandbox = tmp_path / "tree"
    (sandbox / "docs" / "figures").mkdir(parents=True)
    (sandbox / "docs" / "figures" / "prices_DE-LU.png").write_bytes(b"\x89PNG")
    (sandbox / "data").mkdir()
    (sandbox / "data" / "plot_prices.py").write_text(
        'ATTRIBUTION = "Data: Energy-Charts, CC BY 4.0"\n'  # no "Fraunhofer ISE"
    )
    monkeypatch.setattr(c20, "REPO_ROOT", sandbox)
    figures = c20._figure_attribution_check({})
    assert figures["holds"] is False
    assert figures["figures"][0]["tokens_missing"] == ["Fraunhofer ISE"]


def test_the_readme_carries_both_required_data_attributions() -> None:
    report = c20.licence_phase(write=False)
    for attribution in report["data_attributions"]:
        assert attribution["readme_tokens_missing"] == [], attribution
        assert attribution["config_declares_both"] is True


def test_the_code_licence_is_mit_and_named_in_the_readme() -> None:
    report = c20.licence_phase(write=False)["code_licence"]
    assert report["spdx"] == "MIT"
    assert report["has_copyright_line"] is True
    assert report["named_in_readme"] is True


def test_the_readme_separates_the_data_licence_from_the_code_licence() -> None:
    """MIT is the author's to give; CC BY 4.0 data is not."""
    disclosure = c20.licence_phase(write=False)["disclosure"]
    assert disclosure["data_licence_distinct_from_code_licence_stated"] is True
    assert disclosure["agent_built_disclosure_present"] is True


# ---------------------------------------------------------------------------
# Reproducibility: the artefact comparator
# ---------------------------------------------------------------------------


def _artefact_repo(tmp_path: Path, frame: pd.DataFrame) -> Path:
    root = tmp_path / "clone"
    (root / "backtest" / "results").mkdir(parents=True)
    _init_repo(root)
    frame.to_csv(root / "backtest" / "results" / "a_daily.csv", index=False)
    _commit(root, "committed artefact")
    return root


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "zone": ["DE-LU"] * 4,
            "year": [2023] * 4,
            "curve": ["lear"] * 4,
            "market_day": ["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04"],
            "cash": [1.5, -2.25, 0.0, 10.125],
            "n_cycles": [1, 2, 0, 1],
            "flagged": [False, False, False, True],
        }
    )


REL = "backtest/results/a_daily.csv"


def test_an_identical_recompute_reproduces(tmp_path: Path) -> None:
    root = _artefact_repo(tmp_path, _frame())
    result = c20._compare_to_committed(REL, cwd=root)
    assert result["holds"] is True
    assert result["worst_abs_numeric_gap"] == 0.0
    assert result["n_rows_joined"] == 4


def test_a_moved_number_fails_even_when_it_is_tiny(tmp_path: Path) -> None:
    root = _artefact_repo(tmp_path, _frame())
    drifted = _frame()
    drifted.loc[2, "cash"] = 1e-4
    drifted.to_csv(root / REL, index=False)
    result = c20._compare_to_committed(REL, cwd=root)
    assert result["holds"] is False
    assert "cash" in result["columns_over_atol"]


def test_a_moved_boolean_fails_although_no_number_changed(tmp_path: Path) -> None:
    """``cash`` reproducing while an invariant flag flipped is not a reproduction."""
    root = _artefact_repo(tmp_path, _frame())
    drifted = _frame()
    drifted.loc[0, "flagged"] = True
    drifted.to_csv(root / REL, index=False)
    result = c20._compare_to_committed(REL, cwd=root)
    assert result["holds"] is False
    assert result["boolean_columns_differing"] == ["flagged"]


def test_a_partial_recompute_is_reported_as_partial(tmp_path: Path) -> None:
    """Not a failure — a bounded run covers part of the committed file on
    purpose — but it must never read as "all 4 rows reproduced"."""
    root = _artefact_repo(tmp_path, _frame())
    _frame().iloc[:3].to_csv(root / REL, index=False)
    result = c20._compare_to_committed(REL, cwd=root)
    assert result["holds"] is True
    assert result["subset_of_committed"] is True
    assert result["n_rows_joined"] == 3
    assert result["n_rows_committed"] == 4
    assert result["n_committed_rows_not_recomputed"] == 1


def test_a_changed_column_set_fails_before_any_comparison(tmp_path: Path) -> None:
    root = _artefact_repo(tmp_path, _frame())
    renamed = _frame().rename(columns={"cash": "settled_cash"})
    renamed.to_csv(root / REL, index=False)
    result = c20._compare_to_committed(REL, cwd=root)
    assert result["holds"] is False
    assert result["reason"] == "column sets differ"


def test_an_absent_recompute_is_a_failure_not_a_pass(tmp_path: Path) -> None:
    """"Nothing was recomputed" must never read as "it reproduced"."""
    root = _artefact_repo(tmp_path, _frame())
    (root / REL).unlink()
    result = c20._compare_to_committed(REL, cwd=root)
    assert result["holds"] is False
    assert "nothing was recomputed" in result["reason"]


def test_the_repro_phase_fails_without_fresh_clone_evidence(tmp_path: Path) -> None:
    """Committed files agreeing with each other is a weaker claim than a clone."""
    missing = c20._read_clone_check(tmp_path / "absent.json")
    assert missing["holds"] is False
    assert missing["present"] is False
    assert "fresh-clone" in missing["reason"]


def test_the_committed_clone_check_evidence_holds() -> None:
    evidence = c20._read_clone_check(None)
    assert evidence["present"] is True, "c20_clone_check.json is not committed"
    assert evidence["holds"] is True
    assert evidence["clone_is_shallow"] is False
    assert evidence["n_artefacts_compared"] >= 1
    for artefact in evidence["artefacts"]:
        assert artefact["holds"] is True, artefact


# ---------------------------------------------------------------------------
# README claims
# ---------------------------------------------------------------------------


def test_the_readme_makes_no_unbound_quantitative_claim() -> None:
    report = c20.claims_phase(write=False)["quantitative_claims"]
    assert report["unbound"] == [], report["unbound"]


def test_a_planted_result_number_is_reported_as_unbound() -> None:
    planted = "The battery captures 91.9% of the perfect-foresight value.\n"
    report = c20._unbound_numbers(planted)
    assert report["holds"] is False
    assert report["unbound"][0]["number"] == "91.9"


@pytest.mark.parametrize(
    "line",
    [
        "Published 2026-10-29 at the owner's instruction.",
        "See Cycle 20 in PLAN.md.",
        "Licensed under CC BY 4.0.",
        "ENTSO-E Art. 14 wind and solar.",
        "Training runs 2019 to 2023.",
    ],
)
def test_references_are_not_mistaken_for_claims(line: str) -> None:
    assert c20._unbound_numbers(line + "\n")["holds"] is True


def test_every_bound_readme_number_agrees_with_its_artefact() -> None:
    report = c20.claims_phase(write=False)["bound_claims"]
    assert report["holds"] is True
    for binding in report["bindings"]:
        assert binding["found_in_readme"] is True, binding
        assert str(binding["readme_value"]) == str(binding["artefact_value"]), binding


def test_a_binding_whose_sentence_was_reworded_fails() -> None:
    """A table of bindings that silently stops matching is worse than none."""
    report = c20._bound_numbers("This README no longer mentions the scan at all.\n")
    assert report["holds"] is False
    assert report["bindings"][0]["found_in_readme"] is False


def test_the_readme_claim_that_the_holdout_is_unevaluated_is_checked_against_the_store() -> None:
    """The claim with teeth: prose against ``results.csv``, not against prose."""
    checks = c20.claims_phase(write=False)["factual_claims"]["checks"]
    holdout = next(c for c in checks if "holdout" in c["claim"])
    assert holdout["asserted_in_readme"] is True
    assert holdout["results_csv_has_2025"] is False
    assert holdout["holdout_ledger_has_a_completed_run"] is False
    assert holdout["holds"] is True
    assert "2025" not in holdout["evaluation_years_in_results_csv"]


def test_a_completed_holdout_entry_is_detected_whatever_the_ledger_nests_it_under() -> None:
    assert c20._ledger_completed_holdout({}) is False
    assert c20._ledger_completed_holdout(
        {"runs": [{"year": "2024", "status": "completed"}]}
    ) is False
    assert c20._ledger_completed_holdout(
        {"runs": [{"year": 2025, "status": "completed"}]}
    ) is True
    assert c20._ledger_completed_holdout(
        {"holdout": {"entries": {"a": {"year": 2025, "status": "COMPLETED"}}}}
    ) is True


def test_a_readme_still_claiming_the_gate_has_not_run_fails_once_it_has(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = (
        "**Status: no result here has been through the pre-public review gate.**\n"
        "It is public (since 2026-10-29).\n"
        "The 2025 holdout has not been evaluated.\n"
    )
    checks = c20._factual_claim_checks(stale)["checks"]
    gate = next(c for c in checks if "gate" in c["claim"])
    assert gate["asserted_in_readme"] is True
    # Four or more C20 artefacts exist in this repo, so the stale sentence is a
    # live contradiction rather than a matter of taste.
    assert len(gate["c20_artefacts_present"]) >= 4
    assert gate["holds"] is False


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


def test_the_gate_appends_nothing_to_the_results_store() -> None:
    """C20 measures; it must not become a producer of result rows.

    Checked statically rather than by running it: a test that only asserted the
    row count was unchanged would pass for a runner that wrote and rolled back.
    """
    source = (REPO_ROOT / "backtest" / "run_c20_gate.py").read_text(encoding="utf8")
    for forbidden in ("append_rows", "ResultRow", "_record_run"):
        assert forbidden not in source, f"C20 must not import or call {forbidden}"


def test_the_gate_report_is_the_conjunction_of_its_five_phases() -> None:
    """A gate whose summary can pass while a part fails is not a gate."""
    source = (REPO_ROOT / "backtest" / "run_c20_gate.py").read_text(encoding="utf8")
    assert '"holds": all(p["holds"] for p in parts.values())' in source
    assert set(c20.PHASES) >= {
        "secrets", "size", "licence", "repro", "claims", "clone-check", "all",
    }


def test_the_five_phase_artefacts_are_named_and_distinct() -> None:
    paths = [
        c20.SECRETS_PATH, c20.SIZE_PATH, c20.LICENCE_PATH,
        c20.REPRO_PATH, c20.CLAIMS_PATH, c20.GATE_PATH, c20.CLONE_CHECK_PATH,
    ]
    assert len({p.name for p in paths}) == len(paths)
    assert all(p.name.startswith("c20_") for p in paths)


def test_a_non_unique_join_key_is_refused_rather_than_cartesian_joined(
    tmp_path: Path,
) -> None:
    """The bug this comparator shipped with for one run.

    C13's prediction artefact is keyed on ``timestamp_utc``; joining it on
    ``market_day`` alone matched every hour of a day against every other hour
    and reported a 594.9 gap between two files that were in fact identical. A
    comparator that cannot identify a row must say so, not answer anyway.
    """
    frame = pd.DataFrame(
        {
            "market_day": ["2023-01-01"] * 3,
            "timestamp_utc": [
                "2023-01-01T00:00Z", "2023-01-01T01:00Z", "2023-01-01T02:00Z",
            ],
            "y_true": [10.0, 20.0, 30.0],
        }
    )
    assert c20._join_key(frame, frame) == ["timestamp_utc", "market_day"]

    unkeyed = frame.drop(columns=["timestamp_utc"])
    with pytest.raises(c20.GateError, match="cartesian"):
        c20._join_key(unkeyed, unkeyed)


def test_two_missing_values_are_not_a_difference(tmp_path: Path) -> None:
    """``NA == NA`` is NA, not True, so a naive text comparison reports every
    nullable column as differing — which is how this comparator first "found"
    a difference in ``train_from`` whose two sides held identical values."""
    frame = _frame().assign(train_from=[None, "2019-01-01", None, "2019-01-01"])
    root = tmp_path / "clone"
    (root / "backtest" / "results").mkdir(parents=True)
    _init_repo(root)
    frame.to_csv(root / REL, index=False)
    _commit(root, "artefact with nulls")
    result = c20._compare_to_committed(REL, cwd=root)
    assert result["holds"] is True
    assert result["other_columns_differing"] == []


def test_a_bounded_recompute_may_cover_a_subset_but_not_add_a_row(
    tmp_path: Path,
) -> None:
    """C15's committed artefact holds six rungs; the cheap reproduction run
    re-solves one. That is a subset, not a disagreement. A recomputed row with
    no committed partner is a disagreement."""
    root = _artefact_repo(tmp_path, _frame())
    _frame().iloc[:2].to_csv(root / REL, index=False)
    subset = c20._compare_to_committed(REL, cwd=root)
    assert subset["holds"] is True
    assert subset["subset_of_committed"] is True
    assert subset["n_committed_rows_not_recomputed"] == 2

    extra = pd.concat(
        [_frame(), _frame().iloc[[0]].assign(market_day="2023-02-01")],
        ignore_index=True,
    )
    extra.to_csv(root / REL, index=False)
    added = c20._compare_to_committed(REL, cwd=root)
    assert added["holds"] is False
    assert added["n_recomputed_rows_without_a_committed_partner"] == 1


def test_the_fresh_clone_resolved_a_different_library_set_than_the_published_one() -> None:
    """The finding behind NOTE C20-02, asserted so it cannot quietly stop being
    true: `requirements.txt` declares floors, so a reader cloning today does
    **not** get the library set the published numbers were produced under."""
    evidence = c20._read_clone_check(None)
    assert evidence["resolved_library_fingerprint"] != "856fb19ac0c4eecd"
    assert evidence["holds"] is True, (
        "and the numbers reproduced anyway, which is the point of the note"
    )
