# LEAR — the regularised linear price model (C4)

The first real model. C3 built a harness that can catch a pipeline cheating;
C4 puts something in it that could actually want to.

LEAR is the open-benchmark linear model for day-ahead power prices
(Uniejewski/Weron/Ziel's variance-stabilised LASSO, consolidated as a benchmark
in Lago et al. 2021): **one LASSO per delivery hour**, fitted on
variance-stabilised prices, with the penalty chosen *inside* the fold. It is
what a desk reaches for before anything clever, and it is a much harder
reference than the naive floor, because it can combine the weekly cycle, the
day-before level and the calendar shape instead of copying one of them.

```
forecast/lear.py              LearSpec, LearModel, the encoding and the VST
backtest/run_c4_lear.py       CLI: python -m backtest.run_c4_lear
tests/test_c4_lear.py         33 offline tests
```

Committed artefacts:

```
backtest/results/c4_lear_DE-LU_2024_predictions.csv.gz   realised + lear + naive + train-mean
backtest/results/c4_lear_DE-LU_2024_folds.csv            one row per refit
backtest/results/c4_lear_DE-LU_2024_summary.json         scores, selector comparison, diagnostics
```

## The four decisions that carry the model

### 1. One LASSO per delivery hour, partitioned on *local* time

Hour 03 and hour 18 are different products with different drivers; pooling them
produces one model that is wrong about both. So there are 24 independent
LASSOs. They are partitioned by the **local** delivery hour — the hour the
market actually trades — which `hour_of_day_local` already carries as a declared
feature.

CLAUDE.md forbids local time for *resampling or alignment*. This is neither: no
row moves, nothing is reindexed, the matrix is only grouped. And because the
partition key is itself a declared, gate-closure-checked feature column, the
thing that decides which model sees a row is subject to the same guard as
everything else. `hour_key="utc"` selects the alternative — which smears each
model across two local hours as DST moves — and exists so the choice is visible
rather than baked in.

The partition column is dropped from its own model's design matrix: inside an
hour-model it is constant by construction, so it carries no information *there*.
The other clock column survives as a categorical, where it amounts to a
summer/winter indicator.

### 2. Everything is fitted in-fold, and applied frozen

Medians, MADs, standardisation moments, one-hot levels and the LASSO penalty are
estimated on the training window alone, stored, and then *applied* at predict
time — never recomputed. Scaling on the pooled train+test sample is the classic
invisible leak: nothing in the code looks like a future price, and the test set
still votes on the fit.

