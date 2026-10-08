# Exogenous features in LEAR, and the RES-forecast vintage premium (C8)

C7 fetched, validated and contracted the two ENTSO-E day-ahead forecast
documents and deliberately let no model touch them. C8 is the cycle that
connects them to LEAR, and the whole cycle turns on a single awkward fact about
one of the two.

| Document | Feature column | Public for market day `D` | vs gate closure (12:00 local, `D-1`) |
|---|---|---|---|
| Art. 6.1.B day-ahead total load (A65) | `load_forecast_da_mw` | 10:00 local on `D-1` | **2 h before** — safe |
| Art. 14.1.D day-ahead wind/solar (A69) | `wind_forecast_da_mw`, `solar_forecast_da_mw` | 18:00 local on `D-1` | **6 h after** — FLAGGED |

A model fed the archived Art. 14 vintage is reading tomorrow's weather off
tomorrow's newspaper. The bids whose clearing price it is predicting were already
in, six hours before that forecast existed. It is not a subtle leak either: wind
and solar are the two largest single drivers of a short-run price in DE-LU and
ES, so a model given them at the right vintage looks very good for a reason no
desk could ever reproduce.

PLAN.md's answer — and the reason C7 was forbidden from modelling — is neither to
drop the series nor to use it quietly, but to turn the gap into a measured
quantity.

## The ladder: four arms, one code path

`forecast/exog_features.py` builds the same exogenous column set at four declared
**variants**, in increasing order of information. `backtest/run_c8_exogenous.py`
runs all four per Tier-A zone on the 2024 validation year.

