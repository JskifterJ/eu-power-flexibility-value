"""The gate-closure leakage guard: one place that can say "you could not have known that".

PLAN.md requires this to exist, with teeth, **before** the first real model —
because once a model exists, every incentive points at not looking too hard at
why it scores well. The guard is deliberately mechanical and deliberately
fail-closed.

The contract it enforces, per row of a feature matrix:

1. Every feature column must be **declared**: present in the information-time
   frame. An undeclared column is a violation, not a column that gets the
   benefit of the doubt. This is the rule that catches a later cycle quietly
   adding ``price_lead_24h`` to the matrix.
2. A column declared ``deterministic`` (calendar: hour, weekday, month) must
   carry ``NaT`` information times — it embeds no market information at all.
3. Every other column's non-missing cells must carry a real information time
   that is ``<=`` that row's own **gate closure**. Not the target hour: gate
   closure. The gap between the two is a whole afternoon of information a
   bidder did not have.
4. A declaration must be *interpretable*: a UTC timestamp column. One careless
   assignment turns it into ``object`` or tz-naive dtype, and comparing that
   against a tz-aware gate closure raises an opaque ``TypeError`` from inside
   pandas — in a guard, a check that neither passes nor fails is the worst
   outcome of all. So an uninterpretable declaration is reported as a violation
   (``malformed_information_time``), and a declaration for a column that is not
   in the matrix is reported too (``stale_declaration``).

:func:`mask_unavailable` is the companion to the guard: where a feature cell is
genuinely not knowable at gate closure, the honest value is "unknown" (NaN), not
the leaking number and not a quietly dropped row. It reports exactly how many
cells it blanked, per column, so the count is a number in the write-up rather
than a silence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd


class LeakageError(AssertionError):
    """A feature matrix contains information that was not public at gate closure."""


@dataclass(frozen=True)
class LeakageViolation:
    """One way in which a feature matrix fails the gate-closure contract."""

    kind: str
    column: str
    detail: str
    n_rows: int = 0
    first_timestamp: pd.Timestamp | None = None
    worst_lateness: pd.Timedelta | None = None

    def describe(self) -> str:
        where = (
            f" first at {self.first_timestamp.isoformat()}"
            if self.first_timestamp is not None
            else ""
        )
        late = (
            f", worst {self.worst_lateness} after gate closure"
            if self.worst_lateness is not None
            else ""
        )
        rows = f" ({self.n_rows} row(s))" if self.n_rows else ""
        return f"[{self.kind}] {self.column}: {self.detail}{rows}{where}{late}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "column": self.column,
            "detail": self.detail,
            "n_rows": self.n_rows,
            "first_timestamp": (
                self.first_timestamp.isoformat() if self.first_timestamp is not None else None
            ),
            "worst_lateness_seconds": (
                self.worst_lateness.total_seconds() if self.worst_lateness is not None else None
            ),
        }


@dataclass
class MaskReport:
    """How many cells :func:`mask_unavailable` had to blank, and where."""

    masked_per_column: dict[str, int] = field(default_factory=dict)
    first_masked_per_column: dict[str, str] = field(default_factory=dict)

    @property
    def total_masked(self) -> int:
        return sum(self.masked_per_column.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_masked": self.total_masked,
            "masked_per_column": dict(self.masked_per_column),
            "first_masked_per_column": dict(self.first_masked_per_column),
        }


def _check_frames_align(
    features: pd.DataFrame, information_times: pd.DataFrame, gate_closure: pd.Series
) -> None:
    if not features.index.equals(information_times.index):
        raise LeakageError("feature and information-time frames have different indexes")
    if not features.index.equals(gate_closure.index):
        raise LeakageError("gate-closure series does not share the feature index")


def _as_utc(series: pd.Series) -> pd.Series | None:
    """Coerce a declared information-time column to UTC, or ``None`` if it cannot be.

    Information times arrive from several places — built by
    :mod:`forecast.features`, hand-written by an experiment, edited by a later
    cycle — and pandas will happily turn a column into ``object`` or tz-naive
    dtype after a single careless assignment. Comparing such a column against a
    tz-aware gate closure raises an opaque ``TypeError`` deep inside pandas, which
    in a guard is the worst possible outcome: the check neither passes nor fails,
    it explodes somewhere unrelated. So coerce what can be coerced, and report
    what cannot as a violation (``None``) rather than crashing.

    A tz-naive datetime column holding real timestamps is rejected rather than
    assumed to be UTC. The repo's contract is UTC everywhere (CLAUDE.md), and a
    naive column means the timezone was lost somewhere upstream — a thing to
    report, not to guess at. An **all-NaT** naive column is accepted and becomes
    all-NaT UTC: it carries no timestamp that could be misread, and it is how a
    caller spells "this column has no information time" (which the guard then
    reports as missing, if the feature has values).
    """
    if (
        pd.api.types.is_datetime64_any_dtype(series)
        and not isinstance(series.dtype, pd.DatetimeTZDtype)
        and bool(series.notna().any())
    ):
        return None
    try:
        converted = pd.to_datetime(series, utc=True)
    except (TypeError, ValueError):
        return None
    if not isinstance(converted.dtype, pd.DatetimeTZDtype):
        return None
    return converted


def find_leakage(
    features: pd.DataFrame,
    information_times: pd.DataFrame,
    gate_closure: pd.Series,
    deterministic: Iterable[str] = (),
) -> list[LeakageViolation]:
    """Every way ``features`` violates the gate-closure contract. Empty == clean."""
    _check_frames_align(features, information_times, gate_closure)
    deterministic_set = set(deterministic)
    violations: list[LeakageViolation] = []

    gate = _as_utc(gate_closure)
    if gate is None:
        raise LeakageError(
            f"gate-closure series is not a usable timestamp column "
            f"(dtype {gate_closure.dtype}) — the guard cannot check anything against it"
        )

    malformed: set[str] = set()
    normalised: dict[str, pd.Series] = {}
    for column in information_times.columns:
        converted = _as_utc(information_times[column])
        if converted is None:
            malformed.add(column)
            violations.append(
                LeakageViolation(
                    kind="malformed_information_time",
                    column=column,
                    detail=(
                        f"declared information time has dtype "
                        f"{information_times[column].dtype}, which is not a UTC "
                        f"timestamp column — the declaration cannot be checked, so "
                        f"the guard fails closed"
                    ),
                )
            )
        else:
            normalised[column] = converted

    undeclared = [c for c in features.columns if c not in information_times.columns]
    for column in undeclared:
        violations.append(
            LeakageViolation(
                kind="undeclared",
                column=column,
                detail=(
                    "feature column has no declared information time — the guard "
                    "fails closed rather than assuming it is safe"
                ),
                n_rows=int(features[column].notna().sum()),
            )
        )
    for column in [c for c in information_times.columns if c not in features.columns]:
        violations.append(
            LeakageViolation(
                kind="stale_declaration",
                column=column,
                detail="information time declared for a column that is not in the matrix",
            )
        )
    unknown_deterministic = sorted(deterministic_set - set(features.columns))
    for column in unknown_deterministic:
        violations.append(
            LeakageViolation(
                kind="stale_declaration",
                column=column,
                detail="declared deterministic but absent from the matrix",
            )
        )

    for column in features.columns:
        if column in undeclared or column in malformed:
            continue
        values = features[column]
        info = normalised[column]
        present = values.notna()

        if column in deterministic_set:
            bad = info.notna()
            if bool(bad.any()):
                violations.append(
                    LeakageViolation(
                        kind="deterministic_with_information",
                        column=column,
                        detail=(
                            "declared deterministic (calendar) but carries a market "
                            "information time — one of the two declarations is wrong"
                        ),
                        n_rows=int(bad.sum()),
                        first_timestamp=info.index[bad][0],
                    )
                )
            continue

        missing_info = present & info.isna()
        if bool(missing_info.any()):
            violations.append(
                LeakageViolation(
                    kind="missing_information_time",
                    column=column,
                    detail=(
                        "feature has a value but no information time — cannot be "
                        "checked against gate closure, so it is a violation"
                    ),
                    n_rows=int(missing_info.sum()),
                    first_timestamp=info.index[missing_info][0],
                )
            )

        late = present & info.notna() & (info > gate)
        if bool(late.any()):
            lateness = (info[late] - gate[late])
            violations.append(
                LeakageViolation(
                    kind="after_gate_closure",
                    column=column,
                    detail=(
                        "feature embeds information published after the bidding "
                        "deadline for its own target day"
                    ),
                    n_rows=int(late.sum()),
                    first_timestamp=info.index[late][0],
                    worst_lateness=pd.Timedelta(lateness.max()),
                )
            )

    return violations


def assert_no_leakage(
    features: pd.DataFrame,
    information_times: pd.DataFrame,
    gate_closure: pd.Series,
    deterministic: Iterable[str] = (),
    context: str = "feature matrix",
) -> None:
    """Raise :class:`LeakageError` listing every violation, or return silently."""
    violations = find_leakage(features, information_times, gate_closure, deterministic)
    if not violations:
        return
    lines = "\n  ".join(v.describe() for v in violations)
    raise LeakageError(
        f"{context} fails the gate-closure contract "
        f"({len(violations)} violation(s)):\n  {lines}"
    )


def mask_unavailable(
    features: pd.DataFrame,
    information_times: pd.DataFrame,
    gate_closure: pd.Series,
    deterministic: Iterable[str] = (),
) -> tuple[pd.DataFrame, MaskReport]:
    """Blank every feature cell not public at its row's gate closure.

    Returns a copy; the input is never mutated. Deterministic columns are left
    alone. Rows are never dropped: "unknown at decision time" is information in
    itself, and dropping the row would quietly shrink the evaluation set.
    """
    _check_frames_align(features, information_times, gate_closure)
    deterministic_set = set(deterministic)
    masked = features.copy()
    report = MaskReport()

    gate = _as_utc(gate_closure)
    if gate is None:
        raise LeakageError(
            f"gate-closure series is not a usable timestamp column (dtype "
            f"{gate_closure.dtype}) — refusing to decide availability against it"
        )

    for column in features.columns:
        if column in deterministic_set or column not in information_times.columns:
            continue
        info = _as_utc(information_times[column])
        if info is None:
            # Undecidable availability: blank the whole column rather than keep
            # values the guard will reject anyway. Reported like any other mask.
            unavailable = features[column].notna()
        else:
            unavailable = features[column].notna() & (info.isna() | (info > gate))
        count = int(unavailable.sum())
        if not count:
            continue
        masked.loc[unavailable, column] = float("nan")
        report.masked_per_column[column] = count
        report.first_masked_per_column[column] = features.index[unavailable][0].isoformat()
    return masked, report
