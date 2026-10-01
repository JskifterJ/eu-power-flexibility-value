"""Market days, gate closure, and when a price actually became public.

Everything downstream of this module exists to answer one question honestly:
**what did a bidder know at the moment they had to bid?** Get that wrong by one
hour and every metric in the project is optimistic, in a way no plot will show.

The three instants that matter, all derived here and nowhere else:

``market_day(h)``
    The delivery day a given hour belongs to — the auction's own unit, the
    *local* calendar date of the hour in the zone's local timezone. All nine
    zones in scope are CET/CEST, but the function takes the zone's tz rather
    than assuming it.

``gate_closure(D)``
    12:00 Europe/Brussels on ``D-1``: the instant bids for delivery day ``D``
    must be in. 11:00Z in winter, 10:00Z in summer.

``publication(D)``
    When day ``D``'s cleared prices became public — ~12:42-13:00 CET on ``D-1``,
    i.e. **after** gate closure for that same day ``D``.

From which the only rule this project needs follows:

    at ``gate_closure(D)`` a bidder knows every hourly price of market days
    ``<= D-1`` and **no** hourly price of day ``D``.

That is a statement about *market days*, not UTC days or raw hour offsets, and
the difference is not cosmetic. Two consequences that bite, both found by the
C3 guard rather than by reasoning:

* A plain ``t - 24h`` lag reaches into the target's **own** market day on the
  25-hour local day each autumn (the hour-index-24 row): ``t - 24h`` lands on
  that day's first hour. One leaking cell per zone per year.
* A "mean over the UTC day before the target" reaches into the target's own
  market day on **every** row, because for a CET zone UTC day ``D-1`` ends at
  ``D-1 23:00Z``, which is local midnight on day ``D`` — market day ``D``'s
  first hour. See :mod:`forecast.features`.

Local time is used here only to *label* market days and to resolve the gate
closure wall-clock. No series is ever resampled, reindexed or aligned on local
time (CLAUDE.md); grouping and arithmetic stay in UTC.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pandas as pd

from data.config import load_data_config, load_zones

ONE_DAY = dt.timedelta(days=1)


class TimingError(RuntimeError):
    """A timing convention could not be resolved, or was asked for nonsense."""


@dataclass(frozen=True)
class GateClosureConvention:
    """The day-ahead auction clock, read from ``config/data.yaml``.

    ``gate_local_time`` and ``publication_local_time`` are wall-clock times in
    ``tz``, both on ``D-1`` for delivery day ``D``. Only their *order* matters
    to the guard, which is asserted on construction: a convention in which
    results are published before gate closure would silently make leaking
    features look legal.
    """

    tz: str
    gate_local_time: dt.time
    publication_local_time: dt.time

    def __post_init__(self) -> None:
        if not self.publication_local_time > self.gate_local_time:
            raise TimingError(
                f"publication {self.publication_local_time} must be strictly after "
                f"gate closure {self.gate_local_time}: day-ahead results for "
                f"delivery day D are published AFTER bids for day D close. A "
                f"convention violating that would legalise leaking features."
            )


def _parse_hhmm(value: Any, field: str) -> dt.time:
    text = str(value).strip()
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
        return dt.time(hour=hour, minute=minute)
    except (ValueError, TypeError) as exc:
        raise TimingError(f"{field} is not an HH:MM wall-clock time: {value!r}") from exc


@lru_cache(maxsize=None)
def gate_closure_convention(config_dir: Any = None) -> GateClosureConvention:
    """The committed day-ahead clock. Cached; config is immutable within a run."""
    dates = load_data_config(config_dir).get("structural_dates") or {}
    for required in (
        "day_ahead_gate_closure_local",
        "day_ahead_gate_closure_tz",
        "day_ahead_results_published_local",
    ):
        if required not in dates:
            raise TimingError(
                f"config/data.yaml structural_dates is missing {required!r} — the "
                f"gate-closure leakage guard cannot run without it"
            )
    return GateClosureConvention(
        tz=str(dates["day_ahead_gate_closure_tz"]),
        gate_local_time=_parse_hhmm(dates["day_ahead_gate_closure_local"], "gate closure"),
        publication_local_time=_parse_hhmm(
            dates["day_ahead_results_published_local"], "results publication"
        ),
    )


def zone_timezone(zone_key: str) -> str:
    """The zone's IANA timezone — used to label market days, never to resample."""
    zones = load_zones()
    if zone_key not in zones:
        raise TimingError(f"unknown zone key {zone_key!r}; known: {sorted(zones)}")
    return zones[zone_key].local_tz


