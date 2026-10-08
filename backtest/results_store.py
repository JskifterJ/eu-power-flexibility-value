"""The append-only results store (PLAN.md C10).

From C10 the project stops reading its numbers out of per-cycle JSON summaries
and starts accumulating them in one table, **append-only**, with every row
carrying the provenance needed to reproduce it. PLAN.md C10 asks for "results
written append-only, each row tagged with git SHA + config hash"; this module
is that, plus the two things the C9 entry's closing suggestion asked for.

Four decisions here are load-bearing.

**Long format, one row per metric.** A row is
``(run, zone, model, arm, scope, metric) -> value``, not a wide row of metric
columns. The alternative looks friendlier and breaks on the first cycle that
adds a metric: C11 adds capture ratios, C12 adds daily-spread error, the
within-day Spearman and bootstrap CIs, and every one of those would be a new
column that every previously-appended row lacks. In long format a new metric is
a new *value* in an existing column, so the schema that C10 freezes is the
schema C12 still writes into. **The extension point is the metric name, never
the column list.**

**Append-only is verified, not promised.** :func:`append_rows` reads the file's
existing bytes, appends, and then asserts the new file still *starts with* those
exact bytes — so a rewrite that happens to produce a plausible table fails
loudly rather than passing review. Each run also records, in
``results_runs.json``, the SHA-256 of the whole file as it stood after that run
appended; :func:`verify_append_only` replays those hashes against the file's own
prefixes, which catches a retroactive edit of any earlier row even if the run
that made it is long gone. This is the one guarantee the store exists to give:
an earlier cycle's number may be *superseded* by a later row, never silently
changed.

**Provenance is mandatory, including the libraries.** Every row carries the
``git_sha`` and ``config_hash`` PLAN.md asks for, the model's own config
fingerprint where it has one (``GbmSpec.fingerprint()``), and a
``library_fingerprint`` — because, as the C9 entry notes, everything
``GbmSpec.booster_params()`` does *not* name (``max_depth``,
``max_cat_threshold``, ``min_data_per_group``) comes from the installed
LightGBM, so a major-version bump could move a result without moving the
fingerprint. The full version dict goes in the run manifest; the row carries the
hash of it.

**The vintage label travels with the number.** FINDING C9-C is that the Art. 14
``res_as_published`` arm buys 18-24% of MAE that a bidder could not have had.
Any store that lets that number be read without its label is a trap, so
``vintage`` is a required key column taking ``honest`` or
``after_gate_closure``, and :func:`honest_rows` is the filter a reporting cycle
should reach for by default.

Sealed years are refused here too (:mod:`data.holdout`). A metric computed
against 2025 cannot be written into the store before Checkpoint C, even if some
future caller computes one by mistake.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from data.config import REPO_ROOT
from data.holdout import assert_not_sealed

#: Bumped only by a deliberate migration (see ``_assert_header``). The store's
#: filename carries no version: a migration writes a new file and says so.
SCHEMA_VERSION = 1

RESULTS_DIR = REPO_ROOT / "backtest" / "results"
RESULTS_PATH = RESULTS_DIR / "results.csv"
RUNS_PATH = RESULTS_DIR / "results_runs.json"

#: The frozen column order. Adding a column is a migration, not an append —
#: :func:`append_rows` refuses a file whose header is not exactly this.
SCHEMA: tuple[str, ...] = (
    # --- provenance (PLAN.md C10: "tagged with git SHA + config hash") -------
    "run_id",
    "appended_at_utc",
    "cycle",
    "git_sha",
    "config_hash",
    "library_fingerprint",
    # --- what was measured --------------------------------------------------
    "zone",
    "tier",
    "regime",
    "model",
    "model_fingerprint",
    "exog_variant",
    "vintage",
    # --- how it was measured ------------------------------------------------
    "train_from",
    "evaluation_years",
    "refit_every_days",
    "min_train_days",
    "train_window_days",
    "n_folds",
    "scope",
    # --- the number ---------------------------------------------------------
    "metric",
    "value",
    "n",
    "n_scored",
    # --- where it came from, if it was not computed here --------------------
    "source_artefact",
    "source_cycle",
    "source_git_sha",
)

#: Required, non-empty on every row. The rest may be blank where they do not
#: apply (a naive forecast has no ``model_fingerprint``; a rolling window is
#: absent on an expanding one).
REQUIRED: tuple[str, ...] = (
    "run_id",
    "appended_at_utc",
    "cycle",
    "git_sha",
    "config_hash",
    "library_fingerprint",
    "zone",
    "tier",
    "model",
    "vintage",
    "evaluation_years",
    "scope",
    "metric",
    "value",
)

#: The leakage label. ``after_gate_closure`` marks a number produced with
#: information published after the gate the model is predicting — reportable
#: only as the measurement of that leak (FINDING C8-A, FINDING C9-C).
VINTAGES = ("honest", "after_gate_closure")

#: ``own_coverage`` scores each series on the hours it chose to answer;
#: ``common_hours`` re-scores every series of that zone on the intersection, so
#: a cross-model comparison is not partly a comparison of coverage.
SCOPES = ("own_coverage", "common_hours")

#: Metric names are snake_case and the extension point of this schema. They are
#: deliberately *not* pinned to a closed list: C11 and C12 add capture ratios,
#: spread error, Spearman and bootstrap bounds, and should not have to edit a
#: test (CLAUDE.md makes that a flag-and-stop event) in order to record one.
METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

#: Libraries whose version can move a number. ``lightgbm`` is here because of
#: the C9 entry's closing note; the rest because an estimator or a solver
#: default moving would do the same.
TRACKED_LIBRARIES = ("numpy", "pandas", "scikit-learn", "scipy", "lightgbm")


class ResultsStoreError(RuntimeError):
    """The store cannot accept this write, or its history does not verify."""


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def library_versions() -> dict[str, str]:
    """Installed versions of the libraries that can move a number, plus Python.

    A library that is not installed is recorded as ``"absent"`` rather than
    omitted: "scipy was not installed" is itself provenance, and a missing key
    would quietly change the fingerprint's meaning.
    """
    from importlib.metadata import PackageNotFoundError, version

    out = {"python": ".".join(str(p) for p in sys.version_info[:3])}
    for name in TRACKED_LIBRARIES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "absent"
    return out


def library_fingerprint(versions: dict[str, str] | None = None) -> str:
    """16 hex chars over the sorted version dict. Written into every row."""
    payload = json.dumps(versions or library_versions(), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_run_id(cycle: str, now: dt.datetime | None = None) -> str:
    """``C10-20261008T174500Z-<8 hex>``: sortable, unique, and says which cycle.

    The hex suffix is over the instant *and* the provenance, so two appends made
    in the same second from different code cannot collide.
    """
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    seed = f"{cycle}|{stamp}|{library_fingerprint()}"
    return f"{cycle}-{stamp}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:8]}"


# ---------------------------------------------------------------------------
# A row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultRow:
    """One ``(zone, model, arm, scope, metric) -> value``, with its provenance.

    The provenance fields are filled by :func:`append_rows` if left blank, so a
    caller builds rows about *measurements* and the store stamps the run.
    """

    zone: str
    tier: str
    model: str
    metric: str
    value: float
    scope: str = "own_coverage"
    vintage: str = "honest"
    evaluation_years: str = ""
    regime: str = ""
    model_fingerprint: str = ""
    exog_variant: str = ""
    train_from: str = ""
    refit_every_days: str = ""
    min_train_days: str = ""
    train_window_days: str = ""
    n_folds: str = ""
    n: str = ""
    n_scored: str = ""
    source_artefact: str = ""
    source_cycle: str = ""
    source_git_sha: str = ""
    # Stamped by append_rows.
    run_id: str = ""
    appended_at_utc: str = ""
    cycle: str = ""
    git_sha: str = ""
    config_hash: str = ""
    library_fingerprint: str = ""

    def key(self) -> tuple[str, ...]:
        """What makes two rows the same measurement inside one run."""
        return (
            self.zone,
            self.model,
            self.exog_variant,
            self.vintage,
            self.train_from,
            self.evaluation_years,
            self.scope,
            self.metric,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AppendReport:
    """What one append did. Returned so a cycle can log it instead of asserting it."""

    run_id: str
    cycle: str
    n_rows_appended: int
    n_rows_before: int
    n_rows_after: int
    file_sha256: str
    path: str
    libraries: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _years_of(spelling: str) -> set[int]:
    """``"2024"`` / ``"2023-2024"`` / ``"2023,2024"`` -> ``{...}``. Strict."""
    found = {int(m) for m in re.findall(r"\b(\d{4})\b", spelling)}
    if not found:
        raise ResultsStoreError(
            f"evaluation_years {spelling!r} names no four-digit year — the sealed "
            f"holdout guard cannot check a row it cannot read"
        )
    return found


def _validate(rows: Sequence[ResultRow]) -> None:
    """Every refusal here is a refusal to write something unreadable later."""
    if not rows:
        raise ResultsStoreError("nothing to append")
    seen: dict[tuple[str, ...], int] = {}
    for i, row in enumerate(rows):
        data = row.as_dict()
        missing = [k for k in REQUIRED if str(data.get(k, "")).strip() == ""]
        if missing:
            raise ResultsStoreError(f"row {i} ({row.key()}) is missing {missing}")
        if row.vintage not in VINTAGES:
            raise ResultsStoreError(
                f"row {i}: vintage {row.vintage!r} is not one of {VINTAGES}. The "
                f"label is required because FINDING C9-C makes an unlabelled "
                f"late-vintage number actively misleading."
            )
        if row.scope not in SCOPES:
            raise ResultsStoreError(f"row {i}: scope {row.scope!r} not in {SCOPES}")
        if not METRIC_NAME.match(row.metric):
            raise ResultsStoreError(
                f"row {i}: metric {row.metric!r} is not snake_case/3-64 chars"
            )
        try:
            value = float(row.value)
        except (TypeError, ValueError) as exc:
            raise ResultsStoreError(f"row {i}: value {row.value!r} is not a number") from exc
        if value != value:  # NaN
            raise ResultsStoreError(
                f"row {i} ({row.key()}): value is NaN. A metric that could not be "
                f"computed is an absent row, not a NaN one."
            )
        assert_not_sealed(
            _years_of(row.evaluation_years),
            f"write a {row.metric} for {row.zone}/{row.model} into the results store",
        )
        if row.key() in seen:
            raise ResultsStoreError(
                f"row {i} repeats row {seen[row.key()]} within this run: {row.key()}. "
                f"Two values for one measurement in one run is a bug; superseding an "
                f"earlier *run*'s value is what the store is for."
            )
        seen[row.key()] = i


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def _assert_header(path: Path) -> None:
    with path.open("r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh), [])
    if tuple(header) != SCHEMA:
        raise ResultsStoreError(
            f"{path} has a different column list than this code's SCHEMA "
            f"(schema_version {SCHEMA_VERSION}).\n"
            f"  on disk: {header}\n"
            f"  in code: {list(SCHEMA)}\n"
            f"This store is append-only, so a column change is a *migration*: "
            f"write a new file, record the migration in PROGRESS.md, and leave "
            f"this one intact. Note that adding a metric needs no migration — "
            f"long format makes the metric name the extension point."
        )


def _render(rows: Sequence[ResultRow]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(SCHEMA), lineterminator="\n")
    for row in rows:
        data = row.as_dict()
        writer.writerow({k: data[k] for k in SCHEMA})
    return buffer.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def append_rows(
    rows: Sequence[ResultRow],
    cycle: str,
    git_sha: str,
    config_hash: str,
    path: Path | None = None,
    runs_path: Path | None = None,
    argv: Sequence[str] | None = None,
    note: str = "",
    now: dt.datetime | None = None,
) -> AppendReport:
    """Stamp ``rows`` with this run's provenance and append them. Never rewrites.

    The append-only guarantee is checked twice: the pre-existing bytes must
    still be a prefix of the file afterwards, and the file's SHA-256 is recorded
    in the run manifest so :func:`verify_append_only` can detect a later edit of
    any row written here.
    """
    results_path = path or RESULTS_PATH
    manifest_path = runs_path or RUNS_PATH
    stamped_at = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    run_id = make_run_id(cycle, now)
    versions = library_versions()
    fingerprint = library_fingerprint(versions)

    stamped = [
        ResultRow(
            **{
                **row.as_dict(),
                "run_id": run_id,
                "appended_at_utc": stamped_at,
                "cycle": cycle,
                "git_sha": git_sha,
                "config_hash": config_hash,
                "library_fingerprint": fingerprint,
            }
        )
        for row in rows
    ]
    _validate(stamped)

    results_path.parent.mkdir(parents=True, exist_ok=True)
    if results_path.exists():
        _assert_header(results_path)
        existing = results_path.read_bytes()
        n_before = max(0, existing.decode("utf-8").count("\n") - 1)
    else:
        existing = (",".join(SCHEMA) + "\n").encode("utf-8")
        results_path.write_bytes(existing)
        n_before = 0

    with results_path.open("ab") as fh:
        fh.write(_render(stamped).encode("utf-8"))

    after = results_path.read_bytes()
    if not after.startswith(existing):
        raise ResultsStoreError(
            f"{results_path} no longer starts with the {len(existing)} bytes it held "
            f"before this append — the store is append-only and something rewrote it"
        )
    n_after = max(0, after.decode("utf-8").count("\n") - 1)
    if n_after != n_before + len(stamped):
        raise ResultsStoreError(
            f"expected {n_before + len(stamped)} data rows after appending "
            f"{len(stamped)}, found {n_after}"
        )

    report = AppendReport(
        run_id=run_id,
        cycle=cycle,
        n_rows_appended=len(stamped),
        n_rows_before=n_before,
        n_rows_after=n_after,
        file_sha256=_sha256(after),
        path=str(results_path.relative_to(REPO_ROOT)) if results_path.is_relative_to(REPO_ROOT) else str(results_path),
        libraries=versions,
    )
    _record_run(manifest_path, report, git_sha, config_hash, fingerprint, argv, note, stamped_at)
    return report


def _record_run(
    manifest_path: Path,
    report: AppendReport,
    git_sha: str,
    config_hash: str,
    fingerprint: str,
    argv: Sequence[str] | None,
    note: str,
    stamped_at: str,
) -> None:
    """Append this run to ``results_runs.json``: provenance plus the prefix hash.

    ``file_sha256`` is the hash of the *whole file as it stood after this run*,
    which is exactly the hash of its first ``n_rows_after`` data rows. That is
    what makes a later edit of an earlier row detectable.
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    else:
        manifest = {"schema_version": SCHEMA_VERSION, "columns": list(SCHEMA), "runs": []}
    if manifest.get("columns") != list(SCHEMA):
        raise ResultsStoreError(
            f"{manifest_path} records a different column list than this code's "
            f"SCHEMA — see the migration note in append_rows"
        )
    manifest["runs"].append(
        {
            "run_id": report.run_id,
            "cycle": report.cycle,
            "appended_at_utc": stamped_at,
            "git_sha": git_sha,
            "config_hash": config_hash,
            "library_fingerprint": fingerprint,
            "libraries": report.libraries,
            "argv": list(argv) if argv is not None else [],
            "note": note,
            "n_rows_appended": report.n_rows_appended,
            "n_rows_before": report.n_rows_before,
            "n_rows_after": report.n_rows_after,
            "file_sha256": report.file_sha256,
        }
    )
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")


