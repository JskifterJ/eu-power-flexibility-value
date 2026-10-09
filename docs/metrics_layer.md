# C12 — the metrics layer, and the cycle that puts intervals on C11

`backtest/metrics.py` (extended), `backtest/bootstrap.py` (new),
`backtest/run_c12_metrics.py` (new), `tests/test_c12_metrics.py` (51 tests).
Artefacts: `backtest/results/c12_daily_metrics_2024.csv.gz` (16 440 rows),
`c12_metrics_table.csv`, `c12_intervals.csv`, `c12_contrasts.csv`,
`c12_metrics_summary.json`, and 1 341 rows appended to
`backtest/results/results.csv`.

PLAN.md C12 is a list: *"MAE, RMSE, rMAE vs naive, daily-spread error,
within-day Spearman; capture ratio; EUR/MW/yr; block-bootstrap CIs over daily
blocks."* NOTE C11-01 is what the list is **for**: every C11 headline is one
validation year and either nine zones or fifteen paired comparisons, with most
capture deltas under one percentage point, and three questions had to be
answered before C18 quotes any of them. All three are answered below, and two
of the three answers are **no**.

Nothing was re-fitted and nothing was re-dispatched. Every number is built from
C11's committed per-day dispatch artefact and the prediction files C4/C8/C9/C10
committed, so a C12 interval is an interval around a C11 point estimate — which
is asserted, not assumed, before any interval is read (see
[Reproduction](#reproduction-c12-recomputes-c11s-numbers-before-bounding-them)).
`ENTSOE_API_KEY` was not needed and not read; **no price file was opened at
all** (the realised prices are the artefacts' own `y_true`), so this cycle made
zero network requests.

---

## 1. The two new metrics

MAE answers *how far out was the price?*. A battery does not trade the level. It
trades the **shape** of the day: how wide the trough-to-peak spread is (how much
there is to earn) and in which order the hours fall (when to charge and when to
discharge). PLAN.md's two decision-relevant metrics are exactly those two, and
C12 is the first cycle to compute either.

| metric | definition | why |
|---|---|---|
| `daily_spread_mae_eur_per_mwh` | mean \|forecast (max−min) − realised (max−min)\| over market days | the size of the prize the battery thought it was chasing |
| `daily_spread_bias_eur_per_mwh` | mean of the signed version | positive = the forecast promised a wider day than arrived, which is the sign that makes a battery over-trade |
| `within_day_spearman_mean` | mean per-day Spearman rank correlation of the hourly ordering | the only thing the dispatch LP reads off a curve |

Both are **per market day** by construction. `backtest.metrics.daily_shape_table`
returns one row per day carrying `sum_abs_error`, `sum_sq_error`, `sum_error`,
the realised and forecast spreads, the spread error and the day's Spearman. Two
properties of that shape are load-bearing:

* **A pooled MAE is a ratio of column sums, never a mean of per-day MAEs.** A
  23-hour day and a 25-hour day do not carry equal weight, and a mean of daily
  MAEs says they do. That is the DST bug this shape exists to prevent, and
  `test_the_pooled_mae_is_a_ratio_of_sums_not_a_mean_of_daily_maes` pins it.
  `shape_scores` and C3's `score` agree to 1e-12 on the same hours, which is
  what lets a point error and a dispatch metric sit on one row.
* **Everything is day-additive**, so the bootstrap is a resample of *rows*.

Nothing is dropped quietly. A day whose realised prices are flat has no ordering
to predict and its Spearman is `nan`; such days are counted in
`n_days_spearman_undefined` (it is **0** everywhere in 2024) rather than skipped
into a smaller and flattering denominator. Ties are averaged, which is what
"Spearman" means — the test uses a case where breaking them in index order would
give 0.8 instead of 0.9487, because European market days carry identical
consecutive clearing prices often.

### Hours and days are the same ones the capture ratio uses

Every metric here is computed on **exactly the hours the capture ratio is pooled
over**. That is C11's discipline (its paired MAE deltas) carried forward, and it
is not cosmetic: ES's exogenous join has 145 missing hours, so re-using C10's
own-coverage MAE would pair a capture delta with an MAE delta measured on a
different sample, and the whole of FINDING C11-D would be an artefact of two
samples.

---

## 2. The bootstrap

`backtest/bootstrap.py`. Four decisions, each of which moves a reported
interval.

**The resampling unit is a market day.** The LP optimises one day at a time, the
capture ratio is a ratio of sums over days, and C11's artefact is one row per
(zone, curve, day). Resampling *hours* would destroy the within-day shape the
dispatch decision is made of and produce absurdly narrow intervals.

**Paired, not independent.** One replicate draws one day multiset and applies it
to every zone, every curve and every statistic. European prices are strongly
correlated across zones and two arms see the same days, so independent draws
would inflate every difference — and a difference is what questions (ii) and
(iii) are about. `test_pairing_narrows_a_difference_relative_to_resampling_independently`
shows the effect is an order of magnitude on two nearly-identical series.

**Circular moving blocks, with the block length reported.** PLAN.md says "daily
blocks", so the headline is `block_days=1`. But power days are serially
correlated, and a 1-day block assumes they are not — so every interval is
reported at **1, 7 and 14 days**, and a conclusion that does not hold at all
three is reported as not holding. Blocks wrap around the year so no day is
under-weighted; with `block_days == n_days` a replicate can only be a rotation
of the whole year, so every day is drawn exactly once and a day-additive
statistic ties at the point estimate — the analytic check on the wrap-around,
and a test.

A warning for later cycles: **a wider block does not mean a wider interval.**
With 365 days, a 14-day block leaves ~26 independent blocks and the long-run
variance estimate gets noisy; here it comes out *narrower*, not wider. So the
ladder is a robustness check and not an ordering, and the conservative reading
is the rung that is least favourable to the claim being made.

**Percentile intervals, and the limitation is stated.** 2.5th–97.5th percentile
of 10 000 replicates, seed 20261009. No BCa, no studentisation: with a ratio of
sums over 365 dependent days the coverage is approximate, and a more decorated
method would be false precision rather than more of it.

### Is a band wider than noise?

A band is a max minus a min, so it is positively biased and its own interval
never contains zero even when every group is identical. `noise_only_spread`
therefore builds the band's **null** distribution directly: for each replicate
the group effect is removed and the group's own bootstrap deviation kept,

```
null_g,b = mean(points) + (replicate_g,b − point_g)
```

so every group sits at the common level and differs only by the sampling noise
the bootstrap measured for it. The p-value is the share of those draws at least
as wide as the observed band. Each group keeps its own noise scale, which
matters here — NO2's per-day capture is twice as noisy as DE-LU's, and ES has
357 days against 365.

That function is the load-bearing piece of §4, so it is tested for
**calibration**: on eight groups drawn from one distribution it must not call
the band significant (at most 2 of 12 draws below 0.05), and on one group
shifted far out it must return p < 0.01.

---

## 3. Reproduction: C12 recomputes C11's numbers before bounding them

A CI around a number nobody published is worse than no CI, so the run fails with
a non-zero exit if its point estimates do not match C11's committed store rows.
Seven metrics × 27 (zone, curve) pairs are joined on the **store's own key**
(zone, model, exog_variant, vintage, train_from, …), not on C11's internal curve
label.

| metric | worst disagreement |
|---|---|
| `mae_on_dispatched_hours` | **0.0** |
| `rmse_on_dispatched_hours` | **0.0** |
| `bias_on_dispatched_hours` | **0.0** |
| `realised_spread_mean_eur_per_mwh` | **0.0** |
| `capture_rolled_oracle_cash` | 5.2e-10 |
| `dispatch_cash_eur_per_mw_year` | 6.5e-10 relative |
| `eur_per_mw_year_lost_vs_oracle` | 2.9e-9 relative |

The two euro figures carry a *relative* tolerance for a stated reason: C11
formed them as `sum(cash) / span * 365.25` and C12 forms them as
`mean(cash) * (n_days * 365.25 / span)` — algebraically identical, summed in a
different order, so they agree to ~1e-9 relative and cannot agree to 5e-6
absolute. The lost-value figure carries one further order of magnitude because
it is a *difference* of two ~70 000 EUR sums that is itself ~6 000 EUR, and the
cancellation amplifies the relative error. Recomposing them C11's way to dodge
that would give up the resampled-mean form the bootstrap needs.
`test_the_c11_reproduction_check_can_actually_fail` nudges one capture ratio by
1e-6 and confirms the check catches it.

Note what the annualisation preserves: C11 annualised over the **calendar span**,
so a day a curve declined counts as a day the battery earned nothing. C12 holds
that constant across replicates rather than switching to a mean over dispatched
days, because the published number is the one being bounded.

---

## 4. FINDING C12-A — the capture band is wider than noise; rMAE's is not

FINDING C11-A made two claims. They need different tests, and they get different
answers.

The nine-zone table, comparable arm (`lear_full_history`), `own_coverage`,
2024, per-zone capture intervals at the daily block:

| zone | regime | capture | 95% CI | boot sd (pp) | within-day ρ | rMAE | MAE | spread MAE | spread bias |
|---|---|---|---|---|---|---|---|---|---|
| DE-LU | thermal-RES-mixed | 0.9187 | [0.8811, 0.9568] | 1.94 | 0.8109 | 0.6992 | 22.89 | 38.69 | −21.07 |
| ES | solar-dominated | 0.9109 | [0.8636, 0.9594] | 2.46 | 0.8354 | 0.6534 | 17.84 | 22.30 | −7.91 |
| BE | gas-nuclear-mixed | 0.9044 | [0.8663, 0.9421] | 1.93 | 0.8329 | 0.6888 | 19.37 | 28.19 | −16.75 |
| IT-North | gas-dominated | 0.9042 | [0.8552, 0.9571] | 2.60 | 0.8852 | 0.6887 | 9.54 | 15.04 | −8.53 |
| NL | gas-RES-mixed | 0.9031 | [0.8700, 0.9374] | 1.71 | 0.8300 | 0.7187 | 21.46 | 37.55 | −23.72 |
| PL | coal-dominated | 0.8839 | [0.8472, 0.9194] | 1.85 | 0.8135 | 0.6794 | 20.24 | 40.74 | −22.61 |
| FR | nuclear-dominated | 0.8526 | [0.8236, 0.8824] | 1.50 | 0.8073 | 0.6451 | 17.87 | 21.33 | −10.26 |
| DK1 | wind-dominated | 0.8358 | [0.7880, 0.8826] | 2.41 | 0.7062 | 0.6748 | 25.42 | 36.64 | −21.85 |
| NO2 | hydro-dominated | **0.6146** | [0.5315, 0.6964] | **4.19** | **0.5781** | 0.6445 | 13.66 | 25.67 | −10.51 |

(rMAE here is recomputed on the dispatched hours, so it is 0.6992 on DE-LU
against C10's own-coverage 0.6971 — the same quantity on the capture ratio's
own sample.)

**The inequality of the bands holds, decisively.**

| block | capture band | noise-only p | between/within | rMAE band | noise-only p | between/within |
|---|---|---|---|---|---|---|
| 1 day | 30.40pp [23.27, 40.35] | **< 1e-4** | 4.18 | 7.42pp [5.65, 14.19] | 0.196 | 0.95 |
| 7 days | 30.40pp [24.47, 37.75] | **< 1e-4** | 6.10 | 7.42pp [5.93, 15.91] | 0.367 | 0.69 |
| 14 days | 30.40pp [24.92, 37.56] | **< 1e-4** | 5.88 | 7.42pp [6.23, 15.37] | 0.284 | 0.71 |

The capture ratio's cross-zone spread is 4–6 times the sampling noise of its own
estimates. rMAE's is *at or below* it — the nine zones' relative skill is not
distinguishable from nine draws of one number. That sharpens FINDING C10-A from
"near-constant" to "indistinguishable from constant", and it is the strongest
form of FINDING C11-A's claim: a point-error ratio that noise cannot be
distinguished from sits on top of a dispatch metric that is 4–6 σ wide.

C11's "capture's CV is 3.0x rMAE's" survives as an interval:
**CV ratio 2.97 [1.53, 4.30]**, excluding 1 at every block length. 17 of the 36
zone pairs have a paired capture difference excluding zero (21 of 36 at 7 days).

## FINDING C12-B — the eight-zone band is *not* established (NOTE C11-01 (i))

This is the question C11 handed C12, and the honest answer is no.

| block | capture band ex-NO2 | noise-only p | between/within |
|---|---|---|---|
| **1 day (PLAN.md's "daily blocks")** | 8.29pp [6.51, 15.18] | **0.078** | 1.45 |
| 7 days | 8.29pp [6.75, 12.38] | 0.001 | 2.20 |
| 14 days | 8.29pp [6.89, 12.42] | 0.003 | 2.06 |

At the block length PLAN.md names, the eight-zone band does not clear 5%. It
clears comfortably at 7 and 14 days — but a conclusion that depends on the block
length is by definition not established, and the 7/14-day rungs are the ones
whose long-run variance estimate is least trustworthy at n = 365. And once NO2
is out, the capture CV and the rMAE CV become indistinguishable
(**ratio 0.96 [0.51, 1.77]**).

So: **FINDING C11-A is a finding about NO2 plus a direction.** The 30.4pp band
and the inequality of the bands are real and large. The claim that the remaining
eight regimes differ in capture by more than noise is at the edge of what one
validation year can support. **C13's second year is the test, and C18 must not
quote the 8.3pp band as established until it passes.**

## FINDING C12-C — the within-day Spearman is the only point metric that tracks capture

C11 asked whether *rMAE* tracks capture across regimes. The more useful question
turned out to be whether **any** point-forecast metric does, and the answer is
one of them — the one that is closest in meaning to what the LP reads.

Cross-zone rank correlation against capture, nine zones, daily block:

| forecast metric | ρ vs capture | 95% CI | expected sign | sign right? | excludes 0? |
|---|---|---|---|---|---|
| **within-day Spearman** | **+0.70** | **[+0.35, +0.93]** | + | ✔ | **✔** |
| rMAE vs naive | +0.60 | [−0.08, +0.85] | − | ✘ | ✘ |
| MAE | +0.05 | [−0.25, +0.50] | − | ✘ | ✘ |
| daily spread MAE | +0.08 | [−0.37, +0.58] | − | ✘ | ✘ |
| daily spread bias | +0.20 | [−0.55, +0.42] | + | ✔ | ✘ |

The Spearman result holds at every block length and with NO2 removed
(+0.57 [+0.07, +0.91]); every other candidate spans zero everywhere.
`expected sign` is the direction a "regime differences reach flexibility value
through forecastability" story predicts, and it matters: **rMAE's +0.60 has the
wrong sign** — zones where the model is relatively worse than naive capture
*more* — so C11 was right to refuse to lean on it, and C12 can now say the
interval contains zero too.

### A candidate mechanism for FINDING C11-B, which C11 could not offer

NO2's mean within-day Spearman is **0.578**, against 0.71–0.89 in the other
eight; DK1, the second-worst capture, has the second-worst Spearman (0.706).
C11 found that every *spread-based* correlate of NO2's low capture collapsed
when NO2 was dropped. The ordering metric does not: it survives the drop
(+0.57, excluding zero). So the candidate mechanism is **not** "NO2's spread is
too thin to clear the round-trip cost" but "**in NO2 the forecast puts the hours
in the wrong order**", which is the one error a battery cannot trade around.

This is a candidate, **not established**: n = 9, one year, and the rank
correlation is not a mechanism by itself. It does, however, change what the C15
test should be read against — the throughput-cost ladder tests the thin-spread
story, and NOTE C12-02 below asks for the ordering story to be tested beside it.

## FINDING C12-D — capture cannot rank arms at one year (NOTE C11-01 (ii))

FINDING C11-D was "among honest arms, MAE does not predict capture", with C11's
own caveat that most deltas were under 1pp. The bootstrap says the caveat was
the finding.

Across the fifteen honest contrasts, at the daily block:

| contrast metric | intervals excluding 0 | median \|delta\|/boot sd | max |
|---|---|---|---|
| capture (pp) | **1 / 15** | **0.46** | 2.21 |
| EUR/MW/yr | 1 / 15 | 0.46 | 2.23 |
| daily spread MAE | 5 / 15 | 0.93 | 3.88 |
| MAE (%) | 7 / 15 | 1.91 | 6.33 |
| **within-day Spearman** | **8 / 15** | **2.23** | 5.01 |

The ordering (capture fewest, Spearman most) holds at every block length. And
the rank correlation C11 reported as +0.02 has interval **[−0.53, +0.56]** — it
excludes essentially nothing. Sign agreements: 9 of 15, interval [5, 12], against
7.5 under independence.

**So the honest statement is not "MAE does not predict capture". It is "a single
validation year decides 1 of 15 capture deltas, so it cannot establish that MAE
predicts capture and cannot rule it out either."** FINDING C11-D must be
restated in C18 as *undetermined*, not as *contradicted*. The reason the two
metrics appear to disagree is largely that one of them is 4× noisier per unit of
effect.

That is not a reason to prefer MAE. It is a reason to rank arms on the
**within-day Spearman** — decidable, and the only metric whose cross-zone
behaviour tracks capture — and to use capture for the economic translation
(EUR/MW/yr) rather than for the ranking.

## FINDING C12-E — the GBM-exogenous capture gain mostly does not survive (NOTE C11-01 (iii))

C11 answered NOTE C8-01 affirmatively on +0.35 / +2.04 / +2.71pp of capture
(DE-LU / ES / NO2, under the GBM). Paired intervals:

| zone | delta | 1 day | 7 days | 14 days |
|---|---|---|---|---|
| DE-LU | +0.35pp | [−1.83, +2.53] | [−0.68, +1.40] | [−0.54, +1.24] |
| ES | +2.04pp | [−0.26, +4.38] *(P(≤0) = 0.042)* | **[+0.74, +3.60]** | **[+0.88, +3.44]** |
| NO2 | +2.71pp | [−2.50, +8.03] | [−0.79, +6.63] | [−0.68, +6.56] |

**One of three, conditionally.** DE-LU and NO2 contain zero at every block
length — NO2 despite having the largest point estimate, because its per-day
capture is the noisiest of the nine zones. ES misses at the daily block by a
hair and clears at 7 and 14 days; since NOTE C8-01 asked a *directional*
question, the one-sided reading (4.2% of replicates at or below zero) clears 5%
even at the daily block.

**NOTE C8-01 should therefore be re-opened, not left closed-affirmative.** The
honest exogenous block under the booster is supported in ES and unestablished in
DE-LU and NO2. The headline honest Tier-A arm stays `res_persistence` — it is
not *worse* anywhere, and FINDING C8-A already said the block costs nothing on
MAE — but "it buys +2pp of capture" is one zone's result, not three.

### The one honest contrast that is established

Of all fifteen, exactly one capture delta excludes zero at every block length:
**ES, `gbm_price_only − lear_price_only` = −2.22pp [−4.25, −0.29]** — the
booster captures *less* than the LASSO, in the zone where it also has the lower
MAE (−1.15%). That is the one piece of FINDING C11-D's claim (ii) that a single
validation year does establish, and it runs against the booster.

## A systematic result the spread metrics turned up

**Every one of the nine zones under-predicts the daily spread**, by 7.9
(ES) to 23.7 (NL) EUR/MWh — `daily_spread_bias` is negative everywhere, with no
exceptions and no near-misses. The forecast day is reliably flatter than the day
that arrives, which is the regularised model shrinking towards the mean. The
direction matters for the write-up: it biases the battery towards **under**-
trading, which is conservative, and it is part of why the capture ratio sits
near 0.9 rather than near 1 even where the ordering is good.

---

## 5. What went into the store

1 341 rows, run `C12-20261009T102850Z-4d32f5e9`; the store is now **3 426 rows
across 3 runs**, `verify_append_only()` green, and the 2 085 committed C10+C11
rows are **byte-for-byte unchanged** (the new file's first 608 226 bytes are
identical to `git show HEAD:backtest/results/results.csv`, and the diff is
1 341 insertions / **0 deletions**). **No schema change and no test edit were
needed** — long format made the metric name the extension point for the third
cycle running.

Three naming conventions, all mechanical:

* `<metric>` — a new point estimate, at both scopes:
  `daily_spread_{mae,bias,rmse}_eur_per_mwh`,
  `within_day_spearman_{mean,median,p05}`,
  `rmae_vs_naive_on_dispatched_hours`.
* `<metric>_{ci_low,ci_high,boot_sd}` — the interval at the **headline block
  length only**, for `capture_rolled_oracle_cash`,
  `dispatch_cash_eur_per_mw_year`, `eur_per_mw_year_lost_vs_oracle`,
  `mae_on_dispatched_hours`, `daily_spread_mae_eur_per_mwh`,
  `within_day_spearman_mean`. The block length, replicate count and seed are in
  the run note and the artefacts, not in the metric name — a name that encoded
  them would make the ladder unreadable. The full ladder is in
  `c12_intervals.csv` (1 269 rows).
* `{capture_delta_pp,mae_pct_gain}_vs_<baseline curve>` and their bounds — a
  paired contrast, written on the **treatment** row, with the baseline in the
  name because the store's key identifies one series and a difference is about
  two.

`evaluation_years` is `2024` on all 3 426 rows and the store's own tripwire
refuses any other.

---

## 6. Limitations of this cycle's statistics

Stated plainly, because they bound everything above.

1. **One validation year.** 365 daily blocks. Every interval here is the
   sampling uncertainty of *2024*, not of the data-generating process. A second
   year is not a wider sample of the same thing — 2022 was a different regime
   entirely — so C13's per-year tables are a different kind of evidence, not
   more of this kind.
2. **Percentile coverage is approximate.** A ratio of sums over dependent days
   is not pivotal; the interval is a reasonable summary, not an exact 95%.
3. **The block ladder is a robustness check, not an ordering.** At n = 365 a
   14-day block leaves ~26 independent blocks and estimates the long-run
   variance noisily; here it comes out narrower. Read the least favourable rung.
4. **n = 9 zones and n = 15 contrasts are the hard limits.** The bootstrap
   resamples days, so it widens the interval on a cross-zone correlation but
   cannot manufacture zones. +0.70 on nine zones is nine points.
5. **No multiplicity correction.** 36 zone pairs, 15 contrasts × 5 metrics, 5
   candidate metrics — at 5% some of this is chance. Where a claim rests on one
   interval out of many (FINDING C12-E's ES result, the 17/36 separated pairs)
   that is said at the point of claiming it rather than adjusted away, because
   the adjustment a reader would want depends on which family they think the
   test belongs to.
6. **The null-band test keeps each group's own noise and assumes nothing else.**
   It is not an F-test and does not assume equal variances; what it does assume
   is that the bootstrap's per-group variance estimate is roughly right, which
   at 357–365 days is the same assumption every interval here makes.
