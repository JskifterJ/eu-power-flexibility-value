"""CLI: C16 — Checkpoint C's pre-unseal readiness report.

    python -m backtest.run_c16_checkpoint --phase verify
    python -m backtest.run_c16_checkpoint --phase prereg
    python -m backtest.run_c16_checkpoint --phase all

PLAN.md C16: *"CHECKPOINT C: stop, push-notify, wait for explicit human approval
to unseal the 2025 holdout. Only after approval: run a single evaluation of the
2025 holdout; record in PROGRESS.md that it ran exactly once, with the
timestamp."*

**This module never touches 2025 data, and is the thing that proves nothing else
did either.** It has two jobs, and both of them exist because the sentence above
contains the word *single*:

``verify``
    Establish, mechanically rather than in prose, that the seal is still intact
    and that the guard which keeps it intact is armed: the unseal marker is
    absent from ``PROGRESS.md``, the config still declares 2025 sealed, every
    module that can reach a price or a metric calls the guard, every public
    entry point *actually refuses* a 2025 request when called, and no committed
    artefact carries a 2025 evaluation row.

``prereg``
    Write down, **before** the holdout is visible, exactly what the one
    evaluation will compute: the window, the zones, the arms, the curves, the
    metrics, the dispatch configuration, the intervals, the output files, the
    assertions that must hold, and the rules for what happens if one of them
    does not. A holdout evaluated once is only worth something if the choices
    were fixed beforehand; a pre-registration that lives in a committed JSON
    file with a git SHA and a config hash on it is a choice that can be checked
    after the fact, and prose in a log entry is not.

The network-touching probes are handed a session object that raises on use, so a
probe can never reach the Energy-Charts or ENTSO-E API even in the world where
the guard it is testing has been removed. That is the whole point of a probe
that asserts a refusal: it must be safe when it fails.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.bootstrap import (  # noqa: E402
    BLOCK_LADDER,
    DEFAULT_REPLICATES,
    DEFAULT_SEED,
)
from backtest.results_store import (  # noqa: E402
    RESULTS_DIR as STORE_DIR,
    RESULTS_PATH,
    ResultRow,
    append_rows,
    library_fingerprint,
    library_versions,
    read_results,
)
from backtest.run_c3_naive import RESULTS_DIR, git_sha  # noqa: E402
from data.config import (  # noqa: E402
    REPO_ROOT,
    config_hash,
    load_battery_config,
    load_data_config,
    load_zones,
    sealed_years,
)
from data.holdout import (  # noqa: E402
    SealedHoldoutError,
    holdout_is_unsealed,
    unseal_marker,
)

#: The guard functions a static scan looks for.
GUARD_NAMES: frozenset[str] = frozenset(
    {"assert_not_sealed", "assert_range_not_sealed"}
)

#: Modules that can reach a sealed price, a sealed exogenous series, a sealed
#: fold or a sealed number. Each one **must** call a guard; a zero here is the
#: verification failing, not a note. Kept as an explicit list rather than
#: inferred, so deleting a guard call cannot also delete the expectation of it.
REQUIRED_GUARD_MODULES: tuple[str, ...] = (
    "data/energy_charts.py",     # the price fetch and the cached-price read
    "data/prices.py",            # the stitching loader every model sits on
    "data/entsoe.py",            # the exogenous fetch and cached read
    "data/exogenous.py",         # the exogenous stitching loader
    "backtest/walk_forward.py",  # the harness: refuses a sealed evaluation year
    "backtest/results_store.py", # the store: refuses to *write* a sealed number
)

#: Directories the static census walks.
CENSUS_DIRS: tuple[str, ...] = ("data", "backtest", "forecast", "dispatch")

#: Columns in a committed artefact that carry a calendar year.
YEAR_COLUMNS: frozenset[str] = frozenset({"year", "evaluation_years"})

#: Columns in a committed artefact that carry a date or timestamp.
DATE_COLUMNS: frozenset[str] = frozenset(
    {
        "day",
        "date",
        "market_day",
        "first_day",
        "last_day",
        "timestamp_utc",
        "utc_timestamp",
        "train_start_day",
        "train_end_day",
        "target_day",
        "first_target_day",
        "last_target_day",
    }
)

#: JSON keys whose value is *allowed* to name 2025, because the structural dates
#: of the study are themselves 2025 dates (the SDAC 15-minute go-live, the end of
#: the main hourly backtest) and the sealed-year declaration names the year it
#: seals. Everything else naming 2025 in a committed artefact is a leak.
STRUCTURAL_2025_KEYS: frozenset[str] = frozenset(
    {
        "sdac_15min_golive",
        "main_backtest_end",
        "sealed_years",
        "holdout",
        "holdout_years",
        "cutover",
        "why_no_comparison",
        "note",
        "notes",
    }
)

#: C16's own artefacts. The pre-registration necessarily names the year it
#: pre-registers and the window it will evaluate, and the verification report
#: necessarily names the sealed year it verified. Neither carries a *measured*
#: 2025 value — that is what the rest of the scan is for — so both are exempt
#: by name rather than by a loosened rule that would also exempt a result file.
EXEMPT_ARTEFACTS: frozenset[str] = frozenset(
    {"c16_preregistration.json", "c16_seal_verification.json"}
)

#: What the single post-approval evaluation covers. The window stops at
#: ``main_backtest_end`` because the SDAC 15-minute go-live is the next day and
#: PLAN.md keeps native 15-minute analysis a labelled stretch goal.
HOLDOUT_YEAR = 2025
HOLDOUT_FIRST_DAY = "2025-01-01"
HOLDOUT_LAST_DAY = "2025-09-30"

#: The curves the single evaluation dispatches, in the order the invariants
#: relate them: oracle >= model, every day (same-start); model >= naive, on
#: average (CLAUDE.md).
PREREG_CURVES: tuple[str, ...] = ("oracle", "lear_full_history", "naive")


class CheckpointError(RuntimeError):
    """The checkpoint's own verification failed. Never caught — this must stop."""


