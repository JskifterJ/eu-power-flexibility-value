# Data contracts (C2)

What the price data is *asserted* to be, how those assertions are executed, and
what the committed artefacts mean. C1 (`docs/data_layer.md`) got the data onto
disk; C2 is the layer that refuses to let bad data through silently.

Nothing in this layer ever repairs data. Every function reports; `assert_contract`
turns a report into an exception. A gap stays a gap, a short day stays short. That
is the point: silently reindexing to the expected shape is the failure mode these
contracts exist to catch, and it is invisible in a diff.

## Modules

```
data/prices.py           stitches the per-year cache into one continuous UTC series
data/contracts.py        the contracts themselves + the derived DST whitelist
data/aggregate.py        sub-hourly -> hourly, one documented method
data/build_contracts.py  CLI: python -m data.build_contracts
data/plot_prices.py      CLI: python -m data.plot_prices
tests/test_c2_contracts.py   42 offline tests over all of the above
```

Committed artefacts:

```
data/manifest/contract_report.csv    one row per zone, human-eyeballable
data/manifest/contract_report.json   full detail, every violation spelled out
data/manifest/dst_whitelist.csv      the derived 23h/25h local-day calendar
docs/figures/prices_<ZONE>.png       per-zone price series (9)
docs/figures/prices_all_zones.png    nine small multiples, shared y-axis
docs/figures/negative_hours.png      negative-price hours per zone-year
```

## Stitching: why the loader does not reuse `read_cached_year`

`read_cached_year` trims each cached file to its own UTC calendar year, which is
right for a per-year manifest row and wrong for a modelling series. Energy-Charts
interprets the request window in the **zone's local time** (NOTE C1-02), so file
`Y` spans UTC `[Y-1-12-31T23:00Z, Y-12-31T22:00Z]` for the CET/CEST zones in
scope. Trimming every file to its own UTC year would leave a one-hour hole at
**every** year boundary, because `Y-12-31T23:00Z` is in file `Y+1`.

`data/prices.py` therefore parses each file untruncated
(`energy_charts.parse_payload`), concatenates, sorts, and de-duplicates on
timestamp. Duplicates are collapsed only when the files agree on the price; a
genuine disagreement raises rather than picking one. The sealed-holdout guard is
applied per year before any file is opened.

Result, verified for all nine zones: one contiguous hourly series,
`2018-12-31T23:00Z .. 2024-12-31T22:00Z`, 52,608 points, uniform 3600s deltas,
no gaps, no NaN, no duplicates.

## The contracts

| # | Contract | Where |
|---|----------|-------|
| 1 | index is tz-aware **UTC**, strictly monotonic, no duplicate timestamps | `index_is_utc`, `build_contract_report` |
| 2 | every fully-covered **UTC** day holds exactly `86400/resolution` rows | `check_utc_day_counts` |
| 3 | every fully-covered **local** day holds its DST-derived expected count | `check_local_day_counts` |
| 4 | any local day that is not 24h falls on a tz-database transition date | `dst_transition_days` |
| 5 | no gaps (missing intervals) anywhere in the stitched series | `gap_report` |
| 6 | no NaN prices | `build_contract_report` |
| 7 | the only permitted resolution change is 3600s -> 900s at the SDAC go-live | `check_resolution_cutover` |

### UTC days and local days are different contracts, deliberately

A UTC day always holds 24 hourly intervals — UTC has no DST — so a UTC-day count
that isn't 24 is unambiguously a data defect. A *local* calendar day holds 23, 24
or 25 hours, so its expected count comes from a whitelist.

**The whitelist is derived, not hardcoded.** `dst_transition_days(tz, years)` walks
the tz database and returns every local date that is not 24 hours long. So it
cannot drift from reality, and it works in both directions: a 23-hour local day on
the last Sunday in March passes; a 23-hour local day on an ordinary Tuesday is a
violation. That second direction is the one that matters — an hour of real data
quietly dropped must never be excused as "probably DST".

All nine zones are CET/CEST and share one transition calendar (asserted by a test,
so adding a non-CET zone fails loudly rather than silently reusing the wrong one).
Over 2019-2024 that is 12 transition days per zone, 126 rows in
`dst_whitelist.csv` (including the 2018 boundary day each series starts on).

