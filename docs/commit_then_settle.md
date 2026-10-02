# Commit-then-settle, the two oracles, and capture (C6)

`docs/battery_lp.md` covers the LP, the market-day horizon, the terminal mark and
the simultaneity artefact. This file covers what C6 added on top: running **more
than one price curve** through that machinery and checking that the values stand
in the order PLAN.md and CLAUDE.md require.

Numbers below are DE-LU, 2024, the committed 1 MW / 2 MWh asset. They are the
Checkpoint B material.

## The three curves

| curve | decision prices | role |
| --- | --- | --- |
| `oracle` | realised | perfect foresight; the ceiling and every denominator |
| `model` | LEAR, from C4's committed walk-forward artefact | what a desk could actually have bid |
| `naive` | same hour last week | PLAN.md's floor |

The forecast is **read from C4's artefact, not re-fitted**, so the schedule
dispatched here is built from exactly the forecast C4 scored and the two cycles
cannot drift apart. `load_prediction_curves` asserts that the artefact's `y_true`
matches the realised series hour for hour before anything is dispatched — an
off-by-one forecast index is a leak that looks like skill, and it would show up
as a model that beats the oracle only *after* a day had been committed.

## Commit-then-settle, structurally rather than carefully

CLAUDE.md: *never report an LP's own objective value from a run solved on
forecast prices as if it were the realised value*. The machinery makes that hard
to do by accident rather than relying on discipline:

* `run_rolling_dispatch` takes `decision_prices` and `realised_prices` as
  **separate arguments**. The schedule comes from the first; `value_schedule`
  settles it against the second.
* Every `DayValuation` carries `prices_are_decision_prices`, and only an oracle
  run may set it.
* `assert_settlement_is_not_a_readback` re-derives the truth from the schedules —
  comparing each day's decision vector against the realised one — and requires
  the flag to agree with what it finds. A forecast run that *claims* to be a
  read-back fails; a perfect forecast that happens to equal realised prices does
  not, because that is legitimate.

The gap is large enough to matter: on a single DE-LU day the LP's objective
solved on the LEAR forecast exceeds the money that schedule actually made by
tens of euros on a day worth a few hundred. Over a year it is the difference
between claiming ~100% capture and measuring 87%.

## Two oracles, and which question each answers

The per-day bound `value(curve @ realised) <= value(oracle @ realised)` is exact
**only** between schedules solved from the same opening SoC against the same
mark, because the candidate is then a feasible point of the oracle's own problem.

* **Same-start oracle** (`same_start_oracle`) — re-solved each day from *the
  candidate run's own opening SoC*. This is the theorem. It is asserted on
  **every** dispatched day, not a sample, for both the model and the naive curve.
  Measured worst excess on DE-LU 2024: **exactly 0.0 EUR** for both.
* **Rolled oracle** — one continuous perfect-foresight trajectory. This is the
  annual ceiling, and the subject of the pooled comparison.

Across two independently rolled trajectories the opening SoCs diverge and **no
per-day bound exists**. On DE-LU 2024 the model out-earned the *rolled* oracle on
**50 of 365 days**. That is expected, it is counted rather than asserted away,
and it is the reason the same-start oracle exists. `tests/test_c6_commit_then_
settle.py` demonstrates the mechanism as a controlled experiment: a run opening a
day full, committed on an imperfect forecast, beats perfect foresight that opened
the same day empty — and `assert_oracle_dominates` *refuses* that comparison
rather than reporting a breach, because the two are not the same problem.

## Two capture ratios, and why they differ

Both are reported, because quoting one without the other would overstate the
result:

| | DE-LU 2024, model | naive |
| --- | --- | --- |
| **rolled** capture (annual cash / oracle cash) | **0.9187** | 0.8471 |
| **same-start** capture (pooled `value_added`) | **0.8696** | 0.7797 |
| mean of the daily same-start ratios | 0.8204 | 0.6985 |
| median daily same-start ratio | 0.9018 | 0.8176 |

The rolled ratio is the higher of the two and it is the flattering one: part of
what it credits to the forecast is the forecast run's trajectory happening to
open some days in a better state than the oracle's did. The same-start ratio is
bounded above by 1 **by construction** on every single day, so it is the honest
per-day answer. The mean of the daily ratios is lower again than the pooled
ratio, which says what it always says about power prices: value is concentrated
in a few high-spread days, and capture is *better* on those days than on the
quiet ones.

Capture is left **undefined (NaN)** on a day where perfect foresight itself adds
nothing — a flat curve, or a day the opening state fully determines. Filling it
with 0 would punish every model on every flat day and filling it with 1 would
flatter them. DE-LU 2024 has no such day; the mechanism is tested on a synthetic
flat series instead.

## "Doing nothing is feasible" is a statement about the *decision* problem

C5 asserts `value_added >= 0` on the oracle run, reasoning that standing still is
always feasible so the optimum cannot lose. That is true of the problem the LP
solved. For a forecast curve the decision prices and the realised prices are
different vectors and it **does not transfer**: a schedule frozen on a wrong
forecast can lose money at realised prices.

So C6 states the theorem about the problem it is a theorem about
(`check_decision_value_added_non_negative`, asserted on the decision prices, all
three curves, holds) and *reports* the realised-price losses
(`report_realised_losses`) as what they are — a result:

| curve | losing days | total |
| --- | --- | --- |
| oracle | 0 of 366 | 0.00 EUR |
| model | 3 of 365 | −41.37 EUR |
| naive | 17 of 366 | −662.52 EUR |

This is one of the more decision-relevant numbers in the project: a desk cares
about the left tail, not only the mean. Forecast error does not merely forgo
upside — on ~1% of days it turns the day's trading into an outright loss, and
the naive floor does it six times as often and sixteen times as expensively.

## Curves are pooled over a common day set

A curve with a hole in its forecast skips that day (`dispatch.rolling` skips,
never patches). The oracle has no holes, so the runs end with different day
counts, and summing each over *its own* days would compare a 365-day total
against a 366-day one. `common_days` intersects them; every pooled number is
computed over that intersection and the excluded days are listed per curve.

On DE-LU 2024 that is one day — 2024-10-27, the 25-hour autumn DST day, whose
25th hour has no LEAR forecast under the committed `nan_policy="decline"`
(FINDING C3-A). See NOTE C4-02 in `PROGRESS.md` for the decision and what the
alternative was measured to be worth.

## The pooled ordering

`pooled_comparison` asserts PLAN.md's C6 requirement on the common day set:

| | cash, 365 days | EUR/MW/yr |
| --- | --- | --- |
| oracle | 74,365.45 | 74,399 (366d) |
| model | 68,318.88 | 68,179 |
| naive | 62,997.68 | 62,868 |

`oracle >= model >= naive` holds on both cash and `value_added`. CLAUDE.md states
the `model >= naive` half as an **average**, not a per-day claim, so the per-day
version is reported rather than asserted: the model beats the naive floor on
**239 of 365 days (65.5%)** — which is to say it loses to it on more than a
third, and still wins by 5,321 EUR over the year.

**EUR/MW/yr lost to forecast error: 6,047.**