def verify_append_only(
    path: Path | None = None, runs_path: Path | None = None
) -> dict[str, Any]:
    """Replay the run manifest's hashes against the store's own prefixes.

    For each recorded run, hashes the header plus that run's ``n_rows_after``
    data rows and compares with the ``file_sha256`` the run recorded. A
    mismatch means some row written at or before that run has since changed,
    which is the one thing this store promises cannot happen quietly.

    Returns a report; raises :class:`ResultsStoreError` on the first mismatch.
    """
    results_path = path or RESULTS_PATH
    manifest_path = runs_path or RUNS_PATH
    if not results_path.exists() and not manifest_path.exists():
        return {"verified": True, "n_runs": 0, "n_rows": 0, "note": "store is empty"}
    if not manifest_path.exists():
        raise ResultsStoreError(f"{results_path} exists but {manifest_path} does not")
    if not results_path.exists():
        raise ResultsStoreError(f"{manifest_path} exists but {results_path} does not")
    _assert_header(results_path)

    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    runs = manifest.get("runs", [])

    raw = results_path.read_bytes().decode("utf-8")
    lines = raw.splitlines(keepends=True)
    header, data = lines[0], lines[1:]

    last = 0
    for run in runs:
        n = int(run["n_rows_after"])
        if n > len(data):
            raise ResultsStoreError(
                f"run {run['run_id']} recorded {n} data rows but the store has "
                f"{len(data)} — rows written at that run have been removed"
            )
        prefix = (header + "".join(data[:n])).encode("utf-8")
        got = _sha256(prefix)
        if got != run["file_sha256"]:
            raise ResultsStoreError(
                f"run {run['run_id']} ({run['cycle']}) recorded file_sha256 "
                f"{run['file_sha256']} over its first {n} data rows; the store now "
                f"hashes to {got} there. A row written at or before that run has "
                f"been edited. The store is append-only: an earlier number may be "
                f"superseded by a later row, never changed in place."
            )
        if n < last:
            raise ResultsStoreError(
                f"run {run['run_id']} records n_rows_after {n} below the previous "
                f"run's {last} — the manifest is not in append order"
            )
        last = n
    if runs and last != len(data):
        raise ResultsStoreError(
            f"the store has {len(data)} data rows but the last recorded run ends at "
            f"{last} — {len(data) - last} row(s) were appended without a manifest "
            f"entry, so their provenance is unverifiable"
        )
    return {
        "verified": True,
        "n_runs": len(runs),
        "n_rows": len(data),
        "runs": [
            {"run_id": r["run_id"], "cycle": r["cycle"], "n_rows_appended": r["n_rows_appended"]}
            for r in runs
        ],
    }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_results(path: Path | None = None) -> pd.DataFrame:
    """The whole store, every run, oldest first. Strings stay strings."""
    results_path = path or RESULTS_PATH
    if not results_path.exists():
        return pd.DataFrame(columns=list(SCHEMA))
    _assert_header(results_path)
    frame = pd.read_csv(results_path, dtype=str, keep_default_na=False)
    frame["value"] = frame["value"].astype("float64")
    return frame


