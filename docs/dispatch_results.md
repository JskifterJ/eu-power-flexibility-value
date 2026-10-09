# C11 — the battery LP across nine zones, and what the capture ratio says that MAE does not

`backtest/run_c11_dispatch.py`, `tests/test_c11_dispatch.py` (51 tests).
Artefacts: `backtest/results/c11_dispatch_<ZONE>_2024_{daily.csv.gz,summary.json}`,
`c11_capture_daily_2024.csv.gz` (16 440 rows — every curve × every dispatched
day, the file C12 bootstraps over), `c11_comparable_capture.csv`,
`c11_dispatch_summary.json`, and 1 638 rows appended to
`backtest/results/results.csv`.

PLAN.md C11 is one sentence: *"LP across all 9 zones x all curves; persist
per-day capture ratios."* This is what came out of it, and the three decisions
it forced.

## What was dispatched

Nothing was re-fitted. Every curve is the forecast the cycle that scored it
committed, read from that cycle's artefact, so a capture ratio and the MAE of
the same forecast are about the same numbers and cannot drift apart.

| tier | zones | curves |
|---|---|---|
| A | DE-LU, ES, NO2 | oracle + **8**: `lear_full_history` (C8's `price_only_full_history`, 2019+), the three 2022-aligned LEAR arms and the three 2022-aligned GBM arms (C8/C9), and the naive floor |
| B | FR, NL, BE, IT-North, DK1, PL | oracle + **2**: the comparable LEAR (2019+) and the naive floor (C10) |

45 rolled dispatch runs and 45 same-start oracle re-solves, ~33 000 LP solves,
2m09s. The two `res_as_published` arms carry `vintage="after_gate_closure"` and
exist **only** as the measurement of FINDING C9-C's leak; no number from them is
achievable by a bidder.

### Invariants — all green, every curve, every day

`value(curve @ realised) <= value(same-start oracle)` on **every** dispatched day
of **every** curve (not a sample); the pooled `oracle >= arm` and
`naive <= forecast`; no settlement is a read-back of its own decision prices;
`value_added >= 0` on each curve's own decision prices, and at realised prices on
the oracle; day lengths match the local calendar. `invariant_failures` is `[]` in
all nine zones.

### C11 reproduces C6 exactly

C6 dispatched C4's `y_pred_lear_aic` on DE-LU. That column is identical to C8's
`y_pred_price_only_full_history` to **0 EUR/MWh over 8 784 hours**, so C11's
`lear_full_history` arm is the same forecast and the two cycles must agree
exactly. `check_c6_reproduction` asserts eight numbers against C6's committed
summary at C6's own JSON precision, and **8/8 hold, worst absolute delta 2.7e-05**
(oracle/model/naive pooled cash, both rolled capture ratios, both same-start
capture ratios, the common-day count).

Getting that check to pass was itself the first real test of the scope decision
below: C6's pooled cash figures are over the common day set and its per-curve
capture summaries are over each curve's own days, so comparing C6's naive
capture (0.779737) against C11's `common_hours` naive capture (0.780436)
disagrees in the third decimal for a reason that is a **scope**, not an error.
C11's `own_coverage` naive capture is 0.779737 exactly.

## Decision 1 (NOTE C10-01) — the NaN policy

Committed, unchanged from C6's NOTE C4-02: the dispatched LEAR curve is the
`nan_policy="decline"` series every earlier cycle scored, and a market day whose
forecast vector has a hole is **skipped and counted, never patched**. It costs
one autumn-DST day a year in every zone (365 of 366 dispatched), plus in ES the
days the `res_*` arms decline. Every skip is in the per-zone summary with its
reason.

## Decision 2 (NOTE C10-01) — the capture-ratio scope

A capture ratio is a **ratio of two sums**, so numerator and denominator must run
over the same days, and two arms' ratios are only comparable if they do too.
`pooled_capture` therefore takes the day set as an *argument*, and both scopes
the store already knows are written, meaning for a dispatch metric exactly what
they mean for a point-error one — the vocabulary is about *coverage*, not about
the time unit:

- **`own_coverage`** — each curve pooled over the days it dispatched, with its
  same-start denominator over those same days.
- **`common_hours`** — every curve of that zone re-pooled over the intersection
  of the days every one of that zone's C11 curves dispatched. This is the scope a
  within-zone arm comparison must be read at.

The cross-zone table is built from `own_coverage`, as C10's was, because the two
tiers' intersections are over different curve sets (nine curves in Tier A, three
in Tier B) and a Tier-A intersection shrunk by an arm that is not even in the
cross-zone comparison would silently re-scope Tier B's neighbours. **The risk in
that choice is measured, not argued away**: `scope_sensitivity` reports the gap
between the two scopes for every curve in every zone, on **both** ratios,
because the decision has to be auditable on the metric it is actually read off.

