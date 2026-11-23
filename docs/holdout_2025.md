# The 2025 holdout: the one evaluation, and what it says

**The sealed 2025 holdout was evaluated once, on 2026-11-23, between
10:17:59Z and 11:23:13Z, at git SHA `1c19eb0`.** Nine zones, 273 market days
(2025-01-01 to 2025-09-30), three curves, zero invariant flags. The run is
recorded in `backtest/results/c17_holdout_run_ledger.json`, which refuses a
second evaluation and has no override flag. Every number below comes from
artefacts that run wrote.

This file is the pre-registered write-up named in
`c16_preregistration.json` (`outputs.write_up`). It reports what the holdout
says, what it does not say, and the one correction a reader should apply before
believing the headline.

## 1. What was fixed before the seal was broken

`backtest/results/c16_preregistration.json` was written and committed at
Checkpoint C **while 2025 was still sealed**. It fixed the window, the nine
zones, the three curves, the model specifications, the walk-forward
configuration, the battery, the metric list, the bootstrap, and the 2024
baseline the holdout would be read against. The preflight checked all fifteen
frozen specifications field by field against that file before the evaluation
started: **zero disagreements**.

One pre-registered condition was **not** met, and was approved as a deviation
rather than waived. The pre-registration pins
`library_fingerprint 856fb19ac0c4eecd`, which includes the CPython patch
version 3.11.17 — an interpreter that cannot be installed in the container
these cycles run in. The owner approved running under **CPython 3.11.18** with
the five numerical libraries at exactly their pinned versions
(`numpy 2.4.6`, `pandas 3.0.6`, `scikit-learn 1.9.1`, `scipy 1.17.1`,
`lightgbm 4.7.0`), recorded in `backtest/results/c17_environment_approval.json`
and in `PROGRESS.md`. **The 2025 rows therefore carry
`library_fingerprint 00a12bd6aadb09f3`, not the pre-registered one**, and the
gate was not loosened in general: any other interpreter or library set still
blocks. `docs/c17_environment.md` has the full reasoning, and FINDING C20-C is
the relevant evidence — an independent clone under a *third* library set
reproduced the published per-day dispatch numbers to 4.3e-07 EUR.

## 2. The headline

The comparable arm: C4's LEAR on price and calendar features only, expanding
window from 2019, dispatched through C5/C6's rolling-horizon LP on a
commit-then-settle basis — the forecast schedule is frozen and then valued at
realised prices, never at the prices it was optimised against.

| zone | capture | 95% interval | EUR/MW/yr | lost vs oracle | MAE | rMAE | within-day Spearman |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ES | 0.9504 | [0.9196, 0.9821] | 66 931 | 3 496 | 18.70 | 0.665 | 0.8962 |
| DE-LU | 0.9439 | [0.9089, 0.9778] | 89 910 | 5 348 | 22.37 | 0.695 | 0.8737 |
| NL | 0.9251 | [0.8864, 0.9644] | 89 414 | 7 240 | 21.29 | 0.701 | 0.8750 |
| BE | 0.9125 | [0.8803, 0.9446] | 80 514 | 7 718 | 20.36 | 0.673 | 0.8652 |
| IT-North | 0.9026 | [0.8626, 0.9412] | 40 793 | 4 400 | 9.82 | 0.672 | 0.8960 |
| DK1 | 0.8962 | [0.8514, 0.9410] | 77 148 | 8 940 | 26.64 | 0.706 | 0.7928 |
| PL | 0.8909 | [0.8555, 0.9255] | 92 224 | 11 293 | 21.65 | 0.725 | 0.8380 |
| FR | 0.8706 | [0.8362, 0.9036] | 62 358 | 9 269 | 19.43 | 0.620 | 0.8609 |
| NO2 | 0.7572 | [0.7035, 0.8127] | 30 219 | 9 689 | 15.66 | 0.631 | 0.7202 |

Intervals are the paired circular moving-block day bootstrap, 10 000
replicates, seed 20261009, at PLAN.md's literal daily block. Source:
`c17_holdout_2025_metrics.csv` and `c17_holdout_2025_intervals.csv`.

**The ordering invariant holds out of sample in all nine zones.** Pooled over
the window, `naive <= forecast <= oracle` everywhere: the naive floor captures
0.5726 (NO2) to 0.9083 (ES), the forecast 0.7572 to 0.9504, the oracle 1.0000
by construction. The per-day same-start oracle bound — the one CLAUDE.md
requires to hold on *every* day, not on average — was asserted inside the run
and did not fail. `c17_holdout_2025_invariant_flags.json` is empty.

## 3. The finding: the forecast got absolutely worse and economically better

Capture came out **above every visible year in seven of the nine zones**. That
is the kind of result that is usually a bug, so the obvious confound was
removed first.