def latest_results(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per measurement: the most recently appended value for each key.

    History is never deleted, so a reporting cycle needs a "current view". Rows
    are ordered by append time, then by run id, so a run that supersedes an
    earlier value wins deterministically.
    """
    data = read_results() if frame is None else frame
    if data.empty:
        return data
    keys = [
        "zone", "model", "exog_variant", "vintage", "train_from",
        "evaluation_years", "scope", "metric",
    ]
    ordered = data.sort_values(["appended_at_utc", "run_id"], kind="stable")
    return ordered.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)


def honest_rows(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Only ``vintage == "honest"``. The default filter for any reported table.

    The ``after_gate_closure`` rows exist to *measure* the Art. 14 vintage
    premium (FINDINGs C8-A and C9-C) and are never an achievable result, so a
    cycle that wants them has to ask for them by name.
    """
    data = latest_results() if frame is None else frame
    if data.empty:
        return data
    return data[data["vintage"] == "honest"].reset_index(drop=True)


def pivot_metric(
    metric: str, frame: pd.DataFrame | None = None, scope: str = "common_hours"
) -> pd.DataFrame:
    """``zone`` x ``series`` table of one metric, for printing and for the write-up."""
    data = latest_results() if frame is None else frame
    if data.empty:
        return pd.DataFrame()
    sub = data[(data["metric"] == metric) & (data["scope"] == scope)].copy()
    if sub.empty:
        return pd.DataFrame()
    sub["series"] = [
        f"{m}_{v}" if v else m for m, v in zip(sub["model"], sub["exog_variant"])
    ]
    return sub.pivot_table(
        index="zone", columns="series", values="value", aggfunc="last"
    )


def rows_from_scores(
    scores: dict[str, Any],
    *,
    zone: str,
    tier: str,
    model: str,
    metrics: Iterable[str] = ("mae", "rmse", "bias", "coverage"),
    **common: Any,
) -> list[ResultRow]:
    """Turn a :meth:`backtest.metrics.Scores.as_dict` into one row per metric.

    ``n`` and ``n_scored`` ride along on every row rather than being metrics of
    their own: they are how many hours the number was computed over, which is
    part of reading it, not a separate measurement.
    """
    out: list[ResultRow] = []
    for metric in metrics:
        if metric not in scores:
            continue
        out.append(
            ResultRow(
                zone=zone,
                tier=tier,
                model=model,
                metric=metric,
                value=float(scores[metric]),
                n=str(scores.get("n", "")),
                n_scored=str(scores.get("n_scored", "")),
                **common,
            )
        )
    return out