def _rel(path: Path) -> str:
    """Repo-relative where possible, absolute otherwise (tests use tmp dirs)."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# 1. The marker
# ---------------------------------------------------------------------------


def marker_audit(progress_path: Path | None = None) -> dict[str, Any]:
    """Is the holdout sealed, and does ``PROGRESS.md`` mention the marker safely?

    ``data.holdout`` unseals only on a line that, stripped, *equals* the marker.
    Every cycle that writes about Checkpoint C quotes the marker in prose, so the
    interesting number is not "is the string present" but "is it present on a
    line of its own". Both are reported, and the second one is the seal.
    """
    path = progress_path or (REPO_ROOT / "PROGRESS.md")
    marker = unseal_marker()
    mentions: list[int] = []
    bare: list[int] = []
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for i, line in enumerate(text.splitlines(), start=1):
        if marker in line:
            mentions.append(i)
            if line.strip() == marker:
                bare.append(i)
    unsealed = holdout_is_unsealed(path)
    if unsealed or bare:
        raise CheckpointError(
            f"{path} contains the unseal marker on a line of its own "
            f"(line(s) {bare}). Only a human writes that line, and C16's job is "
            f"to *request* the unseal, never to perform it."
        )
    return {
        "progress_path": _rel(path),
        "marker": marker,
        "holdout_is_unsealed": bool(unsealed),
        "n_lines_mentioning_marker_in_prose": len(mentions),
        "lines_mentioning_marker_in_prose": mentions,
        "n_bare_marker_lines": len(bare),
        "seal_intact": True,
    }


# ---------------------------------------------------------------------------
# 2. The declared split
# ---------------------------------------------------------------------------


def split_audit() -> dict[str, Any]:
    """The config side of the seal: what is sealed, and what may be fetched."""
    cfg = load_data_config()
    sealed = sorted(sealed_years())
    fetch = [int(y) for y in cfg["fetch_years"]]
    overlap = sorted(set(fetch).intersection(sealed))
    if sealed != [HOLDOUT_YEAR]:
        raise CheckpointError(
            f"config declares sealed years {sealed}; this checkpoint is about "
            f"{[HOLDOUT_YEAR]} and will not speak for anything else"
        )
    if overlap:
        raise CheckpointError(
            f"fetch_years {fetch} includes sealed year(s) {overlap} — an "
            f"ordinary cycle could have pulled the holdout"
        )
    structural = cfg["structural_dates"]
    return {
        "sealed_years": sealed,
        "fetch_years": fetch,
        "fetch_years_intersect_sealed": overlap,
        "splits": {k: list(v.get("years") or []) for k, v in cfg["splits"].items()},
        "sdac_15min_golive": str(structural["sdac_15min_golive"]),
        "main_backtest_end": str(structural["main_backtest_end"]),
        "exogenous_available_from_year": int(
            cfg["sources"]["entsoe"]["exogenous_available_from_year"]
        ),
    }


# ---------------------------------------------------------------------------
# 3. The static guard census
# ---------------------------------------------------------------------------


def _guard_calls(path: Path) -> list[int]:
    """Line numbers of every guard *call* in one file (calls, not imports)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute) else ""
        )
        if name in GUARD_NAMES:
            lines.append(node.lineno)
    return sorted(lines)


