"""Mechanical enforcement of the sealed 2025 holdout.

CLAUDE.md forbids loading, reading, feature-engineering from, training on, or
computing any metric against a sealed year until ``PROGRESS.md`` records that
Checkpoint C has been explicitly approved by the human. A rule that lives only
in prose gets broken by a tired cycle at 03:00, so it lives here as a function
that every fetch/load path calls.

The only thing that unseals the holdout is the exact marker line from
``config/data.yaml`` (``holdout_unseal_marker``) appearing in ``PROGRESS.md``.
An agent cycle must never write that line — it is the human's signature.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from data.config import REPO_ROOT, load_data_config, sealed_years


class SealedHoldoutError(RuntimeError):
    """Raised on any attempt to touch sealed-holdout data before approval."""


def unseal_marker(config_dir: Path | None = None) -> str:
    return str(load_data_config(config_dir)["holdout_unseal_marker"])


def holdout_is_unsealed(
    progress_path: Path | None = None, config_dir: Path | None = None
) -> bool:
    """True only if PROGRESS.md contains the exact unseal marker line."""
    path = progress_path or (REPO_ROOT / "PROGRESS.md")
    if not path.exists():
        return False
    marker = unseal_marker(config_dir)
    return marker in path.read_text(encoding="utf-8")


def years_in_range(start: dt.date, end: dt.date) -> set[int]:
    """Every calendar year touched by the inclusive date range ``[start, end]``."""
    if end < start:
        raise ValueError(f"end {end} precedes start {start}")
    return set(range(start.year, end.year + 1))


def assert_not_sealed(
    years: int | set[int] | list[int],
    what: str,
    progress_path: Path | None = None,
    config_dir: Path | None = None,
) -> None:
    """Raise :class:`SealedHoldoutError` if ``years`` touches the sealed holdout.

    ``what`` describes the attempted operation and appears in the error message,
    so a traceback in an unattended cycle log says what was about to leak.
    """
    requested = {int(years)} if isinstance(years, int) else {int(y) for y in years}
    sealed = sealed_years(config_dir)
    hit = sorted(requested.intersection(sealed))
    if not hit:
        return
    if holdout_is_unsealed(progress_path, config_dir):
        return
    raise SealedHoldoutError(
        f"refusing to {what}: year(s) {hit} are the SEALED HOLDOUT. "
        f"PROGRESS.md does not contain the unseal marker "
        f"({unseal_marker(config_dir)!r}), which only a human writes after "
        f"Checkpoint C (C16) is approved. See CLAUDE.md."
    )


def assert_range_not_sealed(
    start: dt.date,
    end: dt.date,
    what: str,
    progress_path: Path | None = None,
    config_dir: Path | None = None,
) -> None:
    """Range form of :func:`assert_not_sealed` (inclusive of both endpoints)."""
    assert_not_sealed(years_in_range(start, end), what, progress_path, config_dir)