For the three curves the cross-zone table is built from, the gap (own − common)
on the headline rolled-oracle ratio is:

| curve | gap, pp of capture |
|---|---|
| oracle | +0.0000 in all nine zones (1.0000 by construction at either scope) |
| comparable LEAR | +0.0000 in eight zones, **−0.2394 in ES** |
| naive | −0.4064 to +0.4158 across the nine zones |

Two things to read off that. First, **the comparable arm is scope-invariant in
eight of nine zones** — it and the oracle dispatch the same 365 days, so the
intersection changes nothing. Second, **ES is the whole argument in one number.**
Its Tier-A intersection is over nine curves including the two `res_*` arms, whose
exogenous join has 145 missing hours, so `common_hours` leaves ES with **357
days** where every other zone keeps 365 — and a cross-zone table at that scope
would compare ES on a day set eight days shorter than its neighbours', for a
reason belonging to two arms that are not in the comparison at all. ES's capture
is 0.910932 at `own_coverage` and 0.913326 at `common_hours`; either leaves it
second of nine, so **the decision does not change the cross-zone ordering**, but
the artefact is real and belongs in a labelled row rather than an implicit
default.

The naive floor is the one curve that genuinely moves (up to 0.42pp), because it
is the only curve that dispatches all 366 days while the comparable arm declines
one — which is exactly the 365-vs-366 mismatch the two scopes exist to make
visible. `n` and `n_scored` ride on every store row so the day count is never
inferred.

## Decision 3 (FINDING C11-C) — the headline capture is the *rolled-oracle* ratio

The same-start oracle is the exact per-day bound and stays the invariant. It is
**not** fit to compare arms, and C11 can show that rather than assert it.

On DE-LU, `lear_res_persistence` and `lear_res_as_published` settle **0.35 EUR
apart over 365 days** (67 842.68 vs 67 843.03) — yet their same-start capture
ratios differ by **4.0pp** (0.8589 vs 0.8985). The arms' per-day cash genuinely
differs (mean |Δ| 37 EUR/day, max 282; 13 of 365 days identical), so these are
two real and different schedules whose annual totals coincide. The 4pp gap is
not about their earnings at all: it is the *denominator* moving. The same-start
oracle is re-solved from each arm's own opening SoC, and a day opened with a
fuller battery has less attainable added value — mean opening SoC 0.454 MWh for
the as-published arm against 0.216 for the persistence arm, so the arm that
happens to carry more inventory is scored against an easier ceiling.

The rolled-oracle ratio has **one denominator per zone**, identical for every
curve, and ranks the two arms identically (0.9123 both). So:

> **The project's headline capture ratio is settled cash over the rolled
> perfect-foresight run's cash on the same days.** The same-start ratio travels
> beside it as the exact per-day bound and as the per-day distribution, and is
> never used to rank two curves.

`test_finding_c11_c_the_same_start_ratio_reorders_arms_the_rolled_one_ties`
pins this against the committed artefact, so a later cycle cannot quietly
promote it back.

## FINDING C11-A — the capture ratio diverges across zones; rMAE does not

FINDING C10-A gave C11 a prediction to test: *if the capture ratio is also
regime-insensitive, regime differences do not reach flexibility value through
forecastability; if it diverges while rMAE does not, that is the sharper
finding.* **It diverges.**

