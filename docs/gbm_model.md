# GBM — the gradient-boosted price model (C9)

The third and last model of the family, and the one that exists to answer a
single question: **is there structure in these features that a per-hour LASSO
cannot express?**

Day-ahead price formation is a merit-order stack — piecewise, kinked,
saturating. Residual load is exactly the kind of driver whose effect on price is
flat over most of its range and violent at the top of it. A linear model can fit
one slope through that; a tree ensemble can fit the kink. So the booster is the
natural second shape to try, and C8 left two concrete things for it to settle.

```
forecast/gbm.py               GbmSpec, GbmModel, early_stopping_split
backtest/run_c9_gbm.py        CLI: python -m backtest.run_c9_gbm
tests/test_c9_gbm.py          51 offline tests
```

Committed artefacts, per Tier-A zone:

```
backtest/results/c9_gbm_<ZONE>_2024_predictions.csv.gz   realised + 4 GBM arms + 4 LEAR arms + naive
backtest/results/c9_gbm_<ZONE>_2024_folds.csv            one row per refit, with each arm's chosen round count
backtest/results/c9_gbm_<ZONE>_2024_summary.json         scores, both ladders, model comparison, early-stopping report, day-shift diagnostic
```

## What PLAN.md allows, and why the restriction is the interesting part

> **one fixed LightGBM config, in-fold early stopping, no hyperparameter search
> across cycles.**

That is not frugality. This project is built by unattended cycles that each see
the 2024 validation metrics and have no memory of each other. A booster has a
dozen knobs. Nudging one after seeing a 2024 number and keeping the nudge is
overfitting the validation year *through the agent* rather than through the
code, and it leaves no trace in the diff — the next cycle just finds a slightly
different literal and no reason to doubt it.

So the config is defended structurally rather than by good intentions:

- `GbmSpec` is a frozen dataclass, and every value is either a LightGBM default
  or a standard choice stated with its reason (see the module docstring). None
  was chosen by looking at a score.
- `GbmSpec.fingerprint()` is a 16-hex-character hash of every committed value,
  written into every result row. Two runs with the same fingerprint used the
  same configuration; a cycle that quietly changed one knob cannot produce a row
  claiming otherwise.
- `test_the_committed_config_is_exactly_what_plan_md_froze` pins all seventeen
  values to literals, and `test_the_fingerprint_changes_when_any_knob_changes`
  pins that the hash is sensitive to each of them. A later cycle that wants to
  tune has to **edit a test** — which CLAUDE.md makes a flag-and-stop event.

The committed configuration:

| | value | why |
|---|---|---|
| `objective` | `regression` (L2) | the default loss; choosing L1 *because* MAE is the reported metric would be metric-chasing |
| `learning_rate` | 0.05 | below the 0.1 default; with early stopping choosing the rounds, a smaller step is the standard trade |
| `num_leaves` | 31 | LightGBM default |
| `min_data_in_leaf` | 20 | LightGBM default |
| `feature_fraction` / `bagging_fraction` / `bagging_freq` | 0.9 / 0.9 / 1 | conventional mild stochastic regularisation; both seeds fixed |
| `lambda_l1` / `lambda_l2` | 0.0 / 1.0 | a nominal ridge on leaf values, which the default leaves unshrunk on a heavy-tailed target |
| `num_boost_round` | 2000 | a cap high enough that early stopping, not the cap, ends the fit — reported per fold |
| `early_stopping_rounds` | 50 | conventional |
| `early_stopping_days` | 90 | a *fold* choice: ~2 160 rows is enough to see a validation curve turn, and short enough that the fitting set still ends near the fold |
| `refit_on_full_window` | `True` | see below |
| `seed` / `deterministic` / `force_row_wise` / `num_threads` | 20260101 / `True` / `True` / 4 | a bit-reproducible fit; LightGBM's histogram construction is otherwise thread-count dependent |

## The four decisions that carry the model

### 1. Pooled over delivery hours, with the hour as a categorical feature

This is the deliberate asymmetry with LEAR, and it is how a booster is actually
used. LEAR partitions into 24 models because a ~30-parameter linear model per
hour is estimable from ~1 000 rows, and pooling would force one slope to
describe hour 03 and hour 18 at once. A tree ensemble has the opposite problem:
splitting the sample 24 ways starves all 24 boosters, while one pooled model can
*learn* the hour interaction from a split on `hour_of_day_local` wherever the
data supports one and ignore it where it does not.