def guard_census(root: Path | None = None) -> dict[str, Any]:
    """Every guard call in the source tree, and the modules that must have one."""
    base = root or REPO_ROOT
    per_module: dict[str, list[int]] = {}
    for directory in CENSUS_DIRS:
        for path in sorted((base / directory).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            calls = _guard_calls(path)
            if calls:
                # .as_posix(), not str(): str(WindowsPath) is backslash-separated
                # on Windows, which silently fails every lookup against
                # REQUIRED_GUARD_MODULES's forward-slash literals below — found
                # 2026-10-12, this repo's first run outside a Linux container,
                # when all six required modules reported "missing" despite every
                # one of them genuinely containing a guard call.
                per_module[path.relative_to(base).as_posix()] = calls
    missing = [m for m in REQUIRED_GUARD_MODULES if not per_module.get(m)]
    if missing:
        raise CheckpointError(
            f"module(s) {missing} can reach sealed data and call no holdout "
            f"guard. The seal is not armed; nothing else in this report counts."
        )
    return {
        "n_guard_calls": sum(len(v) for v in per_module.values()),
        "n_modules_with_a_guard": len(per_module),
        "required_modules": list(REQUIRED_GUARD_MODULES),
        "required_modules_missing_a_guard": missing,
        "guard_calls_by_module": per_module,
    }


# ---------------------------------------------------------------------------
# 4. Live refusal probes
# ---------------------------------------------------------------------------


class _RefusingSession:
    """A ``requests.Session`` stand-in that raises on any use.

    Handed to every probe of a network path, so that a probe which *fails* —
    i.e. finds the guard missing — still cannot download a byte of the holdout.
    A probe asserting a refusal has to be safe in the world where the refusal is
    gone, or it is an experiment nobody should run.
    """

    def get(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - guard
        raise CheckpointError(
            "a sealed-holdout probe reached the network: the guard it was "
            "testing did not fire"
        )

    request = get


@dataclass(frozen=True)
class Probe:
    """One public entry point, called for 2025, that must refuse."""

    name: str
    what: str
    call: Callable[[], Any]


@contextmanager
def synthetic_sealed_cache() -> Any:
    """A throwaway cache holding *placeholder* 2024 and 2025 files.

    The stitching loaders (:func:`data.prices.load_zone_series`,
    :func:`data.exogenous.load_zone_document`) discover which years are cached
    *before* they reach their guard, so in a fresh container — where nothing is
    cached at all — they fail with "no cached files" and the guard is never
    exercised. That is an accident of the container, not evidence, and a
    checkpoint may not certify a seal it did not see refuse.

    So the probe builds the situation the guard exists for: a cache in which a
    sealed year **is** present. The files are empty placeholders, named
    ``2024`` and ``2025`` the way each loader's ``cached_years`` reads a name,
    which is enough for year discovery and contains nothing to leak — if the
    guard were missing, the loader would reach an empty file and raise a parse
    error, never a 2025 price. ``sealed_years()`` still reads the committed
    ``config/data.yaml``, so what counts as sealed is not synthetic.
    """
    cfg = deepcopy(load_data_config())
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        price_dir = root / "price" / "DE-LU"
        price_dir.mkdir(parents=True)
        for year in (2024, HOLDOUT_YEAR):
            (price_dir / f"{year}.json").write_text("{}", encoding="utf-8")
        cfg["sources"]["energy_charts"]["cache_dir"] = str(root / "price")
        exog_dir = root / "entsoe" / "load_forecast_da" / "DE-LU"
        exog_dir.mkdir(parents=True)
        for year in (2024, HOLDOUT_YEAR):
            (exog_dir / f"{year}.xml.gz").write_bytes(b"")
        cfg["sources"]["entsoe"]["cache_dir"] = str(root / "entsoe")
        yield cfg


def _store_probe() -> None:
    """Try to *write* a 2025 metric into a throwaway results store."""
    row = ResultRow(
        zone="DE-LU",
        tier="A",
        model="lear",
        metric="mae_eur_per_mwh",
        value=1.0,
        evaluation_years=str(HOLDOUT_YEAR),
    )
    with tempfile.TemporaryDirectory() as tmp:
        append_rows(
            [row],
            cycle="C16probe",
            git_sha="probe",
            config_hash="probe",
            path=Path(tmp) / "results.csv",
            runs_path=Path(tmp) / "results_runs.json",
        )


def build_probes(cache_config: dict[str, Any] | None = None) -> tuple[Probe, ...]:
    """The in-process probes, one per public way into sealed data.

    ``cache_config`` is the config the cache-discovering loaders are pointed at
    — :func:`synthetic_sealed_cache`'s, in the ``verify`` phase. The fetch and
    single-file read paths guard before they look at anything, so they take the
    committed config.
    """
    from data import energy_charts, entsoe, exogenous, prices

    session = _RefusingSession()
    year = HOLDOUT_YEAR
    cache_cfg = cache_config
    return (
        Probe(
            "energy_charts.fetch_year",
            "fetch 2025 day-ahead prices from Energy-Charts",
            lambda: energy_charts.fetch_year("DE-LU", year, session=session),
        ),
        Probe(
            "energy_charts.read_cached_year",
            "read a cached 2025 price file",
            lambda: energy_charts.read_cached_year("DE-LU", year),
        ),
        Probe(
            "prices.read_cached_file",
            "read a cached 2025 price file untruncated",
            lambda: prices.read_cached_file("DE-LU", year),
        ),
        Probe(
            "prices.load_zone_series",
            "stitch a price series that includes 2025",
            lambda: prices.load_zone_series(
                "DE-LU", years=[2024, year], config=cache_cfg
            ),
        ),
        Probe(
            "entsoe.fetch_year",
            "fetch the 2025 D-1 load forecast from ENTSO-E",
            lambda: entsoe.fetch_year(
                "DE-LU", "load_forecast_da", year, session=session
            ),
        ),
        Probe(
            "entsoe.read_cached_year",
            "read a cached 2025 ENTSO-E document",
            lambda: entsoe.read_cached_year("DE-LU", "load_forecast_da", year),
        ),
        Probe(
            "exogenous.load_zone_document",
            "stitch an exogenous document series that includes 2025",
            lambda: exogenous.load_zone_document(
                "DE-LU", "load_forecast_da", years=[2024, year], config=cache_cfg
            ),
        ),
        Probe(
            "results_store.append_rows",
            "write a 2025 metric into the results store",
            _store_probe,
        ),
    )


def run_probes(probes: Iterable[Probe] | None = None) -> dict[str, Any]:
    """Call every probe; each must raise :class:`SealedHoldoutError`."""
    results: list[dict[str, Any]] = []
    for probe in probes if probes is not None else build_probes():
        try:
            probe.call()
        except SealedHoldoutError as exc:
            results.append(
                {
                    "entry_point": probe.name,
                    "attempted": probe.what,
                    "refused": True,
                    "raised": "SealedHoldoutError",
                    "message": str(exc)[:300],
                }
            )
            continue
        except CheckpointError:
            raise
        except BaseException as exc:  # noqa: BLE001 - reported, then raised
            results.append(
                {
                    "entry_point": probe.name,
                    "attempted": probe.what,
                    "refused": False,
                    "raised": type(exc).__name__,
                    "message": str(exc)[:300],
                }
            )
            raise CheckpointError(
                f"{probe.name} raised {type(exc).__name__} instead of "
                f"SealedHoldoutError when asked to {probe.what}. A different "
                f"error means the guard is not what stopped it, and the next "
                f"change to that path could let it through: {exc}"
            ) from exc
        results.append(
            {
                "entry_point": probe.name,
                "attempted": probe.what,
                "refused": False,
                "raised": "",
                "message": "returned normally",
            }
        )
        raise CheckpointError(
            f"{probe.name} did NOT refuse to {probe.what}. The 2025 holdout is "
            f"reachable. Stop: this is the one failure this checkpoint exists "
            f"to catch."
        )
    return {
        "n_probes": len(results),
        "n_refused": sum(1 for r in results if r["refused"]),
        "probes": results,
    }


CLI_PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "backtest.run_c11_dispatch",
        ("--years", "2025", "--zones", "DE-LU", "--no-append"),
    ),
    (
        "backtest.run_c13_regime",
        ("--phase", "compute", "--years", "2025", "--zones", "DE-LU", "--no-append"),
    ),
)


