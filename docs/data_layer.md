# Data layer (C1)

How day-ahead prices get from Energy-Charts onto disk, and what the committed
manifest guarantees. Written in C1; the *contract tests* over this data are C2.

## Layout

```
config/zones.yaml        9 bidding zones: tier, Energy-Charts bzn code,
                         ENTSO-E EIC domain, IANA local_tz, regime label
config/data.yaml         splits, sealed-holdout declaration + unseal marker,
                         fetch_years, source endpoints/licences, time contract
config/features.yaml     target, price-history / calendar / exogenous features,
                         each with its leakage status; plus what is excluded
data/config.py           config loading + validation, config_hash()
data/holdout.py          the sealed-holdout guard (see below)
data/energy_charts.py    /price client, fetch-once cache, strict validation
data/manifest.py         per-(zone, year) summary rows, CSV + JSON writers
data/fetch_prices.py     CLI: python -m data.fetch_prices
data/build_manifest.py   CLI: python -m data.build_manifest
data/raw/energy_charts/price/<ZONE>/<YEAR>.json   raw cache (gitignored)
data/manifest/prices_manifest.{csv,json}          committed manifest
```

## The sealed holdout is enforced in code, not by memory

`data/holdout.py` refuses any fetch or load of a year listed in
`config/data.yaml` → `splits.holdout.years` (currently 2025) unless
`PROGRESS.md` contains this exact line:

```
CHECKPOINT C APPROVED: 2025 holdout unsealed
```

Only a human writes that line, after Checkpoint C (C16). The guard sits in
`fetch_year`, `read_cached_year` and therefore in the manifest builder too, so
a sealed year cannot enter the pipeline by accident — and a stray sealed-year
cache file makes `build_manifest` raise rather than quietly include it. There is
a tripwire test asserting the marker is *absent* from `PROGRESS.md`
(`test_repo_progress_file_does_not_yet_unseal_the_holdout`).

`config/data.yaml` also refuses to load if `fetch_years` ever overlaps the
sealed years, so the seal can't be undone by a config edit alone.

## Fetch-once cache

One request per `(zone, year)`; the result is stored as the raw JSON exactly as
returned, plus a `_fetch_meta` block (URL, UTC fetch timestamp, HTTP status,
licence, attribution). If the file exists, `fetch_year` makes **no request at
all** and returns `(path, False)`.

There is deliberately **no force-refetch flag**: ENTSO-E and Energy-Charts both
throttle abusive clients, and re-pulling is a human act (delete the file on
purpose). See CLAUDE.md.

## Unexpected responses are flagged, never worked around

`validate_payload` accepts only the documented `/price` schema
(`unix_seconds` / `price` lists of equal non-zero length, strictly increasing
integer epochs, numeric-or-null prices, unit `EUR / MWh`, not `deprecated`).
Anything else raises `UnexpectedResponse`. A 404 or any other 4xx raises
immediately without retrying and without trying an alternate endpoint. Only
transport errors, 429 and 5xx are retried (3 attempts, 5/15/45s backoff), after
which `FetchFailed` is raised. Nothing is caught by a bare `except`, and a
payload that fails validation is never written to the cache.

`data/fetch_prices.py` turns a per-pair failure into a `FLAG` line on stderr
plus an entry in `data/manifest/fetch_failures.json`, skips only that pair,
carries on with the rest, and exits non-zero — so a partial pull can't be
mistaken for a complete one.

## Time handling

The API returns `unix_seconds` (UTC epoch), parsed straight to a tz-aware UTC
index; no local-time arithmetic happens in the data layer at all. `local_tz`
exists only to derive the explicit local hour-of-day feature column later.

`expected_points(year, resolution)` is computed from the UTC year length, so it
is exactly 8760 / 8784 hourly intervals — UTC years have no DST discontinuity.
Local-clock 23h/25h days are a feature/presentation concern, handled by the C2
DST whitelist assertions, never by reindexing or filling here.

