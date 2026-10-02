# The battery dispatch LP (C5)

Design notes for `dispatch/battery.py` and `dispatch/rolling.py`. The
**what** is in `PLAN.md`; this is the **why**, and in particular the places where
a choice had to be made and could reasonably have gone the other way.

Modules:

| file | what it owns |
| --- | --- |
| `config/battery.yaml` | the asset and every convention, each with its reason |
| `dispatch/battery.py` | one horizon: the LP/MILP, and the settlement |
| `dispatch/rolling.py` | what a horizon *is*, what it opens at, when to skip |
| `backtest/run_c5_oracle_lp.py` | the C5 oracle run and its invariant checks |
| `tests/test_c5_battery_lp.py` | 64 offline tests |

## The asset

1 MW / 2 MWh, round-trip 0.88 split symmetrically as `sqrt(0.88) ≈ 0.93808` per
leg, throughput cost 2 EUR per MWh *delivered to the grid*, opening at half full.
1 MW makes every number quotable per MW, which is what the write-up needs; the LP
is linear and the battery is a price taker, so value scales exactly with power.
2h is the representative continental new-build duration; 4h is a declared C15
sensitivity, not a second headline.

The throughput cost is charged on discharged energy, not on throughput in both
directions. That is the convention a desk uses for degradation (cost per MWh
delivered), and it matters that it is stated: charging it on both legs would
roughly double it at the same nominal number.

## The LP

Per interval `t` of `dt` hours, grid-side charge `c_t` and discharge `d_t` in MW,
stored energy `s_t` in MWh at the **end** of the interval:

```
maximise   Σ_t dt · (p_t·d_t − p_t·c_t − k·d_t)  +  v·s_{n−1}
s.t.       s_t = s_{t−1} + η·dt·c_t − (dt/η)·d_t
           0 ≤ c_t ≤ P,  0 ≤ d_t ≤ P,  0 ≤ s_t ≤ E
           s_{−1} = the SoC yesterday actually ended at
```

`scipy.optimize.linprog(method="highs")`, 3n variables and n equalities per day.
Charging at a negative price earns money; that is real and is not clipped.

The solver's objective and an independent recomputation of `cash + v·s_end` are
compared on **every single solve** (`solve_day` raises on a mismatch). They are
two expressions of one number, so a disagreement means the matrices encode a
different problem than the docstring claims — the kind of error that shows up in
no result and in no plot.

## Why there is a terminal value, and why it is a *trailing* one

A 24h horizon with no terminal condition always ends the day empty: the last
stored MWh is free revenue inside the horizon and worthless outside it. That is
exactly the midnight SoC reset `PLAN.md` forbids, arrived at by the LP rather than
by a line of code. `test_without_a_terminal_condition_the_lp_empties_the_battery_at_midnight`
pins it. So closing inventory is marked, the way a desk marks end-of-day stock:

```
v = max(0, η·(p_ref − k))     EUR per MWh of *stored* energy
```

`η·` because stored energy pays the discharge leg on its way out; `− k` because it
still owes the throughput cost; floored at zero because holding energy can never
be worth less than nothing, and a negative mark would pay the LP to burn energy —
which it already has one way of doing (below).

`p_ref` is the **median of realised hourly prices over the trailing 7 complete
market days**. Two properties, both asserted rather than argued:

* **Knowable at gate closure.** It uses only market days `≤ D−1`, published at
  13:00 local on `D−2`, before gate closure for `D` at 12:00 local on `D−1`.
  `assert_reference_is_knowable` re-derives both instants from `forecast.timing`
  and raises otherwise. The mark is a term in the objective, not a feature, so the
  C3 gate-closure guard never sees it — it gets its own check instead of an
  argument that it is obviously fine.
* **Independent of the day's own prices.** If the mark were read off the decision
  vector it would differ between the oracle, the forecast and the naive runs, and
  they would not be maximising the same objective. The per-day upper bound below
  would then not hold at all.

A gappy trailing day is excluded from the window entirely rather than pooled at
whatever hours survived. A day with too little history gets no mark and is skipped
with reason `no_reference` — only ever the first day of a series.

## Three money numbers, and which one is "the value"

| field | what it is |
| --- | --- |
| `cash_eur` | settled cash. **The headline annual number is a sum of these.** |
| `terminal_value_eur`, `opening_value_eur` | `v` × closing / opening inventory. Marks, not money. |
| `value_added_eur` | `cash + terminal − opening`: what the day's trading added over holding the opening inventory and standing still. |

`value_added` is the quantity the LP maximises, so it is the quantity the
invariants are stated on. It is exactly `0` on a flat non-negative curve, never
negative (standing still is always feasible), and monotone in spread, in capacity
and in power.

The headline is **cash** and not `Σ value_added`, because the marks do not cancel
across a year: `Σ_D v_D·(s_D − s_{D−1})` is an inventory revaluation at a mark
that moves day to day, and it is a model output, not money. Over 2024 on DE-LU the
two differ by well under a percent — closing inventory is at most 2 MWh — but the
honest number is the one that settled.

### "Value = 0 on a flat curve" has one real caveat

`PLAN.md` asks for a test that a flat curve is worth nothing, and that is right
for a flat **non-negative** curve. At a flat *negative* price a battery is simply
a load being paid to consume: it fills up, never discharges, and the money is
real. A lossless, costless battery shows the same thing, so this is not the
round-trip artefact below. `test_a_flat_negative_curve_is_genuinely_worth_something`
pins it (FINDING C5-A in `PROGRESS.md`).

