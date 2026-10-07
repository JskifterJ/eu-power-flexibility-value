# The ENTSO-E exogenous layer (C7)

Tier-A exogenous features — day-ahead load, wind and solar forecasts for DE-LU,
ES and NO2 — from the ENTSO-E Transparency Platform. This is the companion to
`docs/data_layer.md` (Energy-Charts prices) and `docs/data_contracts.md` (the C2
price contracts).

**C7 fetches, validates, describes and contracts this data. No model consumes it
yet.** Building these columns into LEAR is C8's work, and PLAN.md requires the
RES-forecast degradation sensitivity to land in the same cycle.

Attribution: *Data: ENTSO-E Transparency Platform* (reuse conditions require
attribution). The security token is read from `ENTSOE_API_KEY` and never
written to disk, a log line or an exception — see "Token hygiene" below.

## What is fetched

| Document | Type/Process | Columns | `leakage_status` |
|---|---|---|---|
| Art. 6.1.B day-ahead total load forecast | A65 / A01 | `load_forecast_da_mw` | **safe** |
| Art. 14.1.D day-ahead wind & solar forecast | A69 / A01 | `wind_forecast_da_mw`, `solar_forecast_da_mw` | **FLAGGED** |
| derived | — | `residual_load_forecast_mw` | **FLAGGED** (inherited) |

Three zones × three years (2022–2024) × two documents = 18 requests, one per
`(zone, document, year)`. 2019–2021 are excluded in code, not just in prose: the
platform answers for them, but PLAN.md records that no archived D-1 forecast
vintage exists before 2022, so `sources.entsoe.exogenous_available_from_year`
bounds it and `fetch_year` refuses anything earlier.

### Why wind and solar are FLAGGED

The Art. 14 D-1 forecast is published at 18:00 on D-1 — **after** day-ahead gate
closure for delivery day D — and is revised intraday. The archived vintage is
therefore *not* what a bidder had when they bid. It is fetched because C8 needs
it for the mandatory degradation sensitivity (as-published vs
persistence-degraded), and the flag travels with the data: every frame carries
`attrs['leakage_status']` and `attrs['flagged_columns']`, and every committed
artefact has a `leakage_status` column. The Art. 6 load forecast is published at
latest 2h *before* gate closure, so it is genuinely safe.

`residual_load_forecast_mw` = load − wind − solar is FLAGGED by inheritance, two
of its three inputs being the Art. 14 vintage. An hour missing any input is NaN,
never a partial subtraction — a residual load computed from load alone would
read as a huge residual and become the largest outlier in the C14 chapter.

## The two things that would silently corrupt this series

### 1. `curveType A03` — sparse positions with block semantics

**Every** response observed in C7 is `curveType A03`, a *variable-sized block*
curve. Positions are sparse, and an omitted position means **"the previous
point's value still holds"**. Real DE-LU solar, 2024-01-01, PT15M:

```xml
<Point><position>1</position><quantity>0</quantity></Point>
<Point><position>29</position><quantity>52.58</quantity></Point>
```

Positions 2–28 are absent and mean *zero*, not *missing*. Parsing
position-by-row would yield a 26-row "day" full of holes; parsing it as a dense
index would shift every value after the gap. `data.entsoe.expand_points`
implements the block semantics and the C7 tests pin it against hand-computed
sparse curves. `A01` (fixed-size sequence, every position present) is also
accepted and requires every position; any other curve type is a FLAG.

NO2's solar forecast for a whole year is a **single point of `0.0`** — which is
correct, and is only correct under A03.

### 2. A TSO can change resolution mid-series

DE-LU publishes both documents at PT15M, NO2 at PT60M, and **ES switched from
PT60M to PT15M on 2022-05-23T00:00Z**. `data.aggregate.to_hourly` documents a
single input resolution and takes the modal one, so run over the stitched ES
series it treated the whole PT60M stretch — 3408 hours of real data — as partial
hours and NaN'd them.

The fix is to carry each row's **true** interval length out of the parser
(`attrs['interval_seconds']`, taken from its own `<Period>`) rather than infer it
from index spacing. A delta-based guess cannot tell a resolution change from a
gap: the row before a one-hour hole in a PT15M series has a 4500s forward delta.
`data.exogenous` then splits the series into maximal runs of constant resolution
and hands each to `to_hourly` on its own — which is exactly the uniform input
that function is specified for, so `data/aggregate.py` (the C2 aggregation method
and its tests) stays untouched.

The same correction applies to the manifest: coverage is measured as **time
covered / time in the year**, and a gap is a step longer than the *preceding
row's own* interval. Against the modal resolution, ES 2022 read as 70.8% covered
with 3409 gaps; measured properly it is 99.9886% covered with **one** real
missing hour.