| zone | tier | regime | rMAE (C10) | **capture** | naive capture | oracle EUR/MW/yr | model EUR/MW/yr | lost EUR/MW/yr | mean daily spread | days model loses money |
|---|---|---|---|---|---|---|---|---|---|---|
| DE-LU | A | thermal-RES-mixed | 0.6971 | **0.9187** | 0.8450 | 74 399 | 68 179 | 6 034 | 111.20 | 0.8% |
| ES | A | solar-dominated | 0.6541 | 0.9109 | 0.8366 | 46 700 | 42 407 | 4 146 | 71.27 | 2.5% |
| BE | B | gas-nuclear-mixed | 0.6867 | 0.9044 | 0.8086 | 62 163 | 56 055 | 5 929 | 91.84 | 1.4% |
| IT-North | B | gas-dominated | 0.6896 | 0.9042 | 0.8177 | 41 864 | 37 799 | 4 004 | 65.40 | 0.8% |
| NL | B | gas-RES-mixed | 0.7160 | 0.9031 | 0.8263 | 76 207 | 68 650 | 7 366 | 113.04 | 1.1% |
| PL | B | coal-dominated | 0.6776 | 0.8839 | 0.7859 | 77 116 | 68 029 | 8 935 | 120.24 | 2.7% |
| FR | B | nuclear-dominated | 0.6440 | 0.8526 | 0.7621 | 55 052 | 46 777 | 8 085 | 76.37 | 0.8% |
| DK1 | B | wind-dominated | 0.6727 | 0.8358 | 0.7178 | 64 657 | 53 884 | 10 587 | 99.82 | 7.4% |
| NO2 | A | hydro-dominated | 0.6435 | **0.6146** | 0.4803 | 26 022 | 15 994 | 10 028 | 46.28 | **25.8%** |

| quantity | mean | sd | CV | max/min | band |
|---|---|---|---|---|---|
| rMAE (LEAR/naive MAE) | 0.6757 | 0.0248 | 0.0367 | 1.113× | 7.2pp |
| **capture ratio** | **0.8587** | **0.0957** | **0.1114** | **1.495×** | **30.4pp** |
| naive capture ratio | 0.7645 | 0.1138 | 0.1489 | 1.759× | 36.5pp |

The capture ratio's coefficient of variation is **3.0× rMAE's** and its band is
**4.2× as wide**. A point-error metric that is near-constant across nine regimes
sits on top of a dispatch metric that is not.

And the ranks do not line up — if anything they run the wrong way. **NO2 has the
best relative forecast skill of all nine zones (rMAE 0.6435, rank 1) and by far
the worst capture (0.6146, rank 9). DE-LU is second-worst on rMAE (rank 8) and
best on capture (rank 1).** The rank correlation between rMAE and capture is
**+0.58** (Spearman, p=0.099) — *positive*, i.e. the zones where the model is
relatively worse than naive capture *more* of the oracle's value, which is the
opposite sign of what forecastability would imply.

**What must travel with this.** n = 9, one validation year. The +0.58 is not
significant and its sign should not be leaned on. And the 30.4pp band is
substantially **one zone**: drop NO2 and the remaining eight sit in 0.8358–0.9187,
a band of 8.3pp with CV 0.0335 — still wider than rMAE's but no longer dramatic.
So the defensible claim is the *inequality of the bands and the non-alignment of
the rankings*, not a law about regimes. **C12's block-bootstrap CIs over daily
blocks decide whether the 8.3pp eight-zone band is wider than noise**, and that
has to land before C18 makes anything of it.

One thing the capture ratio says that MAE cannot: **the model's uplift over the
naive floor is largest exactly where capture is lowest** — NO2 +13.4pp, DK1
+11.8pp, against DE-LU +7.4pp and ES +7.4pp. The zones where perfect foresight
is hardest to approach are the zones where a forecast is worth the most relative
to not having one.

## FINDING C11-B — NO2 is the outlier, and the mechanism is not established

NO2 is the interesting case and deserves its own line in the write-up:

- lowest mean daily spread of the nine (46.28 EUR/MWh vs 65–120 elsewhere);
- lowest oracle value by a wide margin (26 022 EUR/MW/yr vs 41 864–77 116);
- fewest oracle cycles (418 equivalent full cycles vs 577–721);
- the model **loses money at realised prices on 25.8% of dispatched days**,
  against 0.8–7.4% in every other zone.

The natural story — a thin spread leaves less headroom over the round-trip
efficiency and the 2 EUR/MWh throughput cost, so a given forecast error more
easily flips a trade from profitable to loss-making — is *consistent* with all
four observations. **It is not established.** Every spread-based regressor's
correlation with capture across the nine zones collapses when NO2 is removed:
mean daily spread Pearson +0.60 → **+0.00**, oracle value +0.66 → **−0.01**,
spread over the round-trip breakeven +0.39 → −0.21. With n = 9 this is one zone,
not a relationship. The one strong correlate — share of days the model loses
money, Pearson −0.97 — is close to mechanically true (losing days reduce the
numerator) and is a restatement, not an explanation.

**The direct test already exists in the plan**: C15's throughput-cost
sensitivity (0 / 2 / 5 EUR/MWh). If the thin-spread mechanism is right, NO2's
capture should move far more than the other zones' when the cost goes to 0. C13
should also report whether NO2's capture is stable across years or specific to
2024's hydrology.

