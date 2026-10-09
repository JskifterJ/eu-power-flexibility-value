# C13 — the regime analysis: five evaluation years, and the crisis year on its own

`backtest/run_c13_regime.py` (new), `tests/test_c13_regime.py` (new).
Artefacts: `backtest/results/c13_year_<ZONE>_<YEAR>_{predictions.csv.gz,folds.csv,summary.json}`
(36 walk-forward runs), `c13_dispatch_<ZONE>_<YEAR>_{daily.csv.gz,summary.json}`
(36 dispatch runs), `c13_daily_by_year.csv.gz`, `c13_per_year_metrics.csv`,
`c13_year_intervals.csv`, `c13_regime_table.csv`, `c13_regime_summary.json`,
`c13_cutover_status.json`, and the rows appended to
`backtest/results/results.csv`.

PLAN.md C13 is four things: *"Regime analysis: 2022 crisis year reported
separately; per-year tables; pre/post 2025-10-01 flagged; negative-hour counts
per zone."* The first two did not exist as results before this cycle, because
**every earlier cycle evaluated 2024 and nothing else** — so "per-year tables"
needed a per-year *backtest* first, which is what NOTE C12-01 called C13's one
piece of new computation and left to C13 to scope.

It is in scope and it ran: the nine-zone comparable arm, walked forward one
evaluation year at a time across **2020, 2021, 2022 and 2023**, dispatched
through the same rolling LP, and scored with the same metric layer — nine zones
× five years, 2024 included from the committed artefact.

---

## 1. What was computed, and what was deliberately reused

| part | source | why |
|---|---|---|
| 2020-2023 forecasts | **new** — C4's committed `LearSpec`, price-history and calendar features, expanding window from the start of the price history, daily refit | the only way a per-year table can exist |
| 2020-2023 dispatch | **new** — C5/C6's `run_rolling_dispatch`, C11's `pooled_capture` imported, not re-derived | a 2022 capture ratio must mean exactly what the 2024 one in `results.csv` means |
| 2020-2023 metrics and intervals | **reused** — C12's `point_metrics`, `curve_replicates`, `Basis`, `cross_zone_analysis` | the band test for a new year is C12's band test with different rows |
| 2024 column | **reused** — C12's committed per-day artefact, re-pooled | so the last column of every table is the number already published, not a near neighbour of it |

Nothing under `tests/`, `config/`, `forecast/`, `dispatch/`, `data/`,
`backtest/walk_forward.py`, `backtest/metrics.py`, `backtest/bootstrap.py`,
`backtest/results_store.py` or any earlier cycle's runner was modified. The
cycle is one new runner, one new test file, this document, and new artefacts.

### The arm, and why it is the only one