### Days at the edge of the series are not counted as violations

The stitched series starts at 23:00Z, so its first UTC day holds one hour.
Completeness is decided from the expected interval *timestamps*, not by assuming
the first and last day are partial — for these CET zones the local-day view is
complete at both ends, and those days are still checked. Genuinely partial days
are listed as `boundary_partial_days` rather than reported as short.

### Gaps vs resolution changes

A missing hour and a market-time-unit change both show up as an unexpected delta,
and conflating them would either hide missing data or flag the 15-minute cutover
as a 2,000-hour gap. `resolution_segments` run-length-encodes the spacing;
`detect_resolution_changes` ignores runs shorter than two intervals (a lone long
delta is a gap, not a change) and merges same-resolution neighbours, so hourly /
missing-hour / hourly reports a **gap**, not a 3600s -> 3600s "change".
`gap_report` measures each step against the resolution in force on either side of
it, so a legitimate cutover contributes zero missing intervals.

### The 15-minute cutover

SDAC moved the day-ahead market time unit from 60 to 15 minutes on **2025-10-01**.
That is a market *day*, so the cutover instant is **local midnight** of that date
in the zone's own timezone — `2025-09-30T22:00Z` for a CEST zone, not UTC
midnight. `check_resolution_cutover` permits exactly one change, 3600s -> 900s, at
that instant; a change at any other time, or between any other pair of
resolutions, is a violation.

No 2025 data is touched to test this. The detector is exercised on synthetic
indices in `tests/test_c2_contracts.py`; the real series ends 2024-12-31 and shows
`n_resolution_changes = 0`, as it must.

## Hourly aggregation — the method, stated

The hourly price for UTC hour *h* is the **unweighted arithmetic mean** of the
sub-hourly prices whose interval starts inside *h*. Sub-hourly intervals are equal
in duration, so this is the correct duration-weighted average.

**It is not volume-weighted, and cannot be.** A VWAP needs cleared volume per
interval; the Energy-Charts `/price` payload carries prices only, and no volume
series is fetched anywhere in this project. `to_hourly` accepts an explicit
`volume` argument so the machinery exists if a volume source is ever added, but
nothing supplies one. The write-up must say "duration-weighted mean of 15-minute
prices", never "VWAP".

Partial hours are never silently averaged: an hour holding fewer intervals than
the resolution implies raises by default (`on_partial="flag"` keeps it as NaN and
records it). The grouping key is the UTC hour; local time is never a resampling
key.

**Interpretation caveat for the write-up's Limits section:** aggregating 15-minute
prices to hourly destroys within-hour spread, so a battery's realisable value is
*higher* at native 15-minute granularity than the aggregated series implies.
Aggregated post-cutover results understate flexibility value and must never be
pooled with pre-cutover hourly results as if they were the same measurement.

## `payload_sha256`

`contracts.payload_fingerprint` hashes only the `(UTC epoch, price)` pairs at
fixed 6-decimal precision, reported as `payload_sha256` per zone here and in
the manifest. Two pulls of the same (zone, span) agree iff the source really
returned the same prices.

**History (Checkpoint A, NOTE C2-01, fixed):** the manifest originally had its
own `raw_sha256` column that hashed the cached **file** instead. That file
embeds the `_fetch_meta.fetched_at_utc` stamp this project writes, so the
column changed on every re-fetch even when the data was identical — useless as
an integrity check, and confusingly named besides, since nothing about it was
reproducibly "raw". The manifest now calls this same `payload_fingerprint`
function and reports it under the same `payload_sha256` name as here, so the
two artefacts can never drift apart again.

## Running it

```bash
python -m data.build_contracts        # exit 0 = all contracts hold, 1 = violations
python -m data.plot_prices            # figures into docs/figures/
python -m pytest tests/ -q
```

`build_contracts` writes the report **even when contracts fail** — a violation is
evidence, not a reason to write nothing — and exits 1 so a pipeline stops.

## Attribution

Day-ahead prices: **Energy-Charts (Fraunhofer ISE), CC BY 4.0**.