def _local_wall_clock_to_utc(day: dt.date, time: dt.time, tz: str) -> pd.Timestamp:
    """``time`` on ``day`` in ``tz``, as a UTC instant.

    Both wall-clock times this project uses (12:00 and 13:00) sit far from any
    DST transition, so neither is ambiguous or non-existent; ``tz_localize``
    raises rather than guessing if that ever stops being true.
    """
    naive = pd.Timestamp(dt.datetime.combine(day, time))
    return naive.tz_localize(tz, ambiguous="raise", nonexistent="raise").tz_convert("UTC")


def market_days(index: pd.DatetimeIndex, tz: str) -> pd.Series:
    """Delivery-day label for each UTC timestamp: its local calendar date.

    Returned as an ``object``-dtype Series of :class:`datetime.date`, indexed by
    the original UTC index. Dates, not timestamps, because a market day is a
    label on an auction, not an instant.
    """
    if index.tz is None:
        raise TimingError("market_days requires a tz-aware (UTC) index")
    local = index.tz_convert(tz)
    return pd.Series(list(local.date), index=index, dtype="object", name="market_day")


def gate_closure_utc(
    day: dt.date, convention: GateClosureConvention | None = None
) -> pd.Timestamp:
    """UTC instant at which bids for delivery ``day`` close: 12:00 local on ``D-1``."""
    conv = convention or gate_closure_convention()
    return _local_wall_clock_to_utc(day - ONE_DAY, conv.gate_local_time, conv.tz)


def publication_utc(
    day: dt.date, convention: GateClosureConvention | None = None
) -> pd.Timestamp:
    """UTC instant at which delivery ``day``'s cleared prices became public."""
    conv = convention or gate_closure_convention()
    return _local_wall_clock_to_utc(day - ONE_DAY, conv.publication_local_time, conv.tz)


def _map_days(days: pd.Series, fn) -> pd.Series:
    """Apply a per-day instant function over a market-day Series, memoised.

    A year of hourly rows holds only ~365 distinct days; computing the instant
    once per distinct day and mapping keeps this out of the hot path.
    """
    distinct = pd.unique(days.dropna())
    lookup = {day: fn(day) for day in distinct}
    mapped = days.map(lookup)
    return pd.to_datetime(mapped, utc=True)


def gate_closure_for(days: pd.Series, convention: GateClosureConvention | None = None) -> pd.Series:
    """Vectorised :func:`gate_closure_utc` over a market-day Series."""
    conv = convention or gate_closure_convention()
    out = _map_days(days, lambda day: gate_closure_utc(day, conv))
    out.name = "gate_closure_utc"
    return out


def publication_for(days: pd.Series, convention: GateClosureConvention | None = None) -> pd.Series:
    """Vectorised :func:`publication_utc` over a market-day Series."""
    conv = convention or gate_closure_convention()
    out = _map_days(days, lambda day: publication_utc(day, conv))
    out.name = "published_utc"
    return out


def price_available_at(
    index: pd.DatetimeIndex, tz: str, convention: GateClosureConvention | None = None
) -> pd.Series:
    """When each hourly price in ``index`` became public knowledge.

    This — not the timestamp of the hour itself — is the information time of any
    feature derived from that hour. ``price_available_at`` is what makes the
    leakage guard able to see that "yesterday's 23:00Z price", for a CET zone, is
    *today's* market day and therefore not knowable at today's gate closure.
    """
    return price_available_at_days(market_days(index, tz), convention)


def price_available_at_days(
    days: pd.Series, convention: GateClosureConvention | None = None
) -> pd.Series:
    """:func:`price_available_at` when market-day labels are already computed."""
    return publication_for(days, convention)


def is_available_at_gate_closure(
    information_time: pd.Series, gate_closure: pd.Series
) -> pd.Series:
    """Boolean: was this information public by the row's own gate closure?

    ``NaT`` information time means "carries no market information" (a calendar
    feature) and is **not** treated as available here — callers decide, so that
    an undeclared ``NaT`` can never pass the guard by accident.
    """
    return information_time.notna() & (information_time <= gate_closure)