## Hourly aggregation

An hour survives only if its rows' interval lengths sum to exactly 3600s **and**
none of them is NaN. `to_hourly` means with pandas' default `skipna`, so an hour
with three real quarter-hours and one NaN would otherwise come back as the mean
of the three — a number that looks real and is not. An hour that does not tile
exactly raises by default, or becomes NaN under `on_partial="flag"`.

The method itself is `data/aggregate.py`'s one documented rule: the unweighted
mean of the sub-hourly values in each UTC hour, which for an equal-duration MW
quantity is the correct average power over the hour. It is **not** volume
weighted and cannot be.

## Summing psrTypes: NaN for a missing fleet, zero for a non-existent one

`wind_forecast_da_mw` is `B18 + B19` (offshore + onshore). Where only *some*
components cover an interval the sum is **NaN**, never a partial total.

Two real cases from C7 pull in opposite directions, and the data itself decides
between them:

- **DE-LU 2023 and 2024.** On 2023-10-28 and 2024-10-26 the German publication
  for onshore wind (B19) and solar (B16) splits into two Periods around a missing
  `22:00Z–23:00Z`, while offshore wind (B18) runs straight through. That instant
  is 00:00 local on the **25-hour autumn DST day**: publication for the long day
  starts an hour late for two of the three psrTypes. Four quarter-hours →
  **NaN**. Treating the absent onshore component as zero would understate wind by
  tens of GW.
- **NO2, every year.** Offshore wind B18 is published for just 48 hours of 2022
  and 192 of 2024, is absent from 2023 altogether, and is `0.0` at *every*
  published point. NO2 has no offshore fleet; the TSO emits an occasional
  all-zero stub. Treating that absence as NaN would wipe out the wind feature for
  a whole Tier-A zone on the strength of a stub.

So: a component that is **identically zero wherever it is published** is not a
fleet, and its absence contributes zero. The test is asserted against the payload
rather than assumed, and which components it caught is recorded in
`attrs['zero_components']` and in the contract report, so a human can overrule it.
Overlapping Periods that *disagree* still raise — that is a contradiction, not a
gap.

## Contracts: integrity fails, completeness is reported

`data/exog_contracts.py` **adds to** the contract layer rather than editing
`data/contracts.py`: CLAUDE.md forbids touching a data-contract or
leakage-assertion file without flagging and stopping first, and the C2 tests pin
that module. Every primitive check (`gap_report`, `check_utc_day_counts`,
`check_local_day_counts`, `dst_transition_days`, …) is imported and reused.

The dividing line, stated once:

- **Integrity findings are violations** — a non-UTC or non-monotonic index,
  duplicate timestamps, a negative value in a quantity that cannot be negative,
  or a day holding *more* rows than it should (which can only come from duplicate
  or misaligned timestamps, i.e. a bug of ours).
- **Completeness findings are reported notes** — gaps, NaNs, and a day holding
  *fewer* rows than it should. These series are genuinely ragged, CLAUDE.md's
  answer to a source gap is to flag it and skip only the dependent work, and this
  project never fills a gap. Failing here would discard whole training years over
  one known hour a year while telling a human nothing the gap count already says.
  A shortfall and a gap are the same fact counted twice, which is why only one is
  a failure.

Two checks the price contract cannot express:

- **Non-negativity**, config-driven per series. A day-ahead load or RES forecast
  below zero is a source defect — unlike a *price*, where negative is a real
  market outcome. **`residual_load_forecast_mw` is the deliberate exception and
  the sign is the whole point of it**: residual load goes negative exactly when
  wind + solar exceed load, which is the condition that drives negative prices
  and the subject of PLAN.md's C14 chapter. Flagging it would flag the signal.
- **The SDAC 15-minute cutover rule does not apply.** A resolution change in a
  TSO's own forecast publication is reported, not a violation.

## Known source gaps (C7, complete list)

All reported, none filled. Worst case ~0.4% of a zone-year.

| Zone / document | Missing | What it is |
|---|---|---|
| DE-LU load | 2022-02-22, 2022-03-24 | 24h each — two whole local days absent |
| DE-LU load | 2023-10-28, 2024-10-26 | 1h each — first hour of the 25-hour DST day |
| DE-LU wind & solar | 2023-10-28, 2024-10-26 | 1h each, NaN — partial psrType coverage, same DST hour |
| ES (both documents) | 2022-10-30 | 1h — first hour of the 25-hour DST day |
| ES solar | 2024-12-07 … 12-11 | 120h NaN — partial psrType coverage |
| ES wind | 2024-06-02 | 24h NaN — partial psrType coverage |
| NO2 wind & solar | 2022-11-01 … 11-02 | 48h — two whole local days absent |

