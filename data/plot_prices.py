"""CLI: per-zone day-ahead price figures for the Checkpoint A review.

    python -m data.plot_prices
    python -m data.plot_prices --zones DE-LU

Writes PNGs to ``docs/figures/``. Reads only the local cache, never the network.

What each figure is for, and why it is drawn this way:

* ``prices_<ZONE>.png`` — one zone's whole series. The daily **mean** is the line;
  the daily **min-max band** behind it is the intraday range, which is the
  quantity a battery actually earns from. Plotting 52,608 hourly points as a line
  would be a solid block of ink at this width, so the hourly detail is summarised
  rather than dropped — and a one-week hourly inset keeps the raw shape visible.
* ``prices_all_zones.png`` — nine small multiples on **one shared y-axis**, so
  cross-zone level differences are readable as height rather than needing a
  per-panel axis read.
* ``negative_hours.png`` — negative-price hours per year per zone: the thing
  Checkpoint A is meant to sanity-check against market history, and a direct
  driver of battery value.

Colour: one hue for data (blue), red reserved for the 0 EUR/MWh reference and the
negative-price counts, grid and axes recessive. Single-series panels carry no
legend — the panel title names the series.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless container: no display, write files only
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from data.config import REPO_ROOT, load_data_config, load_zones  # noqa: E402
from data.energy_charts import PRICE_COLUMN, cached_years  # noqa: E402
from data.prices import load_zone_series  # noqa: E402

FIGURE_DIR = REPO_ROOT / "docs" / "figures"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
SERIES = "#2a78d6"
NEGATIVE = "#e34948"
GRID = "#d8d7d2"

ATTRIBUTION = "Data: Energy-Charts (Fraunhofer ISE), CC BY 4.0"


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_SOFT,
            "axes.titlecolor": INK,
            "text.color": INK,
            "xtick.color": INK_SOFT,
            "ytick.color": INK_SOFT,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 9,
            "figure.dpi": 130,
        }
    )


def _daily(frame: pd.DataFrame) -> pd.DataFrame:
    """Daily mean/min/max over *fully covered* UTC days (never local — CLAUDE.md).

    The stitched series starts at 23:00Z on 31 December of the year before the
    first cached file, so its first UTC day holds a single hour. Plotting that as
    a day would put a meaningless one-point spike at the left edge, so partial
    days at either end are dropped from the figure (they are still reported by
    the contract layer as ``boundary_partial_days``).
    """
    grouped = frame[PRICE_COLUMN].groupby(frame.index.date)
    daily = grouped.agg(["mean", "min", "max"])
    daily["n"] = grouped.size()
    expected = int(daily["n"].mode().iloc[0])
    daily = daily[daily["n"] == expected].drop(columns="n")
    daily.index = pd.to_datetime(daily.index)
    return daily


def plot_zone(zone_key: str, frame: pd.DataFrame, out_dir: Path) -> Path:
    """One zone: daily mean + intraday min-max band, with a one-week hourly inset."""
    zone = load_zones()[zone_key]
    daily = _daily(frame)

    fig, (ax, inset) = plt.subplots(
        2, 1, figsize=(10, 6), height_ratios=[3, 1], constrained_layout=True
    )

    ax.fill_between(
        daily.index, daily["min"], daily["max"],
        color=SERIES, alpha=0.20, linewidth=0, label="daily min-max",
    )
    ax.plot(daily.index, daily["mean"], color=SERIES, linewidth=1.0, label="daily mean")
    ax.axhline(0.0, color=NEGATIVE, linewidth=0.9, linestyle="--", alpha=0.85)
    ax.annotate(
        "0 EUR/MWh", xy=(1.0, 0.0), xycoords=("axes fraction", "data"),
        xytext=(4, 0), textcoords="offset points",
        color=NEGATIVE, fontsize=7.5, va="center", ha="left",
    )
    ax.set_title(
        f"{zone_key} day-ahead price, {daily.index[0]:%Y-%m-%d} to {daily.index[-1]:%Y-%m-%d} "
        f"(Tier {zone.tier}, {zone.regime or 'n/a'})",
        loc="left", fontsize=11,
    )
    ax.set_ylabel("EUR/MWh")
    ax.legend(frameon=False, loc="upper left", fontsize=8, labelcolor=INK_SOFT)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # A representative winter week at full hourly resolution, so the reviewer can
    # see the raw shape the daily summary above is built from.
    week_end = frame.index[-1]
    week_start = week_end - pd.Timedelta(days=7)
    week = frame.loc[week_start:week_end, PRICE_COLUMN]
    inset.plot(week.index, week.values, color=SERIES, linewidth=1.0)
    inset.axhline(0.0, color=NEGATIVE, linewidth=0.9, linestyle="--", alpha=0.85)
    inset.set_title(
        f"last 7 days, hourly ({week_start:%Y-%m-%d} to {week_end:%Y-%m-%d} UTC)",
        loc="left", fontsize=9, color=INK_SOFT,
    )
    inset.set_ylabel("EUR/MWh")
    inset.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))

    inset.annotate(ATTRIBUTION, xy=(0.0, -0.42), xycoords="axes fraction",
                   fontsize=7, color=INK_SOFT, va="top")
    path = out_dir / f"prices_{zone_key}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_all_zones(panel: dict[str, pd.DataFrame], out_dir: Path) -> Path:
    """Nine small multiples on one shared y-axis: levels comparable by height."""
    keys = list(panel)
    ncols = 3
    nrows = -(-len(keys) // ncols)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(12, 2.4 * nrows), sharex=True, sharey=True,
        constrained_layout=True,
    )
    dailies = {key: _daily(panel[key]) for key in keys}

    # One shared y-axis makes levels comparable, but a single 2988 EUR/MWh print
    # (FR, 2022 nuclear outages) would squash all nine panels into the bottom
    # eighth of the frame. Clip to a robust range and say so on the figure —
    # the full extremes are in the manifest and on the per-zone figures.
    pooled = pd.concat([d[["min", "max"]].stack() for d in dailies.values()])
    low, high = float(pooled.quantile(0.0005)), float(pooled.quantile(0.9995))
    low, high = min(low, -50.0), max(high, 100.0)
    n_clipped = int((pooled < low).sum() + (pooled > high).sum())

    flat = axes.ravel()
    for ax, zone_key in zip(flat, keys):
        daily = dailies[zone_key]
        ax.fill_between(daily.index, daily["min"], daily["max"], color=SERIES,
                        alpha=0.20, linewidth=0)
        ax.plot(daily.index, daily["mean"], color=SERIES, linewidth=0.8)
        ax.axhline(0.0, color=NEGATIVE, linewidth=0.7, linestyle="--", alpha=0.8)
        zone = load_zones()[zone_key]
        ax.set_title(f"{zone_key} — Tier {zone.tier}, {zone.regime or 'n/a'}",
                     loc="left", fontsize=9)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.set_ylim(low, high)
    for ax in flat[len(keys):]:
        ax.set_visible(False)
    for ax in axes[:, 0]:
        ax.set_ylabel("EUR/MWh")
    fig.suptitle(
        "Day-ahead price by bidding zone — daily mean and intraday min-max, "
        "shared y-axis, UTC\n"
        f"y-axis clipped to [{low:,.0f}, {high:,.0f}] EUR/MWh; "
        f"{n_clipped} daily extreme(s) fall outside and are off-scale "
        f"(true min/max per zone-year: data/manifest/prices_manifest.csv)",
        x=0.004, ha="left", fontsize=12,
    )
    axes[-1, 0].annotate(ATTRIBUTION, xy=(0.0, -0.34), xycoords="axes fraction",
                         fontsize=7, color=INK_SOFT, va="top")
    path = out_dir / "prices_all_zones.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_negative_hours(panel: dict[str, pd.DataFrame], out_dir: Path) -> Path:
    """Negative-price hours per (zone, UTC year) — small multiples, shared y-axis."""
    keys = list(panel)
    counts: dict[str, pd.Series] = {}
    for zone_key, frame in panel.items():
        prices = frame[PRICE_COLUMN]
        by_year = (prices < 0).groupby(frame.index.year).sum()
        counts[zone_key] = by_year[by_year.index >= by_year.index.min() + 1]

    ncols = 3
    nrows = -(-len(keys) // ncols)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(11, 2.2 * nrows), sharex=True, sharey=True,
        constrained_layout=True,
    )
    flat = axes.ravel()
    for ax, zone_key in zip(flat, keys):
        series = counts[zone_key]
        ax.bar([str(y) for y in series.index], series.values, color=NEGATIVE,
               width=0.62)
        for x, value in zip(range(len(series)), series.values):
            ax.annotate(str(int(value)), (x, value), ha="center", va="bottom",
                        fontsize=7, color=INK_SOFT)
        ax.set_title(zone_key, loc="left", fontsize=9)
    for ax in flat[len(keys):]:
        ax.set_visible(False)
    for ax in axes[:, 0]:
        ax.set_ylabel("hours < 0")
    fig.suptitle(
        "Negative-price hours per UTC calendar year (counts labelled)",
        x=0.004, ha="left", fontsize=12,
    )
    axes[-1, 0].annotate(ATTRIBUTION, xy=(0.0, -0.30), xycoords="axes fraction",
                         fontsize=7, color=INK_SOFT, va="top")
    path = out_dir / "negative_hours.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="*", default=None)
    parser.add_argument("--years", nargs="*", type=int, default=None)
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_data_config()
    zones = load_zones()
    out_dir = Path(args.out_dir) if args.out_dir else FIGURE_DIR

    selected = args.zones or list(zones)
    unknown = [z for z in selected if z not in zones]
    if unknown:
        print(f"unknown zone key(s): {unknown}", file=sys.stderr)
        return 2
    if sum(len(cached_years(z, cfg)) for z in selected) == 0:
        print("no cached price files found — run `python -m data.fetch_prices` first.",
              file=sys.stderr)
        return 3

    _style()
    out_dir.mkdir(parents=True, exist_ok=True)
    panel = {z: load_zone_series(z, args.years, cfg) for z in selected
             if cached_years(z, cfg)}

    written = [plot_zone(z, frame, out_dir) for z, frame in panel.items()]
    written.append(plot_all_zones(panel, out_dir))
    written.append(plot_negative_hours(panel, out_dir))

    for path in written:
        print(f"  {path.relative_to(REPO_ROOT)}  ({path.stat().st_size // 1024} KB)")
    print(f"\n{len(written)} figures -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