## Request-window convention (resolved at C1b, 2026-09-30)

A year `Y` is requested as `start=Y-01-01&end=Y-12-31` and the parsed result is
then truncated to `[Y-01-01T00:00Z, Y+1-01-01T00:00Z)`. The request never names
a date outside `Y`, which is what keeps the holdout guard simple — a fetch of
2024 cannot ask the API for 2025.

**Observed answer, from the completed 54-pair pull:** `end` is inclusive of the
whole day, but the window is interpreted in the bidding zone's **local** time,
not UTC. Energy-Charts returns exactly one full *local* year:
`[Y-01-01T00:00 local, Y-12-31T23:00 local]` = 8760 points (8784 in a leap
year). All nine zones in scope are CET/CEST, so in UTC every raw file spans
`[Y-1-12-31T23:00Z, Y-12-31T22:00Z]`.

Two consequences, both benign and both surfaced by the manifest rather than
hidden:

1. Per-UTC-year truncation drops exactly the one leading point that belongs to
   `Y-1` — hence `n_out_of_window_dropped == 1` on all 54 rows — and the final
   UTC hour of year `Y` (`Y-12-31T23:00Z`) is absent from row `Y` because it was
   never in the `Y` window. It is present in file `Y+1`. So
   `coverage_ratio == 8759/8760 == 0.999886` uniformly is an artefact of
   per-UTC-year windowing, **not** missing data.
2. The union of a zone's cached files is contiguous and gap-free. Verified for
   all nine zones: one unbroken hourly series, uniform 3600s deltas, no interior
   gaps, no NaN, spanning `2018-12-31T23:00Z .. 2024-12-31T22:00Z`.

**Requirement for C2's loader (satisfied in C2 — see `docs/data_contracts.md`):**
build the continuous UTC series by
concatenating the per-year files and de-duplicating on timestamp — do *not*
reindex or fill per-year to 8760. The first hour of UTC year `Y` is in file `Y`;
the last hour of UTC year `Y` is in file `Y+1`.

**Holdout interaction — read before "completing" 2024.** The last hour of UTC
2024, `2024-12-31T23:00Z`, lives only in the 2025 file, and 2025 is SEALED.
The usable UTC span therefore ends at **`2024-12-31T22:00Z`** and a cycle must
**never** fetch 2025 to close that one-hour tail. This costs one hour out of
~52,600 and is irrelevant to the hourly backtest, whose window ends 2025-09-30
anyway. `data/holdout.py` already refuses the fetch; this note exists so no
future cycle mistakes the tail for a bug worth "fixing".

Points returned outside the requested year are dropped **by timestamp, never by
value**, and counted in `n_out_of_window_dropped`.

## Manifest columns

One row per `(zone, year)`: identity (`zone`, `tier`, `bzn`, `year`); shape
(`n_points`, `n_expected_points`, `coverage_ratio`, `resolution_seconds`,
`n_distinct_deltas`, `n_gap_intervals`, `max_gap_hours`, `n_nan`,
`n_out_of_window_dropped`, `first_ts_utc`, `last_ts_utc`); price summary
(`price_min`, `price_p01`, `price_mean`, `price_median`, `price_p99`,
`price_max`, `price_std`, `n_negative`, `n_zero`); provenance (`raw_bytes`,
`payload_sha256` — a reproducible hash of the `(UTC epoch, price)` pairs, see
`docs/data_contracts.md`, not of the cached file — `fetched_at_utc`, `api_url`).

The JSON form adds `generated_at_utc`, `git_sha`, `config_hash`,
`sealed_holdout_years`, source and licence attribution.

`resolution_seconds` is the modal spacing; `n_distinct_deltas > 1` is how the
2025-10-01 hourly→15-minute cutover will show up, which C2 asserts on directly.

## Attribution

Day-ahead prices: **Energy-Charts (Fraunhofer ISE), CC BY 4.0**. ENTSO-E
Transparency Platform attribution is added in C7 when that client lands.
