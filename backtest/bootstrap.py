"""The daily-block bootstrap (PLAN.md C12): confidence intervals over day blocks.

Every headline this project has produced so far is a point estimate over one
validation year, and NOTE C11-01 is blunt about what that is worth: FINDING
C11-A's cross-zone capture band is *substantially one zone*, FINDING C11-D rests
on fifteen paired comparisons most of whose deltas are under one percentage
point, and nothing yet says which of them is wider than noise. This module is
how C12 answers that, and it is the whole reason C12 is not a formatting cycle.

**The resampling unit is a market day, because the day is this project's unit of
everything else.** The battery LP optimises one day at a time; the capture ratio
is a ratio of sums over days; the per-day artefact C11 committed is one row per
(zone, curve, day). Resampling *hours* would destroy the within-day price shape
that the dispatch decision is made of and would produce absurdly narrow
intervals; resampling days keeps each day's 24-hour shape intact and treats the
year as ~365 draws rather than ~8 760.

Four design decisions, each of which changes a reported interval.

**Paired, not independent.** One replicate draws *one* day multiset and applies
it to every zone, every curve and every statistic in that replicate. European
day-ahead prices are strongly correlated across zones and two forecast arms see
the same days, so resampling each series independently would inflate the
interval on every difference — and a difference is exactly what FINDING C11-D
and the GBM-exogenous question are about. All comparisons here are therefore
paired by construction, the same way C11 made its MAE deltas paired by
recomputing them on the dispatched hours.

**Circular moving blocks, with the block length reported.** PLAN.md says "daily
blocks", so the headline is ``block_days=1`` — the day is the block. But power
prices are serially correlated across days (a cold week, a windy week), and a
1-day block assumes they are not, which can make an interval too narrow. So the
block length is a parameter, the cycle reports the same interval at 1, 7 and 14
days, and any conclusion that does not survive the widest block is reported as
not surviving it. Blocks wrap around the end of the year (the circular variant)
so that every day appears in exactly ``block_days`` blocks and no day is
systematically under-weighted.

**Statistics are built from day-additive columns.** A count matrix of shape
``(n_replicates, n_days)`` is drawn once and every statistic is then a matrix
product against per-day columns: a pooled MAE is a ratio of two column sums, a
capture ratio is a ratio of two column sums, a mean Spearman is a column mean.
That is both fast (one matmul instead of 10 000 passes) and exact — the
replicate statistic is computed by the same formula as the point estimate, so
the point estimate is recovered precisely when the "resample" is the identity.
Order statistics of a per-day distribution (C11's ``capture_same_start_p05``
and friends) are deliberately **not** bootstrapped here: they are not
day-additive, and C11 already persists that distribution in full.

**Percentile intervals, and the limitation is stated.** The interval is the
2.5th-97.5th percentile of the replicate distribution. No BCa, no studentisation:
with a ratio of sums over 365 strongly-dependent days, the percentile interval's
coverage is approximate, and pretending otherwise with a more decorated method
would be false precision. Where a conclusion depends on the method rather than
on the data, the honest report is that the data does not settle it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np

#: Fixed so an interval is reproducible across cycles and containers. A cycle
#: that wants a different seed is asking "is my finding an artefact of the
#: draw?", which is a question for ``n_replicates``, not for the seed.
DEFAULT_SEED = 20261009

#: 10 000 replicates puts the Monte-Carlo error on a 2.5% percentile at well
#: under a tenth of the interval width, which is far below the sampling
#: uncertainty the interval is reporting.
DEFAULT_REPLICATES = 10_000

#: The headline is PLAN.md's literal "daily blocks"; the other two are the
#: serial-dependence sensitivity every interval is reported at.
DEFAULT_BLOCK_DAYS = 1
BLOCK_LADDER: tuple[int, ...] = (1, 7, 14)


class BootstrapError(RuntimeError):
    """The resample cannot be drawn, or a statistic cannot be formed from it."""


@dataclass(frozen=True)
class BlockBootstrapSpec:
    """Everything that makes a replicate distribution reproducible."""

    n_days: int
    n_replicates: int = DEFAULT_REPLICATES
    block_days: int = DEFAULT_BLOCK_DAYS
    seed: int = DEFAULT_SEED
    alpha: float = 0.05

    def __post_init__(self) -> None:
        if self.n_days < 2:
            raise BootstrapError(
                f"a bootstrap over {self.n_days} day(s) is not a bootstrap"
            )
        if self.block_days < 1 or self.block_days > self.n_days:
            raise BootstrapError(
                f"block_days {self.block_days} must be in 1..{self.n_days}"
            )
        if self.n_replicates < 2:
            raise BootstrapError("n_replicates must be at least 2")
        if not 0.0 < self.alpha < 1.0:
            raise BootstrapError(f"alpha {self.alpha} must be in (0, 1)")

    @property
    def n_blocks(self) -> int:
        """Blocks per replicate: enough to cover ``n_days``, then truncated."""
        return int(np.ceil(self.n_days / self.block_days))

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "n_blocks_per_replicate": self.n_blocks}


@dataclass(frozen=True)
class Interval:
    """One statistic's point estimate and its bootstrap interval.

    ``prob_le_zero`` / ``prob_ge_zero`` are reported for every interval because
    most of what C12 is asked to decide is a *sign* question — does this arm
    capture more than that one — and the share of replicates on the wrong side
    of zero says that directly, without a null model the data cannot support.
    """

    point: float
    ci_low: float
    ci_high: float
    boot_mean: float
    boot_sd: float
    prob_le_zero: float
    prob_ge_zero: float
    n_replicates: int
    block_days: int
    alpha: float

    @property
    def excludes_zero(self) -> bool:
        return (self.ci_low > 0.0 and self.ci_high > 0.0) or (
            self.ci_low < 0.0 and self.ci_high < 0.0
        )

    @property
    def width(self) -> float:
        return self.ci_high - self.ci_low

    def as_dict(self) -> dict[str, Any]:
        out = {k: (round(v, 10) if isinstance(v, float) else v)
               for k, v in asdict(self).items()}
        out["excludes_zero"] = self.excludes_zero
        out["width"] = round(self.width, 10)
        return out


# ---------------------------------------------------------------------------
# The resample
# ---------------------------------------------------------------------------


def replicate_counts(spec: BlockBootstrapSpec) -> np.ndarray:
    """``(n_replicates, n_days)`` matrix of how often each day was drawn.

    A circular moving-block bootstrap: each replicate draws ``n_blocks`` start
    days uniformly, takes ``block_days`` consecutive days from each (wrapping at
    the end of the year), concatenates them and truncates to exactly ``n_days``.
    Counts rather than index lists because every statistic downstream is a
    weighted column sum, and a count matrix makes all of them one matmul.

    ``block_days=1`` is the ordinary iid-over-days bootstrap, which is what
    PLAN.md's "daily blocks" names.
    """
    rng = np.random.default_rng(spec.seed)
    starts = rng.integers(
        0, spec.n_days, size=(spec.n_replicates, spec.n_blocks), dtype=np.int64
    )
    offsets = np.arange(spec.block_days, dtype=np.int64)
    # (n_reps, n_blocks, block_days) -> flat day indices, wrapped, truncated.
    picks = (starts[:, :, None] + offsets[None, None, :]) % spec.n_days
    picks = picks.reshape(spec.n_replicates, -1)[:, : spec.n_days]
    counts = np.zeros((spec.n_replicates, spec.n_days), dtype=np.float64)
    rows = np.repeat(
        np.arange(spec.n_replicates, dtype=np.int64), spec.n_days
    )
    np.add.at(counts, (rows, picks.reshape(-1)), 1.0)
    drawn = counts.sum(axis=1)
    if not np.allclose(drawn, spec.n_days):
        raise BootstrapError(
            f"a replicate drew {drawn.min()}-{drawn.max()} days, expected "
            f"{spec.n_days} — the block construction is wrong"
        )
    return counts


def _as_column(values: Sequence[float] | np.ndarray, n_days: int, what: str) -> np.ndarray:
    column = np.asarray(values, dtype=np.float64)
    if column.shape != (n_days,):
        raise BootstrapError(
            f"{what} has shape {column.shape}, expected ({n_days},) — a "
            f"bootstrap column is one value per day, in the day order the "
            f"counts were drawn over"
        )
    if not np.all(np.isfinite(column)):
        raise BootstrapError(
            f"{what} contains a non-finite value. A day that cannot contribute "
            f"to this statistic must be excluded from the day set before the "
            f"resample, not carried as a NaN that would silently poison every "
            f"replicate containing it."
        )
    return column


def _interval(point: float, replicates: np.ndarray, spec: BlockBootstrapSpec) -> Interval:
    finite = replicates[np.isfinite(replicates)]
    if finite.size < 2:
        raise BootstrapError("fewer than two finite replicates — no interval")
    lo, hi = np.quantile(finite, [spec.alpha / 2.0, 1.0 - spec.alpha / 2.0])
    return Interval(
        point=float(point),
        ci_low=float(lo),
        ci_high=float(hi),
        boot_mean=float(np.mean(finite)),
        boot_sd=float(np.std(finite, ddof=1)),
        prob_le_zero=float(np.mean(finite <= 0.0)),
        prob_ge_zero=float(np.mean(finite >= 0.0)),
        n_replicates=int(finite.size),
        block_days=spec.block_days,
        alpha=spec.alpha,
    )


# ---------------------------------------------------------------------------
# Statistics that are day-additive
# ---------------------------------------------------------------------------


def ratio_replicates(
    numerator: Sequence[float] | np.ndarray,
    denominator: Sequence[float] | np.ndarray,
    counts: np.ndarray,
) -> np.ndarray:
    """Replicates of ``sum(numerator) / sum(denominator)`` over resampled days.

    This is the shape of almost every number C12 bootstraps: a capture ratio
    (settled cash over the rolled oracle's cash), a pooled MAE (summed absolute
    error over summed hours), an rMAE (one pooled MAE over another). Summing
    numerator and denominator over the *same* resampled days is the same
    discipline C11's :func:`pooled_capture` imposed on the point estimate — a
    ratio of sums taken over different day sets is not a ratio of anything.
    """
    n_days = counts.shape[1]
    num = _as_column(numerator, n_days, "numerator")
    den = _as_column(denominator, n_days, "denominator")
    top = counts @ num
    bottom = counts @ den
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(bottom) > 1e-12, top / bottom, np.nan)
    return out


def mean_replicates(
    values: Sequence[float] | np.ndarray, counts: np.ndarray
) -> np.ndarray:
    """Replicates of the mean of a per-day column over resampled days."""
    n_days = counts.shape[1]
    column = _as_column(values, n_days, "values")
    return (counts @ column) / counts.sum(axis=1)


def ratio_interval(
    numerator: Sequence[float] | np.ndarray,
    denominator: Sequence[float] | np.ndarray,
    counts: np.ndarray,
    spec: BlockBootstrapSpec,
) -> Interval:
    """Point estimate and interval for a ratio of day sums."""
    num = np.asarray(numerator, dtype=np.float64)
    den = np.asarray(denominator, dtype=np.float64)
    point = float(num.sum() / den.sum())
    return _interval(point, ratio_replicates(num, den, counts), spec)


def mean_interval(
    values: Sequence[float] | np.ndarray,
    counts: np.ndarray,
    spec: BlockBootstrapSpec,
) -> Interval:
    """Point estimate and interval for the mean of a per-day column."""
    column = np.asarray(values, dtype=np.float64)
    return _interval(float(column.mean()), mean_replicates(column, counts), spec)


def difference_interval(
    treatment: np.ndarray, baseline: np.ndarray, point: float, spec: BlockBootstrapSpec
) -> Interval:
    """Paired interval for ``treatment - baseline``, replicate by replicate.

    The pairing is the point: both arrays are replicates of the *same* draws, so
    the difference distribution carries none of the year-to-year variation the
    two arms share. ``point`` is passed in rather than differenced out of the
    replicates so that the reported centre is the published point estimate and
    not the bootstrap mean.
    """
    if treatment.shape != baseline.shape:
        raise BootstrapError(
            f"paired replicates must have the same shape, got {treatment.shape} "
            f"and {baseline.shape}"
        )
    return _interval(point, treatment - baseline, spec)


# ---------------------------------------------------------------------------
# Is a spread across groups wider than noise?
# ---------------------------------------------------------------------------


def noise_only_spread(
    points: Sequence[float], replicates: np.ndarray, observed_band: float | None = None
) -> dict[str, Any]:
    """How wide a band would sampling noise alone produce across these groups?

    FINDING C11-A's claim is that the capture ratio's band across zones is wider
    than the forecast-error metric's. A bootstrap interval on the band cannot
    settle that on its own: a band is a maximum minus a minimum, so it is
    positively biased and its interval excludes zero even when every group is
    identical.

    So this builds the band's *null* distribution directly. For each replicate
    the group effect is removed and the group's own bootstrap deviation kept:

        null_g,b = mean(points) + (replicate_g,b - point_g)

    Every group now sits at the common level and differs only by the sampling
    noise the bootstrap measured for it, so ``max - min`` over the groups is a
    draw of the band under "all groups are really the same". The reported
    ``p_value`` is the share of those draws at least as wide as the observed
    band — a small p says the observed spread is more than noise. The
    between/within ratio beside it says the same thing as an effect size.

    This keeps each group's own noise scale (a zone with 357 days and a thinner
    market is noisier than one with 365) rather than assuming a common variance.
    """
    point = np.asarray(points, dtype=np.float64)
    if replicates.ndim != 2 or replicates.shape[1] != point.size:
        raise BootstrapError(
            f"replicates must be (n_replicates, n_groups={point.size}), got "
            f"{replicates.shape}"
        )
    if point.size < 2:
        raise BootstrapError("a band across fewer than two groups is not a band")
    band = float(point.max() - point.min()) if observed_band is None else float(observed_band)
    centred = replicates - point[None, :] + float(point.mean())
    null_band = centred.max(axis=1) - centred.min(axis=1)
    within_sd = np.std(replicates, axis=0, ddof=1)
    between_sd = float(np.std(point, ddof=1))
    mean_within = float(np.mean(within_sd))
    return {
        "observed_band": round(band, 10),
        "n_groups": int(point.size),
        "null_band_mean": round(float(np.mean(null_band)), 10),
        "null_band_p95": round(float(np.quantile(null_band, 0.95)), 10),
        "null_band_max": round(float(np.max(null_band)), 10),
        "p_value": round(float(np.mean(null_band >= band)), 6),
        "between_group_sd": round(between_sd, 10),
        "mean_within_group_boot_sd": round(mean_within, 10),
        "between_over_within": (
            round(between_sd / mean_within, 6) if mean_within > 0 else None
        ),
        "per_group_boot_sd": [round(float(s), 10) for s in within_sd],
    }


def spearman_rows(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Row-wise Spearman rank correlation between two ``(n_rows, k)`` matrices.

    Used to bootstrap a rank correlation across a fixed set of ``k`` items —
    FINDING C11-D's fifteen paired comparisons, or the nine zones of FINDING
    C11-A — where each row is one replicate's recomputation of all ``k`` items.
    Average ranks, so ties behave the standard way, and a row where either side
    is flat returns ``nan`` rather than a spurious correlation.
    """
    if x.shape != y.shape:
        raise BootstrapError(f"shapes differ: {x.shape} vs {y.shape}")
    if x.ndim != 2 or x.shape[1] < 3:
        raise BootstrapError("need (n_rows, k>=3) to rank-correlate")

    def _ranks(a: np.ndarray) -> np.ndarray:
        order = np.argsort(a, axis=1, kind="stable")
        ranks = np.empty_like(a, dtype=np.float64)
        rows = np.arange(a.shape[0])[:, None]
        ranks[rows, order] = np.arange(1, a.shape[1] + 1, dtype=np.float64)[None, :]
        # Average the ranks of tied values, which is what "Spearman" means.
        for i in range(a.shape[0]):
            values = a[i]
            uniq, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
            if counts.max() > 1:
                sums = np.zeros(uniq.size, dtype=np.float64)
                np.add.at(sums, inverse, ranks[i])
                ranks[i] = (sums / counts)[inverse]
        return ranks

    rx, ry = _ranks(x), _ranks(y)
    rx = rx - rx.mean(axis=1, keepdims=True)
    ry = ry - ry.mean(axis=1, keepdims=True)
    num = (rx * ry).sum(axis=1)
    den = np.sqrt((rx**2).sum(axis=1) * (ry**2).sum(axis=1))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)
