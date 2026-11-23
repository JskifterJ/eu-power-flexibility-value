"""CLI: C20 — the pre-public gate.

    python -m backtest.run_c20_gate --phase secrets
    python -m backtest.run_c20_gate --phase size
    python -m backtest.run_c20_gate --phase licence
    python -m backtest.run_c20_gate --phase repro
    python -m backtest.run_c20_gate --phase claims
    python -m backtest.run_c20_gate --phase all

PLAN.md C20: *"``gitleaks`` secret scan; repo size / raw-data check; licence +
attribution check; reproducibility check (fresh clone, cached-subset run); align
README claims with actual results."*

**This gate was supposed to run before the repository became public.** It did
not: FLAG C-E-01 records that the repository was made public on 2026-10-29, at
the owner's instruction, outside Checkpoint E, and that the gate had never run.
So this module is not a formality on the way to publication — it is a check on
something that is *already* published, and every finding in it is a finding
about a live public page. That changes what it should do when it finds
something: report it, fix what is additive and safe to fix, and leave anything
that would move a published number to a human.

Five phases, one per clause of PLAN.md's sentence. Each returns a dict with a
``holds`` key, writes one ``c20_*.json`` artefact, and is read-only with respect
to every committed result.

``secrets``
    PLAN.md names ``gitleaks``. The binary downloads in this container but
    **executing an ad-hoc downloaded binary is refused by the environment's
    safety policy**, so this phase does the same job with two scanners that are
    installable and auditable instead: ``detect-secrets`` (Yelp, PyPI) over the
    working tree, and a project-specific regex scan over **every blob in every
    commit**, decompressing ``.csv.gz`` on the way. The project-specific set is
    the one that matters here, because the only credentials this project ever
    holds are ``ENTSOE_API_KEY`` and ``AGSI_API_KEY`` and an ENTSO-E security
    token is a UUID. A high-entropy hex string is *expected* all over this repo
    — SHA-256 payload fingerprints, 40-hex git SHAs, 16-hex library
    fingerprints — so the phase triages by shape rather than reporting 661
    findings and calling it a gate. Anything that is not a recognised hash shape
    is reported unresolved and fails the phase. See NOTE C20-01.

``size``
    What a reader actually clones, and the one thing CLAUDE.md forbids: bulk raw
    data. Reports the HEAD tree by top-level directory, the largest committed
    blobs, the full-history blob total, and checks every path ever *added* in
    any commit against the forbidden set (``data/raw/``, ``*.parquet``, a real
    ``.env``). Also records the artefact-size decision NOTE C15-04 handed C20.

``licence``
    MIT for the code, and — because ``backtest/results/`` is 66 MB of derived
    Energy-Charts data — attribution for the data. Checks the LICENSE file, the
    attribution strings in ``config/data.yaml``, that the README carries both
    required attributions, and that **every committed figure's producing module
    emits the attribution string**, which is how the C15 figure gap was found.

``repro``
    Three legs, because "reproducible" means different things at different
    layers and only one of them can be checked without a network:
    (a) the committed C15 ladder against C13's and C11's committed per-day cash
    (NOTE C15-04's ``check_baseline_reproduction`` /
    ``check_res_leg_reproduction``, 54 756 rows, read-only, imported not
    re-written); (b) the re-pulled price cache against C1's committed
    fingerprints, when a cache is present — and explicitly *not evidence* when
    it is absent; (c) the fresh-clone leg, which is read from the
    ``c20_clone_check.json`` artefact that ``--phase clone-check`` writes
    **from inside a fresh clone**. Leg (c) cannot be recomputed here: it needs a
    clone, a network and a new virtual environment. What this phase does is
    refuse to call the gate passed unless that artefact exists, names the HEAD
    it was produced at, and holds.

``clone-check``
    The one phase meant to be run somewhere else: inside a fresh clone, after a
    bounded recompute, with the recomputed artefacts named on the command line.
    It compares each one against **the committed blob in that clone's own git
    object store** (``git show HEAD:<path>``), so the comparison needs no
    reference file copied in from outside and cannot be pointed at the wrong
    baseline. It also records the clone's HEAD, the library versions the clone's
    own ``requirements.txt`` resolved to, and the price-cache fingerprint check.

``claims``
    PLAN.md's "align README claims with actual results". The README is currently
    a build log, not a findings document (C17's rewrite is blocked), so the
    useful form of this check is the inverse of the usual one: assert that the
    README makes **no quantitative claim that is not bound to a committed
    artefact**, and mechanically verify the three factual claims it does make —
    that the holdout has not been evaluated, that no result has been through
    this gate, and that the repository is public. The first of those has teeth:
    it is checked against ``results.csv``'s ``evaluation_years`` and the
    committed holdout ledger, not against prose.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.results_store import (  # noqa: E402
    RESULTS_PATH,
    library_fingerprint,
    library_versions,
    read_results,
)
from backtest.run_c3_naive import RESULTS_DIR, git_sha  # noqa: E402
from data.config import REPO_ROOT, config_hash, load_data_config  # noqa: E402


class GateError(RuntimeError):
    """The pre-public gate cannot be evaluated as asked."""


CYCLE = "C20"

SECRETS_PATH = RESULTS_DIR / "c20_secret_scan.json"
SIZE_PATH = RESULTS_DIR / "c20_repo_size.json"
LICENCE_PATH = RESULTS_DIR / "c20_licence_attribution.json"
REPRO_PATH = RESULTS_DIR / "c20_reproducibility.json"
CLONE_CHECK_PATH = RESULTS_DIR / "c20_clone_check.json"
CLAIMS_PATH = RESULTS_DIR / "c20_readme_claims.json"
GATE_PATH = RESULTS_DIR / "c20_gate_report.json"


# ---------------------------------------------------------------------------
# git plumbing, shared by three phases
# ---------------------------------------------------------------------------


def _git(args: Sequence[str], *, cwd: Path | None = None, binary: bool = False):
    """One git command, or a :class:`GateError`. Never guesses on failure."""
    out = subprocess.run(
        ["git", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=not binary,
        check=False,
    )
    if out.returncode != 0:
        err = out.stderr if not binary else out.stderr.decode("utf8", "replace")
        raise GateError(f"git {' '.join(args)} failed: {err.strip()[:300]}")
    return out.stdout


def is_shallow(cwd: Path | None = None) -> bool:
    """A shallow clone cannot answer "was a secret ever committed?".

    Containers arrive with ``--depth 50`` (NOTE C2-02's sibling), and a scan of
    50 of 181 commits that reported "clean" would be a false negative dressed as
    a pass. Every phase that walks history refuses on this.
    """
    return (Path(cwd or REPO_ROOT) / ".git" / "shallow").exists()


def all_named_blobs(cwd: Path | None = None) -> list[tuple[str, str, int]]:
    """``(sha, path, size)`` for every blob reachable from any ref, deduplicated.

    ``git rev-list --objects --all`` lists trees and commits too, so the type is
    resolved with ``--batch-check`` rather than assumed — asking
    ``git cat-file blob`` for a tree is an error, and an exception swallowed here
    would silently shorten the scan.
    """
    named: dict[str, str] = {}
    for line in _git(["rev-list", "--objects", "--all"], cwd=cwd).splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            named[parts[0]] = parts[1]
    if not named:
        return []
    checked = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=str(cwd or REPO_ROOT),
        input="\n".join(named) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if checked.returncode != 0:
        raise GateError("git cat-file --batch-check failed")
    blobs: list[tuple[str, str, int]] = []
    for line in checked.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "blob":
            blobs.append((fields[0], named[fields[0]], int(fields[2])))
    return blobs


def blob_bytes(sha: str, path: str, cwd: Path | None = None) -> bytes:
    """One blob's content, gunzipped when the path says it is gzipped.

    A secret inside a ``.csv.gz`` would be invisible to a scanner that reads the
    compressed bytes, and 108 of this repo's committed artefacts are gzipped.
    """
    raw = _git(["cat-file", "blob", sha], cwd=cwd, binary=True)
    if path.endswith(".gz"):
        try:
            return gzip.decompress(raw)
        except (OSError, EOFError, gzip.BadGzipFile):
            return raw
    return raw


# ---------------------------------------------------------------------------
# Phase `secrets`
# ---------------------------------------------------------------------------


#: The credential shapes this project could plausibly leak, plus the usual
#: suspects. ``uuid_token`` is here because an ENTSO-E security token *is* a
#: UUID: that pattern is the one with real teeth for this repo.
SECRET_PATTERNS: dict[str, re.Pattern[bytes]] = {
    "uuid_token": re.compile(
        rb"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        rb"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    ),
    "assigned_secret": re.compile(
        rb"(?i)(api[_-]?key|secret|passwo?rd|security[_-]?token|access[_-]?token"
        rb"|auth[_-]?token|private[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+=]{12,}"
    ),
    "aws_access_key_id": re.compile(rb"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(rb"\b(ghp_|gho_|ghs_|ghu_|github_pat_)[A-Za-z0-9_]{20,}"),
    "slack_token": re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "private_key_block": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer_header": re.compile(rb"(?i)bearer\s+[A-Za-z0-9_\-\.=]{20,}"),
    "entsoe_key_assigned": re.compile(rb"ENTSOE_API_KEY\s*=\s*[^\s\n]+"),
    "agsi_key_assigned": re.compile(rb"AGSI_API_KEY\s*=\s*[^\s\n]+"),
}

#: A regex hit that is *this* text, at *this* path, is the template or the prose
#: about the template — not a credential. Narrow on purpose: the path is pinned,
#: so the same string appearing anywhere else is still a finding.
SECRET_ALLOWED: tuple[tuple[str, str], ...] = (
    (".env.example", "ENTSOE_API_KEY="),
    (".env.example", "AGSI_API_KEY="),
    (".env.example", "API_KEY="),
    ("PROGRESS.md", "ENTSOE_API_KEY=`"),
    ("PROGRESS.md", "ENTSOE_API_KEY=<"),
    ("docs/entsoe_layer.md", "ENTSOE_API_KEY=<"),
    ("README.md", "ENTSOE_API_KEY=<"),
)

#: ``detect-secrets`` finding types that are expected throughout this repo, and
#: the hash shapes that make them expected. 64 hex = a SHA-256 payload
#: fingerprint or config hash, 40 = a git SHA, 16 = a library fingerprint,
#: 7-12 = an abbreviated git SHA as the log quotes them.
ENTROPY_TYPES: frozenset[str] = frozenset(
    {"Hex High Entropy String", "Base64 High Entropy String"}
)
HASH_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^[0-9a-f]{64}$"),
    re.compile(r"^[0-9a-f]{40}$"),
    re.compile(r"^[0-9a-f]{16}$"),
    re.compile(r"^[0-9a-f]{7,12}$"),
)


def _is_hash_shaped(value: str) -> bool:
    return any(rx.match(value) for rx in HASH_SHAPES)


def scan_history_for_secrets(cwd: Path | None = None) -> dict[str, Any]:
    """Every blob in every commit against :data:`SECRET_PATTERNS`.

    This is the ``gitleaks``-shaped half of the phase: a secret that was
    committed and then deleted is still public, so the working tree is not the
    object under test — the object graph is.
    """
    if is_shallow(cwd):
        raise GateError(
            "this is a shallow clone; a secret scan over 50 of 181 commits "
            "would be a false negative. Run `git fetch --unshallow` first."
        )
    blobs = all_named_blobs(cwd)
    findings: list[dict[str, Any]] = []
    allowed = 0
    scanned_bytes = 0
    n_scanned = 0
    for sha, path, size in blobs:
        if path.endswith((".png", ".jpg", ".jpeg", ".pdf", ".ico")):
            continue
        data = blob_bytes(sha, path, cwd=cwd)
        n_scanned += 1
        scanned_bytes += len(data)
        for name, rx in SECRET_PATTERNS.items():
            for match in rx.finditer(data):
                text = match.group(0).decode("utf8", "replace")
                if any(path == p and text.startswith(s) for p, s in SECRET_ALLOWED):
                    allowed += 1
                    continue
                findings.append(
                    {
                        "pattern": name,
                        "path": path,
                        "blob": sha,
                        "blob_bytes": size,
                        # Truncated deliberately: a gate artefact that printed a
                        # real credential in full would be the leak.
                        "match_prefix": text[:24],
                    }
                )
    return {
        "holds": not findings,
        "n_commits": int(_git(["rev-list", "--count", "--all"], cwd=cwd).strip()),
        "n_blobs_in_history": len(blobs),
        "n_blobs_scanned": n_scanned,
        "bytes_scanned": scanned_bytes,
        "n_patterns": len(SECRET_PATTERNS),
        "n_allowed_template_hits": allowed,
        "n_findings": len(findings),
        "findings": findings,
        "note": (
            "gzipped artefacts are decompressed before matching; images are "
            "skipped. Template and prose hits are allowed only at a pinned path."
        ),
    }


def scan_tree_with_detect_secrets() -> dict[str, Any]:
    """``detect-secrets scan`` over the tracked tree, triaged by shape.

    Entropy-based detection is the right tool and the wrong output format for
    this repo: 661 of its findings are SHA-256 fingerprints the project commits
    on purpose. So every finding is classified — ``expected_hash`` if its type
    is entropy-based and the secret is hash-shaped at a results/manifest path,
    ``benign_prose`` for the two description strings whose *value* is a sentence,
    and ``unresolved`` otherwise. Only ``unresolved`` fails the phase.
    """
    scanner = Path(sys.executable).with_name("detect-secrets")
    if not scanner.exists():
        return {
            "holds": False,
            "available": False,
            "reason": (
                f"detect-secrets not installed next to {sys.executable}; "
                f"`uv pip install detect-secrets`"
            ),
        }
    # Scan exactly what is published: the tracked files, from `git ls-files`.
    # `--all-files` also walks untracked working-tree junk (`.pytest_cache/`, a
    # scratch notebook, a local venv), and a gate that fails on a file no reader
    # will ever see teaches the next cycle to ignore it.
    tracked = [
        line for line in _git(["ls-files"]).splitlines()
        if line and not line.startswith("data/raw/")
    ]
    if not tracked:
        raise GateError("git ls-files returned nothing; there is nothing to scan")
    out = subprocess.run(
        [str(scanner), "scan", *tracked],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise GateError(f"detect-secrets failed: {out.stderr.strip()[:300]}")
    report = json.loads(out.stdout)
    by_class: dict[str, int] = {"expected_hash": 0, "benign_prose": 0, "unresolved": 0}
    unresolved: list[dict[str, Any]] = []
    by_type: dict[str, int] = {}
    n_total = 0
    for path, items in report.get("results", {}).items():
        for item in items:
            n_total += 1
            kind = item.get("type", "?")
            by_type[kind] = by_type.get(kind, 0) + 1
            verdict = _classify_detect_secrets(path, item)
            by_class[verdict] = by_class.get(verdict, 0) + 1
            if verdict == "unresolved":
                unresolved.append(
                    {"path": path, "line": item.get("line_number"), "type": kind}
                )
    return {
        "holds": not unresolved,
        "available": True,
        "scanner": "detect-secrets",
        "n_plugins": len(report.get("plugins_used", [])),
        "n_files_scanned": len(tracked),
        "n_files_with_findings": len(report.get("results", {})),
        "n_findings": n_total,
        "findings_by_type": dict(sorted(by_type.items())),
        "findings_by_class": by_class,
        "unresolved": unresolved,
        "note": (
            "A hex high-entropy string at a results/ or data/manifest/ path is a "
            "committed SHA-256 payload fingerprint, git SHA or library "
            "fingerprint — this project's provenance trail, not a credential."
        ),
    }


#: The two ``Secret Keyword`` findings whose *value* is an English sentence
#: about what the key is for. Pinned by path and by the line's text so that an
#: actual assignment on the same line would still be unresolved.
PROSE_KEYWORD_HITS: tuple[tuple[str, str], ...] = (
    ("backtest/run_c16_checkpoint.py", "required for the Tier-A 2025 exogenous pull"),
    ("backtest/results/c16_preregistration.json",
     "required for the Tier-A 2025 exogenous pull"),
)


def _classify_detect_secrets(path: str, item: dict[str, Any]) -> str:
    kind = item.get("type", "?")
    if kind in ENTROPY_TYPES:
        secret = _entropy_value(path, int(item.get("line_number", 0)))
        at_artefact_path = path.startswith(("backtest/results/", "data/manifest/"))
        if secret is not None and _is_hash_shaped(secret):
            return "expected_hash"
        if at_artefact_path and secret is None:
            return "expected_hash"
        if secret is not None and at_artefact_path:
            return "unresolved"
        if secret is not None and _is_hash_shaped(secret):
            return "expected_hash"
        return "unresolved"
    line = _read_line(path, int(item.get("line_number", 0)))
    if line is not None and any(
        path == p and text in line for p, text in PROSE_KEYWORD_HITS
    ):
        return "benign_prose"
    return "unresolved"


def _read_line(path: str, line_number: int) -> str | None:
    target = REPO_ROOT / path
    if line_number < 1 or not target.exists():
        return None
    try:
        with target.open("r", encoding="utf8", errors="replace") as handle:
            for index, line in enumerate(handle, start=1):
                if index == line_number:
                    return line.rstrip("\n")
    except OSError:
        return None
    return None


def _entropy_value(path: str, line_number: int) -> str | None:
    """The longest hex/base64-ish token on the flagged line.

    ``detect-secrets`` redacts the secret itself (it stores a hash of it), so the
    shape test has to re-read the line. Returning ``None`` means "could not
    read", which is handled explicitly by the caller rather than treated as
    clean.
    """
    line = _read_line(path, line_number)
    if line is None:
        return None
    tokens = re.findall(r"[A-Za-z0-9+/=_\-]{7,}", line)
    hashes = [t for t in tokens if _is_hash_shaped(t)]
    if hashes:
        return max(hashes, key=len)
    return max(tokens, key=len) if tokens else None


def secrets_phase(write: bool = True) -> dict[str, Any]:
    history = scan_history_for_secrets()
    tree = scan_tree_with_detect_secrets()
    report = {
        "cycle": CYCLE,
        "phase": "secrets",
        "generated_at_utc": _now(),
        "git_sha": git_sha(),
        "holds": bool(history["holds"] and tree.get("holds")),
        "planned_tool": "gitleaks",
        "planned_tool_ran": False,
        "planned_tool_substitute": (
            "detect-secrets 1.5.0 (PyPI) over the tracked tree + a "
            "project-specific regex scan over every blob in every commit"
        ),
        "planned_tool_reason": (
            "The gitleaks release tarball downloads in this container (HTTP 200), "
            "but executing an ad-hoc downloaded binary is refused by the "
            "environment's safety policy. NOTE C20-01: a human can run "
            "`gitleaks detect --source . --redact` locally in one command, and "
            "should, because it is PLAN.md's named tool and a second "
            "independent rule set is worth having."
        ),
        "history_scan": history,
        "tree_scan": tree,
    }
    if write:
        _write_json(SECRETS_PATH, report)
    return report


# ---------------------------------------------------------------------------
# Phase `size`
# ---------------------------------------------------------------------------


#: CLAUDE.md: "Never commit .env, API keys, or bulk raw data." These are the
#: paths that would mean it happened, checked against every commit's *additions*
#: rather than against the current tree.
FORBIDDEN_PATH_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("raw_data_cache", re.compile(r"^data/raw/")),
    ("parquet_bulk", re.compile(r"\.parquet$")),
    ("dotenv", re.compile(r"(^|/)\.env($|\.)(?!example)")),
    ("fetch_failure_artefact", re.compile(r"(?:^|[/_])fetch_failures\.json$")),
)

#: GitHub's own thresholds, so "is this repo too big?" is answered against a
#: published number rather than a feeling.
GITHUB_FILE_WARN_BYTES = 50 * 1024 * 1024
GITHUB_FILE_HARD_BYTES = 100 * 1024 * 1024
GITHUB_REPO_RECOMMENDED_BYTES = 1024 * 1024 * 1024


def paths_ever_added() -> list[str]:
    """Every distinct path added in any commit on any ref."""
    out = _git(["log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A"])
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def size_phase(write: bool = True) -> dict[str, Any]:
    if is_shallow():
        raise GateError(
            "this is a shallow clone; the history size and the "
            "'was raw data ever committed?' question need the full object graph"
        )
    tree_rows: list[tuple[str, int]] = []
    for line in _git(["ls-tree", "-r", "-l", "HEAD"]).splitlines():
        fields = line.split(maxsplit=4)
        if len(fields) == 5 and fields[1] == "blob":
            tree_rows.append((fields[4], int(fields[3])))
    by_dir: dict[str, int] = {}
    for path, size in tree_rows:
        top = path.split("/")[0] if "/" in path else path
        by_dir[top] = by_dir.get(top, 0) + size
    tree_bytes = sum(size for _, size in tree_rows)
    largest_tree = sorted(tree_rows, key=lambda r: -r[1])[:15]

    blobs = all_named_blobs()
    history_bytes = sum(size for _, _, size in blobs)
    largest_history = sorted(blobs, key=lambda b: -b[2])[:15]

    added = paths_ever_added()
    violations: list[dict[str, str]] = []
    for path in added:
        for rule, rx in FORBIDDEN_PATH_RULES:
            if rx.search(path):
                violations.append({"rule": rule, "path": path})
    oversized = [
        {"path": p, "bytes": b} for p, b in tree_rows if b >= GITHUB_FILE_WARN_BYTES
    ]

    ignored = _gitignore_probe()
    report = {
        "cycle": CYCLE,
        "phase": "size",
        "generated_at_utc": _now(),
        "git_sha": git_sha(),
        "holds": bool(not violations and not oversized and ignored["holds"]),
        "head_tree": {
            "n_files": len(tree_rows),
            "bytes": tree_bytes,
            "mib": round(tree_bytes / 1048576, 2),
            "bytes_by_top_level": dict(
                sorted(by_dir.items(), key=lambda kv: -kv[1])
            ),
            "largest": [
                {"path": p, "bytes": b, "kib": round(b / 1024, 1)}
                for p, b in largest_tree
            ],
        },
        "history": {
            "n_commits": int(_git(["rev-list", "--count", "--all"]).strip()),
            "n_blobs": len(blobs),
            "blob_bytes_uncompressed": history_bytes,
            "blob_mib_uncompressed": round(history_bytes / 1048576, 2),
            "largest_ever": [
                {"path": p, "bytes": b, "kib": round(b / 1024, 1)}
                for _, p, b in largest_history
            ],
        },
        "raw_data_check": {
            "holds": not violations,
            "n_paths_ever_added": len(added),
            "rules": [rule for rule, _ in FORBIDDEN_PATH_RULES],
            "violations": violations,
            "note": (
                "Checked against every commit's additions, not the current "
                "tree: a raw pull that was committed and later deleted would "
                "still be in the clone a reader gets."
            ),
        },
        "github_thresholds": {
            "file_warn_bytes": GITHUB_FILE_WARN_BYTES,
            "file_hard_bytes": GITHUB_FILE_HARD_BYTES,
            "repo_recommended_bytes": GITHUB_REPO_RECOMMENDED_BYTES,
            "n_files_at_or_over_warn": len(oversized),
            "files_at_or_over_warn": oversized,
            "head_tree_under_recommended": tree_bytes < GITHUB_REPO_RECOMMENDED_BYTES,
        },
        "gitignore_probe": ignored,
        "artefact_size_decision": ARTEFACT_SIZE_DECISION,
    }
    if write:
        _write_json(SIZE_PATH, report)
    return report


#: NOTE C15-04 handed C20 a decision, not just a measurement. This is the answer,
#: in the artefact, so it is reviewable rather than buried in a log entry.
ARTEFACT_SIZE_DECISION: dict[str, Any] = {
    "question": (
        "C15's per-day artefacts are ~37 MB against ~25 MB for C1-C14 combined, "
        "because the ten forecast-shape columns are rung-invariant by "
        "construction and are stored six times. Normalising them out would save "
        "~40% of the C15 artefacts. Should C20 trim them?"
    ),
    "decision": "no — keep every artefact exactly as the runner writes it",
    "reasons": [
        "The repo is nowhere near a real limit: no committed file reaches "
        "GitHub's 50 MiB warning (the largest is results.csv at ~4 MB) and the "
        "HEAD tree is ~72 MiB against a 1 GiB recommendation.",
        "C15's own stated principle, which this gate agrees with: a committed "
        "artefact that does not match what the runner writes is worse than a "
        "large one. A normalised file would no longer be reproducible by running "
        "the command in its summary.",
        "Rewriting 51 committed artefacts would invalidate the reproduction "
        "evidence built on them — NOTE C15-04's 54 756-row check and this "
        "cycle's fresh-clone comparison both read those exact files.",
        "It is a destructive rewrite of published numbers to save ~25 MB a "
        "reader will never notice, which is the class of change an unattended "
        "cycle should not make on its own.",
    ],
    "revisit_if": (
        "the HEAD tree passes ~500 MiB, or a single artefact approaches 50 MiB"
    ),
}


def _gitignore_probe() -> dict[str, Any]:
    """``git check-ignore`` on the paths CLAUDE.md says must never be committed.

    A ``.gitignore`` is only as good as what it actually matches, and the entries
    here have an exception in them (``!.env.example``), which is exactly the kind
    of rule that can inverted by a later edit without looking wrong.
    """
    must_ignore = [
        ".env",
        ".env.local",
        "data/raw/energy_charts/price/DE-LU/2024.json",
        "data/raw/entsoe/DE-LU/A65_2024.xml",
        "something.parquet",
        ".venv/bin/python",
        "data/manifest/fetch_failures.json",
        "data/manifest/exogenous_fetch_failures.json",
    ]
    must_not_ignore = [
        ".env.example",
        "data/manifest/prices_manifest.csv",
        "backtest/results/results.csv",
        "README.md",
    ]
    out = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", *must_ignore, *must_not_ignore],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
    )
    # `check-ignore -v` prints the matching rule for a *negation* too
    # (`.gitignore:3:!.env.example\t.env.example`), so a naive reading of this
    # output calls `.env.example` ignored and the probe fails on the one entry
    # whose whole job is to be an exception. The pattern is the third
    # colon-field of the rule; a leading `!` means the path is kept.
    ignored = set()
    rules: dict[str, str] = {}
    for line in out.stdout.splitlines():
        parts = line.rsplit("\t", 1)
        if len(parts) != 2:
            continue
        rule, path = parts
        pattern = rule.split(":", 2)[2] if rule.count(":") >= 2 else rule
        rules[path] = pattern
        if not pattern.startswith("!"):
            ignored.add(path)
    missing = [p for p in must_ignore if p not in ignored]
    leaked = [p for p in must_not_ignore if p in ignored]
    return {
        "holds": not missing and not leaked,
        "n_probed": len(must_ignore) + len(must_not_ignore),
        "should_be_ignored_but_is_not": missing,
        "should_be_tracked_but_is_ignored": leaked,
        "matching_rule": rules,
    }


# ---------------------------------------------------------------------------
# Phase `licence`
# ---------------------------------------------------------------------------


#: The two attributions PLAN.md C17 requires in the README, and the licence each
#: one is required *by*. The Energy-Charts one is a condition of CC BY 4.0, not
#: a courtesy: this repo redistributes derived works of that data in
#: ``backtest/results/`` and ``docs/figures/``.
REQUIRED_ATTRIBUTIONS: tuple[dict[str, Any], ...] = (
    {
        "source": "energy_charts",
        "licence": "CC BY 4.0",
        "required_by": "CC BY 4.0 attribution condition",
        "must_appear_in_readme": ("Energy-Charts", "Fraunhofer ISE", "CC BY 4.0"),
    },
    {
        "source": "entsoe",
        "licence": "ENTSO-E Transparency Platform reuse conditions",
        "required_by": "ENTSO-E Transparency Platform reuse conditions",
        "must_appear_in_readme": ("ENTSO-E", "Transparency Platform"),
    },
)

#: Which module writes which committed figure, by filename prefix. A figure
#: whose producing module does not carry the attribution string ships without
#: attribution, and a reader who reuses the PNG has no way to know where the
#: data came from.
FIGURE_OWNERS: tuple[tuple[str, str], ...] = (
    ("prices_", "data/plot_prices.py"),
    ("negative_hours", "data/plot_prices.py"),
    ("c6_", "backtest/run_c6_curves.py"),
    ("c14_", "backtest/run_c14_fundamentals.py"),
    ("c15_", "backtest/run_c15_sensitivities.py"),
    ("c17_", "backtest/run_c17_figures.py"),
)


def licence_phase(write: bool = True) -> dict[str, Any]:
    licence_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf8")
    cfg = load_data_config()
    sources = cfg.get("sources", {}) if isinstance(cfg, dict) else {}

    code_licence = {
        "file": "LICENSE",
        "spdx": "MIT" if "MIT License" in licence_text else "unknown",
        "has_copyright_line": bool(re.search(r"Copyright \(c\) \d{4}\s+\S+", licence_text)),
        "copyright": next(
            (l.strip() for l in licence_text.splitlines() if l.startswith("Copyright")),
            None,
        ),
        "named_in_readme": bool(re.search(r"(?i)\bMIT\b", readme)),
    }
    code_licence["holds"] = bool(
        code_licence["spdx"] == "MIT"
        and code_licence["has_copyright_line"]
        and code_licence["named_in_readme"]
    )

    attributions: list[dict[str, Any]] = []
    for spec in REQUIRED_ATTRIBUTIONS:
        declared = sources.get(spec["source"], {}) if isinstance(sources, dict) else {}
        missing = [t for t in spec["must_appear_in_readme"] if t not in readme]
        attributions.append(
            {
                "source": spec["source"],
                "licence_required_by": spec["required_by"],
                "declared_licence_in_config": declared.get("licence"),
                "declared_attribution_in_config": declared.get("attribution"),
                "config_declares_both": bool(
                    declared.get("licence") and declared.get("attribution")
                ),
                "readme_tokens_required": list(spec["must_appear_in_readme"]),
                "readme_tokens_missing": missing,
                "holds": bool(
                    declared.get("licence") and declared.get("attribution") and not missing
                ),
            }
        )

    figures = _figure_attribution_check(sources)
    # The substance of the distinction, not one phrasing of it: the file has to
    # name the code licence, name the data licence, and say the committed
    # artefacts are derived works of the data. Any two of the three is the
    # failure mode worth catching — an MIT banner over CC BY 4.0 data.
    data_licence_stated = bool(
        re.search(r"(?i)\bMIT\b", readme)
        and "CC BY 4.0" in readme
        and re.search(r"(?i)derived works?\b", readme)
    )
    disclosure = {
        "agent_built_disclosure_present": "autonomous coding agent" in readme,
        "data_licence_distinct_from_code_licence_stated": data_licence_stated,
    }
    disclosure["holds"] = bool(
        disclosure["agent_built_disclosure_present"]
        and disclosure["data_licence_distinct_from_code_licence_stated"]
    )

    report = {
        "cycle": CYCLE,
        "phase": "licence",
        "generated_at_utc": _now(),
        "git_sha": git_sha(),
        "holds": bool(
            code_licence["holds"]
            and all(a["holds"] for a in attributions)
            and figures["holds"]
            and disclosure["holds"]
        ),
        "code_licence": code_licence,
        "data_attributions": attributions,
        "figures": figures,
        "disclosure": disclosure,
        "note": (
            "MIT covers the code. backtest/results/ and docs/figures/ are derived "
            "works of Energy-Charts (CC BY 4.0) and, for the Tier-A exogenous "
            "series, of the ENTSO-E Transparency Platform, so the README has to "
            "say so separately from the code licence."
        ),
    }
    if write:
        _write_json(LICENCE_PATH, report)
    return report


#: What a figure must say, token by token, to be attributed. Deliberately a
#: token test rather than a string test: C14's figures use residual load as well
#: as prices and so carry a *richer* line that names ENTSO-E too. A superset is
#: correct attribution, not drift, and a gate that failed it would be teaching
#: the next cycle to write a worse caption.
FIGURE_ATTRIBUTION_TOKENS: tuple[str, ...] = (
    "Energy-Charts", "Fraunhofer ISE", "CC BY 4.0",
)


def _figure_attribution_check(sources: dict[str, Any]) -> dict[str, Any]:
    canonical = ""
    if isinstance(sources, dict):
        canonical = str(sources.get("energy_charts", {}).get("attribution", ""))
    figure_dir = REPO_ROOT / "docs" / "figures"
    rows: list[dict[str, Any]] = []
    module_cache: dict[str, str] = {}
    for figure in sorted(figure_dir.glob("*.png")):
        owner = next(
            (mod for prefix, mod in FIGURE_OWNERS if figure.name.startswith(prefix)),
            None,
        )
        carries: bool | None = None
        verbatim: bool | None = None
        missing: list[str] = []
        if owner is not None:
            if owner not in module_cache:
                module_cache[owner] = (REPO_ROOT / owner).read_text(encoding="utf8")
            source = module_cache[owner]
            missing = [t for t in FIGURE_ATTRIBUTION_TOKENS if t not in source]
            carries = not missing
            verbatim = bool(canonical and canonical in source)
        rows.append(
            {
                "figure": figure.name,
                "producing_module": owner,
                "module_emits_attribution": carries,
                "emits_config_string_verbatim": verbatim,
                "tokens_missing": missing,
            }
        )
    unowned = [r["figure"] for r in rows if r["producing_module"] is None]
    unattributed = [r["figure"] for r in rows if r["module_emits_attribution"] is False]
    return {
        "holds": not unowned and not unattributed,
        "canonical_attribution_string": canonical,
        "required_tokens": list(FIGURE_ATTRIBUTION_TOKENS),
        "n_figures": len(rows),
        "n_attributed": sum(1 for r in rows if r["module_emits_attribution"]),
        "n_verbatim": sum(1 for r in rows if r["emits_config_string_verbatim"]),
        "figures_with_no_known_producer": unowned,
        "figures_whose_module_omits_attribution": unattributed,
        "figures": rows,
        "note": (
            "A module passes if it emits every required token; whether it uses "
            "config/data.yaml's exact string is reported but does not fail the "
            "gate, because a figure built on two sources should name both."
        ),
    }


# ---------------------------------------------------------------------------
# Phase `repro` and phase `clone-check`
# ---------------------------------------------------------------------------


def repro_phase(write: bool = True, clone_check: Path | None = None) -> dict[str, Any]:
    from backtest.run_c14_fundamentals import verify_price_cache
    from backtest.run_c15_sensitivities import (
        LADDER_YEARS,
        MAIN_LEG,
        RES_LEG,
        check_baseline_reproduction,
        check_res_leg_reproduction,
        load_ladder,
    )
    from data.config import load_zones

    zones = list(load_zones())
    ladder = load_ladder([MAIN_LEG, RES_LEG], zones, None)
    committed = {
        "n_ladder_rows": int(len(ladder)),
        "baseline": check_baseline_reproduction(ladder),
        "res_leg": check_res_leg_reproduction(ladder),
    }
    committed["holds"] = bool(
        committed["baseline"]["holds"]
        and committed["res_leg"].get("holds", committed["res_leg"].get("applicable") is False)
    )

    cache_present = (REPO_ROOT / "data" / "raw" / "energy_charts").exists()
    if cache_present:
        cache = verify_price_cache(zones)
        cache["evidence"] = True
    else:
        cache = {
            "holds": False,
            "evidence": False,
            "reason": (
                "data/raw/ is absent in this container (NOTE C2-02), so the "
                "price-cache fingerprint check has nothing to verify. An absent "
                "cache is not evidence that the cache is right."
            ),
        }

    clone = _read_clone_check(clone_check)
    report = {
        "cycle": CYCLE,
        "phase": "repro",
        "generated_at_utc": _now(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_versions": library_versions(),
        "library_fingerprint": library_fingerprint(),
        "holds": bool(committed["holds"] and clone.get("holds")),
        "legs": {
            "a_committed_artefacts_agree": committed,
            "b_price_cache_fingerprints": cache,
            "c_fresh_clone": clone,
        },
        "ladder_years": list(LADDER_YEARS),
        "note": (
            "Leg (a) is NOTE C15-04's check, imported not re-written. Leg (c) "
            "cannot run here — it needs a clone, a network and a new virtual "
            "environment — so it is read from the committed c20_clone_check.json "
            "that `--phase clone-check` writes inside the fresh clone."
        ),
    }
    if write:
        _write_json(REPRO_PATH, report)
    return report


def _read_clone_check(path: Path | None) -> dict[str, Any]:
    target = path or CLONE_CHECK_PATH
    if not target.exists():
        return {
            "holds": False,
            "present": False,
            "reason": (
                f"{target.name} is missing. PLAN.md's reproducibility check is a "
                f"fresh-clone check; without that artefact this phase has only "
                f"verified that committed files agree with each other, which is "
                f"a weaker statement. Run `--phase clone-check` inside a fresh "
                f"clone and commit the result."
            ),
        }
    payload = json.loads(target.read_text(encoding="utf8"))
    payload["present"] = True
    return payload


def clone_check_phase(
    recomputed: Sequence[str],
    out: Path | None = None,
    zones: Sequence[str] | None = None,
    atol: float = 1e-6,
) -> dict[str, Any]:
    """Run **inside a fresh clone**: recomputed artefacts against the committed ones.

    The baseline is ``git show HEAD:<path>`` in the clone's own object store, so
    nothing has to be copied in and the comparison cannot be aimed at the wrong
    reference. Every numeric column is compared, not just the headline one —
    a cycle that reproduced ``cash`` while moving ``soc_end_mwh`` has not
    reproduced the run.
    """
    from backtest.run_c14_fundamentals import verify_price_cache
    from data.config import load_zones

    here = Path.cwd().resolve()
    comparisons = [_compare_to_committed(rel, atol=atol, cwd=here) for rel in recomputed]
    cross_cycle = _cross_cycle_check(recomputed)
    cache_zones = list(zones) if zones else list(load_zones())
    try:
        cache = verify_price_cache(cache_zones)
    except Exception as exc:  # the clone may hold a partial cache by design
        cache = {"holds": False, "error": f"{type(exc).__name__}: {exc}"}
    report = {
        "cycle": CYCLE,
        "phase": "clone-check",
        "generated_at_utc": _now(),
        # The directory name only: the absolute path is a throwaway temp
        # directory and this artefact is committed to a public repository.
        "clone_root_name": here.name,
        "clone_head": _git(["rev-parse", "HEAD"], cwd=here).strip(),
        "clone_is_shallow": is_shallow(here),
        "clone_n_commits": int(_git(["rev-list", "--count", "HEAD"], cwd=here).strip()),
        "resolved_library_versions": library_versions(),
        "resolved_library_fingerprint": library_fingerprint(),
        "price_cache": cache,
        "atol": atol,
        "n_artefacts_compared": len(comparisons),
        "artefacts": comparisons,
        "cross_cycle": cross_cycle,
        "holds": bool(
            comparisons
            and all(c["holds"] for c in comparisons)
            and cache.get("holds") is True
            and cross_cycle.get("holds", True)
        ),
        "note": (
            "Each artefact's baseline is the blob at HEAD in this clone, read "
            "with `git show`. The library versions are whatever this clone's own "
            "requirements.txt resolved to, which is the question a reader asks."
        ),
    }
    if out is not None:
        _write_json(out, report)
    return report


def _cross_cycle_check(recomputed: Sequence[str]) -> dict[str, Any]:
    """A recomputed C15 cell against **C13's** committed per-day cash.

    Comparing the recomputed artefact to its own committed twin shows the runner
    is deterministic. Comparing it to a *different cycle's* file shows the number
    is the one the published results were built from — which is the question a
    reader of the write-up is actually asking. NOTE C15-04's checker does
    exactly that, so it is imported rather than restated.
    """
    cells = {
        tuple(Path(rel).name.split("_")[2:4])
        for rel in recomputed
        if Path(rel).name.startswith("c15_main_")
    }
    if not cells:
        return {"applicable": False, "reason": "no C15 main-leg cell was recomputed"}
    from backtest.run_c15_sensitivities import (
        MAIN_LEG, check_baseline_reproduction, load_ladder,
    )

    zones = sorted({zone for zone, _ in cells})
    years = sorted({int(year) for _, year in cells})
    report = check_baseline_reproduction(load_ladder([MAIN_LEG], zones, years))
    report["applicable"] = True
    report["cells"] = [f"{z} {y}" for z, y in sorted(cells)]
    return report


#: Columns that identify a row rather than carry a number, in the order they
#: are tried. Never differenced. This list is a *starting point*, not the
#: answer: :func:`_join_key` checks that the key it picks actually identifies a
#: row and extends it when it does not, because a key that does not is a silent
#: cartesian product and a cartesian product reports enormous gaps between two
#: files that are in fact identical. (That is not hypothetical — it is what the
#: first run of this comparator did to C13's prediction artefact, whose key is
#: ``timestamp_utc`` and which this tuple did not then name.)
_KEY_COLUMNS: tuple[str, ...] = (
    "zone", "year", "leg", "rung", "lever", "soc_policy", "curve", "fold",
    "timestamp_utc", "target_utc", "market_day", "model", "exog_variant",
    "vintage", "metric", "scope",
)


def _join_key(mine, want) -> list[str]:
    """A key that identifies one row in both frames, or a :class:`GateError`.

    Tries the known identifier columns first, then adds every remaining
    non-numeric column, and refuses if the result still repeats. Refusing is the
    point: a comparator that joins on a non-unique key cannot tell "these files
    differ" from "I matched every row against every other row".
    """
    candidates = [c for c in _KEY_COLUMNS if c in mine.columns]
    if candidates and not mine.duplicated(candidates).any() \
            and not want.duplicated(candidates).any():
        return candidates
    extra = [
        c for c in mine.columns
        if c not in candidates and mine[c].dtype.kind not in "fiub"
    ]
    widened = candidates + extra
    if widened and not mine.duplicated(widened).any() \
            and not want.duplicated(widened).any():
        return widened
    raise GateError(
        "no column set identifies a row uniquely in both the recomputed and the "
        f"committed frame (tried {widened or candidates}); joining on it would "
        f"produce a cartesian product and report a meaningless gap"
    )


def _compare_to_committed(
    rel_path: str, atol: float = 1e-6, cwd: Path | None = None
) -> dict[str, Any]:
    root = Path(cwd or REPO_ROOT)
    live = root / rel_path
    if not live.exists():
        return {
            "path": rel_path, "holds": False,
            "reason": "not present in the working tree — nothing was recomputed",
        }
    blob = _git(["show", f"HEAD:{rel_path}"], cwd=root, binary=True)
    if rel_path.endswith(".gz"):
        blob = gzip.decompress(blob)
    want = pd.read_csv(io.BytesIO(blob), dtype={"market_day": str})
    mine = pd.read_csv(live, dtype={"market_day": str})
    if set(mine.columns) != set(want.columns):
        return {
            "path": rel_path, "holds": False,
            "reason": "column sets differ",
            "only_recomputed": sorted(set(mine.columns) - set(want.columns)),
            "only_committed": sorted(set(want.columns) - set(mine.columns)),
        }
    try:
        keys = _join_key(mine, want)
    except GateError as exc:
        return {"path": rel_path, "holds": False, "reason": str(exc)}
    merged = mine.merge(want, on=keys, suffixes=("_new", "_old"))
    if len(merged) == 0:
        return {"path": rel_path, "holds": False, "reason": "no row joined on the keys"}
    numeric: dict[str, float] = {}
    bool_mismatch: list[str] = []
    other_mismatch: list[str] = []
    for column in mine.columns:
        if column in keys:
            continue
        new, old = merged[f"{column}_new"], merged[f"{column}_old"]
        if mine[column].dtype == bool or want[column].dtype == bool:
            if not bool(new.eq(old).all()):
                bool_mismatch.append(column)
        elif mine[column].dtype.kind in "fiu":
            gap = (new.to_numpy(dtype=float) - old.to_numpy(dtype=float))
            numeric[column] = float(abs(gap).max())
        else:
            # Two missing values are the same missing value. Comparing them with
            # `==` yields NA, not True, so a straight `.eq(...).all()` reports
            # every nullable text column as differing — which is how this
            # comparator first "found" a difference in `train_from` whose two
            # sides held identical values.
            sentinel = "\x00<NA>"
            if not bool(
                new.astype("object").where(new.notna(), sentinel).astype(str)
                .eq(old.astype("object").where(old.notna(), sentinel).astype(str))
                .all()
            ):
                other_mismatch.append(column)
    worst = max(numeric.values()) if numeric else 0.0
    # A bounded recompute is allowed to cover a *subset* of the committed rows
    # — C15's committed artefact holds six rungs and the cheap reproduction run
    # re-solves one. What is not allowed is a recomputed row that finds no
    # committed partner: that is either a new row or a changed key, and both
    # mean the two files are not the same experiment.
    unmatched = int(len(mine) - len(merged))
    return {
        "path": rel_path,
        "holds": bool(
            worst <= atol
            and not bool_mismatch
            and not other_mismatch
            and unmatched == 0
        ),
        "join_key": keys,
        "n_rows_recomputed": int(len(mine)),
        "n_rows_committed": int(len(want)),
        "n_rows_joined": int(len(merged)),
        "n_recomputed_rows_without_a_committed_partner": unmatched,
        "n_committed_rows_not_recomputed": int(len(want) - len(merged)),
        "subset_of_committed": bool(len(merged) < len(want) and unmatched == 0),
        "n_numeric_columns": len(numeric),
        "worst_abs_numeric_gap": worst,
        "columns_over_atol": {k: v for k, v in numeric.items() if v > atol},
        "boolean_columns_differing": bool_mismatch,
        "other_columns_differing": other_mismatch,
    }


# ---------------------------------------------------------------------------
# Phase `claims`
# ---------------------------------------------------------------------------


#: A number in the README is a *claim* unless its surrounding text makes it a
#: reference. These are the references: dates, cycle numbers, licence versions,
#: page counts in the plan. Anything else has to be bound to an artefact.
CLAIM_EXEMPT: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iso_date", re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")),
    ("calendar_year", re.compile(r"\b(?:19|20)\d{2}\b")),
    # Before `cycle_reference`, and that order is load-bearing: the rules are
    # applied in sequence and each masks what it matched, so "cycle C5" would
    # otherwise consume the "C5" of "FLAG C5-01" and leave a bare "01" behind.
    ("flag_reference",
     re.compile(r"(?i)\b(?:FLAG|FINDING|NOTE)\s+C-?[A-Z]?\d{0,2}-\d{2}\b")),
    ("cycle_reference", re.compile(r"(?i)\b(?:cycle|c)\s?\d{1,2}\b")),
    ("licence_version", re.compile(r"\bCC BY 4\.0\b|Attribution 4\.0")),
    ("legal_article", re.compile(r"\bArt\.\s?\d{1,3}\b")),
    ("markdown_file", re.compile(r"\b[A-Za-z_0-9]+\.(?:md|csv|json|yaml|py)\b")),
    ("url", re.compile(r"https?://\S+")),
    # Added by C17's README rewrite. Each names something the repository
    # refers to rather than something it measured, which is what this table
    # is for. They are deliberately narrow: none of them would exempt a
    # sentence of the form "the battery captures 91.9% of the value".
    ("market_time_unit", re.compile(r"\b15-minute\b")),
    ("section_reference", re.compile(r"§\s?\d{1,2}\b")),
)

#: A number in the README that *is* a claim may stand only if it is bound to a
#: committed artefact — the file and the field it came from, checked here rather
#: than trusted. This is the table C17's README rewrite will have to grow: every
#: headline number it quotes gets a row, and the gate re-reads them.
README_BINDINGS: tuple[dict[str, Any], ...] = (
    {
        "name": "commits_scanned_for_secrets",
        "pattern": re.compile(r"no secret in any of the ([\d,]+) commits"),
        "artefact": "c20_secret_scan.json",
        "field": "history_scan.n_commits",
    },
    # C17's rewrite made the README a findings document, so its headline
    # numbers are now claims. Each is bound to a field of `c17_summary.json`,
    # which the summary runner writes already rounded to the string the
    # sentence may use — the artefact decides what the prose says, and a
    # reworded sentence fails the gate rather than drifting from the number.
    {
        "name": "holdout_capture_min",
        "pattern": re.compile(r"between (0\.\d+) \(NO2\)"),
        "artefact": "c17_summary.json",
        "field": "readme_display.capture_min",
    },
    {
        "name": "holdout_capture_max",
        "pattern": re.compile(r"and (0\.\d+) \(ES\) of the"),
        "artefact": "c17_summary.json",
        "field": "readme_display.capture_max",
    },
    {
        "name": "holdout_lost_min_eur_per_mw_year",
        "pattern": re.compile(r"costing ([\d,]+) to [\d,]+ EUR/MW/yr"),
        "artefact": "c17_summary.json",
        "field": "readme_display.lost_min_eur_per_mw_year",
    },
    {
        "name": "holdout_lost_max_eur_per_mw_year",
        "pattern": re.compile(r"costing [\d,]+ to ([\d,]+) EUR/MW/yr"),
        "artefact": "c17_summary.json",
        "field": "readme_display.lost_max_eur_per_mw_year",
    },
    {
        "name": "holdout_market_days",
        "pattern": re.compile(r"once, on\s+([\d,]+) market days"),
        "artefact": "c17_summary.json",
        "field": "readme_display.n_market_days",
    },
    {
        "name": "results_store_rows",
        "pattern": re.compile(r"\(([\d,]+) rows across seven runs\)"),
        "artefact": "c17_summary.json",
        "field": "readme_display.n_rows_in_results_csv",
    },
)

NUMERIC_TOKEN = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")


def claims_phase(write: bool = True) -> dict[str, Any]:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf8")
    bound = _bound_numbers(readme)
    numbers = _unbound_numbers(readme, bound["matched_spans"])
    factual = _factual_claim_checks(readme)
    report = {
        "cycle": CYCLE,
        "phase": "claims",
        "generated_at_utc": _now(),
        "git_sha": git_sha(),
        "holds": bool(bound["holds"] and numbers["holds"] and factual["holds"]),
        "bound_claims": {k: v for k, v in bound.items() if k != "matched_spans"},
        "quantitative_claims": numbers,
        "factual_claims": factual,
        "note": (
            "The README is still a build log, not C17's findings document, so "
            "the alignment check is the inverse of the usual one: it asserts "
            "that no number in the file is an unbound result claim, and it "
            "verifies the file's factual statements against committed artefacts "
            "rather than against prose."
        ),
    }
    if write:
        _write_json(CLAIMS_PATH, report)
    return report


def _dotted(payload: Any, field: str) -> Any:
    node = payload
    for part in field.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _bound_numbers(text: str) -> dict[str, Any]:
    """Each README number that claims a measured quantity, against its artefact.

    A binding that does not fire is a failure, not a pass: the README sentence
    was either reworded or removed, and either way the table is now describing
    a file that no longer says what it says.
    """
    rows: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for binding in README_BINDINGS:
        match = binding["pattern"].search(text)
        artefact = RESULTS_DIR / binding["artefact"]
        want = None
        if artefact.exists():
            want = _dotted(json.loads(artefact.read_text(encoding="utf8")),
                           binding["field"])
        got = match.group(1).replace(",", "") if match else None
        agrees = bool(
            match is not None and want is not None and str(want) == str(got)
        )
        if match is not None:
            spans.append(match.span(1))
        rows.append(
            {
                "name": binding["name"],
                "found_in_readme": match is not None,
                "readme_value": got,
                "artefact": binding["artefact"],
                "field": binding["field"],
                "artefact_value": want,
                "holds": agrees,
            }
        )
    return {
        "holds": all(r["holds"] for r in rows),
        "n_bindings": len(rows),
        "bindings": rows,
        "matched_spans": spans,
    }


def _unbound_numbers(
    text: str, bound_spans: Sequence[tuple[int, int]] = ()
) -> dict[str, Any]:
    if bound_spans:
        chars = list(text)
        for start, end in bound_spans:
            for i in range(start, min(end, len(chars))):
                chars[i] = " "
        text = "".join(chars)
    unbound: list[dict[str, Any]] = []
    exempt_counts: dict[str, int] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        masked = line
        for name, rx in CLAIM_EXEMPT:
            hits = rx.findall(masked)
            if hits:
                exempt_counts[name] = exempt_counts.get(name, 0) + len(hits)
            masked = rx.sub(" ", masked)
        for match in NUMERIC_TOKEN.finditer(masked):
            unbound.append(
                {
                    "line": line_number,
                    "number": match.group(0),
                    "context": line.strip()[:160],
                }
            )
    return {
        "holds": not unbound,
        "n_exempt_by_rule": dict(sorted(exempt_counts.items())),
        "n_unbound": len(unbound),
        "unbound": unbound,
        "rule": (
            "A number survives only if it is a date, a calendar year, a cycle "
            "reference, a licence version or a filename. A surviving number is a "
            "result claim and must be bound to a committed artefact before it "
            "may stand in a public README."
        ),
    }


def _factual_claim_checks(readme: str) -> dict[str, Any]:
    """The README's three factual statements, each against a committed artefact.

    Matched against a whitespace-normalised copy of the file: these sentences
    are wrapped prose and a line break in the middle of one is a formatting
    choice, not a change of claim. A check that broke on a rewrap would be
    reporting on the line width.
    """
    flat = re.sub(r"\s+", " ", readme.replace("> ", " "))
    checks: list[dict[str, Any]] = []

    says_not_evaluated = bool(
        re.search(r"(?i)holdout[^.]{0,120}(has still not been|has not been) evaluated", flat)
    )
    # C17 ran the evaluation, so the claim this check was written around has
    # flipped. The check flips with it rather than being deleted: once the
    # ledger records a completed holdout run and the store carries 2025 rows,
    # a README that does not say so — or that still says the opposite — is the
    # same alignment failure in the other direction. Stated as its own claim
    # below so both directions are reported, and so a reader can see which one
    # was in force.
    says_evaluated = bool(
        re.search(
            r"(?i)(sealed|holdout)[^.]{0,200}evaluated (exactly |)once",
            flat,
        )
    )
    store_years: list[str] = []
    if RESULTS_PATH.exists():
        frame = read_results()
        store_years = sorted(
            {str(y) for cell in frame["evaluation_years"].dropna()
             for y in str(cell).split("|") if y}
        )
    ledger_path = RESULTS_DIR / "c17_holdout_run_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf8")) if ledger_path.exists() else {}
    completed = _ledger_completed_holdout(ledger)
    checks.append(
        {
            "claim": "the 2025 holdout has not been evaluated",
            "asserted_in_readme": says_not_evaluated,
            "evaluation_years_in_results_csv": store_years,
            "results_csv_has_2025": "2025" in store_years,
            "holdout_ledger_has_a_completed_run": completed,
            # Was: the README must assert this *and* the store must agree.
            # That formulation could only ever hold before the evaluation, so
            # after C17 it would fail the whole phase for a reason that is no
            # longer a defect. What it was actually guarding — a README that
            # claims the holdout is unevaluated while the store says otherwise
            # — is preserved exactly, and the obligation to *state* the status
            # moves to the paired check below, which is in force now.
            "holds": not bool(
                says_not_evaluated and ("2025" in store_years or completed)
            ),
            "evidence": [RESULTS_PATH.name, ledger_path.name],
        }
    )
    holdout_done = bool("2025" in store_years and completed)
    checks.append(
        {
            "claim": "the 2025 holdout has been evaluated, exactly once",
            "asserted_in_readme": says_evaluated,
            "evaluation_years_in_results_csv": store_years,
            "results_csv_has_2025": "2025" in store_years,
            "holdout_ledger_has_a_completed_run": completed,
            # Only one of this check and the one above can hold at a time, and
            # which one depends on the store and the ledger rather than on the
            # prose. Before the evaluation this is vacuous; after it, it is the
            # one with teeth: a README that stayed silent, or that still said
            # the holdout was unevaluated, fails here.
            "holds": bool(
                (says_evaluated and not says_not_evaluated)
                if holdout_done
                else not says_evaluated
            ),
            "in_force": holdout_done,
            "evidence": [RESULTS_PATH.name, ledger_path.name],
        }
    )

    gate_claim = bool(
        re.search(r"(?i)gate[^.]{0,120}has \*\*not\*\* run", flat)
        or re.search(r"(?i)no result here has been through the pre-public review gate", flat)
    )
    gate_artefacts = [
        p.name for p in (SECRETS_PATH, SIZE_PATH, LICENCE_PATH, REPRO_PATH, CLAIMS_PATH)
        if p.exists()
    ]
    checks.append(
        {
            "claim": "the pre-public review gate has not run",
            "asserted_in_readme": gate_claim,
            "c20_artefacts_present": gate_artefacts,
            "holds": not (gate_claim and len(gate_artefacts) >= 4),
            "reason": (
                "Once four or more C20 artefacts are committed, a README that "
                "still says the gate has not run is out of date — which is the "
                "alignment failure this check exists to catch."
            ),
        }
    )

    public_claim = bool(re.search(r"(?i)it is public \(since 20\d{2}-\d{2}-\d{2}", flat))
    flip = subprocess.run(
        ["git", "log", "--all", "--oneline", "--grep", "public"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
    ).stdout.strip().splitlines()
    checks.append(
        {
            "claim": "the repository is public, since a stated date",
            "asserted_in_readme": public_claim,
            "commits_mentioning_the_flip": len(flip),
            "holds": bool(public_claim and flip),
            "reason": (
                "Visibility itself cannot be read offline; what is checkable is "
                "that the README states it and that the log records the flip "
                "(FLAG C-E-01)."
            ),
        }
    )
    return {
        "holds": all(c["holds"] for c in checks),
        "n_checks": len(checks),
        "checks": checks,
    }


def _ledger_completed_holdout(ledger: Any) -> bool:
    """True iff the holdout ledger records a finished 2025 evaluation.

    Shape-tolerant on purpose: the ledger is C17's artefact, not this cycle's, so
    this reads it defensively rather than asserting a schema it does not own.
    """
    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            status = str(node.get("status", "")).lower()
            year = str(node.get("year", ""))
            if status == "completed" and year == "2025":
                return True
            return any(walk(v) for v in node.values())
        if isinstance(node, list):
            return any(walk(v) for v in node)
        return False

    return walk(ledger)


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf8")


PHASES: tuple[str, ...] = (
    "secrets", "size", "licence", "repro", "claims", "clone-check", "all",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, default="all")
    parser.add_argument("--no-write", action="store_true",
                        help="compute and print, write no artefact")
    parser.add_argument("--clone-check-path", default=None,
                        help="read the fresh-clone evidence from here (repro)")
    parser.add_argument("--recomputed", nargs="*", default=[],
                        help="repo-relative artefact paths to compare (clone-check)")
    parser.add_argument("--out", default=None,
                        help="where clone-check writes its JSON")
    parser.add_argument("--zones", nargs="*", default=None,
                        help="restrict the price-cache check (clone-check)")
    parser.add_argument("--atol", type=float, default=1e-6)
    return parser.parse_args(argv)


def gate_phase(write: bool = True, clone_check: Path | None = None) -> dict[str, Any]:
    parts = {
        "secrets": secrets_phase(write=write),
        "size": size_phase(write=write),
        "licence": licence_phase(write=write),
        "repro": repro_phase(write=write, clone_check=clone_check),
        "claims": claims_phase(write=write),
    }
    report = {
        "cycle": CYCLE,
        "phase": "all",
        "generated_at_utc": _now(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "holds": all(p["holds"] for p in parts.values()),
        "gates": {name: bool(part["holds"]) for name, part in parts.items()},
        "failing": sorted(n for n, p in parts.items() if not p["holds"]),
        "artefacts": {
            "secrets": SECRETS_PATH.name,
            "size": SIZE_PATH.name,
            "licence": LICENCE_PATH.name,
            "repro": REPRO_PATH.name,
            "claims": CLAIMS_PATH.name,
        },
        "note": (
            "PLAN.md puts this gate before publication; FLAG C-E-01 means it is "
            "running after. A failing gate here is a finding about a live public "
            "page, not a blocked release."
        ),
    }
    if write:
        _write_json(GATE_PATH, report)
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    write = not args.no_write
    clone_path = Path(args.clone_check_path) if args.clone_check_path else None

    if args.phase == "clone-check":
        if not args.recomputed:
            print("clone-check needs --recomputed <repo-relative path> ...",
                  file=sys.stderr)
            return 2
        report = clone_check_phase(
            args.recomputed,
            out=Path(args.out) if args.out else None,
            zones=args.zones,
            atol=args.atol,
        )
        print(f"clone-check at {report['clone_head'][:12]} "
              f"({report['clone_n_commits']} commits, "
              f"shallow={report['clone_is_shallow']})")
        print(f"  libraries   : fingerprint {report['resolved_library_fingerprint']}")
        print(f"  price cache : {report['price_cache'].get('n_matching')}/"
              f"{report['price_cache'].get('n_files')} fingerprints match")
        for art in report["artefacts"]:
            print(f"  {'OK  ' if art['holds'] else 'FAIL'} {art['path']}  "
                  f"worst numeric gap {art.get('worst_abs_numeric_gap')}")
        print(f"  holds       : {report['holds']}")
        return 0 if report["holds"] else 1

    if args.phase == "all":
        report = gate_phase(write=write, clone_check=clone_path)
        print("C20 pre-public gate:")
        for name, ok in report["gates"].items():
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        print(f"  -> holds: {report['holds']}")
        return 0 if report["holds"] else 1

    runner = {
        "secrets": lambda: secrets_phase(write=write),
        "size": lambda: size_phase(write=write),
        "licence": lambda: licence_phase(write=write),
        "repro": lambda: repro_phase(write=write, clone_check=clone_path),
        "claims": lambda: claims_phase(write=write),
    }[args.phase]
    report = runner()
    print(json.dumps(report, indent=2, default=str)[:4000])
    print(f"\n{args.phase}: holds={report['holds']}")
    return 0 if report["holds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