A second, smaller caveat: at `p_ref` exactly equal to a flat day's price, holding
and liquidating are worth the same to the penny, so the LP may return either and
the day's reported *cycling* is arbitrary. The day's value is 0 either way. Real
prices make the exact tie measure-zero and the C5 run counts flat days so the
claim is a measurement; DE-LU 2024 has none.

## The per-day upper bound, in two stages

CLAUDE.md requires `value(forecast schedule @ realised) ≤ value(oracle @ realised)`
**every day**. It holds exactly, and only, when both schedules are solved

* from the **same opening SoC**, and
* against the **same mark** `v`,

because the frozen forecast schedule is then a feasible point of the oracle's own
problem and the oracle is its maximiser. `assert_oracle_dominates` checks both
preconditions and refuses to compare mismatched setups: an assertion that
silently compares two different problems is worse than no assertion.

Across two independently rolled trajectories the opening SoCs *diverge* — the two
curves end their days in different states — and no per-day bound exists; a lucky
forecast run that happens to open a day with a fuller battery can out-earn the
oracle run on that one day. **That is expected, not a bug.** C6 therefore needs
two oracles:

* a **rolled oracle** for the pooled/annual comparison, and
* a **same-start oracle**, re-solved each day from the *forecast* run's own
  opening SoC, for the per-day assertion.

`solve_day` takes `soc_start_mwh` as an explicit argument precisely so C6 can do
the second without reaching into anything's internal state. C5 implements and
tests both halves and uses only the oracle curve, which is its scope.

The pooled half of the invariant — `value(naive) ≤ value(forecast)` on average,
not per day — needs the naive curve and so is C6's.

## Simultaneous charge and discharge: found, measured, not silently fixed

`PLAN.md` requires an explicit check and calls this an LP artefact needing a
penalty term or a MILP. It is not hypothetical.

With the upper SoC bound binding, `c_t` and `d_t` both positive lets the battery
draw a net `c − d = c·(1 − η²) > 0` MW from the grid while its stored energy stays
flat — burning power in its own round-trip losses. At a sufficiently negative
price, being paid to consume beats the throughput cost of doing it, and the LP
takes the trade. The threshold is exact:

```
p < − k·η² / (1 − η²)   =   −2 × 0.88 / 0.12   =   −14.67 EUR/MWh
```

DE-LU had 457 negative hours in 2024, so this appears. A single-inverter BESS
cannot do it.

`simultaneity_report` measures it on every solve — intervals, the grid energy
burned, the cash earned from the overlap, the lowest price at which it happened —
and the C5 run turns that into a FLAG with magnitudes. `forbid_simultaneous=True`
rules it out *exactly* with one binary per interval via scipy's HiGHS MILP
(24 binaries a day is free), and both variants are run and reported.

The pure LP stays the committed default because that is what C5 scopes, and the
choice of default is a human's: see the FLAG in `PROGRESS.md` for the measured gap.
`c_t + d_t ≤ P` — a single shared inverter rating — is a third, physically
motivated option that bounds the artefact without a binary; it is noted there and
not implemented, to keep one decision in front of the reviewer rather than three.

## The horizon is the market day, 23 and 25 hours included

Not a UTC day and not 24 rows. The day-ahead auction clears a *local* calendar day
as one block of products — 23 or 25 of them twice a year — and a bidder commits
exactly that block. `market_day_blocks` groups on `forecast.timing.market_days`
and asserts each block's length against `data.contracts.local_day_hours`, i.e.
against the tz database rather than a remembered rule. This is CLAUDE.md's DST
whitelist assertion applied to dispatch: a short or long day is accepted when and
only when the calendar says it should be, and is never reindexed or padded.

`PLAN.md` writes the horizon as "24h, D+1"; the 23/25-hour days are that same
convention read off the calendar instead of assumed. Forcing 24 rows would mean
dispatching hours no auction cleared.

## A day is skipped, never patched

Three reasons, each counted in the summary:

| reason | when |
| --- | --- |
| `incomplete` | fewer rows than the local calendar says, or a missing price |
| `no_reference` | too little trailing history to mark closing inventory |
| `boundary` | the partial first/last local day of the loaded window |

A day cannot be committed from a partial price vector, and filling the hole inside
the LP is the silent-fill bug `data/prices.py` already refuses. SoC is carried
across a skipped day unchanged — the battery sat idle, which is what a desk with no
price vector would have done.

This is the mechanism that answers **NOTE C4-02**: LEAR declines exactly one hour
a year (the autumn DST hour whose 24h lag the gate-closure mask blanks), and the
LP needs a complete vector. The day is skipped and reported, with the `impute`
variant's measured cost (0.001 EUR/MWh of annual MAE) available if C6 prefers to
dispatch it from the imputed forecast with the substitution labelled. C6 chooses;
C5 only makes sure that neither choice can be made invisibly.

## Limitations, stated here and again in the write-up

* No intraday re-optimisation: one commitment per day, at gate closure.
* No ancillary services, no capacity payments. Day-ahead arbitrage only, which is
  a *lower* bound on what a real BESS earns and is the point of the comparison.
* Price taker: the battery's own 1 MW never moves the clearing price.
* No per-zone grid fees, levies or losses.
* The terminal mark is a modelling device, not a traded forward. A desk would mark
  against the actual D+1 curve.
* Degradation enters only as a linear cost per MWh discharged — no SoC-dependent
  or depth-of-discharge-dependent ageing, no calendar ageing.
