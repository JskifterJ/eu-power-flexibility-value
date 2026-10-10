# C14 — the fundamentals chapter: price against residual load, Tier A

`backtest/run_c14_fundamentals.py` (new), `tests/test_c14_fundamentals.py` (new).
Artefacts: `backtest/results/c14_cache_verification.json`,
`c14_merit_order_deciles.csv`, `c14_explanatory_power.csv`,
`c14_supply_curve_slopes.csv`, `c14_negative_price_mechanism.csv`,
`c14_residual_load_sufficiency.csv`, `c14_fundamentals_summary.json`,
`c14_headroom_daily.csv.gz`, `c14_headroom_cells.csv`,
`c14_headroom_correlations.csv`, `c14_headroom_summary.json`, the 2023 ladder
files, and the rows appended to `backtest/results/results.csv`.
Figures: `docs/figures/c14_merit_order_tier_a.png`,
`c14_negative_price_by_decile.png`, `c14_headroom_vs_res_revision.png`.

PLAN.md C14: *"Fundamentals chapter: price vs residual load (load − wind −
solar) per Tier-A zone, merit-order commentary."* Plus the two notes C13 handed
forward: **NOTE C13-03** (does residual-load forecast error explain
`error_over_headroom`?) and **NOTE C13-04 / NOTE C8-01** (the 2023 exogenous
ladder, which needs the same ENTSO-E pull this chapter needs).

---

## 1. The honesty problem this cycle has, and does not have

Every cycle from C3 to C13 asked *what could a bidder have known at gate
closure*. This one asks *what set the price*. That is a different question, and
it changes which vintage is allowed.

The Art. 14 wind/solar D-1 forecast is published at 18:00 local on D-1 — **six
hours after** day-ahead gate closure (`docs/exogenous_model.md`). That is why C8
built the `res_persistence` degradation and why `res_as_published` travels only
as a labelled measurement of a leak. It makes the series unusable as a **model
input**. It does **not** make it unusable as a **description** of the delivery
day: it is the closest thing in PLAN.md's declared scope to realised wind and
solar, and nothing in this chapter is fitted or scored as a forecast.

So the line is drawn in code, not in prose:

- `FUNDAMENTALS_VINTAGE = "after_gate_closure"` is on every artefact and **every
  store row** this cycle writes descriptively. `honest_rows()` therefore excludes
  all of them, which is the right default for a results table.
- `assert_descriptive_only()` is a callable that **raises**. A later cycle that
  imports `fundamentals_frame` and hands the result to a feature builder gets a
  refusal naming the publication clock, not a silent leak.
- The descriptive rows go in under the **oracle's** `(model, exog_variant)`
  identity, because there is no forecast behind an R² of the realised price on
  residual load. Filing them under a model's key would make them join to that
  model's MAE as if they described it.

**The limitation, stated plainly and not engineered around:** the residual load
behind every figure here is a *forecast* of residual load, not a measurement of
it. The fix would be an ENTSO-E **actuals** pull (A65/A16 realised load, A75
realised generation per type), and that is outside PLAN.md's declared data scope
— Tier A gets the two D-1 forecast documents and nothing else. C18's Limits
section inherits this.

### 1.1 The cache, verified byte-for-byte

`data/raw/` did not survive the container again — **NOTE C2-02, 25th
recurrence** — so all 54 price files and all 18 ENTSO-E documents were
re-pulled: `downloaded=54 already_cached=0 flagged=0` and `downloaded=18
already_cached=0 flagged=0`.

C13 compared six summary statistics against the committed manifest. This cycle
compares the **`payload_sha256` the manifest committed**, which is the only
comparison that cannot be passed by accident — two series with the same mean,
min and max are not the same series:

