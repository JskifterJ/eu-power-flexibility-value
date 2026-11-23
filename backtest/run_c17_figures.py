"""CLI: C17 — the figures the results summary is read from.

    python -m backtest.run_c17_figures

Three figures, each answering one question a reader of the README will ask, and
nothing else. **This module computes no result.** It reads the append-only store
(`backtest/results/results.csv`), the holdout evaluation's own interval file and
the Checkpoint-C pre-registration, and draws what is already there. It neither
imports nor defines any of the store's writing machinery — a figure phase that
grew into a producer of result rows would be a quiet way to put an unreviewed
number into the store, which is exactly what C20's gate asserts against for its
own phases, statically, for the same reason.

The three questions:

1. **Does the holdout land inside the range of the visible years?** Capture
   ratio per zone, 2020-2025, the comparable arm. The out-of-sample year is
   drawn as an open marker on a shaded band so it cannot be read as one more
   visible year. FINDING C13-A says a zone's capture moves across years by as
   much as the zones differ from each other within a year, so "is 2025 inside
   the band" is the honest headline question, not "is 2025 high or low".
2. **How does the holdout compare with the number that was written down before
   it was unsealed?** Capture, 2025 against `baseline_2024_for_comparison` in
   `c16_preregistration.json`, with the holdout's own bootstrap interval. The
   baseline is pre-registered, so this panel cannot be a comparison chosen
   after seeing the result.
3. **Does the one cross-regime relationship that survived five years survive a
   sixth, unseen one?** `error_over_headroom` against capture over every usable
   (zone, year) cell, 2020-2024 in grey and the six 2025 cells in colour
   (FINDING C13-D: rho = -0.738 over 44 cells).

Every figure carries the Energy-Charts attribution: a PNG travels on its own,
and a reader who lifts one out of ``docs/figures/`` has no ``config/data.yaml``
to consult.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest.results_store import RESULTS_DIR, honest_rows
from backtest.run_c3_naive import git_sha

#: C13's spelling of the nine-zone comparable arm, and the one C17 evaluated.
COMPARABLE_MODEL = "lear"
COMPARABLE_VARIANT = "price_only"
COMPARABLE_TRAIN_FROM = "2019-01-01"

#: The zone every cross-zone finding in this project has to be read twice
#: around (FINDINGs C11-B, C12-C, C13-C, C13-E, C15-E).
OUTLIER_ZONE = "NO2"

#: The out-of-sample year. Drawn apart from the visible ones on purpose.
HOLDOUT_YEAR = 2025

#: PLAN.md's literal daily block, which is C13's headline rung.
HEADLINE_BLOCK = 1

FIGURES_DIR = RESULTS_DIR.parent.parent / "docs" / "figures"

#: The string declared in ``config/data.yaml``; C20's licence phase asserts
#: that every committed figure's producing module emits it.
ATTRIBUTION = "Data: Energy-Charts (Fraunhofer ISE), CC BY 4.0"

PREREGISTRATION = RESULTS_DIR / "c16_preregistration.json"
HOLDOUT_INTERVALS = RESULTS_DIR / "c17_holdout_2025_intervals.csv"
SUMMARY = RESULTS_DIR / "c17_figures.json"


class FigureError(RuntimeError):
    """A figure cannot be drawn from what is committed."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=None,
                        help="where the PNGs go (default: docs/figures)")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Reading what is already committed
# ---------------------------------------------------------------------------


def comparable_cells(metric: str) -> pd.DataFrame:
    """One row per (zone, year) for the comparable arm's ``metric``.

    Read through :func:`backtest.results_store.honest_rows`, so the
    ``after_gate_closure`` rows that exist only to measure the Art. 14 vintage
    premium (FINDINGs C8-A, C9-C) cannot reach a figure by accident.
    """
    frame = honest_rows()
    if frame.empty:
        raise FigureError("the results store is empty")
    sub = frame[
        (frame["model"] == COMPARABLE_MODEL)
        & (frame["exog_variant"] == COMPARABLE_VARIANT)
        & (frame["train_from"] == COMPARABLE_TRAIN_FROM)
        & (frame["scope"] == "common_hours")
        & (frame["metric"] == metric)
    ].copy()
    if sub.empty:
        raise FigureError(f"no comparable-arm rows for metric {metric!r}")
    years = sub["evaluation_years"].astype(str)
    single = years.str.fullmatch(r"\d{4}")
    sub = sub[single].copy()
    sub["year"] = sub.loc[single.index[single], "evaluation_years"].astype(int)
    return sub[["zone", "year", "value"]].sort_values(["zone", "year"])