def run_cli_probes() -> dict[str, Any]:
    """The same refusal, end to end through the runners a cycle actually types.

    A subprocess rather than an import, because what is being checked is that
    the *command* refuses — including its argument parsing, which is where a
    year gets in.
    """
    out: list[dict[str, Any]] = []
    for module, args in CLI_PROBES:
        proc = subprocess.run(
            [sys.executable, "-m", module, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        blob = f"{proc.stdout}\n{proc.stderr}"
        refused = proc.returncode != 0 and "SEALED HOLDOUT" in blob
        out.append(
            {
                "command": f"python -m {module} {' '.join(args)}",
                "returncode": proc.returncode,
                "refused": refused,
                "mentions_sealed_holdout": "SEALED HOLDOUT" in blob,
                "tail": blob.strip().splitlines()[-1][:300] if blob.strip() else "",
            }
        )
        if not refused:
            raise CheckpointError(
                f"`python -m {module} {' '.join(args)}` exited "
                f"{proc.returncode} without refusing the sealed year. Tail: "
                f"{blob.strip()[-500:]}"
            )
    return {"n_cli_probes": len(out), "cli_probes": out}


# ---------------------------------------------------------------------------
# 5. The artefact scan
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"\b(\d{4})\b")


def _years_in(value: Any) -> set[int]:
    return {int(m) for m in _YEAR_RE.findall(str(value))}


def _scan_table(path: Path) -> list[str]:
    """Hits of 2025 in the year/date columns of one committed table."""
    header = pd.read_csv(path, nrows=0)
    wanted = [c for c in header.columns if c in YEAR_COLUMNS | DATE_COLUMNS]
    if not wanted:
        return []
    frame = pd.read_csv(path, usecols=wanted, low_memory=False)
    hits: list[str] = []
    for column in wanted:
        series = frame[column].dropna().astype(str)
        if series.empty:
            continue
        if column in YEAR_COLUMNS:
            bad = series[series.map(lambda v: HOLDOUT_YEAR in _years_in(v))]
        else:
            bad = series[series.str.startswith(str(HOLDOUT_YEAR))]
        if not bad.empty:
            hits.append(f"{column}: {bad.iloc[0]!r} ({len(bad)} row(s))")
    return hits


def _scan_json(node: Any, key: str = "") -> list[str]:
    """Hits of 2025 under a year/date-ish key, outside the structural whitelist."""
    if key in STRUCTURAL_2025_KEYS:
        return []
    hits: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            hits.extend(_scan_json(v, str(k)))
        return hits
    if isinstance(node, (list, tuple)):
        for v in node:
            hits.extend(_scan_json(v, key))
        return hits
    if key in YEAR_COLUMNS and HOLDOUT_YEAR in _years_in(node):
        hits.append(f"{key} = {node!r}")
    if key in DATE_COLUMNS and str(node).startswith(str(HOLDOUT_YEAR)):
        hits.append(f"{key} = {node!r}")
    return hits


def artefact_scan(results_dir: Path | None = None) -> dict[str, Any]:
    """No committed artefact may carry a 2025 evaluation row.

    The store is checked on ``evaluation_years`` (the column the guard itself
    reads), every table on its year and date columns, and every summary JSON on
    the same key names — with the structural 2025 dates whitelisted, because
    ``main_backtest_end`` is *supposed* to say 2025-09-30.
    """
    directory = results_dir or STORE_DIR
    hits: dict[str, list[str]] = {}
    n_tables = n_jsons = 0
    for path in sorted(directory.glob("*.csv")) + sorted(directory.glob("*.csv.gz")):
        if path.name in EXEMPT_ARTEFACTS:
            continue
        n_tables += 1
        found = _scan_table(path)
        if found:
            hits[_rel(path)] = found
    for path in sorted(directory.glob("*.json")):
        if path.name in EXEMPT_ARTEFACTS:
            continue
        n_jsons += 1
        with path.open("r", encoding="utf-8") as fh:
            found = _scan_json(json.load(fh))
        if found:
            hits[_rel(path)] = found
    store_years: set[int] = set()
    if RESULTS_PATH.exists():
        frame = read_results()
        for spelling in frame["evaluation_years"].dropna().astype(str).unique():
            store_years |= _years_in(spelling)
    if hits or HOLDOUT_YEAR in store_years:
        raise CheckpointError(
            f"committed artefacts already carry {HOLDOUT_YEAR} data: "
            f"{hits or sorted(store_years)}. The holdout has been touched and "
            f"this checkpoint cannot certify otherwise."
        )
    return {
        "n_tables_scanned": n_tables,
        "n_summaries_scanned": n_jsons,
        "exempt_artefacts": sorted(EXEMPT_ARTEFACTS),
        "evaluation_years_in_store": sorted(store_years),
        "artefacts_naming_the_holdout": hits,
        "clean": True,
    }


# ---------------------------------------------------------------------------
# 6. The manifest and raw-cache scan
# ---------------------------------------------------------------------------

#: C1/C2/C7's committed record of what was actually downloaded.
MANIFEST_DIR = REPO_ROOT / "data" / "manifest"

#: Manifest tables with a ``year`` column: one row per (zone, year) fetched.
MANIFEST_YEAR_TABLES: tuple[str, ...] = (
    "prices_manifest.csv",
    "exogenous_manifest.csv",
)

#: Manifest tables carrying coverage timestamps.
MANIFEST_TS_TABLES: tuple[str, ...] = (
    "prices_manifest.csv",
    "exogenous_manifest.csv",
    "contract_report.csv",
    "exogenous_contract_report.csv",
)

MANIFEST_TS_COLUMNS: tuple[str, ...] = ("first_ts_utc", "last_ts_utc")


def manifest_scan(manifest_dir: Path | None = None) -> dict[str, Any]:
    """The download record itself: no sealed year was ever fetched.

    The artefact scan proves no 2025 *number* was published. This proves the
    stronger and simpler thing: no 2025 file was ever pulled. ``data/manifest/``
    is the committed record of every fetch, with one row per (zone, year) and
    the coverage timestamps of each, so a sealed year appearing in it would mean
    a download happened whatever was later computed from it.

    The timestamp check is a real constraint and not a tautology. Because the
    Energy-Charts request window is in local time, a *raw* 2024 file can legally
    contain the instant 2025-01-01T00:00Z — but the manifest trims to the UTC
    calendar year, and every committed ``last_ts_utc`` ends 2024-12-31T22:00Z.
    If a later regeneration ever carried a 2025 boundary hour into the manifest,
    this fires, and that is a conversation worth having rather than a false
    positive to suppress.

    ``data/raw/`` is gitignored and does not survive a container, so the raw-file
    check is cheap and usually vacuous — reported with ``raw_cache_present`` so a
    zero cannot be mistaken for a verified absence.
    """
    directory = manifest_dir or MANIFEST_DIR
    sealed = sealed_years()
    hits: dict[str, list[str]] = {}
    years_seen: dict[str, list[int]] = {}
    for name in MANIFEST_YEAR_TABLES:
        path = directory / name
        if not path.exists():
            continue
        column = pd.read_csv(path, usecols=["year"])["year"].dropna().astype(int)
        years_seen[name] = sorted(set(column.tolist()))
        bad = sorted(set(column.tolist()).intersection(sealed))
        if bad:
            hits.setdefault(name, []).append(f"year: {bad}")
    for name in MANIFEST_TS_TABLES:
        path = directory / name
        if not path.exists():
            continue
        header = pd.read_csv(path, nrows=0)
        wanted = [c for c in MANIFEST_TS_COLUMNS if c in header.columns]
        if not wanted:
            continue
        frame = pd.read_csv(path, usecols=wanted)
        for column in wanted:
            series = frame[column].dropna().astype(str)
            for year in sorted(sealed):
                bad = series[series.str.startswith(str(year))]
                if not bad.empty:
                    hits.setdefault(name, []).append(
                        f"{column}: {bad.iloc[0]!r} ({len(bad)} row(s))"
                    )
    raw_dir = REPO_ROOT / "data" / "raw"
    raw_hits = (
        [_rel(p) for p in raw_dir.rglob("*") if any(str(y) in p.name for y in sealed)]
        if raw_dir.exists()
        else []
    )
    if hits or raw_hits:
        raise CheckpointError(
            f"the download record names a sealed year: manifest {hits}, "
            f"raw cache {raw_hits}. A sealed year was fetched."
        )
    return {
        "manifest_dir": _rel(directory),
        "years_in_manifests": years_seen,
        "sealed_years_found": [],
        "raw_cache_present": raw_dir.exists(),
        "raw_files_naming_a_sealed_year": raw_hits,
        "clean": True,
    }


# ---------------------------------------------------------------------------
# 7. The pre-registration
# ---------------------------------------------------------------------------


def _baseline_2024() -> dict[str, dict[str, float]]:
    """The validation-year numbers the holdout will be read against.

    Carried into the pre-registration so the comparison the write-up will make
    is fixed *before* the holdout is visible: these are the numbers 2025 gets
    compared to, whatever 2025 turns out to be.
    """
    path = RESULTS_DIR / "c13_per_year_metrics.csv"
    frame = pd.read_csv(path)
    rows = frame[(frame["year"] == 2024) & (frame["curve"] == "lear_full_history")]
    out: dict[str, dict[str, float]] = {}
    for _, row in rows.iterrows():
        out[str(row["zone"])] = {
            "capture_rolled_oracle_cash": round(
                float(row["capture_rolled_oracle_cash"]), 6
            ),
            "dispatch_cash_eur_per_mw_year": round(
                float(row["dispatch_cash_eur_per_mw_year"]), 2
            ),
            "mae_on_dispatched_hours": round(float(row["mae_on_dispatched_hours"]), 4),
            "within_day_spearman_mean": round(
                float(row["within_day_spearman_mean"]), 6
            ),
        }
    return dict(sorted(out.items()))


def preregistration() -> dict[str, Any]:
    """Everything the single 2025 evaluation will do, fixed in advance."""
    zones = load_zones()
    battery = load_battery_config()["battery"]
    terminal = load_battery_config()["terminal"]
    return {
        "cycle": "C16",
        "checkpoint": "C",
        "status": "AWAITING HUMAN APPROVAL — the holdout is sealed",
        "written_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(library_versions()),
        "window": {
            "year": HOLDOUT_YEAR,
            "first_market_day": HOLDOUT_FIRST_DAY,
            "last_market_day": HOLDOUT_LAST_DAY,
            "n_market_days": (
                dt.date.fromisoformat(HOLDOUT_LAST_DAY)
                - dt.date.fromisoformat(HOLDOUT_FIRST_DAY)
            ).days
            + 1,
            "why_it_stops_there": (
                "the SDAC 15-minute go-live is 2025-10-01 and PLAN.md ends the "
                "main hourly backtest the day before; native 15-minute analysis "
                "stays a labelled stretch goal, never blended in"
            ),
        },
        "zones": {
            "tier_a": [k for k, z in zones.items() if z.tier == "A"],
            "tier_b": [k for k, z in zones.items() if z.tier == "B"],
        },
        "arms": {
            "headline_comparable": {
                "model": "lear",
                "exog_variant": "price_only",
                "vintage": "honest",
                "train_from": "2019-01-01",
                "why": (
                    "the nine-zone arm every cross-zone number in C10-C15 is "
                    "built on; comparability across zones outranks per-zone "
                    "accuracy for the headline"
                ),
            },
            "floor": {"model": "naive_last_week", "vintage": "honest"},
            "ceiling": {"model": "oracle", "exog_variant": "perfect_foresight"},
            "tier_a_exogenous": {
                "variants": ["price_only", "load_only", "res_persistence"],
                "models": ["lear", "gbm"],
                "excluded": "res_as_published",
                "why_excluded": (
                    "the Art. 14 D-1 wind/solar forecast is published at 18:00 "
                    "on D-1, after gate closure (vintage after_gate_closure). "
                    "It is reported in C8/C9 as a measured leak premium, and a "
                    "once-only holdout evaluation reports the honest arms"
                ),
            },
        },
        "models_frozen": {
            "lear": {
                "selector": "aic",
                "hour_key": "local",
                "vst": True,
                "note": "C4's committed LearSpec, unchanged since C4",
            },
            "gbm": {
                "fingerprint": "a366a760e269bba6",
                "note": (
                    "C9's one fixed LightGBM config with in-fold early stopping; "
                    "PLAN.md forbids a hyperparameter search, and the holdout is "
                    "not an occasion to start one"
                ),
            },
            "naive_last_week": {"note": "same hour, seven days earlier"},
        },
        "walk_forward": {
            "refit_every_days": 1,
            "min_train_days": 365,
            "train_window_days": None,
            "window": "expanding",
            "note": (
                "identical to C10/C11/C13. The expanding window means the 2025 "
                "folds train on 2019-2024 inclusive — the validation year moves "
                "from 'evaluated' to 'trained on', which is what an expanding "
                "window does and is legitimate because 2024 is in the past "
                "relative to every 2025 fold"
            ),
        },
        "curves": list(PREREG_CURVES),
        "dispatch": {
            "power_mw": float(battery["power_mw"]),
            "duration_hours": float(battery["duration_hours"]),
            "round_trip_efficiency": float(battery["round_trip_efficiency"]),
            "throughput_cost_eur_per_mwh": float(
                battery["throughput_cost_eur_per_mwh"]
            ),
            "initial_soc_fraction": float(battery["initial_soc_fraction"]),
            "terminal_mode": str(terminal["mode"]),
            "trailing_days": int(terminal["trailing_days"]),
            "trailing_quantile": float(terminal["trailing_quantile"]),
            "commit_then_settle": True,
            "note": (
                "config/battery.yaml as committed. NOTE C15-01 asks the human "
                "whether terminal_mode stays trailing_value; if it changes, it "
                "must change BEFORE the unseal, because changing it afterwards "
                "would mean re-evaluating the holdout a second time"
            ),
        },
        "metrics": {
            "forecast": [
                "mae_on_dispatched_hours",
                "rmse_on_dispatched_hours",
                "rmae_vs_naive_on_dispatched_hours",
                "daily_spread_mae_eur_per_mwh",
                "daily_spread_bias_eur_per_mwh",
                "within_day_spearman_mean",
            ],
            "dispatch": [
                "capture_rolled_oracle_cash",
                "capture_same_start",
                "dispatch_cash_eur_per_mw_year",
                "eur_per_mw_year_lost_vs_oracle",
            ],
            "intervals": {
                "method": "block bootstrap over daily blocks",
                "block_days_ladder": list(BLOCK_LADDER),
                "n_replicates": DEFAULT_REPLICATES,
                "seed": DEFAULT_SEED,
                "alpha": 0.05,
            },
        },
        "outputs": {
            "per_day": "backtest/results/c17_holdout_<ZONE>_2025_daily.csv.gz",
            "per_zone_summary": "backtest/results/c17_holdout_<ZONE>_2025_summary.json",
            "table": "backtest/results/c17_holdout_2025_metrics.csv",
            "intervals": "backtest/results/c17_holdout_2025_intervals.csv",
            "store": "backtest/results/results.csv (append-only, cycle C17)",
            "write_up": "docs/holdout_2025.md",
        },
        "assertions_that_must_hold": [
            "value(forecast schedule @ realised) <= value(same-start oracle @ "
            "realised) on EVERY dispatched day",
            "value(naive @ realised) <= value(forecast @ realised) pooled over "
            "the window (on average, not per day)",
            "no LP objective from a forecast-price solve is reported as a "
            "realised value (commit-then-settle, assert_settlement_is_not_a_readback)",
            "every feature's max timestamp precedes its row's gate closure "
            "(forecast/leakage.py, every fold, train and test)",
            "every training target was published before the fold's gate closure",
            "expected row count per (zone, local day) against the DST whitelist",
            "resolution_seconds == 3600 on every evaluated row; a 15-minute "
            "segment inside the window is a FLAG, not a resample",
            "no evaluated market day falls on or after 2025-10-01",
        ],
        "stop_rules": [
            "the evaluation runs ONCE. PROGRESS.md records the UTC timestamp of "
            "the run and the git SHA it ran at",
            "a failing invariant is a FLAG and a stop, not an occasion to "
            "adjust the model, the config or the window",
            "no model, feature set, hyperparameter, battery parameter or metric "
            "definition may change after the first 2025 number is seen. A "
            "change that looks necessary is a finding to report, and any re-run "
            "is a second evaluation that must be labelled as one",
            "a 404, an empty response or an Acknowledgement from either source "
            "is a FLAG; the dependent zone is skipped and the rest continues",
        ],
        "preconditions": {
            "human_writes_the_unseal_marker": (
                "a line in PROGRESS.md that, stripped, equals the "
                "holdout_unseal_marker value in config/data.yaml"
            ),
            "config_data_yaml_fetch_years_must_add_2025": (
                "ENTSO-E fetches are bounded by fetch_years (entsoe."
                "exogenous_years), so the Tier-A 2025 exogenous pull is refused "
                "until 2025 is added to fetch_years. The Energy-Charts price "
                "fetch is bounded only by the holdout guard"
            ),
            "entsoe_api_key": "required for the Tier-A 2025 exogenous pull",
            "fresh_download_required": (
                "no 2025 file has ever been cached, so the unseal cycle fetches "
                "9 zone-years of prices and 3 zones x 2 documents of ENTSO-E "
                "data — one request each, then cached"
            ),
            "expect_a_resolution_change_in_the_2025_price_file": (
                "a full-year 2025 Energy-Charts pull contains 15-minute data "
                "from 2025-10-01. data/contracts.py detects the change; the "
                "evaluation window ends 2025-09-30 so no 15-minute row is "
                "scored, and the post-cutover segment is reported, not dropped "
                "silently"
            ),
        },
        "baseline_2024_for_comparison": _baseline_2024(),
    }


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------


def _probe_report() -> dict[str, Any]:
    """Run every in-process probe against a cache that holds a sealed year."""
    with synthetic_sealed_cache() as cache_cfg:
        return run_probes(build_probes(cache_cfg))


def verify(write: bool = True) -> dict[str, Any]:
    """Every seal check, in one report. Raises on the first failure."""
    report = {
        "cycle": "C16",
        "checkpoint": "C",
        "verified_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "marker": marker_audit(),
        "split": split_audit(),
        "guards": guard_census(),
        "refusal_probes": _probe_report(),
        "cli_refusal_probes": run_cli_probes(),
        "artefacts": artefact_scan(),
        "download_record": manifest_scan(),
    }
    report["seal_intact"] = True
    report["holdout_year_touched_by_this_cycle"] = False
    if write:
        _write(RESULTS_DIR / "c16_seal_verification.json", report)
    return report


def prereg(write: bool = True) -> dict[str, Any]:
    """Write the pre-registration. Refuses to run if the seal is already broken."""
    if holdout_is_unsealed():
        raise CheckpointError(
            "PROGRESS.md already carries the unseal marker: a pre-registration "
            "written after the holdout is visible is not a pre-registration"
        )
    doc = preregistration()
    if write:
        _write(RESULTS_DIR / "c16_preregistration.json", doc)
    return doc


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str, sort_keys=False)
        fh.write("\n")
    print(f"  wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size / 1024:.0f} KiB)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["verify", "prereg", "all"], default="all",
        help="verify the seal, write the pre-registration, or both",
    )
    parser.add_argument(
        "--no-write", action="store_true", help="compute but write no artefact"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    write = not args.no_write
    if args.phase in ("verify", "all"):
        report = verify(write=write)
        print("seal verification:")
        print("  marker on a line of its own : no (seal intact)")
        print(f"  guard calls                 : {report['guards']['n_guard_calls']} "
              f"in {report['guards']['n_modules_with_a_guard']} module(s)")
        print(f"  entry points that refused   : "
              f"{report['refusal_probes']['n_refused']}/"
              f"{report['refusal_probes']['n_probes']}")
        print(f"  runners that refused        : "
              f"{report['cli_refusal_probes']['n_cli_probes']}/"
              f"{len(CLI_PROBES)}")
        print(f"  artefacts scanned           : "
              f"{report['artefacts']['n_tables_scanned']} table(s), "
              f"{report['artefacts']['n_summaries_scanned']} summary file(s), "
              f"clean")
        print(f"  years in the download record: "
              f"{report['download_record']['years_in_manifests']}")
    if args.phase in ("prereg", "all"):
        doc = prereg(write=write)
        print("pre-registration:")
        print(f"  window   : {doc['window']['first_market_day']} .. "
              f"{doc['window']['last_market_day']} "
              f"({doc['window']['n_market_days']} market days)")
        print(f"  zones    : {len(doc['zones']['tier_a'])} Tier A + "
              f"{len(doc['zones']['tier_b'])} Tier B")
        print(f"  curves   : {', '.join(doc['curves'])}")
        print(f"  git sha  : {doc['git_sha'][:12]}  config {doc['config_hash']}")
    print("\nCheckpoint C: the 2025 holdout is SEALED and stays sealed. "
          "Only a human unseals it.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
