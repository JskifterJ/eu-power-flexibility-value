# C15 — the sensitivities: the same forecasts, dispatched under six batteries

`backtest/run_c15_sensitivities.py` (new), `tests/test_c15_sensitivities.py`
(new), one additive change to `dispatch/rolling.py` (the `soc_policy` lever,
§2).
Artefacts: `backtest/results/c15_{main,res}_<ZONE>_<YEAR>_{daily.csv.gz,summary.json}`,
`c15_rung_points.csv`, `c15_lever_contrasts.csv`, `c15_lever_summary.csv`,
`c15_friction_decomposition.csv`, `c15_no2_ordering.csv`,
`c15_boundary_inventory.csv`, `c15_res_degradation.csv`,
`c15_invariant_flags.json`, `c15_cache_verification.json`,
`c15_sensitivity_summary.json`, three figures under `docs/figures/`, and the
rows appended to `backtest/results/results.csv`.

PLAN.md C15 is four sensitivities — *"throughput cost 0/2/5 EUR/MWh; daily-reset
vs rolling-horizon SoC; RES-forecast degradation; 2h vs 4h duration"* — and one
instruction about how to read them: *"This is where the honest findings live —
look here first for the surprising finding."*

Two notes from earlier cycles point the cycle before it starts. **NOTE C13-02**:
the throughput-cost ladder is no longer NO2's mechanism test (FINDING C13-E
settled that) — run it for *how much of the capture ratio is friction*, with
NO2 2020 as the stress cell. **NOTE C14-06**: NOTE C8-01 is closed, the honest
exogenous block buys nothing, so C15 needs no new model arm.

---

## 1. What was computed, and what was deliberately reused

| part | source | why |
|---|---|---|
| every forecast | **reused** — C13's 36 per-year artefacts (2020-2023), C8's and C10's (2024), C8's and C9's (the RES leg) | a sensitivity is a change to the *battery*; a cycle that re-fits anything is measuring two things at once |
| the dispatch LP | **reused** — C5/C6's `solve_day`, `value_schedule`, `run_rolling_dispatch` | a rung-to-rung difference must not be a difference in the code |
| the pooled numbers | **reused** — C11's `pooled_capture`, `same_start_oracle`, `capture_frame`, `beats_naive` | a C15 capture ratio must mean exactly what the one in `results.csv` means |
| the intervals | **reused** — C12's `backtest/bootstrap.py`, same seed, same block ladder | the `base` rung's 2024 columns are then drawn exactly as C12 drew them |
| the SoC lever | **new** — `soc_policy` in `dispatch/rolling.py` (§2) | PLAN.md's daily-reset leg had no implementation, and the obvious one invents energy |
| the price cache | **re-pulled** — NOTE C2-02, 26th recurrence | `data/raw/` does not survive a container; all 54 fingerprints matched C1's manifest |

Nothing under `tests/`, `config/`, `forecast/`, `data/`,
`backtest/{walk_forward,metrics,bootstrap,results_store}.py`, `dispatch/battery.py`,
`dispatch/curves.py` or any earlier cycle's runner was modified. The one
pre-existing module this cycle touches is `dispatch/rolling.py`, additively, and
the committed default is pinned byte-for-byte by a test
(`test_carry_is_the_default_and_is_unchanged_by_naming_it`).

### The ladder

Six rungs, each **exactly one** declared departure from `config/battery.yaml`.
One-at-a-time, not factorial: a rung that moved two knobs could not be
attributed, and a test asserts that each rung moves one lever plus the fields
derived from it.

| rung | lever | the battery |
|---|---|---|
| `base` | — | 1 MW / 2h, k = 2 EUR/MWh, SoC carries, closing inventory marked at the trailing reference. **The committed spec.** |
| `throughput_0` | throughput cost | k = 0: all friction removed |
| `throughput_5` | throughput cost | k = 5: PLAN.md's upper end |
| `duration_4h` | duration | 4h of storage at the same 1 MW (so it also opens half full at 2 MWh) |
| `soc_daily_reset` | SoC policy | every market day opens **and** closes half full: each day an independent problem |
| `soc_no_terminal` | SoC policy | SoC carries, but closing inventory is worth nothing — the trap `config/battery.yaml` warns about |