The consequence is stated rather than hidden, in the module docstring, in the
runner, and in the summary's `model_comparison.note`: **a GBM−LEAR difference is
a difference of functional form *and* of pooling, and this cycle cannot separate
the two.** What it can do is measure the same four exogenous arms LEAR was
measured on, so the *within-model* differences — which is what FINDING C8-A
turns on — are re-measured under a second functional form instead of inherited
from the first.

`day_of_week`, `month`, `hour_of_day_local` and `hour_of_day_utc` are handed to
LightGBM as unordered categories; the set is read from the same two constants
LEAR one-hot encodes (`CATEGORICAL_CALENDAR`, `HOUR_KEYS`), so the two models
cannot drift apart about what is a category and what is a number. The codes are
the *values themselves* (hour 0-23, ISO weekday, month 1-12), not positions in a
fitted level list, so a level the training window never saw cannot shift the
meaning of another one.

### 2. The target transform is LEAR's, imported rather than re-implemented

`asinh((y − a) / b)` with `a` the in-fold median and `b` the in-fold MAD,
inverted exactly by `a + b·sinh(z)`. The helpers come straight from
`forecast.lear` **on purpose**: an *identical* transform is what makes the model
comparison a comparison of functional form rather than of loss scale, and
importing is the only way to guarantee it stays identical as the code moves.

Trees are invariant to monotone transforms of a *feature*, so no feature is
transformed (LEAR's per-column price VST is pointless here and is not used).
They are very much not invariant to one of the *target*: L2 boosting on raw
European power prices spends its whole budget on the 2022 spikes.

### 3. Early stopping is in-fold, and the fold is split by time

The number of boosting rounds is the one quantity that must adapt per fold, and
therefore the only place a GBM fold could look forward. `early_stopping_split`
takes the last `early_stopping_days` **market days** of the training window as
the stopping set and everything strictly before them as the fitting set:

- the split is by *day*, not by row — half a day on each side would put a row's
  own near neighbours across the split and make the stopping curve optimistic;
- it is strictly time-ordered, asserted rather than assumed;
- the stopping set is inside the training window, which the harness has already
  asserted was public at the fold's gate closure, so it never touches the test
  fold.

`test_early_stopping_uses_only_training_days` checks this against the fold's own
day sets rather than by reading the code, and the chosen round count is reported
per fold — so a run where the boosting *cap*, not the stopping curve, ended the
fits is visible rather than silent (`n_folds_hitting_the_round_cap`).

**The refit.** With `refit_on_full_window=True` the model is then refit on the
whole training window for the chosen number of rounds. The alternative throws
away the most recent 90 days — the days most like the one being predicted —
purely as a side effect of having used them to choose a round count. The refit
sees those days' targets, which is in-fold model *selection*, not leakage: every
one of them was published before the fold's gate closure.

**A trap worth naming.** `lgb.train` does not discard the trees built *after* the
best iteration while early stopping discovers it; it only records which
iteration was best. A booster therefore generally holds more trees than the
model should use, and predicting with `num_trees()` would quietly serve the
overfit tail that early stopping existed to reject. The round count is carried
explicitly in `n_iteration_` and passed to every predict call;
`test_the_overfit_tail_after_the_best_iteration_is_never_predicted_with` pins
both the gap and the fact that the two counts give different answers.

### 4. Missing cells are routed, not invented

LightGBM takes NaN natively and learns a default side for each split, so under
the default `nan_policy="native"` the booster predicts hours the committed LEAR
declines — a real property of the model, not a trick, but one that makes raw
coverage differ between the two. So every comparison in the summary is read off
a `common_hours` block scored on the hours all models and all arms predicted;
`nan_policy="decline"` exists to mirror LEAR's listwise refusal exactly.

What the routing can and cannot do: the gate-closure mask writes NaN into cells
that were not yet public, so missingness is itself a pattern the booster can
split on — but it is a pattern derived from the publication calendar, which is
public, and never from the target.

A training row with a NaN *target* cannot be fitted and is dropped (counted); a
row with a NaN *feature* is kept and routed.

## The leakage assertions, and FINDING C9-A

The booster inherits every guard without a door of its own: the harness runs the
gate-closure check on both matrices of every fold, `data.holdout` refuses a
sealed year before a fold is built, and `res_as_published` goes through exactly
C8's acknowledgement path (`assert_only_acknowledged_leakage` over the whole arm
matrix, which demands the only violations anywhere are `after_gate_closure` on
exactly the declared RES columns, late by exactly what the declared publication
clock predicts).

PLAN.md C3's three assertions are re-run on the booster:

- **(ii) a deliberately inserted future feature must be caught.** Both the
  declared and the smuggled variant raise, and
  `test_a_leading_feature_would_be_worth_a_lot_to_the_gbm` measures what the
  guard is protecting: on a persistence-dominated series a 24-hour lead cuts MAE
  by more than 20%.
- **(iii) target permutation must destroy skill.** It does, on a near-symmetric
  series. (On a *skewed* one, read FINDING C4-A first: the probe's reference is
  the train mean, and a median-like estimator — which a booster fitted in asinh
  space is — collects a margin there before it has learned anything.)
- **(i) a one-day-staler feature matrix must score worse.** This one needed more
  care, and produced a finding.

### FINDING C9-A — assertion (i) is vacuous for a pooled booster on a periodic series

C3 asserts (i) against `NaiveLastWeek`, which *is* `price_lag_168h`, so
misaligning the matrix necessarily wrecks it. Run the same experiment with the
GBM on the same synthetic week-periodic fixture and the staler matrix scores
**better** (MAE 1.716 against 1.759).

That is not a bug and not a leak. The pooled booster also holds
`hour_of_day_local`, `day_of_week` and `month`, and on that fixture the price
shape is an exact deterministic function of those three. The lagged prices are a
*noisier restatement* of a signal the calendar gives for free — each lag carries
its own copy of the noise term — so the best available model on that series
ignores the lags, and misaligning them nudges the booster towards doing exactly
that. The aligned MAE (1.759) is already within 10% of the 1.596 noise floor
that no model can beat, which is the tell.

So assertion (i) is only informative on a series where the lagged prices carry
something the calendar cannot. The response was not to weaken the assertion but
to move it to where it means something, in three places:

1. `test_shifting_the_features_forward_a_day_degrades_the_gbm` runs it on the
   **persistence-dominated** synthetic series, where it passes decisively.
2. `test_the_day_shift_assertion_is_vacuous_for_this_model_on_a_periodic_series`
   pins the vacuity *and its reason*, so nobody later reads a passing
   periodic-series shift test as evidence of anything.
3. `backtest/run_c9_gbm.py` runs the assertion on each zone's **real prices** at
   the committed config, and records the number in
   `summary.day_shift_diagnostic`. This is where the assertion is actually
   established for this model.

Nothing in `tests/test_c3_leakage_harness.py` is touched. Its assertion is about
the naive floor and remains true of it.

## How LEAR enters the comparison

LEAR is **not refitted** in C9. C8 committed its predictions for all four arms
on each Tier-A zone, for 2024, on the same aligned 2022-01-01 training window and
the same daily-refit walk-forward spec. Refitting would spend an hour of compute
to reproduce a committed number, and would quietly allow the two models to be
compared on different folds if any spec drifted.

Instead `load_c8_lear_predictions` loads the artefact and **asserts** its index
and its realised prices against this run's, rather than reindexing onto them: a
mismatch means the two cycles did not evaluate the same hours, which must be a
loud failure. A clean match is also a re-verification of C8's committed artefact
against a freshly re-pulled cache. `--no-lear-reference` skips it.

## Results — 2024 validation year, Tier A

<!-- RESULTS -->

## Limitations, stated

- **Pooling and functional form are entangled.** See decision 1. A cycle that
  wants to separate them would need a per-hour booster or a pooled LEAR, and
  either is a new model, not a knob.
- **One configuration, never tuned.** That is PLAN.md's instruction and it is
  the right one here, but it means the GBM is not shown at its best — only at a
  defensible default. Any statement of the form "trees do not help on this
  problem" must carry that caveat.
- **The round count is the only adaptive quantity.** Everything else is frozen
  across 366 folds and three zones with very different price-formation regimes.
- **Split-gain importances are descriptive only.** They are reported for the
  last fold of each arm and are never used to select a feature, which would be a
  search by another name.
- **The fingerprint covers what we set, not LightGBM's own defaults.** Anything
  `GbmSpec.booster_params()` does not name — `max_cat_threshold`,
  `min_data_per_group`, `max_depth` and the rest — comes from the installed
  LightGBM, so the fingerprint pins *our* configuration and the
  `lightgbm>=4.3` floor in `requirements.txt` pins the rest only loosely. A
  major-version bump that moved a default would change results without changing
  the fingerprint. C9's runs were made with **lightgbm 4.7.0**, recorded in the
  C9 entry of `PROGRESS.md`; the right home for library provenance is C10's
  append-only results layer, which PLAN.md already tags with the git SHA and
  config hash, and that is where it should be added rather than bolted onto this
  cycle's summaries after the fact.
