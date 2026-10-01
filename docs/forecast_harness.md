# Forecast harness and leakage guard (C3)

What a bidder knew when they had to bid, how that is enforced mechanically, and
the walk-forward machinery the models in C4/C9 plug into. C1 got the prices onto
disk, C2 asserted they are what they claim to be; C3 is the layer that decides
which of those prices a forecast is *allowed to see*.

The naive model shipped here is not the point. The point is that by the time a
real model arrives, the pipeline can already be caught cheating.

## Modules

```
forecast/timing.py        market days, gate closure, publication times
forecast/features.py      the feature matrix + an information time per cell
forecast/leakage.py       the gate-closure guard, and the availability mask
forecast/models.py        the Model protocol, naive same-hour-last-week, train-mean
backtest/walk_forward.py  folds, the three per-fold guards, the run loop
backtest/metrics.py       MAE / RMSE / rMAE / skill (C12 owns the full layer)
backtest/diagnostics.py   PLAN.md's three leakage experiments as library functions
backtest/run_c3_naive.py  CLI: python -m backtest.run_c3_naive
tests/test_c3_timing_features.py    19 offline tests
tests/test_c3_leakage_harness.py    31 offline tests
```

Committed artefacts:

```
backtest/results/c3_naive_DE-LU_2024_predictions.csv.gz   every evaluated hour
backtest/results/c3_naive_DE-LU_2024_folds.csv            one row per refit
backtest/results/c3_naive_DE-LU_2024_summary.json         scores + diagnostics
```

## The one rule everything else follows from

Day-ahead bids for delivery day `D` close at **12:00 Europe/Brussels on `D-1`**.
Day `D`'s cleared prices are published at ~12:42–13:00 CET on `D-1` — *after* that
deadline. Therefore:

> At gate closure for market day `D`, a bidder knows every hourly price of market
> days `<= D-1`, and **no** hourly price of day `D`.

That is a statement about **market days** — local delivery days, the auction's own
unit — not about UTC days and not about raw hour offsets. The difference is not
cosmetic, and C3 found two places where it bites.

`config/data.yaml -> structural_dates` holds the three constants
(`day_ahead_gate_closure_local`, `..._tz`, `day_ahead_results_published_local`).
The guard's correctness depends only on the *ordering*
`gate_closure(D) < publication(D) < gate_closure(D+1)`, which
`GateClosureConvention` asserts on construction and a test asserts for every day
of a year. The exact publication minute does not matter.

## Finding 1 — a plain 24-hour lag leaks once a year

On the 25-hour local day each autumn, the 25th hour's `t - 24h` lands on **that
same market day's first hour** — a price published after the bidding deadline for
the very day being predicted. Six cells over DE-LU 2019–2024, one per year.

Masked to NaN, counted in the build report, never dropped: "unknown at decision
time" is the truth, and dropping the row would quietly shrink the evaluation set.
The 48h, 72h and 168h lags never reach that far forward, and 168h is weekday
aligned, which is why the naive baseline is unaffected.

## Finding 2 — NOTE C3-01, the daily aggregates cannot be built as specified

`config/features.yaml` declares `price_daily_{mean,min,max}_lag_24h` as
`aggregate: mean_over_utc_day` with `lag_hours: 24`. Read literally — the mean over
the UTC day containing `t - 24h` — that window is UTC day `D-1` for 23 of the 24
hours of target day `D`. For a CET zone, UTC day `D-1` ends at `D-1 23:00Z`, which
is **local midnight on `D`**: market day `D`'s own first cleared price. The literal
feature embeds one hour of the day it is predicting, on nearly every row. No
literal reading of the spec is leak-free.

`forecast/features.py` therefore builds those three columns over **the latest UTC
calendar day every hour of which was public at the row's gate closure** — derived
mechanically from the publication calendar, not hardcoded; for the CET/CEST zones
in scope that resolves to UTC day `D-2`. The committed column *names* are kept, so
config stays the single source of truth, but `lag_24h` in those names is now a
misnomer.

**A human decision is requested** on whether `features.yaml` should rename them
(`..._prev_available_utc_day`) and restate the aggregate. Proposed, not done:
editing a feature spec so that a leak disappears is exactly the move CLAUDE.md
warns about, so the leak is documented and the code is conservative instead.

A UTC day holding fewer than 24 hours yields NaN statistics rather than a mean
over a short day, and the count of such days is reported (2 for DE-LU: the two
partial days at either end of the stitched series).

## The feature matrix

`build_features` returns a `FeatureMatrix`: the feature frame, an
**identically-shaped frame of information times**, the target, the per-row gate
closure, and the market-day label. They travel together because a feature frame
separated from its information times is a feature frame nobody can check.

* Calendar columns carry `NaT` — they embed no market information. A test asserts
  they are bit-identical when rebuilt on shuffled prices, so nothing price-derived
  can hide in a column declared deterministic.