| Arm | Columns added | Vintage | Leak-free? |
|---|---|---|---|
| `price_only` | — | — | yes (C4's feature set) |
| `load_only` | `load_forecast_da_mw` | target day's own | **yes** |
| `res_persistence` | `+` wind, solar, residual load | the vintage published 24 h earlier | **yes** |
| `res_as_published` | `+` wind, solar, residual load | target day's own | **no — acknowledged** |

Two differences out of those four arms are the point of the cycle:

* **`load_only − price_only` — the capturable exogenous gain.** Every cell was
  public before gate closure, so whatever this buys is a gain a bidder could
  actually have banked. This is the number that belongs in the write-up's results
  table.
* **`res_as_published − res_persistence` — the vintage premium.** Both arms hold
  the *same four columns*; only the publication time differs. This is how much of
  a RES-fed model's apparent skill is owed purely to the archive being better
  informed than the market was. It is a measurement of a leak, not a result.

`res_persistence` is the honest RES arm: a real bidder at 12:00 on `D-1` holds
the load forecast for `D` and the RES forecast for `D-1`, and nothing better.
Yesterday's RES forecast is still informative, because wind and solar are
autocorrelated day to day — it is a degradation, not a deletion.

Each arm's information set contains the previous arm's, so MAE is expected to be
non-increasing along the ladder. The runner checks that and reports
`mae_monotone_non_increasing` rather than assuming it: a violation is a finding
about the model (a column the LASSO cannot exploit, or a weak signal swamped by
the parameters it costs), not a plumbing bug.

## The publication clock lives in config, not in prose

C7 recorded the 18:00 publication time in a `leakage_note:` comment. A comment
cannot be checked. C8 therefore adds, beside each document in
`config/data.yaml`:

```yaml
    publication_tz: "Europe/Brussels"
    documents:
      load_forecast_da:
        published_day_offset: -1
        published_local: "10:00"
      wind_solar_forecast_da:
        published_day_offset: -1
        published_local: "18:00"
```

Two consequences. First, `forecast/exog_features.py` derives every exogenous
column's information time from these numbers, so the existing C3 gate-closure
guard checks the exogenous block exactly as it checks a price lag — the FLAGGED
status stops being an assertion in a comment and becomes six hours of arithmetic.
Second, `test_the_declared_clock_is_what_makes_the_leak_visible` pins the two
numbers against the gate-closure convention, so a later cycle that edits either
one is caught rather than quietly re-basing the whole experiment.

A document with no declared clock is an error, not a default. The only safe
default ("assume it was late") would silently disable a column, and the only
convenient one ("assume it was early") is the bug this module exists to prevent.

The Art. 6.1.B time is the **latest** instant the regulation permits (two hours
before gate closure), not a typical one. A guard built on an optimistic
publication time would pass a column a real bidder was still waiting for.

## The late arm's guard is pointed at it, not switched off

`res_as_published` is the only place in this repo where a post-gate-closure
column reaches a model, and the door is deliberately narrow.

For the three leak-free arms, nothing is special: late cells are blanked by
`forecast.leakage.mask_unavailable` exactly as C3 blanks a late price lag, and
`assert_no_leakage` then has to pass clean — the unmodified guard, with no
acknowledgement of any kind. `test_leak_free_variants_pass_the_plain_guard`
asserts it.

For `res_as_published`, `assert_only_acknowledged_leakage` replaces the plain
guard and permits a violation only if **all** of the following hold:

1. its column was named in advance, in `ExogAttachReport.acknowledged_late_columns`;
2. its kind is `after_gate_closure` — an undeclared or malformed information time
   is never acknowledgeable, because then nobody knows what is being permitted;
3. its worst lateness equals what the declared clock predicts, **to the minute**.
   A column late by more than its clock says is not the known leak; it is a
   different and unexamined one.

It also refuses a *silent* acknowledgement: if a column named as late produces no
`after_gate_closure` violation, the clock, the vintage or the gate convention has
changed and the experiment would be measuring something else.

That check is **stricter** than the plain guard on that matrix, not weaker. It
pins the leak's shape instead of merely tolerating one, and a genuine leak in a
price lag cannot hide behind the RES acknowledgement
(`test_acknowledgement_refuses_an_unrelated_leak`).

The harness's own per-fold check is skipped for that one arm
(`run_walk_forward(check_leakage=False)`, the same door
`backtest/diagnostics.py` already uses for the deliberate misalignment
experiments) and replaced by one pass over the whole arm matrix. That is sound
because the guard is a per-`(row, column)` predicate: a violation in any row
subset is a violation of the whole, so a whole-matrix pass with no unacknowledged
violation leaves no subset with one.
`test_the_whole_matrix_check_implies_every_row_subset_s` asserts that on real
subsets rather than arguing it. Sealed-year refusal and the "training targets
must be public" guard are untouched and still run on every fold of every arm.

**Nothing frozen was edited to make this work.** `forecast/leakage.py`,
`forecast/features.py`, `data/contracts.py` and every existing file under
`tests/` are unchanged; the acknowledgement is built out of `find_leakage` and
`mask_unavailable` rather than by relaxing them. `tests/` gained one new file.

## Three design choices that are easy to get wrong

### The residual-load column is derived *after* degradation

Under `res_persistence` a bidder holds the load forecast for `D` **and** the RES
forecast for `D-1`. So the best residual-load estimate available to them is

```
load(t) − wind(t − 24h) − solar(t − 24h)
```

which is what this module builds. The alternative — lagging C7's already-derived
`residual_load_forecast_mw` column by 24 hours — would throw away the load
forecast they did hold, and would differ from the above by the day-on-day change
in load, which is exactly the part of residual load a day-ahead bidder knows.
`test_residual_load_is_derived_after_degradation_not_before` asserts the two are
not the same thing.

Its information time is the element-wise **maximum** of its three inputs': a
derived value is knowable only once its last input is.

### The persistence offset is late on the autumn DST long day

The 24-hour offset is applied by explicit UTC-instant reindexing, never
`.shift(n)` (which counts rows and so hands back the wrong hour across a gap).
Its information time is then read back off the clock rather than assumed safe —
and on the autumn DST day that matters. The local market day has **25** hours, so
its *last* hour minus 24 hours is its own *first* hour, whose RES forecast was
published at 18:00 on `D-1`, after the gate. The guard catches exactly those
rows, the mask blanks them, and the count is reported as
`persistence_masked_dst_rows` with its timestamps.

Nobody would have thought to special-case that; the clock arithmetic found it.
For NO2 all three autumn DST days in 2022-2024 are blanked. For DE-LU only
**one** is — because for 2023 and 2024 the source hour is already NaN, and it is
already NaN for a reason: FINDING C7-C recorded that DE-LU's wind and solar
publications drop the hour `22:00Z-23:00Z` on 2023-10-28 and 2024-10-26, and that
hour *is* the long day's first local hour. The two findings describe the same
hour from opposite ends.

### Every arm trains from the same day

The exogenous series start in 2022 (no archived D-1 forecast vintage exists
earlier, PLAN.md), and LEAR drops a training row with any missing design cell. An
exogenous arm on an expanding 2019-start window therefore trains on 2022+ while
`price_only` trains on 2019+, and the difference between the arms would be partly
"more features" and partly "less history" with no way to separate them.

All four arms are run on a training window beginning `2022-01-01`
(`--align-train-from`). `price_only` is *additionally* run on the full history as
a labelled `full_history_reference` row — which is C4's committed configuration,
reproduces its number, and makes the cost of the alignment a figure in the
summary rather than a caveat. It is not part of the ladder: it trains on
different rows.

### The arms are compared on hours every arm predicted

The committed LEAR declines an hour whose design has a hole, and the exogenous
columns bring holes of their own — FINDING C7-C's source gaps, of which the
largest is ES solar missing for 120 hours of December 2024. Scored on their own
coverage, the four arms would be four different measurements wearing one table.

Each arm's own scores are reported, **and** a `common_hours` block re-scores every
arm on the intersection of the hours all of them predicted. The degradation table
is computed from the latter. Both are in the summary; neither is hidden.

## What C8 deliberately did not do

* **No hyperparameter search.** The LEAR spec is C4's committed one (AIC
  selection, `nan_policy="decline"`, local-hour partition). PLAN.md forbids
  tuning against repeatedly visible metrics across cycles, and four arms × three
  zones is already four chances to over-read 2024.