## FINDING C11-D — among honest arms, MAE does not predict capture

This is the finding C11 exists to produce, and the one C18's model section
should be built around.

Every intervention this project has measured, scored twice: the MAE gain in per
cent (recomputed over **exactly the hours the capture ratio is computed over**,
not re-used from C10's own-coverage rows — ES's exogenous hole differs by ~145
hours and would make the comparison unpaired), and the change in capture ratio
in percentage points. Positive = the arm is better.

| question | zone | ΔMAE % | Δcapture pp | ΔEUR/MW/yr |
|---|---|---|---|---|
| **honest exogenous block, LEAR** (`res_persistence − price_only`) | DE-LU | −0.26 | +0.22 | +166 |
| | ES | +1.08 | +0.52 | +236 |
| | NO2 | −0.52 | −0.83 | −217 |
| **honest exogenous block, GBM** | DE-LU | +1.03 | +0.35 | +262 |
| | ES | +0.85 | **+2.04** | **+924** |
| | NO2 | +0.23 | **+2.71** | **+706** |
| **model class, price-only** (`gbm − lear`) | DE-LU | +3.17 | −0.59 | −435 |
| | ES | −1.15 | −2.22 | −1 006 |
| | NO2 | +4.72 | −2.02 | −525 |
| **model class, with the block** | DE-LU | +4.41 | −0.46 | −340 |
| | ES | −1.38 | −0.70 | −318 |
| | NO2 | +5.43 | +1.53 | +398 |
| **more history** (`full_history − price_only`) | DE-LU | +2.81 | +0.86 | +641 |
| | ES | +3.62 | −0.27 | −123 |
| | NO2 | **+7.42** | **−1.31** | −342 |
| *vintage premium, LEAR — **not achievable*** | DE-LU | +8.33 | +0.00 | +0 |
| | ES | +11.13 | −0.84 | −381 |
| | NO2 | +0.14 | −0.76 | −197 |
| *vintage premium, GBM — **not achievable*** | DE-LU | **+23.91** | +3.47 | +2 577 |
| | ES | +17.71 | +0.95 | +429 |
| | NO2 | +3.58 | −0.84 | −220 |

**Across the 15 honest comparisons the two metrics agree on the sign 9 times —
a coin flip — with Spearman +0.02 (p=0.95) and Pearson −0.11 (p=0.69).**
Knowing which of two honest arms has the lower MAE tells you essentially nothing
about which one captures more flexibility value.

Three specific reversals matter for the write-up:

1. **NOTE C8-01 is answered, affirmatively, for the booster.** The honest
   exogenous block buys **+0.35 / +2.04 / +2.71pp** of capture (+262 / +924 /
   +706 EUR/MW/yr) in DE-LU / ES / NO2 under the GBM — far more than its
   +1.0% / +1.0% / +0.2% of MAE suggested, and *the ordering is inverted*: NO2
   gained the least on MAE and the most on capture. This is the first time in
   this project that a decision-relevant metric has disagreed with MAE about
   whether a feature block is worth having, and it is exactly the mechanism
   NOTE C8-01 hypothesised — RES information kills the large errors, and those
   sit in the high-wind, negative-price hours a battery earns in. Under the LEAR
   the same block buys nothing (+0.22 / +0.52 / −0.83pp), consistent with
   FINDING C8-A.
2. **"Gradient boosting beats LEAR" does not survive the move to a dispatch
   metric.** At an honest vintage, price-only, the GBM has the lower MAE in
   DE-LU (+3.17%) and NO2 (+4.72%) and yet **loses on capture in all three
   zones** (−0.59 / −2.22 / −2.02pp). With the exogenous block it loses DE-LU
   and ES and wins only NO2. Read with FINDING C9-C — the booster's whole
   advantage was concentrated in the leaking arm — the C18 ranking of model
   classes should be stated on capture, and it does not favour the booster.
3. **FINDING C10-B's window gain largely evaporates.** Three extra years of
   price history were worth +2.81 / +3.62 / +7.42% of MAE; in capture terms they
   are +0.86 / −0.27 / **−1.31**pp. NO2 had the largest MAE gain of any
   intervention measured in this project and the *second-worst* capture outcome.
4. **The Art. 14 leak buys almost nothing a battery can trade.** Worth 8.3% and
   11.1% of MAE to the LEAR, it is worth +0.00 and −0.84pp of capture. Under the
   GBM the 23.9% MAE gain on DE-LU does convert to +3.47pp — so the leak is not
   *uniformly* worthless — but this number is `after_gate_closure` and
   unachievable, and it is the one place where a large MAE gain and a large
   capture gain coincide.