* Price columns carry the **publication instant of the auction that set the price
  they came from** — not the price's own timestamp. This is what lets the guard see
  that "yesterday's 23:00Z price" is, for a CET zone, *today's* market day.
* Lags are taken by explicit UTC offset reindexing, never `.shift(n)`. `shift`
  counts rows, so across a missing hour it returns the price from 25 hours earlier
  and calls it a 24-hour lag — a modelling bug that looks exactly like clean data.

## The guard

`forecast/leakage.py` checks the whole matrix in one pass and is deliberately
fail-closed. Violation kinds:

| kind | meaning |
| --- | --- |
| `undeclared` | a feature column with no declared information time |
| `after_gate_closure` | the cell's information was published after its row's deadline |
| `missing_information_time` | the cell has a value but no information time |
| `deterministic_with_information` | a calendar column carrying a market information time |
| `malformed_information_time` | a declaration that is not a UTC timestamp column |
| `stale_declaration` | an information time declared for a column that is not there |

`undeclared` is the one that matters most in an unattended build: it is what
catches a later cycle adding a column and forgetting the bookkeeping.
`malformed_information_time` exists because one careless assignment turns a
timestamp column into `object` or tz-naive dtype, and comparing that against a
tz-aware gate closure raises an opaque `TypeError` from inside pandas — in a guard,
the worst outcome is a check that neither passes nor fails. A tz-naive column
holding real timestamps is reported, not assumed to be UTC.

`mask_unavailable` is the companion: where a cell genuinely was not knowable, the
honest value is NaN, and the count per column is reported rather than silent.

## The walk-forward harness

A fold is one refit. `refit_every_days` sets how many consecutive evaluation days
share a fitted model; the training window always ends the day **before the first**
day of the block, so a weekly refit means the last day of the block is predicted
by a six-day-stale model — what a weekly-refit desk actually experiences, not a
bug. `train_window_days` switches expanding (`None`) to rolling. The harness takes
a model *factory* and calls it once per fold, so no fold can inherit state fitted
on a later fold's data (asserted).

Three guards run on every fold:

1. **Training targets must have been public.** Asserted against the real
   publication calendar for the latest training day actually in the fold, not
   inferred from the day arithmetic.
2. **Features must have been public.** Both the training and the test matrix go
   through the gate-closure guard, per row, against that row's own gate closure.
3. **Sealed years are refused**, before a single fold is built.

Evaluation days with insufficient history are skipped *with a recorded reason*,
never padded over.

## PLAN.md's three leakage assertions, and what they establish

Run on the real DE-LU pipeline (2024 validation, daily refit, expanding window
from 2019) by `python -m backtest.run_c3_naive`, and on synthetic series in
`tests/test_c3_leakage_harness.py`.

**(i) Shifting the feature matrix forward one day degrades metrics.** Aligned MAE
32.80 EUR/MWh; one day staler 36.66; one day fresher 36.04. Both directions hurt,
because `price_lag_168h` shifted either way stops being the same weekday — so the
*sign* of the shift effect is not itself a leakage detector. What this establishes
is that the harness is sensitive to time at all, which is the precondition for (ii)
meaning anything.

**(ii) A deliberately inserted future-timestamped feature is caught.** A
`price_lead_24h` column declared honestly is rejected as `after_gate_closure`;
smuggled in undeclared it is rejected as `undeclared`. Both routes closed, and the
walk-forward refuses to run on the injected matrix. A separate test measures what
the leak would have been *worth* on a persistence-dominated series — more than
halving MAE — which is why the guard has to make it impossible rather than
discouraged.

**(iii) Target permutation destroys skill.** Skill is measured against a train-mean
baseline run through the same harness. DE-LU 2024: real skill +0.134, hour-wise
permuted −0.130, whole-day permuted −0.105. Both negative: a model fitted on
shuffled targets is worse than a constant.

## Results, DE-LU 2024 (validation)

| model | MAE | RMSE | bias | hours |
| --- | --- | --- | --- | --- |
| naive same-hour-last-week | 32.80 | 55.22 | −1.52 | 8,784 |
| train-mean baseline | 37.88 | — | — | 8,784 |

366 folds, every evaluation hour predicted exactly once, zero skipped days, zero
missing predictions.

The naive model beats the train-mean baseline by only 13%, which says more about
the baseline than the model: an expanding window from 2019 puts the 2022 crisis in
the training mean, so the constant reference sits around 99 EUR/MWh against a 2024
realised mean nearer 78. It is a deliberately weak reference, used here only as the
denominator for the permutation test. **rMAE against the naive model** is the
comparison that matters, and that is C12's job.

## Deliberately out of scope in C3

* Any exogenous feature (C7/C8, needs ENTSO-E).
* LEAR (C4) and the gradient booster (C9).
* The full metrics layer — daily-spread error, within-day Spearman, capture ratio,
  block-bootstrap CIs (C12).
* Tier-B zones (C10) and the battery LP (C5/C6).
* The 2025 holdout, which stays sealed until Checkpoint C (C16).