def oracle_cells(metric: str) -> pd.DataFrame:
    """The same, for the perfect-foresight ceiling."""
    frame = honest_rows()
    sub = frame[
        (frame["model"] == "oracle")
        & (frame["scope"] == "common_hours")
        & (frame["metric"] == metric)
    ].copy()
    years = sub["evaluation_years"].astype(str)
    single = years.str.fullmatch(r"\d{4}")
    sub = sub[single].copy()
    sub["year"] = sub.loc[single.index[single], "evaluation_years"].astype(int)
    return sub[["zone", "year", "value"]].sort_values(["zone", "year"])


def holdout_interval(metric: str) -> pd.DataFrame:
    """The holdout's own bootstrap bounds at the headline block, per zone."""
    if not HOLDOUT_INTERVALS.exists():
        raise FigureError(
            f"{HOLDOUT_INTERVALS.name} is missing — run the evaluation's analyse "
            f"phase first"
        )
    frame = pd.read_csv(HOLDOUT_INTERVALS)
    sub = frame[
        (frame["curve"] == "lear_full_history")
        & (frame["metric"] == metric)
        & (frame["block_days"] == HEADLINE_BLOCK)
    ]
    return sub[["zone", "point", "ci_low", "ci_high", "boot_sd"]].set_index("zone")


def preregistered_baseline() -> dict[str, dict[str, float]]:
    rec = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    return rec["baseline_2024_for_comparison"]


# ---------------------------------------------------------------------------
# The figures
# ---------------------------------------------------------------------------


def _style(zone: str) -> dict[str, Any]:
    style: dict[str, Any] = dict(marker="o", ms=3.5, lw=1.4)
    if zone == OUTLIER_ZONE:
        style.update(color="black", lw=2.2, zorder=5)
    return style