* **No `config/features.yaml` edit.** It already declares the four exogenous
  features and their leakage statuses. NOTE C7-01's two spellings
  (`load_forecast_da` there, `load_forecast_da_mw` in the built columns) stay as
  the human resolved them — option (a), keep both and document the mapping — and
  `exogenous_feature_names()` *is* that mapping, derived rather than written down
  twice, so a rename in either file surfaces as a failing test instead of drift.
* **No Tier-B exogenous features.** PLAN.md keeps Tier B on price history alone.
* **No battery LP.** C8 touches no dispatch code, so the LP invariants apply to
  no new artefact; they remain executable and green in the suite. C11 is the
  cycle that puts these forecasts through the LP across all nine zones.
* **No 2025.** The holdout is sealed. Evaluation is the 2024 validation year
  only, and `test_no_arm_can_be_evaluated_against_a_sealed_year` asserts the arms
  inherit the refusal.
* **No sweep of the degradation offset.** 24 hours is the one PLAN.md names and
  the only one a bidder's information set offers for free. A fractional-day
  offset is refused outright: it would read a different delivery hour rather than
  an older vintage.

## Results — 2024 validation year, Tier A

MAE and RMSE in EUR/MWh, on the **common hours** (the hours every arm predicted),
LEAR with C4's committed spec, refit daily, every arm training from 2022-01-01.
Full artefacts in `backtest/results/c8_exog_<ZONE>_2024_summary.json`.

| Arm | DE-LU MAE | RMSE | ES MAE | RMSE | NO2 MAE | RMSE |
|---|---|---|---|---|---|---|
| `naive_last_week` | 32.799 | 55.219 | 27.316 | 38.135 | 21.195 | 41.758 |
| `price_only` | 23.525 | 37.416 | 18.126 | 24.075 | 14.737 | 26.894 |
| `load_only` | 23.715 | 37.425 | 18.015 | 23.992 | 14.746 | 26.915 |
| `res_persistence` | 23.588 | 37.199 | 17.930 | 23.892 | 14.817 | 26.938 |
| `res_as_published` *(late)* | **21.610** | **32.699** | **15.906** | **20.650** | 14.809 | 26.273 |

The two headline differences:

| Zone | Capturable gain (`load_only − price_only`) | Vintage premium (`as_published − persistence`) |
|---|---|---|
| DE-LU | **−0.19** EUR/MWh (−0.81% of MAE) | **+1.98** EUR/MWh (**+8.39%**) |
| ES | **+0.11** EUR/MWh (+0.61%) | **+2.02** EUR/MWh (**+11.28%**) |
| NO2 | **−0.01** EUR/MWh (−0.06%) | **+0.01** EUR/MWh (+0.06%) |

**Almost all of the apparent value of the ENTSO-E RES forecast block is the
vintage, not the information.** At an honest vintage the entire exogenous block
is worth between −0.8% and +0.7% of MAE — i.e. nothing, in any of the three
regimes. Fed the as-published Art. 14 archive, the same columns in the same model
buy 8-11% of MAE in the two RES-exposed zones. A backtest that uses the archived
Art. 14 forecast without this split is reporting roughly a tenth of its MAE
improvement as skill when it is a publication timestamp.

Three further observations, all in the committed summaries:

* **RMSE moves more than MAE.** For `res_as_published` the RMSE gain is −12.6%
  (DE-LU) and −14.2% (ES), against MAE gains of −8.4% and −11.3%. RES forecast
  information mostly kills the *large* errors — the high-wind, negative-price
  hours — which MAE under-weights and which are exactly the hours a battery earns
  in. The vintage premium will therefore be **larger** in captured-value terms
  than it looks here, and C11/C12 are where that gets measured rather than
  guessed.
* **History beats features.** Aligning every arm to the 2022 exogenous start
  costs `price_only` +0.66 (DE-LU), +0.26 (ES) and +1.10 (NO2) EUR/MWh of MAE
  against C4's full 2019+ window. For LEAR on these zones, three extra years of
  *price history* is worth several times the entire exogenous block at an honest
  vintage.
* **NO2 shows nothing, in either direction**, which is the control that makes the
  other two credible. A hydro-dominated zone with ~1.3 GW of onshore wind, no
  solar fleet at all and reservoir-set prices has nothing for a RES forecast to
  explain, at any vintage — so a method that invented a premium there would be
  measuring its own machinery.

The MAE ladder is **not** monotone for DE-LU and NO2: `load_only` and
`res_persistence` land fractionally *above* `price_only`. Reported, not smoothed
— the runner's `mae_monotone_non_increasing` flag carries it. The reading is that
these columns buy nothing a LASSO can use once the price lags are present (the
day-ahead load forecast is largely a restatement of the weekly and daily cycle
the lags already carry), and so cost a little in parameters. That is a finding
about the features, not a defect in the plumbing: ES — where solar genuinely sets
the midday price — is monotone.

## Attribution

Load and wind/solar forecasts: ENTSO-E Transparency Platform. Day-ahead prices:
Energy-Charts (Fraunhofer ISE), CC BY 4.0.