`base` is not a seventh experiment. It is re-solved from scratch here and its
**per-day settled cash is checked against the rows C11 and C13 committed**
(`check_baseline_reproduction`): a ladder whose zero rung does not reproduce the
published number is measuring its own re-implementation. It does reproduce it —
see §5.

### The cells

* **Main leg** — the nine-zone comparable set every cross-zone claim rests on:
  9 zones × 5 years (2020-2024) × {oracle, `lear_full_history`, `naive`}.
  Five years because FINDING C13-A showed that a one-year capture band is not a
  regime effect, so a one-year *lever* effect would not be one either.
* **RES leg** — PLAN.md's RES-forecast degradation sensitivity: Tier A × {2023,
  2024} × {oracle, `lear_res_persistence`, `lear_res_as_published`,
  `gbm_res_persistence`, `gbm_res_as_published`}. Those are the only two years
  for which both vintages of the same model exist (no archived ENTSO-E D-1
  vintage before 2022, plus 365 days of required history).

51 cells, 6 rungs each: 1 836 rolling-horizon runs, each with its own per-day
same-start oracle bound.

---

## 2. The one new lever, and why it needed a guard

`dispatch/rolling.py` carried SoC and nothing else, because that is what PLAN.md
requires of the headline. The daily-reset leg had no implementation, and the
obvious implementation is wrong in a way that would not look wrong in the diff:

> open every day at `initial_soc_fraction`, and keep the terminal condition as
> it is.

Under `terminal_mode="none"` the LP empties the battery before midnight — that
is exactly the behaviour `config/battery.yaml` documents — so a reset to half
full hands the battery 1 MWh of free energy, 365 times a year, and the extra
cash reads as a sensitivity result. Under `trailing_value` the run books a mark
on inventory the reset then throws away.

So `soc_policy="reset"` is accepted **only** with a terminal **floor** at or
above the opening fraction. Then the LP must hand back at least what it was
given, the reset can only ever *discard* energy, and how much it discarded is
counted (`RollingResult.soc_reset_discarded_mwh`) rather than assumed to be
zero. Both halves are checked: `dispatch/rolling.py` refuses the unsafe spec
combinations up front, and `check_reset_conserves_energy` re-checks the *outcome*
on the days actually solved — every day opened at the configured SoC, and no
discard was negative.

The decomposition leg exists for the same reason. `soc_daily_reset` changes two
things at once in substance (no carryover **and** no mark), so `soc_no_terminal`
— carryover kept, mark removed — separates them. It is reported as a
decomposition leg, not as a candidate battery.

The two legs turn out to be two *different* daily resets, and §5.4 is why that
matters: `soc_daily_reset` makes every day start and end **half full**, while
`soc_no_terminal` leaves the LP free to end where it likes and it chooses
**empty** on 99.8% of days. The first forces the day to buy back what it sold;
the second does not. They are not two estimates of one quantity.

### Comparability across rungs is a day-set problem

`run_rolling_dispatch` skips a day with reason `no_reference` only when the
terminal mode is `trailing_value`, so the two rungs that switch the terminal
condition off *can* dispatch days `base` skips. A ratio summed over one day set
against a denominator summed over another is not a ratio of anything (C11's
rule), so every cross-rung number here is computed on the **ladder-common day
set**: the days every rung of every curve of that (zone, year) dispatched. That
is C11's `common_hours` definition applied to a larger run set, which is why
`scope` needed no new value — read `source_artefact` beside any C15 row.

### The boundary-inventory objection, answered before it is asked