The recurring autumn-DST hour is the one to carry into the write-up's Limits
section: it is a structural property of these publications, not a one-off.

## Token hygiene

ENTSO-E authenticates with a `securityToken` query parameter, so unlike
Energy-Charts the request URL is a secret. Everything that could carry it goes
through `data.entsoe.redact` first, which removes both the literal token and any
`securityToken=...` parameter:

- the cached provenance sidecar stores `url_redacted`, with
  `securityToken=<REDACTED>`;
- `document_request()` returns params **without** the token, which is added only
  at request time;
- every exception message and every CLI FLAG line is redacted, including
  transport errors that quote the URL.

`api_key_is_set()` tests presence only and never reads the value. If the key is
absent, `data.fetch_exogenous` prints one FLAG and exits 4 without a request —
per CLAUDE.md the cycle then continues with whatever does not depend on it.

## The sealed holdout, asserted rather than argued

ENTSO-E's `periodEnd` is the **exclusive** end of the window, so fetching
calendar year `Y` must name `(Y+1)-01-01T00:00Z`. That is the only spelling that
returns the year's last interval: verified in C7, an end of `Y-12-31T23:00`
returns 92 of that day's 96 quarter-hours.

Naming that boundary is not an observation of year `Y+1`. Rather than rely on
that argument, `parse_document` asserts **positively** that no returned timestamp
falls in a sealed year — so if the platform ever did return a point past the
boundary while fetching 2024, it raises instead of caching it. The ordinary
`assert_not_sealed` guard still runs before any request and before any cached
read.

## Cache layout and politeness

```
data/raw/entsoe/<document_key>/<ZONE>/<YEAR>.xml.gz        raw XML, gzipped
data/raw/entsoe/<document_key>/<ZONE>/<YEAR>.meta.json     provenance, redacted URL
```

Gitignored, like all of `data/raw/`. Gzipped because a year of DE-LU A69 is
~13 MB of XML (~0.7 MB compressed); the whole 18-file cache is ~3.5 MB.

**Never re-downloaded.** `fetch_year` returns the cached path untouched if the
file exists, and there is deliberately no `--force` flag: refetching is a human
act (delete the file on purpose). This matters more here than for Energy-Charts
because ENTSO-E throttles abusive tokens. One request per `(zone, document,
year)`, 3s apart, retrying transport errors and 429/5xx only.

A window larger than one year is rejected by the platform with HTTP 400 and an
`Acknowledgement_MarketDocument` carrying `Reason` code 999 — which is exactly
how a FLAG should look, and is never retried or worked around.

## Committed artefacts

```
data/manifest/exogenous_manifest.csv            one row per (zone, document, series, year)
data/manifest/exogenous_manifest.json           + provenance (git SHA, config hash, licence)
data/manifest/exogenous_contract_report.csv     one row per (zone, series)
data/manifest/exogenous_contract_report.json    + every finding and note
```

## CLIs

```bash
python -m data.fetch_exogenous --dry-run        # show what would be requested
python -m data.fetch_exogenous                  # Tier A, 2022-2024, both documents
python -m data.build_exog_manifest              # cache -> manifest
python -m data.build_exog_contracts             # cache -> contract report
```

Exit codes follow the C1/C2 convention: a per-pair failure is a FLAG line, that
pair is skipped, the rest still run, and the process exits non-zero so a cycle
cannot mistake a partial pull for a complete one.

## Plausibility of the pulled data

Worth an eyeball, since these are the first exogenous numbers in the project:

| Series | Range (2022–2024, hourly) | Sense check |
|---|---|---|
| DE-LU load | 30.9 – 76.5 GW | German peak load ~80 GW ✓ |
| DE-LU wind | 0.2 – 50.4 GW | German wind record ~50 GW ✓ |
| DE-LU solar | 0 – 48.6 GW | German solar record ~48–50 GW ✓ |
| DE-LU residual load | **−13.6** – 68.7 GW | negative at sunny/windy midday ✓ |
| ES load | 16.8 – 38.7 GW | Spanish peak ~40 GW ✓ |
| ES wind | 0.3 – 19.8 GW | ~30 GW installed ✓ |
| ES solar | 0 – 21.2 GW | ✓ |
| NO2 load | 2.1 – 6.4 GW | ✓ |
| NO2 wind | 0 – 1.3 GW | NO2 onshore ~1.5 GW ✓ |
| NO2 solar | identically 0 | no solar fleet ✓ |