| cache | units | fingerprints identical to the committed manifest |
|---|---|---|
| Energy-Charts prices (C1's manifest) | 54 zone-years | **54 / 54** |
| ENTSO-E D-1 forecasts (C7's manifest) | 27 series rows, 18 documents | **27 / 27** |

Two details that make this a real check rather than a decorative one, both of
which were got wrong on the first attempt and caught by the check failing loudly:

- **It is a fingerprint of the *data*, not of the file.** The cached file embeds
  a `_fetch_meta.fetched_at_utc` stamp, so a file hash changes on every re-fetch
  even when the prices are identical — which is precisely the column the
  Checkpoint-A decision removed (**NOTE C2-01**). The verification calls the
  manifest's own `data.contracts.payload_fingerprint` and
  `data.exog_manifest.series_fingerprint`, which cover the `(UTC epoch, value)`
  pairs at fixed precision and nothing else, so a difference means the source
  returned different numbers.
- **The exogenous fingerprint is per *series*, not per document.** The A69
  document carries wind and solar, with a different hash each, so a check keyed
  on `(zone, document, year)` would find two candidate values and have to pick
  one. All 27 series rows are checked.

A changed fingerprint on the ENTSO-E side would mean the platform had revised an
archived D-1 vintage, which would invalidate C8's and C9's measured vintage
premium — so it is a FLAG, not a tolerance. Neither manifest was regenerated or
re-committed (C8/C9/C10/C13's precedent).

---

## 2. How "merit order" is measured here

Short-run marginal cost rises with residual load: zero-marginal-cost wind and
solar and must-run clear first, then lignite, coal, gas, oil. That makes the
price-against-residual-load curve the **empirical supply curve** of the zone,
and three of its properties are falsifiable:

1. **Convexity** — the slope at high residual load should exceed the slope
   through the middle, because the marginal unit climbs a steepening stack.
2. **Level shifts, not shape changes** — a fuel-cost shock raises the money axis
   and leaves the quantity axis alone, so 2022 should sit far above 2023/24 at
   matched residual load *while keeping its shape*.
3. **The floor fails downward** — below some residual load the stack runs out of
   units willing to turn down and the price goes negative, which should pile the
   negative hours into the bottom of the residual-load distribution.

### 2.1 Five specifications, two of them nested on purpose

`explanatory_power()` reports five in-sample fits per (zone, year). Two
comparisons are **nested**, which is what makes the "gain" columns mean anything:

| fit | parameters | what it is |
|---|---|---|
| `linear` | 2 | price on residual load |
| `binned_20` | 20 | a 20-quantile-bin step function — the fit the decile figure draws |
| `piecewise_linear_20` | 40 | intercept **and slope** per bin; **nests `linear`** |
| `calendar_only` | 30 | hour-of-day + weekday dummies, **additively** — the control |
| `residual_load_plus_calendar` | 68 | the piecewise block + the same dummies; **nests `calendar_only`** |

Two methodological points, both of which bit during this cycle and are recorded
rather than smoothed over:

- **The step function is not an upper bound.** It discards the variation *inside*
  each bin, so on a smooth relationship it scores *below* the straight line. On a
  synthetic exactly-linear zone it returns 0.995, not 1.0, and **DE-LU 2024 is
  the real case** (`binned_20` 0.596 against `linear` 0.601). Reading
  `r2_binned_20` as "the best residual load can do" understates the merit order
  wherever the relationship is smooth — a conservative error, and therefore the
  kind that survives review. `r2_piecewise_linear_20` is the column without that
  defect, and it is the headline. `discretisation_loss_of_the_step_fit` reports
  the gap (up to **0.079** on DE-LU 2024).
- **The calendar block is additive, not a saturated interaction.** An
  hour × weekday × bin interaction would be ~3 400 cells on ~8 760 hours, about
  2.6 observations each, and its in-sample R² would be a statement about the cell
  count. `n_parameters_*` is reported for every fit so the in-sample caveat is a
  number a reader can check rather than a disclaimer.

Every R² here is in-sample by construction and is a descriptive share of
variance, never skill.

### 2.2 The three figures, and the axis choices they make

- **`c14_merit_order_tier_a.png`** — the empirical supply curve, one panel per
  zone, one decile-median line per year over the pooled hourly cloud. The
  **price axis is shared** across the three panels, because §5 compares price
  *levels* across zones and three independent axes would make a 143 EUR/MWh line
  and a 316 EUR/MWh line look alike. The **residual-load axes are not** shared:
  NO2 spans 2-6 GW and DE-LU −13 to 69, and forcing those together reduces NO2
  to a smear. The price axis is symlog (linear within ±50, log outside) and
  clipped to −150..1000; the full range runs to −500 and +936 on a handful of
  hours, and letting those set the axis spends two thirds of the panel on them.
  The clipped hours are **counted in §6**, not hidden.
- **`c14_negative_price_by_decile.png`** — `P(price < 0)` by residual-load
  decile, shared y-axis. This is the figure §6 is about and the contrast is
  visible without reading a number: DE-LU and ES spike in decile 1 and collapse
  to zero by decile 3; NO2 is a low, slowly-declining line across all ten.
- **`c14_headroom_vs_res_revision.png`** — two rows, because §8's answer has two
  halves. Top: the day's RES revision against its error-over-headroom (NOTE
  C13-03 as asked). Bottom: the day's residual-load range against its realised
  price spread (the half that carries FINDING C14-F). A **binned decile-median
  line** is drawn over each cloud — 1 090 scattered days is a blob and a rank
  correlation of +0.5 cannot be read off one, so without the line the figure
  would be asking the reader to take the table on trust. The contrast between
  the two rows in the NO2 column is the mechanism.

---

## 3. FINDING C14-A — the merit order is a DE-LU and ES fact, and barely an NO2 one

`r2_piecewise_linear_20`, price on D-1 forecast residual load, with the
clock-only control beside it:

| zone | 2022 | 2023 | 2024 | calendar-only (2022/23/24) | gain over the clock (2022/23/24) |
|---|---|---|---|---|---|
| **DE-LU** | 0.406 | **0.802** | **0.675** | 0.130 / 0.233 / 0.220 | +0.285 / **+0.586** / +0.470 |
| **ES** | 0.264 | 0.650 | 0.555 | 0.096 / 0.238 / 0.168 | +0.177 / +0.432 / +0.424 |
| **NO2** | **0.044** | 0.361 | 0.323 | 0.042 / 0.066 / 0.089 | +0.051 / +0.332 / +0.282 |

NO2 is last in every year, on the raw R² **and** on the gain over a clock, and
the gap is a factor of 2.0-2.2 against DE-LU in 2023/24 and a factor of **9** in
2022. The Spearman ordering is the same: DE-LU +0.90/+0.85, ES +0.79/+0.74, NO2
+0.59/+0.56 (2023/2024).

**And the crisis year degrades the relationship everywhere**: 0.41 / 0.26 / 0.04
in 2022 against 0.68 / 0.56 / 0.32 in 2024. The stack did not change in 2022; its
fuel cost did, violently and within the year, so residual load stopped pinning
the price *level* even where it still pinned the ordering. That is the same fact
FINDING C13-F found from the dispatch side (the crisis multiplied the prize and
left the captured share alone) measured on a fundamental.

---

## 4. FINDING C14-B — NO2's supply curve slopes the wrong way in 2022

Decile medians, NO2, price in EUR/MWh against D-1 forecast residual load in GW:

| decile | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| residual load (GW) | 2.3 | 2.6 | 2.8 | 3.0 | 3.2 | 3.4 | 3.7 | 4.0 | 4.3 | 4.8 |
| **2022** price | **219.3** | 198.3 | 190.0 | 190.6 | 189.9 | 189.2 | 178.7 | 174.4 | 151.3 | **143.4** |
| 2023 price | 58.6 | 69.9 | 73.0 | 75.2 | 77.5 | 76.4 | 89.8 | 97.3 | 102.4 | 120.4 |
| 2024 price | 35.1 | 39.5 | 40.8 | 43.8 | 44.3 | 47.9 | 49.1 | 52.5 | 58.4 | 86.2 |

In 2022 NO2's price **falls** as residual load rises: Spearman **−0.177**, and
the three measured slopes are **−39.1 / −17.6 / −31.4 EUR/MWh per GW**. It is the
only (zone, year) in the table with a negative sign.

**A merit order cannot slope down.** A hydro reservoir's opportunity cost can: in
a water-scarce, export-constrained year the price is set by the reservoir's
shadow value and the export arbitrage against the Continent, not by a domestic
thermal stack — and NO2's domestic "stack" is 4 GW of load against 0.5 GW of
wind and **no solar fleet at all** (its Art. 14 solar forecast is a single point
of 0.0 for a whole year; see `docs/entsoe_layer.md`). Hours of high domestic
residual load in 2022 were hours when the Continent was *not* short, so NO2
exported less and priced lower.

This is a **mechanism for the project's largest open puzzle.** FINDING C11-B
found NO2 the capture outlier; FINDING C12-C proposed "the forecast puts the
hours in the wrong order"; FINDING C13-E killed the rival thin-spread story; and
FINDING C13-C confirmed NO2 is last on within-day ordering in all five years.
§6 closes the loop quantitatively.

---

## 5. FINDING C14-C — the crisis moved the level and kept the shape

At the **median residual-load decile**, which holds the quantity axis fixed:

| zone | 2022 → 2023 level | 2022 → 2024 level | shape ρ (decile medians) | normalised-curve Pearson | max normalised gap |
|---|---|---|---|---|---|
| DE-LU | ×0.465 | **×0.381** | 1.000 | **0.998** | 0.233 |
| ES | ×0.555 | **×0.372** | 0.988 | **0.974** | 0.660 |
| NO2 | ×0.408 | ×0.233 | **−0.988** | **−0.898** | 1.190 |

So in the two zones with a real merit order, 2022 priced at **2.6-2.7× 2024 at
the same residual load** while the normalised decile curve correlates 0.97-1.00:
**shifted, not bent.** That is the signature a fuel-cost shock should leave, and
it is a cross-check on FINDING C13-F from the other direction — C13 measured the
perfect-foresight battery earning ×1.72-2.71 its usual in 2022; this measures the
price level at matched fundamentals at ×2.6-2.7.

NO2's negative shape correlation is **the same fact as FINDING C14-B**, not a
second one: its curve inverted, so of course it anti-correlates with itself.

Rank correlation alone cannot distinguish a shift from a steepening — any two
monotone curves rank-correlate at 1 — which is why the normalised comparison is
reported beside it, and why a synthetic test pins both behaviours.

**What no model in this project has:** the fuel-cost axis. PLAN.md excluded the
AGSI+ gas-storage proxy for being weak and sign-unstable (`docs/audit.md`), so
the single largest driver of the 2022 price *level* is absent from every arm by
design. FINDING C13-F says that cost little in capture terms; this says why a
point-forecast MAE in 2022 looks as bad as it does.

---

## 6. FINDING C14-D — negative prices are a bottom-decile event, except in NO2

The merit-order reading of a negative price is specific: wind and solar have
pushed residual load so low that the units still running would rather pay than
cycle off. If that is the mechanism, the negative hours must pile up at the
bottom. **10% is the number to compare against** — the share a uniform spread
would put in the bottom decile.

| zone | year | negative hours | share in the bottom decile | ×uniform | highest residual load with a negative price |
|---|---|---|---|---|---|
| DE-LU | 2022 | 69 | 1.000 | **10.0×** | 15.2 GW |
| DE-LU | 2023 | 301 | 0.980 | **9.8×** | 14.1 GW |
| DE-LU | 2024 | 457 | 0.880 | **8.8×** | 19.7 GW |
| ES | 2022 | **0** | — | — | — |
| ES | 2023 | **0** | — | — | — |
| ES | 2024 | 237 | 0.882 | **8.8×** | 9.0 GW |
| **NO2** | 2022 | **0** | — | — | — |
| **NO2** | 2023 | 174 | **0.397** | **4.0×** | 3.3 GW |
| **NO2** | 2024 | 206 | **0.209** | **2.1×** | 4.1 GW |

DE-LU and ES sit at **8.8-10.0× uniform**: textbook. NO2 sits at **4.0× and
2.1×**, with only 21-40% of its negative hours in the bottom decile and 47-63% in
the bottom two — so **the majority of NO2's negative hours are not
low-residual-load hours**, and the 2024 figure only just clears a 2× bar while
DE-LU is at ~9×. A negative price in DE-LU is a merit-order event; in NO2 it is
mostly something else (local hydro/grid constraints and export-corridor
behaviour, which this project has no data for and will not guess at).

Two structural facts the table makes concrete, both of which refine C13's
negative-hour counts:

- **ES printed its first negative hour of the whole 2019-2024 window in 2024**
  (237 here over the exogenous-join hours, 247 over the full market year in
  C13's table). Before that the Iberian gas cap and the Iberian stack simply did
  not produce one — `config/zones.yaml` carries the cap as a structural note.
- **In no (zone, year) is a negative price more likely than not, even in the
  bottom decile.** DE-LU 2024 comes closest at **0.457**. So "negative prices
  are normal in the bottom decile" is not yet true anywhere in Tier A, which is
  worth knowing before a battery write-up leans on them.

---

## 7. FINDING C14-E — residual load is nearly a sufficient statistic, except in the crisis

The merit-order restriction is that only the *residual* matters: a GW of load and
a GW less wind are the same displacement, so a regression on the three components
should return `(+b, −b, −b)`. Two ways it can fail, both economically real.

`wind_plus_load_cancels` is `b_load + b_wind`, which the restriction sets to
zero. Intervals are the paired circular moving-block **day** bootstrap, 10 000
replicates, seed 20261010, block 1 day:

| zone | year | b_load | b_wind | b_solar | load+wind | 95% interval | R² lost by imposing residual load |
|---|---|---|---|---|---|---|---|
| DE-LU | 2022 | +4.92 | −9.13 | −4.94 | **−4.21** | [−5.17, −3.33] | **0.068** |
| DE-LU | 2023 | +3.27 | −2.93 | −3.25 | +0.35 | [+0.17, +0.52] | 0.004 |
| DE-LU | 2024 | +3.10 | −2.69 | −3.37 | +0.42 | [+0.20, +0.66] | 0.013 |
| ES | 2022 | +7.29 | −5.49 | −6.95 | +1.80 | [+0.03, +3.65] | 0.005 |
| ES | 2023 | +5.12 | −6.43 | −4.20 | −1.30 | [−2.00, −0.58] | 0.041 |
| ES | 2024 | +5.56 | −6.07 | −4.31 | −0.51 | [−1.29, +0.31] | 0.027 |
| NO2 | 2022 | −32.63 | −66.53 | n/a | **−99.16** | [−124.47, −74.55] | **0.094** |
| NO2 | 2023 | +24.41 | −36.91 | n/a | −12.50 | [−17.36, −7.51] | 0.019 |
| NO2 | 2024 | +23.06 | −22.56 | n/a | +0.50 | [−3.70, +4.54] | 0.000 |

(EUR/MWh per GW. NO2 has no solar fleet, so its solar coefficient is **not
identified** and is reported as such rather than as a fitted zero.)

- **In DE-LU 2023/24 the restriction is violated but trivially**: +0.35 and +0.42
  against a load coefficient of ~3.2, so ~11-13% of the coefficient, and only
  0.4-1.3pp of R² is lost by imposing it. Residual load is a good summary there.
- **In the crisis year it breaks.** DE-LU 2022: a GW of wind moved the price
  nearly **twice** as much as a GW of load (−9.13 against +4.92), and 6.8pp of R²
  is lost by collapsing them. At crisis gas prices a MW of wind displaced a MW of
  very expensive gas while a MW of extra load was partly met by cheaper inframarginal
  plant, so the two were genuinely not interchangeable.
- **NO2 2024 is the one cell where the restriction is *not* rejected** (+0.50
  [−3.70, +4.54], R² lost 0.00003) — residual load is sufficient there; it just
  does not explain much (§3).

**Do not compare the per-GW slopes across zones.** NO2's mean load is 4.1 GW and
DE-LU's is 53.2, so the same *relative* displacement is 13× the GW in DE-LU, and
NO2's 23 EUR/MWh/GW against DE-LU's 3.1 is that artefact and nothing else.
`coef_*_per_10pct_mean_load` is the comparable figure, and on it the three zones
are much closer: a 10%-of-mean-load displacement is worth **16.5 (DE-LU) / 14.7
(ES) / 9.5 (NO2)** EUR/MWh in 2024. A synthetic test pins this.

### 7.1 Solar and wind are not interchangeable, and they disagree by zone

`b_solar − b_wind`, with the same intervals:

| zone | 2023 | 2024 | reading |
|---|---|---|---|
| DE-LU | **−0.33** [−0.50, −0.17] | **−0.69** [−0.82, −0.55] | solar cannibalises **more** than wind |
| ES | **+2.23** [+1.65, +2.77] | **+1.76** [+1.14, +2.35] | **wind** cannibalises more than solar |

Both exclude zero at the daily block, in both years, and they point in opposite
directions. The reading that fits the fundamentals: solar arrives in a fixed
midday block, so in **solar-dominated ES** the marginal MW of solar lands in
hours already pushed to the bottom of the stack (and, from 2024, through zero),
where there is little price left to displace, while wind can arrive in any hour
and still finds a thermal unit on the margin. In DE-LU, with a smaller solar
share relative to its stack, the midday block is still landing on priced hours.
This is a two-year, two-zone observation with intervals, not an established
cross-zone law.

---

## 8. NOTE C13-03 — does residual-load forecast error explain `error_over_headroom`?

### 8.1 What is actually measurable, and the label that travels with it

`error_over_headroom` (FINDING C13-D) is **pooled price MAE ÷ mean realised
daily spread** — a ratio with a model in the numerator and a market in the
denominator. Both halves get their own question, because they have different
consequences for a desk: a bigger error is a worse model, a smaller spread is a
worse market.

**Two granularities, and they are not the same number.** FINDING C13-D's
definition is a *cell* statistic: one pooled MAE over one mean spread per (zone,
year), and that is what `c14_headroom_cells.csv` and §8.3 carry. A per-*day*
correlation needs a per-day value, which is that day's own
`MAE_d / spread_d` — the ratio of the day's figures, not the day's contribution
to the pooled one. The two agree in spirit and not in arithmetic (a ratio of
means is not a mean of ratios), so the per-day column is named the same thing
but computed per day, and §8.2's correlations are correlations of *that*. Days
with a non-positive realised spread are NaN rather than infinite, and are
dropped from the correlation rather than winsorised.

The predictor is the **day-over-day revision** of the as-published Art. 14
residual load: the mean over the day's hours of `|RL(h) − RL(h−24h)|`, computed
on the **UTC** index with a true 24-hour offset (not "yesterday's same local
hour", which is 23 or 25 hours twice a year).

**This is a revision, not a forecast error, and it is a lower bound on the
error a bidder carried.** The only stand-in for realised residual load available
inside PLAN.md's scope is itself a forecast, so the true D-1 error is larger than
what is measured here. It is also exactly the quantity C8's `res_persistence` arm
has to live with — a bidder at gate closure holds yesterday's RES publication and
nothing better — which is what makes it the relevant one rather than merely the
available one. `RES_ERROR_IS_A_REVISION` carries this on every row.

Nothing was refitted: the dispatch outcomes are C13's committed
`c13_daily_by_year.csv.gz` rows for the nine-zone comparable arm, so this is
arithmetically the `error_over_headroom` FINDING C13-D is about.

### 8.2 The answer: yes in DE-LU and ES, weakly in NO2, and not in the crisis year

Spearman over market days, 95% interval from the paired circular moving-block
day bootstrap (10 000 replicates, seed 20261010, block 1 day). **`*` = excludes
zero.**

| zone | outcome | 2022 | 2023 | 2024 |
|---|---|---|---|---|
| DE-LU | `error_over_headroom` | +0.139 [+0.03, +0.24]* | **+0.500** [+0.41, +0.58]* | **+0.481** [+0.39, +0.57]* |
| DE-LU | price MAE | +0.101 [−0.01, +0.21] | +0.487 [+0.40, +0.57]* | +0.431 [+0.34, +0.52]* |
| DE-LU | realised spread | +0.402 [+0.31, +0.48]* | **+0.593** [+0.52, +0.66]* | **+0.596** [+0.52, +0.67]* |
| ES | `error_over_headroom` | +0.108 [+0.00, +0.21]* | +0.341 [+0.25, +0.43]* | +0.357 [+0.27, +0.44]* |
| ES | price MAE | +0.288 [+0.19, +0.38]* | +0.394 [+0.30, +0.48]* | +0.387 [+0.29, +0.48]* |
| ES | realised spread | +0.618 [+0.54, +0.68]* | +0.578 [+0.50, +0.65]* | +0.352 [+0.25, +0.45]* |
| **NO2** | `error_over_headroom` | +0.078 [−0.03, +0.18] | +0.160 [+0.06, +0.26]* | +0.241 [+0.14, +0.34]* |
| **NO2** | price MAE | −0.032 [−0.14, +0.07] | +0.326 [+0.23, +0.42]* | +0.175 [+0.07, +0.28]* |
| **NO2** | **realised spread** | **+0.012** [−0.09, +0.11] | **+0.035** [−0.07, +0.14] | **+0.020** [−0.09, +0.12] |

Three readings:

1. **NOTE C13-03 is answered affirmatively, with a zone gradient.** A harder RES
   day is a harder day to capture in DE-LU (ρ ≈ +0.49 in 2023/24) and in ES
   (≈ +0.35), and the effect is 2-3× weaker in NO2 (+0.16/+0.24). So
   residual-load forecast error is *part* of what sits behind
   `error_over_headroom`, and the part is largest exactly where the merit order
   is strongest (§3) — which is the mechanism FINDING C13-D's ρ = −0.74 was
   missing.
2. **The crisis year breaks it again.** 2022 collapses to +0.14 / +0.11 / +0.08.
   In a year when the fuel axis moves more than the quantity axis, a RES revision
   stops being the thing that makes a day hard.
3. **The headline: NO2's daily price shape has no relationship to its
   residual-load shape.** The day's residual-load *range* against the day's
   realised price *spread* is +0.59/+0.60 in DE-LU and +0.35-0.62 in ES, and in
   NO2 it is **+0.012, +0.035, +0.020 — an interval containing zero in all three
   years, including the crisis.** This is a robust zero, not a noisy one.

#### Why NO2's hours cannot be ordered from its fundamentals

Two numbers from `c14_headroom_cells.csv`, side by side. The day's residual-load
**swing as a share of that zone-year's own mean residual load** — the comparable
figure, since NO2's mean residual load is 3.4-3.6 GW against DE-LU's 30.0:

| zone | 2022 | 2023 | 2024 |
|---|---|---|---|
| DE-LU | 0.64 | 0.81 | 0.90 |
| ES | 0.68 | 1.01 | 1.18 |
| **NO2** | **0.33** | **0.29** | **0.26** |

NO2's residual load barely moves within a day — a swing of about a quarter of its
own level, against most or all of it in DE-LU and ES — **and what movement there
is has no relationship to the price spread** (+0.01 to +0.04, intervals
containing zero). Both halves are needed: a small swing that still predicted the
spread would leave a weak but usable signal, and a large swing that predicted
nothing would be a different puzzle. NO2 has neither.

#### A sign reversal, and why it is not a scale artefact

Across the nine cells a RES predictor correlates **negatively** with
`error_over_headroom` — raw-MW revision ρ = **−0.67**, and after normalising by
each cell's own mean residual load, revision ρ = **−0.65** and daily range
ρ = **−0.72**. That is the opposite sign from every per-day within-cell
correlation in §8.2.

The first draft of this section called that a scale artefact. **It is not** —
normalising does not remove it, so the explanation has to be something else, and
it is that the two levels measure different things:

- **Between cells** the predictor is *structural RES penetration*. A zone-year
  whose residual load swings by 90% of its own level (DE-LU 2024) has a wide
  price spread and so a lot of headroom, which makes its error small *relative
  to* that headroom. Hence the negative sign, and note that ρ = −0.72 is the
  same sign and nearly the same size as FINDING C13-D's −0.74 for
  `error_over_headroom` against capture — the two are consistent.
- **Within a cell** the predictor is *forecast error on the day*. Holding the
  structure fixed, a day whose RES publication was revised more than usual is a
  harder day: ρ ≈ +0.49 (DE-LU), +0.35 (ES).

So the complete answer to NOTE C13-03 has two layers, both real and both
pointing the same economic way: **RES build-out creates the headroom, and RES
forecast error eats into it.** Neither layer can be read off the other, and the
nine-cell table carries this in its own `honest_label`.

Use the `*_over_mean` columns for any cross-zone sentence regardless: the raw-MW
predictors *are* also size proxies (NO2's mean residual load is 3.6 GW against
DE-LU's 30.0), which is the same per-GW trap §7 reports for the supply-curve
slopes.

**§8.2's third reading is the mechanism FINDING C12-C asked for.** NO2's
within-day ordering is the worst of the nine zones in all five years (FINDING
C13-C) and conditioning on the spread does not explain its capture deficit
(FINDING C13-E). §8.2 says why: the fundamental that orders the hours in DE-LU
and ES — the within-day swing in residual load — **does not order them in NO2 at
all**. A model built on price history and residual load has nothing to learn
NO2's within-day shape *from*. That is a fundamentals explanation for a dispatch
finding, and it predicts something C15 can check: no change to the throughput
cost, the battery duration or the SoC policy should fix NO2's ordering, because
the information is not in the inputs.

### 8.3 The cross-cell version is not established, and says so

FINDING C13-D is a cross-cell correlation over **44** (zone, year) cells. The
Tier-A exogenous window gives **9**. A rank correlation on nine points has a
sampling sd of roughly 0.38 under independence, so `cross_cell_headroom()`
reports its point estimates with an explicit **not established** label and no
interval. The per-day columns in §8.2 are where this cycle's power is; the
nine-cell table is reported because a reader will ask for it.

---

## 9. NOTE C13-04 / NOTE C8-01 — the 2023 exogenous ladder

The question NOTE C8-01 has been waiting on since C12 re-opened it is whether
the **honest** exogenous block is worth having under the booster *outside ES*,
and the answer needed a second evaluation year rather than more arms. **It ran,
and the answer is no.**

The arithmetic that makes 2023 the only year available: the exogenous arms are
aligned to `train_from = 2022-01-01` (no archived ENTSO-E D-1 vintage exists
earlier) and the harness needs 365 market days of history, so the honest
evaluation years are **2023 and 2024** — one extra draw. 2025 is sealed.

**2023 is a PLAN.md *training* year.** Every forecast is a genuine
expanding-window walk-forward prediction — a fold never sees its own day and the
gate-closure guard runs on every matrix — but the LEAR spec was chosen in C4 and
the GBM config frozen in C9 *while looking at 2024*. So this is a second
**prediction** year, not a second **configuration** test. The sealed 2025 holdout
is the only clean one, and it stays sealed until Checkpoint C.

The arms, the contrasts and the capture denominator are C11's, imported rather
than respelled: `ladder_arms()` is checked against `arms_for(zone, "A")` key by
key in `tests/test_c14_fundamentals.py`, because the store key is
`(model, exog_variant, vintage, train_from)` and a single different spelling
would make the two years two unrelated rows — the second-year comparison would
silently not exist. The denominator is **FINDING C11-C's**
`capture_rolled_oracle_cash`; `capture_same_start_pooled` is never used to rank
two curves. The contrast table and the dispatch phase's own `pooled_capture`
are two code paths to one number and are cross-checked against each other: **30
comparisons, worst absolute delta 4.8e-07**, and the run refuses anything above
1e-6.

### 9.1 FINDING C14-G — NOTE C8-01 is closed: the honest exogenous block is not worth having

`gbm_res_persistence − gbm_price_only`, capture in percentage points, daily
block, 2023 from this cycle and 2024 from C11/C12:

| zone | 2023 | 2024 |
|---|---|---|
| **DE-LU** | **−3.55pp [−6.76, −0.33]** ✱ | +0.35pp [−1.83, +2.53] |
| ES | +0.26pp [−2.15, +2.72] | +2.04pp [−0.26, +4.38] |
| NO2 | +2.39pp [−4.82, +9.78] | +2.71pp [−2.50, +8.03] |

Six (zone, year) cells under the booster. **Exactly one excludes zero at
PLAN.md's daily block, and it is negative.** The nearest thing to an
established positive remains ES 2024, which misses at the daily block
(P(≤0) = 0.042, clearing only under the one-sided reading NOTE C8-01's
directional question licensed). Under the LASSO all six cells contain zero.

So the honest exogenous block — everything a bidder could legitimately have had
— does **not** have a reliable positive value for a battery, in either model
class, in either year, in any of the three Tier-A zones. FINDING C8-A said it
was worth ~nothing on MAE; the dispatch metric now says the same across two
years, and the one contrast that clears a CI says it is actively harmful.
**NOTE C8-01 is answered: no.** C18 must not claim an exogenous gain.

This also settles the MAE half. `res_persistence − price_only` as a fraction of
MAE, twelve cells:

| zone | LEAR 2023 | LEAR 2024 | GBM 2023 | GBM 2024 |
|---|---|---|---|---|
| DE-LU | −0.71% | +0.28% | −3.76% | −1.01% |
| ES | +0.51% | −2.41% | +2.06% | −1.20% |
| NO2 | +1.36% | +0.54% | +0.38% | −0.22% |

Every cell is inside ±4% (the largest is −3.76%), and the sign flips between
years in **four** of the six (zone, model) pairs — the two that hold their sign
are DE-LU under the GBM (negative twice) and NO2 under the LEAR (positive
twice). **FINDING C8-A replicates in a second evaluation year and
gets stronger**: the honest exogenous block is worth nothing, and which side of
nothing it lands on is noise.

### 9.2 FINDING C14-H — the leak is worth what the merit order is worth

The Art. 14 vintage premium under the booster, against §3's measure of how much
residual load explains that zone-year's price:

| cell | `r2_piecewise_linear_20` | GBM vintage premium (% of MAE) |
|---|---|---|
| DE-LU 2023 | 0.802 | **28.13%** |
| DE-LU 2024 | 0.675 | 23.97% |
| ES 2023 | 0.650 | 23.21% |
| ES 2024 | 0.555 | 17.48% |
| NO2 2023 | 0.361 | 7.25% |
| NO2 2024 | 0.323 | **3.48%** |

**Strictly monotone: Spearman 1.0 over six cells, zero inversions.** A leak
about tomorrow's wind and solar is worth precisely as much as wind and solar
matter to tomorrow's price, and the span is a factor of eight.

**Suggestive, not established**, for two reasons stated plainly. The two axes
are not independent — a zone where RES sets the price is mechanically a zone
where knowing RES early helps — so this is a quantitative consistency check that
*could* have failed rather than an independent discovery. And three zones
contribute two cells each, so the effective sample is nearer three than six: a
perfect ordering of three zones happens one time in six by chance.

What it does give C18 is a *reason* for FINDING C9-C's zone pattern rather than
a list of numbers, and a prediction: a zone with little merit order has little
to leak.

### 9.3 Two more things the second year settled

**The vintage premium is a property of the model class, and the LASSO is
fragile.** DE-LU's premium is −16.83% under the LEAR in 2023 and **+28.13%
under the GBM in the same zone-year**; in capture terms the GBM's is
+9.05pp [+4.31, +13.62] (2023) and +3.47pp [+0.43, +6.60] (2024, C11), both
established. So the LEAR's 2023 sign reversal is a LASSO failure under a regime
shift, not evidence about the vintage: in the same rows the booster extracts the
leak cleanly. This strengthens **FINDING C9-C** — the leak is worth more to a
non-linear model, and now also *more reliably*. It remains **unachievable** and
travels only as the measurement of a leak.

**FINDING C12-E's one established contrast replicates.**
`gbm_price_only − lear_price_only` in ES is **−4.49pp [−7.40, −1.58]** in 2023
against C12's −2.22pp [−4.25, −0.29] in 2024: same sign, larger, excluding zero
in both years. The booster captures **less** than the LASSO in the zone where it
also has the better MAE — now a two-year result.

### 9.4 FLAG C14-01 — a pooled naive-dominance failure that is a tie, and a finding

**DE-LU 2023, `gbm_res_persistence`, fails CLAUDE.md's pooled naive-dominance
invariant.** It settles **52 763 EUR** against the naive floor's **52 850** over
364 days: a margin of **−87 EUR**, or **0.16%**, with a per-day win rate of
**50.3%**.

It is a tie, and the bootstrap says so rather than the prose: the margin is
**−0.139pp of oracle cash with a 95% interval of [−6.22, +6.15]** at the daily
block — forty-four times wider than the point estimate — and P(≤0) = 0.516,
0.518 and 0.526 at the 1, 7 and 14-day blocks. There is no evidence the arm is
worse than naive; it landed 87 EUR on the wrong side of zero.

**The assertion was not weakened.** It still reports `holds: false`, the failure
is recorded in `c14_ladder_invariant_flags.json`, and the dispatch phase exits
non-zero. No tolerance was widened and no test was edited. Every other check
passed on every curve of every zone, including the per-day same-start oracle
bound — the actual theorem.

**Why it is worth more than a footnote.** Among the five honest curves of
DE-LU 2023 this arm has **the best MAE and the worst capture** — both ends at
once:

| honest curve | MAE | capture |
|---|---|---|
| **gbm_res_persistence** | **23.60** (best) | **0.8453** (worst) |
| gbm_price_only | 24.53 | 0.8807 |
| lear_res_persistence | 25.62 | 0.8700 |
| lear_price_only | 25.77 | 0.8853 |
| naive | 33.62 | 0.8467 |

(Only the leaky `gbm_res_as_published` beats its MAE overall, at 17.05.) A
forecast **30% better than the naive floor on the point metric captured
slightly less of the flexibility value than the naive floor did**. The ranking
is not merely uncorrelated here, it is inverted at both ends. That is the
sharpest single instance in this project of **FINDING C11-D / C12-D**, and it
belongs in C18 beside them.

This is a different animal from **FLAG C13-01** (NO2 2020), where the margin was
−655 EUR on a perfect-foresight prize of 769 EUR/MW/yr in a market with a
3.41 EUR/MWh daily spread. That was a thin-market artefact; this is a tie in a
deep market. Neither should be "fixed" by relaxing the check.

---

## 10. What this cycle did not do, and why

- **No ENTSO-E actuals pull.** §1. Outside PLAN.md's declared scope; the
  limitation is stated and inherited by C18.
- **Tier B gets no fundamentals chapter.** PLAN.md C14 says Tier A, and Tier B
  has no exogenous block at all by design (price-history features only).
- **No gas or coal price series.** PLAN.md excluded the AGSI+ proxy after the
  audit. §5 quantifies what that costs — the 2022 level shift is the largest
  single thing no arm in this project can see — and leaves it as a stated
  limitation rather than adding an unsourced series.
- **No re-fit for NOTE C13-03.** C13's committed per-day artefact is the source,
  which is why the `error_over_headroom` here is the same statistic rather than a
  near neighbour of it.
- **The GBM config was not touched.** Fingerprint `a366a760e269bba6`, pinned by
  `test_the_committed_config_is_exactly_what_plan_md_froze`. PLAN.md forbids a
  hyperparameter search across cycles; a 2023 run on a re-tuned config would not
  be a second year of the same experiment, and the difference would be invisible
  in the capture table. Its `num_threads=4` is part of that fingerprint, which
  is why the ladder's zones were run **serially**: two four-thread fits sharing
  four cores were several times slower in total than running them one at a time,
  and lowering the thread count to fit would have changed the frozen config.
- **The 2023 full-history LEAR reference was run for DE-LU only.** C13 already
  computed that exact curve for 2023 (it is the nine-zone comparable arm), so
  for ES and NO2 it was ~20 minutes per zone of duplicated work. DE-LU's was
  kept deliberately, as the reproducibility cross-check in §1.1. The three C8
  artefacts therefore differ by one column, which nothing in the ladder reads.
- **No third evaluation year.** 2022 cannot be one for a 2022-aligned arm and
  2025 is sealed. §9's conclusions rest on two years, one of which has a
  crisis-dominated training window.

---

## 11. Limitations

1. **The residual load is a forecast, not a measurement** (§1). Every number in
   §§2-8 inherits this. The Art. 14 part is also published after gate closure,
   which is harmless for a description and fatal for a model — hence the code-level
   refusal rather than a comment.
2. **The residual-load "error" in §8 is a day-over-day revision**, a lower bound
   on the true D-1 error. The direction of the bias is known (understated), so the
   §8.2 correlations are if anything conservative.
3. **Every R² in §3 is in-sample.** The parameter counts are reported so the
   caveat is checkable. These are descriptions of a year, not forecasts of one,
   and they are not comparable to a walk-forward R².
4. **Three zones and three years is nine cells.** §8.3. The per-day correlations
   have real power; the cross-cell table does not.
5. **The source gaps are not filled** (C7's standing rule). 50 (DE-LU), 144 (ES)
   and 48 (NO2) hours are dropped for an incomplete residual load out of ~26 300,
   i.e. 0.2-0.6%, concentrated in the known autumn-DST hour and the partial-psrType
   stretches listed in `docs/entsoe_layer.md`. An hour missing *any* component is
   dropped, never part-subtracted.
6. **§7.1's solar/wind asymmetry is two zones and two years.** The intervals
   exclude zero and the two zones disagree in sign, which is interesting and not
   an established law.
7. **NO2's negative prices are left unexplained** (§6). The data to attribute
   them — reservoir levels, local grid constraints, corridor flows — is outside
   PLAN.md's scope (`docs/audit.md` records the absence of reservoir data for NO2
   and DK1 as a known limitation). Naming the residual it is *not* is as far as
   this chapter honestly goes.
8. **§9's ladder rests on two evaluation years, and 2023 is not a clean one.**
   Every 2023 arm carries a **+5.3 to +10.8 EUR/MWh upward bias**, because an
   arm aligned to `train_from = 2022-01-01` needing 365 market days of history
   has a training window dominated by the crisis year and over-predicts into
   2023's collapse. That is a property of the only second year available, not of
   the arms. It makes the *negative* NOTE C8-01 answer (§9.1) the conservative
   one — a block that cannot help a well-conditioned model is unlikely to start
   helping a badly-conditioned one — but it does bound every number in §9.
9. **§9.2's monotone ordering is six cells from three zones**, on two axes that
   are not independent. Stated there as suggestive, and it should not be quoted
   as a law.
10. **2023 is a PLAN.md training year.** Its forecasts are genuine
    expanding-window predictions, but the LEAR spec (C4) and the GBM config (C9)
    were both chosen while looking at 2024. §9 is a second *prediction* year, not
    a second *configuration* test. The sealed 2025 holdout is the only clean one.