Two tests assert this behaviourally rather than by reading the code:
`test_a_rows_prediction_does_not_depend_on_the_rest_of_the_test_set` (predicting
one row alone returns exactly what predicting the whole block returned) and
`test_scaling_is_frozen_at_fit_time` (multiplying every *other* test row by a
thousand cannot move the first row's number). A scaler fitted on train+test
fails both.

The penalty is selected by a fixed rule applied per fold — AIC or BIC on the
LARS path, or a **time-ordered** cross-validation inside the training window. A
shuffled K-fold would let a later day pick the penalty for an earlier one, so
`TimeSeriesSplit` is asserted structurally in the tests.

### 3. The asinh variance-stabilising transform, inverted exactly

Power prices are heavy-tailed and go negative, so a log is unavailable and an
untransformed LASSO spends its whole coefficient budget on the 2022 spikes.
`asinh((y - a) / b)`, with `a` the in-fold median and `b` the in-fold MAD scaled
to a standard deviation, is defined on the whole real line, is near-linear in the
body of the distribution and compresses the tails. Predictions come back through
`a + b * sinh(z)`, the exact inverse — asserted to round-trip, and asserted to
work on a series shifted deep into negative prices.

`b` falls back from MAD to the standard deviation when more than half a sample
sits on one value, and to 1.0 only when a column is genuinely constant — which
is *reported*, because a constant price column in a training window is a data
problem, not a feature.

Back-transformed predictions are **not clipped**. A run that produces an absurd
price should show an absurd number rather than a tidied one; the fit report
carries the predicted min and max so it is visible either way.

### 4. NaN is answered, not absorbed — the question C3 handed to C4

The gate-closure mask leaves genuine holes (one per autumn DST day even in a
plain 24-hour lag — FINDING C3-A) and the lag warm-up leaves more. LASSO cannot
take NaN, so a policy is required, and only two are honest:

* **training rows** with any missing design cell are **dropped from the fit**
  (listwise). Nothing is invented. The count is reported per hour-model, and a
  test asserts that dropping a row is *equivalent* to the row never having been
  there — i.e. nothing was imputed behind the report's back.
* **test rows** with any missing design cell get **no prediction**. This is the
  committed default, `nan_policy="decline"`. `backtest/metrics.py` counts a
  declined hour as missing rather than shrinking the denominator, so declining
  costs the model coverage and cannot flatter it.

A missing *calendar* cell is treated as missing too, not as a row of zero
indicators — one-hot encoding a NaN would silently make it the reference level.
A category the training window never saw is counted (`n_predict_unseen_category_rows`)
rather than folded into the reference level without trace. A delivery hour the
training window never showed gets no model and no number.

`nan_policy="impute"` (in-fold column median, substituted on the raw scale) is
implemented and measured, not used by default — see the hand-off to C6 below.

## What is deliberately not here

* **No hyperparameter search across cycles.** The penalty is selected in-fold,
  per fold, by a fixed rule. The *rule* was chosen once, on the visible 2024
  validation year, by the margin rule stated in `backtest/run_c4_lear.py`, and is
  frozen thereafter.
* **No exogenous features.** Load and RES forecasts arrive in C7/C8. C4 is the
  price-only model, which is also exactly what Tier B will use for good.
* **No hand feature selection**, no interaction terms, no per-zone variants.
* **No intraday or multi-horizon anything.** One matrix, one target hour.

## Results, DE-LU 2024 (validation)

Expanding window from 2019, **daily refit**, 366 folds, 8,784 evaluation hours.
Every hour predicted exactly once; no day skipped.

| model | MAE | RMSE | bias | rMAE vs naive | coverage |
| --- | --- | --- | --- | --- | --- |
| naive same-hour-last-week | 32.80 | 55.22 | −1.52 | 1.000 | 1.00000 |
| **LEAR (AIC, committed)** | **22.86** | **36.92** | +2.60 | **0.697** | 0.99989 |
| LEAR (BIC) | 22.83 | 36.93 | +1.66 | 0.696 | 0.99989 |
| LEAR (time-ordered CV) | 22.90 | 36.93 | +2.74 | 0.699 | 0.99989 |
| LEAR (AIC, `nan_policy="impute"`) | 22.87 | 36.92 | +2.60 | 0.697 | 1.00000 |
| train-mean reference | 37.88 | — | — | — | 1.00000 |

Units are EUR/MWh. The single uncovered hour is the autumn DST hour discussed
under the C5/C6 hand-off below.

**LEAR cuts naive MAE by 30%.** That is a real model, not a reshuffled
baseline — and it is the number C9's gradient booster has to beat, and the
forecast error the battery will be dispatched against from C6.

**The three in-fold selection rules are within 0.35% of each other** (22.83 to
22.90). BIC wins by 0.17%, which is inside the 0.5% margin the runner commits to
in advance, so **AIC stays the default** — the cheapest and fully deterministic
of the three. The flatness is itself informative: the design matrix here has
only ~26 columns, so there is very little for a penalty to do, and the selected
alphas are tiny (near-OLS). The regularisation should start to matter in C8,
when exogenous load and RES features widen the design — so the comparison is
worth re-reading then, once, rather than per cycle.

**Full coverage is nearly free**: imputing the one holed hour instead of
declining it costs 0.001 EUR/MWh of MAE over the year. That is the measured
basis the C5/C6 hand-off below needs.

**The leak the guard refuses is worth everything.** On the day-shift probe,
feeding LEAR features from a day later gives MAE **0.000** — it recovers the
target exactly from the shifted `price_lag_24h` column, because that column then
*is* the target. Feeding it features a day staler costs 3.6 EUR/MWh (22.86 ->
26.48). The naive floor in C3 could not exploit the same leak at all. A
gate-closure guard is not paperwork.

## Reading the committed summary

`c4_lear_DE-LU_2024_summary.json` holds a few fields whose meaning is easy to
misread:

* **`representative_fit`** is *one* fit, on the first fold's training window
  (the model as it stood on the eve of the evaluation year), not an aggregate.
  The harness refits per fold by design and does not hand the fitted models
  back, so reporting 366 fit reports would be noise. Its `n_train_rows_*` and
  per-hour fields describe that window; its `n_predict_*` counters describe only
  that fold's target days, because that is the only block it was asked to
  predict. The run-wide coverage number lives in `scores`, and the run-wide
  declined-hour count is the difference between `n` and `n_scored` there.
* **`selector_comparison`** holds all three in-fold selection rules run over the
  same folds. `committed_selector` is the one frozen into `LearSpec`'s default
  by the margin rule in the runner's docstring.
* **`nan_policy_variant`** is the full-coverage `impute` run, reported for the
  C5/C6 hand-off (below). It is not the committed model.
* **`diagnostics.day_shift`** has `degrades_for_every_shift: false` for LEAR, and
  that is the expected answer, not a failure — see the next section.

## The three leakage assertions, re-run on a model that could exploit a leak

C3 ran PLAN.md's three probes against the naive floor. They are re-run here
against LEAR, because a baseline that reads a single lag column is not a
demanding test of a leakage guard.

One result needs stating plainly. On the day-shift probe, `shift=-1` feeds every
row the features belonging to the row 24 hours *later* — so the shifted
`price_lag_24h` column holds the target day's own price. The naive floor could
not use that (it reads only `price_lag_168h`, which any whole-day shift breaks in
both directions, which is why C3 saw both shift directions degrade). LEAR uses it
immediately, so `shift=-1` **improves** its MAE. `degrades_for_every_shift` is
therefore `false` for LEAR by construction.

That is the measurement, not the bug. What the probe establishes is that the
harness is sensitive to time at all; what refuses the leak on the real matrix is
the gate-closure guard, which rejects the same column whether it is declared
honestly (`after_gate_closure`) or smuggled in undeclared (`undeclared`). The
test suite asserts both refusals with LEAR in the harness, and separately
measures what the leak would have been worth to it.

## Hand-off to C5/C6 — the one hour a year with no forecast

The committed model declines to predict an hour whose design has a hole, and
over DE-LU 2024 that is exactly one hour: the 25th hour of the autumn DST day,
whose 24-hour lag the gate-closure mask had to blank (FINDING C3-A). For a
forecast-accuracy table that is the honest answer, and the metrics layer charges
it coverage.

The battery LP in C5/C6 cannot shrug in the same way: committing a schedule for a
market day needs a complete price vector for that day. So the `impute` variant is
run and scored here too, which leaves C6 with a measured choice rather than an
improvised one:

1. dispatch that one day from the `impute` forecast, with the substitution
   labelled in the results; or
2. exclude that day from the dispatch sample and report it as excluded.

Either is defensible; silently filling the hole inside the LP is not. The cost of
option 1 is in `nan_policy_variant`, measured on the hours both models predicted
so it is a comparison rather than two different evaluation sets.

## FINDING C4-A — a mean reference hands free skill to a median-like model

Running PLAN.md's assertion (iii) on LEAR produced `destroys_skill: False` in
both shuffle modes: real skill **+0.397** against the train-mean baseline, and
**+0.055** (hour-wise shuffle) / **+0.069** (whole-day shuffle) with the target
destroyed. Read at face value that says a model fitted on noise still has skill,
which would be alarming. It is not what happened, and the cause is the
reference, not the model.

`backtest/metrics.py` scores MAE, which is minimised by the **median**.
`backtest/diagnostics.py` measures skill against the train-**mean** baseline.
DE-LU 2019-2024 prices are strongly right-skewed — mean **95.65**, median
**66.18** EUR/MWh, the gap being the 2022 crisis — so a constant placed at the
training median beats a constant placed at the training mean by about **7%** of
MAE, on shuffled targets, knowing nothing whatsoever.

LEAR is a LASSO fitted in asinh space and mapped back through `sinh`: a
median-like estimator. So it collects that margin before it has learned
anything. The numbers, on the permuted 2024 evaluation set:

| predictor on shuffled targets | MAE (EUR/MWh) | skill vs train-mean |
| --- | --- | --- |
| train-mean baseline | 66.47 | 0 (reference) |
| **zero-information constant at the train median** | **61.95** | **+0.068** |
| LEAR fitted on shuffled targets | 62.78 | +0.055 |

The permuted model earns **less** than the zero-information constant. Re-based
on a median reference its skill is **negative** (−0.013), while the honest
model's stays clearly positive (**+0.380**). Shuffling the target destroyed
every bit of conditional skill; the probe's pass criterion was simply calibrated
for a mean-predicting model, which the naive floor is and LEAR is not.

### The whole-day shuffle, which is a different question

Under `mode="days"` the residue is larger: permuted skill **+0.069** against the
mean reference, and still **+0.013** against the median one. That mode permutes
whole market days, so it preserves the **within-day shape** — and
`backtest/diagnostics.py` says so in its own docstring, which is why it reports
that mode separately instead of using it as the pass/fail probe.

Measured rather than asserted: on the day-permuted 2024 set, a predictor that
knows nothing except the **per-local-hour training median** earns **+0.017**
over the global training median. That is more than the **+0.013** LEAR retains.
Under the hour-wise shuffle the same hour-of-day profile is worth **−0.001** —
nothing, because that shuffle destroys it too.

So the whole residue under day-permutation is the daily price profile, LEAR
extracts slightly *less* of it than a plain per-hour median does, and the
hour-wise shuffle — the probe that is meant to be decisive — leaves it with
negative skill. There is nothing conditional left in either case.

What was done about it:

* `forecast/models.py` gains `TrainMedianBaseline` — the zero-information
  constant as a first-class reference.
* `backtest/run_c4_lear.py` reports the re-based comparison alongside the
  original, under `diagnostics.target_permutation_against_median`, with both
  references refitted inside the same walk-forward so nothing is a different
  evaluation set.
* `tests/test_c4_lear.py::test_a_mean_reference_hands_free_skill_to_a_median_like_model`
  reproduces all three halves of the diagnosis on a deliberately skewed
  synthetic series, so the finding cannot be quietly un-learned. The ordinary
  near-symmetric test series does not show it at all — which is exactly why it
  surfaced only when LEAR met real prices.
* **`backtest/diagnostics.py` was not touched.** It holds a PLAN.md leakage
  assertion, and re-basing `destroys_skill()` is the kind of edit that makes a
  red probe green without anyone noticing. The proposal to re-base it is
  **NOTE C4-01**, recorded in `PROGRESS.md` for a human to decide.

The general lesson is worth carrying into C12: a skill score is a statement
about two things, and the reference is the half that is easy to get wrong. On a
price distribution this skewed, "beats the mean" and "beats the median" are
different claims and only one of them is about the model.