The rungs end the year in different states: `soc_no_terminal` empty,
`soc_daily_reset` half full, `base` holding whatever the mark told it to hold.
So part of any cross-rung cash difference is inventory one run still owns and
another has already sold. `c15_boundary_inventory.csv` bounds that part **twice**,
for every non-base rung and not only the SoC ones:

* the **natural** bound — the net stored-energy difference at the *last
  dispatched day's* highest price, which is when that difference is realised or
  not;
* the **deliberately unfair** bound — the same quantity at the *year's* highest
  price, which is strictly more than the inventory could ever have fetched.

A difference that is not an order of magnitude above its bound is reported as
inconclusive rather than as a finding, and §5.3 gives both counts.

---

## 3. NOTE C14-01, and the one thing C15 refuses to claim

C14 handed this cycle what it called *"a falsifiable prediction, not just a
result"*:

> NO2's within-day ordering will not improve at any rung — not at a 0 EUR/MWh
> throughput cost, not at a different duration, not under a different SoC policy
> — because the fundamental that orders the hours elsewhere has no measurable
> relationship to NO2's price spread. **If the Spearman moves materially with the
> throughput cost, FINDING C14-F is wrong and C18 must say so.**

It does not move, and that is not evidence. **The within-day Spearman is a
function of the forecast and the realised prices alone.** No rung of this ladder
touches either: the forecasts are read from committed artefacts and the realised
prices are the price cache. So the number is identical at every rung *by
construction*, and the prediction as written cannot fail.

C15 therefore reports it as an **assertion about the design rather than a
result**: `spearman_is_rung_invariant` checks the drift is exactly zero, and a
non-zero drift would mean two rungs had been pooled over different day sets —
a bug, not a finding. Presenting a tautology as a confirmed prediction would be
the kind of thing an unattended cycle does and a reader cannot see.

The prediction *does* have a substantive form, and that one is testable:

> If NO2's capture deficit were friction, removing the friction
> (`throughput_0`) would close it.

That is what §5 reports, per year, as the gap between NO2's capture and the
other eight zones' mean at `base` and at `throughput_0`.

---

## 4. The RES-forecast degradation leg

PLAN.md lists RES-forecast degradation as a C15 sensitivity. The *experiment*
already exists: C8 built the as-published / persistence pair as a first-class
arm and C9 re-measured it under the booster (FINDING C9-C — the Art. 14 leak is
worth +23.96% of MAE on DE-LU and +17.82% on ES to a tree ensemble, against
+8.4% / +11.3% to the LASSO). NOTE C14-06 closed the remaining modelling
question: the honest exogenous block has no reliable positive value in either
model class, either year, any Tier-A zone, so **C15 adds no exogenous model
arm**.

What C15 adds is the narrow dispatch question nobody has asked: **does the value
of that publication timestamp depend on the battery?** A leak worth nothing a
battery can trade at *every* rung is a stronger version of FINDING C14-G than a
leak worth nothing at one. The contrast is fixed in direction —
`as_published` minus `persistence`, labelled `after_gate_closure` everywhere,
**never an achievable result** — and is run at all six rungs in both model
classes.

---

## 5. Results

### 5.0 The zero rung is the published result

`base` was re-solved from scratch, in a fresh container, from an independently
re-pulled price cache, by a runner that did not exist when the numbers were
published. It reproduces:

| reference | rows | curves | worst absolute gap |
|---|---|---|---|
| `c13_daily_by_year.csv.gz` (carries C11's 2024 column unchanged) | 49 284 | 3 | **5.0e-7 EUR** |
| `c11_capture_daily_2024.csv.gz` (the exogenous arms) | 5 472 | 5 | **5.0e-7 EUR** |

**54 756 per-day settled-cash rows, worst gap half a microeuro.** DE-LU 2024's
capture comes back as 0.9187 and NO2 2024's as 0.6146 — the two ends of FINDING
C11-A, to four decimals. This is also most of what NOTE C14-04 hands C20: the
reproducibility check it asked for now covers the whole nine-zone, five-year
dispatch surface rather than one zone's hours.

### 5.1 Friction is almost none of the capture shortfall (NOTE C13-02)

Over the 44 usable (zone, year) cells — NO2 2020 excluded under C13's declared
thin-regime floor and reported separately in §5.5 — the comparable LEAR's mean
capture is **0.7953**, a shortfall of **20.47pp**. Removing the **entire**
throughput cost recovers **0.80pp** of it and leaves **19.67pp**:

| | mean | median | range |
|---|---|---|---|
| friction share of the capture shortfall | **0.034** | 0.029 | −0.033 … +0.174 |

**FINDING C15-A — about 3% of the capture shortfall is friction; the other ~97%
is not.** And the share is itself regime-dependent, in the direction a desk
would expect: it is indistinguishable from zero in the three deepest zones
(DE-LU 0.001, BE 0.005, FR 0.006) and largest in the thinner ones (ES 0.091,
IT-North 0.070, NO2 0.065, DK1 0.042).

What the throughput cost *does* move is the **prize**. At k = 0 the
perfect-foresight battery earns +2 175 EUR/MW/yr more and the forecast-driven
one +1 982 (42 of 45 cells' cash intervals exclude zero at the daily block);
at k = 5 both lose ~2 800-3 000. Because it taxes the oracle and the forecast
almost equally, it barely touches the ratio between them — the capture delta's
interval excludes zero in only **3 of 45** cells at the headline daily block.

So NOTE C13-02 is answered: **the capture ratio is not mostly friction.** It is
an ordering problem, which is what FINDING C12-C and FINDING C13-D already said
with different instruments.

### 5.2 A longer battery captures a larger share of a larger prize

Levels, averaged over the 44 usable cells of the comparable LEAR:

| rung | capture | EUR/MW/yr | oracle EUR/MW/yr | full cycles/yr |
|---|---|---|---|---|
| `base` (2h) | 0.795 | 42 746 | 52 731 | 577 |
| `duration_4h` | **0.812** | **68 416** | 82 379 | 482 |

(The levels above average the 44 usable cells; the paired deltas quoted
everywhere else average all 45, including the thin NO2 2020 cell — which is why
0.812 − 0.795 = 1.7pp here and the paired mean is +1.61pp. Every table says which
it is.)

**FINDING C15-B — doubling the duration adds +25 094 EUR/MW/yr (44 of 45 cells'
cash intervals exclude zero) and +1.61pp of capture.** The cash result is the
solid half; the capture gain is directional (11 of 45 cells at the daily block,
16-17 at 7 and 14 days). The mechanism is the one a trader would guess: a 4h
battery charges and discharges over a wider window, so getting the exact hour
wrong costs it less — it is a *slightly easier forecasting problem*, not just a
bigger one. It also cycles **less** (482 against 577 equivalent full cycles),
which matters for a degradation budget.

### 5.3 The SoC convention is the biggest lever in the ladder

| rung | mean Δcapture | cells excl. zero (1 / 7 / 14 d) | mean Δ EUR/MW/yr | cash cells excl. zero (1 d) |
|---|---|---|---|---|
| `throughput_0` | +2.18pp | 3 / 10 / 14 | +1 982 | 42 / 45 |
| `throughput_5` | −2.90pp | 4 / 20 / 21 | −2 799 | 44 / 45 |
| `duration_4h` | +1.61pp | 11 / 16 / 17 | +25 094 | 44 / 45 |
| `soc_daily_reset` | **−3.97pp** | 11 / 31 / 33 | −3 185 | 29 / 45 |
| `soc_no_terminal` | +1.28pp | **0** / 14 / 19 | +2 943 | 16 / 45 |

(45 cells, comparable LEAR, including the thin NO2 2020 cell — which is what
produces the extreme tails `throughput_0` +62.88pp and `throughput_5` −54.99pp
in `c15_lever_summary.csv`. §5.5 reports that cell on its own.)

**FINDING C15-C — forcing each market day to open and close half full costs
−3.97pp of capture and −3 185 EUR/MW/yr, which is a larger effect than removing
the entire trading friction.** PLAN.md's insistence that nothing resets at
midnight is therefore not a detail of the LP: it is the single modelling choice
in this ladder with the most money attached. The mechanism is that the floor
forces the day to *buy back* whatever it sold, at whatever hour is left, rather
than ending where the price says it should.

**A caveat this result must carry.** `soc_daily_reset` ends the year half full
and `base` ends it wherever the mark left it, so part of that −3 185 is
inventory accounting. `c15_boundary_inventory.csv` bounds it twice. Against the
**strictly generous** bound — the net stored-energy difference at the *year's*
highest realised price, which is more than that inventory could ever have
fetched — the median cell's difference is **8.2×** its bound and 46 of 114 clear
10×. Against the **natural** bound — the last dispatched day's highest price,
which is when that inventory difference is actually realised or not — the median
is **37.1×** and **105 of 114** clear 10×. So the direction is safe and the
magnitude is safe under the bound that fits the question; under the deliberately
unfair one it carries a boundary term of order 10%. Both are reported.

### 5.4 The surprising finding: the device that protects the rolling horizon mostly does nothing

`config/battery.yaml` introduced the trailing-value terminal mark for a stated
reason — without a terminal condition a 24h LP always empties the battery before
midnight, which "silently turns PLAN.md's rolling-horizon SoC carryover into the
daily reset it forbids."

Under the committed battery, it empties anyway:

| curve | share of days ending at SoC ≈ 0 | mean closing SoC (of 2.0 MWh) |
|---|---|---|
| oracle | **0.744** | 0.419 |
| comparable LEAR | **0.767** | 0.352 |
| naive | 0.758 | 0.381 |

**FINDING C15-D — three days in four already end empty with the mark in place,
so for a 2h battery the rolling horizon is in practice a nightly reset to empty,
and the terminal mark is binding on about a quarter of days.** On those days it
is not obviously helping: removing it entirely (`soc_no_terminal`) leaves the
captured share **statistically unchanged — 0 of 45 cells' capture intervals
exclude zero at the daily block**, the weakest result of any lever here — while
the point estimate on cash moves **+2 943 EUR/MW/yr in the battery's favour**
(16 of 45 cells, so **directional and not established**).

Read plainly: the mark was introduced to stop a degeneration it does not
actually stop, and where it binds, the best current estimate is that it costs
realised cash rather than protecting it. That is a **decision request, not a
change** — see NOTE C15-01. C15 changed nothing in `config/battery.yaml`, and no
headline anywhere in this project moves on it.

**Why the two SoC legs disagree so much** (−3.97pp against +1.28pp) is the same
fact from the other side. They are not two estimates of one quantity: under
`soc_no_terminal` the LP is free to end the day where it likes and chooses
**empty on 99.8% of days** (mean closing SoC 0.004 MWh), whereas
`soc_daily_reset` **forces** it to hand back 1.0 MWh by midnight. Both make the
day independent; only the second makes it buy back what it sold, at whatever hour
is left. So the honest reading of FINDING C15-C is "**a forced closing inventory
costs ~3 200 EUR/MW/yr**", not "the overnight carryover is worth that" — the
carryover itself, as §5.4's first table shows, is exercised on about one day in
four.

### 5.5 NO2, and what NOTE C14-01 can and cannot be asked

**NO2 is last of nine on capture *and* last of nine on the within-day Spearman in
all 30 of 30 (year, rung) rows of `c15_no2_ordering.csv`.** FINDING C13-C held
for five years at one battery; it holds for five years at six batteries.

The substantive form of NOTE C14-01's prediction — *if NO2's deficit were
friction, removing the friction would close it* — is tested per year, on the four
years above C13's thin-regime floor:

| year | capture gap at `base` | at `throughput_0` | closed | share of the gap |
|---|---|---|---|---|
| 2021 | −30.70pp | −27.41pp | 3.28pp | 10.7% |
| 2022 | −27.35pp | −25.47pp | 1.88pp | 6.9% |
| 2023 | −22.95pp | −21.54pp | 1.41pp | 6.1% |
| 2024 | −27.46pp | −24.16pp | 3.29pp | 12.0% |
| **mean, 4 usable years** | **−27.11pp** | **−24.65pp** | **2.47pp** | **9.1%** |

**FINDING C15-E — removing every euro of trading friction closes 6-12% of NO2's
capture deficit (9.1% on the four-year mean) and leaves 88-94% of it standing, in
every usable year.** The
thin-spread story is already dead (FINDING C13-E); the friction story dies here.
What is left is the within-day ordering (FINDING C12-C) with the fundamental
FINDING C14-F gave it.

The prediction **as C14 wrote it** is a different matter, and C15 declines to
claim it. The within-day Spearman is a function of the forecast and the realised
prices; no rung touches either; the mean Spearman is **0.783 at every one of the
six rungs**, and the asserted drift is exactly **0.0**. That is a property of the
experiment, not evidence about NO2 — see §3.

**The stress cell (NOTE C13-02).** NO2 2020, where the perfect-foresight battery
earns 769 EUR/MW/yr against a mean realised daily spread of 3.41 EUR/MWh:

| rung | capture | EUR/MW/yr | oracle EUR/MW/yr | cycles/yr |
|---|---|---|---|---|
| `base` | −0.5222 | −401 | 769 | 215 |
| `throughput_0` | **+0.1065** | +133 | 1 252 | 652 |
| `throughput_5` | −1.0721 | −658 | 614 | 94 |
| `duration_4h` | −0.5464 | −656 | 1 201 | 176 |
| `soc_daily_reset` | −0.5923 | −491 | 828 | 209 |
| `soc_no_terminal` | −0.3283 | −310 | 946 | 218 |

This is the one cell where friction dominates — zero throughput cost is the
difference between losing money and making a little — and it is also the cell
where the naive floor beats the model at every rung (**FLAG C13-01, reproduced
six times over**, below). Both facts are the same fact: with a 3.41 EUR/MWh
spread against a 2 EUR/MWh throughput cost and a 12% round trip, there is
nothing to trade, and which curve trades *less* is luck.

### 5.6 The Art. 14 leak's dispatch value is a model-class fact, not a battery fact

PLAN.md's RES-forecast degradation sensitivity, as `as_published − persistence`
in capture points, **never achievable** (FINDING C9-C):

| model | zone-year | `base` | `k=0` | `k=5` | `4h` | `daily_reset` | `no_terminal` |
|---|---|---|---|---|---|---|---|
| LEAR | DE-LU 2023 | −2.11 | −1.53 | −2.85 | −3.01 | +1.86 | +0.94 |
| LEAR | DE-LU 2024 | 0.00 | +0.28 | +0.19 | +0.16 | +3.20 | +2.26 |
| LEAR | ES 2023 | −0.82 | −0.65 | −0.67 | +1.24 | +1.73 | +0.76 |
| LEAR | ES 2024 | −0.84 | −0.16 | −0.62 | +0.02 | +1.50 | +0.54 |
| LEAR | NO2 2023 | −1.86 | −2.16 | −2.21 | −1.80 | +2.50 | +0.92 |
| LEAR | NO2 2024 | −0.76 | +0.16 | −0.68 | +1.28 | +1.79 | +1.10 |
| GBM | DE-LU 2023 | **+9.05** | +8.06 | +9.75 | +8.04 | +11.71 | +10.07 |
| GBM | DE-LU 2024 | **+3.47** | +3.24 | +3.58 | +3.29 | +5.33 | +4.89 |
| GBM | ES 2023 | **+5.40** | +4.82 | +5.92 | +6.90 | +6.79 | +5.55 |
| GBM | ES 2024 | +0.95 | +0.92 | +1.72 | +0.84 | +3.83 | +2.65 |
| GBM | NO2 2023 | −2.23 | −2.94 | −3.42 | −1.37 | +1.09 | +0.71 |
| GBM | NO2 2024 | −0.84 | +0.98 | +1.05 | −1.22 | +3.43 | +1.88 |

**FINDING C15-F — the leak's dispatch value is set by the model class and barely
moves across the ladder.** Under the LASSO it is ≈0 or negative at every rung in
every cell; under the booster it is large and positive in DE-LU at every rung,
positive in ES 2023 at every rung, and ≈0 in NO2 at every rung. This is FINDING
C9-C and FINDING C11-D's "except on DE-LU under the GBM", now shown to be
robust to the whole battery specification rather than measured once.

Intervals, at the headline daily block: under the LASSO the leak's capture delta
excludes zero in **0 of 6** cells at `base` — the cleanest statement yet that the
Art. 14 vintage buys the LASSO nothing a battery can trade — and under the
booster in **3 of 6** (both DE-LU years and ES 2023, the three large positives).

The one systematic movement is worth noting because it runs the *opposite* way
to the obvious objection. The rung at which the leak is worth **most** is
`soc_daily_reset` — the hardest, most constrained dispatch problem — in **11 of
12** cells (the exception is GBM/ES 2023, where `duration_4h` edges it, +6.90
against +6.79). A better forecast is worth more when the battery has less slack,
which is the reverse of "the leak only looks valuable because the battery is
forgiving."

### 5.7 A cross-lever restatement of FINDING C12-D

Look down the two "cells excluding zero" columns of §5.3. On **cash**, four of
the five levers are decided in 42-44 of 45 cells. On **capture**, the best of
them manages 11 of 45 and the worst manages 0. Same days, same draws, same
battery — the only difference is whether the statistic is a sum or a ratio of
two sums that move together.

**FINDING C15-G — the levers move the money with confidence and the captured
*share* with very little.** This is FINDING C12-D ("capture cannot rank arms at
one validation year") restated across a dimension C12 could not reach: it is not
that capture is a bad metric, it is that capture is designed to divide out
exactly what a battery-parameter lever changes. A desk asking "what is a 4h
battery worth" wants the EUR/MW/yr, which is decided; a reader asking "does a 4h
battery capture a larger share" is asking a much noisier question.

C18 should quote the lever effects in EUR/MW/yr and treat the capture deltas as
directional, with the one exception of `soc_daily_reset`, whose capture effect
survives at 31 and 33 of 45 cells at the 7- and 14-day blocks.

---

## 6. FLAGs

**FLAG C13-01 reproduced at all six rungs, and it is still a regime fact.**
NO2 2020's comparable LEAR fails CLAUDE.md's pooled naive-dominance invariant at
`base` (−402 EUR against the naive floor's +253, exactly C13's numbers) and at
**every other rung** — including `throughput_0`, where it earns +133 EUR against
the floor's +543. `c15_invariant_flags.json` records all six failures, the
dispatch phase exited non-zero, no tolerance was widened and no test was edited.
It is **not a new flag**: the mechanism is the one C13 recorded (a 769 EUR/MW/yr
prize against a 2 EUR/MWh throughput cost and a 3.41 EUR/MWh mean spread), and
C15 adds only that removing the friction does not rescue it either. No later
cycle should "fix" this by relaxing the check.

**No new FLAG.** Every other check passed on every curve of every rung of every
cell: 1 836 rolling-horizon runs, the per-day same-start oracle bound included.
`FLAG C5-01` (simultaneous charge/discharge) and `FLAG C14-01` (the DE-LU 2023
GBM tie) are unchanged and were not re-touched by this cycle.

---

## 7. What this cycle did not do, deliberately

* **No model was re-fitted and no arm was added.** NOTE C14-06 closed the one
  question that might have justified an exogenous arm.
* **`config/battery.yaml` was not changed**, including by §5.4's finding. A
  sensitivity is a measurement; moving the committed default is a human decision
  (NOTE C15-01).
* **The frozen GBM config was not touched.** `test_every_gbm_arm_carries_the_frozen_config_fingerprint`
  pins it from this cycle's side too.
* **No post-cutover or 15-minute work.** PLAN.md puts that at C15+ as a labelled
  stretch goal; this cycle spent its budget on the four sensitivities PLAN.md
  names, and the main hourly backtest still ends before 2025-10-01 because 2025
  is sealed.
* **`c14_headroom_daily.csv.gz` was not read.** NOTE C14-05 offers it for
  fundamentals-against-dispatch questions; every lever here is a battery
  parameter, so there was nothing to join it to.
* **2025 was not touched.** `LADDER_YEARS` stops at 2024, `main_curves` has no
  mapping for a sealed year and raises before a path is built, `dispatch_cell`
  calls `assert_not_sealed` first, and a test sweeps every committed C15
  artefact for a bare `2025` token.

---

## 8. Reading the artefacts

| file | one row per | what it is for |
|---|---|---|
| `c15_{main,res}_<ZONE>_<YEAR>_daily.csv.gz` | (rung, curve, market day) | the raw ladder. Every dispatch column is **day-additive**, so `backtest/bootstrap.py` takes the file directly — a later cycle re-pools a rung without re-solving an LP. |
| `c15_{main,res}_<ZONE>_<YEAR>_summary.json` | cell | the rung specs, the skips and their reasons, every invariant's report, the curve provenance, the point error on the ladder-common days. |
| `c15_rung_points.csv` | (leg, zone, year, rung, curve) | every pooled number. The table most later work should start from. |
| `c15_lever_contrasts.csv` | (cell, curve, rung, block length) | paired daily-block intervals on each lever's capture and cash delta, at 1 / 7 / 14 days. |
| `c15_lever_summary.csv` | (leg, curve, rung) | the cross-cell view of the above at the headline block. |
| `c15_friction_decomposition.csv` | (leg, zone, year, curve) | the shortfall, the friction share of it, and the thin-regime flag. |
| `c15_no2_ordering.csv` | (year, rung) | NOTE C14-01's table: NO2's capture and within-day Spearman against the other eight. |
| `c15_boundary_inventory.csv` | (cell, curve, rung) | the inventory-accounting bound on every cross-rung cash difference, under both bounds. |
| `c15_res_degradation.csv` | (zone, year, rung, pair, block) | PLAN.md's RES-forecast degradation sensitivity, at every rung. |
| `c15_invariant_flags.json` | run | CLAUDE.md's invariants on all 1 836 runs, and which failed. |
| `c15_sensitivity_summary.json` | run | everything above in one place, plus both reproduction checks and the provenance stamps. |

**Store rows.** Levels are `c15_<rung>_{capture,eur_per_mw_year,eur_per_mw_year_lost,cycles,within_day_spearman}`
and deltas against `base` are `c15_d_<rung>_{capture_pp,capture_pp_ci_low,capture_pp_ci_high,eur_per_mw_year}`.
The rung lives in the **metric name**, which is the store's documented extension
point (`docs/results_store.md`), so a C15 row needed no schema change and no
migration — the same property C11, C12 and C13 relied on. `scope` is
`common_hours`, which here means the ladder-common day set (§2); read
`source_artefact` beside the row.

**Three cautions, inherited and re-earned.**
1. Rank arms on the within-day Spearman and translate to EUR/MW/yr with capture
   (FINDING C12-C) — and rank *levers* on EUR/MW/yr outright (FINDING C15-G).
2. A wider bootstrap block does **not** mean a wider interval at n = 365; read
   the rung least favourable to the claim (C12's warning, unchanged).
3. `capture_same_start_pooled` must never rank two curves (FINDING C11-C). The
   headline here is `capture` = settled cash over the **rolled** oracle's cash on
   the same days, which is `capture_rolled_oracle_cash` under its C11 name.