**The correction.** The holdout window is 273 days ending 2025-09-30, because
PLAN.md stops the main hourly backtest the day before the SDAC 15-minute
go-live. The visible years are full calendar years. So every visible year was
re-aggregated over **January-September only**, from the same committed per-day
rows, by the same definitions (`backtest/run_c17_summary.py`,
`c17_like_for_like.csv`). Nothing was re-fitted. On that like-for-like basis
the holdout is above every visible year in **six** of nine zones rather than
seven, and inside the visible range in the other three (FR, IT-North, PL). The Q4 term is
real but small and two-sided: over the 44 visible cells (excluding NO2 2020,
the thin-regime cell of FLAG C13-01, where it is meaningless) including
October-December moves a zone-year's capture by a median of −1.04 percentage
points, range −7.95 to +8.34, negative in 26 of 44 and larger than 5pp either
way in 7. So the short window is *mildly* favourable on average, and the
correction it justifies is about one percentage point — against changes over
2024, on the same basis, of −0.6pp (PL) to +11.7pp (NO2).

**What actually moved.** Against 2024, on the like-for-like basis:

| | direction | zones |
| --- | --- | --- |
| pooled MAE | **up** (worse) | 9 of 9 |
| mean realised daily spread | up | 9 of 9 |
| `error_over_headroom` (MAE / spread) | **down** (better) | 9 of 9 |
| within-day Spearman | up (better) | 9 of 9 |
| capture ratio | up | 7 of 9 |

The forecast's absolute error rose in every single zone — DK1 from 21.15 to
26.64 EUR/MWh, NO2 from 11.33 to 15.66 — and the captured share of
perfect-foresight value rose anyway, because the spread available to trade rose
faster. **This is FINDING C13-D confirmed on a year the model never saw**: what
predicts capture across regimes is not the forecast error but the error
relative to the headroom, and 2025 has the lowest `error_over_headroom` of any
year in all nine zones. It is also a direct out-of-sample refutation of the
intuition that a lower MAE means more captured value — here the two moved in
opposite directions in nine zones out of nine.

The ordering mechanism moved with it. The within-day Spearman — the only
point-forecast metric that tracked capture across regimes in C12 (FINDING
C12-C) — rose in all nine zones, most of all in NO2 (0.6106 to 0.7202), which
is also the zone whose capture rose most (+11.7pp on the like-for-like basis).

## 4. NO2 stays last, and stays the thing to explain

NO2 is bottom of the nine on capture (0.7572) and bottom on the within-day
Spearman (0.7202) in the holdout year, as it was in all five visible years
(FINDING C13-C). It closed a lot of ground — its capture is 14.3pp above the
pre-registered 2024 baseline and its loss-making day count fell from 25.8% of
dispatched days in 2024 to **11.0%** in 2025 (30 of 273) — but the ranking did
not change. Two earlier explanations stay dead: the thin-spread story (FINDING
C13-E) and the friction story (FINDING C15-E). The within-day ordering story is
the one still standing, and the holdout is consistent with it rather than a
test that could have killed it.

## 5. What the holdout does not establish

- **It is one year, and the comparison against 2024 is unpaired.** Two
  different years share no market day, so the intervals in the table are the
  holdout's own sampling uncertainty, not the uncertainty of the *difference*
  against 2024. Three of nine zones' 2025 intervals exclude the pre-registered
  2024 point (DK1, ES, NO2); six do not. Read "2025 is better" as directional.
- **The expanding window confounds the year.** A 2025 fold trains on 2019-2024;
  a 2024 fold trained on 2019-2023. FINDING C10-B measured that three extra
  years of price history were worth more than the entire honest exogenous
  block, so part of the improvement is almost certainly training-set size
  rather than anything about 2025. Separating the two needs a deliberate second
  experiment with the training window held fixed — which is a *new* experiment,
  not a re-run, and must be labelled as one.
- **The nine-zone capture band is not a regime effect.** FINDING C13-A and
  FINDING C13-B stand: a band measured in one year is the same size as a single
  zone's movement across years. The holdout's 19.3pp nine-zone band is one more
  year's draw, not a measurement of how much regimes differ.
- **No exogenous arm was evaluated on the holdout.** The pre-registration's
  headline is price-only, and NOTE C8-01 had already closed the honest
  exogenous block as not worth having in any zone, year or model class. The
  Tier-A 2025 ENTSO-E documents were fetched and are in the manifest; they were
  not used for a holdout number.
- **FLAG C5-01 is unchanged.** The LP admits simultaneous charge and discharge
  under sufficiently negative prices, and it did so again in 2025 (oracle
  curve: 21 days in DE-LU, 19 in NL, 17 in BE, 16 in PL, 11 in FR, 6 in DK1; 0
  in ES, IT-North and NO2). This was reviewed at Checkpoint B and resolved as a
  stated limitation, with the MILP variant measured and the pure LP kept as the
  default. It is a limitation of the dispatch model, not a holdout finding.
- **Everything in `PLAN.md`'s limits list still applies**: day-ahead only, no
  intraday re-optimisation, no ancillary services, no per-zone grid fees or
  levies, price-taker, hourly resolution, and the 2025 window stopping at the
  15-minute cutover.

## 6. Reproducing it

```
python -m backtest.run_c17_holdout --phase preflight     # computes nothing
python -m backtest.run_c17_summary                       # the like-for-like read
python -m backtest.run_c17_figures                       # the three figures
```

The evaluation itself will refuse to run again: the ledger records it as
completed, and there is no override flag, because a second evaluation of a
sealed holdout is a human's decision and has to be labelled as one.