def plot_capture_by_year(out_dir: Path) -> Path:
    """Capture per zone, 2020-2025, with the holdout year set apart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cells = comparable_cells("capture_rolled_oracle_cash")
    zones = sorted(cells["zone"].unique())
    years = sorted(cells["year"].unique())
    if HOLDOUT_YEAR not in years:
        raise FigureError(
            "the store carries no 2025 comparable-arm capture row: the holdout "
            "evaluation's ingest phase has not run"
        )

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    ax.axvspan(HOLDOUT_YEAR - 0.5, HOLDOUT_YEAR + 0.5, color="#f0efe6", zorder=0)
    for zone in zones:
        sub = cells[cells["zone"] == zone].sort_values("year")
        visible = sub[sub["year"] != HOLDOUT_YEAR]
        line, = ax.plot(visible["year"], visible["value"], label=zone, **_style(zone))
        held = sub[sub["year"] == HOLDOUT_YEAR]
        if held.empty:
            continue
        # The out-of-sample point is hollow and detached: a filled marker on a
        # continuous line would read as a sixth visible year.
        ax.plot(held["year"], held["value"], marker="o", ms=6.5, mfc="white",
                mec=line.get_color(), mew=1.8, lw=0, zorder=6)
        ax.plot([visible["year"].max(), HOLDOUT_YEAR],
                [visible[visible["year"] == visible["year"].max()]["value"].iloc[0],
                 held["value"].iloc[0]],
                lw=1.0, ls=(0, (3, 2)), color=line.get_color(), zorder=4)
    ax.set_xticks(years)
    ax.set_xlabel("evaluation year")
    ax.set_ylabel("capture ratio (settled / rolled oracle cash)")
    ax.grid(alpha=0.25, lw=0.5)
    ax.annotate(
        f"{HOLDOUT_YEAR}: sealed holdout,\nevaluated once (273 days,\nends at the "
        f"15-min cutover)",
        xy=(HOLDOUT_YEAR, ax.get_ylim()[0]), xytext=(-4, 8),
        textcoords="offset points", ha="right", va="bottom", fontsize=7.5,
        color="#4a4a45",
    )
    ax.legend(ncol=5, fontsize=7.5, frameon=False, loc="lower center",
              bbox_to_anchor=(0.5, -0.30))
    fig.suptitle(
        "C17: the captured share of perfect-foresight value, nine zones, "
        "2020-2025\n(the comparable LEAR on price and calendar features; NO2 in "
        "black; hollow markers are the out-of-sample year)",
        fontsize=9)
    fig.tight_layout(rect=(0, 0.06, 1, 0.90))
    fig.text(0.005, -0.04, ATTRIBUTION, fontsize=7, color="#5a5a55")
    path = out_dir / "c17_capture_by_year.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_holdout_vs_baseline(out_dir: Path) -> Path:
    """2025 against the 2024 number the pre-registration recorded."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    baseline = preregistered_baseline()
    capture = comparable_cells("capture_rolled_oracle_cash")
    cash = comparable_cells("dispatch_cash_eur_per_mw_year")
    bounds = holdout_interval("capture_rolled_oracle_cash")
    zones = sorted(baseline)

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.2))
    held_capture, want_capture, lo, hi = [], [], [], []
    held_cash, want_cash = [], []
    for zone in zones:
        row = capture[(capture["zone"] == zone) & (capture["year"] == HOLDOUT_YEAR)]
        cash_row = cash[(cash["zone"] == zone) & (cash["year"] == HOLDOUT_YEAR)]
        if row.empty or cash_row.empty:
            raise FigureError(f"no 2025 comparable-arm row for {zone}")
        held_capture.append(float(row["value"].iloc[0]))
        want_capture.append(float(baseline[zone]["capture_rolled_oracle_cash"]))
        held_cash.append(float(cash_row["value"].iloc[0]))
        want_cash.append(float(baseline[zone]["dispatch_cash_eur_per_mw_year"]))
        if zone in bounds.index:
            lo.append(float(bounds.loc[zone, "ci_low"]))
            hi.append(float(bounds.loc[zone, "ci_high"]))
        else:
            lo.append(np.nan)
            hi.append(np.nan)

    y = np.arange(len(zones))
    ax = axes[0]
    ax.errorbar(held_capture, y,
                xerr=[np.array(held_capture) - np.array(lo),
                      np.array(hi) - np.array(held_capture)],
                fmt="o", ms=5, lw=0, elinewidth=1.2, capsize=2.5,
                color="#1f4e79", label=f"{HOLDOUT_YEAR} holdout (95% block bootstrap)")
    ax.plot(want_capture, y, marker="|", ms=12, lw=0, color="#b5651d",
            label="2024, pre-registered before the unseal")
    ax.set_yticks(y)
    ax.set_yticklabels(zones, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("capture ratio")
    ax.grid(alpha=0.25, lw=0.5, axis="x")
    ax.legend(fontsize=7.5, frameon=False, loc="lower left")

    ax = axes[1]
    delta = np.array(held_cash) - np.array(want_cash)
    ax.barh(y, delta, color=["#1f4e79" if d >= 0 else "#8c2f1f" for d in delta],
            height=0.6)
    ax.axvline(0.0, color="black", lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels([])
    ax.invert_yaxis()
    ax.set_xlabel("EUR/MW/yr, 2025 minus pre-registered 2024")
    ax.grid(alpha=0.25, lw=0.5, axis="x")

    fig.suptitle(
        "C17: the 2025 holdout beside the 2024 baseline written down before it "
        "was unsealed\n(left: captured share, with the holdout's own daily-block "
        "interval; right: the cash difference, which is a different year's prices "
        "as much as a different year's forecast)",
        fontsize=9)
    fig.tight_layout(rect=(0, 0.02, 1, 0.88))
    fig.text(0.005, -0.02, ATTRIBUTION, fontsize=7, color="#5a5a55")
    path = out_dir / "c17_holdout_vs_baseline.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_headroom_out_of_sample(out_dir: Path) -> Path:
    """FINDING C13-D's relationship, with the six unseen cells drawn on top."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    capture = comparable_cells("capture_rolled_oracle_cash")
    headroom = comparable_cells("error_over_headroom")
    cells = capture.merge(headroom, on=["zone", "year"],
                          suffixes=("_capture", "_headroom"))
    visible = cells[cells["year"] != HOLDOUT_YEAR]
    held = cells[cells["year"] == HOLDOUT_YEAR]
    if held.empty:
        raise FigureError("no 2025 cells: the ingest phase has not run")

    fig, ax = plt.subplots(figsize=(6.8, 4.6))
    ax.scatter(visible["value_headroom"], visible["value_capture"], s=22,
               color="#b9b9b2", edgecolor="none",
               label=f"2020-2024 ({len(visible)} cells, visible)")
    for _, row in held.iterrows():
        colour = "black" if row["zone"] == OUTLIER_ZONE else "#1f4e79"
        ax.scatter(row["value_headroom"], row["value_capture"], s=52,
                   facecolor="white", edgecolor=colour, linewidth=1.8, zorder=5)
        ax.annotate(str(row["zone"]),
                    xy=(row["value_headroom"], row["value_capture"]),
                    xytext=(5, 3), textcoords="offset points", fontsize=7.5,
                    color=colour)
    ax.scatter([], [], s=52, facecolor="white", edgecolor="#1f4e79", linewidth=1.8,
               label=f"{HOLDOUT_YEAR} ({len(held)} cells, out of sample)")

    usable = visible.dropna(subset=["value_headroom", "value_capture"])
    rho_visible = (
        usable["value_headroom"].corr(usable["value_capture"], method="spearman")
        if len(usable) > 2 else float("nan")
    )
    held_usable = held.dropna(subset=["value_headroom", "value_capture"])
    rho_held = (
        held_usable["value_headroom"].corr(held_usable["value_capture"],
                                           method="spearman")
        if len(held_usable) > 2 else float("nan")
    )
    ax.set_xlabel("error_over_headroom  (pooled MAE / mean realised daily spread)")
    ax.set_ylabel("capture ratio")
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(fontsize=7.5, frameon=False, loc="upper right")
    ax.annotate(
        f"Spearman rho: {rho_visible:+.3f} over the visible cells, "
        f"{rho_held:+.3f} within 2025",
        xy=(0.02, 0.03), xycoords="axes fraction", fontsize=7.5, color="#4a4a45")
    fig.suptitle(
        "C17: the one cross-regime relationship that survived five years, tested "
        "on a sixth it never saw\n(FINDING C13-D: capture falls as forecast error "
        "rises relative to the spread there is to trade)",
        fontsize=9)
    fig.tight_layout(rect=(0, 0.02, 1, 0.90))
    fig.text(0.005, -0.02, ATTRIBUTION, fontsize=7, color="#5a5a55")
    path = out_dir / "c17_headroom_out_of_sample.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# The phase
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir) if args.out_dir else FIGURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    written = [
        plot_capture_by_year(out_dir),
        plot_holdout_vs_baseline(out_dir),
        plot_headroom_out_of_sample(out_dir),
    ]
    summary = {
        "cycle": "C17",
        "phase": "figures",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "figures": [p.name for p in written],
        "attribution": ATTRIBUTION,
        "reads": [
            "backtest/results/results.csv (the append-only store)",
            HOLDOUT_INTERVALS.name,
            PREREGISTRATION.name,
        ],
        "writes_no_result_rows": True,
        "note": (
            "this module draws committed numbers and computes no result; the "
            "capture ratios, intervals and headroom values are the ones the "
            "evaluation phases wrote and the store carries."
        ),
    }
    with SUMMARY.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    for path in written:
        print(f"  -> {path}")
    print(f"  -> {SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