NOTE C9-01's prediction is confirmed and generalised: a roughly uniform upward
bias (−0.03 to +3.0 EUR/MWh on the comparable curves) barely perturbs the
within-day ordering a battery trades on — and more than that, **most point-error
gains do not reach the ordering either**.

**The caveat that has to travel with FINDING C11-D.** n = 15 paired comparisons,
three zones, one year, and most of the capture deltas are under 1pp. A good deal
of this could be noise around zero, and the honest reading today is "MAE is not
a reliable proxy for capture", not "MAE is anti-correlated with capture". **C12's
block bootstrap over daily blocks is what turns this from a table into a
finding**, and it should be run on the per-day artefact
`c11_capture_daily_2024.csv.gz` before C18 quotes any of these deltas. The
GBM-exogenous result (+2.04 / +2.71pp, ~700–900 EUR/MW/yr) is the largest honest
effect and the one most likely to survive.

## What C11 wrote into the results store

1 638 rows, run `C11-20261009T022531Z-5e82e39f`, store now 2 085 rows across 2
runs, `verify_append_only()` green and the committed 447 C10 rows byte-identical.
No schema change and no test edit were needed — long format makes the metric
name the extension point, exactly as `docs/results_store.md` promised, and
`test_the_metrics_c11_and_c12_will_write_need_no_schema_change` was written in
C10 against this.

Metrics per (zone, curve, scope): `dispatch_cash_eur`,
`dispatch_value_added_eur`, `dispatch_cash_eur_per_mw_year`,
`capture_same_start_pooled`, `capture_same_start_mean_daily`,
`capture_same_start_{p05,p25,p50,p75,p95}_daily`,
`capture_rolled_oracle_cash`, `eur_per_mw_year_lost_vs_oracle`,
`share_of_days_value_added_negative`, `share_of_days_with_simultaneity`,
`equivalent_full_cycles`, `realised_spread_{mean,median}_eur_per_mwh`; and at
`common_hours` only, the paired `{mae,rmse,bias}_on_dispatched_hours`.

`vintage` is `after_gate_closure` on every `res_as_published` row and `honest`
elsewhere; the oracle's rows carry `model="oracle"`,
`exog_variant="perfect_foresight"` and an empty `train_from` (perfect foresight
has no training window). `evaluation_years` is `2024` on all 2 085 rows.

## FLAG C5-01 across nine zones, for the first time

Simultaneous charge/discharge (resolved at Checkpoint B as option (b): keep the
pure LP, carry it as a stated limitation). C11 is the first cycle to measure it
outside DE-LU, and **the nine-zone picture supports that decision more strongly
than DE-LU alone did.** On the comparable arm:

| zone | days affected | intervals | energy burned (MWh) | cash from overlap, share of total |
|---|---|---|---|---|
| FR | 9 of 365 (2.5%) | 28 | 2.70 | 0.14% |
| BE | 3 (0.8%) | 5 | 0.49 | 0.03% |
| DK1 | 2 (0.5%) | 3 | 0.29 | 0.03% |
| DE-LU | 1 (0.3%) | 1 | 0.09 | 0.004% |
| ES | 1 (0.3%) | 4 | 0.39 | −0.0001% |
| NL | 1 (0.3%) | 3 | 0.30 | 0.009% |
| PL | 1 (0.3%) | 2 | 0.20 | 0.0002% |
| NO2 | 0 | 0 | 0.00 | — |
| IT-North | 0 | 0 | 0.00 | — |

The artefact is present in seven of nine zones but is tiny everywhere: at worst
2.5% of days, 2.70 MWh burned over a year, and 0.14% of settled cash. Combined
with Checkpoint B's measurement that it biases capture *against* the model by
~0.16pp (LP 0.9187 vs MILP 0.9203 on DE-LU), the pure LP remains the
conservative default. Nothing new was decided and no dispatch code was touched.

## Sealed holdout

**SEALED.** Verified before and after: marker-alone-on-a-line count 0,
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises, no `*2025*` file under `data/`, every
`market_day` in every C11 artefact in 2024, and `evaluation_years` = `2024` on
all 2 085 store rows. The 18 occurrences of the string `2025` in
`c11_capture_daily_2024.csv.gz` are digits inside float values
(`30.402025`, `34.220252`, `0.2025`), checked individually.