The per-year arm is the **nine-zone comparable arm**: `lear` / `price_only` /
`train_from=2019-01-01`, the series FINDING C10-B and the whole cross-zone table
are built on, with the naive floor beside it and the oracle above it. The
exogenous and gradient-boosted arms are **not** extended to the new years — see
[§7](#7-what-this-cycle-did-not-do) for why that is a scope decision with a
reason and not an omission.

### Each year is its own rolling run

SoC carries from day to day inside a year and **not** across a year boundary:
every year opens at `initial_soc_fraction` (half full), exactly as C11's 2024
run did. So the five columns are five independent runs of the same battery, not
five slices of one five-year trajectory. That is the right shape for a per-year
table — a 2022 number that depended on how 2021 ended would not be a statement
about 2022 — and it is stated in every dispatch summary under `soc_note`.

---

## 2. The honesty label this cycle must carry

PLAN.md's split calls 2019-2023 **training** years and 2024 the validation year.
Every prediction added here is a genuine expanding-window walk-forward — a fold
never sees its own day, the gate-closure mask runs on every feature matrix, and
C3's leakage assertions are untouched — so these are out-of-sample
**predictions**.

They are **not** an out-of-sample **configuration** test. C4 chose the LEAR
specification while looking at 2024, and C9 froze the GBM config the same way.
A second year drawn from the same pool of years the configuration was chosen
against weakens "one validation year decides too little" without being the
clean draw the sealed 2025 holdout will be.

So: where this cycle strengthens a C12 finding, it does so **as four extra
years of walk-forward evidence under a configuration chosen on 2024**, and
C18 must say so. The only clean test is Checkpoint C, and **2025 stays
sealed**.

---

## 3. The per-year table

`c13_per_year_metrics.csv` — one row per (zone, year, curve, scope), every
metric C11 and C12 defined. Two scopes, as C11 and C12 used them:

`common_hours`
: the intersection of the days **every curve of that zone-year** dispatched —
  C11's definition exactly, applied to this cycle's three curves. The scope
  every within-year and cross-year comparison is read at. Worth stating
  plainly: in Tier A this is *not* the same day set as C11's 2024
  `common_hours`, which intersected over nine curves. The C13 rows are labelled
  with the artefact they came from, and no 2024 row is rewritten.

`own_coverage`
: each curve on the days it dispatched. Kept because it is the scope C11's
  cross-zone table and the committed store rows use, which is what makes the
  2024 reproduction check below possible.

`c13_year_intervals.csv` carries the bootstrap interval for eight metrics at
every (zone, year, curve) and every block length in the ladder (1 / 7 / 14
days), 10 000 replicates, seed 20261009 — C12's seed, deliberately, so the 2024
column is drawn exactly as C12 drew it.

**Within a year the bootstrap is paired** (one draw of days applied to every
zone and curve) and that pairing is what makes a cross-zone difference tight.
**Between years it cannot be**: two years share no market day, so a year-on-year
difference is an unpaired bootstrap of two independent draws, its standard
error is ~√2 × a single year's, and it is labelled `"pairing": "unpaired"`
everywhere it appears. A test pins that labelling, because quietly treating a
year-on-year change as paired would halve every interval in §5.

---

## 4. The 2024 column is the published 2024 number

A per-year table whose last column is *almost* the figure already in
`results.csv` is worse than a table without it. So the analyse phase recomputes
2024 from C12's committed per-day rows and checks it against the committed store
rows **before** any per-year claim is made, and exits non-zero on a
disagreement. Two passes:

* **`own_coverage`, all nine zones** — every dispatch metric, plus the C12 shape
  metrics, against the rows C11 and C12 wrote at that scope.
* **`common_hours`, the six Tier-B zones** — C11's Tier-B curve inventory *is*
  this cycle's three curves, so the day set is the same one and the
  **point-error** metrics (MAE, RMSE, bias, rMAE) reproduce as well. Tier A
  cannot offer this check: C11's Tier-A intersection is over nine curves, which
  C13's three-curve basis deliberately is not.

The tolerances are float64 association error, with C12's stated relative
tolerances on the two EUR/MW/yr figures (C11 formed them as `sum/span`; the
bootstrap needs `mean × annualisation`). The test file nudges one capture ratio
by 1e-6 and confirms the check catches it.

---

## 5. The crisis year, reported separately

`c13_regime_summary.json → crisis_2022`. Per zone: the oracle's EUR/MW/yr in
2022 against the mean of the other four years (how much more theoretical
flexibility value the crisis year held), the comparable arm's capture ratio in
2022 against the same baseline with an **unpaired** interval, the EUR/MW/yr
actually settled, the EUR/MW/yr lost to forecast error, and the within-day
Spearman.

The reason the two are reported side by side is that a reader who sees only the
first will assume the second followed it. The price level and the *share* of the
prize a forecast-driven battery captures are different questions, and C13 is the
first cycle that can show whether they move together.

`c13_regime_table.csv` is the price-regime description PLAN.md asks for, per
(zone, year): mean / median / sd / min / max, the **negative-hour count** and
its share, the zero-hour count, hours above 200 EUR/MWh, and the mean / median /
p95 daily spread.

### The negative-hour counts cross-check the committed manifest

The counts here are taken over the **local market days** of each year — the day
labels every dispatch row in this project is keyed on — while C1's manifest
counted over the fetched file's own window, which starts at local midnight on
01-01 and ends an hour short of it. The two windows differ, so agreement is
checked rather than assumed (`manifest_cross_check` in the summary, and a test).

---

## 6. Pre/post 2025-10-01 — a flag, not a split

`c13_cutover_status.json`. Nothing in this project has crossed the SDAC
15-minute go-live: `config/data.yaml` stops fetching at 2024, PLAN.md's main
hourly backtest ends 2025-09-30, and the cutover date falls **inside the sealed
2025 holdout**. So the flag is a statement about the evaluated window, not a
comparison:

* every price hour behind every C13 number was served at 60-minute resolution
  (`resolution_seconds = 3600` on all 54 manifest zone-years);
* every evaluated market day is before 2025-10-01;
* `post_cutover_rows = 0`.

`data/contracts.py` already carries the resolution-change detection that would
catch a post-cutover file if a later cycle fetched one, and PLAN.md keeps native
15-minute analysis as a labelled C15+ stretch goal that is never blended into
these results.

---

## 7. What five years say

### The capture ratio by (zone, year) — the table the project did not have

`capture_rolled_oracle_cash`, the comparable LEAR arm, `common_hours`:

| zone | 2020 | 2021 | 2022 | 2023 | 2024 | across-year band |
|---|---|---|---|---|---|---|
| BE | 0.8170 | 0.7443 | 0.7544 | 0.8733 | 0.9044 | 16.0pp |
| DE-LU | 0.8652 | 0.7749 | 0.8238 | 0.8983 | 0.9187 | 14.4pp |
| DK1 | 0.7660 | 0.7221 | 0.7539 | 0.8082 | 0.8358 | 11.4pp |
| ES | 0.7522 | 0.7107 | 0.7980 | 0.8762 | 0.9109 | 20.0pp |
| FR | 0.8672 | 0.8032 | 0.7757 | 0.8752 | 0.8526 | 10.0pp |
| IT-North | 0.8302 | 0.8085 | 0.8553 | 0.8923 | 0.9042 | 9.6pp |
| NL | 0.8080 | 0.7521 | 0.7996 | 0.8814 | 0.9031 | 15.1pp |
| **NO2** | **−0.5222** | **0.4480** | **0.5230** | **0.6279** | **0.6146** | 18.0pp¹ |
| PL | 0.6875 | 0.7238 | 0.8118 | 0.7541 | 0.8839 | 19.6pp |

¹ excluding the flagged 2020 cell; including it, 115pp.

**FINDING C13-A — a zone's capture ratio moves across years by as much as the
eight zones differ from each other within a year.** The within-zone across-year
band is **9.6-20.0pp** (eight non-outlier zones) against a single year's
bootstrap sd of 2.8-5.1pp, so the year effect is **2.3-5.4× its own sampling
noise** and unmistakably real. The eight-zone band *within* a year is 8.3-18.0pp
— the same size. A capture band measured in one year therefore cannot be read as
a regime effect, because a band of that size appears when the same zone is
re-measured in a different year.

**FINDING C13-B — FINDING C12-B is settled: the eight-zone capture band is NOT
established.** The noise-only null band, eight zones, at PLAN.md's daily block:

| year | band ex-NO2 | noise-only p | nine-zone band | noise-only p |
|---|---|---|---|---|
| 2020 | 17.98pp | 0.095 | 138.95pp | 0.053 |
| 2021 | 9.78pp | **0.846** | 36.05pp | 0.010 |
| 2022 | 10.15pp | **0.523** | 33.23pp | 0.0004 |
| 2023 | 14.42pp | 0.015 | 27.04pp | 0.0006 |
| 2024 | 8.29pp | 0.078 | 30.40pp | <1e-4 |

**One of five years clears 5%.** C12 could only say the 2024 result was at the
edge; five years say the edge is where it stays, and in 2021 and 2022 the eight
zones' capture ratios are indistinguishable from eight draws of one number. The
**nine-zone** band is significant in four of five years — so the cross-zone
capture finding is, as C12 suspected, **a finding about NO2 plus a direction**,
now confirmed in five independent years rather than argued from one.

**FINDING C13-C — NO2 is the worst-capture zone in every one of the five years,
and the lowest-ordering zone in every one of the five years.** Its within-day
Spearman is 0.470 / 0.592 / 0.650 / 0.615 / 0.578 against 0.699-0.886 in the
other eight, every year. The cross-zone capture ranking replicates moderately
between year pairs (Spearman +0.33 to +0.88, positive in all ten pairs) and NO2
is bottom in 10 of 10. FINDING C11-B is the one C11/C12 claim that five years
makes **stronger**, not weaker.

### The mechanism: error measured against headroom

**FINDING C13-D — neither the forecast error nor the price spread predicts
capture; their ratio does.** Across the 44 usable (zone, year) cells, rank
correlation with the capture ratio:

| cell predictor | ρ vs capture | ex-NO2 |
|---|---|---|
| **MAE ÷ mean realised daily spread** (`error_over_headroom`) | **−0.738** | **−0.682** |
| within-day Spearman | +0.698 | +0.599 |
| oracle value (EUR/MW/yr) | +0.331 | +0.249 |
| mean realised daily spread | +0.256 | +0.203 |
| MAE | **−0.015** | −0.071 |

MAE alone carries **no** cross-cell information about capture — the flat
confirmation of FINDING C11-D's direction that one year could not give — and the
spread alone carries little. Error measured *in units of the headroom it has to
find* carries most of it, and the per-year cross-zone version has an interval
excluding zero in **three of five years at the daily block and five of five at
7 and 14 days** (−0.43 to −0.73).

It also explains the year effect in FINDING C13-A. Mean over the usable cells:

| year | capture | error ÷ headroom | mean spread | within-day Spearman |
|---|---|---|---|---|
| 2020 | 0.799 | 0.234 | 27.03 | 0.790 |
| 2021 | 0.721 | 0.287 | 65.34 | 0.786 |
| 2022 | 0.766 | 0.272 | 161.15 | 0.766 |
| 2023 | 0.832 | 0.237 | 82.42 | 0.784 |
| 2024 | 0.859 | 0.217 | 88.39 | 0.789 |

The spread rises six-fold from 2020 to 2022 while capture barely moves; the
error-to-headroom ratio tracks capture's ordering in four of the five years.
2024 — the year every earlier cycle's headline rests on — is the **most
favourable year in the sample on both counts**, which is a label C18 must carry.

**FINDING C13-E — NOTE C12-02 is answered: the thin-spread story does not
explain NO2.** Fitting capture on log(mean realised spread) over the other eight
zones' 40 usable cells (slope +0.0196 per log unit, residual sd 6.35pp) and
asking where NO2 lands:

| year | NO2 capture | predicted from the eight-zone line | residual |
|---|---|---|---|
| 2021 | 0.4480 | 0.8030 | **−35.5pp** (−5.6 sd) |
| 2022 | 0.5230 | 0.8264 | **−30.3pp** (−4.8 sd) |
| 2023 | 0.6279 | 0.8111 | **−18.3pp** (−2.9 sd) |
| 2024 | 0.6146 | 0.8101 | **−19.5pp** (−3.1 sd) |

Conditioning on the realised spread removes **almost none** of NO2's deficit: it
sits 2.9-5.6 residual sd below the line in every non-thin year. A thin-spread
mechanism predicts NO2 lands *on* the line and it does not. The ordering
mechanism (FINDING C12-C) survives — NO2's within-day Spearman is the lowest of
the nine in all five years. C15's throughput-cost ladder should be read against
this: the thin-spread leg now has a prior answer to beat.

### The crisis year

**FINDING C13-F — the 2022 crisis multiplied both the prize and the loss by
~2.5× and left the captured *share* alone.** Per zone, 2022 against the mean of
that zone's other usable years (unpaired intervals):

| zone | capture 2022 | other years | Δ | oracle × | EUR/MW/yr lost 2022 vs others |
|---|---|---|---|---|---|
| DE-LU | 0.8238 | 0.8643 | −4.05pp [−12.58, +4.56] | ×2.35 | 21 092 vs 6 438 |
| ES | 0.7980 | 0.8125 | −1.45pp [−13.52, +10.68] | ×1.72 | 10 732 vs 4 624 |
| NO2 | 0.5230 | 0.5635 | −4.05pp [−19.83, +12.23] | ×2.53 | 25 796 vs 8 920 |
| FR | 0.7757 | 0.8496 | −7.39pp [−17.97, +3.47] | ×2.39 | 22 567 vs 6 391 |
| NL | 0.7996 | 0.8361 | −3.65pp [−9.66, +2.46] | ×2.52 | 27 771 vs 8 197 |
| BE | 0.7544 | 0.8347 | **−8.04pp [−15.41, −0.81]** | ×2.71 | 32 108 vs 7 614 |
| IT-North | 0.8553 | 0.8588 | −0.35pp [−9.95, +9.85] | ×2.65 | 12 564 vs 4 211 |
| DK1 | 0.7539 | 0.7830 | −2.91pp [−11.88, +6.37] | ×2.42 | 27 302 vs 9 498 |
| PL | 0.8118 | 0.7623 | +4.95pp [−2.76, +12.59] | ×2.37 | 16 638 vs 7 031 |

Eight of nine zones captured a *lower* share in 2022 and **one** interval
excludes zero. The crisis is unmistakable in the levels — the perfect-foresight
battery earned 1.7-2.7× its usual, and the money a forecast-driven battery left
on the table rose to 2.4-4.2× — and close to invisible in the ratio. The honest
sentence for C18 is therefore: *a crisis is a bigger prize and a proportionally
bigger loss, not a worse hit rate*.

### The price regime, and the negative hours PLAN.md asks for

`c13_regime_table.csv`. Negative hours per (zone, year):

| zone | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|
| BE | 136 | 159 | 112 | 222 | 404 |
| DE-LU | 298 | 139 | 69 | 301 | 457 |
| DK1 | 192 | 87 | 38 | 281 | 375 |
| ES | 0 | 0 | 0 | 0 | 247 |
| FR | 102 | 64 | 4 | 147 | 352 |
| IT-North | 0 | 0 | 0 | 0 | 0 |
| NL | 97 | 70 | 85 | 316 | 458 |
| NO2 | 5 | 5 | 0 | 174 | 206 |
| PL | 0 | 0 | 0 | 43 | 197 |
| **total** | **830** | **524** | **308** | **1 484** | **2 696** |

Two structural facts a reader should have before any zone comparison: negative
prices nearly **vanish** in the crisis year (308 hours across nine zones, the
fewest of the five) and then rise 3.3× from 2023 to 2024 as solar builds out;
and **ES printed its first negative hour of the whole window in 2024** (247 of
them) while **IT-North has never printed one**. A cross-zone claim about
negative pricing is therefore a claim about a particular year.

---

## 8. The flagged zone-year — FLAG C13-01

**NO2 2020 fails CLAUDE.md's pooled naive-dominance invariant, and it is a
regime fact rather than a bug.** The numbers: the comparable LEAR arm settles
**−402 EUR/MW** over the year against the naive floor's **+253 EUR/MW**, a
margin of −655 EUR; the perfect-foresight battery itself earns only **769
EUR/MW/yr**; the mean realised daily spread is **3.41 EUR/MWh** against a 2
EUR/MWh throughput cost and a 12% round-trip loss; capture is **−0.5222**.

NO2's 2020 mean price was **9.3 EUR/MWh** — a Nordic hydro glut — and a battery
trading a 3.4 EUR/MWh daily range while paying 2 EUR/MWh per MWh discharged has
no headroom at all. In that regime whether a curve trades *less* is luck, so the
ranking of two curves that are both trading noise carries no information, and
CLAUDE.md's own qualification of this invariant ("on average, not per-day") is
the relevant one: it is an empirical claim about an average over regimes, and
2020 NO2 is the regime where it fails.

What this cycle did about it, and did not do:

* **The assertion was not weakened.** The check still runs on every zone-year
  and still reports `holds: false` here.
* The per-day **same-start oracle bound** — the actual theorem, and the one whose
  violation would mean a broken LP — **holds on all 26 262 (curve, day) checks
  of the 36 zone-years this cycle dispatched, with a worst per-day excess over
  perfect foresight of exactly 0.0 EUR**, as do the
  settlement-is-not-a-readback and decision-value-added checks on every curve of
  every zone-year. (2024's 9 873 rows were checked by C11 and are not
  re-dispatched here.)
* The dispatch phase **records** the failure in `c13_invariant_flags.json`,
  **exits non-zero**, and the analyse phase labels the cell.
* The cell is reported everywhere and **excluded from the cross-zone band
  statistics and from every baseline average**, under a declared floor: a
  (zone, year) whose *perfect-foresight* battery earns less than 2 000
  EUR/MW/yr is a cell where the capture ratio's denominator is noise. One cell
  of 45 is flagged, the gap is an order of magnitude wide (769 against 8 992 for
  the next thinnest), and `label_count_by_floor` in the summary shows that no
  floor between ~1 000 and ~8 000 EUR/MW/yr changes a single label.

The economically interesting reading is in the write-up's favour, not against
it: **a 2 EUR/MWh throughput cost is not a rounding error in a thin market, it
is the whole result**, and C15's throughput-cost ladder now has a zone-year
where the answer is known in advance.

---

## 9. What this cycle did not do

**The Tier-A exogenous and GBM arms were not extended to the new years.** NOTE
C12-01 asked C13 for "the three GBM-exogenous capture deltas with intervals" per
year, and that is not here. The reasons, in order of weight:

1. **Only one new year is even available.** Those arms are aligned to
   `train_from=2022-01-01` because no archived ENTSO-E D-1 forecast vintage
   exists earlier (PLAN.md, `features.yaml`), and the harness requires 365
   market days of history before a fold may run. So the honest evaluation years
   for an exogenous arm are 2023 and 2024 — one new year, not four. FINDING
   C12-E's two unestablished zones would be decided by *one* extra draw, which
   is the same "one year decides too little" problem in a new coat.
2. **It needs a fresh ENTSO-E pull**, because `data/raw/` does not survive a
   container (NOTE C2-02, now at its 24th recurrence): three zones × two
   document types × two years of full-year A65/A69 documents, one of which is
   ~13 MB of XML per zone-year.
3. **C13's own scope comes first.** PLAN.md C13 is the regime analysis; the
   exogenous ladder is NOTE C8-01's question, and NOTE C12-01 explicitly left
   the call to this cycle.

It is therefore carried forward as **NOTE C13-04** with the reason above, and
the right home for it is the cycle that already has to re-pull ENTSO-E data.

**No new model, no new config, no tuning.** The GBM config fingerprint
`a366a760e269bba6` was not touched, no `config/*.yaml` changed (config hash
`515d4e8d98887256`, unchanged since C8), and PLAN.md's prohibition on a
hyperparameter search across cycles is intact.

---

## 10. Limitations of this cycle's own numbers

* **Four of the five years are configuration-visible** (§2). The per-year
  evidence is four extra walk-forward draws, not four independent experiments.
* **A year-on-year difference is unpaired** and therefore wide (§3). Several of
  the year-on-year moves below are large as point estimates and still fail to
  exclude zero; the interval is the honest statement.
* **Nine zones is nine points.** A cross-zone rank correlation at n = 9 has a
  wide interval however many years it is computed in, and computing it in five
  years does not make the five estimates independent of one another — they share
  the zones, the model and the specification.
* **No multiplicity correction.** Five years × two scopes × three block lengths
  is a lot of intervals, and the ladder is a robustness check, not three
  independent tests. The conservative reading remains C12's: take the rung least
  favourable to the claim being made, which at n ≈ 365 is usually the 1-day one.
* **The price history itself is not a controlled experiment.** 2020 is a
  demand-collapse year, 2021 a gas ramp, 2022 the crisis, 2023-24 the
  normalisation. A per-year table is a description of what those regimes did to
  a battery, not an identification of why.
