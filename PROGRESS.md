# Progress log

## Current status

- **Next cycle to run:** **AWAITING HUMAN — C17 BLOCKED.** The holdout is unsealed and the
  pre-registered evaluation is ready to run, but it **has not run**: this repo's own
  ENTSO-E parser refuses every 2025 response (**FLAG C17-01**), and the fix is an edit to a
  sealed-holdout assertion, which CLAUDE.md makes a flag-and-stop event and PLAN.md lists
  among its five human checkpoints. **No 2025 forecast, dispatch or metric value has been
  computed.** Read `docs/c17_blocker.md` — §5 is the three-part decision, of which §5(a),
  approving a one-call fix to `data/entsoe.py`, is the only one that unblocks the cycle.
  A scheduled cycle firing while this line still reads AWAITING HUMAN does no new work: it
  verifies nothing has changed, appends a one-line note and stops. Once approved, C17 runs
  the single pre-registered evaluation from `backtest/results/c16_preregistration.json`
  **exactly once** — PLAN.md's stop rule: no model, feature, hyperparameter, battery
  parameter or metric definition may change after the first 2025 number is seen. A change
  that looks necessary is a finding to report, and any re-run must be labelled as a second
  evaluation.
- **FLAG C17-01 — `data/entsoe.py`'s sealed-timestamp check never asks whether the human
  unsealed the holdout, so the whole Tier-A 2025 exogenous pull is refused.** `sealed_years()`
  is the permanent declaration in `config/data.yaml` and still reads `{2025}` by design;
  `holdout_is_unsealed()` is the approval, and `parse_document` consults only the first.
  Right before Checkpoint C ("contains a sealed year" and "leaked past the requested
  window" were then the same condition), wrong after it. Observed 6 times of 6 on the live
  pull and reproduced offline by `entsoe_parse_guard_probe()` with a synthetic A65
  document. The repo's own
  `tests/test_c7_entsoe.py::test_fetching_2025_now_passes_the_holdout_guard` already
  asserts the behaviour the code lacks — it passed locally at Checkpoint C only because no
  API key was set there. Proposed fix (not applied): route the hit through
  `assert_not_sealed`, exactly as the two sibling checks in `data/prices.py:120` and
  `data/exogenous.py:275` already do.
- **FLAG C17-02 — seven tests are red and six of them are correctly obsolete, not broken.**
  One is FLAG C17-01's own regression test; the other six assert a pre-fetch or
  pre-approval state that this cycle legitimately changed (2025 prices are now cached and
  in the download record, and the seal is open). They are the same family the Checkpoint C
  session rewrote across nine files, and they could only go red once a real 2025 fetch
  happened. **Nothing under `tests/` was touched.** The table in `docs/c17_blocker.md` §5(b)
  names each one and why. Related and now settled: **Bug 3 from the Checkpoint C session is
  a Windows-only artefact** — on Linux `results.csv` holds no CRLF bytes and
  `verify_append_only()` returns `verified: True` over 6 runs and 14 265 rows, so no
  committed result is affected; the two skip markers stay in place because removing them is
  a `tests/` edit.
- **C16 complete — Checkpoint C requested.** Two committed artefacts, both machine-checked
  rather than asserted: `backtest/results/c16_seal_verification.json` (the seal: marker
  absent, 33 guard calls across 14 modules, 6 of 6 required modules guarded, **8 of 8**
  public entry points and **2 of 2** runners refused a 2025 request, 243 tables + 172
  summaries scanned clean, and the `data/manifest/` download record carrying no 2025 row
  and no 2025 coverage timestamp) and `backtest/results/c16_preregistration.json` (the single
  evaluation specified in full and stamped with `ae59c54` / config `515d4e8d98887256`).
  Readiness report: `docs/checkpoint_c.md`. Runner `backtest/run_c16_checkpoint.py`,
  39 new tests. **No 2025 data was fetched, loaded, read or measured.** One code fix
  outside the checkpoint (an empty-cache `KeyError` in C14's cache verifier — see the
  entry below); **no new FLAG**.
- **C15 complete** (PLAN.md's four sensitivities: throughput cost 0/2/5, daily-reset vs
  rolling-horizon SoC, RES-forecast degradation, 2h vs 4h). Six batteries x 51
  (leg, zone, year) cells = **1 836 rolling-horizon runs**, nothing re-fitted.
  **FINDING C15-A** (~3% of the capture shortfall is friction and ~97% is not — NOTE
  C13-02 answered), **FINDING C15-B** (4h: +25 094 EUR/MW/yr, +1.61pp capture, 95 fewer
  full cycles a year), **FINDING C15-C** (a forced closing inventory is the biggest lever
  in the ladder: −3.97pp and −3 185 EUR/MW/yr), **FINDING C15-D** (**the surprising
  finding** — the committed battery already ends **74-77% of days empty**, so the
  end-of-day mark mostly does not prevent the degeneration it exists for, and where it
  binds the point estimate says it *costs* ~2 900 EUR/MW/yr; **not established**),
  **FINDING C15-E** (removing every euro of friction closes **9.1%** of NO2's capture
  deficit; NO2 is last of nine on capture *and* on within-day Spearman in **30 of 30**
  (year, rung) rows), **FINDING C15-F** (the Art. 14 leak's dispatch value is a
  model-class fact, not a battery fact) and **FINDING C15-G** (levers move the money with
  confidence and the captured *share* with very little — FINDING C12-D across a new
  dimension). **No new FLAG**; **FLAG C13-01 reproduced at all six rungs** and still a
  regime fact. **One new decision request: NOTE C15-01.** No open blocker.
  Write-up: `docs/sensitivities.md`.
- **NOTE C15-01 — DECISION REQUEST, for the human at Checkpoint C or D.** FINDING C15-D
  says the committed `trailing_value` end-of-day mark (i) does not prevent the nightly
  degeneration it was introduced for and (ii) where it binds, the point estimate is that
  it **costs** the battery ~2 900 EUR/MW/yr — **not established** (16 of 45 cells on
  cash, 0 of 45 on capture). **C15 changed nothing.** Options: **(a)** keep it and carry
  FINDING C15-D as a stated limitation in C18 (**recommended** — the effect is not
  established and every C5-C14 headline stays exactly as published); **(b)** re-run the
  headline on `terminal_mode="none"`, which moves every published number and needs its
  own cycle; **(c)** mark closing inventory at a lower quantile, which is a new modelling
  choice and therefore a new sensitivity, not a fix.
- **C15 also discharged NOTE C14-04's reproducibility check, at scale.** C15's `base`
  rung reproduces **54 756 committed per-day settled-cash rows to 5.0e-7 EUR** — 49 284
  against `c13_daily_by_year.csv.gz` and 5 472 against `c11_capture_daily_2024.csv.gz`
  over five curves — in a fresh container, off an independent price re-pull, via a runner
  that did not exist when those numbers were published. DE-LU 2024 capture 0.9187 and NO2
  2024 0.6146, both ends of FINDING C11-A, to four decimals.
  `check_baseline_reproduction` and `check_res_leg_reproduction` are committed and
  tested; **C20 should run them rather than start fresh** (NOTE C15-04).
- **A third label for C18, from C15 (NOTE C15-02).** **Quote a lever in EUR/MW/yr, not in
  capture points**: on cash four of five levers are decided in 42-44 of 45 cells, on
  capture the best manages 11 of 45 and `soc_no_terminal` manages 0. And **"friction
  costs the battery money" and "friction explains the capture shortfall" are different
  claims, only the first of which is true** (+1 982 EUR/MW/yr of prize against 3% of the
  shortfall).
- **Human checkpoints:** **Checkpoint C closed 2026-10-12** — holdout unsealed by J.
  Checkpoint B closed 2026-10-07 (approved as-is). Checkpoint A closed 2026-10-01. Next is
  **Checkpoint D at C19** (read the write-up, verify the surprising finding, hand-check
  three numbers) and **Checkpoint E at C21** (mandatory, human-only: make the repo public).
- **Two labels every later cycle must attach, now evidenced rather than cautionary.**
  **(i) 2024 is the most favourable year of the five** — highest capture in six of nine
  zones — so every C10-C12 headline travels with "in the validation year, which is the
  best of the five evaluated". **(ii) A capture band measured in one year is not a
  regime effect** (FINDING C13-A). See NOTE C13-01.
- **Read these three before quoting any number from C10 or C11.**
  1. **FINDING C11-C** — the headline capture ratio is **`capture_rolled_oracle_cash`**
     (settled cash over the *rolled* perfect-foresight run's cash on the same days: one
     denominator per zone, comparable across curves). **`capture_same_start_pooled` is the
     exact per-day bound and must never be used to rank two curves** — its denominator is
     re-solved from each curve's own opening SoC, so a curve arriving with a fuller
     battery is scored against an easier ceiling. Demonstrated: two DE-LU LEAR arms settle
     0.35 EUR apart over 365 days yet their same-start captures differ by 4.0pp, while the
     rolled ratio ties them at 0.9123.
  2. **FINDING C12-D** — **do not rank two arms on capture at one validation year.** One
     of the fifteen honest capture deltas has an interval excluding zero, against seven
     for MAE and eight for the within-day Spearman; the median capture delta is 0.46 of
     its own bootstrap sd. Rank on the **within-day Spearman**, translate to EUR/MW/yr
     with capture (**FINDING C12-C**).
  3. **NOTE C12-03** — three earlier claims now carry a required label: C11-A's
     eight-zone band is *not established*, C11-D is *undetermined not contradicted*, and
     C10-A's "near-constant" is now the stronger *"indistinguishable from constant"*.
- **FINDING C12-A — the capture band across the nine regimes is 4-6x its own sampling
  noise; rMAE's band is not distinguishable from noise at all.** Noise-only null-band
  p < 1e-4 for capture at every block length (1 / 7 / 14 days), between/within 4.18-6.10;
  for rMAE p = 0.196 / 0.367 / 0.284, between/within 0.69-0.95. Capture band 30.40pp
  [23.27, 40.35]; rMAE band 7.42pp [5.65, 14.19]. C11's "capture's CV is 3.0x rMAE's"
  survives as **CV ratio 2.97 [1.53, 4.30]**, excluding 1 at every block. 17 of 36 zone
  pairs separate on a paired capture difference (21 of 36 at 7 days). This also sharpens
  **FINDING C10-A** from "near-constant relative skill" to **"indistinguishable from
  constant"** — nine zones' rMAE cannot be told apart from nine draws of one number.
- **FINDING C12-B — the eight-zone capture band (NO2 excluded) is NOT established.**
  8.29pp, noise-only p = **0.078** at PLAN.md's literal daily block, 0.001 at 7 days,
  0.003 at 14 days. A conclusion that depends on the block length is not established, and
  the longer rungs are the least trustworthy at n = 365 (~26 independent blocks). With NO2
  out the capture CV and the rMAE CV are indistinguishable (ratio 0.96 [0.51, 1.77]).
  **So FINDING C11-A is a finding about NO2 plus a direction. C18 must not quote the
  8.3pp band as established; C13's second year is the test.**
- **FINDING C12-C — the within-day Spearman is the only point-forecast metric that tracks
  capture across regimes.** Cross-zone rank correlation against capture, nine zones:
  within-day Spearman **+0.70 [+0.35, +0.93]** (expected sign, excludes zero at every
  block length and with NO2 removed: +0.57 [+0.07, +0.91]); rMAE +0.60 [−0.08, +0.85]
  with the **wrong** sign; MAE +0.05 [−0.25, +0.50]; spread MAE +0.08; spread bias +0.20 —
  all spanning zero. **A rival candidate mechanism for FINDING C11-B:** NO2's mean
  within-day Spearman is **0.578** against 0.71-0.89 elsewhere (DK1, second-worst capture,
  is second-worst at 0.706), and unlike every spread-based correlate C11 tried, this one
  survives dropping NO2. So the candidate is "**in NO2 the forecast puts the hours in the
  wrong order**", not "NO2's spread is too thin". **Candidate, not established** (n = 9,
  one year) — see NOTE C12-02 for how C15 distinguishes the two.
- **FINDING C12-D — capture cannot rank arms at one validation year, which is what
  FINDING C11-D actually rests on.** Intervals excluding zero across the fifteen honest
  contrasts: capture **1/15** (median |delta|/sd 0.46), EUR/MW/yr 1/15, spread MAE 5/15,
  MAE 7/15 (1.91), **within-day Spearman 8/15 (2.23)** — ordering stable at every block
  length. C11's MAE/capture rank correlation of +0.02 now has interval **[−0.53, +0.56]**;
  Pearson −0.11 [−0.58, +0.59]; sign agreements 9/15 [5, 12] against 7.5 under
  independence. **The honest statement is "one year decides 1 of 15 capture deltas, so it
  can neither establish nor rule out that MAE predicts capture" — undetermined, not
  contradicted.** The apparent disagreement is largely that capture is ~4x noisier per
  unit of effect.
- **FINDING C12-E — the GBM-exogenous capture gain survives a CI in ES only.** DE-LU
  +0.35pp [−1.83, +2.53] and NO2 +2.71pp [−2.50, +8.03] contain zero at every block length
  (NO2 despite the largest point estimate — its per-day capture is the noisiest of the
  nine, boot sd 4.19pp vs 1.50-2.60). ES +2.04pp misses at the daily block by a hair
  ([−0.26, +4.38], P(≤0) = 0.042, so the one-sided reading NOTE C8-01's directional
  question licenses does clear 5%) and excludes zero at 7 and 14 days. **The one honest
  contrast established at every block length is ES `gbm_price_only − lear_price_only` =
  −2.22pp [−4.25, −0.29]** — the booster captures *less* than the LASSO in the zone where
  it also has the lower MAE. The headline honest Tier-A arm **stays `res_persistence`**.
- **FINDING C12-F — all nine zones under-predict the daily spread**, by 7.9 (ES) to 23.7
  (NL) EUR/MWh, no exceptions. The regularised forecast day is flatter than the day that
  arrives, which biases the battery towards **under**-trading (conservative) and is part
  of why capture sits near 0.9 rather than near 1 where the ordering is good.
- **FINDING C11-A — the capture ratio diverges across the nine regimes; rMAE does not.**
  Capture spans 0.6146 (NO2) to 0.9187 (DE-LU): band 30.4pp, CV 0.1114, max/min 1.495x —
  against rMAE's 7.2pp / 0.0367 / 1.113x. The rankings do not line up and if anything run
  the wrong way (NO2 best rMAE and worst capture; DE-LU second-worst rMAE and best
  capture). **C12 confirmed the inequality of the bands (FINDING C12-A) and did NOT
  confirm the eight-zone band (FINDING C12-B); the +0.58 rMAE/capture correlation's
  interval contains zero and its sign is wrong.**
- **FINDING C11-B — NO2 is the outlier.** Lowest spread (46.28), lowest oracle value
  (26 022 EUR/MW/yr), fewest oracle cycles (418), model loses money on **25.8%** of
  dispatched days against 0.8-7.4% elsewhere. C11 found every spread-based correlate
  collapses when NO2 is dropped. **C12 adds a rival candidate that does not collapse: the
  within-day ordering (FINDING C12-C).** C15's throughput-cost ladder tests the
  thin-spread story only — see NOTE C12-02.
- **FINDING C11-D — among honest arms, MAE does not predict capture.** 9 sign agreements
  of 15, Spearman +0.02, Pearson −0.11. **Superseded in strength by FINDING C12-D: this
  is "undetermined", not "contradicted".** Its four specifics still stand as point
  estimates and must now travel with their intervals: the honest exogenous block under the
  GBM (+0.35 / +2.04 / +2.71pp — now FINDING C12-E, ES only); "gradient boosting beats
  LEAR" not surviving the move to a dispatch metric (established in ES, undetermined in
  DE-LU and NO2); FINDING C10-B's window gain being an MAE claim; and the Art. 14 leak
  buying ~nothing a battery can trade except on DE-LU under the GBM (+3.47pp
  [+0.43, +6.60], and unachievable).
- **Results live in one append-only table: `backtest/results/results.csv`** (**14 265 rows
  after C15**, 6 runs, `backtest/results_store.py`, written up in `docs/results_store.md`,
  `docs/dispatch_results.md`, `docs/metrics_layer.md`, `docs/regime_analysis.md` and
  `docs/sensitivities.md`). Long
  format, so **a new metric is a new value, not a new column** and **a new evaluation year
  is new rows** — C11 added 17 dispatch metrics, C12 added 7 point metrics plus interval
  bounds, and C13 added 4 824 rows for 2020-2023 (1 206 per year) including
  `error_over_headroom`; **none of the three needed a schema change or a test edit.**
  Every row carries `git_sha`, `config_hash`, the model's fingerprint and a
  `library_fingerprint`; `vintage` (`honest` / `after_gate_closure`) is a **required key
  column**, and `evaluation_years` is now a single year on every C13 row. **C15 added
  5 700 rows with no schema change either**: a ladder rung lives in the **metric name**
  (`c15_<rung>_capture`, `c15_d_<rung>_capture_pp`, …), which is the store's documented
  extension point, so a new battery is a new metric and never a migration. Call
  `verify_append_only()` before trusting anything in there and append with `append_rows` —
  never edit a row in place. The 3 426 C10-C12 rows are byte-for-byte unchanged after
  C13's append (verified against `git show HEAD:`). **`scope` is a closed list**
  (`own_coverage`, `common_hours`): C13's three-curve intersection is written as
  `common_hours` because that *is* C11's definition applied to C13's curve set — which in
  Tier A is **not** the same day set as C11's nine-curve 2024 `common_hours`, so read
  `source_artefact` beside any Tier-A row.
- **The per-day artefacts later cycles should read rather than rebuild:**
  `backtest/results/c11_capture_daily_2024.csv.gz` (16 440 rows, the dispatch columns) and
  **`c12_daily_metrics_2024.csv.gz`** (16 440 rows, the same rows with the per-day shape
  columns joined on: `sum_abs_error`, `sum_sq_error`, `sum_error`, `realised_spread`,
  `forecast_spread`, `spread_error`, `spearman`). Every column in the C12 file is
  **day-additive**, which is what makes `backtest/bootstrap.py` usable on it directly:
  a pooled MAE, a capture ratio and a mean Spearman are all `counts @ column`. **C13 adds
  `c13_daily_by_year.csv.gz` (49 284 rows)** — the same columns for **five** years
  (2020-2024) x nine zones x the three comparable curves, which is what C15 should
  re-dispatch from and C17 should report from rather than re-fitting 36 walk-forward runs.
  The 36 `c13_year_<ZONE>_<YEAR>_predictions.csv.gz` files are the forecasts themselves.
  **C15 adds `c15_{main,res}_<ZONE>_<YEAR>_daily.csv.gz` (51 files, 361 350 rows: the same
  shape again for each of six battery rungs) and `c15_rung_points.csv` (every pooled
  number per (leg, zone, year, rung, curve)).** C17 should read `c15_rung_points.csv`
  rather than the per-day files unless it needs to re-bootstrap.
- **`backtest/bootstrap.py` is reusable as-is for C13/C15.** Circular moving-block over
  market days, **paired** (one draw applied to every zone, curve and statistic in a
  replicate), 10 000 replicates, seed 20261009, percentile intervals, plus
  `noise_only_spread` (the null-band test, calibration-tested) and `spearman_rows`.
  **Warning: a wider block does not mean a wider interval.** At n = 365 a 14-day block
  leaves ~26 independent blocks and the long-run variance estimate gets noisy — here it
  comes out *narrower*. The ladder (1 / 7 / 14) is a robustness check, not an ordering;
  read the rung **least favourable to the claim being made**.
- **FINDING C9-C — read this before any later cycle reports a GBM number.** C8 measured
  the Art. 14 **vintage premium** (as-published vs leak-free persistence) with a per-hour
  LASSO: +8.4% of MAE on DE-LU, +11.3% on ES. C9 re-measured it with a tree ensemble on
  the same rows, vintages and folds: **+23.96% (DE-LU) and +17.82% (ES)**. The leak is
  worth *more* to a non-linear model, and the booster's whole advantage over the LASSO is
  concentrated in the late arm. On capture the same leak is worth +3.47 / +0.95 / −0.84pp
  under the GBM and ~0 under the LEAR, and C12 finds only the DE-LU one survives a CI. So
  "gradient boosting beats LEAR on a RES-fed day-ahead model" is substantially an artefact
  of a publication timestamp.
- **FINDING C8-A still stands.** At an honest vintage the entire ENTSO-E exogenous block
  is worth ~nothing on 2024 **MAE** for all three Tier-A zones (+1.0% DE-LU and ES, +0.2%
  NO2 under the booster). C11 qualified it on *capture* (+0.35 / +2.04 / +2.71pp) and C12
  bounds that: ES only. The headline honest arm for Tier A remains `res_persistence`;
  `res_as_published` travels **only** as the labelled measurement of the leak.
- **FINDING C10-B — three extra years of price history beat the entire honest exogenous
  block and the switch to a booster, in all three Tier-A zones — *on MAE*** (+2.80% /
  +3.53% / +7.45%). On capture it is +0.86 / −0.27 / −1.31pp, none of which survives a CI,
  so this is an **MAE claim** and must be labelled as one wherever C18 uses it.
- **The GBM config is frozen and tripwired.** `forecast.gbm.GbmSpec`, fingerprint
  **`a366a760e269bba6`**, lightgbm 4.7.0. PLAN.md forbids a hyperparameter search across
  cycles, so the config is pinned to literals by
  `test_the_committed_config_is_exactly_what_plan_md_froze` — **a cycle that wants to tune
  a knob has to edit a test, which CLAUDE.md makes a flag-and-stop event.** Do not edit
  it; flag instead.
- **`ENTSOE_API_KEY` is set but C10, C11 and C12 did not need it.** **C12 opened no price
  file at all** — the realised prices it needs are the committed prediction artefacts'
  own `y_true` column (which C11 verified equal to the price cache to 0 EUR/MWh), so C12
  made **0 network requests, 0 FLAGs**. This is the shape later reporting cycles should
  prefer.
- **Open FLAGs:** **FLAG C5-01** — simultaneous charge/discharge in the dispatch LP.
  **RESOLVED at Checkpoint B (2026-10-07): option (b)** — keep the pure LP as the default
  and carry the artefact as a stated limitation in the write-up. C11 measured it across
  nine zones: present in seven of nine but tiny everywhere — at worst FR with 9 of 365
  days (2.5%), 2.70 MWh burned over a year and 0.14% of settled cash; NO2 and IT-North
  show none. It biases capture *against* the model (~0.16pp on DE-LU), so it is
  conservative. Unchanged by C7-C13: C13 re-ran the dispatch code on 36 new zone-years
  without modifying it.
- **Open FLAGs (cont.): FLAG C13-01 — NO2 2020 fails CLAUDE.md's pooled naive-dominance
  invariant, and it is a regime fact, not a bug. C15 reproduced it at all six battery
  rungs** — including `throughput_0`, where the comparable arm earns **+133 EUR** against
  the naive floor's **+543**, so **removing every euro of friction does not rescue it
  either**. Six failures recorded in `c15_invariant_flags.json`, the C15 dispatch phase
  exited non-zero, no tolerance widened and no test edited. The C13 text follows and is
  unchanged. The comparable LEAR arm settles
  **-402 EUR/MW** over the year against the naive floor's **+253**; the
  *perfect-foresight* battery earns only **769 EUR/MW/yr**; the mean realised daily spread
  is **3.41 EUR/MWh** against a 2 EUR/MWh throughput cost and a 12% round trip; capture is
  **-0.5222**. NO2's 2020 mean price was 9.3 EUR/MWh (Nordic hydro glut) — there is no
  headroom to trade, so which of two curves trades *less* is luck, and CLAUDE.md's own
  qualification ("on average, not per-day") is the operative one. **The assertion was not
  weakened**: it still reports `holds: false`, the failure is recorded in
  `backtest/results/c13_invariant_flags.json`, the dispatch phase **exits non-zero**, and
  the cell is excluded from every band statistic and baseline under a declared floor
  (oracle < 2 000 EUR/MW/yr; 1 of 45 cells, and no floor between ~1 000 and ~8 000 moves a
  label). The per-day same-start oracle bound — the actual theorem — **held on all 26 262
  (curve, day) checks, worst excess exactly 0.0 EUR**. **Needs a human only if the human
  disagrees that this is a regime fact**; no later cycle should "fix" it by relaxing the
  check.
- **Open FLAGs (cont.): FLAG C14-01 — DE-LU 2023 `gbm_res_persistence` fails the same
  pooled naive-dominance invariant, and it is a TIE, not a defeat.** It settles **52 763
  EUR** against the naive floor's **52 850** over 364 days: **−87 EUR**, **0.16%**,
  per-day win rate **50.3%**. The bootstrap says tie rather than the prose doing so:
  **−0.139pp of oracle cash, 95% interval [−6.22, +6.15]** at the daily block — 44x wider
  than the point estimate — P(≤0) = 0.516 / 0.518 / 0.526 at the 1 / 7 / 14-day blocks.
  **The assertion was not weakened**: `holds: false` is still reported, the failure is in
  `backtest/results/c14_ladder_invariant_flags.json`, the dispatch phase exits non-zero,
  no tolerance was widened and no test was edited; every other check passed on every
  curve of every zone, the per-day same-start oracle bound included. **Why it matters
  beyond the flag:** this arm has the **second-best honest MAE of the eight DE-LU 2023
  curves** (23.60 against the naive floor's 33.62, a 30% improvement) and the **worst
  honest capture** (0.8453 against naive's 0.8467). A forecast 30% better than naive on
  the point metric captured no more flexibility value than naive — the sharpest instance
  in this project of **FINDING C11-D / C12-D**, and it belongs in C18 beside them. Unlike
  FLAG C13-01 (a thin-market artefact: −655 EUR on a 769 EUR/MW/yr prize) this is a tie
  in a deep market. Neither should be "fixed" by relaxing the check.
- **Earlier findings that still bind:** C9-A (PLAN.md leakage assertion (i) is vacuous for
  a pooled booster on the synthetic fixture; re-sited, `tests/test_c3_leakage_harness.py`
  untouched), **C9-B RETRACTED** (the claim that `lgb.train` keeps post-best-iteration
  trees is false on lightgbm 4.7.0; two pushed commit messages still assert the retracted
  version and cannot be rewritten — the C9 entry is the correction of record), C9-D, C9-E,
  C7-A..C7-E (`docs/entsoe_layer.md`), C8-A..C8-C (`docs/exogenous_model.md`), C4-A (the
  mean-reference contamination of the target-permutation probe).
- **Decision requests — all closed "as-is" at Checkpoint B (2026-10-07):** NOTE C3-01,
  NOTE C4-01, NOTE C4-02, NOTE C7-01. **NOTE C2-02** (the raw cache does not survive a
  container) — no change, **24th recurrence**, and it mattered again: C13 needed prices
  for 36 walk-forward runs, so it re-pulled all 54 (zone, year) files and verified **all
  54 `payload_sha256` identical to C1's** before fitting anything. The manifest was
  therefore not regenerated or re-committed.
- **NOTE C8-01 — CLOSED by C14 (FINDING C14-G), and the answer is NO.** The second
  evaluation year ran: C8's LEAR ladder and C9's GBM ladder for 2023, all three Tier-A
  zones, both runners unmodified, then the rolling LP. Across the **six** booster cells
  (3 zones x 2 years) of `gbm_res_persistence − gbm_price_only`, **exactly one excludes
  zero at the daily block and it is NEGATIVE** (DE-LU 2023, **−3.55pp [−6.76, −0.33]**);
  2024's nearest positive, ES at +2.04pp, misses at the daily block. Under the LASSO all
  six contain zero. On MAE the twelve cells are all inside ±4% (largest −3.76%) with the
  sign flipping between years in **four** of six (zone, model) pairs. **So the honest exogenous block — all
  a bidder could legitimately have had — does not have a reliable positive value, in
  either model class, either year, any Tier-A zone. C18 must not claim an exogenous
  gain**, and C15 needs no exogenous arm (NOTE C14-06).
- **NOTE C9-01, NOTE C10-01, NOTE C11-01 — all ANSWERED and closed.** NOTE C11-01's three
  questions are FINDINGs C12-B (no), C12-D (undetermined) and C12-E (ES only).
- **NOTE C12-01 — ANSWERED by C13**, except for its GBM-exogenous clause, which NOTE
  C13-04 re-homes in C14. The per-year tables exist (nine zones x five years): FINDING
  C12-B is settled as **not established** (FINDING C13-B), FINDING C12-D's "MAE cannot be
  told apart from noise" has a cross-cell answer (**rho = -0.015**, FINDING C13-D), and
  NO2's per-year capture and within-day Spearman are in `c13_per_year_metrics.csv`
  (FINDING C13-C). Original text follows.
- **NOTE C12-01 (as written for C13).** Every one of C12's unresolved questions
  reduces to the same thing: one validation year decides too little. FINDING C12-B
  (p = 0.078), FINDING C12-D ([−0.53, +0.56]) and FINDING C12-E (two unestablished zones)
  all want a second year. C13's per-year tables should report, per year: the eight-zone
  capture band with its noise-only p, the three GBM-exogenous capture deltas with
  intervals, and NO2's capture and within-day Spearman. `backtest/bootstrap.py` takes any
  day-additive column, so the machinery is reusable — **but it needs per-day dispatch rows
  for the other years, which do not exist yet** (C11 dispatched 2024 only). That is the
  one piece of new computation C13 would need, and whether it is in C13's scope or a C15
  item is C13's call.
- **NOTE C12-02 — CLOSED by FINDING C13-E.** Conditioning on the realised spread removes
  almost none of NO2's capture deficit (-18 to -36pp, 2.9-5.6 residual sd below the
  eight-zone log-spread line in every usable year), so the thin-spread mechanism does not
  explain NO2 and the within-day-ordering mechanism survives. **NOTE C13-02 re-points
  C15's throughput-cost ladder** at what it does measure: how much of the capture ratio is
  friction. Original text follows.
- **NOTE C12-02 (as written for C13/C15; refines NOTE C11-02).** FINDING C11-B's thin-spread
  mechanism for NO2 now has a rival with better cross-zone support: the within-day
  ordering (FINDING C12-C). C15's throughput-cost ladder (0 / 2 / 5 EUR/MWh) is the direct
  test of the **thin-spread** story and should be read as such; it is **not** a test of the
  ordering story, which predicts instead that NO2's capture stays low at zero throughput
  cost while its within-day Spearman stays the lowest of the nine. Running both predictions
  against the same ladder is cheap and distinguishes them.
- **NOTE C12-03 (new, for C18 — wording, not computation).** Required labels: FINDING
  C11-A's eight-zone band is **not established**; FINDING C11-D is **undetermined, not
  contradicted**; FINDING C10-A's "near-constant" is now the stronger **"indistinguishable
  from constant"**. And FINDING C12-C gives C18 its model-ranking instrument: rank arms on
  the within-day Spearman, translate to EUR/MW/yr with capture, never rank on capture at
  one year.
- **FINDING C13-A — a zone's capture ratio moves across years by as much as the eight
  zones differ from each other within a year.** Within-zone across-year band 9.6-20.0pp
  (eight non-outlier zones) against a single year's bootstrap sd of 2.8-5.1pp, so
  **2.3-5.4x its own sampling noise**; the eight-zone band within a year is 8.3-18.0pp —
  the same size. **So a capture band measured in one year is not a regime effect.** 2024
  is also the most favourable of the five years (highest capture in six of nine zones).
- **FINDING C13-B — the eight-zone capture band is NOT established (FINDING C12-B
  settled).** Noise-only p at PLAN.md's daily block: 0.095 (2020), **0.846** (2021),
  **0.523** (2022), 0.015 (2023), 0.078 (2024) — **one of five years clears 5%**. The
  nine-zone band clears in four of five, so FINDING C11-A is confirmed as **a finding
  about NO2 plus a direction**. C18 must not quote the 8.3pp band as established.
- **FINDING C13-C — NO2 is bottom on capture *and* on within-day ordering in all five
  years.** Spearman 0.470 / 0.592 / 0.650 / 0.615 / 0.578 against 0.699-0.886 elsewhere,
  every year; cross-year capture ranking +0.33 to +0.88 (positive in all ten year pairs),
  NO2 last in 10 of 10. The one C11/C12 claim five years makes **stronger**.
- **FINDING C13-D — neither the forecast error nor the price spread predicts capture;
  their ratio does.** Over 44 usable (zone, year) cells: `error_over_headroom` (pooled MAE
  / mean realised daily spread) **rho = -0.738** (-0.682 ex-NO2), within-day Spearman
  +0.698, oracle value +0.331, spread +0.256, **MAE -0.015**. Per-year cross-zone
  intervals exclude zero in 3 of 5 years at the daily block and 5 of 5 at 7 and 14 days.
  It also explains FINDING C13-A's year effect. Now a store metric.
- **FINDING C13-E — the thin-spread story does not explain NO2 (NOTE C12-02 closed).**
  Against a log-spread line fitted on the *other eight* zones' 40 usable cells, NO2 sits
  **-35.5 / -30.3 / -18.3 / -19.5pp** (2021-2024), i.e. 2.9-5.6 residual sd below it,
  every usable year. Conditioning on the spread removes almost none of the deficit; the
  within-day-ordering mechanism (FINDING C12-C) survives.
- **FINDING C13-F — the 2022 crisis multiplied the prize and the loss by ~2.5x and left
  the captured share alone.** Oracle value x1.72-2.71, EUR/MW/yr lost x2.4-4.2, capture
  delta -8.04 to +4.95pp with **one of nine** intervals excluding zero (BE). Intervals are
  **unpaired** — two years share no market day — and are labelled so everywhere.
- **NOTE C13-01 (for C18, wording).** Two labels are now evidenced: **2024 is the best of
  five years**, so every C10-C12 headline travels with that clause; and **a one-year
  capture band is not a regime effect** (FINDING C13-A). Read with NOTE C12-03.
- **NOTE C13-02 (for C15).** The throughput-cost ladder is no longer NO2's mechanism test
  (FINDING C13-E settled that). Run it for **how much of the capture ratio is friction**,
  with NO2 2020 as the stress cell (oracle 769 EUR/MW/yr, mean spread 3.41, capture
  -0.52). `c13_daily_by_year.csv.gz` plus the 36 prediction artefacts mean the ladder
  needs **no re-fitting**, only re-dispatch.
- **NOTE C13-03 (for C14/C15).** `error_over_headroom` is the strongest cell-level
  predictor of capture found so far. C14's residual-load chapter should ask whether
  **residual-load forecast error explains it** across Tier-A zones and years, and C18
  should use it as the bridge from a point metric to EUR/MW/yr beside the within-day
  Spearman.
- **NOTE C13-04 (for C14) — the Tier-A exogenous/GBM per-year deltas were NOT computed.**
  Only 2023 is available for a 2022-aligned arm (no archived ENTSO-E D-1 vintage before
  2022, plus 365 days of required history), it needs a fresh ENTSO-E pull, and PLAN.md
  C13 is the regime analysis. **NOTE C8-01 stays RE-OPENED** and is handed to **C14**,
  which must re-pull those series for its own chapter — fold the 2023 ladder in there or
  say why not.
- **Sealed holdout (2025):** SEALED. Guard verified armed in C15 after the work:
  marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`, `sealed_years()`
  = `{2025}`, `assert_not_sealed(2025)` raises `SealedHoldoutError`, **no `*2025*` file
  anywhere under `data/`**, the price cache holds exactly **2019-2024 in every one of the
  nine zones**, and store-wide `evaluation_years` across all **14 265** rows is
  **2020-2024**. C14's three-bucket string-`2025` sweep, re-run over every committed C15
  artefact and `docs/sensitivities.md`: **86** digit runs inside longer floats (e.g.
  `1073.6417765862025`), **4** bare year tokens (all of them prose in
  `docs/sensitivities.md` saying 2025 is sealed or that the backtest ends before
  2025-10-01), **0** in neither — and **0 bare tokens in any `backtest/results/c15_*`
  artefact at all**. No `year` column in any of the 51 per-day files contains 2025.
  `main_curves` has **no artefact mapping for a sealed year** and raises before a path is
  built, `dispatch_cell` calls `assert_not_sealed` first, and two tests pin both. No 2025
  data has been fetched, loaded, dispatched or computed against at any point in C2-C15.
- **Config hash:** **`515d4e8d98887256`** — unchanged from C8. C13, C14 and C15 modified
  no `config/*.yaml`, **including C15, whose FINDING C15-D is an argument for changing
  `config/battery.yaml` and which deliberately changed nothing** (NOTE C15-01). C15's
  library fingerprint is **`856fb19ac0c4eecd`**, identical to C10's through C14's (python
  3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1, lightgbm 4.7.0),
  so C10-C15 rows are directly comparable.
- **C15 modified exactly one pre-existing module, additively: `dispatch/rolling.py`**
  (74 insertions, 1 deletion — the `soc_policy` lever PLAN.md's daily-reset leg needed and
  did not have). The committed `"carry"` behaviour is pinned **byte-for-byte** by
  `test_carry_is_the_default_and_is_unchanged_by_naming_it`, and the lever is guarded so
  that a reset can only ever *discard* stored energy, never create it (see the C15 entry).
  `git diff --stat HEAD` over `tests/`, `config/`, `forecast/`, `data/`,
  `backtest/{walk_forward,metrics,bootstrap,results_store}.py`, `dispatch/battery.py`,
  `dispatch/curves.py` and every earlier runner came back **empty**. Otherwise C15 is one
  new runner (`backtest/run_c15_sensitivities.py`), one new test file
  (`tests/test_c15_sensitivities.py`, 119 tests), one new document
  (`docs/sensitivities.md`), three figures and new artefacts. C11's `pooled_capture`,
  `same_start_oracle`, `capture_frame` and `beats_naive`, C12's bootstrap and C14's
  `verify_price_cache` are **imported**, not re-derived — which is what makes a C15
  capture ratio the same number as the one in `results.csv`.
- **C14 modified no pre-existing module at all.** It is one new runner
  (`backtest/run_c14_fundamentals.py`), one new test file
  (`tests/test_c14_fundamentals.py`, 68 tests), one new document
  (`docs/fundamentals.md`), three figures, a `requirements.txt` comment block and new
  artefacts; `git diff --stat HEAD` over `tests/`, `config/`, `forecast/`, `dispatch/`,
  `data/`, `backtest/walk_forward.py`, `backtest/metrics.py`, `backtest/bootstrap.py`,
  `backtest/results_store.py` and every earlier runner came back empty. C8's and C9's
  runners were **invoked unmodified** for the 2023 ladder rather than wrapped, which is
  what makes a 2023 arm the same experiment as the 2024 one; C11's `Arm`, `pooled_capture`
  and contrast taxonomy and C12's bootstrap are **imported**, and a test checks
  `ladder_arms()` against `arms_for(zone, "A")` field by field because one different
  spelling of the store key would make the two years two unrelated rows.
- **`backtest/metrics.py` was extended in C12, additively.** 225 lines added; the only
  removed line is `from dataclasses import dataclass` becoming
  `from dataclasses import asdict, dataclass`. No existing function changed, so C3's
  leakage assertions and C4's skill score read exactly the code they read before. A *new*
  file under `tests/` follows C11's precedent and is not a flag-and-stop event; editing a
  **pre-existing** test still is.
- **Full suite green after C15: 827 passed, 0 failed** (708 before, plus C15's 119).
- **Repo-state note:** the detached-HEAD trap recurred in C15 — the container arrived
  detached at `c7ffea5` with local `master` stale **24** commits behind. **30 recurrences
  out of 37 containers.** `HEAD` equalled `origin/master` exactly after a fetch and local
  `master` was a strict ancestor, so **C14's safer recipe applied and worked first time**:
  `git checkout master` then `git merge --ff-only origin/master`, which cannot discard a
  commit and fails loudly if the branch has diverged. **That is the recipe later cycles
  should reach for** — C14 found `git checkout -B master` refused by this session's
  permission classifier as a destructive git action. C9's warning still stands for a
  container that arrives detached *and* genuinely behind the remote, where neither recipe
  is safe and the cycle should flag rather than improvise. Keep checking
  `git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the start
  of every cycle.
- **Artefact size — an input to C20's repo-size check.** C15's artefacts are ~37 MB
  against ~25 MB for C1-C14 combined, because the per-day ladder is 361 350 rows (six
  rungs x the C11/C13 dispatch surface). **Nothing was trimmed**, because a committed
  artefact that does not match what the runner writes is worse than a large one. The
  obvious saving, if C20 wants it: the ten forecast-shape columns are **rung-invariant by
  construction** (that is FINDING C15-E's Spearman point) and are stored six times;
  normalising them out would save ~40%.

## Log

### C0 — 2026-09-28 (human + local assistant session, not a scheduled cycle)
- Repo skeleton created: `data/{raw,manifest}`, `forecast/`, `dispatch/`,
  `backtest/`, `notebooks/`, `tests/`, `docs/`.
- `PLAN.md`, `CLAUDE.md`, `docs/audit.md`, `README.md`, `.gitignore`,
  `.env.example`, `LICENSE` written and committed.
- Independent pre-build audit completed (Opus subagent, no involvement in
  original design) — verdict GO conditional on 4 changes, all folded into
  `PLAN.md`. Full report in `docs/audit.md`.
- Private GitHub repo to be created next: `JskifterJ/eu-power-flexibility-value`.

### C1 — 2026-09-28 (scheduled cycle) — code complete, data pull BLOCKED

Scope per PLAN.md C1: config schema, Energy-Charts client + local cache, pull
day-ahead prices for all 9 zones, build the manifest. No modelling.

**Built and committed (all offline work done, 44 unit tests passing):**
- `config/zones.yaml` — 9 zones with tier, Energy-Charts `bzn`, ENTSO-E EIC
  domain, IANA `local_tz`, regime label, and structural-break notes (DE-AT-LU
  split, Iberian gas cap, IT zonal reconfiguration, PL SDAC go-live).
- `config/data.yaml` — splits, the sealed-holdout declaration with its exact
  unseal marker string, `fetch_years`, source endpoints/licences/politeness
  settings, and the UTC time contract. Refuses to load if `fetch_years` ever
  overlaps the sealed years.
- `config/features.yaml` — target, price-history and calendar features, Tier-A
  exogenous features each carrying an explicit `leakage_status` (Art. 6 load =
  safe; Art. 14 wind/solar = FLAGGED, post-gate-closure vintage), plus the
  excluded-by-audit list (Open-Meteo reanalysis, AGSI+) with reasons.
- `data/config.py` — config loading/validation, `config_hash()` for tagging
  result rows from C10.
- `data/holdout.py` — the sealed-holdout guard as executable code: any fetch or
  load of 2025 raises `SealedHoldoutError` unless `PROGRESS.md` contains the
  exact marker line, which only a human writes at C16. Wired into `fetch_year`,
  `read_cached_year` and therefore the manifest builder; a stray sealed-year
  cache file makes the manifest build raise rather than quietly include it.
  A tripwire test asserts the marker is currently ABSENT from this file.
- `data/energy_charts.py` — `/price` client with fetch-once cache
  (`data/raw/energy_charts/price/<ZONE>/<YEAR>.json`, gitignored, with a
  `_fetch_meta` provenance block). Strict schema validation; 4xx incl. 404
  raises immediately with no endpoint guessing; only transport/429/5xx retried
  (3 attempts, 5/15/45s); no bare `except` anywhere; a payload that fails
  validation is never written to the cache. No force-refetch flag by design.
- `data/manifest.py` + `data/build_manifest.py` — 28-column per-(zone, year)
  manifest: counts, coverage vs UTC-exact expected intervals, modal resolution
  and distinct-delta count (how the 2025-10-01 15-min cutover will surface),
  gap count/max gap, NaN count, price min/p01/mean/median/p99/max/std,
  negative-hour and zero-hour counts, raw sha256, fetch timestamp, API URL.
  CSV (human-eyeballable at Checkpoint A) + JSON with git SHA, config hash,
  licence and attribution.
- `data/fetch_prices.py` — CLI over 9 zones x 6 years (54 pairs). Per-pair
  failure becomes a FLAG line plus `data/manifest/fetch_failures.json`, skips
  only that pair, continues, exits non-zero.
- `tests/test_c1_data_layer.py` + `tests/conftest.py` — 44 unit tests over
  config, the holdout guard, request shape, 13 malformed-payload rejections,
  cache behaviour (no-refetch, 404-no-retry, bad-payload-not-cached), and
  manifest stats against a synthetic full year with injected negatives, NaNs
  and a 3-hour gap. All offline, no network, no real price data.
- `requirements.txt` + `.venv` (gitignored): requests, PyYAML, pandas, numpy,
  pytest.
- `docs/data_layer.md` — cache layout, holdout enforcement, flag-not-swallow
  policy, time handling, manifest columns, attribution.

**FLAG C1-01 — day-ahead price pull blocked by the environment's egress policy.**
Not a data-source problem: `api.energy-charts.info:443` is refused by this cloud
environment's network policy before any request reaches Fraunhofer ISE. Verbatim,
after the client's 3 retries:

```
FetchFailed: energy-charts /price DE-LU 2024: giving up after 3 attempts;
last error: ProxyError: HTTPSConnectionPool(host='api.energy-charts.info',
port=443): Max retries exceeded with url:
/price?bzn=DE-LU&start=2024-01-01&end=2024-12-31
(Caused by ProxyError('Unable to connect to proxy',
OSError('Tunnel connection failed: 403 Forbidden')))
```

The agent proxy's own status endpoint records it as `connect_rejected` /
"gateway answered 403 to CONNECT (policy denial)". `pypi.org` and `github.com`
reach fine from the same session, so this is host-specific policy, not a broken
tunnel. Per the proxy's documented guidance a policy denial must be reported,
not routed around — so no mirror, scraper or alternative source was tried, and
`config/data.yaml` still names Energy-Charts as the only price source.

*Human action needed:* widen **Network access** for this cloud environment (the
environment menu in the session title bar → Edit) — either a broader access
level or `api.energy-charts.info` added to the allowed domains. Access levels
are documented at https://code.claude.com/docs/en/claude-code-on-the-web.
Nothing in C1-C6 can proceed without it: Energy-Charts is the key-free critical
path, and `web-api.tp.entsoe.eu` will very likely need the same treatment
before C7.

**Deliberate deviation from PLAN.md C1, for the record:** C1 says "pull
day-ahead prices, all 9 zones, 2019-today". `fetch_years` is set to 2019-2024,
not "today", because (a) 2025 is the sealed holdout and CLAUDE.md's seal
outranks the plan's wording, and (b) 2026 is outside the study window (the main
hourly backtest ends 2025-09-30, the day before the SDAC 15-minute go-live). The
2025 pull happens at C16 after Checkpoint C approval, via the same code path
once the guard opens.

**Also noted for C2:** whether the Energy-Charts `end` parameter is inclusive of
the whole end day is not assumed anywhere. The request is
`start=Y-01-01&end=Y-12-31` and the result is truncated to
`[Y-01-01T00:00Z, Y+1-01-01T00:00Z)`; if `end` is exclusive, coverage will read
~8736/8760 with `last_ts_utc` at `Y-12-30T23:00Z`. C2 must resolve that
explicitly rather than patching it silently.

**Next:** C1b — rerun the fetch and build the manifest once the host is
allowed. Then C2 (data contract tests, hourly aggregation, per-zone plots) which
ends at **Checkpoint A**.

### C1b — 2026-09-28 (scheduled cycle) — STILL BLOCKED, no new work

Checked the one thing this cycle exists to check: **`api.energy-charts.info` is
still denied by the cloud environment's egress policy.** FLAG C1-01 stands
unchanged, so there is no manifest, and per the C1b instruction no C2 work was
started and no second push notification was sent.

What was verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file. The committed C1 data layer is healthy.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the C1
  failure **byte-identically** (`ProxyError ... Tunnel connection failed: 403
  Forbidden`), exits 1, and caches nothing. The flag-don't-swallow path works.
- The agent proxy's own status endpoint again records
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  `api.energy-charts.info:443`. `pypi.org` and `github.com` reach fine from the
  same session, so this remains host-specific policy, not a broken tunnel.
- `python -m data.build_manifest` correctly refuses on an empty cache rather
  than writing an empty manifest.

**Deliberately did NOT run the full 54-pair fetch.** With the gateway refusing
CONNECT on policy, all 54 pairs would burn ~55 minutes in the client's 5/15/45s
backoff and put 162 rejected CONNECTs against the host, for no information
beyond what the single pair and the proxy's own denial record already establish.
One pair was run through the real client instead. When the host is allowed, the
full pull must still be run in full.

**Also confirmed for C7 (probe only, no request sent):**
`web-api.tp.entsoe.eu:443` is denied by the same policy, exactly as C1
predicted. So widening Network access needs to cover **both** hosts, not just
Energy-Charts — otherwise C7 will stall the same way even once
`ENTSOE_API_KEY` is configured.

*Human action needed (unchanged, now covering both hosts):* widen **Network
access** for this cloud environment — the environment menu in the session title
bar → Edit — either to a broader access level or by adding
`api.energy-charts.info` **and** `web-api.tp.entsoe.eu` to the allowed domains.
Access levels are documented at
https://code.claude.com/docs/en/claude-code-on-the-web.

**Noted for whoever runs C1b next, not changed this cycle (out of scope):**
`data/build_manifest.py` prints "no cached price files found" but exits **0**.
`fetch_prices` exits 1 so an `&&` chain still stops, but a bare
`build_manifest` run that builds nothing reporting success is a trap worth
closing — it belongs with the C1 data layer, not C2. *[Corrected in the
2026-09-29 C1b entry below: this claim was wrong — it already exits 3.]*
Relatedly, decide whether
`data/manifest/fetch_failures.json` should be gitignored: it is currently
tracked-eligible, and this cycle's single-pair probe wrote an `n_failures=1`
version that would have been misleading if committed as though it were a
full-run record, so it was deleted rather than committed.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the host is allowed. Then C2, which ends at
**Checkpoint A**.

### C1b — 2026-09-29 (scheduled cycle) — STILL BLOCKED, no new work

Third consecutive blocked cycle. Checked the one thing this cycle exists to
check: **`api.energy-charts.info` is still denied by the cloud environment's
egress policy.** FLAG C1-01 stands unchanged, there is still no manifest, and
per the standing C1b instruction no C2 work was started and no second push
notification was sent (3 blocked cycles, escalation threshold is ~6).

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file. The committed C1 data layer is healthy.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure **byte-identically** for the third cycle running (`ProxyError ...
  Tunnel connection failed: 403 Forbidden`), exits 1, and caches nothing.
- The agent proxy's own status endpoint records, for this cycle's probes:
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  **both** `api.energy-charts.info:443` and `web-api.tp.entsoe.eu:443`.
  `github.com` tunnels fine from the same session, so this remains
  host-specific policy, not a broken tunnel. No mirror, scraper or alternative
  source was tried, and `config/data.yaml` still names Energy-Charts as the
  only price source.
- `python -m data.build_manifest` refuses on an empty cache rather than writing
  an empty manifest.

**Correction to the previous C1b handover note:** it recorded that
`data/build_manifest.py` "prints 'no cached price files found' but exits 0".
That is wrong — it returns **3** on an empty cache (`data/build_manifest.py:46`),
and 2 on a config-load failure. Measured directly this cycle:
`build_manifest EXIT=3`. There is no trap to close and no code change was made.
The earlier note most likely misread the `&&`-chain behaviour it was describing.

**Still open (unchanged, deliberately not decided this cycle):** whether
`data/manifest/fetch_failures.json` should be gitignored. This cycle's
single-pair probe again wrote an `n_failures=1` version that would misrepresent
a full 54-pair run if committed, so it was again deleted rather than committed.
Recommendation for whoever unblocks this: gitignore it — `PROGRESS.md` is the
durable FLAG record per `CLAUDE.md`, so the JSON is a per-invocation artefact,
while `data/manifest/` otherwise holds the committed Checkpoint A manifest.
Left as a one-line change for a cycle that is actually touching the data layer.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as last
cycle: with the gateway refusing CONNECT on policy, all 54 pairs would burn
~55 minutes in the client's 5/15/45s backoff and put 162 rejected CONNECTs
against the host for no information beyond what one pair plus the proxy's own
denial record already establish. When the host is allowed, the full pull must
still be run in full.

*Human action needed (unchanged):* widen **Network access** for this cloud
environment — the cloud environment menu in the session title bar → Edit —
either to a broader access level or by adding `api.energy-charts.info` **and**
`web-api.tp.entsoe.eu` to the allowed domains. Access levels are documented at
https://code.claude.com/docs/en/claude-code-on-the-web. Nothing in C1-C6 can
proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-29 10:01 UTC (scheduled cycle) — STILL BLOCKED, no new work

Fourth consecutive blocked cycle. **`api.energy-charts.info` is still denied by
the cloud environment's egress policy**, so FLAG C1-01 stands unchanged, there
is still no manifest, and per the standing C1b instruction no C2 work was
started and no push notification was sent (4 blocked cycles; escalation
threshold is ~6).

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the fourth cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), exits 1, and caches nothing.
- The agent proxy's status endpoint records, for this cycle's probes,
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  **both** `api.energy-charts.info:443` and `web-api.tp.entsoe.eu:443`
  (timestamps 10:00:56Z and 10:01:04Z). `github.com` tunnels fine from the same
  session, so this remains host-specific policy, not a broken tunnel. No mirror,
  scraper or alternative source was tried.
- `python -m data.build_manifest` refuses on the empty cache (`EXIT=3`) rather
  than writing an empty manifest.
- The single-pair probe's `data/manifest/fetch_failures.json` (`n_failures=1`)
  was again deleted rather than committed, since it would misrepresent a full
  54-pair run. The standing recommendation to gitignore it is unchanged and
  still left for a cycle that is actually touching the data layer.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous two cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

*Human action needed (unchanged):* the environment's network policy is denying
`api.energy-charts.info` and `web-api.tp.entsoe.eu`. Change **Network access**
in the cloud environment's settings (the environment menu in the session title
bar → Edit): either a broader access level, or add both hosts to the allowed
domains. Access levels are described at
https://code.claude.com/docs/en/claude-code-on-the-web. Nothing in C1-C6 can
proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-29 18:02 UTC (scheduled cycle) — STILL BLOCKED, no new work

Fifth consecutive blocked cycle. **`api.energy-charts.info` is still denied by
the cloud environment's egress policy**, so FLAG C1-01 stands unchanged, there
is still no manifest, and per the standing C1b instruction no C2 work was
started and no push notification was sent (5 blocked cycles; escalation
threshold is ~6, so the *next* blocked cycle should send the single escalation
ping).

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the fifth cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), exits 1, and caches nothing.
- The agent proxy's status endpoint records, for this cycle's probes,
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  **both** `api.energy-charts.info:443` (18:01:29Z, and again at 18:01:44Z /
  18:01:49Z / 18:02:04Z through the client's three retries) and
  `web-api.tp.entsoe.eu:443` (18:01:35Z). A `github.com` control probe from the
  same session tunnels fine (HTTP 400 from the origin, i.e. CONNECT succeeded),
  so this remains host-specific policy, not a broken tunnel. No mirror, scraper
  or alternative source was tried.
- `python -m data.build_manifest` refuses on the empty cache (`EXIT=3`) rather
  than writing an empty manifest.
- `ENTSOE_API_KEY` is still **not set** in this environment. Not blocking
  anything before C7, recorded here only so the C7 precondition stays visible.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous three cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

**Closed the standing `fetch_failures.json` recommendation.** Three consecutive
cycles recommended gitignoring `data/manifest/fetch_failures.json` and each left
it for "a cycle actually touching the data layer", while each in the meantime
hand-deleted a misleading `n_failures=1` probe artefact. That is a trap that
only gets more likely the longer the block lasts, so this cycle added the single
`.gitignore` line. Scope note, stated plainly: this is one line of repo hygiene,
not C2 work and not a change to any test, data contract or fetch/manifest code
path — `tests/`, `data/` and `config/` are untouched this cycle.

**Repo-state note (no history was lost, but worth knowing).** This container's
fresh clone arrived on a **detached HEAD** at `d11ec8a` with the local `master`
ref stale at the C0 commit `d257e20`; `origin/master` was already `d11ec8a`.
Checking out `master` therefore silently reverted the working tree to the C0
state, including `PROGRESS.md`. Resolved with `git fetch origin` and a verified
`git merge --ff-only origin/master` (local `master` confirmed a strict ancestor
first), so all four prior commits are intact and this cycle commits on `master`.
**If a future cycle finds itself on a detached HEAD, fetch and verify against
`origin/master` before committing** — committing from the detached state would
have stranded the work, and reverting the tree without noticing would have
looked in the diff like a deliberate rewrite of `PROGRESS.md` history.

*Human action needed (unchanged):* the environment's network policy is denying
`api.energy-charts.info` and `web-api.tp.entsoe.eu`. Change **Network access**
in the cloud environment's settings (the environment menu in the session title
bar → Edit): either a broader access level, or add both hosts to the allowed
domains. Access levels are described at
https://code.claude.com/docs/en/claude-code-on-the-web. Nothing in C1-C6 can
proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-30 02:02 UTC (scheduled cycle) — STILL BLOCKED, escalation ping sent

**Sixth consecutive blocked cycle.** `api.energy-charts.info` is still denied by
the cloud environment's egress policy, so FLAG C1-01 stands unchanged, there is
still no manifest, and no C2 work was started. This is the cycle the previous
entry designated as the escalation point (~2 days of zero progress), so **one
escalation push notification was sent** — the first ping since C1. No further
pings for this same wait unless the human asks or the situation changes.

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the 9 sealed-holdout tests. The 2025 unseal marker is
  confirmed **absent** from this file (`grep -c` = 0), so the holdout guard is
  still armed and the holdout remains SEALED.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the sixth cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), exits 1, and caches nothing (`data/raw/`
  was never created).
- The agent proxy's status endpoint records, for this cycle's probes,
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial or
  upstream failure)" for **both** `api.energy-charts.info:443` and
  `web-api.tp.entsoe.eu:443`. A `github.com` control probe from the same
  session tunnels fine (HTTP 400 from the origin, i.e. CONNECT succeeded), so
  this remains host-specific policy, not a broken tunnel. No mirror, scraper or
  alternative source was tried, and `config/data.yaml` still names
  Energy-Charts as the only price source.
- `python -m data.build_manifest` refuses on the empty cache (`EXIT=3`) rather
  than writing an empty manifest.
- `ENTSOE_API_KEY` is still **not set** in this environment. Not blocking
  anything before C7; recorded so the C7 precondition stays visible.

**The `fetch_failures.json` trap is confirmed closed.** Last cycle added the
`.gitignore` line; this cycle's single-pair probe wrote its `n_failures=1`
artefact as usual and `git check-ignore` confirms it is now ignored
(`.gitignore:15`), so no hand-deletion was needed and `git status` came back
clean. Three cycles of manual cleanup are no longer a per-cycle risk.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous four cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

**Repo-state note — the detached-HEAD trap recurred, exactly as C1b (5th)
warned.** This container's fresh clone again arrived on a **detached HEAD** at
`607e6f6` with local `master` stale at the C0 commit `d257e20` and
`origin/master` also reading `d257e20` before a fetch. The previous cycle's
warning is what caught it. Resolved the same way: `git fetch origin` (which
moved `origin/master` `d257e20..607e6f6`), confirmed local `master` was a strict
ancestor via `git merge-base --is-ancestor`, confirmed `HEAD == origin/master`,
then `git checkout master` + `git merge --ff-only origin/master`. All five prior
commits intact; this cycle commits on `master`. **This is now a reproducible
property of this environment, not a one-off — every future cycle should fetch
and verify against `origin/master` before committing.** Committing from the
detached state would strand the work, and checking out stale `master` without
fetching first would revert the tree to C0 and look in the diff like a
deliberate rewrite of `PROGRESS.md` history.

*Human action needed (unchanged, and now the blocker for ~2 days):* this cloud
environment's network policy is denying `api.energy-charts.info` and
`web-api.tp.entsoe.eu`. Change **Network access** in the cloud environment's
settings (the environment menu in the session title bar → Edit): either a
broader access level, or add both hosts to the allowed domains. Access levels
are described at https://code.claude.com/docs/en/claude-code-on-the-web.
Nothing in C1-C6 can proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-30 10:02 UTC (scheduled cycle) — STILL BLOCKED, no new work

**Seventh consecutive blocked cycle** (~2.5 days). `api.energy-charts.info` is
still denied by the cloud environment's egress policy, FLAG C1-01 stands
unchanged, there is still no manifest, and per the standing C1b instruction no
C2 work was started and **no push notification was sent** — both pings for this
wait (C1 and the 2026-09-30 02:02 UTC escalation) are spent.

Short note, since the previous six entries already document this block in full.
Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**. The exact unseal marker string is confirmed **absent** from this file
  (`grep -cF` = 0), so the holdout guard is armed and 2025 remains SEALED.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the seventh cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), **exits 1**, and caches nothing
  (`data/raw/` was never created).
- `python -m data.build_manifest` refuses on the empty cache (**EXIT=3**).
- Proxy status endpoint: `connect_rejected` / "gateway answered 403 to CONNECT
  (policy denial or upstream failure)" for **both**
  `api.energy-charts.info:443` and `web-api.tp.entsoe.eu:443` (both
  10:01:34Z). A `github.com` control probe from the same session tunnels fine
  (HTTP 400 from the origin, i.e. CONNECT succeeded), so this remains
  host-specific policy, not a broken tunnel. No mirror, scraper or alternative
  source was tried; `config/data.yaml` still names Energy-Charts as the only
  price source.
- `ENTSOE_API_KEY` still **not set**. Not blocking anything before C7; recorded
  so the precondition stays visible.
- `git status` clean — the `.gitignore` line added at the 5th cycle continues to
  absorb the probe's `fetch_failures.json` artefact (`.gitignore:15`), so no
  hand-deletion was needed. No files under `tests/`, `data/`, `config/` or any
  data contract were touched this cycle.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous five cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

**Repo-state note — the detached-HEAD trap recurred for the third cycle
running.** Fresh clone arrived on a **detached HEAD** at `fe5aca1` with local
`master` stale at the C0 commit `d257e20` and `origin/master` also reading
`d257e20` before a fetch. Resolved the documented way: `git fetch origin`
(moved `origin/master` `d257e20..fe5aca1`), confirmed local `master` was a
strict ancestor via `git merge-base --is-ancestor`, then `git checkout master` +
`git merge --ff-only origin/master`. All six prior commits intact; this cycle
commits on `master`. This is a stable property of this environment — **every
future cycle must fetch and verify against `origin/master` before committing.**

*Human action needed (unchanged, now the blocker for ~2.5 days):* this cloud
environment's network policy is denying `api.energy-charts.info` and
`web-api.tp.entsoe.eu`. Change **Network access** in the cloud environment's
settings (the environment menu in the session title bar → Edit): either a
broader access level, or add both hosts to the allowed domains. Access levels
are described at https://code.claude.com/docs/en/claude-code-on-the-web.
Nothing in C1-C6 can proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-30 13:17-13:30 UTC (scheduled cycle) — UNBLOCKED, C1 COMPLETE

**The egress block is over after 7 blocked cycles (~2.5 days).**
`api.energy-charts.info` now answers (HTTP 200) and `web-api.tp.entsoe.eu`
tunnels (HTTP 401, i.e. CONNECT succeeded — 401 is just the missing-key
response to a bare probe). **FLAG C1-01 is RESOLVED.** Separately,
`ENTSOE_API_KEY` is now **set** in this environment, so the C7 precondition is
also satisfied. Thanks — both of those were human-side changes to the cloud
environment settings, and both landed.

C1's remaining work — the pull and the manifest — ran to completion this cycle.
**C1 is now fully done.**

**What ran:**
- `.venv` rebuilt from the committed `requirements.txt` (fresh container, no
  venv). **All 44 C1 unit tests pass**, before and after the pull.
- Holdout guard verified armed *before* touching anything: the unseal marker
  (the exact string defined in `config/data.yaml` -> `holdout_unseal_marker`;
  deliberately **not** reproduced verbatim anywhere in this file, see the
  warning at the end of this entry) is **absent** here (`grep -cF` = 0),
  `holdout_is_unsealed()` returns `False`, `sealed_years()` = `{2025}`, and
  `fetch_years` = 2019-2024 with no overlap. **2025 remains SEALED and was
  never requested.**
- `python -m data.fetch_prices` — the full **54-pair** pull (9 zones x 6 years),
  as the previous six entries said it must be run when the host was allowed.
  Result: `downloaded=54 already_cached=0 flagged=0`, **EXIT=0**.
  `fetch_failures.json` records `n_failures: 0`. No 404s, no empty payloads, no
  schema rejections, no retries needed.
- `python -m data.build_manifest` — **EXIT=0**, 54 rows written to
  `data/manifest/prices_manifest.csv` (18 KB) and `.json` (52 KB), tagged with
  git SHA `0388dac`, config hash `47583ac06601f0a2`, CC BY 4.0 licence and the
  Energy-Charts attribution.
- `data/raw/` is 9.0 MB and **gitignored** (`.gitignore:4`), as is
  `fetch_failures.json` (`.gitignore:15`). Only the manifest artefacts are
  committed — no bulk raw data, no keys.

**Data quality — the pull is clean.** Across all 54 (zone, year) pairs:
`n_gap_intervals` = 0, `n_nan` = 0, `resolution_seconds` = 3600 uniformly,
`n_distinct_deltas` = 1. An independent check over the raw cache confirms each
zone is **one contiguous hourly series, `2018-12-31T23:00Z .. 2024-12-31T22:00Z`,
uniform 3600s deltas, no interior gaps.**

Mean day-ahead price, EUR/MWh (the Checkpoint A table in miniature):

| zone     | 2019 | 2020 | 2021  | 2022  | 2023  | 2024  |
|----------|------|------|-------|-------|-------|-------|
| BE       | 39.3 | 31.9 | 104.1 | 244.6 |  97.3 |  70.3 |
| DE-LU    | 37.7 | 30.5 |  96.9 | 235.5 |  95.2 |  78.5 |
| DK1      | 38.5 | 25.0 |  88.1 | 219.1 |  86.8 |  70.7 |
| ES       | 47.7 | 34.0 | 111.9 | 167.5 |  87.1 |  63.0 |
| FR       | 39.4 | 32.2 | 109.2 | 275.9 |  96.9 |  58.0 |
| IT-North | 51.2 | 37.8 | 125.2 | 307.8 | 127.8 | 107.4 |
| NL       | 41.2 | 32.2 | 103.0 | 241.9 |  95.8 |  77.3 |
| NO2      | 39.3 |  9.3 |  75.1 | 211.3 |  79.4 |  50.1 |
| PL       | 53.5 | 46.7 |  87.0 | 166.7 | 111.7 |  96.3 |

Negative-price hours per zone-year:

| zone     | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|----------|------|------|------|------|------|------|
| BE       |  71 | 136 | 159 | 112 | 221 | 404 |
| DE-LU    | 211 | 298 | 139 |  69 | 300 | 457 |
| DK1      | 132 | 192 |  87 |  38 | 281 | 375 |
| ES       |   0 |   0 |   0 |   0 |   0 | 247 |
| FR       |  27 | 102 |  64 |   4 | 147 | 352 |
| IT-North |   0 |   0 |   0 |   0 |   0 |   0 |
| NL       |   3 |  97 |  70 |  85 | 315 | 458 |
| NO2      |   0 |   5 |   5 |   0 | 174 | 206 |
| PL       |   0 |   0 |   0 |   0 |  43 | 197 |

These are **not** yet verified against an independent source — that is
Checkpoint A's job — but they line up with known market history: the 2022
crisis peak in every zone; NO2's 2020 Nordic hydro glut at 9.3 EUR/MWh;
IT-North with a 0.00 EUR/MWh floor and zero negative hours throughout (MGP had
no negative prices in this window); ES with zero negative hours until 2024,
then 247 as solar penetration bit; and the sharp 2023->2024 rise in negative
hours almost everywhere. FR's 2987.78 EUR/MWh maximum sits in the 2022
nuclear-outage period. Extremes: DE-LU / NL / BE / DK1 all touch the
-500 EUR/MWh region; DE-LU and DK1 peak at 936.28.

**NOTE C1-02 — request-window convention, resolved. Not a defect; C2 must
know it.** Every one of the 54 rows reports `coverage_ratio` = 0.999886
(8759/8760) with `n_out_of_window_dropped` = 1 and `last_ts_utc` =
`Y-12-31T22:00Z`. This is **not missing data**. `docs/data_layer.md` had left
this question open as "to verify in C2"; the pull answers it:

- Energy-Charts interprets `start`/`end` as whole days in the **zone's local
  time**, returning exactly one full *local* year (8760 / 8784 points). All
  nine zones are CET/CEST, so each raw file spans `Y-1-12-31T23:00Z ..
  Y-12-31T22:00Z` in UTC.
- Truncating to the UTC calendar year therefore drops exactly the one leading
  point belonging to `Y-1` (hence `n_out_of_window_dropped` = 1), and the final
  UTC hour of year `Y` is absent from row `Y` because it was never in the `Y`
  window — **it is present in file `Y+1`**. The per-year rows understate
  coverage by exactly one hour by construction.
- **C2's loader must concatenate the per-year files and de-duplicate on
  timestamp — it must not reindex or fill per-year to 8760.** The first hour of
  UTC year `Y` is in file `Y`; the last hour of UTC year `Y` is in file `Y+1`.
- **Holdout interaction, flagged deliberately:** the last hour of UTC 2024
  (`2024-12-31T23:00Z`) lives *only* in the 2025 file, and 2025 is SEALED. The
  usable UTC span therefore ends at **`2024-12-31T22:00Z`**. A future cycle
  must **never** fetch 2025 to close that one-hour tail. It costs 1 hour out of
  ~52,600, the hourly backtest window ends 2025-09-30 regardless, and
  `data/holdout.py` already refuses the fetch. This note exists so the tail is
  not mistaken for a bug worth "fixing".

`docs/data_layer.md` has been updated with the resolved convention and the C2
requirement. **No file under `tests/`, `config/`, or `data/*.py` was touched
this cycle** — the only code-adjacent edit is that documentation section
(`git diff --name-only` confirms `docs/data_layer.md` is the sole modification).

**Scope discipline:** C1b was scoped as the pull plus the manifest, and stops
there. C2 was deliberately **not** started even though budget remained, per the
standing rule against running ahead into a later cycle's work — and C2 ends at
Checkpoint A, which needs its own full cycle. No push notification was sent:
this is a routine cycle, not a checkpoint, and the unblocking is good news
rather than something needing a human decision. The human will be pinged at
the end of C2 for Checkpoint A.

**WARNING FOR EVERY FUTURE CYCLE — do not quote the unseal marker verbatim in
`PROGRESS.md`.** This cycle tripped that wire and caught it pre-commit. While
writing the log entry above, this session reproduced the unseal marker string
literally (inside backticks, in a sentence *asserting the marker was absent*).
`data/holdout.py` tests membership with a plain `marker in
PROGRESS.md_text` — backticks, surrounding prose and negating context are
invisible to it. The result: `grep -cF` went 0 -> 1 and
`holdout_is_unsealed()` flipped to **`True`**, i.e. the 2025 seal was
**mechanically open**, purely from a cycle describing the guard.

Caught by re-checking the guard immediately after the write, **before any
commit, push, fetch or model touched a sealed year**. The verbatim string was
removed, and the state is confirmed restored: `grep -cF` = **0**,
`holdout_is_unsealed()` = **`False`**, and the 44-test suite (which includes
the tripwire test asserting the marker is absent) passes. No sealed data was
fetched, loaded, or computed against at any point — the whole episode lived
inside an uncommitted working-tree edit to a prose file.

Two things follow, and they are worth more than the incident cost:
1. **Refer to the marker indirectly** — as "the string in `config/data.yaml` ->
   `holdout_unseal_marker`" — never by reproducing it. The same applies to
   commit messages and any other file the guard reads.
2. The guard's substring test is doing its job but is **context-blind**, which
   is a real design observation for the human: a hardening option (e.g.
   requiring the marker alone on its own line, plus a human signature/date) is
   worth considering at Checkpoint A. **Proposed, not done** — `data/holdout.py`
   is the leakage-contract file, and CLAUDE.md forbids an agent cycle changing
   it without human review. Flagged here for that review; no code was changed.

**Next:** **C2** — data contract tests (per-(zone, day) row counts against the
DST whitelist, resolution-change detection at the 2025-10-01 15-min cutover,
gap report), documented hourly aggregation, and a price plot per zone. Then
**stop at CHECKPOINT A** and push-notify for human review of the manifest and
plots before any modelling begins.

### C2 — 2026-09-30 17:55-18:30 UTC (scheduled cycle) — COMPLETE, **CHECKPOINT A REACHED**

Scope per PLAN.md C2: data contract tests (per-(zone, day) row counts against a
DST whitelist, resolution-change detection at the 2025-10-01 cutover, gap
report), documented hourly aggregation, and a price plot per zone. Then stop at
Checkpoint A. All of that is done; nothing from C3 was started.

**Container state on arrival.** Detached HEAD at `6227d69` (4th recurrence),
reattached to `master` before touching anything. `.venv` absent, rebuilt from the
committed `requirements.txt`. **`data/raw/` was empty** — the raw cache is
gitignored and the container is ephemeral, so C1's 9.0 MB of cached price files
did not survive. See NOTE C2-02.

**The 54-pair pull was re-run, and it reproduced C1 exactly.** Re-fetching was
not a violation of "never re-download cached data": the cache was empty, so there
was nothing cached to re-download, and C2 cannot check contracts on data that
isn't there. `downloaded=54 already_cached=0 flagged=0`, EXIT=0, no 404s, no
retries, no schema rejections. The manifest was then rebuilt and diffed against
C1's committed copy: **all 25 data columns identical across all 54 rows** —
`n_points`, `raw_bytes`, `first/last_ts_utc`, every price statistic, every
negative-hour count. The committed `prices_manifest.{csv,json}` were therefore
restored to C1's versions rather than re-committed with fresh provenance stamps,
so the Checkpoint A artefact the human reviews is stable and diff-free.

**Built this cycle:**
- `data/prices.py` — the stitching loader NOTE C1-02 specified. It does **not**
  reuse `read_cached_year`: that trims each file to its own UTC year, which would
  leave a one-hour hole at *every* year boundary, since `Y-12-31T23:00Z` lives in
  file `Y+1`. It parses each file untruncated, concatenates, sorts, and
  de-duplicates on timestamp — collapsing a duplicate only when the two files
  agree on the price, and raising if they disagree. Never reindexes, never fills.
  The holdout guard is applied per year before any file is opened.
- `data/contracts.py` — the seven contracts (table below), the derived DST
  whitelist, resolution segmentation/change detection, the gap report, and
  `payload_fingerprint` (see NOTE C2-01).
- `data/aggregate.py` — sub-hourly -> hourly by one documented method.
- `data/build_contracts.py`, `data/plot_prices.py` — the two CLIs.
- `tests/test_c2_contracts.py` — **42 new tests**, all offline and synthetic.
- `docs/data_contracts.md` — the layer documented; `docs/data_layer.md` got a
  one-line pointer marking its "requirement for C2's loader" satisfied.
- `requirements.txt` — matplotlib added.

**Test suite: 86 passing (44 from C1, 42 new).**

**Result: all nine zones pass all seven contracts.** Each zone is one contiguous
hourly series, `2018-12-31T23:00Z .. 2024-12-31T22:00Z`, 52,608 points:

| contract | result, all 9 zones |
|---|---|
| index tz-aware UTC, monotonic, no duplicates | pass; 0 duplicates |
| every fully-covered UTC day = 24 rows | pass; **2,191 days checked**, 0 violations |
| every fully-covered local day = DST-derived count | pass; **2,192 days checked**, 0 violations |
| every non-24h local day is a tz-database transition date | pass; **12 DST days** seen per zone |
| no gaps | pass; `n_missing_intervals` = 0, `max_gap_hours` = 0.0 |
| no NaN prices | pass; 0 |
| only permitted resolution change is 3600s->900s at the cutover | pass; 0 changes (series ends 2024) |

**The DST whitelist is derived, not hardcoded.** `dst_transition_days(tz, years)`
walks the tz database, so it cannot drift from reality, and it fails in *both*
directions: a 23-hour local day on the last Sunday in March passes, a 23-hour
local day on an ordinary Tuesday is a violation (there is a test for exactly
that). This is the assertion that stops an hour of silently dropped real data
from being excused as "probably DST". All nine zones are CET/CEST and share one
transition calendar — asserted by a test, so adding a non-CET zone later fails
loudly instead of silently reusing the wrong calendar. 126 rows committed to
`data/manifest/dst_whitelist.csv`.

**UTC days and local days are deliberately separate contracts.** A UTC day always
holds 24 hourly intervals, so a deviation is unambiguously a defect; a local day
holds 23/24/25 and needs the whitelist. Day completeness is decided from expected
interval *timestamps*, not by assuming the first and last day are partial — for
these CET zones the local-day view is complete at both ends and those days are
still checked (hence 2,192 local vs 2,191 UTC days).

**Gaps and resolution changes are not allowed to be confused.** A missing hour and
a market-time-unit change both appear as an odd delta. `detect_resolution_changes`
ignores runs shorter than two intervals and merges same-resolution neighbours, so
hourly / missing-hour / hourly reports a **gap**, not a 3600s->3600s "change" —
that was a genuine bug in this cycle's first draft, caught by its own test.
`gap_report` measures each step against the resolution in force either side of it,
so a legitimate cutover contributes zero missing intervals.

**The 2025-10-01 cutover instant is local midnight, not UTC midnight**
(`2025-09-30T22:00Z` for a CEST zone) — it is a market *day*. Only one change,
3600s->900s at that instant, is permitted; anything else is a violation.
**No 2025 data was touched to test this.** The detector is exercised on synthetic
hand-built indices; the real series ends 2024-12-31 and reports 0 changes.

**Hourly aggregation — the method, on the record.** The hourly price is the
**unweighted arithmetic mean** of the sub-hourly prices whose interval starts in
that UTC hour. Sub-hourly intervals are equal length, so that is the correct
duration-weighted average. **It is not a VWAP and cannot be**: a volume-weighted
price needs cleared volume per interval, and the Energy-Charts `/price` payload
carries prices only. `to_hourly` accepts an explicit `volume` argument so the
machinery exists if a volume source is ever added, but nothing in this repo
supplies one — the write-up must say "duration-weighted mean of 15-minute prices",
never "VWAP". Partial hours raise by default rather than being averaged. Grouping
is on the UTC hour; local time is never a resampling key.
*For the write-up's Limits section:* aggregating 15-minute prices to hourly
destroys within-hour spread, so a battery's realisable value is **higher** at
native 15-minute granularity than an aggregated hourly series implies. Aggregated
post-cutover results understate flexibility value and must never be pooled with
pre-cutover hourly results as though they were the same measurement.

**Independent cross-check of C1's manifest, and a clean reconciliation.** The
negative-hour counts recomputed from the stitched series match C1's per-year
manifest everywhere except three cells: DE-LU 2022 (69 -> 70), NL 2022 (85 -> 86),
BE 2022 (112 -> 113). All three are the *same single hour*, `2022-12-31T23:00Z`,
which was negative in exactly those three zones (-5.17, -3.61, -4.39 EUR/MWh).
That hour is absent from the manifest's 2022 row because it lives in file 2023 —
precisely and only the discrepancy NOTE C1-02 predicts. Every other (zone, year)
pair agrees exactly. This is a good sign for both artefacts: the manifest and the
stitched series differ in exactly the documented way and nowhere else.

**Figures (11, in `docs/figures/`, 1.8 MB total).** One per zone — daily mean with
the intraday min-max band behind it, plus a one-week hourly inset so the raw shape
is visible; a nine-panel small-multiples overview on a shared y-axis; and
negative-price hours per zone-year. The overview's y-axis is **clipped to
[-124, 850] EUR/MWh with the clipping stated on the figure itself** (36 daily
extremes fall outside): FR's 2,987.78 EUR/MWh 2022 print otherwise squashes all
nine panels into the bottom eighth of the frame. True extremes are in the
manifest. Daily aggregation is on the UTC date and drops the partial boundary days
so the left edge is not a one-hour "day".

**NOTE C2-01 — the manifest's `raw_sha256` cannot be reproduced, by construction.
Not a defect in the data; a limit on what that column can be used for.** The
re-pull produced 54 files with byte-identical *sizes* and *contents* but 54
different `raw_sha256` values. Cause: the column hashes the cached file, and this
project writes a `_fetch_meta.fetched_at_utc` stamp into that file before hashing
it. So `raw_sha256` identifies a *file*, not a *payload*, and can never match
across re-fetches — it cannot serve as the data-integrity check it looks like.
Rather than change `data/manifest.py` mid-checkpoint (it produces the artefact the
human is about to review), C2 added `payload_sha256` to the contract report:
sha256 over the `(UTC epoch, price)` pairs at fixed 6-decimal precision,
reproducible across pulls. **A human decision is requested** on whether
`data/manifest.py` should switch `raw_sha256` to hash the payload rather than the
file. Proposed, not done.

**NOTE C2-02 — the raw cache does not survive a container, so every cycle re-pulls
54 files (~9 MB).** `data/raw/` is gitignored (correctly — CLAUDE.md forbids
committing bulk raw data) and containers are ephemeral, so C1's cache was gone.
This is not currently harmful: the pull takes ~4 minutes, is polite (2s between
requests), and reproduced byte-identically. But it means "never re-download cached
data" is effectively unenforceable across cycles, and ~15 more cycles implies ~15
more full pulls against a free, unauthenticated Fraunhofer ISE endpoint. **A human
decision is requested** between: (a) leave it — it is polite and provably
reproducible; (b) commit a compact derived artefact (all nine zones, hourly, 2019
-2024 is ~1.2 MB as compressed parquet) so cycles load from the repo and only fetch
what is missing; (c) configure a persistent cache volume if the platform offers
one. Option (b) touches the "no bulk raw data" rule and is the kind of call that
should not be made by an unattended cycle. Proposed, not done.

**Files under `tests/` — declared, per CLAUDE.md.** One file was **added**:
`tests/test_c2_contracts.py`. That is C2's own mandate in PLAN.md ("data contract
tests"), and adding a new test file is not what the rule guards against. **No
existing test was edited, and no existing assertion was weakened or deleted** —
`tests/test_c1_data_layer.py` and `tests/conftest.py` are untouched
(`git diff --stat` confirms). Where this cycle's tests failed, the *code* was
fixed: the resolution-change merge bug described above was a real defect in new
code, found by a new test, and fixed in `data/contracts.py`.

**One C1 file was modified, and it is a pure refactor:** `data/energy_charts.py`
gained `parse_payload(payload, context)` — the untruncated parse — and
`payload_to_frame` now calls it before applying its per-UTC-year window. Behaviour
is unchanged (all 44 C1 tests pass unmodified, before and after). This was needed
because the stitching loader must see the whole file, not one UTC year.
`data/holdout.py`, `data/config.py`, `data/manifest.py` and everything under
`config/` were **not** touched.

**Sealed holdout.** Verified armed before the work and again before committing:
marker count in this file 0, `holdout_is_unsealed()` = `False`, `sealed_years()` =
`{2025}`, `fetch_years` = 2019-2024. The C1b warning was heeded — the marker
string is not reproduced anywhere in this entry, only referred to by its config
key. No 2025 data was fetched, loaded, or computed against. The synthetic indices
dated 2025 in the cutover tests are hand-built timestamps with made-up prices, not
sealed data; `data/prices.py` has a test asserting it refuses a sealed year even
when a 2025 file is sitting in the cache.

---

## CHECKPOINT A — ready for review

**What to look at, roughly in this order:**
1. `docs/figures/prices_all_zones.png` — the nine series at a glance. Sanity-check
   against market history: the 2022 crisis in every zone, NO2's 2020 hydro glut
   near zero, IT-North's 0.00 EUR/MWh floor, ES's flatter solar-shaped profile.
2. `docs/figures/negative_hours.png` — negative hours per zone-year. The
   2023->2024 jump almost everywhere, ES's first negative hours in 2024, IT-North
   at zero throughout, and the 2022 dip (high gas priced out negatives).
3. `data/manifest/prices_manifest.csv` — 54 rows, unchanged from C1. The mean and
   negative-hour tables are in the C1b entry above.
4. `data/manifest/contract_report.csv` — nine rows, `ok = True` on all of them.
5. `docs/figures/prices_<ZONE>.png` — any zone you want to look at closely.

**The one thing worth verifying independently:** these prices have not been
checked against a second source. Picking two or three cells from the manifest
(say DE-LU 2022 mean 235.5 EUR/MWh, NO2 2020 mean 9.3 EUR/MWh) and comparing them
against ENTSO-E, a market report, or memory is the highest-value five minutes of
this checkpoint — everything downstream inherits these numbers.

**Checkpoint A: what needs a human (three decisions, none blocking C3):**
1. **NOTE C2-01** — should `data/manifest.py` hash the payload rather than the
   file, so `raw_sha256` becomes reproducible? (C2 added a reproducible
   `payload_sha256` alongside it either way.)
2. **NOTE C2-02** — cache persistence: leave the per-cycle re-pull as is, commit a
   compact derived hourly artefact, or use a persistent volume?
3. **Carried over from C1b, still proposed and not done** — hardening
   `data/holdout.py`. Its unseal test is a plain substring check against this
   file, which is context-blind: the C1b cycle mechanically opened the seal just
   by *describing* the marker in prose, and caught it pre-commit. Options: require
   the marker alone on its own line, and/or require a human signature + date
   alongside it. `data/holdout.py` is the leakage-contract file, so CLAUDE.md
   forbids an agent cycle changing it without review. This is that review request.

**To approve and continue:** replace the "Next cycle to run" line at the top of
this file with C3, and note the approval here. C3 is the walk-forward harness plus
the naive model on DE-LU, with the three leakage tests written before the real
model.

**Next (after approval):** C3 — walk-forward harness + naive (same hour last week)
model, DE-LU only, and the leakage assertions: (i) shifting the feature matrix
forward one day must degrade metrics, (ii) a deliberately future-timestamped
feature must be caught by a gate-closure guard, (iii) target permutation must
destroy skill.

---

### Checkpoint A wait — 2026-10-01 (scheduled cycle, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT A**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `origin/master` == local HEAD at `fc422de` (the C2 checkpoint
  commit, no human commits since); all Checkpoint A artefacts present and unmodified
  (`data/manifest/prices_manifest.{csv,json}`, `contract_report.{csv,json}`,
  `dst_whitelist.csv`, 11 figures in `docs/figures/`); holdout guard re-verified armed
  (`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`); no 2025 data touched;
  no push notification sent (avoiding repeat pings for the same wait). HEAD arrived
  attached to `master` this container — the detached-HEAD trap did **not** recur
  (now 4 recurrences out of 10 containers). Still waiting on the three Checkpoint A
  decisions listed in the C2 entry above; C3 remains blocked until a human replaces the
  status line with C3 and records approval here.

---

### Checkpoint A — approved and closed — 2026-10-01 (human session, local, not a
scheduled cycle)

Reviewed `prices_all_zones.png` and `negative_hours.png` against known market
history (2022 crisis in every zone, ES's gas price cap keeping it at zero
negative hours until 2024, IT-North's price floor at zero throughout, the
2023→2024 negative-hour jump from renewables build-out) — consistent with real
market behaviour, not noise. All three Checkpoint A decisions resolved:

1. **NOTE C2-01, fixed in code.** `data/manifest.py` no longer hashes the
   cached file. The manifest's checksum column is renamed `raw_sha256` →
   `payload_sha256` and now calls `contracts.payload_fingerprint()` — the same
   function the C2 contract report already used — so it hashes only the `(UTC
   epoch, price)` pairs and is reproducible across re-fetches. Confirmed: a
   completely independent re-pull of all 54 (zone, year) pairs, two days after
   C1's pull, reproduced `price_mean` to 3 decimal places on every spot-checked
   cell (DE-LU 2022: 235.467; NO2 2020: 9.289) — this is a reproducibility
   check against the same source on a fresh pull, not an independent second
   source, and that distinction is worth keeping in mind for the write-up.
   `data/contracts.py`'s docstring, `tests/test_c1_data_layer.py` (assertion
   updated to the new column name, computed via `contracts.payload_fingerprint`
   on the loaded frame) and `docs/data_contracts.md` / `docs/data_layer.md`
   updated to match. All existing tests pass unweakened; nothing was deleted.
2. **NOTE C2-02, decided: leave as is.** The raw cache will keep not surviving
   between containers/cycles. Accepted trade-off — the pull is polite (2s
   between requests) and has now proven byte-reproducible across two
   independent pulls on different days; a persistent cache or a committed
   derived artefact isn't worth the engineering effort or the added "bulk raw
   data" rule-bending for a one-week project. No code change.
3. **Holdout guard hardened, as requested.** `data/holdout.py`'s
   `holdout_is_unsealed()` was a plain substring search; it now requires the
   marker to be the **entire content of some line** (stripped of surrounding
   whitespace) in `PROGRESS.md`, closing the near-miss C1b's own log entry
   almost triggered by describing the marker in prose. Deliberately did *not*
   add a human-signature/date requirement — judged more ceremony than this
   project needs; the marker is already something only a human writes, and
   CLAUDE.md already forbids an agent cycle from touching this file. Added
   `test_guard_stays_shut_when_the_marker_is_only_quoted_in_prose`, which
   checks both the negative case (marker embedded in a sentence must not
   unseal) and that a padded-whitespace marker-alone-on-its-own-line still
   does. The existing `test_guard_opens_only_when_the_exact_marker_is_present`
   continues to pass unmodified in its assertions (only its fixture gained an
   explicit `encoding="utf-8"` — see below) because its "approved" fixture
   already put the marker alone on its own line.

**One unrelated real bug found and fixed while verifying all this: a
Windows-locale encoding failure, not a logic error.**
`test_guard_opens_only_when_the_exact_marker_is_present`'s fixture wrote an
em-dash via `Path.write_text()` with no explicit encoding, which uses the
platform locale (cp1252 on this Windows machine) rather than UTF-8; the guard
reads `PROGRESS.md` as explicit UTF-8, so the two disagreed and the test raised
`UnicodeDecodeError` the first time it ran anywhere other than a UTF-8-locale
Linux container — which is all 10 scheduled cycles so far, explaining why this
was never caught before now. Fixed by adding `encoding="utf-8"` to every
`write_text()` call in this test file. Worth remembering if more local/Windows
verification happens later: this whole repo has otherwise been built and run
exclusively on Linux cloud containers.

**Manifest and figures regenerated from a fresh local pull**, not just
hand-edited: ran `python -m data.fetch_prices` (full 54 pairs; 4 hit `HTTP 429`
on the first pass — rate-limited, almost certainly from C1/C1b's pull of the
same 54 pairs against the same free, unauthenticated endpoint earlier the same
day — retried cleanly to 0 flagged), `python -m data.build_manifest`, `python
-m data.build_contracts` (all 9 zones `ok = True`), and `python -m
data.plot_prices`. All 87 tests pass (`pytest tests/ -q`). This was run
locally, with real internet access confirmed separately, rather than waiting
for the next scheduled cloud cycle, specifically so the committed manifest and
figures match the fixed `payload_sha256` code rather than sitting stale.

**Sealed holdout:** re-verified before writing this entry —
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`. No 2025 data
fetched, loaded, or computed against at any point in this session.

**Approved by:** J., 2026-10-01, via the assistant session that ran this
review and these fixes.

---

### C3 — 2026-10-01 (scheduled cycle) — walk-forward harness + naive model, DE-LU

**Done, as scoped in PLAN.md C3.** The harness, the naive floor, and — written
before any real model exists — the three leakage assertions, plus the gate-closure
guard they test. 50 new offline tests (137 total, all passing). Full design notes
in `docs/forecast_harness.md`.

**New modules.** `forecast/timing.py` (market days, gate closure, publication
instants), `forecast/features.py` (the feature matrix, built from
`config/features.yaml`, with an information time attached to every cell),
`forecast/leakage.py` (the gate-closure guard + availability mask),
`forecast/models.py` (the `Model` protocol, `NaiveLastWeek`, `TrainMeanBaseline`),
`backtest/walk_forward.py` (folds + three per-fold guards),
`backtest/metrics.py` (MAE/RMSE/rMAE/skill only — C12 owns the full layer),
`backtest/diagnostics.py` (PLAN's three probes as library functions, so later
cycles re-run them instead of re-deriving them), `backtest/run_c3_naive.py` (CLI).

**The rule the whole layer rests on, stated once.** Bids for delivery day `D` close
at 12:00 Europe/Brussels on `D-1`; day `D`'s prices are published ~13:00 on `D-1`,
*after* that deadline. So at gate closure for `D` a bidder knows every hourly price
of market days `<= D-1` and none of day `D`. That is about **market days**, not UTC
days and not raw hour offsets — and C3 found two places where the difference bites.

**FINDING C3-A — a plain 24-hour lag leaks once per zone per year.** On the
25-hour local day each autumn, the 25th hour's `t - 24h` lands on *that same market
day's first hour* — a price published after the bidding deadline for the very day
being predicted. Six cells over DE-LU 2019–2024, one per year, worth exactly one
hour of lateness. Found by the guard, not by reasoning. Masked to NaN, counted in
the build report (`price_lag_24h: 6`), rows never dropped. The 48h/72h/168h lags
never reach that far forward, so the naive baseline is unaffected.

**NOTE C3-01 — the daily-aggregate features cannot be built the way
`config/features.yaml` literally describes, because that description leaks. A
human decision is requested; proposed, not done.**
`price_daily_{mean,min,max}_lag_24h` are declared as `mean_over_utc_day` with
`lag_hours: 24`. Read literally — the aggregate over the UTC day containing
`t - 24h` — that window is UTC day `D-1` for 23 of the 24 hours of target day `D`.
For a CET zone UTC day `D-1` ends at `D-1 23:00Z`, which is **local midnight on
`D`**: market day `D`'s own first cleared price. So the literal feature embeds one
hour of the day it is predicting, on nearly every row, and **no** literal reading
of the spec is leak-free. `forecast/features.py` therefore builds those three
columns over *the latest UTC calendar day every hour of which was public at the
row's gate closure* — derived mechanically from the publication calendar, which for
the CET/CEST zones in scope resolves to UTC day `D-2`. The committed column names
are kept so config stays the single source of truth, but `lag_24h` in those names
is now a misnomer. **Decision requested:** rename them in `features.yaml` to
`..._prev_available_utc_day` and restate the aggregate, or leave the names and rely
on the documentation? Deliberately not done by this cycle — editing a feature spec
so that a leak disappears is precisely the move CLAUDE.md warns about.

**PLAN's three leakage assertions, on the real DE-LU pipeline (2024 validation,
daily refit, expanding window from 2019).** Also asserted on synthetic series in
`tests/test_c3_leakage_harness.py`.
- **(i) shifting the feature matrix forward one day degrades metrics.** Aligned MAE
  **32.80** EUR/MWh; one day staler **36.66**; one day fresher **36.04**. Both
  directions hurt, because `price_lag_168h` shifted either way stops being the same
  weekday — so the *sign* of the shift effect is not itself a leakage detector, and
  the test asserts correct alignment beats both. What it establishes is that the
  harness is sensitive to time at all, which is the precondition for (ii) meaning
  anything.
- **(ii) a deliberately inserted future-timestamped feature is caught.** A
  `price_lead_24h` column declared honestly → rejected `after_gate_closure` (52,584
  rows, worst 2 days late); smuggled in undeclared → rejected `undeclared`. The
  walk-forward refuses to run on the injected matrix. A separate test measures what
  the leak would have been *worth* on a persistence-dominated series: it more than
  halves MAE.
- **(iii) target permutation destroys skill.** Skill measured against a train-mean
  baseline run through the same harness. Real **+0.134**; hour-wise permuted
  **−0.130**; whole-day permuted **−0.105**. Both negative — a model fitted on
  shuffled targets is worse than a constant.

**Results, DE-LU 2024 (validation).** naive same-hour-last-week: **MAE 32.80,
RMSE 55.22, bias −1.52** over 8,784 hours / 366 folds; every evaluation hour
predicted exactly once, zero skipped days, zero missing predictions. Train-mean
baseline MAE 37.88. The naive model beats that reference by only 13%, which says
more about the reference than the model: an expanding window from 2019 puts the
2022 crisis in the training mean (2019–2023 mean 99.08 EUR/MWh) against a 2024
realised mean of 78.52. It is a deliberately weak denominator, used only for the
permutation test — **rMAE against naive** is the comparison that matters, and that
is C12's job. Committed: `backtest/results/c3_naive_DE-LU_2024_{predictions.csv.gz,
folds.csv,summary.json}` (126 KiB total), each tagged with git SHA and config hash.

**Design decisions worth a later cycle's attention.**
- *Lags by explicit UTC offset reindexing, never `.shift(n)`.* `shift` counts rows,
  so across a missing hour it hands back the price from 25 hours earlier and calls
  it a 24-hour lag — a modelling bug that looks exactly like clean data. Asserted
  against directly.
- *Refit cadence is explicit.* `refit_every_days` blocks consecutive evaluation
  days; the training window always ends the day before the *first* day of the
  block, so a weekly refit means the last day is predicted by a six-day-stale
  model. That is what a weekly-refit desk experiences, not a bug. C3's committed
  run uses daily refit.
- *The guard fails closed.* An undeclared column is a violation, not a column
  given the benefit of the doubt — that is what catches a future cycle adding a
  feature and forgetting the bookkeeping. Likewise a declaration that is not a UTC
  timestamp column: one careless assignment turns it `object` or tz-naive, and
  comparing that to a tz-aware gate closure raises an opaque pandas `TypeError`,
  which in a guard is the worst outcome — a check that neither passes nor fails.
  Two of this cycle's own new tests hit exactly that crash and the *code* was
  fixed, not the test.
- *Calendar columns are asserted price-independent* (rebuilt on shuffled prices,
  bit-identical), so nothing price-derived can hide in a column declared to carry
  no market information.

**Files under `tests/` — declared, per CLAUDE.md.** Two files **added**:
`tests/test_c3_timing_features.py` (19 tests) and
`tests/test_c3_leakage_harness.py` (31 tests). That is C3's own mandate in PLAN.md
("leakage tests written *before* the real model"), and adding a new test file is not
what the rule guards against. **No existing test was edited, and no existing
assertion weakened or deleted** — `git diff --stat HEAD -- tests/` is empty;
`test_c1_data_layer.py`, `test_c2_contracts.py` and `conftest.py` are untouched. All
87 pre-existing tests pass unmodified. Where a new test failed, the code was fixed
(the two guard-robustness bugs above) except in three cases where the *test* was
wrong and was corrected before anything was committed: it masked cells inside the
lag warm-up window where the feature is legitimately NaN; it expected the
belt-and-braces day-ordering error when the stronger publication check correctly
fires first; and it asserted a 24-hour lead beats the weekly lag on a
*week-periodic* synthetic series, where by construction it does not — that test now
builds its own persistence-dominated series, which is the honest way to measure
what a leak buys.

**NOTE C3-02 — `config/data.yaml` gained three keys, so `config_hash` moved:
`47583ac06601f0a2` → `d524f72059bc6d85`.** The leakage guard needs the day-ahead
clock as config rather than as literals in code, so `structural_dates` gained
`day_ahead_gate_closure_tz: Europe/Brussels` and
`day_ahead_results_published_local: "13:00"` (plus comments). Purely additive —
nothing was changed, removed or weakened, and `splits`, the holdout declaration and
the unseal marker are untouched. Consequence: the committed
`data/manifest/prices_manifest.json` still records the C2-era `config_hash`
`47583ac06601f0a2`, which no longer matches the current config. The manifest's
*data* is unchanged and still valid — only the config fingerprint moved, and it
moved because of a key that has nothing to do with prices. Deliberately **not**
regenerated: that would mean re-pulling all 54 (zone, year) pairs to chase a hash,
churning a Checkpoint-A-approved artefact and hammering a free endpoint. Both
hashes are recorded here so provenance stays traceable. The guard's correctness
depends only on the ordering `gate_closure(D) < publication(D) < gate_closure(D+1)`,
asserted in `GateClosureConvention.__post_init__` and tested for every day of a
year — not on the exact publication minute.

**Data.** Only DE-LU was fetched (6 files, 2019–2024, ~1 MB) — C3 is DE-LU only, so
there was no reason to re-pull the other eight zones. All 6 downloaded cleanly, 0
flagged; the container arrived with `data/raw/` empty as NOTE C2-02 predicts and the
human decision there ("leave as is") was followed. No ENTSO-E call was made —
C3 needs no exogenous data, so `ENTSOE_API_KEY` was not read this cycle.

**Sealed holdout.** Verified armed before the work and again before committing:
marker-alone-on-a-line count in this file 0, `holdout_is_unsealed()` = `False`,
`sealed_years()` = `{2025}`, `fetch_years` = 2019–2024. No 2025 data was fetched,
loaded, feature-engineered from or measured against. Two tests name the year 2025
in order to prove the harness *refuses* it (`evaluation_days` and
`run_walk_forward` both raise `SealedHoldoutError`); they pass bare `datetime.date`
labels and read nothing — the same line C2 drew for its resolution-cutover tests.
The C1b warning was heeded: the marker string is not reproduced anywhere in this
entry, only referred to by its config key.

**Repo-state note.** The detached-HEAD trap **did** recur: the container arrived on
a detached HEAD at `17249e9`. Reattached with `git checkout -B master 17249e9` and
re-pointed at `origin/master` before any work. Now 5 recurrences out of 11
containers.

**Next:** C4 — LEAR (per-hour LASSO, in-fold scaling / asinh transform, in-fold
IC/CV selection), DE-LU, walk-forward on 2024 only. It plugs into this harness as a
`Model` and adds `scikit-learn` to `requirements.txt`. It will need a documented
policy for the NaN cells this cycle's mask creates (LASSO cannot take NaN) — the
honest options are dropping those rows from the *training* fit only, or imputing
in-fold from the training window, and neither should be chosen silently. The open
item from this cycle is **NOTE C3-01** (rename the daily-aggregate features in
`features.yaml`, or keep the names and rely on the docs); it does not block C4.

### C4 — 2026-10-02 (scheduled cycle) — LEAR, DE-LU, walk-forward on 2024

**Done, as scoped in PLAN.md C4.** LEAR — per-hour LASSO, in-fold asinh/MAD
variance stabilisation, in-fold penalty selection — plugged into C3's harness as a
`Model`, with the NaN policy C3 asked for decided and documented. 35 new offline
tests (172 total, all passing). Design notes in `docs/lear_model.md`.

**Headline, DE-LU 2024 (validation), expanding window from 2019, daily refit, 366
folds, 8,784 hours.**

| model | MAE | RMSE | bias | rMAE vs naive | coverage |
| --- | --- | --- | --- | --- | --- |
| naive same-hour-last-week (C3) | 32.80 | 55.22 | −1.52 | 1.000 | 1.00000 |
| **LEAR (AIC, committed)** | **22.86** | **36.92** | +2.60 | **0.697** | 0.99989 |
| LEAR (BIC) | 22.83 | 36.93 | +1.66 | 0.696 | 0.99989 |
| LEAR (time-ordered CV) | 22.90 | 36.93 | +2.74 | 0.699 | 0.99989 |
| LEAR (AIC, `nan_policy="impute"`) | 22.87 | 36.92 | +2.60 | 0.697 | 1.00000 |
| train-mean reference | 37.88 | — | — | — | 1.00000 |

**LEAR cuts the naive floor's MAE by 30%** (rMAE 0.697). That is the number C9's
booster has to beat and the forecast error the battery gets dispatched against
from C6.

**New modules.** `forecast/lear.py` (`LearSpec`, `LearModel`, the design encoding,
the VST), `backtest/run_c4_lear.py` (CLI). `forecast/models.py` gained
`TrainMedianBaseline` — purely additive, and the reason is FINDING C4-A below.

**The four decisions that carry the model, each one a place this usually goes
wrong.**
- *One LASSO per delivery hour, partitioned on **local** time.* Hour 03 and hour 18
  are different products; pooling them makes one model wrong about both. CLAUDE.md
  forbids local time for *resampling or alignment* — this is neither: no row moves,
  nothing is reindexed, the matrix is only grouped. And the partition key is itself
  a declared, gate-closure-checked feature column, so the thing deciding which
  model sees a row is under the same guard as everything else. `hour_key="utc"`
  exists so the choice is visible rather than baked in.
- *Everything fitted in-fold, then applied frozen.* Medians, MADs, standardisation
  moments, one-hot levels and the penalty are estimated on the training window and
  never recomputed at predict time. Two tests assert this behaviourally rather than
  by reading the code: predicting one row alone must return exactly what predicting
  the whole block returned, and multiplying every *other* test row by a thousand
  must not move the first row's number. A scaler fitted on train+test fails both —
  which is the point, because it is invisible in a diff.
- *asinh((y−a)/b) with the in-fold median and MAD, inverted exactly.* A log is
  unavailable on a market with negative prices, and an untransformed LASSO spends
  its whole budget on the 2022 spikes. `b` falls back MAD → std → 1.0 and the
  fallback is *reported*, because a constant price column in a training window is a
  data problem, not a feature. Back-transformed predictions are **not clipped**: an
  absurd run should show an absurd number, and the fit report carries predicted
  min/max so it is visible either way.
- *NaN answered, not absorbed* — the open question C3 handed over. Training rows
  with any missing design cell are **dropped from the fit** (listwise), counted per
  hour-model; a test asserts dropping a row is *equivalent* to the row never having
  existed, i.e. nothing was imputed behind the report's back. Test rows with a hole
  get **no prediction** (`nan_policy="decline"`), and `backtest/metrics.py` charges
  the model coverage for it rather than shrinking the denominator. A missing
  *calendar* cell is missing too, not a row of zero indicators — one-hot encoding a
  NaN would silently make it the reference level. An unseen category is counted; an
  unseen delivery hour gets no model and no number.

**The selector was chosen once, on validation, by a rule stated before the
numbers.** All three in-fold rules land within 0.35% of each other (22.83–22.90).
BIC wins by 0.17%, inside the 0.5% margin `backtest/run_c4_lear.py` commits to in
its docstring, so **AIC stays the committed default** — cheapest, fully
deterministic. The flatness is informative: with only ~26 design columns there is
little for a penalty to do and the selected alphas are near-zero (near-OLS). That
should change in C8 when load/RES features widen the design, so the comparison is
worth re-reading **once** then, not per cycle.

**PLAN's three leakage assertions, re-run on a model that can actually exploit a
leak** (probe cadence: weekly refit, for cost; the main run is daily).
- **(i) day shift.** Aligned MAE **22.861**; one day staler **26.479**; one day
  fresher **0.000**. LEAR recovers the target *exactly* from the shifted
  `price_lag_24h` column, because that column then **is** the target. So
  `degrades_for_every_shift` is **False** here where C3's naive floor had it True —
  the naive model reads only `price_lag_168h`, which any whole-day shift breaks in
  both directions. That is the measurement of what the leak is worth, not a bug;
  the gate-closure guard, not the sign of this number, is what refuses it on the
  real matrix.
- **(ii) future-feature guard.** Declared honestly → `after_gate_closure`;
  smuggled in undeclared → `undeclared`. The walk-forward refuses to run on either,
  with LEAR in the harness.
- **(iii) target permutation.** See FINDING C4-A — it needed real work.

**FINDING C4-A — a mean reference hands free skill to a median-like model, so
`destroys_skill` reads False for reasons that have nothing to do with LEAR.**
Real skill **+0.397** vs the train-mean baseline; with the target shuffled,
**+0.055** (hour-wise) and **+0.069** (whole-day). Read at face value that says a
model fitted on noise has skill. It does not. `backtest/metrics.py` scores MAE, minimised by the **median**;
`backtest/diagnostics.py` scores skill against the train-**mean**. DE-LU 2019–2024
prices are strongly right-skewed (mean **95.65**, median **66.18** EUR/MWh — the
2022 crisis), so on shuffled targets a constant at the training median beats a
constant at the training mean by ~**7%** of MAE while knowing nothing at all. LEAR
is a LASSO fitted in asinh space and mapped back through `sinh` — a median-like
estimator — so it collects that margin before it has learned anything. On the
permuted 2024 set: train-mean 66.47, **zero-information constant median 61.95
(+0.068 skill)**, permuted LEAR 62.78 (+0.055). **The permuted model earns less
than the constant that knows nothing**, and re-based on a median reference its
skill is **negative** (−0.013) while the honest model's stays clearly positive
(+0.380). Shuffling the target did destroy every bit of conditional skill; the
probe's pass criterion was simply calibrated for a mean-predicting model, which the
naive floor is and LEAR is not.
*The whole-day shuffle is a different question and also clean.* `mode="days"`
permutes whole market days, so it preserves the within-day shape — C3's own
docstring says as much, which is why that mode is reported separately rather than
used as the pass/fail probe. Its residue was measured rather than assumed: on the
day-permuted 2024 set a predictor knowing nothing but the **per-local-hour training
median** earns **+0.017** over the global training median, which is *more* than the
**+0.013** LEAR retains there; under the hour-wise shuffle the same hour-of-day
profile is worth **−0.001**, i.e. nothing, because that shuffle destroys it too. So
the entire day-mode residue is the daily price profile, LEAR extracts slightly less
of it than a plain per-hour median does, and the decisive hour-wise probe leaves it
with negative skill.
*What was done:* `TrainMedianBaseline` added to `forecast/models.py`; the re-based
comparison reported alongside the original in the committed summary under
`diagnostics.target_permutation_against_median`, both references refitted inside
the same walk-forward so nothing is a different evaluation set; and
`test_a_mean_reference_hands_free_skill_to_a_median_like_model` reproduces all
three halves of the diagnosis on a deliberately skewed synthetic series, so it
cannot be quietly un-learned. The ordinary near-symmetric test series does not show
it at all, which is why it surfaced only when LEAR met real prices.
*What was deliberately **not** done:* `backtest/diagnostics.py` was not touched. It
holds a PLAN.md leakage assertion, and re-basing `destroys_skill()` is exactly the
edit that turns a red probe green without looking wrong in a diff. Hence:

**NOTE C4-01 — decision requested, non-blocking: should `destroys_skill()` in
`backtest/diagnostics.py` be re-based on `TrainMedianBaseline`?** Proposed, not
done. As it stands the probe will read `destroys_skill: False` for every
median-like model from here on (LEAR now, very likely the C9 booster too), which
risks becoming a warning everyone learns to ignore — the worst state for a leakage
check. The options are (a) re-base the criterion on the median reference, (b) keep
the mean criterion and require instead that the permuted model not beat the
zero-information constant, or (c) leave it and rely on the re-based numbers
reported next to it. A human should pick; C5 is not blocked either way.

**NOTE C4-02 — hand-off to C5/C6: one hour a year has no forecast.** The committed
model declines the autumn DST hour whose 24-hour lag the gate-closure mask blanks
(FINDING C3-A) — exactly 1 hour of 8,784 in 2024. A forecast table can report that
honestly; the battery LP cannot, because committing a day's schedule needs a
complete 24-hour price vector. So the `impute` variant was run and scored too:
full coverage costs **0.001 EUR/MWh** of annual MAE. C6 therefore has a measured
choice — dispatch that day from the imputed forecast with the substitution
labelled, or exclude the day and report it as excluded. Either is defensible;
filling the hole silently inside the LP is not.

**NOTE C3-01 is still open** (rename the daily-aggregate features in
`features.yaml` to match the only leak-free window, or keep the names and rely on
`docs/forecast_harness.md`). C4 did not touch `config/features.yaml` and was not
blocked by it. `config_hash` is unchanged from C3's `d524f72059bc6d85`.

**Files under `tests/` — declared, per CLAUDE.md.** One file **added**:
`tests/test_c4_lear.py` (35 tests). **No existing test was edited** and no existing
assertion weakened or deleted — `git diff --stat HEAD -- tests/` shows only the new
file; `conftest.py`, `test_c1_data_layer.py`, `test_c2_contracts.py`,
`test_c3_timing_features.py` and `test_c3_leakage_harness.py` are untouched, and
all 137 pre-existing tests pass unmodified. Four of this cycle's own new tests
failed on first run and in all four cases the *test* was wrong and was corrected
before anything was committed: two poked holes in cells that were already NaN
inside the lag warm-up or spanned two months where the test said one; one asserted
LEAR predicts every hour when declining the masked DST hour is the designed
behaviour (it now asserts the declined hours are *exactly* the holed ones); and one
expected a 24-hour lead to halve LEAR's MAE as it halved the naive floor's, where
the honest expectation is ~30% — LEAR already holds the price 24 hours *back*, so
the leading feature is a second observation the same distance away on the other
side, and averaging two symmetric observations of a random walk cuts error by about
sqrt(2), not sqrt(7). The bound and the reasoning are both in the test.

**Dependencies.** `scikit-learn>=1.7` added to `requirements.txt`; the floor is 1.7
because `LassoCV`'s alpha-path argument was renamed there (`n_alphas` → an int
`alphas`) and `forecast/lear.py` uses the current spelling. Installed 1.9.1.

**Data.** Only DE-LU was fetched (6 files, 2019–2024, ~1 MB) — C4 is DE-LU only.
The container again arrived with `data/raw/` empty, as NOTE C2-02 predicts; all 6
pairs downloaded cleanly, 0 flagged. No ENTSO-E call was made: C4 needs no
exogenous data, so `ENTSOE_API_KEY` was not read (it *is* set in this environment —
the C7 precondition still holds).

**Sealed holdout.** Verified armed before the work and again before committing:
marker-alone-on-a-line count in this file 0, `holdout_is_unsealed()` = `False`,
`sealed_years()` = `{2025}`, `fetch_years` = 2019–2024. No 2025 data was fetched,
loaded, feature-engineered from or measured against at any point in C4. The
evaluation years passed to every run were `[2024]`. The marker string is not
reproduced here, only referred to by its config key.

**Repo-state note.** The detached-HEAD trap recurred again: the container arrived
on a detached HEAD at `1a084d3`. Reattached with `git checkout -B master 1a084d3`
and re-pointed at `origin/master` before any work. Now 6 recurrences out of 12
containers — worth a line in the write-up's reproducibility section.

**Next:** C5 — battery LP v1, DE-LU, **oracle curve only**. Rolling 24h horizon,
realised end-of-day SoC carried into the next day plus a terminal condition (never
reset to zero at midnight), symmetric round-trip efficiency (sqrt(0.88) per leg),
throughput/cycling cost ~2–5 EUR/MWh discharged, and an explicit check for
simultaneous charge/discharge under negative prices (a FLAG if found — LP artefact
needing a penalty term or a MILP). Unit tests PLAN.md names: a hand-computed toy
price vector, value monotone in spread, value exactly 0 on a flat curve. Adds an LP
solver to `requirements.txt` (`highspy` via scipy's HiGHS, or `pulp`). The
commit-then-settle machinery and the oracle ≥ model ≥ naive assertions are C6, at
**Checkpoint B**. Open items carried forward: NOTE C3-01, NOTE C4-01, NOTE C4-02.

### C5 — 2026-10-02 (scheduled cycle) — battery LP v1, DE-LU, oracle curve only

**Done, as scoped in PLAN.md C5.** The dispatch LP, the rolling horizon with
carried SoC, the settlement, and PLAN's three named unit tests. 64 new offline
tests (**236 total, all passing**). Design notes in `docs/battery_lp.md`. New
modules: `config/battery.yaml`, `dispatch/battery.py`, `dispatch/rolling.py`,
`backtest/run_c5_oracle_lp.py`. One FLAG, raised not worked around — **FLAG
C5-01** below.

**Headline, DE-LU 2024, oracle (perfect foresight) curve.** 1 MW / 2 MWh (2h),
round-trip 0.88 split `sqrt(0.88) = 0.938083` per leg, throughput cost
2 EUR/MWh discharged, 7-day median trailing mark on closing inventory. 366 market
days dispatched, **0 skipped**.

| | |
| --- | --- |
| oracle cash | **74,552.06 EUR** = **74,399 EUR/MW/yr** |
| equivalent full cycles | 634.8 (1.73/day) |
| energy in / out | 1,443.76 / 1,269.57 MWh (ratio 0.8793 ≈ the 0.88 round trip) |
| day-length histogram | 23h × 1, 24h × 364, 25h × 1 |

That is the ceiling C6's forecast curve is measured against, and the denominator
of every capture ratio from C11 on.

**Per-year oracle value, 2019–2024 — descriptive context, not a result.** The
oracle is a property of the realised price series: no model, no forecast, nothing
fitted. One continuous roll, SoC carrying across year boundaries.

| year | EUR/MW/yr | cycles | mean daily spread | sim-days |
| --- | --- | --- | --- | --- |
| 2019 | 16,250 | 578.4 | 30.01 | 9 |
| 2020 | 18,498 | 616.7 | 32.47 | 16 |
| 2021 | 48,327 | 600.9 | 80.31 | 9 |
| 2022 | **119,855** | 624.7 | 186.99 | 0 |
| 2023 | 62,522 | 621.5 | 97.88 | 8 |
| 2024 | 74,399 | 634.8 | 111.20 | 20 |

Value tracks mean daily spread almost exactly (2 MWh × spread × ~0.9 reproduces
each row to within a few percent) while cycling barely moves — the asset is
spread-limited, not cycle-limited, which is the shape C13's regime chapter needs.
2022 at 7.4× 2019 is the crisis year PLAN.md requires reporting separately.

**The design decisions that carry the result.** Full reasoning in
`docs/battery_lp.md`; the four that would change numbers:

- *The horizon is the **market day**, 23 and 25 hours included.* Not a UTC day and
  not 24 rows. The auction clears a local calendar day as one block and a bidder
  commits exactly that block. Each block's length is asserted against
  `data.contracts.local_day_hours` — the tz database, not a remembered rule — which
  is CLAUDE.md's DST whitelist applied to dispatch. The 2024 histogram above is
  that assertion's output: exactly one short day and one long day, neither padded.
- *Closing inventory is marked, because otherwise the LP invents the forbidden
  midnight reset.* A 24h horizon with no terminal condition always ends empty — the
  last stored MWh is free revenue inside the horizon and worthless outside it, so
  PLAN.md's rolling SoC carryover becomes the daily reset it forbids, arrived at by
  the LP rather than by a line of code, which is worse because nothing in the diff
  shows it. One test pins that behaviour deliberately. The mark is
  `max(0, eta * (p_ref - k))` per MWh *stored*: it pays the discharge leg and the
  throughput cost on the way out, and it is floored at zero because a negative mark
  would pay the LP to burn energy. **271 of 366 days open at SoC 0 and 95 do not** —
  a reset would have made it 366, so the carryover is doing real work.
- *`p_ref` is a **trailing** 7-day median of realised prices, never the day's own
  vector.* Two properties, both asserted rather than argued. **Knowable at gate
  closure**: it uses only market days `<= D-1`, published 13:00 local on `D-2`,
  before gate closure 12:00 local on `D-1`; `assert_reference_is_knowable`
  re-derives both instants from `forecast.timing` and raises otherwise. The mark is
  a term in the objective, not a feature, so C3's gate-closure guard never sees it
  and it gets its own check. **Curve-independent**: a mark read off the decision
  vector would differ between the oracle, forecast and naive runs, and the per-day
  dominance bound would not hold at all.
- *Three money numbers, and the headline is **cash**.* `cash` (settled),
  `terminal`/`opening` (marks on inventory), and
  `value_added = cash + terminal - opening` — what the day's trading added over
  standing still. `value_added` is what the LP maximises, so the invariants are
  stated on it: exactly 0 on a flat non-negative curve, never negative, monotone in
  spread/capacity/power. The headline is cash because the marks do not cancel over
  a year — measured divergence on DE-LU 2024 is **0.861%**, small but a model
  output rather than money.

**The per-day upper bound needs two oracles, and C6 must build the second.**
CLAUDE.md's `value(forecast @ realised) <= value(oracle @ realised)` **every day**
holds exactly — and only — when both are solved from the **same opening SoC**
against the **same mark**: the frozen forecast schedule is then a feasible point of
the oracle's own problem. `assert_oracle_dominates` checks both preconditions and
refuses to compare mismatched setups, because an assertion that silently compares
two different problems is worse than none. Across two independently *rolled*
trajectories the opening SoCs diverge and no per-day bound exists — a forecast run
that happens to open a day fuller can out-earn the rolled oracle that day, which is
expected, not a bug. **So C6 needs a rolled oracle for the pooled comparison and a
same-start oracle, re-solved each day from the forecast run's own opening SoC, for
the per-day assertion.** `solve_day` takes `soc_start_mwh` explicitly so C6 can do
that without reaching into anything's state. Both halves are implemented and tested
in C5; only the oracle curve is run, which is C5's scope.

**Invariants run on the real 2024 run, all passing**, and independently
re-verified from the committed artefacts alone (not from the objects that wrote
them): annual cash recomputed hour-by-hour from `..._schedule.csv.gz` × realised
prices reproduces 74,552.0 EUR; `soc_end(D) == soc_start(D+1)` for all 365 day
pairs to **0.0e+00**; power never exceeds 1.000000 MW; the best day (2024-12-12,
the 936 EUR/MWh spike) hand-recomputes to 1,754.724 EUR against 1,754.724 in the
artefact, with its round-trip energy balance exact to 4 d.p.; `value_added >= 0` on
all 366 days; perfect foresight beats a foresight-free schedule on all 60 sampled
days with worst excess **0.0**.

**FLAG C5-01 — simultaneous charge/discharge found, as PLAN.md anticipated.
Measured, not silently fixed. One decision requested; C6 is not blocked.**
PLAN.md requires an explicit check and calls this an LP artefact needing a penalty
term or a MILP. It is real here, and the arithmetic predicts exactly where: with
the upper SoC bound binding, `c` and `d` both positive draw a net
`c * (1 - eta^2) > 0` MW from the grid with stored energy flat — the battery burning
power in its own round-trip losses to be paid for consuming. It pays below
`-k * eta^2 / (1 - eta^2)` = **-14.67 EUR/MWh**, and DE-LU had 457 negative hours in
2024. A single-inverter BESS cannot do this.

| | |
| --- | --- |
| days affected | **20 of 366** |
| intervals affected | 53, **all 53 at a negative price** |
| lowest price with overlap | -100.06 EUR/MWh (2024-05-12) |
| grid energy burned | 5.318 MWh |
| cash earned from the overlap | 322.30 EUR = **0.43% of annual cash** |
| cost of forbidding it exactly (MILP) | **125.47 EUR = 0.17%** |

The gap is smaller than the overlap cash because forbidding the trade makes the LP
do something else instead rather than nothing. Per-year `sim-days` above show the
same signature: 20 in 2024 and 16 in 2020 (many deep-negative hours), **0 in 2022**
(69 negative hours, none deep enough).

*What was done:* `forbid_simultaneous=True` implements PLAN's named remedy exactly,
one binary per interval via scipy's HiGHS MILP (24 binaries a day is free), and
both variants are run and persisted. `no_simultaneity_remains` reads 0 intervals
under the MILP and `milp_cannot_beat_lp` holds, as it must.

*What was deliberately **not** done:* the committed default was not changed. The
pure LP is what C5 scopes, and which variant becomes the default from C6 onward
moves every headline number by 0.17% — a human's call, not an unattended cycle's.
The options are **(a)** make the MILP the default and report the pure LP as the
sensitivity, **(b)** keep the pure LP and carry 0.17% as a stated limitation, or
**(c)** add `c_t + d_t <= P` — a single shared inverter rating, which is physically
the right constraint for real hardware, bounds the artefact without a binary, and
is not implemented so that one decision sits in front of the reviewer instead of
three. **No push notification was sent for this**: PLAN.md reserves that for a
genuine blocker or an invariant failing in a way that is *not* an expected,
explained finding, and this is a finding PLAN.md predicted by name and told this
cycle to flag. C6 is Checkpoint B and will ask anyway.

**FINDING C5-A — "value = 0 on a flat curve" is true only for a flat
*non-negative* curve.** At a flat negative price, with no spread whatsoever, a
battery is simply a load being paid to consume: it fills up, never discharges, and
the money is real. The committed 1 MW / 2 MWh asset earns 29.76–80.42 EUR on a flat
-25 EUR/MWh day depending on opening SoC. This is **not** FLAG C5-01 — a *lossless,
costless* battery shows it too, where there is no round-trip channel to burn
through at all (`simultaneity_price_threshold` is `-inf` at `eta = 1`), earning
exactly 50 EUR by filling 2 MWh at -25. PLAN's invariant is kept as stated for
`p >= 0`, where it holds exactly for every opening SoC, and the negative case is
pinned by its own test so it cannot be quietly re-broken.

**FINDING C5-B — the mark makes the flat-curve optimum degenerate, and that is
value-neutral.** At `p_ref` exactly equal to a flat day's price, holding and
liquidating are worth the same to the penny, so the LP may return either and the
day's reported *cycling* is arbitrary; its *value* is exactly 0 either way, and
cash is exactly the opening inventory liquidated at the mark. Two tests pin both
halves, and the run counts flat days so "measure zero on real prices" is a
measurement: **DE-LU 2024 has 0 flat days and 0 flat-at-the-mark days.** Priced
away from the mark a flat day trades toward it — which is a second reason the
headline is cash and not summed `value_added`.

**NOTE C4-02 answered mechanically; C6 still chooses.** A day whose price vector
has a hole is **skipped and reported**, never patched: `solve_day` refuses a
non-finite decision price outright, and `dispatch/rolling.py` counts skips by
reason (`incomplete` / `no_reference` / `boundary`). The oracle run skipped 0 days
because realised prices are complete; the one declined hour a year is a *forecast*
problem, so C6 still picks between dispatching that day from the `impute` variant
with the substitution labelled (measured cost: 0.001 EUR/MWh of annual MAE) and
excluding the day. C5's contribution is that neither choice can now be made
invisibly.

**Files under `tests/` — declared, per CLAUDE.md.** One file **added**:
`tests/test_c5_battery_lp.py` (64 tests). **No existing test was edited**, no
assertion weakened or deleted — `git diff --stat HEAD -- tests/` shows only the new
untracked file, and all 172 pre-existing tests pass unmodified. Five of this
cycle's own new tests failed on first run, before anything was committed. In four
cases the *test* was wrong and in one it found a real code bug:
1. `value_added == 0` asserted on a flat curve at **-25 EUR/MWh** — wrong, that is
   FINDING C5-A. Test renamed to `..._non_negative_curve`, parameters changed to
   `{0, 2, 50, 400}`, and the negative case given its own test asserting the
   genuine value.
2. "a flat curve produces no trading" — wrong, FINDING C5-B: at `p_ref == p` the
   optimum is degenerate. Replaced by a test that the degenerate case is
   value-neutral with cash pinned to the mark.
3. "the mark keeps inventory on a flat day" — the same degeneracy; the reference is
   now set above the day's price so the prediction is real.
4. "a mark strictly above the day's price means no trading" — wrong premise
   entirely: a mark above today's price makes *charging* attractive, so there is no
   non-degenerate flat case in which the LP stands still. Replaced by a directional
   test (below the mark → fills; above → empties).
5. **A real bug.** Writing the FINDING C5-A test with a lossless, costless battery
   exposed `simultaneity_price_threshold` returning `0.0` instead of `-inf` at
   `eta = 1` with `k > 0`: at `eta = 1` matched charge/discharge draws a net zero
   from the grid, so **no** price makes burning pay and the threshold is `-inf`
   whatever the cost. `dispatch/battery.py` fixed; the test asserts the `-inf`.

**Dependencies.** `scipy>=1.11` added to `requirements.txt` — already present
transitively via scikit-learn, but C5 depends on it directly so it is declared
directly. HiGHS ships inside scipy, so no separate solver install and no licence;
the floor is 1.11 because `milp` and the `Bounds`/`LinearConstraint` objects it
takes settled into their current form there. Installed 1.17.1. No `highspy` or
`pulp`.

**Config hash changed: `d524f72059bc6d85` → `84f7bf31591d1e7f`**, because
`config/battery.yaml` is new and `config_hash()` spans every `config/*.yaml`. No
existing config file was modified; `config/features.yaml` is untouched and **NOTE
C3-01 is still open**.

**Data.** DE-LU only, 6 files 2019–2024 (~1 MB) — C5 is DE-LU only. The container
again arrived with `data/raw/` empty, as NOTE C2-02 predicts; all 6 pairs
downloaded cleanly, 0 flagged. **Integrity verified rather than assumed**:
`payload_fingerprint` for all six years matches C1's committed manifest exactly, so
this is byte-identical to the data every prior cycle used. No ENTSO-E call — C5
needs no exogenous data, so `ENTSOE_API_KEY` was not read (it *is* set in this
environment; the C7 precondition still holds).

**Sealed holdout.** Verified armed before the work and again before committing:
marker-alone-on-a-line count in this file 0, `holdout_is_unsealed()` = `False`,
`sealed_years()` = `{2025}`, `fetch_years` = 2019–2024. No 2025 data was fetched,
loaded, dispatched or measured against at any point in C5. The runner calls
`assert_not_sealed` on every requested year before a price file is opened. The
marker string is not reproduced here, only referred to by its config key.

**Repo-state note.** The detached-HEAD trap recurred again: the container arrived
on a detached HEAD at `89d5583`. Reattached with `git checkout -B master 89d5583`
and re-pointed at `origin/master` before any work. Now **7 recurrences out of 13
containers** — still worth a line in the write-up's reproducibility section.

**Next:** **C6 — CHECKPOINT B.** Commit-then-settle machinery with all three curves
(oracle / LEAR / naive) on DE-LU, asserting pooled `oracle >= model >= naive` and
the per-day bound via the **same-start oracle** described above; then stop,
push-notify, and wait for the human to eyeball one zone end-to-end (a week of
dispatch against the price plot) before scaling out. C6 also decides NOTE C4-02
(imputed hour vs excluded day) and should put FLAG C5-01's three options to the
human in the same review. Open items carried forward: **FLAG C5-01**, NOTE C3-01,
NOTE C4-01, NOTE C4-02.

### C6 — 2026-10-02 (scheduled cycle) — commit-then-settle, three curves, DE-LU — **CHECKPOINT B REACHED**

**Done, as scoped in PLAN.md C6, and then stopped.** The commit-then-settle
machinery across all three curves (oracle / LEAR / naive) on DE-LU 2024, both
oracles, the pooled assertion, and Checkpoint B's own required output: three
figures of a week of dispatch drawn against the price plot. 35 new offline tests
(**271 total, all passing**). Design notes in `docs/commit_then_settle.md`. New
modules: `dispatch/curves.py`, `backtest/run_c6_curves.py`. **NOTE C4-02 is
decided and the decision is priced. FLAG C5-01 is restated with new evidence and
is still the human's to decide.** No new FLAG was raised.

**Checkpoint B is a human eyeballing one zone end to end before anything scales
out to nine zones. Nothing in C7+ has been started.**

---

#### The headline, DE-LU 2024, 1 MW / 2 MWh

Pooled over the 365 market days every curve dispatched (see NOTE C4-02 below for
the 366th):

| curve | cash, 365d | EUR/MW/yr | rolled capture | same-start capture |
| --- | --- | --- | --- | --- |
| **oracle** (perfect foresight) | 74,365.45 | **74,399** | 1.0000 | 1.0000 |
| **model** (LEAR, C4's committed run) | 68,318.88 | **68,179** | **0.9187** | **0.8696** |
| **naive** (same hour last week) | 62,997.68 | **62,868** | 0.8471 | 0.7797 |

**EUR/MW/yr lost to forecast error: 6,047.** `oracle >= model >= naive` holds on
pooled cash and on pooled `value_added`; margins 6,046.57 and 5,321.20 EUR.
The oracle total reproduces C5's committed 74,552.06 EUR over its full 366 days
**exactly** — a cross-cycle check that the LP and the roll did not move.

**Two capture ratios, and the honest one is the lower one.** Both are reported
because quoting either alone misleads:

* **rolled** 0.9187 — annual cash against the rolled oracle's annual cash. Part
  of what this credits to the forecast is the forecast run's *trajectory*
  happening to open some days in a better state than the oracle's did.
* **same-start** 0.8696 — pooled `value_added` against an oracle re-solved each
  day from the model run's own opening SoC. Bounded above by 1 **on every single
  day by construction**, so this is the per-day truth.
* mean of the daily same-start ratios **0.8204**, median **0.9018**, p05 0.2919,
  p25 0.7645, p75 0.9731. Mean below pooled says what it always says about power
  prices: value is concentrated in a few high-spread days, and capture is
  *better* on those days than on the quiet ones. PLAN.md asks for the
  distribution and not just the mean, so the quantiles are persisted from C6 on.

**The model beats the naive floor on 239 of 365 days (65.5%)** — it loses to it
on more than a third of days and still wins by 5,321 EUR over the year. CLAUDE.md
states that half of the invariant as an average and not a per-day claim; this is
the number behind that wording.

#### The two oracles, and the per-day invariant

CLAUDE.md's `value(forecast @ realised) <= value(oracle @ realised)` **every
day** is asserted on **every dispatched day, not a sample**, against the
same-start oracle. Worst excess over the bound: **exactly 0.0 EUR** for both the
model and the naive curve; **0 days** out of 730 curve-days have
`capture_same_start > 1`, re-derived independently from the committed
`..._daily.csv` rather than from the objects that wrote it.

**The model out-earned the *rolled* oracle on 50 of 365 days.** That is the
trajectory divergence C5 predicted in prose, now a number: across two
independently rolled trajectories the opening SoCs differ and no per-day bound
exists. It is counted and reported, never asserted away. A test demonstrates the
mechanism as a controlled experiment rather than by hoping a fixture exhibits it
— a run opening a day full, committed on an imperfect forecast, beats perfect
foresight that opened the same day empty, and `assert_oracle_dominates`
**refuses** that comparison rather than reporting a breach, because the two are
not the same problem.

**Commit-then-settle is structural, not careful.** `decision_prices` and
`realised_prices` are separate arguments; every valuation carries
`prices_are_decision_prices`; and `assert_settlement_is_not_a_readback`
re-derives the truth from the schedules — comparing each day's decision vector
against the realised one — and requires the flag to agree with what it finds. A
perfect forecast that happens to equal realised prices is legitimate and passes;
a forecast run that *claims* to be a read-back fails. Verified on all three runs.

#### FINDING C6-A — `value_added >= 0` is a theorem about the **decision** problem, not about settlement

C5 asserts `value_added >= 0` on the oracle run, reasoning that standing still is
always feasible so the optimum cannot lose. Applied unchanged to the forecast
curves it **failed on first run** — 3 model days and 17 naive days. It was right
to fail: for the oracle the decision prices *are* the realised prices, so the
statement transfers; for a forecast curve they are different vectors and it does
not. A schedule frozen on a wrong forecast **can lose money at realised prices**,
and that is the quantity this whole project exists to measure.

So the theorem is now asserted about the problem it is a theorem about
(`check_decision_value_added_non_negative`, on the decision prices, all three
curves, holds), C5's realised-price form stays asserted **unchanged** on the
oracle where it is binding, and the realised losses are *reported*:

| curve | days that lost money at realised prices | total |
| --- | --- | --- |
| oracle | 0 of 366 | 0.00 EUR |
| model | 3 of 365 (worst 2024-12-07, −34.13) | **−41.37 EUR** |
| naive | 17 of 366 (worst 2024-12-25, −130.30) | **−662.52 EUR** |

Nothing was weakened to make this green: no assertion was deleted or loosened,
the oracle's version is unchanged, and the new one is a strictly-defined theorem
that must hold. This is a left-tail result a desk would ask for before the mean —
forecast error does not merely forgo upside, on ~1% of days it turns the day's
trading into an outright loss, and the naive floor does it six times as often and
sixteen times as expensively.

#### NOTE C4-02 — **DECIDED: exclude the day, report it excluded.** The alternative was priced, not argued away.

One hour a year (2024-10-27 23:00 local, the 25-hour autumn DST day whose 24-hour
lag the gate-closure mask blanks — FINDING C3-A) has no LEAR forecast under the
committed `nan_policy="decline"`, and the LP needs a complete vector.

**Decision: the day is skipped and reported, and every pooled number is computed
over the common day set** (365 days), so the exclusion can never compare a
365-day model total against a 366-day oracle total. Reasons: it uses the
skip-by-reason mechanism C5 already built and tested, it introduces no price that
no model produced, and the alternative is recoverable at any time.

**Priced**: `--measure-impute` re-runs that single fold under
`nan_policy="impute"` (one LEAR fit, not 366) and dispatches the day from the
imputed vector, opening at the SoC the committed model run actually carried in
(0.0 MWh). It would have earned **−33.47 EUR of cash** — the day is a *loss* —
at a same-start capture of 0.673. **Excluding it therefore does not flatter the
model; it very slightly flatters it to include it**, which is the direction that
matters for honesty. A human can overturn this to `impute` with the substitution
labelled and the headline moves by about 0.05%.

#### FLAG C5-01 — restated with new evidence, **still open, still the human's call**

The committed default is **unchanged** (pure LP), exactly as C5 left it. C6 ran
the MILP (`forbid_simultaneous=True`) across all three curves so the review can
see whether the *result* — the capture ratio — moves. New evidence, which points
the opposite way from what C5's single-curve measurement suggested:

| curve | LP cash − MILP cash | simultaneity days (LP) | overlap cash (LP) |
| --- | --- | --- | --- |
| oracle | **+125.47** | 20 of 366 | +322.30 |
| model | **−0.49** | 1 of 365 | +2.36 |
| naive | **−89.88** | 20 of 366 | **−87.61** |

**The artefact flatters the oracle and *penalises* the forecast curves.** A
forecast curve commits the overlap on hours its forecast said were deeply
negative; when they do not realise negative, the burn is paid for at realised
prices and earns nothing — the naive curve's overlap cash is *negative*. So the
pure LP's capture ratio is biased **against** the model: capture is 0.9187 under
the LP and **0.9203 under the MILP**, a shift of **+0.0016** (+0.16pp). The
ordering `oracle >= model >= naive` holds under both. Zero simultaneity intervals
remain under the MILP, as they must.

The three options are unchanged — **(a)** MILP as default with the pure LP as the
sensitivity, **(b)** keep the pure LP and carry the artefact as a stated
limitation, or **(c)** add `c_t + d_t <= P`, the single shared inverter rating,
which is physically right for real hardware and needs no binary. The new
information for the decision is that the effect on the headline is 0.16pp and in
the model's favour, so none of the three changes any conclusion. Still
non-blocking. No separate push notification: Checkpoint B's own notification
carries it.

#### Checkpoint B's required output — three weeks of dispatch, drawn

`docs/figures/c6_dispatch_week_DE-LU_<START>.png`, chosen by rule rather than by
taste: **typical** (week whose mean daily spread is closest to the year's),
**high_spread** (the week with the most oracle value), **worst_capture** (the
week containing the model's worst same-start capture day).

| figure | week | oracle | model | naive |
| --- | --- | --- | --- | --- |
| typical | 2024-05-20 | 1,523 EUR | 1,382 (91%) | 1,449 (**95%**) |
| high_spread | 2024-11-04 | 3,425 EUR | 3,340 (**98%**) | 3,110 (91%) |
| worst_capture | 2024-12-02 | 998 EUR | 577 (58%) | 516 (52%) |

Each has three panels on one time axis: realised price against both forecasts;
the SoC each curve actually carried (including across midnight — a daily reset
would show as a sawtooth and does not); and **cumulative settled cash**, which
puts the whole result in one readable panel. In the typical week the **naive
floor beats LEAR** — worth seeing, and exactly the kind of thing a weekly figure
should surface rather than an annual mean hide.

#### Independently re-verified from the committed artefacts alone

Not from the objects that wrote them. Per curve, recomputing annual cash hour by
hour from `..._schedule.csv.gz` × realised prices reproduces 74,552.06 /
68,318.88 / 62,997.08 EUR to <2e-4 (CSV rounding); `soc_end(D) == soc_start(D+1)`
to **0.0e+00** on every day pair for all three curves, including across the
model's skipped day (SoC carried unchanged — the battery sat idle, as designed);
power never exceeds 1.000000 MW and SoC stays inside [0, 2]; the capture ratios
recompute from `..._daily.csv` to 0.918691 / 0.847136, matching the summary.

#### Files under `tests/` — declared, per CLAUDE.md

One file **added**: `tests/test_c6_commit_then_settle.py` (35 tests). **No
existing test was edited** — `git diff --stat HEAD -- tests/` is empty and only
the new untracked file appears in `git status tests/`; all 236 pre-existing tests
pass unmodified. One of this cycle's own new tests failed on first run, before
anything was committed, and the fix was to the *test*, not to a claim:
`test_the_rolled_oracle_gives_no_per_day_bound` asserted that some day in a
30-day synthetic fixture would see the model out-earn the rolled oracle. The
claim is true on real data (50 of 365 days) but the fixture was too short and too
smooth to exhibit it, and tuning a random fixture until it did would have been
fabricating the phenomenon. Replaced by two tests that establish the same thing
deterministically: a controlled same-day experiment (full opening SoC vs empty
opening SoC) and a direct measurement that the two rolled trajectories do diverge
in opening SoC.

#### Housekeeping

- **Data.** Only DE-LU was fetched (6 files, 2019–2024, ~1 MB) — C6 is DE-LU
  only. The container again arrived with `data/raw/` empty, as **NOTE C2-02**
  predicts; 6 pairs downloaded cleanly, 0 flagged. **NOTE C2-02 is still open**
  and this is its 4th recurrence.
- **No ENTSO-E call.** C6 needs no exogenous data, so `ENTSOE_API_KEY` was not
  read. It *is* set in this environment; the C7 precondition still holds.
- **Sealed holdout verified armed**, before and after the work: marker-alone-on-
  a-line count **0**, `holdout_is_unsealed()` = `False`, `sealed_years()` =
  `{2025}`, and no 2025 file exists in the cache. No 2025 data has been fetched,
  loaded, dispatched or computed against at any point in C2–C6.
- **Config hash unchanged at `84f7bf31591d1e7f`.** No `config/*.yaml` file was
  modified; `config/features.yaml` is untouched and **NOTE C3-01 is still open**.
- **No new dependency.** scipy/matplotlib/scikit-learn already declared.
- **Repo-state note:** the detached-HEAD trap recurred again — the container
  arrived on a detached HEAD at `f653618`. Reattached with
  `git checkout -B master f653618` and re-pointed at `origin/master` before any
  work. **8 recurrences out of 14 containers.** Keep checking
  `git rev-parse --abbrev-ref HEAD` at the start of every cycle.

#### What Checkpoint B is asking the human for

1. **Eyeball the three week figures** against the price plots from Checkpoint A.
   Does the dispatch look like a battery buying low and selling high, and does
   the SoC carry across midnight rather than resetting?
2. **Sanity-check the headline**: 87–92% of perfect-foresight value captured by a
   price-history-only LEAR on DE-LU 2024, 6,047 EUR/MW/yr lost to forecast error.
   Is that plausible for a 2h battery in a thermal/RES-mixed zone?
3. **Decide FLAG C5-01** (a / b / c above). Effect on the headline is 0.16pp.
4. **Confirm or overturn NOTE C4-02** (exclude the declined day — current
   decision — vs dispatch it from the imputed forecast with the substitution
   labelled).
5. **NOTE C3-01 and NOTE C4-01 are still open** from C3/C4 and are unchanged.

Then set "Next cycle to run" at the top of this file to **C7** and the cycle
after this one will scale out.

---

### Checkpoint B wait — 2026-10-03 (scheduled cycle, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `origin/master` == local HEAD at `babdca9` (the C6 checkpoint
  commit, no human commits since, `git status` clean); all Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them); holdout guard re-verified armed
  (marker-alone-on-a-line → `holdout_is_unsealed()` = `False`, `sealed_years()` =
  `{2025}`, no 2025 file anywhere under `data/`); no 2025 data touched; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). The detached-HEAD trap **did** recur: the container
  arrived detached at `babdca9`, reattached with `git checkout -B master babdca9` and
  re-pointed at `origin/master` before anything else (now **9 recurrences out of 15
  containers**). Still waiting on the five Checkpoint B items listed at the top of
  this file (eyeball the three week figures, sanity-check the 87–92% headline, decide
  **FLAG C5-01**, confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01**
  / **NOTE C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human
  replaces the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-03 (scheduled cycle, 2nd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `origin/master` == local HEAD at `00f70fc` (the first
  Checkpoint B wait commit — no human commits since, `git status` clean, `git fetch`
  brought nothing new beyond the commit this session's container already had); all
  Checkpoint B artefacts present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}`,
  the three `docs/figures/c6_dispatch_week_DE-LU_*.png`, and the C1–C5 artefacts
  beneath them); holdout guard re-verified armed (marker-alone-on-a-line count **0**,
  `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`, no 2025 file
  anywhere under `data/`); no 2025 data touched; `ENTSOE_API_KEY` not read (not
  needed before C7); config hash unchanged (no `config/*.yaml` modified); no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` again arrived empty, **NOTE C2-02**'s 5th
  recurrence, but nothing was re-downloaded because no work needed data. The
  detached-HEAD trap **did** recur: the container arrived detached at `00f70fc`,
  reattached with `git checkout -B master 00f70fc` and re-pointed at `origin/master`
  before anything else (now **10 recurrences out of 16 containers**). Still waiting on
  the five Checkpoint B items listed at the top of this file (eyeball the three week
  figures, sanity-check the 87–92% headline, decide **FLAG C5-01**, confirm or overturn
  **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE C4-01**); **NOTE C2-02**
  also remains open. C7 stays blocked until a human replaces the status line with
  **C7** and records the approval here.

### Checkpoint B wait — 2026-10-03 (scheduled cycle, 3rd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin` advanced `origin/master` from the stale
  `fc422de` the container shipped with to **`c329968`** (the 2nd Checkpoint B wait
  commit) — i.e. **no human commits since**, and `origin/master` == local HEAD ==
  `c329968`, `git status` clean, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`). Holdout guard re-verified armed (marker-alone-on-a-line count
  **0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`, no `*2025*`
  file anywhere under `data/`); no 2025 data touched. `ENTSOE_API_KEY` not read (not
  needed before C7); no `config/*.yaml` modified, so the config hash is unchanged; no
  push notification sent (the Checkpoint B ping was already sent in C6 — repeat pings
  for the same wait are noise). `data/raw/` did not exist at all this time, **NOTE
  C2-02**'s 6th recurrence, but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur: the container arrived detached at `c329968`
  (now **11 recurrences out of 17 containers**). New wrinkle worth recording for
  future cycles: the local `master` *ref* arrived stale at `fc422de` (the C2
  checkpoint commit, 3 commits behind HEAD), so a bare `git checkout master` would
  have silently rewound C5, C6 and the two wait commits out of the working tree. The
  safe reattach is the one used here and in the previous two waits — `git checkout -B
  master <HEAD sha>` after a `git fetch`, then `--set-upstream-to=origin/master` —
  never a plain `git checkout master`.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-04 (scheduled cycle, 4th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`31f4818`** (the 3rd Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `31f4818` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`, unchanged from the 3rd wait). Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. `ENTSOE_API_KEY` not read (not needed before C7); no `config/*.yaml`
  modified, so the config hash is unchanged; no push notification sent (the
  Checkpoint B ping was already sent in C6 — repeat pings for the same wait are
  noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s 7th recurrence,
  but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur: the container arrived detached at `31f4818`
  with the local `master` *ref* stale at `fc422de` (4 commits behind HEAD) — now
  **12 recurrences out of 18 containers**, and the stale-local-`master` wrinkle first
  recorded in the 3rd wait is now confirmed as the normal shape of it, not a one-off.
  The safe reattach used here is unchanged: `git fetch origin master`, then
  `git checkout -B master <HEAD sha>`, then `--set-upstream-to=origin/master` —
  **never** a plain `git checkout master`, which would silently rewind C5, C6 and the
  three wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-04 (scheduled cycle, 5th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`d206580`** (the 4th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `d206580` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty. All Checkpoint B artefacts present and unmodified
  (`backtest/results/c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}`,
  the three `docs/figures/c6_dispatch_week_DE-LU_*.png`, and the C1–C5 artefacts
  beneath them: 12 files in `backtest/results/`, 14 in `docs/figures/`, unchanged
  from the 4th wait). Holdout guard re-verified armed (marker-alone-on-a-line count
  **0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`, no `*2025*`
  file anywhere under `data/`); no 2025 data touched. `ENTSOE_API_KEY` not read (not
  needed before C7); no `config/*.yaml` modified, so the config hash is unchanged; no
  push notification sent (the Checkpoint B ping was already sent in C6 — repeat pings
  for the same wait are noise). `data/raw/` did not exist at all again, **NOTE
  C2-02**'s 8th recurrence, but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur, in exactly the shape the 3rd and 4th waits
  recorded: the container arrived detached at `d206580` with the local `master` *ref*
  stale at `fc422de` (5 commits behind HEAD) — now **13 recurrences out of 19
  containers**. Reattached with `git checkout -B master d206580` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C5, C6 and the four wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-04 (scheduled cycle, 6th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`98d4fae`** (the 5th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `98d4fae` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`, unchanged from the 5th wait). Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. `ENTSOE_API_KEY` not read (not needed before C7); no `config/*.yaml`
  modified, so the config hash is unchanged; no push notification sent (the
  Checkpoint B ping was already sent in C6 — repeat pings for the same wait are
  noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s 9th recurrence,
  but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–5th waits: the
  container arrived detached at `98d4fae` with the local `master` *ref* stale at
  `fc422de` (6 commits behind HEAD) — now **14 recurrences out of 20 containers**.
  Reattached with `git checkout -B master 98d4fae` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C5, C6 and the five wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-05 (scheduled cycle, 7th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`78fbba5`** (the 6th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `78fbba5` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`, unchanged from the 6th wait). Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  10th recurrence, but nothing was re-downloaded because no work needed data.
- **NEW, and the one thing that changed outside the repo: `ENTSOE_API_KEY` is now
  set in the cloud environment.** Every prior cycle recorded it as absent, and
  PLAN.md's "ENTSO-E API key note" still describes it as not yet available to cloud
  routine cycles. It is now present. This cycle did **not** read, use, or log its
  value, and made no ENTSO-E request — C7 is the first cycle that needs it, and C7 is
  blocked behind this checkpoint. Consequence for whoever closes Checkpoint B: the
  C7 fallback path ("flag it and do Tier-B / Energy-Charts-only work instead") looks
  **unnecessary** — C7 can run its full intended scope. Worth re-confirming the key
  is still set at the start of C7 rather than trusting this note, since the
  environment is configured outside the repo and can change between cycles.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–6th waits: the
  container arrived detached at `78fbba5` with the local `master` *ref* stale at
  `fc422de` — now **15 recurrences out of 21 containers**. Reattached with
  `git checkout -B master 78fbba5` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C5, C6 and the six wait commits out of the working tree. Correction to the arithmetic
  in the 3rd–6th wait entries: the stale `master` ref is **12** commits behind HEAD
  here (`git rev-list --count master..HEAD`), not the 5–6 those entries reported —
  they appear to have counted only the wait commits, not C3–C6 and the Checkpoint A
  close beneath them. The reattach procedure is unaffected; the stakes of getting it
  wrong are simply larger than those entries implied.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-05 (scheduled cycle, 8th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`888347f`** (the 7th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `888347f` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}`,
  the three `docs/figures/c6_dispatch_week_DE-LU_*.png`, and the C1–C5 artefacts
  beneath them: 12 files in `backtest/results/`, 14 in `docs/figures/`, all 26
  git-tracked and clean, unchanged from the 7th wait). Holdout guard re-verified
  armed (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  11th recurrence, but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — the 7th wait's
  observation holds for a second consecutive container, so it looks like a durable
  environment change rather than a one-off. Presence only was tested (`-n` on the
  variable); the value was not read, logged, or used, and no ENTSO-E request was
  made. C7 remains the first cycle that needs it, and C7 is blocked behind this
  checkpoint; still re-confirm at the start of C7 rather than trusting this note.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–7th waits: the
  container arrived detached at `888347f` with the local `master` *ref* stale at
  `fc422de` — now **16 recurrences out of 22 containers**. The stale ref is **13**
  commits behind HEAD here (`git rev-list --count master..HEAD`), consistent with the
  7th wait's corrected count of 12 plus that wait's own commit. Reattached with
  `git checkout -B master 888347f` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C3–C6, the Checkpoint A close and the seven wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-05 (scheduled cycle, 9th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`2e60b70`** (the 8th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `2e60b70` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean, unchanged from the 8th wait),
  including `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the
  three `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  12th recurrence, but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — third consecutive
  container, so the durable-environment-change reading from the 7th and 8th waits
  continues to hold. Presence only was tested (`-n` on the variable); the value was
  not read, logged, or used, and no ENTSO-E request was made. C7 remains the first
  cycle that needs it, and C7 is blocked behind this checkpoint; still re-confirm at
  the start of C7 rather than trusting this note.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–8th waits: the
  container arrived detached at `2e60b70` with the local `master` *ref* stale at
  `fc422de` — now **17 recurrences out of 23 containers**. The stale ref is **14**
  commits behind HEAD here (`git rev-list --count master..HEAD`), consistent with the
  8th wait's 13 plus that wait's own commit. Reattached with
  `git checkout -B master 2e60b70` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C3–C6, the Checkpoint A close and the eight wait commits out of the working tree.
- No virtualenv exists in a fresh container (`.venv/` is gitignored and not rebuilt);
  the guard check above ran against the system `python3`, which already has the
  imports `data.holdout` / `data.config` need. C7 will need to create the venv and
  install `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-06 (scheduled cycle, 10th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`3639e3a`** (the 9th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `3639e3a` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean, unchanged from the 9th wait),
  including `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the
  three `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  13th recurrence, but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — fourth consecutive
  container, so the durable-environment-change reading from the 7th–9th waits
  continues to hold. Presence only was tested (`-n` on the variable); the value was
  not read, logged, or used, and no ENTSO-E request was made. C7 remains the first
  cycle that needs it, and C7 is blocked behind this checkpoint; still re-confirm at
  the start of C7 rather than trusting this note.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–9th waits: the
  container arrived detached at `3639e3a` with the local `master` *ref* stale at
  `fc422de` — now **18 recurrences out of 24 containers**. The stale ref is **15**
  commits behind HEAD here (`git rev-list --count master..HEAD`), consistent with the
  9th wait's 14 plus that wait's own commit. Reattached with
  `git checkout -B master 3639e3a` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C3–C6, the Checkpoint A close and the nine wait commits out of the working tree.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, which already has
  the imports `data.holdout` / `data.config` need. C7 will need to create the venv and
  install `requirements.txt` before any modelling work.
- **Elapsed-wait note, for the human's benefit rather than as an escalation:** this
  is the **10th consecutive wait cycle**, and Checkpoint B was reached **2026-10-02**
  — roughly **4 days** and ~3.3 days of scheduled fires with the status line
  unchanged. Nothing is wrong and nothing is lost: C3–C6 are committed and pushed,
  every artefact is intact, and the project simply cannot advance past this gate
  without the human. But the remaining budget is now the binding constraint —
  **C7–C21 is 15 cycles of work and the plan's own buffer note assumed 3–4 lost
  cycles, which 10 waits has already more than spent.** If the review cannot happen
  soon, the human may want to consider either approving C7 provisionally (the five
  Checkpoint B items are all non-blocking by their own descriptions — none of the
  three FLAG C5-01 options changes a conclusion) or explicitly cutting C14 and the
  stretch items per PLAN.md's buffer rule. **This cycle is not making that call and
  is not acting on it** — it is recorded here only so the trade-off is visible at
  review time. Still no push notification, per the status line's own instruction.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-06 (scheduled cycle, 11th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. **No human commits since the 10th wait** — after
  `git fetch origin master`, `HEAD` == `master` == `origin/master` == **`0108407`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6).
  `data/raw/` did not exist at all again — **NOTE C2-02**'s 14th recurrence — but
  nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — fifth consecutive
  container. Presence only was tested (`-n` on the variable); the value was not read,
  logged, or used, and no ENTSO-E request was made. Still re-confirm at the start of
  C7 rather than trusting this note.
- **The detached-HEAD trap did NOT recur this container**, the first time since the
  2nd wait: the container arrived already attached to `master` at `0108407`, matching
  `origin/master`, so no `git checkout -B` reattachment was needed. Running tally is
  therefore **18 recurrences out of 25 containers** (unchanged count, one more
  container). Future cycles should still check `git rev-parse --abbrev-ref HEAD` and
  `git rev-list --count master..HEAD` before any `git checkout master`.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`. C7 will need to
  create the venv and install `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file, plus
  the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21 is 15 cycles
  and the plan's 3–4-cycle buffer is more than spent) still stands and is **not**
  re-escalated here. C7 stays blocked until a human replaces the status line with
  **C7** and records the approval here.

### Checkpoint B wait — 2026-10-06 (scheduled cycle, 12th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. This is the **second fire on 2026-10-06** (the 11th wait was
  the first). **No human commits since the 11th wait** — after
  `git fetch origin master`, `HEAD` == `master` == `origin/master` == **`3c86bde`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again — **NOTE C2-02**'s
  15th recurrence — but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — sixth consecutive
  container, so the durable-environment-change reading continues to hold. Presence
  only was tested (`-n` on the variable); the value was not read, logged, or used, and
  no ENTSO-E request was made. Still re-confirm at the start of C7 rather than
  trusting this note.
- The detached-HEAD trap **did** recur this container, after one container without it:
  arrived detached at `3c86bde` with the local `master` *ref* stale at `0108407`, i.e.
  **1** commit behind HEAD (`git rev-list --count master..HEAD`) — the 11th wait's own
  commit. Running tally is now **19 recurrences out of 26 containers**. Reattached
  with `git checkout -B master 3c86bde` after the fetch, then
  `--set-upstream-to=origin/master`. Future cycles should still check
  `git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` before any
  plain `git checkout master`.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, importing
  `data.holdout` from the repo root. C7 will need to create the venv and install
  `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**), plus the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21
  is 15 cycles and the plan's 3–4-cycle buffer is more than spent) still stands and is
  **not** re-escalated here. C7 stays blocked until a human replaces the status line
  with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-07 (scheduled cycle, 13th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. **No human commits since the 12th wait** — after
  `git fetch origin master`, `HEAD` == `origin/master` == **`a69dbcb`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`), and the three
  most recent commits are all this log's own wait commits (`a69dbcb`, `3c86bde`,
  `0108407`), authored by the agent, not a human. `git status --porcelain
  --untracked-files=all` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (12 files in `backtest/results/`, 14 in `docs/figures/`, all
  26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again — **NOTE C2-02**'s
  16th recurrence — but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — seventh consecutive
  container, so the durable-environment-change reading continues to hold. Presence
  only was tested (`-n` on the variable); the value was not read, logged, or used, and
  no ENTSO-E request was made. Still re-confirm at the start of C7 rather than
  trusting this note.
- The detached-HEAD trap recurred this container: arrived detached at `a69dbcb` with
  the local `master` *ref* stale at `0108407`, i.e. **2** commits behind HEAD
  (`git rev-list --count master..HEAD`) — the 11th and 12th waits' own commits.
  Running tally is now **20 recurrences out of 27 containers**. **New this cycle:**
  the usual `git checkout -B master a69dbcb` reattachment was **denied by this
  session's permission classifier** (flagged as irreversible local destruction),
  which it is not — the working tree was clean and the stale `master` ref was a
  strict ancestor of `HEAD`, so the move was a fast-forward. Rather than route around
  the denial, this cycle committed **on the detached HEAD** and pushed with
  `git push origin HEAD:master`, which updates the remote branch without touching the
  local ref. Net effect on the repo is identical; the only residue is that the local
  `master` ref in *this* container stays stale, which is harmless because the
  container is discarded. Future cycles should keep checking
  `git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD`, and may
  need this `HEAD:master` push path if the same denial recurs.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, importing
  `data.holdout` from the repo root. C7 will need to create the venv and install
  `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**), plus the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21
  is 15 cycles and the plan's 3–4-cycle buffer is more than spent) still stands and is
  **not** re-escalated here. C7 stays blocked until a human replaces the status line
  with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-07 (scheduled cycle, 14th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. This is the **second fire on 2026-10-07** (the 13th wait was
  the first). **No human commits since the 13th wait** — after
  `git fetch origin master`, `HEAD` == `origin/master` == **`77b1a52`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`), and the four
  most recent commits are all this log's own wait commits (`77b1a52`, `a69dbcb`,
  `3c86bde`, `0108407`), authored by `Claude <noreply@anthropic.com>`, not a human.
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again — **NOTE C2-02**'s
  17th recurrence — but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — eighth consecutive
  container, so the durable-environment-change reading continues to hold. Presence
  only was tested (`-n` on the variable); the value was not read, logged, or used, and
  no ENTSO-E request was made. Still re-confirm at the start of C7 rather than
  trusting this note.
- The detached-HEAD trap recurred this container: arrived detached at `77b1a52` with
  the local `master` *ref* stale at `0108407`, i.e. **3** commits behind `HEAD`
  (`git rev-list --count master..HEAD`) — the 11th, 12th and 13th waits' own commits.
  Running tally is now **21 recurrences out of 28 containers**. Following the 13th
  wait's note, this cycle did **not** attempt `git checkout -B master` (denied there
  by the session's permission classifier) and instead committed on the detached `HEAD`
  and pushed with `git push origin HEAD:master`, which updates the remote branch
  without touching the local ref. Net effect on the repo is identical; the stale local
  `master` ref is harmless because the container is discarded.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, importing
  `data.holdout` from the repo root. C7 will need to create the venv and install
  `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**), plus the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21
  is 15 cycles and the plan's 3–4-cycle buffer is more than spent) still stands and is
  **not** re-escalated here. C7 stays blocked until a human replaces the status line
  with **C7** and records the approval here.

### Checkpoint B — approved and closed — 2026-10-07 (human instruction, local assistant session, not a scheduled cycle)

**Approved by:** J., 2026-10-07, who instructed the local assistant session to
"approve as is so it can move forward". Recorded faithfully: this is an approval
of the current state **without an itemised review** — J. did not report
eyeballing the three C6 week figures or re-deriving the headline numbers in this
session. Checkpoint D (C19) still requires the human to hand-check three numbers
and verify the surprising finding, so the numbers get a human read before
anything is published.

**How each open item was resolved ("as-is" = keep current committed behaviour):**
- **Headline (87–92% capture, DE-LU 2024):** accepted as the working result.
- **FLAG C5-01:** option **(b)** — pure LP stays the default; the simultaneous
  charge/discharge artefact is carried as a stated limitation in the C18 write-up,
  quoting the C6 evidence (MILP capture 0.9203 vs LP 0.9187).
- **NOTE C4-02:** confirmed — the declined hour's day stays excluded and reported.
- **NOTE C3-01:** keep the `lag_24h` names; `docs/forecast_harness.md` stays the
  documentation of the actual `D-2` window. No config change.
- **NOTE C4-01:** `destroys_skill()` is not re-based; the PLAN.md leakage assertion
  file stays untouched.
- **NOTE C2-02:** no change — cycles keep re-pulling the ~1 MB DE-LU cache.

**Next:** C7 (ENTSO-E client + D-1 load / wind / solar forecasts for Tier-A zones).
`ENTSOE_API_KEY` was observed set from 2026-10-05; re-confirm at the start of C7.
No code, config, data or holdout state was touched by this entry.

### C7 — 2026-10-07 (scheduled cycle) — ENTSO-E client + Tier-A exogenous forecasts

Scope per PLAN.md C7: `ENTSOE_API_KEY` is configured, so the full intended scope ran
— ENTSO-E client, D-1 load forecast (Art. 6, safe) + D-1 wind/solar forecast
(Art. 14, FLAGGED) for the three Tier-A zones, and extend manifest/contracts. No
Tier-B fallback was needed. No modelling: C7 fetches, validates, describes and
contracts this data; **no model consumes it yet**, which is C8's work alongside the
RES-degradation sensitivity PLAN.md requires in the same cycle.

**Pulled and cached (18/18 pairs, 0 FLAGs on the final run):** DE-LU, ES, NO2 ×
{A65/A01 day-ahead total load, A69/A01 day-ahead wind+solar} × 2022-2024. 2019-2021
are refused *in code* (`exogenous_available_from_year: 2022`) — the platform answers
for them, but PLAN.md records that no archived D-1 forecast vintage exists there.
~3.5 MB gzipped, gitignored under `data/raw/entsoe/`.

**Built and committed (68 new tests, 339 passing in total):**
- `data/entsoe.py` — the client. Config-driven document specs; A03/A01 curve
  expansion; `Acknowledgement_MarketDocument` → `UnexpectedResponse` with its Reason
  code; 4xx never retried, 429/5xx/transport retried 3× at 5/15/45s; nothing
  unvalidated ever reaches the cache; per-row interval lengths carried out of each
  `<Period>`; the sealed-year assertion described below.
- `data/exogenous.py` — stitching loader + hourly aggregation + derived
  `residual_load_forecast_mw`. The FLAGGED status travels on `attrs`.
- `data/exog_manifest.py` + `data/build_exog_manifest.py` — 35-column manifest, one
  row per (zone, document, series, year), carrying `leakage_status`.
- `data/exog_contracts.py` + `data/build_exog_contracts.py` — the contract layer.
- `data/fetch_exogenous.py` — the fetch CLI (`--dry-run`, per-pair FLAG, exit 4 on a
  missing key without making a request).
- `tests/test_c7_entsoe.py` — 68 offline tests. No network, no real payload, no
  sealed year; the holdout tests assert the guard *fires*.
- `docs/entsoe_layer.md` — the full write-up of everything below.

**No frozen file was edited.** `tests/` gained one new file and no existing test was
modified; `data/contracts.py` and `forecast/leakage.py` were not touched. PLAN.md's
C7 line says "extend manifest/contracts", and CLAUDE.md forbids editing a
data-contract or leakage-assertion file without flagging and stopping, so the
extension is **additive**: `data/exog_contracts.py` imports and reuses the C2
primitives (`gap_report`, `check_utc_day_counts`, `check_local_day_counts`,
`dst_transition_days`, `modal_resolution_seconds`, …) rather than changing them, and
`data/exog_manifest.py` sits beside `data/manifest.py` rather than inside it.
`data/aggregate.py` is likewise untouched — see FINDING C7-B.

**All exogenous contracts hold.** All 12 (zone, series) reports `ok`, 0 negative
values in any load/wind/solar series, every index UTC and strictly monotonic with no
duplicates.

#### FINDING C7-A — `curveType A03`: sparse positions with block semantics. RESOLVED.

Every response the platform returned is `curveType A03`, a *variable-sized block*
curve: positions are **sparse**, and an omitted position means "the previous point's
value still holds". Real DE-LU solar, 2024-01-01 at PT15M, is
`position 1 → 0`, then `position 29 → 52.58`, with 2-28 absent and meaning *zero*.
Parsing position-by-row would have produced a 26-row "day" full of holes; parsing
positions as a dense index would have shifted every value after each block. NO2's
solar forecast for a whole year is a **single point of `0.0`**, which is only
correct under A03. `expand_points` implements the semantics; the tests pin it against
hand-computed sparse curves. A missing position 1 raises rather than guessing the
leading block.

#### FINDING C7-B — ES changed resolution mid-2022. RESOLVED.

DE-LU and NO2 publish at a single resolution (PT15M and PT60M), but **ES switched
PT60M → PT15M on 2022-05-23T00:00Z**. `data/aggregate.py`'s `to_hourly` documents a
single input resolution and takes the modal one, so over the stitched ES series it
treated the entire PT60M stretch — **3408 hours of real data** — as partial hours and
NaN'd them. Two knock-on errors in the first manifest build: ES 2022 read as **70.8%
covered** with **3409 gaps**, when it has one real missing hour.

Fixed without touching `data/aggregate.py` (it holds the C2 aggregation method and
its tests): each row's **true** interval length is now carried out of its own
`<Period>` as `attrs['interval_seconds']`, and `data/exogenous.py` splits the series
into maximal runs of constant resolution, handing each to `to_hourly` separately —
which is exactly the uniform input that function is specified for. A delta-based
guess cannot do this: the row before a one-hour hole in a PT15M series has a 4500s
forward delta, indistinguishable from a resolution change. The manifest now measures
coverage as *time covered / time in the year* and counts a gap as a step longer than
the **preceding row's own** interval. ES 2022 now reads **99.9886% covered, 1 gap**,
and ES load's NaN count went 3408 → **0**.

#### FINDING C7-C — autumn-DST-day publication gaps. REPORTED, not filled.

The German and Spanish day-ahead publications each **drop one hour at the autumn DST
boundary**, at the first hour of the 25-hour local day. DE-LU 2023-10-28 and
2024-10-26: the onshore-wind (B19) and solar (B16) series split into two Periods
around a missing `22:00Z-23:00Z` while offshore wind (B18) runs straight through. ES
2022-10-30: the same hour missing from both documents.

This is a structural property of these publications, not a one-off, and belongs in
the write-up's Limits section. Complete list of every source gap found (worst case
~0.4% of a zone-year, all reported, none filled):

| Zone / document | Missing | What it is |
|---|---|---|
| DE-LU load | 2022-02-22, 2022-03-24 | 24h each — two whole local days absent |
| DE-LU load | 2023-10-28, 2024-10-26 | 1h each — autumn DST long day |
| DE-LU wind & solar | 2023-10-28, 2024-10-26 | 1h each, NaN — partial psrType, same hour |
| ES (both documents) | 2022-10-30 | 1h — autumn DST long day |
| ES solar | 2024-12-07 … 12-11 | 120h NaN — partial psrType coverage |
| ES wind | 2024-06-02 | 24h NaN — partial psrType coverage |
| NO2 wind & solar | 2022-11-01 … 11-02 | 48h — two whole local days absent |

An intermediate version of the parser **raised** on the DE-LU case, which cost a
whole training year for four intervals. That was the wrong granularity: CLAUDE.md
says to flag a source anomaly and skip only the *dependent* work, and this project's
standing rule (`data/prices.py`) is that a gap stays a gap and gets reported rather
than filled. The four intervals are now NaN, counted on `attrs`, and surfaced in both
committed artefacts. NaN cannot be mistaken for a real low-wind hour; zero could.

#### FINDING C7-D — NO2 offshore wind is an all-zero stub. RESOLVED by a checkable rule.

`wind_forecast_da_mw` is `B18 + B19` (offshore + onshore), and two cases pull in
opposite directions:
- **DE-LU**: the absent onshore component is worth tens of GW → the sum must be NaN.
- **NO2**: offshore B18 is published for just **48 hours of 2022 and 192 of 2024**,
  absent from 2023 entirely, and is **`0.0` at every single published point**. NO2 has
  no offshore fleet; the TSO emits an occasional all-zero stub. Treating that absence
  as NaN wiped out the wind feature for a whole Tier-A zone for ~8600 hours/year.

Resolved by a rule the **data decides**, not the zone: a component that is
*identically zero wherever it is published* is not a fleet, so its absence
contributes zero. Asserted against the payload rather than assumed, and recorded in
`attrs['zero_components']` and the contract report so a human can overrule it. NO2
wind is now complete; DE-LU's four DST intervals correctly stay NaN. Both directions
are pinned by tests.

#### FINDING C7-E — negative residual load is the signal, not a defect. RESOLVED.

The first contract run failed `residual_load_forecast_mw` for 262 negative hours
(DE-LU) and 317 (ES). Those are **real and are the point**: residual load =
load − wind − solar goes negative exactly when renewables exceed demand, which is the
condition that produces negative day-ahead prices and the subject of PLAN.md's C14
fundamentals chapter. DE-LU's first is 2022-03-20T11:00Z, a sunny windy Sunday
midday. Flagging it would have flagged the signal itself. Non-negativity is now
config-driven per series (load/wind/solar: a negative value is a source defect) with
residual load the deliberate, documented exception.

**The contract dividing line, now stated once in `data/exog_contracts.py`:**
*integrity* findings are violations (non-UTC or non-monotonic index, duplicate
timestamps, a negative value in a quantity that cannot be negative, or a day with
*more* rows than expected — which can only be a bug of ours); *completeness* findings
are reported notes (gaps, NaNs, a day with *fewer* rows than expected). A shortfall
and a gap are the same fact counted twice, which is why only one is a failure.

#### Sealed-holdout guard strengthened

ENTSO-E's `periodEnd` is the **exclusive** window end, so fetching year `Y` must name
`(Y+1)-01-01T00:00Z` — verified in C7 as the only complete spelling (an end of
`Y-12-31T23:00` returns 92 of that day's 96 quarter-hours). Naming that boundary is
not an observation of `Y+1`, but rather than rely on the argument, `parse_document`
now asserts **positively** that no parsed timestamp falls in a sealed year. If the
platform ever returned a point past the boundary while fetching 2024, it raises
instead of caching. The ordinary `assert_not_sealed` guard still runs before any
request and before any cached read, and a test asserts the new check fires.

#### Token hygiene

ENTSO-E authenticates with a `securityToken` **query parameter**, so unlike
Energy-Charts the request URL is itself a secret. `data.entsoe.redact` strips both the
literal token and any `securityToken=...` parameter, and is applied to every stored
provenance record, every exception message and every CLI FLAG line (including
transport errors that quote the URL). `document_request()` returns params *without*
the token; it is added only at request time. `api_key_is_set()` tests presence only.
Tests assert the token appears in no cached metadata and in no raised message.

#### Plausibility eyeball (first exogenous numbers in the project)

DE-LU load 30.9-76.5 GW (peak ~80 GW ✓), wind 0.2-50.4 GW (record ~50 GW ✓), solar
0-48.6 GW (record ~48-50 GW ✓), residual load **-13.6** to 68.7 GW (negative at
sunny/windy midday ✓). ES load 16.8-38.7 GW (peak ~40 GW ✓), wind 0.3-19.8 GW,
solar 0-21.2 GW. NO2 load 2.1-6.4 GW, wind 0-1.3 GW (onshore ~1.5 GW ✓), solar
identically 0 (no fleet ✓).

#### LP invariants

C7 touched no dispatch, forecast or backtest code, so the battery-LP invariants do
not apply to any new artefact. They remain executable and green as part of the full
suite: `assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` all pass
(339 tests, 0 failures). No LP objective from a forecast-priced solve is reported
anywhere as a realised value.

#### NOTE C7-01 — one open question for a human (presentation, not a blocker)

`config/features.yaml` names the exogenous features `load_forecast_da`,
`wind_forecast_da`, `solar_forecast_da`, `residual_load_forecast`; the columns this
cycle produces are the same names with a `_mw` suffix (`load_forecast_da_mw`, …),
because the unit matters once three series in MW sit beside prices in EUR/MWh. The
suffix is declared in `config/data.yaml` under `sources.entsoe.documents.*.series`,
so nothing is ambiguous in code, but the two config files now spell the same feature
two ways. Options: (a) keep both spellings and let `docs/entsoe_layer.md` be the
mapping — the same resolution a human already chose for **NOTE C3-01**; (b) rename
the `config/features.yaml` entries to carry `_mw`. **Not done either way**, because
`config/features.yaml` is a feature contract and C8 is the cycle that actually
consumes it. Proceeding as (a) unless a human says otherwise; this does not block C8.

**Next:** C8 — exogenous features into LEAR for Tier A, plus the RES-forecast
degradation sensitivity (as-published vs persistence-degraded) as a first-class
experiment. C8 must read the gap/NaN notes in
`data/manifest/exogenous_contract_report.json` before building these columns in: the
FLAGGED Art. 14 vintage is only usable alongside that sensitivity, and ~0.4% of
hours are NaN by design.

### C8 — 2026-10-08 (scheduled cycle) — exogenous features into LEAR + the RES vintage premium

Scope per PLAN.md C8: exogenous features into LEAR for Tier A, plus the
RES-forecast degradation sensitivity (as-published vs persistence-degraded) as a
first-class experiment. Both done, for all three Tier-A zones. No checkpoint, no
blocker, no FLAG raised. `ENTSOE_API_KEY` is set and was used only to re-populate
the cache (see "Cache re-pull" below).

#### The headline finding — FINDING C8-A: the vintage, not the information

`config/features.yaml` has marked the Art. 14.1.D wind/solar forecast **FLAGGED**
since C1 because it is published at 18:00 local on D-1, *after* the 12:00 gate
closure the model is predicting. C8 turns that from a caveat into a measurement by
running the same LEAR four times per zone over the same rows, changing only which
exogenous columns are present and at which **vintage**:

| Arm | Columns added | Vintage | Leak-free? |
|---|---|---|---|
| `price_only` | — | — | yes (C4's feature set) |
| `load_only` | `load_forecast_da_mw` | target day's own (public 10:00 D-1) | **yes** |
| `res_persistence` | `+` wind, solar, residual load | the vintage published 24h earlier | **yes** |
| `res_as_published` | `+` wind, solar, residual load | target day's own (public 18:00 D-1) | **no — acknowledged** |

2024 validation year, MAE/RMSE in EUR/MWh, scored on the **common hours** (the
hours every arm predicted), LEAR at C4's committed spec, refit daily, every arm
training from 2022-01-01:

| Arm | DE-LU MAE | RMSE | ES MAE | RMSE | NO2 MAE | RMSE |
|---|---|---|---|---|---|---|
| `naive_last_week` | 32.799 | 55.219 | 27.316 | 38.135 | 21.195 | 41.758 |
| `price_only` | 23.525 | 37.416 | 18.126 | 24.075 | 14.737 | 26.894 |
| `load_only` | 23.715 | 37.425 | 18.015 | 23.992 | 14.746 | 26.915 |
| `res_persistence` | 23.588 | 37.199 | 17.930 | 23.892 | 14.817 | 26.938 |
| `res_as_published` *(late)* | **21.610** | **32.699** | **15.906** | **20.650** | 14.809 | 26.273 |

| Zone | Capturable gain (`load_only − price_only`) | Vintage premium (`as_published − persistence`) |
|---|---|---|
| DE-LU | **−0.19** EUR/MWh (−0.81% of MAE) | **+1.98** EUR/MWh (**+8.39%**) |
| ES | **+0.11** EUR/MWh (+0.61%) | **+2.02** EUR/MWh (**+11.28%**) |
| NO2 | **−0.01** EUR/MWh (−0.06%) | **+0.01** EUR/MWh (+0.06%) |

**At an honest vintage the entire ENTSO-E exogenous block is worth nothing** —
between −0.8% and +0.7% of MAE, in all three price-formation regimes. Fed the
as-published Art. 14 archive, the *same columns in the same model* buy 8-11% of
MAE in the two RES-exposed zones. So a backtest that uses the archived Art. 14
forecast without this split reports roughly a tenth of its MAE improvement as
skill when it is a publication timestamp. That is the write-up's surprising
finding arriving at C8 instead of C15, and it is a finding *about the literature's
standard data source*, which makes it the most portfolio-relevant thing the
project has produced so far.

Three supporting observations, all in the committed summaries:

- **RMSE moves more than MAE.** `res_as_published` improves RMSE by 12.6% (DE-LU)
  and 14.2% (ES) against 8.4% and 11.3% on MAE. RES forecast information mostly
  kills the *large* errors — high-wind, negative-price hours — which MAE
  under-weights and which are exactly the hours a battery earns in. The vintage
  premium should therefore be **larger** in captured-value terms than it looks
  here. C11/C12 measure that; C8 does not guess at it.
- **History beats features.** Aligning every arm to the 2022 exogenous start costs
  `price_only` +0.66 (DE-LU), +0.26 (ES) and +1.10 (NO2) EUR/MWh of MAE against
  C4's full 2019+ window. Three extra years of *price history* is worth several
  times the whole exogenous block at an honest vintage. C4's DE-LU number
  (MAE 22.864) reproduced exactly as the `full_history_reference` row, which also
  re-verifies the C4 pipeline end to end on a freshly re-pulled cache.
- **NO2 shows nothing in either direction**, which is the control that makes the
  other two credible. A hydro zone with ~1.3 GW onshore wind, no solar fleet and
  reservoir-set prices has nothing for a RES forecast to explain at any vintage —
  a method that invented a premium there would be measuring its own machinery.

#### FINDING C8-B — the MAE ladder is not monotone for DE-LU and NO2

Each arm's information set contains the previous arm's, so MAE was expected to be
non-increasing along the ladder. It is for ES (`mae_monotone_non_increasing: true`)
and **is not** for DE-LU or NO2: `load_only` and `res_persistence` land
fractionally *above* `price_only` (−0.19 and −0.06 EUR/MWh respectively on DE-LU).

Reported, not smoothed — the runner carries the flag in every summary. The reading
is that these columns buy nothing a LASSO can use once the price lags are present
(the day-ahead load forecast is largely a restatement of the daily and weekly cycle
`price_lag_24h`/`price_lag_168h` already carry) and so cost a little in parameters.
A finding about the features, not a defect in the plumbing — and ES, where solar
genuinely sets the midday price, is monotone. **No action taken**: dropping the
column, or widening the model to rescue it, would be tuning against a visible
validation metric, which PLAN.md forbids.

#### FINDING C8-C — the persistence offset is itself late on the autumn DST day

The 24-hour degradation offset is applied by explicit UTC-instant reindexing, and
its information time is then read back off the publication clock rather than
assumed safe. On the autumn DST day that matters: the local market day has **25**
hours, so its last hour minus 24 hours is its own *first* hour, whose RES forecast
was published at 18:00 on D-1 — after the gate. The guard catches exactly those
rows and the mask blanks them.

NO2 and ES blank all three such days (2022-10-30, 2023-10-29, 2024-10-27). DE-LU
blanks only **2022-10-30**, because for 2023 and 2024 the source hour is already
NaN — and it is already NaN for a reason: FINDING C7-C recorded that DE-LU's wind
and solar publications drop the hour `22:00Z-23:00Z` on 2023-10-28 and 2024-10-26,
and *that hour is the long day's first local hour*. The two findings describe the
same hour from opposite ends. Nobody would have special-cased this; the clock
arithmetic found it, and it is pinned by a test.

#### How the late arm is allowed to run at all

`res_as_published` is the only place in this repo where a post-gate-closure column
reaches a model, and the door is deliberately narrow.

- The three leak-free arms get nothing special: late cells are blanked by
  `forecast.leakage.mask_unavailable` exactly as C3 blanks a late price lag, and
  the **unmodified** `assert_no_leakage` then has to pass clean.
  `test_leak_free_variants_pass_the_plain_guard` asserts it.
- For the late arm, `assert_only_acknowledged_leakage` replaces the plain guard and
  permits a violation only if its column was named in advance, its kind is
  `after_gate_closure`, **and** its worst lateness equals what the declared
  publication clock predicts to the minute. It also refuses a *silent*
  acknowledgement. Measured on all three zones: exactly 3 acknowledged columns,
  worst lateness exactly 6h, on 26 158-26 301 rows each — nothing else anywhere.
- That check is **stricter** than the plain guard on that matrix, not weaker: it
  pins the leak's shape instead of tolerating one, and a genuine leak in a price
  lag cannot hide behind the RES acknowledgement (asserted by
  `test_acknowledgement_refuses_an_unrelated_leak`, plus four more refusal tests).
- The harness's per-fold check is skipped for that one arm only
  (`check_leakage=False`, the same door `backtest/diagnostics.py` already uses for
  the deliberate misalignment experiments) and replaced by one pass over the whole
  arm matrix, which implies it: the guard is a per-(row, column) predicate, so a
  violation in any subset is a violation of the whole.
  `test_the_whole_matrix_check_implies_every_row_subset_s` asserts that on real
  subsets rather than arguing it. Sealed-year refusal and the "training targets
  must be public" guard are untouched and run on every fold of every arm.
- `test_a_leading_res_column_is_worth_a_lot_to_lear` measures what the guard is
  protecting: a wind column derived from the target hour's own price more than
  halves MAE. The guard is not defending a technicality.

#### The publication clock moved from a comment into config

C7 recorded "published 18:00 on D-1" in a `leakage_note:` prose field. A comment
cannot be checked. C8 adds, beside each document in `config/data.yaml`:
`publication_tz: Europe/Brussels`, and per document `published_day_offset: -1`
with `published_local: "10:00"` (A65) / `"18:00"` (A69). The Art. 6.1.B time is
the **latest** instant the regulation permits (2h before gate closure), not a
typical one — a guard built on an optimistic publication time would pass a column
a bidder was still waiting for. `test_the_declared_clock_is_what_makes_the_leak_visible`
pins both numbers against the gate convention, so a later edit to either is caught
rather than quietly re-basing the experiment.

#### Three design choices that were easy to get wrong

- **The residual-load column is derived *after* degradation.** Under
  `res_persistence` a bidder holds the load forecast for D *and* the RES forecast
  for D-1, so their best residual-load estimate is
  `load(t) − wind(t−24h) − solar(t−24h)`, which is what is built. Lagging C7's
  already-derived residual column by 24h instead would discard the load forecast
  they did hold. Its information time is the element-wise **maximum** of its three
  inputs' — a derived value is knowable only once its last input is.
- **Every arm trains from the same day.** The exogenous series start in 2022 and
  LEAR drops a training row with any missing design cell, so an exogenous arm on a
  2019-start expanding window would silently train on 2022+ while `price_only`
  trained on 2019+, making the comparison partly "more features" and partly "less
  history". All four arms run from `2022-01-01`; `price_only` is *additionally* run
  on the full history as a labelled `full_history_reference`, which is not part of
  the ladder.
- **The arms are compared on hours every arm predicted.** The committed LEAR
  declines an hour whose design has a hole, and the exogenous columns bring
  FINDING C7-C's source gaps with them (ES loses 193 hours this way — chiefly the
  120-hour December 2024 solar gap). Each arm's own scores are reported *and* a
  `common_hours` block re-scores every arm on the intersection; the degradation
  table is computed from the latter. Both are in the summary, neither is hidden.

#### Built and committed (42 new tests, 381 passing in total)

- `forecast/exog_features.py` — the four variants, the publication clock, the
  vintage offsets, the derived-after-degradation residual load, the masking split
  and `assert_only_acknowledged_leakage`.
- `backtest/run_c8_exogenous.py` — the CLI: four arms × three zones, the
  common-hours table, the degradation table, the monotonicity flag, the
  full-history reference.
- `tests/test_c8_exogenous_features.py` — 42 offline tests. No network, no cached
  file, no sealed year.
- `docs/exogenous_model.md` — the full write-up of everything above.
- `backtest/results/c8_exog_{DE-LU,ES,NO2}_2024_{predictions.csv.gz,folds.csv,summary.json}`.
- `config/data.yaml` — the publication clocks (additive; see below).
- `requirements.txt` — a note that C8 adds no dependency.

**No frozen file was edited.** `tests/` gained one new file and no existing test
was modified. `forecast/leakage.py`, `forecast/features.py`, `data/contracts.py`,
`data/aggregate.py` and `config/features.yaml` are **untouched** — verified by
`git diff --stat HEAD` over exactly those paths before committing. The only edit
to an existing file is the additive `config/data.yaml` block above; the
acknowledgement mechanism is built out of `find_leakage` and `mask_unavailable`
rather than by relaxing either.

#### Cache re-pull — NOTE C2-02, 19th recurrence, and a stronger statement than usual

`data/raw/` was empty again (the container does not keep it), so C8 re-pulled 18
(zone, year) price files and 18 (zone, document, year) ENTSO-E files. 36/36
succeeded, 0 FLAGs. Then `data.build_exog_manifest` and `data.build_exog_contracts`
were re-run against the fresh cache and diffed against C7's committed artefacts:
of 27 (zone, document, series, year) rows × 35 columns, **the only fields that
differ are `fetched_at_utc` (27 rows) and `gzip_bytes` (24 rows)**. Every
`payload_sha256`, count, coverage figure, gap count, NaN count, negative count and
distribution statistic is **identical**, and the contract report body is byte-identical.
`gzip_bytes` moves by a few bytes because ENTSO-E stamps a fresh random `mRID` into
each response's header, which the series fingerprint correctly ignores.

The regenerated manifest artefacts were therefore **reverted** rather than
committed: they describe the same data, they are correctly labelled `"cycle": "C7"`
with C7's git SHA and config hash, and committing a new timestamp every cycle would
churn the manifest forever with no information gain. The verification above is the
durable record.

#### LP invariants

C8 touched no dispatch, LP or settlement code, so the battery-LP invariants apply
to no new artefact. They remain executable and green as part of the full suite:
`assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` all pass
(381 tests, 0 failures). No LP objective from a forecast-priced solve is reported
anywhere as a realised value. **FLAG C5-01** (simultaneous charge/discharge) is
unchanged and still resolved as option (b) per Checkpoint B.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count
**0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, and no `*2025*` file
exists anywhere under `data/`. Every arm of every zone was evaluated on `[2024]`
only; the exogenous window is 2022-01-01..2024-12-31 and the price window
2018-12-31..2024-12-31. `test_no_arm_can_be_evaluated_against_a_sealed_year`
asserts the new arms inherit the refusal. No 2025 data has been fetched, loaded,
dispatched or computed against at any point in C2-C8.

#### Config hash

**`515d4e8d98887256`** (was `28ebdd1ca5e72913`). It moved because C8 added
`sources.entsoe.publication_tz` and the two `published_*` pairs to
`config/data.yaml`. No other `config/*.yaml` file was modified; in particular
`config/features.yaml` is unchanged, so **NOTE C7-01 stays closed as option (a)** —
the two spellings (`load_forecast_da` there, `load_forecast_da_mw` in the built
columns) remain, and `forecast.exog_features.exogenous_feature_names()` *is* the
mapping, derived from both files rather than written down twice, so a rename in
either surfaces as a failing test instead of as drift.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `bb8e67c` with
local `master` stale 6 commits behind. `git checkout -B master bb8e67c` was
permitted, so no `HEAD:master` push path was needed. **23 recurrences out of 30
containers.** Keep checking `git rev-parse --abbrev-ref HEAD` and
`git rev-list --count master..HEAD` at the start of every cycle.

#### Open question for a human — NOTE C8-01 (presentation, not a blocker)

FINDING C8-A says the honest exogenous block is worth ~0 on MAE for all three Tier-A
zones. PLAN.md's C9 (GBM) and C10 (scale-out) both assume Tier A runs "with exogenous
features". Nothing in C8 contradicts that — a GBM may extract from residual load what
a LASSO cannot, and the capture-ratio metric that actually matters is a spread
metric, not MAE, so the C8 result does not settle the question. **Proceeding as
PLAN.md describes**: C9 and C10 keep the exogenous block for Tier A, and the arm
that goes into the headline results is `res_persistence` (leak-free), with
`res_as_published` carried alongside as the labelled vintage-premium measurement.
If a human would rather Tier A ran `load_only` or price-only until a spread metric
justifies the RES columns, say so and C9 will follow.

**Next:** C9 — GBM, one fixed LightGBM config, in-fold early stopping, Tier A only,
no hyperparameter search. Note that `lightgbm` is not yet in `requirements.txt` and
will need adding. C9 should read FINDING C8-A first: the GBM must be run on the same
four arms (or at minimum on `res_persistence` and `res_as_published`) so the vintage
premium is measured for the non-linear model too rather than inherited from LEAR.

### C9 — 2026-10-08 (scheduled cycle) — the gradient-boosted model, Tier A, on C8's four arms

Scope per PLAN.md C9: GBM, **one fixed LightGBM config, in-fold early stopping, Tier A
only, no hyperparameter search**. Done for all three Tier-A zones. Following the C8
entry's instruction, the booster was run on **all four of C8's exogenous arms** so the
vintage premium is *re-measured* under a non-linear functional form rather than
inherited from LEAR. No checkpoint, no blocker, no FLAG raised. `ENTSOE_API_KEY` is
set and was used only to re-populate the cache (see "Cache re-pull" below).

`lightgbm` was added to `requirements.txt` (installed: **4.7.0**) — the only new
dependency since C5.

#### How the "no hyperparameter search" rule is actually enforced

This is the part of C9 that matters most across cycles, so it is structural rather
than a promise. Validation metrics are visible to every cycle, a booster has a dozen
knobs, and a cycle that nudges one after seeing a 2024 number is overfitting the
validation year *through the agent* — leaving no trace in the diff, because the next
cycle just finds a slightly different literal and no reason to doubt it.

- `forecast.gbm.GbmSpec` is a frozen dataclass. Every value is either a LightGBM
  default or a standard choice stated with its reason in the module docstring; none
  was chosen by looking at a score.
- `GbmSpec.fingerprint()` is a 16-hex hash of every committed value and is written
  into every result row. C9's runs all carry **`a366a760e269bba6`**.
- `test_the_committed_config_is_exactly_what_plan_md_froze` pins all seventeen values
  to literals and `test_the_fingerprint_changes_when_any_knob_changes` pins that the
  hash is sensitive to each. **A later cycle that wants to tune has to edit a test**,
  which CLAUDE.md makes a flag-and-stop event. That is the whole mechanism.

The config: L2 objective, `learning_rate=0.05`, `num_leaves=31`, `min_data_in_leaf=20`,
`feature_fraction=bagging_fraction=0.9`, `bagging_freq=1`, `lambda_l2=1.0`,
`num_boost_round=2000` capped with `early_stopping_rounds=50`, `early_stopping_days=90`,
`refit_on_full_window=True`, `seed=20260101`, `deterministic=True`,
`force_row_wise=True`, `num_threads=4`. `docs/gbm_model.md` tabulates the provenance
of each.

#### Results — all three Tier-A zones, 2024, common hours

Daily refit, expanding window aligned to 2022-01-01, 366 folds per arm, config
fingerprint `a366a760e269bba6`, lightgbm 4.7.0. Scored on the hours every arm of
**both** models predicted (DE-LU 8 782, ES 8 591, NO2 8 783 — ES drops the most,
chiefly FINDING C7-C's 120-hour December 2024 solar gap, which LEAR declines and the
GBM routes natively). MAE/RMSE in EUR/MWh:

| Series | DE-LU MAE | RMSE | ES MAE | RMSE | NO2 MAE | RMSE |
|---|---|---|---|---|---|---|
| `naive_last_week` | 32.791 | 55.213 | 26.958 | 37.513 | 21.192 | 41.757 |
| `gbm_price_only` | 22.787 | 36.339 | 18.348 | 24.354 | 14.035 | 25.907 |
| `gbm_load_only` | 22.749 | 36.085 | 18.376 | 24.472 | 14.005 | 25.846 |
| `gbm_res_persistence` | 22.556 | 35.998 | 18.171 | 24.329 | 14.004 | 25.696 |
| `gbm_res_as_published` *(late)* | **17.151** | **29.077** | **14.932** | **19.572** | **13.517** | **24.625** |
| `lear_price_only` (C8) | 23.525 | 37.416 | 18.126 | 24.075 | 14.737 | 26.894 |
| `lear_load_only` | 23.715 | 37.425 | 18.015 | 23.992 | 14.746 | 26.915 |
| `lear_res_persistence` | 23.588 | 37.199 | 17.930 | 23.892 | 14.817 | 26.938 |
| `lear_res_as_published` *(late)* | 21.610 | 32.699 | 15.906 | 20.650 | 14.809 | 26.273 |

#### FINDING C9-C — the vintage premium is 2-3x LARGER for the booster. Read this before any later cycle reports a GBM number.

| Zone | capturable gain, GBM | **vintage premium, GBM** | vintage premium, LEAR (C8) | ratio |
|---|---|---|---|---|
| DE-LU | +0.16% of MAE | **+23.96%** | +8.39% | **2.9x** |
| ES | −0.15% | **+17.82%** | +11.28% | **1.6x** |
| NO2 | +0.21% | +3.48% | +0.06% | — |

C8 measured the premium with a per-hour LASSO: 8-11% of MAE in the two RES-exposed
zones. Same columns, same vintages, same rows, same folds, under a tree ensemble:
**24% and 18%.** FINDING C8-A therefore does not merely survive a change of
functional form — **the leak is worth two to three times more to a non-linear model.**

The mechanism shows up in the model's own internals, not only in the metric.
Split-gain importance on `residual_load_forecast_mw` (DE-LU, last fold) is **0.033**
under `res_persistence` and **0.236** under `res_as_published` — the booster leans
*seven times harder* on residual load when fed the vintage published after gate
closure. That is what a non-linear model does with a merit-order driver it can
actually trust, and precisely what the honest vintage denies it.

The practical reading is the opposite of reassuring, and it is the sharpest thing
this project has produced so far. On these three zones the booster's advantage over
the LASSO is concentrated almost entirely in the late arm:

| `gbm − lear` MAE (negative favours GBM) | DE-LU | ES | NO2 |
|---|---|---|---|
| `price_only` | −0.738 (−3.1%) | **+0.222 (+1.2%)** | −0.703 (−4.8%) |
| `load_only` | −0.966 (−4.1%) | **+0.361 (+2.0%)** | −0.740 (−5.0%) |
| `res_persistence` | −1.032 (−4.4%) | **+0.241 (+1.4%)** | −0.813 (−5.5%) |
| `res_as_published` *(late)* | **−4.458 (−20.6%)** | −0.974 (−6.1%) | −1.291 (−8.7%) |

On the honest arms there is **no uniform winner**: the GBM wins DE-LU and NO2 by
3-5% and *loses* solar-dominated ES by 1-2%. On the late arm it wins everywhere, and
on DE-LU by 21%. So a published result of the form *"gradient boosting beats LEAR on
a RES-fed day-ahead price model"* may be substantially an artefact of the Art. 14
publication timestamp rather than of the functional form.

**Caveat that must travel with that comparison** (stated in the module docstring, the
runner and `summary.model_comparison.note`): the GBM−LEAR difference is one of
functional form **and** of pooling — LEAR fits 24 models partitioned by delivery
hour, the GBM fits one pooled model with the hour as a categorical feature — and C9
cannot separate the two. The *within-model* vintage premium above is unaffected by
that entanglement, which is exactly why it is the number this cycle can settle and
the model ranking is not.

#### FINDING C9-D — NO2's control holds in ratio but is no longer exactly null

C8's NO2 result was a clean zero in both directions (+0.06% premium), and that is
what made the other two zones credible: a method that invented a premium in a hydro
zone with no solar fleet would be measuring its own machinery. Under the booster
NO2's honest arms stay flat (+0.21%; `price_only`, `load_only` and `res_persistence`
land within 0.03 EUR/MWh of each other) but the premium is **+3.48%**, not zero.

Reported, not smoothed. NO2 carries ~1.3 GW of onshore wind, so same-day wind
information the market had not yet seen is apparently worth a little to a model that
can respond to it non-linearly, even where reservoir opportunity cost sets the price.
The control still carries the finding in *ratio* — 24% and 18% against 3.5%, a 5-7x
gap — but **"the hydro zone shows nothing" is a C8 sentence, not a C9 one**, and the
C18 write-up must use the C9 version.

#### FINDING C9-E — ladder monotonicity flips between models, in all three zones

Each arm's information set contains the previous arm's, so MAE was expected to be
non-increasing along the ladder. FINDING C8-B recorded that it is not, for DE-LU and
NO2 under LEAR. Under the GBM it **is** monotone for DE-LU and NO2 and is **not** for
ES (`load_only` lands 0.028 EUR/MWh above `price_only`) — the flag flips relative to
LEAR in every zone.

That is the strongest available evidence that these fractional non-monotonicities are
noise around zero rather than structure: across 2 models x 3 zones both orderings
occur, which is what to expect if the honest exogenous gain really is ~0 and the sign
of a 0.2% difference is a coin flip. **No action taken** on either — dropping a column
or widening a model to rescue an ordering would be tuning against a visible validation
metric, which PLAN.md forbids.

#### NOTE C8-01, partially answered

C8 asked whether Tier A should keep the exogenous block given that it is worth ~0 on
MAE, and PLAN.md's argument for keeping it was that "a GBM may use residual load where
a LASSO cannot". **Measured: it does, a little, and nowhere near enough to justify the
block on MAE.** The leak-free `res_persistence` arm buys 1.0% of MAE over `price_only`
on DE-LU (22.787 → 22.556) and 1.0% on ES (18.348 → 18.171), where LEAR got −0.8% and
−1.1% respectively; NO2 gets 0.2%. So the booster does extract something honest where
the LASSO extracted nothing, and it is ~1%, not the 8-24% the late vintage buys.

This still does not settle the question, because the metric that decides is a spread
metric and not MAE. **C11/C12 should decide it**, and the right test is whether
`res_persistence` improves the *capture ratio* over `price_only` by more than its 1%
of MAE suggests — RES information mostly kills the large errors (RMSE moves more than
MAE here too), and large errors are concentrated in exactly the high-wind,
negative-price hours a battery earns in.

#### Early stopping did its job, in all 12 runs

Across all 12 (zone, arm) runs of 366 folds each, the chosen round count ranged
**43-624** with medians of 81-139 by arm, and **not one fold of any arm in any zone hit
the 2 000-round cap.** So the round count is genuinely an in-fold choice rather than a
fixed hyperparameter wearing its name. Fitting set 24 119 rows, in-fold stopping set
2 161 rows, on the last fold of every run. NO2 consistently needs more rounds (median
114-139) than DE-LU or ES (81-104) — the kind of thing a per-zone tuning pass would
have "fixed", and which is left alone.

#### Bias — flagged for C11/C12, not acted on

Every arm of every zone is biased **high**: GBM +2.6 to +8.7 EUR/MWh, LEAR +2.6 to
+5.7. This is the shared asinh VST, not a GBM defect — `sinh` is convex, so
back-transforming a conditional-mean estimate in asinh space overshoots in price
space, and the booster inherits the effect LEAR already had (DE-LU `price_only`: GBM
+5.20, LEAR +5.06). The late arm is the most biased because it is the most confident.

Flagged because C11/C12 dispatch against these curves: a roughly *uniform* upward bias
barely perturbs the within-day ordering and spread a battery actually trades on, so the
capture ratio may be far less sensitive to it than the MAE table suggests. That is a
prediction for C11/C12 to test, not a claim made here.

#### Leakage assertion (i) on real prices — decisive in all three zones

| Zone | aligned MAE | one day staler | degradation | `staler_is_worse` |
|---|---|---|---|---|
| DE-LU | 22.786 | 26.104 | **+14.56%** | yes |
| ES | 18.766 | 23.282 | **+24.07%** | yes |
| NO2 | 14.035 | 16.956 | **+20.81%** | yes |

Which is the point of FINDING C9-A below: the assertion has real content on real
prices; it was the synthetic fixture that was vacuous, not the guard.

#### FINDING C9-A — PLAN.md assertion (i) is vacuous for a pooled booster on a periodic series

C3 asserts leakage assertion (i) ("shifting the feature matrix forward one day must
degrade metrics") against `NaiveLastWeek`, which *is* `price_lag_168h`, so misaligning
the matrix necessarily wrecks it. Run the same experiment with the GBM on the same
synthetic week-periodic fixture and the **staler matrix scores better** — MAE 1.716
against 1.759.

Not a bug and not a leak. The pooled booster also holds `hour_of_day_local`,
`day_of_week` and `month`, and on that fixture the price shape is an exact
deterministic function of those three. The lagged prices are a *noisier restatement*
of a signal the calendar gives for free — each lag carries its own copy of the noise
term — so the best available model on that series ignores the lags, and misaligning
them nudges the booster towards doing exactly that. The tell is that the aligned MAE
(1.759) is already within 10% of the 1.596 noise floor no model can beat.

So assertion (i) is only informative on a series where the lagged prices carry
something the calendar cannot. The response was **not to weaken the assertion** but to
put it where it means something, in three places:

1. `test_shifting_the_features_forward_a_day_degrades_the_gbm` runs it on the
   persistence-dominated synthetic series, where it passes decisively.
2. `test_the_day_shift_assertion_is_vacuous_for_this_model_on_a_periodic_series` pins
   the vacuity *and its reason*, so nobody later reads a passing periodic-series shift
   test as evidence of anything.
3. `backtest/run_c9_gbm.py` runs the assertion on each zone's **real prices** at the
   committed config and records it in `summary.day_shift_diagnostic` — which is where
   the assertion is actually established for this model (numbers above).

**`tests/test_c3_leakage_harness.py` is untouched.** Its assertion is about the naive
floor and remains true of it. Nothing was edited to make a red test green; one new
test file was added and the assertion was re-sited onto a fixture where it has content.

#### FINDING C9-B — RETRACTED. It was my hypothesis, and my own test disproved it.

**Recorded in full because the retraction is the useful part.**

The hypothesis: LightGBM's early stopping might not discard the
`early_stopping_rounds` trees built while it discovers the best iteration, in which
case `booster.predict(X, num_iteration=booster.num_trees())` would quietly serve the
exact overfit tail early stopping existed to reject — a nasty bug class, because
nothing about it looks wrong. The model was changed to carry the round count
explicitly, and a test was written to pin the supposed gap.

**The hypothesis is false on lightgbm 4.7.0.** `lgb.train` truncates the booster to
the best iteration: `num_trees() == best_iteration`, and a bare `predict()` already
uses the right trees. Verified directly on a synthetic fit (best_iteration 83,
num_trees() 83, `predict()` identical to `predict(num_iteration=best_iteration)`), and
the original code was therefore never wrong. **The test is what caught it** — it
failed on the first full-suite run with `assert 354 > 354` — which is exactly what a
test pinning a claimed mechanism is for.

What survives: `GbmModel` still passes `num_iteration` explicitly, because the
rollback is a library implementation detail rather than a documented guarantee and the
code should be correct either way, and the fit report still distinguishes
`n_rounds_used` from `n_trees_in_booster`. The test was rewritten as
`test_the_booster_is_rolled_back_to_the_best_iteration`, which pins the behaviour in
the *opposite* direction — so a future LightGBM that stops rolling back surfaces as a
failure here rather than as a silent shift in every result.

**Two pushed commit messages state the retracted version and cannot be rewritten**
(`3388a39` "C9: GBM ... code + tests", which asserts the finding, and the DE-LU/ES
artefact commits, which reference "the fixed code"). The commits' *code* is correct —
it just was not fixing a real bug. This entry is the correction of record; a later
cycle reading those messages should read this paragraph instead. Nothing about the
committed numbers changes: the explicit round count and the implicit one are the same
number on this version, so every C9 result stands as reported.

#### Where early stopping chooses from, and why that is the only forward-looking risk

The round count is the one quantity this model adapts per fold, so it is the one place
a GBM fold could look forward. `early_stopping_split` takes the last
`early_stopping_days` **market days** of the training window as the stopping set and
everything strictly before as the fitting set:

- split by *day*, not by row — half a day on each side would put a row's own near
  neighbours across the split and make the stopping curve optimistic;
- strictly time-ordered, asserted rather than assumed (`ModelError` if not);
- inside the training window, which the harness has already asserted was public at the
  fold's gate closure, so it never touches the test fold.
  `test_early_stopping_uses_only_training_days` checks that against the fold's own day
  sets rather than by reading the code.

With `refit_on_full_window=True` the model is then refit on the *whole* window for the
chosen rounds. The alternative throws away the most recent 90 days — the days most like
the one being predicted — purely as a side effect of having used them to pick a number.
The refit sees those days' targets, which is in-fold model *selection*, not leakage:
every one of them was published before the fold's gate closure.

#### How the late arm is allowed to run at all

Unchanged from C8 and reused rather than reimplemented: `res_as_published` goes through
`forecast.exog_features.assert_only_acknowledged_leakage` over the whole arm matrix,
which permits a violation only if its column was named in advance, its kind is
`after_gate_closure`, and its worst lateness equals what the declared publication clock
predicts to the minute. The harness's per-fold check is skipped for that one arm only
(`check_leakage=False`) and replaced by that one pass, which implies it — the guard is
a per-(row, column) predicate. The three leak-free arms get nothing special and the
**unmodified** `assert_no_leakage` has to pass clean on every fold of each.

`forecast/leakage.py`, `forecast/features.py`, `forecast/exog_features.py`,
`forecast/lear.py`, `data/contracts.py`, `data/aggregate.py` and every `config/*.yaml`
are **untouched** by C9 — verified with `git diff --stat HEAD` over exactly those paths
before committing. The only modified existing file in the whole cycle is
`requirements.txt` (the `lightgbm>=4.3` line).

#### LEAR is read from C8's artefact, not refitted

C8 committed LEAR's predictions for all four arms, per Tier-A zone, for 2024, on the
same aligned 2022-01-01 training window and the same daily-refit spec. Refitting would
spend an hour reproducing a committed number and would quietly allow the two models to
be compared on different folds if any spec drifted. So `load_c8_lear_predictions`
loads the artefact and **asserts** its index and realised prices against this run's
rather than reindexing onto them — a mismatch is a loud failure, not a silent
realignment.

#### Built and committed (51 new tests, 432 in total)

**Test-run record, stated exactly.** The first full-suite run gave **431 passed, 1
failed** — the failure being C9's own new `test_the_overfit_tail_...`, which disproved
FINDING C9-B (see its retraction above). That test was rewritten as
`test_the_booster_is_rolled_back_to_the_best_iteration` and verified passing, and the
full suite was then re-run clean: **432 passed, 0 failed, 51 warnings, 591s** (the
warnings are all pre-existing sklearn LARS convergence notices from the C8 LEAR tests).
That is the run that closes C9.

- `forecast/gbm.py` — `GbmSpec` (the frozen, fingerprinted config), `GbmModel`
  (pooled booster, categorical calendar, LEAR's asinh target VST imported rather than
  re-implemented, native/decline NaN policy, per-fold fit report, split-gain
  importances), `early_stopping_split`, `gbm_factory`.
- `backtest/run_c9_gbm.py` — the CLI: four arms × three zones, the common-hours table,
  both ladders, the GBM−LEAR comparison, the early-stopping report, the real-data
  day-shift diagnostic, and the C8 LEAR-artefact loader with its index/price
  assertions.
- `tests/test_c9_gbm.py` — 51 offline tests. No network, no cached file, no sealed year.
- `docs/gbm_model.md` — the full write-up of everything above.
- `backtest/results/c9_gbm_{DE-LU,ES,NO2}_2024_{predictions.csv.gz,folds.csv,summary.json}`.
- `requirements.txt` — `lightgbm>=4.3`, with the reason for the floor.

#### Three design choices that were easy to get wrong

- **Pooled over delivery hours, not 24 models.** LEAR partitions because a
  ~30-parameter linear model per hour is estimable from ~1 000 rows and pooling would
  force one slope to describe hour 03 and hour 18 at once. A tree ensemble has the
  opposite problem: splitting 24 ways starves all 24 boosters, while one pooled model
  can *learn* the hour interaction where the data supports it. The consequence is
  stated, not hidden, in three places including `summary.model_comparison.note`: **a
  GBM−LEAR difference is a difference of functional form AND of pooling, and this
  cycle cannot separate the two.** The within-model differences — which is what
  FINDING C8-A turns on — are unaffected by that entanglement, which is why the
  vintage premium is the number this cycle can actually settle.
- **The target transform is imported from `forecast.lear`, not copied.** Identical
  `asinh((y−a)/b)` on the in-fold median/MAD, inverted exactly. Copying would let the
  two drift and turn a model comparison into a comparison of loss scales; importing
  makes "identical" a property of the code rather than of a comment. No *feature* is
  transformed — trees are invariant to monotone feature transforms, so LEAR's
  per-column price VST is pointless here and is not used.
- **The categorical set is read from LEAR's own constants.** `CATEGORICAL_FEATURES`
  is built from `forecast.lear.CATEGORICAL_CALENDAR` and `HOUR_KEYS`, so the two models
  cannot drift apart about what is a category and what is a number;
  `test_the_calendar_categoricals_are_the_same_set_lear_encodes` pins it. The codes
  handed to LightGBM are the *values themselves* (hour 0-23, ISO weekday, month 1-12),
  not positions in a fitted level list, so a level the training window never saw cannot
  shift the meaning of another one.

#### LP invariants

C9 touched no dispatch, LP or settlement code, so the battery-LP invariants apply to no
new artefact. They remain executable and green as part of the full suite:
`assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` pass. No LP
objective from a forecast-priced solve is reported anywhere as a realised value.
**FLAG C5-01** (simultaneous charge/discharge) is unchanged and still resolved as
option (b) per Checkpoint B.

#### Cache re-pull — NOTE C2-02, 20th recurrence

`data/raw/` was empty again (the container does not keep it), so C9 re-pulled 18
(zone, year) price files and 18 (zone, document, year) ENTSO-E files for the Tier-A
zones. **36/36 succeeded, 0 FLAGs.** Then `data.build_exog_manifest`,
`data.build_exog_contracts` and `data.build_manifest --zones DE-LU ES NO2` were re-run
against the fresh cache and diffed against the committed artefacts:

- **exogenous manifest** (27 rows x 38 columns): the only fields that differ are
  `fetched_at_utc` (27 rows) and `gzip_bytes` (27 rows). Every `payload_sha256`, count,
  coverage figure, gap count, NaN count, negative count and distribution statistic is
  **identical**.
- **price manifest**, Tier-A rows (18 x 28): the only field that differs is
  `fetched_at_utc`.
- **exogenous contract report**: CSV body byte-identical ignoring timestamps; "all
  exogenous data contracts hold". The JSON differs only in `generated_at_utc`,
  `git_sha` and `config_hash` — the last because the committed report was generated at
  C7, before C8 added the publication clocks.

`gzip_bytes` moves by a few bytes because ENTSO-E stamps a fresh random `mRID` into
each response header, which the series fingerprint correctly ignores. The regenerated
manifest artefacts were therefore **reverted** rather than committed, as in C8:
they describe the same data, they are correctly labelled `"cycle": "C7"`, and
committing a new timestamp every cycle would churn the manifest forever for no
information gain. The 9-zone price contract report was **not** regenerated, because C9
is Tier-A only and doing so would have meant re-downloading the six Tier-B zones for
nothing.

An additional, stronger verification this cycle: `load_c8_lear_predictions` asserts
C8's committed realised prices against C9's freshly-loaded ones per zone, and the
**worst disagreement is 0.0 EUR/MWh in all three zones**. C8's artefact reproduces
exactly on a cache pulled a day later.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count
**0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, and no `*2025*` file exists
anywhere under `data/`. Every arm of every zone was evaluated on `[2024]` only; the
exogenous window is 2022-01-01..2024-12-31 and the price window
2018-12-31..2024-12-31. `test_the_gbm_cannot_be_evaluated_against_a_sealed_year`
asserts the booster inherits the refusal with no door of its own. No 2025 data has
been fetched, loaded, dispatched or computed against at any point in C2-C9.

#### Config hash

**`515d4e8d98887256`** — unchanged from C8. C9 modified no `config/*.yaml` file; the
GBM's configuration lives in `forecast.gbm.GbmSpec` and is tracked by its own
fingerprint (`a366a760e269bba6`) rather than by the config hash, because it is code, not
data-layer config. Verified with `git diff --stat HEAD -- config/` (empty).

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `24e01c6` with local
`master` stale 7 commits behind. **24 recurrences out of 31 containers.** This time
`git checkout -B master 24e01c6` was **denied by the permission classifier** ("Git
Destructive"), so the cycle worked detached and pushed `HEAD:master` throughout, which
was safe only because `origin/master` equalled `HEAD` at session start. **If a future
container arrives detached *and* genuinely behind the remote, that fallback is not
available** — the cycle will need either the `checkout -B` permission or a different
reattachment route, and should flag rather than improvise. Keep checking
`git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the start
of every cycle.

#### Suggestion for C10 (not done here — out of C9's scope)

PLAN.md C10 writes results append-only, "each row tagged with git SHA + config hash".
Add **library provenance** to that row too (at minimum `lightgbm.__version__`): the GBM
fingerprint pins the values *we* set, but everything `GbmSpec.booster_params()` does not
name — `max_cat_threshold`, `min_data_per_group`, `max_depth` — comes from the installed
LightGBM, so a major-version bump that moved a default would change results without
changing the fingerprint. C9's runs used **lightgbm 4.7.0**. Deliberately not bolted onto
C9's summaries after the fact, because the artefacts and the code that produced them
should stay in lockstep.

**Next:** C10 — scale the harness: Tier A (3 models, exogenous features) + Tier B
(naive + LEAR, price-only), results written append-only with each row tagged by git SHA
and config hash. Read FINDING C9-C first: the headline arm for Tier A is
`res_persistence` (leak-free), with `res_as_published` carried alongside **only** as the
labelled vintage-premium measurement, and the GBM's apparent edge over LEAR must never
be quoted from the late arm. Note also that C10's Tier-B scale-out needs the six Tier-B
zones' price cache, which this cycle did not pull (Tier A only).

### C10 — 2026-10-08 (scheduled cycle) — the scale-out: nine zones, one append-only results store

Scope per PLAN.md C10: *"Scale the harness: Tier A (3 models, exogenous features) +
Tier B (naive + LEAR, price-only). Results written append-only, each row tagged with
git SHA + config hash."* Done for all nine zones. No checkpoint, no blocker, no FLAG
raised. No new dependency. `ENTSOE_API_KEY` was **not needed and not read**: C10's
Tier-A rows come from C8's and C9's committed artefacts, and Tier B has no exogenous
block, so the only network traffic this cycle was the 54 Energy-Charts price pulls.

**Full suite: 505 passed, 0 failed, 51 warnings, 624.59s** (432 before C10 + 73 new).
The 51 warnings are the pre-existing sklearn LARS convergence notices from the C8 LEAR
tests. `tests/`, `config/`, `forecast/`, `dispatch/`, `data/contracts.py`,
`data/aggregate.py`, `backtest/walk_forward.py` and `backtest/metrics.py` are
**untouched** — verified with `git diff --stat HEAD` over exactly those paths before
committing. The only modified existing file in the whole cycle is `requirements.txt`
(a comment block recording that C10 added no dependency and why).

#### The headline numbers — all nine zones, 2024, like-for-like

C4's committed LEAR (per-hour LASSO, price-history and calendar features only,
expanding window over the whole cached history) against the naive floor. MAE in
EUR/MWh, each series on its own coverage (LEAR 8 783 hours, naive 8 784 — LEAR declines
the one autumn DST hour whose 24-hour lag the gate-closure mask blanks, FINDING C3-A):

| zone | tier | regime | naive MAE | LEAR MAE | LEAR/naive |
|---|---|---|---|---|---|
| NO2 | A | hydro-dominated | 21.195 | 13.639 | **0.6435** |
| FR | B | nuclear-dominated | 27.790 | 17.897 | 0.6440 |
| ES | A | solar-dominated | 27.316 | 17.866 | 0.6541 |
| DK1 | B | wind-dominated | 37.746 | 25.393 | 0.6727 |
| PL | B | coal-dominated | 29.822 | 20.207 | 0.6776 |
| BE | B | gas-nuclear-mixed | 28.217 | 19.376 | 0.6867 |
| IT-North | B | gas-dominated | 13.833 | 9.539 | 0.6896 |
| DE-LU | A | thermal-RES-mixed | 32.799 | 22.864 | 0.6971 |
| NL | B | gas-RES-mixed | 29.941 | 21.437 | **0.7160** |

#### FINDING C10-A — the *relative* skill of a price-only model is near-constant across nine regimes; the *level* of difficulty is not

Absolute MAE spans **2.73x** across the nine zones (IT-North 13.83 to DK1 37.75 on the
naive floor; 9.54 to 25.39 on LEAR). The ratio spans **1.11x** — 0.6435 to 0.7160,
mean 0.6757, sd 0.0248. A standard price-only LEAR removes **28-36% of the naive
floor's MAE in every zone**, whether the marginal unit is a reservoir, a reactor, a
wind farm, a solar fleet, a lignite block or a CCGT.

Some of that tightness is mechanical — both errors scale with the zone's price
volatility — but **not all of it, and that is the part worth keeping.** Normalising by
each zone's own 2024 price standard deviation leaves real cross-zone variation, and the
ratio is still three times tighter than either normalised error:

| quantity | mean | sd | CV | max/min |
|---|---|---|---|---|
| naive MAE / sd(price) | 0.6246 | 0.0723 | 0.116 | 1.548x |
| LEAR MAE / sd(price) | 0.4216 | 0.0472 | 0.112 | 1.510x |
| **LEAR MAE / naive MAE** | **0.6757** | **0.0248** | **0.037** | **1.113x** |

So the zones genuinely differ in how hard they are *relative to their own volatility*
(DK1's naive floor costs 0.75 sd, IT-North's 0.49 sd), and the model still removes a
near-constant fraction of whatever that floor is. Read plainly: on point error, this
model is not finding zone-specific structure beyond scale.

**Caveats that must travel with it.** n = 9, one validation year, and it is a ratio of
two strongly correlated quantities (Pearson 0.990 between the two MAE columns; the
zone ordering by naive difficulty is *identical* to the ordering by LEAR difficulty,
Spearman 1.00 — which mostly says volatility drives both, and is not itself a
surprising statistic). Whether a 7.3pp band is wider than sampling noise is exactly
what **C12's block-bootstrap CIs over daily blocks** are for, and C12 should answer it
before the C18 write-up makes anything of it.

**Why this matters for C11/C12.** PLAN.md's premise is a comparison "across zones with
genuinely different price-formation regimes". If the capture ratio turns out to be
*also* near-constant, then regime differences do not reach flexibility value through
forecastability at all, and the cross-zone story has to come from the price *shape* —
spread, number of profitable cycles per day, negative-hour count — not from how well
the curve can be forecast. If the capture ratio *diverges* while rMAE does not, that is
the sharper finding and the better one: it would mean a point-error metric is blind to
the thing a battery actually trades. **Either way C11/C12 now has a specific prediction
to test rather than a table to admire.**

#### FINDING C10-B — three extra years of price history beat the entire honest exogenous block, and beat the switch to a booster, in all three Tier-A zones

C10 puts three gains on one comparable scale for the first time. Per-cent of MAE,
Tier A, 2024:

| zone | window: 2019+ vs 2022+ (LEAR, price-only) | honest exogenous block (GBM, `res_persistence` vs `price_only`, C9) | model class (GBM − LEAR, honest arms, C9) |
|---|---|---|---|
| DE-LU | **+2.80%** (23.522 -> 22.864) | +1.0% | −3.1% (GBM better) |
| ES | **+3.53%** (18.521 -> 17.866) | +1.0% | +1.2% (LEAR better) |
| NO2 | **+7.45%** (14.737 -> 13.639) | +0.2% | −4.8% (GBM better) |

And the full-history price-only LEAR — the simplest honest model in the project — beats
the **best honest arm of either model fitted on the aligned window** in two of the
three Tier-A zones (ES by 0.209 EUR/MWh, NO2 by 0.366) and loses DE-LU by only 0.308
(1.3%, to `gbm_res_persistence`).

**The honest statement of this, which is not quite the dramatic one.** It is not a
controlled test of window length against features, because the exogenous arms *cannot*
run on a 2019 start — no archived ENTSO-E D-1 forecast vintage exists before 2022
(PLAN.md, `features.yaml` `available_from`). So the claim is the one a desk actually
faces: *at the only window where the exogenous block can be measured it is worth ~1% of
MAE, and moving to a window it cannot occupy is worth 3-7%.* Combined with FINDING C9-C
(the as-published Art. 14 vintage buys 18-24% that no bidder could have had), the C18
write-up's model section now has a clear spine: the two things that actually moved this
model were **more history** and **a publication timestamp**, and only one of them is
available to a bidder.

C8 had already committed the per-zone window gain as
`full_history_reference.mae_vs_aligned_price_only` (0.658 / 0.654 / 1.099 EUR/MWh,
which C10 reproduces to 1e-6). C10's contribution is putting it beside the exogenous
and model-class gains on one scale, which is what makes the ranking visible.

#### NOTE C9-01, substantially answered — the upward bias is a property of the 2022-aligned window, not of the models

C9 flagged that every model arm is biased high (+2.6 to +8.7 EUR/MWh) and attributed it
to the shared convex `sinh` back-transform. C10 can now separate that from the training
window, because the same model and the same zone exist at two starts:

| zone | LEAR price-only, train from 2022-01-01 | train from 2019-01-01 |
|---|---|---|
| DE-LU | +5.063 | **+2.600** |
| ES | +3.555 | **+1.100** |
| NO2 | +2.989 | **+0.813** |

A factor of 2-4 smaller on the longer window, with the model, the features and the
evaluation year all identical. The six Tier-B zones, all on the full history, land in
the same low range: IT-North **−0.027**, PL +0.156, DK1 +0.412, FR +1.837, BE +2.640,
NL +2.999.

The VST mechanism C9 named is still the right one — `sinh` is convex, so
back-transforming a conditional-mean estimate in asinh space overshoots in price space
— but the *size* of the overshoot scales with the in-fold MAD, and a window that is
half crisis-year rows has a much larger one. **The practical consequence for C11/C12 is
that the nine-zone comparable curves carry a bias of −0.03 to +3.0 EUR/MWh, not C9's
+2.6 to +8.7.** The prediction NOTE C9-01 asked C11/C12 to test (that a roughly uniform
upward bias barely perturbs the within-day ordering a battery trades on) is unchanged,
but the bias it has to be robust to on the comparable row set is a good deal smaller
than the Tier-A aligned arms suggested. Not acted on — correcting a bias by looking at
a 2024 metric is tuning against the validation year.

#### The results store — `backtest/results/results.csv`, 447 rows, 1 run

`backtest/results_store.py`. Long format: a row is
`(run, zone, model, arm, scope, metric) -> value`. Four decisions are load-bearing and
all four are written up in `docs/results_store.md`.

- **Long, not wide.** The wide alternative reads better and breaks on the first cycle
  that adds a metric: C11's capture ratios and C12's spread error, within-day Spearman
  and bootstrap bounds would each be a column every earlier row lacks. **The extension
  point is the metric name, never the column list** —
  `test_the_metrics_c11_and_c12_will_write_need_no_schema_change` pins exactly that,
  parameterised over the ten metric names those cycles are expected to want.
- **Append-only is verified twice, not promised.** `append_rows` reads the file's
  existing bytes, appends, then asserts the new file still *starts with* those exact
  bytes; and every run records in `results_runs.json` the SHA-256 of the whole file as
  it stood after it appended, which is the hash of its first `n_rows_after` data rows.
  `verify_append_only()` replays those hashes against the file's own prefixes, so an
  edit to **any earlier row is detectable long after the run that wrote it is gone**.
  Tests cover an edited row, a deleted row, a row hand-appended with no manifest entry,
  and a manifest out of append order. A column change is refused as a *migration* with
  the route spelled out, not absorbed.
- **Provenance includes the libraries** — the C9 entry's closing suggestion, taken up.
  Every row carries `git_sha`, `config_hash` (PLAN.md's requirement), the model's own
  fingerprint where it has one (`a366a760e269bba6` on every C9-sourced GBM row), and a
  16-hex `library_fingerprint` over `{python, numpy, pandas, scikit-learn, scipy,
  lightgbm}`; the run manifest keeps the full version dict. This cycle's fingerprint is
  **`856fb19ac0c4eecd`** = python 3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn
  1.9.1, scipy 1.17.1, **lightgbm 4.7.0** (the version C9's numbers were produced on,
  so the ingested rows are correctly labelled).
- **`vintage` is a required key column**, taking `honest` or `after_gate_closure`, and
  an unknown value is refused. FINDING C9-C makes an unlabelled late-arm number the
  single most misleading thing this project could publish, so `honest_rows()` is the
  default filter and a cycle that wants the Art. 14 arm has to ask for it by name. Of
  the 447 rows, **60 are `after_gate_closure`** (the `res_as_published` arm, 2 models x
  3 Tier-A zones x 2 scopes x 5 metrics) and 387 are honest.

The store also runs `data.holdout.assert_not_sealed` on every row's `evaluation_years`,
so **a metric computed against 2025 cannot be written** even if some later caller
computes one by mistake — and a spelling the guard cannot read (`"validation"`) is
refused rather than waved through.

#### Why Tier A is ingested from C8/C9 rather than refitted

`backtest/run_c10_scale.py` runs in two phases. `compute` is Tier B — the only new
fitting in this cycle, six zones x (naive + train_mean + LEAR), independent per zone so
it takes `--zones` and three processes ran it in parallel; nothing is appended to the
store there, which is what makes that safe. `ingest` is one process, one append.

Refitting Tier A's 24 model-arms would have spent hours reproducing committed numbers
and — worse — would have let the store's Tier-A rows drift from the artefacts the
findings were written against if any spec had moved. C9 set the precedent by reading
C8's LEAR predictions instead of refitting them; C10 extends it, and **every metric is
recomputed from the prediction columns rather than copied out of a summary**, then
asserted equal to the number its source cycle committed:

- **264 recomputed-vs-committed cross-checks, worst absolute delta 3e-6** against a
  tolerance of 5e-4 (the artefacts' own `%.4f` precision — the tolerance is the
  artefact's precision, not a margin chosen to let a disagreement pass). The whole
  check report is in `c10_scale_summary.json`, so the store shows its own working.
- C8's and C9's prediction **indices are asserted equal** per zone — a mismatch means
  the two cycles did not evaluate the same hours and is refused, never realigned.
- Their committed realised prices agree with each other **and** with a freshly loaded
  price series to **0.000000 EUR/MWh in all three zones**.
- The intersection of C9's nine prediction columns is asserted equal to the `n_hours`
  C9's summary committed (DE-LU 8 782, ES 8 591, NO2 8 783), so artefact and summary
  cannot disagree about what was compared.

#### Why Tier B trains on the full price history

Tier A's four arms are cut from 2022-01-01 because no archived forecast vintage exists
earlier. Tier B has no exogenous block and therefore no such constraint, so it runs
C4's committed `LearSpec` on everything cached (2019+). That makes the nine-zone
comparable row set `lear` / `price_only` / `train_from=2019-01-01`, which **exists for
Tier A too**: C8 ran exactly that as its `full_history_reference` and committed it as
`y_pred_price_only_full_history`. The cross-zone table is therefore like-for-like by
construction rather than by assertion, and
`test_the_comparable_table_refuses_a_row_trained_from_a_different_date` pins that a
2022-aligned row cannot sneak into it.

`scope` in the store: `own_coverage` is each series on the hours it answered;
`common_hours` re-scores every series of that zone on the intersection of all of them —
for Tier A, over exactly the nine series C9's artefact carries, which is what makes the
recomputation checkable against C9's committed `common_hours` block. The two tiers'
intersections are over different series sets, which is why the nine-zone table is built
from `own_coverage` rows and carries `n_scored` beside every number rather than a
footnote.

#### Data: 54/54 price pulls, and the first full nine-zone re-verification since C2

NOTE C2-02, **21st recurrence** — `data/raw/` was empty again. C10 re-pulled all 54
(zone, year) Energy-Charts price files: **54/54 succeeded, 0 FLAGs**. No ENTSO-E pull
was needed or made.

`data.build_manifest` and `data.build_contracts` were then re-run over all nine zones
and diffed against the committed artefacts. This is the first time since C2 that the
six Tier-B zones have been re-verified, and the result is clean:

- **price manifest** (54 rows x 28 columns): the only field that differs is
  `fetched_at_utc`, on all 54 rows. Every `payload_sha256`, count, coverage figure,
  distribution statistic and negative-hour count is **identical**.
- **contract report**: the CSV body is **byte-identical**, and "all data contracts
  hold" — 9 zones, 52 608 hours each, 0 duplicate timestamps, 0 NaN prices, 0 missing
  intervals, 0 UTC-day violations, 0 local-day violations, 12 DST days seen per zone,
  0 resolution changes, 0 cutover violations, **0 violations total**. The JSON differs
  only in `generated_at_utc`, `git_sha` and `config_hash` (the committed copy was
  generated at C2, before C8 added the publication clocks).

The regenerated manifest artefacts were therefore **reverted** rather than committed,
as in C8 and C9: they describe the same data, they are correctly labelled `"cycle":
"C2"`, and committing a fresh timestamp every cycle would churn the manifest forever
for no information gain.

#### LP invariants

C10 touched no dispatch, LP or settlement code, so the battery-LP invariants apply to
no new artefact. They remain executable and green as part of the full suite:
`assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` pass (re-run
separately as a 33-test subset to confirm). No LP objective from a forecast-priced
solve is reported anywhere as a realised value. **FLAG C5-01** (simultaneous
charge/discharge) is unchanged and still resolved as option (b) per Checkpoint B.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count
**0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, no `*2025*` file exists
anywhere under `data/`, and **no row of the results store mentions 2025** (grep count
0). Every series of every zone was evaluated on `[2024]` only. The store adds a new,
independent tripwire: a metric whose `evaluation_years` touches a sealed year cannot be
written at all. No 2025 data has been fetched, loaded, dispatched or computed against
at any point in C2-C10.

#### Config hash

**`515d4e8d98887256`** — unchanged from C8/C9. C10 modified no `config/*.yaml` file;
verified with `git diff --stat HEAD -- config/` (empty).

#### Built and committed (73 new tests, 505 in total)

- `backtest/results_store.py` — the append-only store: `SCHEMA`, `ResultRow`,
  `append_rows`, `verify_append_only`, `read_results`, `latest_results`,
  `honest_rows`, `pivot_metric`, `rows_from_scores`, `library_versions`,
  `library_fingerprint`.
- `backtest/run_c10_scale.py` — the two-phase CLI: Tier-B compute, Tier-A/Tier-B
  ingest with the recompute-and-cross-check guards, the nine-zone comparable table.
- `tests/test_c10_results_store.py` — 46 offline tests (append-only, provenance,
  validation, sealed-year refusal, reading).
- `tests/test_c10_scale_out.py` — 27 offline tests (the cross-check tolerance, the
  vintage labelling, the common-hours mask, the comparable table's like-for-like rule,
  the artefact provenance guards).
- `docs/results_store.md` — the full write-up of all of the above.
- `backtest/results/results.csv` (447 rows) + `results_runs.json` (1 run,
  `C10-20261008T183636Z-8e556310`) + `c10_scale_summary.json`.
- `backtest/results/c10_tierb_{FR,NL,BE,IT-North,DK1,PL}_2024_{predictions.csv.gz,folds.csv,summary.json}`.
- `requirements.txt` — a comment block recording that C10 added no dependency, and why
  the store is deliberately plain csv/json/hashlib.

#### NOTE C10-01 (new, for C11 — not a blocker)

The store's `common_hours` scope is defined per zone over the series that zone has, so
Tier A's intersection is over nine series and Tier B's over three. That is correct for
within-zone model comparison and is why the cross-zone table uses `own_coverage`, but
**C11 will add nine zones x three curves of dispatch results and should decide once
whether a capture ratio belongs at `own_coverage` or at a common-hours scope**, rather
than per zone. A battery LP needs a complete 24-hour vector, so the question is really
which NaN policy C11 dispatches the LEAR curve under (C4 measured both; `decline`
leaves one hole a year, `impute` fills it with the in-fold column median) — and that
choice should be a labelled row in the store, not an implicit default.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `144ecf5` with local
`master` stale 13 commits behind. **25 recurrences out of 32 containers.** This time
`git checkout -B master` **was permitted** (it was denied as "Git Destructive" in C9),
so the cycle worked on a properly attached `master` throughout. `origin/master` equalled
`HEAD` at session start, so nothing was at risk either way. The C9 entry's warning still
stands for a future container that arrives detached *and* genuinely behind the remote:
flag rather than improvise. Keep checking `git rev-parse --abbrev-ref HEAD` and
`git rev-list --count master..HEAD` at the start of every cycle.

**Next:** C11 — the LP across all nine zones x all curves (oracle / model / naive),
persisting per-day capture ratios. Read FINDING C10-A first: it gives C11 a specific
prediction to test (is the capture ratio as regime-insensitive as rMAE, or does it
diverge?), and NOTE C8-01's open question — whether `res_persistence` buys more capture
ratio than its 1% of MAE suggests — is the other half of the same experiment. Note
NOTE C10-01 on the NaN policy for the dispatched LEAR curve, and FINDING C10-B/NOTE
C9-01: the comparable nine-zone curves carry a bias of −0.03 to +3.0 EUR/MWh, not the
+2.6 to +8.7 the Tier-A aligned arms showed. Write every dispatch result into
`backtest/results/results.csv` via `backtest.results_store.append_rows` — the metric
name is the extension point, no schema change is needed, and
`verify_append_only()` should be called before trusting anything already in there.

### C11 — 2026-10-09 (scheduled cycle) — the LP across nine zones, and the first metric that disagrees with MAE

Scope per PLAN.md C11: *"LP across all 9 zones x all curves; persist per-day capture
ratios."* Done for all nine zones and every committed curve. No checkpoint, no blocker,
no FLAG raised, no new dependency. `ENTSOE_API_KEY` was **not needed and not read** —
every forecast dispatched here was read from the artefact the cycle that scored it
committed, so the only network traffic was 18 Energy-Charts price pulls.

**Full suite: 556 passed, 0 failed, 51 warnings, 432.67s** (505 before C11 + 51 new).
The 51 warnings are the same pre-existing sklearn LARS convergence notices from the C8
LEAR tests. `tests/` (every pre-existing file), `config/`, `forecast/`, `dispatch/`,
`data/`, `backtest/walk_forward.py`, `backtest/metrics.py` and
`backtest/results_store.py` are **untouched** — verified with
`git diff --stat HEAD` over exactly those paths, which came back empty. The only
modified committed files in the whole cycle are `requirements.txt` (a comment block
recording that C11 added no dependency) and the two append-only store files.

#### What was dispatched

45 rolled dispatch runs and 45 same-start oracle re-solves, ~33 000 LP solves, 2m09s.

- **Tier A** (DE-LU, ES, NO2) — oracle + **8** curves: `lear_full_history` (C8's
  `price_only_full_history`, the nine-zone comparable arm), the three 2022-aligned LEAR
  arms and the three 2022-aligned GBM arms (C8/C9), and the naive floor.
- **Tier B** (FR, NL, BE, IT-North, DK1, PL) — oracle + **2**: the comparable LEAR and
  the naive floor (C10's artefacts).

Nothing was re-fitted, extending the C9/C10 precedent: a capture ratio and the MAE of
the same forecast are now about the same numbers and cannot drift apart. The two
`res_as_published` arms carry `vintage="after_gate_closure"` and travel only as the
measurement of FINDING C9-C's leak.

#### Invariants — all green, every curve, every day

`invariant_failures` is `[]` in all nine zones. `value(curve @ realised) <= value(
same-start oracle)` on **every** dispatched day of **every** curve (not a sample — the
check asserts `n_days_checked` equals the curve's dispatched day count, and a test pins
that); the pooled `oracle >= arm` and `naive <= forecast`; no settlement is a read-back
of its own decision prices; `value_added >= 0` on each curve's own decision prices and
at realised prices on the oracle; day lengths match the local calendar. The worst
per-day excess over the bound across all 45 runs is `+0.00e+00` or negative.

#### C11 reproduces C6 exactly

C6 dispatched C4's `y_pred_lear_aic` on DE-LU, and that column is identical to C8's
`y_pred_price_only_full_history` to **0 EUR/MWh over 8 784 hours** — so C11's
`lear_full_history` arm is the same forecast and the two cycles must agree exactly, not
approximately. `check_c6_reproduction` asserts eight numbers against C6's committed
summary at C6's own JSON precision: **8/8 hold, worst absolute delta 2.73e-05.** Oracle
/ model / naive pooled cash (74 365.4450 / 68 318.8799 / 62 997.6827), both rolled
capture ratios (0.918691 / 0.847136), both same-start capture ratios (0.869574 /
0.779737) and the 365-day common count all reproduce.

That check was itself the first real test of the scope decision below: C6's pooled cash
is over the common day set while its per-curve capture summaries are over each curve's
own days, so C6's naive capture (0.779737) matches C11's **`own_coverage`** row exactly
and differs from C11's `common_hours` row (0.780436) in the third decimal — for a
reason that is a *scope*, not an error.

#### The three decisions C11 was asked to make

**NOTE C10-01, the NaN policy — committed, unchanged.** The dispatched LEAR curve is the
`nan_policy="decline"` series every earlier cycle scored, and a market day whose
forecast vector has a hole is **skipped and counted, never patched** (C6's NOTE C4-02
decision carried to all nine zones). It costs one autumn-DST day a year in every zone
(365 of 366), plus in ES the days the `res_*` arms decline. Every skip is in the
per-zone summary with its reason. No impute variant was fitted: C6 already priced that
alternative on DE-LU and refitting it here would be new modelling work outside C11's
scope.

**NOTE C10-01, the capture-ratio scope — decided, and the decision is measured.** A
capture ratio is a ratio of two sums, so numerator and denominator must run over the
same days, and two arms' ratios are only comparable if they do too; `pooled_capture`
therefore takes the day set as an *argument*. Both of the store's existing scopes are
written and mean for a dispatch metric what they mean for a point-error one (the
vocabulary is about *coverage*, not the time unit): `own_coverage` = each curve over the
days it dispatched; `common_hours` = every curve of that zone re-pooled over the
intersection of the days every C11 curve of that zone dispatched. **The within-zone arm
comparison is read at `common_hours`; the cross-zone table is built from
`own_coverage`**, as C10's was, because the two tiers' intersections are over different
curve sets (nine curves vs three) and a Tier-A intersection shrunk by an arm that is not
even in the cross-zone comparison would silently re-scope Tier B's neighbours. **No new
scope value was added and `backtest/results_store.py` was not touched.**

The cost of that choice is reported per curve per zone in `scope_sensitivity`, on both
ratios. On the headline rolled-oracle ratio the comparable arm is **scope-invariant in
eight of nine zones** (+0.0000) and moves **−0.2394pp in ES**: ES's nine-curve
intersection drops to **357 days** against 365 everywhere else, because of the 145
missing hours in the exogenous join that only the two `res_*` arms suffer. ES's capture
is 0.910932 at `own_coverage` and 0.913326 at `common_hours` — either leaves it second
of nine, so the decision does not change the cross-zone ordering. The naive floor is
the one curve that genuinely moves (−0.41 to +0.42pp), because it is the only curve
dispatching all 366 days while the comparable arm declines one.

**FINDING C11-C, the headline metric — not the same-start ratio.** See below; this was
not a decision C11 expected to have to make.

#### FINDING C11-C — the same-start capture ratio cannot be used to rank two curves

The same-start oracle is the exact per-day bound and stays the invariant. It is **not**
fit to compare arms, and C11 can demonstrate that rather than assert it.

On DE-LU, `lear_res_persistence` and `lear_res_as_published` settle **0.35 EUR apart
over 365 days** (67 842.68 vs 67 843.03) — yet their same-start capture ratios differ by
**4.0pp** (0.8589 vs 0.8985). The two schedules are genuinely different (per-day cash
differs by a mean of 37 EUR and a max of 282; only 13 of 365 days are identical), so the
coincidence is in the annual totals, not in the behaviour. The 4pp gap is not about
their earnings at all — it is the **denominator** moving: the same-start oracle is
re-solved from each arm's own opening SoC, and a day opened with a fuller battery has
less attainable added value. Mean opening SoC is 0.454 MWh for the as-published arm
against 0.216 for the persistence arm, so the arm carrying more inventory is scored
against an easier ceiling.

The rolled-oracle ratio has **one denominator per zone**, identical for every curve, and
ranks the two arms identically (0.9123 both). **So the project's headline capture ratio
is settled cash over the rolled perfect-foresight run's cash on the same days**; the
same-start ratio travels beside it as the exact per-day bound and as the per-day
distribution, and is never used to rank two curves.
`test_finding_c11_c_the_same_start_ratio_reorders_arms_the_rolled_one_ties` pins the
measurement against the committed artefact, so a later cycle cannot quietly promote it
back. **C12 and C18 must quote `capture_rolled_oracle_cash`, not
`capture_same_start_pooled`.**

#### FINDING C11-A — the capture ratio diverges across zones; rMAE does not

FINDING C10-A handed C11 a specific prediction: *if the capture ratio is also
regime-insensitive, regime differences do not reach flexibility value through
forecastability; if it diverges while rMAE does not, that is the sharper finding.*
**It diverges.**

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
| rMAE (LEAR/naive MAE) | 0.6757 | 0.0248 | 0.0367 | 1.113x | 7.2pp |
| **capture ratio** | **0.8587** | **0.0957** | **0.1114** | **1.495x** | **30.4pp** |
| naive capture ratio | 0.7645 | 0.1138 | 0.1489 | 1.759x | 36.5pp |

The capture ratio's CV is **3.0x rMAE's** and its band **4.2x as wide**. A point-error
metric that is near-constant across nine regimes sits on top of a dispatch metric that
is not.

And the rankings do not line up — if anything they run the wrong way. **NO2 has the best
relative forecast skill of the nine (rMAE 0.6435, rank 1) and by far the worst capture
(0.6146, rank 9); DE-LU is second-worst on rMAE (rank 8) and best on capture (rank 1).**
Spearman between rMAE and capture is **+0.58** (p=0.099) — *positive*, i.e. zones where
the model is relatively worse than naive capture *more* of the oracle's value, the
opposite sign of what forecastability would imply.

**What must travel with it.** n = 9, one validation year; the +0.58 is not significant
and its sign must not be leaned on. And the 30.4pp band is substantially **one zone**:
drop NO2 and the remaining eight sit in 0.8358–0.9187 — a band of 8.3pp, CV 0.0335,
still wider than rMAE's 7.2pp but no longer dramatic. **The defensible claim is the
inequality of the bands and the non-alignment of the rankings, not a law about
regimes.** C12's block-bootstrap CIs over daily blocks must decide whether the 8.3pp
eight-zone band is wider than noise before C18 makes anything of it.

One thing the capture ratio says that MAE cannot: the model's **uplift over the naive
floor is largest exactly where capture is lowest** — NO2 +13.4pp, DK1 +11.8pp, against
DE-LU +7.4pp and ES +7.4pp. Where perfect foresight is hardest to approach, having a
forecast at all is worth the most.

#### FINDING C11-B — NO2 is the outlier, and the mechanism is NOT established

NO2 deserves its own line in the write-up: lowest mean daily spread of the nine (46.28
vs 65–120), lowest oracle value by a wide margin (26 022 EUR/MW/yr vs 41 864–77 116),
fewest oracle cycles (418 equivalent full cycles vs 577–721), and the model **loses
money at realised prices on 25.8% of dispatched days** against 0.8–7.4% everywhere
else.

The natural story — a thin spread leaves less headroom over the round-trip efficiency
and the 2 EUR/MWh throughput cost, so a given forecast error more easily flips a trade
from profitable to loss-making — is consistent with all four observations and is **not
established.** Every spread-based regressor's correlation with capture across the nine
zones collapses when NO2 is removed: mean daily spread Pearson +0.60 -> **+0.00**,
oracle value +0.66 -> **−0.01**, spread over the round-trip breakeven +0.39 -> −0.21.
With n = 9 this is one zone, not a relationship. The one strong correlate — share of
days the model loses money, Pearson −0.97 — is close to mechanically true (losing days
reduce the numerator) and is a restatement, not an explanation. **Not acted on**:
nothing was tuned, and no regime variable was fitted to a visible 2024 metric.

**The direct test is already in the plan.** C15's throughput-cost sensitivity (0 / 2 /
5 EUR/MWh) is it: if the thin-spread mechanism is right, NO2's capture should move far
more than the other zones' when the cost goes to zero. C13 should also report whether
NO2's capture is stable across years or specific to 2024's hydrology.

#### FINDING C11-D — among honest arms, MAE does not predict capture

This is the finding C11 exists to produce, and the spine of C18's model section.

Every intervention this project has measured, scored twice: the MAE gain in per cent,
recomputed over **exactly the hours the capture ratio is computed over** (not re-used
from C10's own-coverage rows — ES's exogenous hole differs by ~145 hours and would make
the comparison unpaired, which would make the whole finding an artefact of two samples),
and the change in the rolled-oracle capture ratio in percentage points. Positive = the
arm is better. Persisted as `{mae,rmse,bias}_on_dispatched_hours` at `common_hours` so
C12 can bootstrap both on the same days.

| question | DE-LU | ES | NO2 |
|---|---|---|---|
| honest exogenous block, **LEAR** (`res_persistence − price_only`) | −0.26% / +0.22pp | +1.08% / +0.52pp | −0.52% / −0.83pp |
| honest exogenous block, **GBM** | +1.03% / +0.35pp | +0.85% / **+2.04pp** | +0.23% / **+2.71pp** |
| model class, price-only (`gbm − lear`) | +3.17% / −0.59pp | −1.15% / −2.22pp | +4.72% / −2.02pp |
| model class, with the block | +4.41% / −0.46pp | −1.38% / −0.70pp | +5.43% / +1.53pp |
| more history (`full_history − price_only`) | +2.81% / +0.86pp | +3.62% / −0.27pp | **+7.42% / −1.31pp** |
| *vintage premium, LEAR — NOT achievable* | +8.33% / +0.00pp | +11.13% / −0.84pp | +0.14% / −0.76pp |
| *vintage premium, GBM — NOT achievable* | **+23.91%** / +3.47pp | +17.71% / +0.95pp | +3.58% / −0.84pp |

**Across the 15 honest comparisons the two metrics agree on the sign 9 times — a coin
flip — with Spearman +0.02 (p=0.95) and Pearson −0.11 (p=0.69).** Knowing which of two
honest arms has the lower MAE tells you essentially nothing about which captures more
flexibility value. Four specifics:

1. **NOTE C8-01 is answered, affirmatively, for the booster.** The honest exogenous
   block buys **+0.35 / +2.04 / +2.71pp** of capture (**+262 / +924 / +706 EUR/MW/yr**)
   under the GBM — far more than its +1.0% / +1.0% / +0.2% of MAE suggested, and *the
   ordering is inverted*: NO2 gained the least on MAE and the most on capture. This is
   the first time in this project that a decision-relevant metric has disagreed with MAE
   about whether a feature block is worth having, and it is exactly the mechanism
   NOTE C8-01 hypothesised — RES information kills the large errors, and those sit in the
   high-wind, negative-price hours a battery earns in. Under the LEAR the same block
   still buys nothing (+0.22 / +0.52 / −0.83pp), consistent with FINDING C8-A. **The
   honest headline arm for Tier A remains `res_persistence`, and it now has a reason to
   exist that is not an MAE reason.**
2. **"Gradient boosting beats LEAR" does not survive the move to a dispatch metric.** At
   an honest vintage, price-only, the GBM has the lower MAE in DE-LU (+3.17%) and NO2
   (+4.72%) and yet **loses on capture in all three zones** (−0.59 / −2.22 / −2.02pp).
   With the exogenous block it loses DE-LU and ES and wins only NO2. Read with
   FINDING C9-C — the booster's whole advantage was concentrated in the leaking arm — the
   C18 model ranking should be stated on capture, and on capture it does not favour the
   booster.
3. **FINDING C10-B's window gain largely evaporates.** Three extra years of price history
   were worth +2.81 / +3.62 / +7.42% of MAE; in capture terms they are +0.86 / −0.27 /
   **−1.31**pp. NO2 had the largest MAE gain of any intervention in this project and the
   second-worst capture outcome of any honest arm. FINDING C10-B's claim ("more history
   beat the entire honest exogenous block") is an **MAE** claim and must be labelled as
   one from here on — on capture the ranking reverses, and it is the exogenous block
   under the booster that wins.
4. **The Art. 14 leak buys almost nothing a battery can trade.** Worth 8.3% and 11.1% of
   MAE to the LEAR, it is worth +0.00 and −0.84pp of capture. Under the GBM the 23.9%
   MAE gain on DE-LU does convert to +3.47pp, so the leak is not *uniformly* worthless —
   but that number is `after_gate_closure` and unachievable, and it is the one place a
   large MAE gain and a large capture gain coincide.

NOTE C9-01's prediction is confirmed and generalised: a roughly uniform upward bias
(−0.03 to +3.0 EUR/MWh on the comparable curves) barely perturbs the within-day ordering
a battery trades on — and beyond that, **most point-error gains do not reach the ordering
either.**

**The caveat that must travel with FINDING C11-D.** n = 15 paired comparisons, three
zones, one year, and most capture deltas are under 1pp. A good deal of this could be
noise around zero, and the honest reading today is *"MAE is not a reliable proxy for
capture"*, **not** *"MAE is anti-correlated with capture"*. **C12's block bootstrap over
daily blocks is what turns this table into a finding** and should run on
`c11_capture_daily_2024.csv.gz` before C18 quotes any delta. The GBM-exogenous result
(+2.04 / +2.71pp, ~700–900 EUR/MW/yr) is the largest honest effect and the most likely
to survive.

#### FLAG C5-01 across nine zones, for the first time

Simultaneous charge/discharge — resolved at Checkpoint B as option (b) (keep the pure
LP, carry it as a stated limitation). C11 is the first cycle to measure it outside
DE-LU, and the nine-zone picture **supports that decision more strongly than DE-LU alone
did.** On the comparable arm: FR 9 of 365 days (2.5%, 28 intervals, 2.70 MWh burned,
0.14% of settled cash), BE 3 days, DK1 2 days, DE-LU / ES / NL / PL 1 day each, NO2 and
IT-North **none**. Present in seven of nine zones but tiny everywhere — at worst 2.5% of
days and 0.14% of cash. With Checkpoint B's measurement that it biases capture *against*
the model by ~0.16pp (LP 0.9187 vs MILP 0.9203 on DE-LU), the pure LP stays the
conservative default. **Nothing new decided; no dispatch, LP or settlement code
touched.** No MILP variant was run this cycle — it is a C15 sensitivity, not C11 scope.

#### The results store

**1 638 rows appended**, run `C11-20261009T022531Z-5e82e39f`; the store is now **2 085
rows across 2 runs**, `verify_append_only()` green, and the **447 committed C10 rows are
byte-for-byte unchanged** (checked directly: the new file's first N bytes are identical
to `git show HEAD:backtest/results/results.csv`, and the diff is 1 638 insertions / **0
deletions**). **No schema change and no test edit were needed** — long format made the
metric name the extension point exactly as `docs/results_store.md` promised, and C10's
`test_the_metrics_c11_and_c12_will_write_need_no_schema_change` was written against
this.

Per (zone, curve, scope): `dispatch_cash_eur`, `dispatch_value_added_eur`,
`dispatch_cash_eur_per_mw_year`, `capture_same_start_pooled`,
`capture_same_start_mean_daily`, `capture_same_start_{p05,p25,p50,p75,p95}_daily`,
`capture_rolled_oracle_cash`, `eur_per_mw_year_lost_vs_oracle`,
`share_of_days_value_added_negative`, `share_of_days_with_simultaneity`,
`equivalent_full_cycles`, `realised_spread_{mean,median}_eur_per_mwh`; plus, at
`common_hours` only, the paired `{mae,rmse,bias}_on_dispatched_hours`. The oracle's rows
carry `model="oracle"`, `exog_variant="perfect_foresight"` and an **empty `train_from`**
(perfect foresight has no training window). `evaluation_years` is `2024` on all 2 085
rows.

#### Data: 18/18 price pulls, verified against the C2 manifest

NOTE C2-02, **22nd recurrence** — `data/raw/` was empty again on arrival. C11 re-pulled
only the **18** (zone, year) files it needed (2023 for the trailing mark run-in, 2024 for
dispatch) rather than all 54: **18/18 succeeded, 0 FLAGs**, no ENTSO-E pull needed or
made. Every one of the 18 was then checked against the committed C2 manifest with the
manifest's own `payload_fingerprint`: **18/18 `payload_sha256` identical.** The manifest
artefacts were not regenerated or committed — C10 did the full nine-zone re-verification
three cycles ago and committing a fresh `fetched_at_utc` every cycle churns the manifest
for no information gain.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count **0**,
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, no `*2025*` file exists anywhere
under `data/`, only 2023 and 2024 price files were fetched, every `market_day` in every
C11 artefact is in 2024, and `evaluation_years` = `2024` on all 2 085 store rows. The 18
occurrences of the string `2025` in `c11_capture_daily_2024.csv.gz` were each inspected
and are digits inside float values (`30.402025`, `34.220252`, `0.2025`). No 2025 data has
been fetched, loaded, dispatched or computed against at any point in C2–C11.

#### Config hash and libraries

Config hash **`515d4e8d98887256`** — unchanged from C8/C9/C10; C11 modified no
`config/*.yaml` (verified with `git diff --stat HEAD -- config/`, empty). Library
fingerprint **`856fb19ac0c4eecd`** — identical to C10's (python 3.11.17, numpy 2.4.6,
pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1, lightgbm 4.7.0), so C10's and C11's rows
are directly comparable. The GBM config fingerprint `a366a760e269bba6` is carried on
every GBM row and was not touched.

#### Built and committed (51 new tests, 556 in total)

- `backtest/run_c11_dispatch.py` — the nine-zone dispatch CLI: the `Arm` inventory,
  `load_arm_curves` with the three provenance checks, `pooled_capture` (the day set as an
  argument), `mae_on_days` (the paired point error), `beats_naive`, `store_rows`,
  `comparable_table`, `check_c6_reproduction`, and the `CONTRASTS` that answer
  NOTE C8-01.
- `tests/test_c11_dispatch.py` — 51 offline tests: the arm inventory and its vintage
  labels, the ratio-of-sums property, the two scopes on a market where they genuinely
  differ, the denominator-coverage refusal, the paired MAE's hour set, the store rows
  (including the sealed-year refusal and "no row for a metric that could not be
  computed"), FINDING C11-C pinned against the artefact, and that the C6 reproduction
  check can actually fail.
- `docs/dispatch_results.md` — the full write-up of all of the above.
- `backtest/results/c11_dispatch_<ZONE>_2024_{daily.csv.gz,summary.json}` (nine zones),
  `c11_capture_daily_2024.csv.gz` (**16 440 rows** — every curve x every dispatched day,
  the artefact C12 bootstraps over), `c11_comparable_capture.csv`,
  `c11_dispatch_summary.json`, and the 1 638 new rows in `results.csv` /
  `results_runs.json`.
- `requirements.txt` — a comment block recording that C11 added no dependency.

#### Two notes for later cycles (neither a blocker)

**NOTE C11-01 — for C12, and it is the whole job.** Every headline in this entry is one
validation year and either n = 9 zones or n = 15 paired comparisons, with most capture
deltas under 1pp. C12's block bootstrap over daily blocks has to decide three specific
things before C18 quotes any of them: (i) is FINDING C11-A's eight-zone 8.3pp capture
band (NO2 excluded) wider than noise, (ii) is FINDING C11-D's near-zero MAE/capture rank
correlation distinguishable from a real relationship, and (iii) does the GBM-exogenous
capture gain (+2.04 / +2.71pp) survive a CI. The per-day artefact is already in the
shape a daily-block bootstrap needs.

**NOTE C11-02 — for C13/C15.** FINDING C11-B's thin-spread mechanism for NO2 is
untested. C15's throughput-cost ladder (0 / 2 / 5 EUR/MWh) is the direct test and should
be read as such, not merely as a sensitivity; C13 should say whether NO2's capture is a
2024 hydrology artefact or a standing property.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `e30892d` with local
`master` stale 14 commits behind. **26 recurrences out of 33 containers.** `HEAD` equalled
`origin/master` exactly (0 ahead, 0 behind) so nothing was at risk, and
`git checkout -B master` was permitted, so the cycle worked on a properly attached
`master` throughout. C9's warning still stands for a container that arrives detached *and*
genuinely behind the remote: flag rather than improvise. Keep checking
`git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the start of
every cycle.

**Next:** C12 — the metrics layer: MAE, RMSE, rMAE vs naive, daily-spread error,
within-day Spearman, capture ratio, EUR/MW/yr, and **block-bootstrap CIs over daily
blocks**. Read NOTE C11-01 first: C12 is not a formatting cycle, it is the cycle that
decides whether C11's three findings are real. Quote `capture_rolled_oracle_cash`, never
`capture_same_start_pooled` (FINDING C11-C). The per-day input is
`backtest/results/c11_capture_daily_2024.csv.gz`; the paired point error is already in
the store as `{mae,rmse,bias}_on_dispatched_hours` at `common_hours`, on the same hours
as the capture ratios, so the spread and Spearman metrics C12 adds should be computed on
that same hour set. Call `verify_append_only()` before trusting the store and append with
`append_rows` — the metric name is still the extension point and no schema change is
needed.

### C12 — 2026-10-09 (scheduled cycle) — the metrics layer, and two of C11's three questions answered "no"

Scope per PLAN.md C12: *"Metrics layer: MAE, RMSE, rMAE vs naive, daily-spread error,
within-day Spearman; capture ratio; EUR/MW/yr; block-bootstrap CIs over daily blocks."*
Done, all nine zones, every committed curve. No checkpoint, no blocker, no FLAG raised,
no new dependency. **No price file was opened at all** — the realised prices came from
the committed artefacts' own `y_true` — so this is the first cycle since C1 with **zero
network requests**, and `ENTSOE_API_KEY` was neither needed nor read.

NOTE C11-01 said C12 "is not a formatting cycle, it is the cycle that decides whether
C11's three findings are real." It decided. **One survives decisively, one is at the
edge, one is downgraded to undetermined** — and the cycle turned up a metric nobody had
computed yet that does better than any of them.

**Full suite: 607 passed, 0 failed, 51 warnings, 620.66s** (556 before C12 + 51 new). The
51 warnings are the same pre-existing sklearn LARS convergence notices from the C8 LEAR
tests. `tests/` (every pre-existing file), `config/`,
`forecast/`, `dispatch/`, `data/`, `backtest/walk_forward.py` and
`backtest/results_store.py` are **untouched** — verified with `git diff --stat HEAD`
over exactly those paths, which came back empty. `backtest/metrics.py` **was** modified
and the diff is **purely additive**: 225 lines added, and the only removed line is
`from dataclasses import dataclass` becoming `from dataclasses import asdict, dataclass`.
No existing function was changed, so C3's leakage assertions and C4's skill score read
exactly the code they read before. A new file under `tests/` follows C11's precedent
(C11 added `tests/test_c11_dispatch.py` and recorded `tests/` as untouched meaning every
*pre-existing* file); no pre-existing test was edited, so this is not a CLAUDE.md
flag-and-stop event.

#### Reproduction first: C12 bounds C11's numbers, not near neighbours of them

A CI around a number nobody published is worse than no CI, so the run **exits non-zero**
if its point estimates do not match C11's committed store rows. Seven metrics × 27
(zone, curve) pairs, joined on the store's own key rather than on C11's internal curve
label. `mae/rmse/bias_on_dispatched_hours` and `realised_spread_mean` reproduce at
**exactly 0.0**; `capture_rolled_oracle_cash` at 5.2e-10. The two EUR/MW/yr figures
carry a *relative* tolerance for a stated reason — C11 formed them as
`sum(cash)/span*365.25` and C12 as `mean(cash)*(n_days*365.25/span)`, the same number
summed in a different order (~1e-9 relative), and the lost-value figure one order worse
because it is a ~6 000 EUR difference of two ~70 000 EUR sums. **7/7 hold.**
`test_the_c11_reproduction_check_can_actually_fail` nudges one capture ratio by 1e-6 and
confirms the check catches it.

#### FINDING C12-A — the capture band is wider than noise; rMAE's band is not. CONFIRMED.

FINDING C11-A's *inequality of bands* claim survives decisively, at all three block
lengths. A band is a max minus a min, so it is positively biased and its own interval
never excludes zero even when every zone is identical; the test is therefore a
**noise-only null band** — remove the zone effect, keep each zone's own bootstrap
deviation, and ask how often sampling noise alone produces a band this wide.

| block | capture band | noise-only p | between/within | rMAE band | noise-only p | between/within |
|---|---|---|---|---|---|---|
| 1 day | 30.40pp [23.27, 40.35] | **<1e-4** | 4.18 | 7.42pp [5.65, 14.19] | 0.196 | 0.95 |
| 7 days | 30.40pp [24.47, 37.75] | **<1e-4** | 6.10 | 7.42pp [5.93, 15.91] | 0.367 | 0.69 |
| 14 days | 30.40pp [24.92, 37.56] | **<1e-4** | 5.88 | 7.42pp [6.23, 15.37] | 0.284 | 0.71 |

The capture ratio's cross-zone spread is **4–6 times** the sampling noise of its own
estimates; rMAE's is at or below it. That **sharpens FINDING C10-A from "near-constant"
to "indistinguishable from constant"**: nine zones' relative forecast skill cannot be
told apart from nine draws of one number, while the dispatch metric sitting on top of it
is 4–6σ wide. C11's "capture's CV is 3.0x rMAE's" survives as an interval:
**CV ratio 2.97 [1.53, 4.30]**, excluding 1 at every block. 17 of 36 zone pairs have a
paired capture difference excluding zero (21 of 36 at 7 days).

#### FINDING C12-B — the eight-zone band is NOT established. (NOTE C11-01 (i): answered, no.)

| block | capture band ex-NO2 | noise-only p | between/within |
|---|---|---|---|
| **1 day (PLAN.md's literal "daily blocks")** | 8.29pp [6.51, 15.18] | **0.078** | 1.45 |
| 7 days | 8.29pp [6.75, 12.38] | 0.001 | 2.20 |
| 14 days | 8.29pp [6.89, 12.42] | 0.003 | 2.06 |

At the block length PLAN.md names it does not clear 5%. It clears at 7 and 14 days — but
a conclusion that depends on the block length is by definition not established, and the
longer rungs are the ones whose long-run variance estimate is least trustworthy at
n = 365 (~26 independent blocks). With NO2 out, the capture CV and the rMAE CV become
indistinguishable (**ratio 0.96 [0.51, 1.77]**).

**So FINDING C11-A is a finding about NO2 plus a direction.** The 30.4pp band and the
inequality of the bands are real and large; the claim that the other eight regimes differ
in capture by more than noise is at the edge of what one validation year supports.
**C18 must not quote the 8.3pp eight-zone band as established, and C13's second year is
the test.**

#### FINDING C12-C — the within-day Spearman is the only point-forecast metric that tracks capture. NEW.

C11 asked whether *rMAE* tracks capture across regimes. The better question was whether
**any** point-forecast metric does, and one of them does — the one closest in meaning to
what the LP actually reads off a curve. Cross-zone rank correlation against capture, nine
zones, daily block:

| forecast metric | ρ vs capture | 95% CI | sign a forecastability story predicts | sign right? | excludes 0? |
|---|---|---|---|---|---|
| **within-day Spearman** | **+0.70** | **[+0.35, +0.93]** | + | yes | **yes** |
| rMAE vs naive | +0.60 | [−0.08, +0.85] | − | **no** | no |
| MAE | +0.05 | [−0.25, +0.50] | − | no | no |
| daily spread MAE | +0.08 | [−0.37, +0.58] | − | no | no |
| daily spread bias | +0.20 | [−0.55, +0.42] | + | yes | no |

Holds at every block length and with NO2 removed (**+0.57 [+0.07, +0.91]**); every other
candidate spans zero everywhere. Note that **rMAE's +0.60 has the wrong sign** — zones
where the model is relatively worse than naive capture *more* — so C11 was right to
refuse to lean on it, and now the interval contains zero too.

**A candidate mechanism for FINDING C11-B, which C11 could not offer.** NO2's mean
within-day Spearman is **0.578** against 0.71–0.89 in the other eight; DK1, the
second-worst capture, has the second-worst Spearman (0.706). C11 found every
*spread-based* correlate of NO2's low capture collapsed when NO2 was dropped. The
ordering metric does not — it survives the drop. So the candidate mechanism is **not**
"NO2's spread is too thin to clear the round-trip cost" but "**in NO2 the forecast puts
the hours in the wrong order**", the one error a battery cannot trade around. **This is a
candidate, not established** (n = 9, one year, and a rank correlation is not a mechanism),
but it changes what C15's throughput-cost ladder should be read against — see NOTE C12-02.

#### FINDING C12-D — capture cannot rank arms at one validation year. (NOTE C11-01 (ii): answered.)

FINDING C11-D was "among honest arms, MAE does not predict capture", with C11's own
caveat that most deltas were under 1pp. **The bootstrap says the caveat was the finding.**
Across the fifteen honest contrasts, at the daily block:

| contrast metric | intervals excluding 0 | median \|delta\|/boot sd | max |
|---|---|---|---|
| **capture (pp)** | **1 / 15** | **0.46** | 2.21 |
| EUR/MW/yr | 1 / 15 | 0.46 | 2.23 |
| daily spread MAE | 5 / 15 | 0.93 | 3.88 |
| MAE (%) | 7 / 15 | 1.91 | 6.33 |
| **within-day Spearman** | **8 / 15** | **2.23** | 5.01 |

The ordering (capture fewest, Spearman most) holds at every block length. C11's rank
correlation of +0.02 now has interval **[−0.53, +0.56]** — it excludes essentially
nothing; Pearson −0.11 [−0.58, +0.59]; sign agreements 9 of 15 with interval [5, 12]
against 7.5 under independence.

**The honest statement is therefore not "MAE does not predict capture". It is "one
validation year decides 1 of 15 capture deltas, so it can neither establish nor rule out
that MAE predicts capture."** FINDING C11-D must be restated in C18 as **undetermined,
not contradicted**. The apparent disagreement between the two metrics is largely that one
of them is ~4x noisier per unit of effect.

That is not an argument for MAE. It is an argument for **ranking arms on the within-day
Spearman** — decidable, and the only metric whose cross-zone behaviour tracks capture —
and using capture for the economic translation (EUR/MW/yr) rather than for the ranking.

#### FINDING C12-E — the GBM-exogenous capture gain mostly does not survive. (NOTE C11-01 (iii): answered, one of three.)

C11 answered NOTE C8-01 affirmatively on +0.35 / +2.04 / +2.71pp (DE-LU / ES / NO2,
under the GBM). Paired intervals:

| zone | delta | 1 day | 7 days | 14 days |
|---|---|---|---|---|
| DE-LU | +0.35pp | [−1.83, +2.53] | [−0.68, +1.40] | [−0.54, +1.24] |
| ES | +2.04pp | [−0.26, +4.38] *(P(≤0)=0.042)* | **[+0.74, +3.60]** | **[+0.88, +3.44]** |
| NO2 | +2.71pp | [−2.50, +8.03] | [−0.79, +6.63] | [−0.68, +6.56] |

DE-LU and NO2 contain zero at every block length — **NO2 despite the largest point
estimate**, because its per-day capture is the noisiest of the nine zones (boot sd 4.19pp
against 1.50–2.60 elsewhere). ES misses at the daily block by a hair and clears at 7 and
14 days; since NOTE C8-01 asked a *directional* question, the one-sided reading (4.2% of
replicates at or below zero) clears 5% even at the daily block.

**NOTE C8-01 is therefore RE-OPENED** (see below): the honest exogenous block under the
booster is supported in ES and unestablished in DE-LU and NO2. The headline honest Tier-A
arm **stays `res_persistence`** — it is not worse anywhere and FINDING C8-A already said
the block costs nothing on MAE — but "it buys +2pp of capture" is one zone's result, not
three.

**The one honest contrast that *is* established** at every block length is
**ES, `gbm_price_only − lear_price_only` = −2.22pp [−4.25, −0.29]**: the booster captures
*less* than the LASSO in the zone where it also has the lower MAE (−1.15%). That is the
one piece of FINDING C11-D's claim (ii) a single validation year does establish, and it
runs against the booster.

#### FINDING C12-F — every zone under-predicts the daily spread

`daily_spread_bias` is **negative in all nine zones**, by 7.9 (ES) to 23.7 (NL) EUR/MWh,
with no exceptions and no near-misses. The forecast day is reliably flatter than the day
that arrives — the regularised model shrinking towards the mean. The direction matters for
C18: it biases the battery towards **under**-trading, which is conservative, and it is
part of why capture sits near 0.9 rather than near 1 even where the ordering is good.
`n_days_spearman_undefined` is 0 in every zone, so no day was dropped for want of an
ordering.

#### The two new metrics, and the shape they are built on

`backtest/metrics.py` gains `spearman_rho`, `daily_shape_table`, `ShapeScores`,
`shape_scores`, `daily_spread_error`, `within_day_spearman` — all additive. Two
properties are load-bearing:

* **A pooled MAE is a ratio of column sums, never a mean of per-day MAEs.** A 23-hour and
  a 25-hour day do not carry equal weight; a mean of daily MAEs says they do. That is the
  DST bug the one-row-per-day shape exists to prevent, and a test pins it.
  `shape_scores` agrees with C3's `score` to 1e-12 on the same hours, which is what lets
  a point error and a dispatch metric sit on one row.
* **Everything is day-additive**, so the bootstrap is a resample of rows and the replicate
  statistic is computed by the same formula as the point estimate.

Ties are averaged (Pearson on average ranks *is* Spearman) rather than broken in index
order — the test uses a case where the two rules give 0.9487 and 0.8, because European
market days carry identical consecutive clearing prices often. A flat day's rho is `nan`
and is **counted**, never dropped into a flattering denominator.

Every metric is computed on **exactly the hours the capture ratio is pooled over** —
C11's discipline carried forward, and not cosmetic: ES's exogenous join has 145 missing
hours, so reusing C10's own-coverage MAE would pair a capture delta with an MAE delta from
a different sample and make the whole of FINDING C11-D an artefact of two samples.

#### The bootstrap, and the one warning in it

`backtest/bootstrap.py`: circular moving-block, **paired** (one draw applied to every
zone, curve and statistic in a replicate), 10 000 replicates, seed 20261009, percentile
interval. The day is the resampling unit because the day is this project's unit of
everything else. Two bases: each zone's `common_hours` day set (365, or 357 in ES), and
the nine-zone comparable arm's 365 days — **verified to be the same calendar days in all
nine zones**, which is what makes the cross-zone band a paired statistic. ES's 357-day set
is a subset of that basis, so the FINDING C11-D correlation draws on the 365-day basis and
projects; ES contributes ~357/365 of each replicate's draws, which widens its own interval
slightly and is recorded rather than hidden.

**Warning for C13/C15: a wider block does not mean a wider interval.** At n = 365 a
14-day block leaves ~26 independent blocks and the long-run variance estimate gets noisy —
here it comes out *narrower*, not wider. So the ladder (1 / 7 / 14) is a robustness check,
not an ordering, and the conservative reading is **the rung least favourable to the claim
being made**, which for FINDING C12-B is the 1-day rung and not the 7-day one.

The null-band test is the load-bearing statistical primitive, so it is tested for
**calibration**: on eight groups drawn from one distribution it must not call the band
significant (at most 2 of 12 draws below 0.05), and on one group shifted far out it must
return p < 0.01. A band test that cried wolf would make FINDING C12-A an artefact of the
test file.

#### The results store

**1 341 rows appended**, run `C12-20261009T102850Z-4d32f5e9`; the store is now
**3 426 rows across 3 runs**, `verify_append_only()` green, and the 2 085 committed
C10+C11 rows are **byte-for-byte unchanged** (the new file's first 608 226 bytes are
identical to `git show HEAD:backtest/results/results.csv`, and the diff is 1 341
insertions / **0 deletions**). **No schema change and no test edit were needed** — the
third cycle running in which long format made the metric name the extension point.

New point metrics at both scopes: `daily_spread_{mae,bias,rmse}_eur_per_mwh`,
`within_day_spearman_{mean,median,p05}`, `rmae_vs_naive_on_dispatched_hours`. Interval
bounds (`_ci_low` / `_ci_high` / `_boot_sd`) at the **headline block length only** for six
metrics — the block length, replicate count and seed live in the run note and the
artefacts, because a metric name that encoded them would make the ladder unreadable; the
full ladder is in `c12_intervals.csv`. Paired contrasts are written on the **treatment**
row as `{capture_delta_pp,mae_pct_gain}_vs_<baseline curve>`, with the baseline in the
name because the store's key identifies one series and a difference is about two.
`evaluation_years` is `2024` on all 3 426 rows.

#### Data: no fetch at all

NOTE C2-02 — `data/raw/` was empty on arrival again, and **for the first time it did not
matter**: C12 reads C11's per-day dispatch artefact and the C4/C8/C9/C10 prediction files,
and the realised prices it needs are those files' own `y_true` column (which C11 had
already verified equal to the price cache, hour for hour, to 0 EUR/MWh). So no
Energy-Charts pull, no ENTSO-E pull, no manifest regeneration, and no `payload_sha256`
re-verification was possible or needed. **0 network requests, 0 FLAGs.** This is the
shape later reporting cycles should prefer.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count **0**,
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, no `*2025*` file exists anywhere
under `data/`, no price file was opened at all, every `market_day` in every C12 artefact
is in 2024, and `evaluation_years` = `2024` on all 3 426 store rows. The 48 occurrences of
the string `2025` across the C12 artefacts and the store were checked **programmatically**
rather than by eye — each one's full comma/quote-delimited token was matched against a
numeric literal, and all 48 are digits inside floats (`-68.12025300000002`, `34.220252`,
`20250.5689464276`, `0.9062025870440182`); **zero non-numeric `2025` tokens.** No 2025
data has been fetched, loaded, dispatched or computed against at any point in C2–C12.

#### Config hash and libraries

Config hash **`515d4e8d98887256`** — unchanged from C8; C12 modified no `config/*.yaml`
(verified with `git diff --stat HEAD -- config/`, empty). Library fingerprint
**`856fb19ac0c4eecd`** — identical to C10's and C11's (python 3.11.17, numpy 2.4.6,
pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1, lightgbm 4.7.0), so C10, C11 and C12 rows
are directly comparable. The GBM config fingerprint `a366a760e269bba6` was not touched.

#### Built and committed (51 new tests, 607 in total)

- `backtest/metrics.py` — **additive only**: the per-day shape table and the two PLAN.md
  decision-relevant metrics.
- `backtest/bootstrap.py` — the circular moving-block day bootstrap, the paired interval,
  the `noise_only_spread` null-band test and row-wise Spearman.
- `backtest/run_c12_metrics.py` — the CLI: `CurveDays`, `Basis` (with `restricted`),
  `point_metrics`, `curve_replicates`, `check_c11_reproduction`, `contrast_intervals`,
  `cross_zone_analysis` over `CANDIDATE_METRICS`, `mae_vs_capture_correlation`,
  `decidability`, `store_rows`.
- `tests/test_c12_metrics.py` — 51 offline tests: the two new metrics on hand-made price
  vectors, the pooled-MAE-is-a-ratio-of-sums property, tie averaging, the bootstrap's two
  analytic end points, the null-band **calibration** test, and FINDINGs C12-A..C12-F each
  pinned against the artefacts this cycle committed so a later cycle cannot quietly
  promote MAE back or re-report a gain this one could not establish.
- `docs/metrics_layer.md` — the full write-up, including a **Limitations** section (one
  year, approximate percentile coverage, the block-ladder warning, n = 9 and n = 15, no
  multiplicity correction, what the null-band test assumes).
- `backtest/results/c12_daily_metrics_2024.csv.gz` (**16 440 rows** — the dispatch columns
  joined to the shape columns, the artefact C13/C15 should read rather than rebuilding the
  join), `c12_metrics_table.csv` (90 rows), `c12_intervals.csv` (1 269 rows, the full
  ladder), `c12_contrasts.csv` (63 rows), `c12_metrics_summary.json`, and the 1 341 new
  store rows.
- `requirements.txt` — a comment block recording that C12 added no dependency, and why
  the Spearman is not `scipy.stats.spearmanr`.

#### Notes for later cycles

**NOTE C8-01 — RE-OPENED by C12.** C11 closed it affirmatively for the booster on point
estimates of +0.35 / +2.04 / +2.71pp. Two of the three intervals contain zero at every
block length and the third (ES) depends on the block length. The question is now "is the
honest exogenous block worth having under the booster *outside ES*", and the answer needs
a second evaluation year, not more arms. C13 should report the three deltas per year.

**NOTE C12-01 (new, for C13).** Both of C12's unresolved questions reduce to the same
thing: one validation year decides too little. FINDING C12-B's eight-zone band (p = 0.078
at the daily block), FINDING C12-D's rank correlation ([−0.53, +0.56]) and FINDING C12-E's
two unestablished zones all want a second year. C13's per-year tables should therefore
report, for each year: the eight-zone capture band with its noise-only p, the three
GBM-exogenous capture deltas with intervals, and NO2's capture and within-day Spearman.
The machinery is reusable as-is — `backtest/bootstrap.py` takes any day-additive column —
but **it needs per-day dispatch rows for the other years, which do not exist yet**: C11
dispatched 2024 only. That is the one piece of new computation C13 would need, and it is
C13's call whether that is in scope or a C15 item.

**NOTE C12-02 (new, for C13/C15, supersedes nothing in NOTE C11-02).** FINDING C11-B's
thin-spread mechanism for NO2 now has a **rival** candidate with better cross-zone support:
the within-day ordering (NO2 ρ = 0.578 vs 0.71–0.89). C15's throughput-cost ladder
(0 / 2 / 5 EUR/MWh) is the direct test of the *thin-spread* story and should be read as
such; it is **not** a test of the ordering story, which predicts instead that NO2's capture
stays low at zero throughput cost while its within-day Spearman stays the lowest of the
nine. Running both predictions against the same ladder is cheap and distinguishes them.

**NOTE C12-03 (new, for C18 — wording, not computation).** Three C11/C10 claims now have
a required label and must not travel without it: FINDING C11-A's eight-zone band is **not
established** (FINDING C12-B); FINDING C11-D is **undetermined, not contradicted**
(FINDING C12-D); FINDING C10-A's "near-constant relative skill" is now
**"indistinguishable from constant"**, which is stronger and should be stated that way.
And FINDING C12-C gives C18 its model-ranking instrument: rank arms on the within-day
Spearman, translate to EUR/MW/yr with capture, and do not rank on capture at one year.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `c9a9ef8` with local
`master` stale 15 commits behind. **27 recurrences out of 34 containers.** `HEAD` equalled
`origin/master` exactly (0 ahead, 0 behind), so nothing was at risk and
`git checkout -B master` was permitted; the cycle worked on a properly attached `master`
throughout. C9's warning still stands for a container that arrives detached *and*
genuinely behind the remote: flag rather than improvise. Keep checking
`git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the start of
every cycle.

**Next:** C13 — regime analysis: the 2022 crisis year reported separately, per-year tables,
pre/post 2025-10-01 flagged, negative-hour counts per zone. Read **NOTE C12-01 first**: the
per-year tables are also the second-year test that FINDINGs C12-B, C12-D and C12-E are all
waiting on, and the per-day dispatch rows for years other than 2024 **do not exist yet**
(C11 dispatched 2024 only), so C13's first decision is whether producing them is in scope.
Quote `capture_rolled_oracle_cash`, never `capture_same_start_pooled` (FINDING C11-C), and
carry the labels NOTE C12-03 requires. The 2025 holdout stays SEALED until Checkpoint C.

### C13 — 2026-10-09 (scheduled cycle) — five evaluation years, and the year effect nobody had measured

Scope per PLAN.md C13: *"Regime analysis: 2022 crisis year reported separately; per-year
tables; pre/post 2025-10-01 flagged; negative-hour counts per zone."* Done, all four
parts, nine zones × five years. **One FLAG raised (FLAG C13-01, explained and not a
bug)**, no checkpoint, no blocker, no new dependency. Full write-up in
`docs/regime_analysis.md`.

NOTE C12-01 left C13 one decision: the per-year tables need per-day dispatch rows for
years other than 2024, which did not exist, and whether producing them was in scope was
C13's call. **It was in scope and it ran**: 36 new walk-forward runs (nine zones ×
2020-2023) of the nine-zone comparable arm, 36 new dispatch runs through the same
rolling LP, and C12's metric and bootstrap layer imported rather than re-derived.

**Full suite: 640 passed, 0 failed, 51 warnings** (607 before C13 + 33 new). The 51
warnings are the same pre-existing sklearn LARS notices from the C8 LEAR tests.
`tests/` (every pre-existing file), `config/`, `forecast/`, `dispatch/`, `data/`,
`backtest/walk_forward.py`, `backtest/metrics.py`, `backtest/bootstrap.py`,
`backtest/results_store.py` and every earlier cycle's runner are **untouched** —
verified with `git diff --stat HEAD` over exactly those paths, which came back empty.
The cycle is one new runner (`backtest/run_c13_regime.py`), one new test file
(`tests/test_c13_regime.py`, C11/C12's precedent — a *new* file is not the
flag-and-stop event, editing a pre-existing one is), one new document, a comment block
in `requirements.txt`, and new artefacts.

#### What was reused, and why the 2024 column is the published number

2024 is **not** re-dispatched: C12's committed per-day artefact is re-pooled, and the
result is checked against the committed store rows **before** any per-year claim is
made, in two passes, with the run exiting non-zero on a disagreement:

* **`own_coverage`, nine zones — 171 checks, worst absolute delta 1.24e-05, all hold.**
* **`common_hours`, the six Tier-B zones — 120 checks, same worst delta, all hold.**
  Tier B is where this works: C11's Tier-B curve inventory *is* C13's three curves, so
  the day set is the same one and the **point-error** metrics (MAE, RMSE, bias, rMAE)
  reproduce as well. Tier A's C11 intersection is over nine curves and deliberately is
  not C13's basis.

The worst delta is the known C11-vs-C12 annualisation-order difference on
`eur_per_mw_year_lost_vs_oracle` (~1e-8 relative on a ~6 000 EUR figure), carried at
C12's stated tolerances. `tests/test_c13_regime.py` nudges one capture ratio by 1e-6 and
confirms the check catches it.

#### FINDING C13-A — a zone's capture ratio moves across years by as much as the eight zones differ from each other within a year

`capture_rolled_oracle_cash`, comparable LEAR arm, `common_hours`:

| zone | 2020 | 2021 | 2022 | 2023 | 2024 | across-year band |
|---|---|---|---|---|---|---|
| BE | 0.8170 | 0.7443 | 0.7544 | 0.8733 | 0.9044 | 16.0pp |
| DE-LU | 0.8652 | 0.7749 | 0.8238 | 0.8983 | 0.9187 | 14.4pp |
| DK1 | 0.7660 | 0.7221 | 0.7539 | 0.8082 | 0.8358 | 11.4pp |
| ES | 0.7522 | 0.7107 | 0.7980 | 0.8762 | 0.9109 | 20.0pp |
| FR | 0.8672 | 0.8032 | 0.7757 | 0.8752 | 0.8526 | 10.0pp |
| IT-North | 0.8302 | 0.8085 | 0.8553 | 0.8923 | 0.9042 | 9.6pp |
| NL | 0.8080 | 0.7521 | 0.7996 | 0.8814 | 0.9031 | 15.1pp |
| **NO2** | **−0.5222** | **0.4480** | **0.5230** | **0.6279** | **0.6146** | 18.0pp (ex-2020) |
| PL | 0.6875 | 0.7238 | 0.8118 | 0.7541 | 0.8839 | 19.6pp |

The within-zone across-year band is **9.6-20.0pp** in the eight non-outlier zones,
against a single year's bootstrap sd of 2.8-5.1pp — so the year effect is **2.3-5.4× its
own sampling noise**. The eight-zone band *within* a year is 8.3-18.0pp: **the same
size**. **A capture band measured in one year cannot be read as a regime effect**,
because re-measuring one zone in a different year produces a band just as wide. Note
also that **2024 is the most favourable year in the sample** (highest capture in six of
nine zones) — every C10-C12 headline rests on the best year of five, and C18 must say so.

#### FINDING C13-B — FINDING C12-B is settled: the eight-zone capture band is NOT established

Noise-only null band at PLAN.md's literal daily block:

| year | band ex-NO2 | noise-only p | nine-zone band | noise-only p |
|---|---|---|---|---|
| 2020 | 17.98pp | 0.095 | 138.95pp | 0.053 |
| 2021 | 9.78pp | **0.846** | 36.05pp | 0.0098 |
| 2022 | 10.15pp | **0.523** | 33.23pp | 0.0004 |
| 2023 | 14.42pp | 0.015 | 27.04pp | 0.0006 |
| 2024 | 8.29pp | 0.078 | 30.40pp | <1e-4 |

**One of five years clears 5%**, and in 2021 and 2022 the eight zones' capture ratios
are indistinguishable from eight draws of one number. The **nine-zone** band clears in
four of five. So FINDING C11-A is confirmed as **a finding about NO2 plus a direction**,
now in five years rather than argued from one. C12's required label stands and is now
evidenced: **C18 must not quote the 8.3pp eight-zone band as established.**

#### FINDING C13-C — NO2 is bottom on capture *and* on within-day ordering in all five years

NO2's within-day Spearman: 0.470 / 0.592 / 0.650 / 0.615 / 0.578 against 0.699-0.886
elsewhere, **every year**. The cross-zone capture ranking replicates moderately between
year pairs (Spearman +0.33 to +0.88, positive in all ten pairs) and NO2 is last in
**10 of 10**. FINDING C11-B is the one C11/C12 claim five years makes *stronger*.

#### FINDING C13-D — neither the forecast error nor the price spread predicts capture; their ratio does

Across the 44 usable (zone, year) cells, rank correlation with capture:

| cell predictor | ρ vs capture | ex-NO2 |
|---|---|---|
| **MAE ÷ mean realised daily spread** (`error_over_headroom`) | **−0.738** | **−0.682** |
| within-day Spearman | +0.698 | +0.599 |
| oracle value EUR/MW/yr | +0.331 | +0.249 |
| mean realised daily spread | +0.256 | +0.203 |
| MAE | **−0.015** | −0.071 |

MAE alone carries **no** cross-cell information about capture — the flat version of what
FINDING C11-D/C12-D could only call undetermined at one year — and the spread alone
carries little. The per-year cross-zone version of the ratio has an interval excluding
zero in **three of five years at the daily block and five of five at 7 and 14 days**
(−0.43 to −0.73). It also explains FINDING C13-A's year effect: the mean
error-to-headroom ratio falls 0.287 (2021) → 0.217 (2024) while mean capture rises
0.721 → 0.859, and the mean spread rises six-fold from 2020 to 2022 with capture barely
moving. `error_over_headroom` is now a store metric at every (zone, year, curve).

#### FINDING C13-E — NOTE C12-02 answered: the thin-spread story does not explain NO2

Fit capture on log(mean realised spread) over the **other eight** zones' 40 usable cells
(slope +0.0196 per log unit, residual sd 6.35pp) and ask where NO2 lands:

| year | NO2 capture | predicted from the eight-zone line | residual |
|---|---|---|---|
| 2021 | 0.4480 | 0.8030 | **−35.5pp** (−5.6 sd) |
| 2022 | 0.5230 | 0.8264 | **−30.3pp** (−4.8 sd) |
| 2023 | 0.6279 | 0.8111 | **−18.3pp** (−2.9 sd) |
| 2024 | 0.6146 | 0.8101 | **−19.5pp** (−3.1 sd) |

Conditioning on the realised spread removes **almost none** of NO2's deficit. A
thin-spread mechanism predicts NO2 lands *on* the line; it sits 2.9-5.6 residual sd
below it in every non-thin year, while its within-day Spearman is the lowest of the nine
in all five. **The ordering mechanism (FINDING C12-C) survives and the thin-spread one
does not.** C15's throughput-cost ladder now has a prior answer to beat rather than an
open question — NOTE C12-02 is closed, and the ladder is still worth running for the
*level* of the frictions (see FLAG C13-01).

#### FINDING C13-F — the 2022 crisis multiplied the prize and the loss by ~2.5× and left the captured share alone

Per zone, 2022 against the mean of that zone's other usable years (**unpaired**
intervals — two years share no market day):

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

Eight of nine captured a lower share, **one** interval excludes zero. The crisis is
unmistakable in the levels (perfect foresight earned 1.7-2.7× its usual; the money left
on the table rose to 2.4-4.2×) and close to invisible in the ratio. **A crisis is a
bigger prize and a proportionally bigger loss, not a worse hit rate.**

#### The negative-hour counts PLAN.md asks for, per (zone, year)

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

Two structural facts to have before any cross-zone claim: negative prices nearly
**vanish** in the crisis year (308 hours across nine zones, the fewest of the five) then
rise **3.3×** from 2023 to 2024; and **ES printed its first negative hour of the whole
window in 2024** (247 of them) while **IT-North has never printed one**. A claim about
negative pricing is a claim about a year. Full regime table (mean/median/sd/min/max,
zero hours, hours >200, daily-spread mean/median/p95) in `c13_regime_table.csv`.

**The counts cross-check C1's committed manifest, hour by hour.** 42 of 45 zone-years
agree exactly. The three that differ — DE-LU, NL and BE in 2023 — differ by exactly one
hour, and the check *explains* rather than tolerates it: this cycle counts over the
local market days of the year, C1's manifest over the fetched window starting 00:00Z on
01-01, so the local market year reaches one hour further back, and that hour
(2022-12-31T23:00Z = midnight local on 1 Jan 2023) cleared at **−5.17 / −3.61 / −4.39
EUR/MWh** in those three zones and at exactly **0.00** in FR, which is why FR agrees.
`0 unexplained differences`; an unexplained one fails the analyse phase.

#### Pre/post 2025-10-01 — a flag, not a split (`c13_cutover_status.json`)

Nothing in this project has crossed the SDAC 15-minute go-live: `config/data.yaml` stops
fetching at 2024, the main hourly backtest ends 2025-09-30, and the cutover falls
**inside the sealed 2025 holdout**. So the flag is a statement about the evaluated
window: every price hour behind every C13 number was served at 60-minute resolution
(`resolution_seconds = 3600` on all 54 manifest zone-years), every evaluated market day
is before 2025-10-01, `post_cutover_rows = 0`. `data/contracts.py` already carries the
resolution-change detection that would catch a post-cutover file. PLAN.md's native
15-minute analysis stays a labelled C15+ stretch goal.

#### FLAG C13-01 — NO2 2020 fails CLAUDE.md's pooled naive-dominance invariant

**This is a regime fact, not a bug, and the assertion was not weakened.**

The numbers: in NO2 2020 the comparable LEAR arm settles **−402 EUR/MW over the year**
against the naive floor's **+253 EUR/MW** (margin −655 EUR, per-day win rate 15.9%); the
**perfect-foresight** battery itself earns only **769 EUR/MW/yr**; the mean realised
daily spread is **3.41 EUR/MWh** against a 2 EUR/MWh throughput cost and a 12%
round-trip loss; capture is **−0.5222**. NO2's 2020 mean price was **9.3 EUR/MWh** — a
Nordic hydro glut. A battery trading a 3.4 EUR/MWh daily range while paying 2 EUR/MWh
per MWh discharged has no headroom at all, so which of two curves trades *less* is luck,
and CLAUDE.md's own qualification of this invariant ("on average, not per-day") is the
relevant one: it is an empirical claim about an average over regimes, and this is the
regime where it fails.

What the cycle did:

* The check still runs on every zone-year and still reports `holds: false` here. **No
  tolerance was widened and no test was edited** to make it pass.
* The per-day **same-start oracle bound** — the actual theorem — **holds on all 26 262
  (curve, day) checks across the 36 zone-years dispatched here, worst per-day excess
  over perfect foresight exactly 0.0 EUR**, as do the settlement-is-not-a-readback and
  decision-value-added checks on every curve of every zone-year.
* The dispatch phase **records** the failure in `backtest/results/c13_invariant_flags.json`
  and **exits non-zero**; it no longer aborts the remaining zone-years, so the failure
  is neither swallowed nor allowed to skip work that does not depend on it.
* The cell is reported everywhere and **excluded from the cross-zone band statistics and
  from every baseline average**, under a **declared floor**: a (zone, year) whose
  *perfect-foresight* battery earns under **2 000 EUR/MW/yr** is a cell where the capture
  ratio's denominator is noise. One of 45 cells is flagged; the gap is an order of
  magnitude (769 against 8 992 for the next thinnest), and `label_count_by_floor` shows
  **no floor between ~1 000 and ~8 000 EUR/MW/yr changes a single label**.

The economically interesting reading favours the write-up: **a 2 EUR/MWh throughput cost
is not a rounding error in a thin market, it is the whole result.** C15's throughput-cost
ladder now has a zone-year whose answer is known in advance.

#### The results store

**4 824 rows appended**, run `C13-20261009T192245Z-48a713ec`; the store is now **8 250
rows across 4 runs**, `verify_append_only()` green, and the 3 426 committed C10-C12 rows
are **byte-for-byte unchanged** (the new file's first 992 193 bytes are identical to
`git show HEAD:backtest/results/results.csv`). **No schema change and no test edit were
needed** — the fourth cycle running in which long format made the metric name the
extension point, and the first in which a new *evaluation year* is simply new rows:
1 206 per year, `evaluation_years` ∈ {2020, 2021, 2022, 2023}, two scopes, 42 distinct
metric names including `error_over_headroom` and the headline-block interval bounds.
**2024 rows are not rewritten** — C11 and C12 wrote them, and two rows with different
provenance behind one number is what the append-only store exists to prevent.

One contract detail worth recording: `SCOPES` in `backtest/results_store.py` is a closed
list (`own_coverage`, `common_hours`). C13's three-curve intersection *is* C11's
`common_hours` definition applied to this cycle's curve set, so it is written under that
name rather than editing the store's contract to add a third spelling. In Tier A that is
**not** the same day set as C11's 2024 `common_hours` (nine curves); every C13 row
carries its `source_artefact`, and `docs/regime_analysis.md` §3 states it.

#### Data: 54 price pulls, every payload hash identical to C1's

NOTE C2-02 — `data/raw/` was empty on arrival again (**24th recurrence**), and unlike
C12 this cycle **did** need prices: 36 walk-forward runs cannot be built from committed
prediction artefacts. So `data.fetch_prices` ran for all nine zones × 2019-2024:
**54 downloaded, 0 already cached, 0 flagged**. Before any fitting, every cached file was
re-summarised and compared against the committed manifest: **all 54 `payload_sha256`,
`n_points`, `n_negative`, `n_nan`, `price_min` and `price_max` values are identical to
C1's.** The re-fetch is byte-identical data, so the manifest was **not** regenerated or
re-committed (C8/C9/C10's precedent). No ENTSO-E pull: `ENTSOE_API_KEY` was neither
needed nor read, because the comparable arm has no exogenous block.

#### Sealed holdout

**SEALED.** Verified after the work: marker-alone-on-a-line count **0**,
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises, no `*2025*` file exists anywhere under `data/`,
cached years are exactly 2019-2024, every `market_day` in every C13 artefact is in
2020-2024, and `evaluation_years` ∈ {2020, 2021, 2022, 2023} on all 4 824 new store rows
(2020-2024 across all 8 250). The **362** occurrences of the string `2025` across the C13
artefacts and the store were checked **programmatically**: 356 are digits inside floats
and the remaining **6 are the cutover date strings** `2025-10-01` / `2025-09-30` copied
from `config/data.yaml`'s `structural_dates` into `c13_cutover_status.json` and
`c13_regime_summary.json` — which is PLAN.md C13's own "flag the cutover" requirement,
and contains no 2025 *data*. `load_daily_by_year` and `regime_price_table` both refuse a
sealed year **before any path is built**, and two tests pin that. No 2025 data has been
fetched, loaded, dispatched or computed against at any point in C2-C13.

#### Config hash and libraries

Config hash **`515d4e8d98887256`** — unchanged since C8; C13 modified no `config/*.yaml`.
Library fingerprint **`856fb19ac0c4eecd`** — identical to C10's, C11's and C12's (python
3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1, lightgbm 4.7.0), so
C10-C13 rows are directly comparable. The GBM config fingerprint `a366a760e269bba6` was
not touched and no hyperparameter was tuned.

#### Built and committed (33 new tests, 640 in total)

- `backtest/run_c13_regime.py` — four phases: `compute` (the 36 walk-forward runs,
  parallel-safe per zone), `dispatch` (the 36 LP runs, recording invariant flags instead
  of swallowing or aborting), `analyse` (the per-year tables, the band tests per year,
  the crisis comparison, the year-stability block, the spread/headroom analysis, the
  regime table, the manifest cross-check, the cutover flag, the 2024 reproduction), and
  `ingest`.
- `tests/test_c13_regime.py` — 33 offline tests: the three-curve basis, the *unpaired*
  year-on-year difference (its sd must be ~√2× a single arm's, so a quietly paired
  interval cannot slip through), this cycle's shape table on hand-made days, the
  sealed-year guards, the 2024 reproduction **and its ability to fail**, the store rows,
  the manifest cross-check's hour-by-hour explanation, and FINDINGs C13-A..C13-F each
  pinned to the artefacts this cycle committed.
- `docs/regime_analysis.md` — the full write-up, including the honesty label (§2), the
  FLAG (§8), what the cycle did not do and why (§9) and its own Limitations (§10).
- Artefacts: 36 × `c13_year_<ZONE>_<YEAR>_{predictions.csv.gz,folds.csv,summary.json}`,
  36 × `c13_dispatch_<ZONE>_<YEAR>_{daily.csv.gz,summary.json}`,
  `c13_daily_by_year.csv.gz` (**49 284 rows** — the artefact C15/C17 should read rather
  than re-dispatching), `c13_per_year_metrics.csv` (270 rows), `c13_year_intervals.csv`,
  `c13_regime_table.csv` (45 rows), `c13_regime_summary.json`, `c13_cutover_status.json`,
  `c13_invariant_flags.json`, and 4 824 new store rows.
- `requirements.txt` — a comment block recording that C13 added no dependency.

#### Notes for later cycles

**NOTE C13-01 (for C18, wording — read with NOTE C12-03).** Three labels are now
*evidenced* rather than cautionary: the eight-zone capture band is **not established**
(one of five years clears 5%, FINDING C13-B); the cross-zone capture finding is **a
finding about NO2 plus a direction** (FINDING C13-C); and **2024 is the most favourable
year of the five**, so every C10-C12 headline must travel with "in the validation year,
which is the best of the five evaluated". A fourth is new: **a one-year capture band
cannot be called a regime effect** when one zone re-measured in another year moves just
as far (FINDING C13-A).

**NOTE C13-02 (for C15).** The throughput-cost ladder (0 / 2 / 5 EUR/MWh) is no longer
the test of NO2's mechanism — FINDING C13-E settled that against the thin-spread story.
Run it instead for the thing FLAG C13-01 exposes: **how much of the capture ratio is
friction**, which the ladder measures directly, and where the break-even spread sits.
NO2 2020 is the natural stress cell (oracle 769 EUR/MW/yr, mean spread 3.41 EUR/MWh,
capture −0.52); at a 0 EUR/MWh throughput cost its capture should rise sharply if
friction is the binding constraint there, while FINDING C13-E predicts NO2's *relative*
deficit in the other four years barely moves. `c13_daily_by_year.csv.gz` and the 36
prediction artefacts mean the ladder needs **no re-fitting**, only re-dispatch.

**NOTE C13-03 (for C14/C15, new).** `error_over_headroom` (pooled MAE ÷ mean realised
daily spread) is the strongest cell-level predictor of capture this project has found
(ρ = −0.74 over 44 cells, −0.68 ex-NO2, against MAE's −0.015). It is now a store metric.
C14's residual-load chapter should ask the obvious follow-up — **does residual-load
forecast error explain `error_over_headroom` across Tier-A zones and years?** — and C18
should use it as the bridge from a point-forecast metric to EUR/MW/yr, alongside the
within-day Spearman (FINDING C12-C).

**NOTE C13-04 — the Tier-A exogenous/GBM per-year deltas were NOT computed, with
reasons.** NOTE C12-01 asked C13 for the three GBM-exogenous capture deltas per year.
They are not here, because: (i) **only one new year is even available** — those arms are
aligned to `train_from=2022-01-01` (no archived ENTSO-E D-1 vintage exists earlier) and
the harness needs 365 market days of history, so the honest evaluation years for an
exogenous arm are 2023 and 2024, i.e. one extra draw, which is the same "one year
decides too little" problem in a new coat; (ii) it needs a **fresh ENTSO-E pull** (three
zones × two document types × two years, one of them ~13 MB of XML per zone-year) because
`data/raw/` does not survive a container; (iii) PLAN.md C13 is the regime analysis and
NOTE C12-01 left the call to this cycle. **NOTE C8-01 therefore stays RE-OPENED**, and
the right home for it is the next cycle that must re-pull ENTSO-E data anyway — **C14**,
whose residual-load chapter needs exactly those load/wind/solar series for Tier A. C14
should fold the 2023 exogenous ladder in while it has the data, or say why not.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `0116440` with local
`master` stale 16 commits behind. **28 recurrences out of 35 containers.** `HEAD`
equalled `origin/master` exactly after a fetch (0 ahead, 0 behind), so nothing was at
risk and `git checkout -B master` was permitted; the cycle worked on an attached
`master` throughout. C9's warning still stands for a container that arrives detached
*and* genuinely behind the remote: flag rather than improvise.

**Next:** C14 — the fundamentals chapter: price vs residual load (load − wind − solar)
per Tier-A zone, merit-order commentary. It needs a fresh ENTSO-E pull (`data/raw/` is
gone again), so read **NOTE C13-04** first and fold in the 2023 exogenous/GBM ladder
while the data is there, which closes NOTE C8-01. Read **NOTE C13-03** for the question
C14's own chapter is best placed to answer. PLAN.md's buffer note allows cutting C14 if
behind — C13 finished on schedule, so it is not cut. The 2025 holdout stays **SEALED**
until Checkpoint C (C16).

### C14 — 2026-10-10 (scheduled cycle) — the fundamentals chapter, and a mechanism for NO2

Scope per PLAN.md C14: *"Fundamentals chapter: price vs residual load (load −
wind − solar) per Tier-A zone, merit-order commentary."* Done, plus both notes
C13 handed forward: **NOTE C13-03** (does residual-load forecast error explain
`error_over_headroom`?), which is answered and turned out to supply the
mechanism FINDING C12-C asked for; and **NOTE C13-04** (the 2023 exogenous
ladder), which ran in full and **closes NOTE C8-01 — the answer is no**. Full
write-up in `docs/fundamentals.md`.

**Full suite: 708 passed, 0 failed, 51 warnings** (640 before C14 + 68 new). The 51
warnings are the same pre-existing sklearn LARS notices from the C8 LEAR tests that
C13 recorded; C14 adds none.

**No checkpoint, no blocker, no new dependency.** The cycle is one new runner
(`backtest/run_c14_fundamentals.py`), one new test file
(`tests/test_c14_fundamentals.py`, 68 tests — C11/C12/C13's precedent, a
*new* file is not the flag-and-stop event, editing a pre-existing one is), one
new document (`docs/fundamentals.md`), three figures, a `requirements.txt`
comment block, and new artefacts.

#### The one genuinely new judgement this cycle had to make

C3-C13 all asked *what could a bidder have known at gate closure*. C14 asks
*what set the price*, and that changes which vintage is allowed. The Art. 14
wind/solar D-1 forecast is published 18:00 local on D-1 — **six hours after**
gate closure — which makes it unusable as a **model input** (the whole subject
of C8) and leaves it the closest thing in PLAN.md's scope to **realised** wind
and solar. This cycle uses it descriptively and draws the line in code:

* `FUNDAMENTALS_VINTAGE = "after_gate_closure"` on every descriptive artefact
  and every descriptive store row — **228 of this cycle's 315** — so
  `honest_rows()` excludes all of them. The other 87 are the 2023 ladder's own
  capture and MAE figures, which are about real forecasts and are filed
  `honest` (its two late arms excepted).
* `assert_descriptive_only()` is a callable that **raises**, naming the
  publication clock. A later cycle that imports `fundamentals_frame` and hands
  the result to a feature builder gets a refusal, not a silent leak. Two tests
  pin it, including that a frame mislabelled `honest` is refused *for the label*
  — the earlier of the two errors.
* The descriptive rows are filed under the **oracle's** `(model, exog_variant)`
  identity, because there is no forecast behind an R² of the realised price on
  residual load. Filing them under a model's key would make them join to that
  model's MAE as if they described it.

**The limitation is stated, not engineered around**: the residual load behind
every figure is a *forecast* of residual load. The fix is an ENTSO-E actuals
pull (A65/A16, A75) and that is outside PLAN.md's declared data scope. C18
inherits this.

#### FINDING C14-A — the merit order is a DE-LU and ES fact, and barely an NO2 one

`r2_piecewise_linear_20` (price on a per-bin intercept-and-slope fit of D-1
forecast residual load), with the clock-only control beside it:

| zone | 2022 | 2023 | 2024 | calendar-only | gain over the clock |
|---|---|---|---|---|---|
| DE-LU | 0.406 | **0.802** | **0.675** | 0.130 / 0.233 / 0.220 | +0.285 / **+0.586** / +0.470 |
| ES | 0.264 | 0.650 | 0.555 | 0.096 / 0.238 / 0.168 | +0.177 / +0.432 / +0.424 |
| **NO2** | **0.044** | 0.361 | 0.323 | 0.042 / 0.066 / 0.089 | +0.051 / +0.332 / +0.282 |

NO2 is last every year on the raw R² **and** on the gain over a clock — a factor
of 2.0-2.2 behind DE-LU in 2023/24 and a factor of **9** in 2022. Spearman
agrees: +0.90/+0.85 (DE-LU), +0.79/+0.74 (ES), +0.59/+0.56 (NO2) in 2023/2024.
And **the crisis year degrades it everywhere** (0.41 / 0.26 / 0.04): the stack
did not change in 2022, its fuel cost did, so residual load stopped pinning the
price *level* even where it still pinned the ordering.

**A methodological trap worth recording, because it bites in the conservative
direction.** The 20-bin *step* function is **not** an upper bound on what
residual load can explain — it discards the variation inside each bin, so on a
smooth relationship it scores *below* the straight line. On a synthetic
exactly-linear zone it returns 0.995, not 1.0, and **DE-LU 2024 is the real
case** (step 0.596 against linear 0.601, a discretisation loss of 0.079). The
per-bin intercept-**and-slope** fit nests the straight line, so its R² can never
be lower and `nonlinearity_gain` is curvature rather than curvature minus
discretisation loss. Two tests pin both behaviours. A first draft of this cycle
reported the step fit as the headline and was caught by its own fixture test.
A second draft fitted hour × weekday × bin as the control — ~3 400 cells on
~8 760 hours, 2.6 observations each — and was replaced by an **additive**
calendar block; `n_parameters_*` is now reported for all five fits so the
in-sample caveat is a number rather than a disclaimer.

#### FINDING C14-B — NO2's supply curve slopes the wrong way in 2022

NO2 2022 decile medians run **219.3 → 143.4 EUR/MWh** as residual load rises
2.3 → 4.8 GW: Spearman **−0.177**, slopes **−39.1 / −17.6 / −31.4 EUR/MWh per
GW**, 8 of 9 inter-decile steps *down*. It is the only (zone, year) in the table
with a negative sign.

**A merit order cannot slope down. A hydro reservoir's opportunity cost can.** In
a water-scarce, export-constrained year the price is set by the reservoir's
shadow value and the export arbitrage against the Continent, not by a domestic
thermal stack — and NO2's domestic "stack" is 4 GW of load against 0.5 GW of
wind and **no solar fleet at all**. Hours of high domestic residual load in 2022
were hours when the Continent was not short, so NO2 exported less and priced
lower. (Note: `high_over_mid` is +1.78 here — the ratio of two *negative* slopes
— so the artefact now carries `high_over_mid_is_a_convexity_ratio = False` and a
test pins the trap.)

#### FINDING C14-C — the crisis moved the level and kept the shape

At the median residual-load decile, which holds the quantity axis fixed:

| zone | 2022→2024 level | shape ρ (decile medians) | normalised-curve Pearson |
|---|---|---|---|
| DE-LU | **×0.381** | 1.000 | **0.998** |
| ES | **×0.372** | 0.988 | **0.974** |
| NO2 | ×0.233 | **−0.988** | **−0.898** |

So in the two zones with a real merit order, **2022 priced at 2.6-2.7× 2024 at
the same residual load** while the normalised decile curve correlates 0.97-1.00:
**shifted, not bent**, which is the signature a fuel-cost shock should leave.
This is an independent cross-check on **FINDING C13-F** from the fundamentals
side — C13 measured the perfect-foresight battery earning ×1.72-2.71 its usual
in 2022; this measures the price level at matched fundamentals at ×2.6-2.7.
NO2's negative shape correlation is the *same fact* as FINDING C14-B, not a
second one. Rank correlation alone cannot tell a shift from a steepening (any
two monotone curves rank-correlate at 1), which is why the normalised comparison
sits beside it and a synthetic test pins both.

**What no arm in this project can see:** the fuel-cost axis. PLAN.md excluded the
AGSI+ gas proxy after the audit, so the single largest driver of the 2022 price
*level* is absent by design. FINDING C13-F says that cost little in capture
terms; this says why a 2022 point-forecast MAE looks as bad as it does.

#### FINDING C14-D — negative prices are a bottom-decile event, except in NO2

Share of a zone-year's negative hours falling in its lowest residual-load
decile. **10% is the uniform-spread benchmark.**

| zone | 2022 | 2023 | 2024 |
|---|---|---|---|
| DE-LU | 1.000 (**10.0×**) | 0.980 (**9.8×**) | 0.880 (**8.8×**) |
| ES | no negative hours | no negative hours | 0.882 (**8.8×**) |
| **NO2** | no negative hours | **0.397 (4.0×)** | **0.209 (2.1×)** |

DE-LU and ES sit at **8.8-10.0× uniform**: textbook. NO2 sits at **4.0× and
2.1×**, with only 21-40% of its negative hours in the bottom decile and 47-63%
in the bottom two — so **the majority of NO2's negative hours are not
low-residual-load hours**, and its 2024 figure only just clears a 2× bar where
DE-LU is at ~9×. A negative price in DE-LU is a merit-order event; in NO2 it is
mostly something else, and this project has no data to attribute it (reservoir
levels and corridor flows are outside scope — `docs/audit.md` already records
the absence of NO2/DK1 reservoir data as a known limitation). Naming the
residual it is *not* is as far as the chapter honestly goes.

Two structural facts that refine C13's negative-hour counts: **ES printed its
first negative hour of the whole window in 2024** (237 over the exogenous-join
hours against C13's 247 over the full market year), and **in no (zone, year) is
a negative price more likely than not even in the bottom decile** — DE-LU 2024
comes closest at **0.457**. So "negative prices are normal in the bottom decile"
is not yet true anywhere in Tier A.

#### FINDING C14-E — residual load is nearly a sufficient statistic, except in the crisis

`b_load + b_wind`, which the merit-order restriction sets to zero, with paired
day-block bootstrap intervals (10 000 replicates, seed 20261010, block 1 day):

| zone | 2022 | 2023 | 2024 | R² lost by imposing residual load |
|---|---|---|---|---|
| DE-LU | **−4.21** [−5.17, −3.33] | +0.35 [+0.17, +0.52] | +0.42 [+0.20, +0.66] | **0.068** / 0.004 / 0.013 |
| ES | +1.80 [+0.03, +3.65] | −1.30 [−2.00, −0.58] | −0.51 [−1.29, +0.31] | 0.005 / 0.041 / 0.027 |
| NO2 | **−99.16** [−124.5, −74.6] | −12.50 [−17.36, −7.51] | +0.50 [−3.70, +4.54] | **0.094** / 0.019 / **0.000** |

In DE-LU 2023/24 the restriction is violated but trivially (+0.35 and +0.42
against a load coefficient of ~3.2, so 11-13% of it, and 0.4-1.3pp of R² lost by
imposing it). **In the crisis year it breaks**: DE-LU 2022's wind coefficient
(−9.13) is nearly **twice** its load coefficient (+4.92) — at crisis gas prices a
MW of wind displaced very expensive gas while a MW of extra load was partly met
by cheaper inframarginal plant, so the two were genuinely not interchangeable.
**NO2 2024 is the one cell where the restriction is not rejected** (R² lost
0.00003); residual load is sufficient there, it just explains little.

**Do not compare the per-GW slopes across zones.** NO2's mean load is 4.1 GW and
DE-LU's 53.2, so NO2's 23 EUR/MWh/GW against DE-LU's 3.1 is that artefact and
nothing else. `coef_*_per_10pct_mean_load` is the comparable figure and brings
the three much closer: **16.5 / 14.7 / 9.5** EUR/MWh in 2024. A synthetic test
with two zones differing 10× in size pins this.

**Solar and wind are not interchangeable, and they disagree by zone.**
`b_solar − b_wind` is **−0.33 [−0.50, −0.17]** and **−0.69 [−0.82, −0.55]** in
DE-LU 2023/24 (solar cannibalises *more*) and **+2.23 [+1.65, +2.77]** and
**+1.76 [+1.14, +2.35]** in ES (wind cannibalises more). Both exclude zero in
both years and they point in opposite directions. Reading: solar arrives in a
fixed midday block, so in solar-dominated ES the marginal MW of solar lands in
hours already at the bottom of the stack where there is little price left to
displace, while wind can arrive in any hour and still find a thermal unit on the
margin. **Two zones, two years, with intervals — not an established law.**

#### FINDING C14-F — NOTE C13-03 answered, and it is the mechanism FINDING C12-C asked for

`error_over_headroom` is pooled price MAE ÷ mean realised daily spread, so both
halves got their own question. The predictor is the **day-over-day revision** of
the as-published Art. 14 residual load, computed on the UTC index at a true
24-hour offset (not "yesterday's same local hour", which is 23 or 25 hours twice
a year). **It is a revision, not a forecast error, and a lower bound on the
error a bidder carried** — the only stand-in for realised residual load in scope
is itself a forecast. It is also exactly what C8's `res_persistence` arm has to
live with, which is what makes it the relevant quantity rather than merely the
available one. `RES_ERROR_IS_A_REVISION` carries this on every row, and a test
pins the label. **Nothing was refitted**: the dispatch outcomes are C13's
committed `c13_daily_by_year.csv.gz` rows for the nine-zone comparable arm, so
this `error_over_headroom` *is* the one FINDING C13-D is about.

Spearman over market days, 95% paired day-block intervals. `*` = excludes zero.

| zone | outcome | 2022 | 2023 | 2024 |
|---|---|---|---|---|
| DE-LU | `error_over_headroom` | +0.139* | **+0.500*** | **+0.481*** |
| DE-LU | realised spread | +0.402* | **+0.593*** | **+0.596*** |
| ES | `error_over_headroom` | +0.108* | +0.341* | +0.357* |
| ES | realised spread | +0.618* | +0.578* | +0.352* |
| **NO2** | `error_over_headroom` | +0.078 | +0.160* | +0.241* |
| **NO2** | **realised spread** | **+0.012** | **+0.035** | **+0.020** |

1. **NOTE C13-03 is answered yes, with a zone gradient.** A harder RES day is a
   harder day to capture in DE-LU (≈ +0.49) and ES (≈ +0.35), 2-3× weaker in NO2.
   The effect is largest exactly where the merit order is strongest (FINDING
   C14-A) — which is the mechanism FINDING C13-D's ρ = −0.74 was missing.
2. **The crisis year breaks it again** (+0.14 / +0.11 / +0.08 in 2022).
3. **The headline: NO2's daily price shape has no relationship to its
   residual-load shape.** The day's residual-load *range* against the day's
   realised price *spread* is +0.59/+0.60 in DE-LU and +0.35-0.62 in ES, and in
   NO2 it is **+0.012, +0.035, +0.020 — intervals containing zero in all three
   years, including the crisis.** A robust zero, not a noisy one. And NO2's
   within-day residual-load swing is only **0.26-0.33 of its own mean** residual
   load against 0.64-0.90 (DE-LU) and 0.68-1.18 (ES): the swing is small *and*
   what there is predicts nothing.

**This closes the loop on the project's largest open puzzle.** FINDING C11-B
found NO2 the capture outlier; FINDING C12-C proposed "the forecast puts the
hours in the wrong order"; FINDING C13-E killed the rival thin-spread story;
FINDING C13-C confirmed NO2 last on within-day ordering in all five years. C14
says *why*: **the fundamental that orders the hours in DE-LU and ES does not
order them in NO2 at all**, so a model built on price history and residual load
has nothing to learn NO2's within-day shape from. **This is a falsifiable
prediction for C15**: no change to the throughput cost, the battery duration or
the SoC policy should fix NO2's ordering, because the information is not in the
inputs.

**A sign reversal, and it is *not* a scale artefact — the first draft of this
entry said it was.** Across the nine cells a RES predictor correlates
**negatively** with `error_over_headroom`: raw-MW revision ρ = −0.67, and after
normalising by each cell's own mean residual load, revision ρ = **−0.65** and
daily range ρ = **−0.72**. Normalising does not remove it, so the two levels are
measuring different things and both are real:

* **Between cells** the predictor is *structural RES penetration*. A zone-year
  whose residual load swings by 90% of its own level (DE-LU 2024) has a wide
  spread and so a lot of headroom, making its error small *relative to* that
  headroom. ρ = −0.72 is the same sign and nearly the same size as FINDING
  C13-D's −0.74 for `error_over_headroom` against capture — consistent, not
  contradictory.
* **Within a cell** the predictor is *forecast error on the day*. Holding the
  structure fixed, a day revised more than usual is harder (+0.49 DE-LU, +0.35
  ES).

So NOTE C13-03's complete answer has two layers pointing the same economic way:
**RES build-out creates the headroom, and RES forecast error eats into it.**
Neither layer can be read off the other. Separately, the raw-MW predictors *are*
size proxies across zones (NO2's mean residual load 3.6 GW against DE-LU's
30.0) — the same per-GW trap as FINDING C14-E — so the `*_over_mean` columns are
the ones a cross-zone sentence may use. The nine-cell table carries all of this
in its own `honest_label`.

#### NOTE C13-04 / NOTE C8-01 — the 2023 exogenous ladder

**NOTE C8-01 is CLOSED, and the answer is no.** It ran in full: C8's LEAR
ladder and C9's GBM ladder for 2023, all three Tier-A zones, both runners
unmodified, then C5/C6's rolling LP and C11's `pooled_capture` imported rather
than re-derived.

**FINDING C14-G — the honest exogenous block is not worth having.**
`gbm_res_persistence − gbm_price_only`, capture in pp, daily block:

| zone | 2023 (C14) | 2024 (C11/C12) |
|---|---|---|
| **DE-LU** | **−3.55pp [−6.76, −0.33]** ✱ | +0.35pp [−1.83, +2.53] |
| ES | +0.26pp [−2.15, +2.72] | +2.04pp [−0.26, +4.38] |
| NO2 | +2.39pp [−4.82, +9.78] | +2.71pp [−2.50, +8.03] |

Six cells under the booster, **exactly one excludes zero, and it is negative**.
Under the LASSO all six contain zero. On MAE the twelve cells are all inside
±4% and the sign flips between years in five of six (zone, model) pairs — so
**FINDING C8-A replicates in a second year and strengthens**: the block is worth
nothing, and which side of nothing it falls on is noise. **C18 must not claim an
exogenous gain.**

**FINDING C14-H — the leak is worth what the merit order is worth.** The GBM
vintage premium against FINDING C14-A's R², six cells, **strictly monotone,
Spearman 1.0, zero inversions**: DE-LU 2023 (R² 0.802 → 28.13%), DE-LU 2024
(0.675 → 23.97%), ES 2023 (0.650 → 23.21%), ES 2024 (0.555 → 17.48%), NO2 2023
(0.361 → 7.25%), NO2 2024 (0.323 → 3.48%). A factor of eight, perfectly ordered.
**Suggestive, not established**: the two axes are not independent (a zone where
RES sets the price is mechanically one where knowing RES early helps), and three
zones contributing two cells each make the effective n nearer three than six — a
perfect ordering of three happens one time in six by chance. It is a
quantitative consistency check that could have failed and did not, and it gives
C18 a *reason* for FINDING C9-C's zone pattern.

**The vintage premium is a property of the model class, and the LASSO is
fragile.** DE-LU's is **−16.83% under the LEAR and +28.13% under the GBM in the
same zone-year**; in capture terms the GBM's is +9.05pp [+4.31, +13.62] (2023)
and +3.47pp [+0.43, +6.60] (2024), both established. So the LEAR's 2023 sign
reversal is a LASSO failure under a regime shift, not evidence about the
vintage — in the same rows the booster extracts the leak cleanly. **FINDING
C9-C is strengthened**: the leak is worth more to a non-linear model and now
also *more reliably*. Still unachievable.

**FINDING C12-E's one established contrast replicates.**
`gbm_price_only − lear_price_only` in ES is **−4.49pp [−7.40, −1.58]** (2023)
against C12's **−2.22pp [−4.25, −0.29]** (2024): same sign, larger, excluding
zero in both years. The booster captures **less** than the LASSO in the zone
where it has the better MAE — now a two-year result.

**FLAG C14-01 — a pooled naive-dominance failure that is a tie, and a finding.**
DE-LU 2023 `gbm_res_persistence` settles **52 763 EUR** against the naive floor's
**52 850** over 364 days: **−87 EUR**, **0.16%**, per-day win rate **50.3%**. The
bootstrap says tie rather than the prose doing so: **−0.139pp of oracle cash,
95% interval [−6.22, +6.15]** at the daily block — forty-four times wider than
the point estimate — with P(≤0) = 0.516 / 0.518 / 0.526 across the 1 / 7 /
14-day blocks. **The assertion was not weakened**: it still reports
`holds: false`, the failure is recorded in `c14_ladder_invariant_flags.json`,
the dispatch phase exits non-zero, no tolerance was widened and no test was
edited. Every other check passed on every curve of every zone, including the
per-day same-start oracle bound.

What makes it more than a footnote: among the **five honest curves** of DE-LU
2023 this arm has **the best MAE and the worst capture, both ends at once** —
MAE 23.60 against gbm_price_only's 24.53, lear_res_persistence's 25.62,
lear_price_only's 25.77 and the naive floor's 33.62; capture 0.8453 against
0.8807, 0.8700, 0.8853 and naive's 0.8467. (Only the leaky arm beats its MAE
overall, at 17.05.) A forecast **30% better than naive on the point metric
captured slightly less flexibility value than naive did**, and the ranking is
not merely uncorrelated but inverted at both ends. That is the sharpest instance in this
project of **FINDING C11-D / C12-D**, and it belongs in C18 beside them. It is a
different animal from **FLAG C13-01** (a thin-market artefact at −655 EUR on a
769 EUR/MW/yr prize); this is a tie in a deep market, and neither should be
"fixed" by relaxing the check.

**Mechanics.** 2023's zones ran **serially** — two four-thread fits sharing four
cores were several times slower in total, and the GBM's `num_threads=4` is part
of the frozen fingerprint so it could not be lowered. Per zone: C8 ~7 min, C9
~21 min. The contrast table and the dispatch phase's `pooled_capture` are
cross-checked against each other (**30 comparisons, worst delta 4.8e-07**; the
run refuses >1e-6), because a mismatch would be the FINDING C11-C failure mode
and invisible in the published table.

#### Data: 54 price pulls and 18 ENTSO-E documents, every fingerprint identical

NOTE C2-02 — `data/raw/` was empty on arrival again (**25th recurrence**), and
this cycle needed both caches. `data.fetch_prices`: **54 downloaded, 0 already
cached, 0 flagged.** `data.fetch_exogenous`: **18 downloaded, 0 already cached,
0 flagged.**

C13 compared six summary statistics per file. This cycle compares the
**`payload_sha256` the manifests committed** — **54/54** price zone-years against
C1's manifest and **27/27** ENTSO-E *series* rows against C7's — which is the one
comparison that cannot be passed by accident. Two details got wrong on the first
attempt and caught by the check failing loudly rather than vacuously passing:

* **It is a fingerprint of the data, not of the file.** The cached file embeds
  `_fetch_meta.fetched_at_utc`, so a file hash changes on every re-fetch even
  when the numbers are identical — which is exactly the column the Checkpoint-A
  decision removed (**NOTE C2-01**). The check now calls the manifests' own
  `data.contracts.payload_fingerprint` and
  `data.exog_manifest.series_fingerprint`.
* **The exogenous fingerprint is per *series*, not per document.** The A69
  document carries wind and solar with a different hash each, so a check keyed on
  `(zone, document, year)` finds two candidates and has to pick one. All 27
  series rows are checked, and a test asserts the A69 document really does carry
  two distinct committed hashes.

Neither manifest was regenerated or re-committed (C8/C9/C10/C13's precedent).
Source gaps are reported and never filled (C7's standing rule): 50 (DE-LU), 144
(ES) and 48 (NO2) hours dropped for an incomplete residual load out of ~26 300,
i.e. 0.2-0.6%, concentrated in the known autumn-DST hour and the partial-psrType
stretches in `docs/entsoe_layer.md`. An hour missing *any* component is dropped,
never part-subtracted.

#### Sealed holdout

**SEALED.** Verified after the work: marker-alone-on-a-line count **0**,
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises, **no `*2025*` file exists anywhere under
`data/`**, the price cache holds exactly 2019-2024 in **every one of the nine
zones**, and the only years appearing in any committed C14 artefact are **2022,
2023 and 2024**. Store-wide `evaluation_years` across all rows: 2020-2024.

The string-`2025` sweep is **stricter than C13's**, and the improvement is worth
recording because C13's version had a false negative. C13 classified each
occurrence as "numeric" or not; a *bare* `2025` in prose matches a numeric
literal just as a digit run inside a float does, so the one test could not
separate "a 2025 datum" from "the word 2025". C14 sorts every occurrence into
three buckets instead:

| bucket | count | what they are |
|---|---|---|
| digits inside a longer number | **1** | `19.522025`, a residual-load value in `c14_merit_order_deciles.csv` |
| a bare `2025` year token | **2** | both in `docs/fundamentals.md` prose, both stating that 2025 is sealed |
| neither | **0** | — |

Three occurrences in total, **none of them a 2025 datum**. `fundamentals_frame`
and `headroom_frame` both refuse a sealed year **before any path is built** (two
tests pin it, so 2025 cannot arrive as a missing-file message), and the store's
tripwire stands: a metric whose `evaluation_years` touches a sealed year cannot
be written. No 2025 data has been fetched, loaded, dispatched or computed
against at any point in C2-C14.

#### The results store

**315 rows appended**, run `C14-20261010T043651Z-0e34c57a`; the store is now
**8 565 rows across 5 runs**, `verify_append_only()` green, and the 8 250
committed C10-C13 rows are **byte-for-byte unchanged** (the new file's first
2 484 512 bytes are identical to `git show HEAD:backtest/results/results.csv`).
**No schema change and no test edit were needed** — the fifth cycle running in
which long format made the metric name the extension point. 40 distinct metrics
across three evaluation years.

Two deliberate filing choices, both about not misfiling a description as a
result. **228 of the 315 rows are `vintage = after_gate_closure`**, so
`honest_rows()` excludes every descriptive number this cycle produced — which is
the correct default for a results table, since they are built on the Art. 14
late vintage. And the fundamentals rows are filed under the **oracle's**
`(model, exog_variant)` identity, because there is no forecast behind an R² of
the realised price on residual load; filing them under a model's key would make
them join to that model's MAE as though they described it. The 87 `honest` rows
are the 2023 ladder's own capture and MAE figures, which are about real
forecasts.

#### Config hash and libraries

Config hash **`515d4e8d98887256`** — unchanged since C8; C14 modified no
`config/*.yaml`. Library fingerprint **`856fb19ac0c4eecd`** — identical to
C10/C11/C12/C13's (python 3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn
1.9.1, scipy 1.17.1, lightgbm 4.7.0), so C10-C14 rows are directly comparable.
The GBM config fingerprint `a366a760e269bba6` was not touched and no
hyperparameter was tuned.

#### Built and committed

- `backtest/run_c14_fundamentals.py` — seven phases, deliberately separable
  because only the ladder's two fitting phases are expensive: `verify` (the
  cache fingerprint check), `fundamentals` (the descriptive chapter + two
  figures), `headroom` (NOTE C13-03 + one figure), `ladder-compute` (a
  *refusal* that names the two C8/C9 commands to run — it does **not** wrap or
  re-implement them, because a second evaluation year is only comparable to the
  first if it came out of the same code), `ladder-dispatch`, `ladder-analyse`
  and `ingest`.
- `tests/test_c14_fundamentals.py` — 68 offline tests. The new machinery is
  tested against **synthetic zones whose answers are known by construction**: an
  exactly linear stack must return equal slopes and R² = 1, a convex one must
  return convex, a *falling* one must not report a convexity ratio (NO2 2022's
  trap), a uniformly-sprinkled negative-price zone must **not** be labelled
  RES-surplus (the falsification FINDING C14-D rests on), a zone with no solar
  fleet must report **no** solar coefficient rather than a fitted zero, and two
  zones differing 10× in size must agree on the normalised slope and disagree
  10× on the raw one. Plus: the descriptive-vintage refusals, the bootstrap's
  agreement with `backtest.bootstrap.replicate_counts`, the sealed-year guards
  firing before any path is built, the cache check *failing* rather than passing
  vacuously, the ladder arms matching C11's store key field by field, and each
  FINDING pinned to the committed artefact.
- `docs/fundamentals.md` — the chapter, with the vintage line (§1), the two
  methodological traps (§2.1), the findings (§§3-8), what the cycle did not do
  and why (§10) and its own Limitations (§11).
- Artefacts: `c14_cache_verification.json`, `c14_merit_order_deciles.csv`,
  `c14_explanatory_power.csv`, `c14_supply_curve_slopes.csv`,
  `c14_negative_price_mechanism.csv`, `c14_residual_load_sufficiency.csv`,
  `c14_fundamentals_summary.json`, `c14_headroom_daily.csv.gz` (3 269 rows — the
  per-day artefact C15/C17 should read rather than rebuild),
  `c14_headroom_cells.csv`, `c14_headroom_correlations.csv`,
  `c14_headroom_summary.json`, `c14_ladder_<ZONE>_2023_{daily.csv.gz,summary.json}` (3 zones x 8 curves), `c14_ladder_capture.csv`, `c14_ladder_contrasts.csv`, `c14_ladder_invariant_flags.json`, `c14_ladder_summary.json` and the new store rows.
- Figures: `docs/figures/c14_merit_order_tier_a.png` (the empirical supply curve,
  one panel per zone, one line per year, symlog price axis so the negative tail
  does not swallow the part of the curve the chapter is about),
  `c14_negative_price_by_decile.png`, `c14_headroom_vs_res_revision.png`.
- `requirements.txt` — a comment block recording that C14 added no dependency and
  why the statistics are explicit design matrices rather than a formula API.

#### Notes for later cycles

**NOTE C14-01 (for C15) — FINDING C14-F hands C15 a falsifiable prediction, not
just a result.** NOTE C13-02 already re-pointed the throughput-cost ladder at
*how much of the capture ratio is friction*. C14 adds a prediction the same
ladder tests for free: **NO2's within-day ordering will not improve at any rung**
— not at a 0 EUR/MWh throughput cost, not at a different duration, not under a
different SoC policy — because the fundamental that orders the hours elsewhere
(the within-day residual-load swing) has **no measurable relationship to NO2's
price spread in any of the three years**, so the information a model would need
is not in its inputs. C15 should report NO2's within-day Spearman at every rung
beside its capture. If the Spearman moves materially with the throughput cost,
FINDING C14-F is wrong and C18 must say so.

**NOTE C14-02 (for C18, wording — read with NOTE C12-03 and NOTE C13-01).** Two
more labels are now evidenced. **(i) The merit order is a DE-LU/ES fact.** A
sentence like "price is driven by residual load" is true at R² 0.56-0.80 in
those two zones and at 0.32-0.36 in NO2, where in 2022 the relationship runs
*backwards*. Any cross-zone fundamentals claim must carry the zone. **(ii) A
crisis year degrades every fundamental relationship measured here** — the
residual-load R², the component-symmetry restriction and the RES-revision
correlation all collapse in 2022 — so a 2022 number is not a draw from the same
process as a 2023 or 2024 one, on the fundamentals side just as FINDING C13-F
found on the dispatch side.

**NOTE C14-03 (for C17/C18) — the bridge from a point metric to EUR/MW/yr now
has a fundamental behind it.** FINDING C12-C gave the within-day Spearman and
FINDING C13-D gave `error_over_headroom`; neither had a mechanism. FINDING C14-F
supplies one and splits it in two: **RES build-out creates the headroom**
(between-cell, ρ = −0.72 of relative RES swing against error-over-headroom) and
**RES forecast error eats into it** (within-cell, ρ ≈ +0.35 to +0.50). C18
should use both rungs and say which is structural and which is a forecasting
problem — they have different implications for a desk, and only the second one
is something a better model fixes.

**NOTE C14-04 (for C20) — part of the reproducibility check is already done, and
it passed.** C8's full-history reference arm and C13's nine-zone comparable arm
are the same committed configuration. Run by two different runners, in two
different containers, off two independent Energy-Charts re-pulls, they agree on
**all 8 759 hours of DE-LU 2023 to a worst absolute difference of exactly
0.0 EUR/MWh**. `cross_check_full_history_against_c13()` is committed and tested;
C20 should extend it (more zones, the GBM arms) rather than start fresh. The
cache-fingerprint check in `c14_cache_verification.json` is the other half: 54
price zone-years and 27 ENTSO-E series, all identical to the committed
manifests.

**NOTE C14-05 (for C15/C17) — the per-day artefact to read rather than rebuild.**
`c14_headroom_daily.csv.gz` is 3 269 rows: one per (Tier-A zone, market day,
2022-2024) carrying the day's residual-load mean / min / max / range, its
day-over-day revision, both size-normalised, and the C13 dispatch columns joined
on. Anything C15 or C17 wants to say about a fundamental against a dispatch
outcome for Tier A is a groupby on that file, not a re-fit.

**NOTE C14-06 (for C15/C18) — what the closed NOTE C8-01 means downstream.**
The headline honest Tier-A arm stays `res_persistence` for *consistency with
C8-C13*, but C18 should now say plainly that it buys nothing: six booster cells,
one established contrast, negative. The ENTSO-E exogenous block's role in this
project is therefore **the measurement of a leak** (FINDING C9-C, FINDING
C14-H) and **the fundamentals chapter** (FINDING C14-A..F), not a modelling
gain. C15 needs no exogenous arm in its sensitivity ladder.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `abaa193`
with local `master` stale 17 commits behind. **29 recurrences out of 36
containers.** `HEAD` equalled `origin/master` exactly after a fetch (0 ahead, 0
behind) and local `master` was a strict ancestor, so nothing was at risk.
**`git checkout -B master` was refused by this session's permission classifier
as a destructive git action**, so the branch was attached the safer way instead
— `git checkout master` followed by `git merge --ff-only origin/master`, which
cannot discard a commit and fails loudly if the branch has diverged. That is the
better recipe for this situation and later cycles should reach for it first;
C9's warning still stands for a container that arrives detached *and* genuinely
behind the remote, where neither recipe is safe and the cycle should flag rather
than improvise. Keep checking `git rev-parse --abbrev-ref HEAD` and
`git rev-list --count master..HEAD` at the start of every cycle.

**Next:** C15 — the sensitivities: throughput cost 0/2/5 EUR/MWh, daily-reset vs
rolling-horizon SoC, RES-forecast degradation, 2h vs 4h duration. PLAN.md calls
this "where the honest findings live". Read **NOTE C13-02** (the ladder is a
friction measurement, not NO2's mechanism test — FINDING C13-E settled that) and
**NOTE C14-01** (C14 hands it a falsifiable prediction: NO2's within-day
ordering should not improve at any rung, because the information is not in the
inputs — report NO2's within-day Spearman beside its capture at every rung).
**NOTE C14-06** says the RES-degradation sensitivity no longer needs an
exogenous arm: NOTE C8-01 is closed. `c13_daily_by_year.csv.gz` and
`c14_headroom_daily.csv.gz` mean the ladder needs **no re-fitting, only
re-dispatch**. Two open FLAGs carry forward, both explained and neither a bug:
**FLAG C5-01** (resolved at Checkpoint B, carried as a stated limitation) and
**FLAG C13-01**; **FLAG C14-01** is new and in the same category. The 2025
holdout stays **SEALED** until Checkpoint C (C16).

---

### C15 — 2026-10-10 (scheduled cycle) — the sensitivities: the same forecasts, dispatched under six batteries

Scope per PLAN.md C15: *"Sensitivities: throughput cost 0/2/5 EUR/MWh; daily-reset
vs rolling-horizon SoC; RES-forecast degradation; 2h vs 4h duration. This is where
the honest findings live — look here first for the surprising finding."* Read with
**NOTE C13-02** (the throughput ladder is a friction measurement, not NO2's
mechanism test) and **NOTE C14-01** / **NOTE C14-06**.

All four sensitivities ran, on the committed forecasts, with nothing re-fitted:
**six batteries x 51 (leg, zone, year) cells = 1 836 rolling-horizon runs**, each
with its own per-day same-start oracle bound. Full write-up in
`docs/sensitivities.md`.

#### The ladder

One-at-a-time around the committed spec, and a test asserts each rung moves one
lever plus the fields derived from it: `base` (`config/battery.yaml` as
committed), `throughput_0`, `throughput_5`, `duration_4h`, `soc_daily_reset`
(every day opens *and* closes half full) and `soc_no_terminal` (SoC carries,
closing inventory unvalued — the decomposition leg, and the trap
`config/battery.yaml` warns about). Main leg: 9 zones x 2020-2024 x {oracle,
`lear_full_history`, `naive`}. RES leg: Tier A x {2023, 2024} x {oracle, both
vintages of both model classes}.

#### The zero rung is the published result

`base` was re-solved from scratch in a fresh container, from an independently
re-pulled price cache, by a runner that did not exist when the numbers were
published, and it reproduces **54 756 committed per-day settled-cash rows to a
worst absolute gap of 5.0e-7 EUR**: 49 284 against `c13_daily_by_year.csv.gz`
(which carries C11's 2024 column unchanged) and 5 472 against
`c11_capture_daily_2024.csv.gz` over five curves. DE-LU 2024's capture comes back
as 0.9187 and NO2 2024's as 0.6146 — both ends of FINDING C11-A, to four
decimals. **This is most of what NOTE C14-04 handed C20**: the reproducibility
check now covers the whole nine-zone, five-year dispatch surface instead of one
zone's hours.

#### Findings

**FINDING C15-A — about 3% of the capture shortfall is friction; the other ~97%
is not (NOTE C13-02 answered).** Over the 44 usable (zone, year) cells the
comparable LEAR's mean capture is **0.7953** — a **20.47pp** shortfall — and
removing the **entire** throughput cost recovers **0.80pp** of it, leaving
**19.67pp**. Friction share of the shortfall: **mean 0.034, median 0.029, range
−0.033 to +0.174**. The share is itself regime-dependent in the direction a desk
would expect: ~0 in the deepest zones (DE-LU 0.001, BE 0.005, FR 0.006) and
largest in the thinner ones (ES 0.091, IT-North 0.070, NO2 0.065, DK1 0.042).
What the throughput cost moves is the **prize**, not the ratio: k = 0 adds
+2 175 EUR/MW/yr to the oracle and +1 982 to the forecast (42 of 45 cells' cash
intervals exclude zero), k = 5 removes ~2 800-3 000 from both, and because it
taxes them almost equally the capture delta's interval excludes zero in only
**3 of 45** cells at PLAN.md's daily block.

**FINDING C15-B — doubling the duration adds +25 094 EUR/MW/yr and +1.61pp of
capture, and cycles the battery less.** 44 of 45 cells' cash intervals exclude
zero; the capture gain is directional (11 / 16 / 17 of 45 at the 1 / 7 / 14-day
blocks). Equivalent full cycles fall from **577 to 482 per year**, which matters
for a degradation budget. The mechanism is the obvious one: a 4h battery charges
and discharges over a wider window, so getting the exact hour wrong costs less —
it is a slightly *easier* forecasting problem as well as a bigger one.

**FINDING C15-C — the SoC convention is the biggest lever in the ladder, and
what it prices is a *forced closing inventory*, not the overnight carryover.**
Forcing each market day to open and close half full costs **−3.97pp of capture
and −3 185 EUR/MW/yr** — a larger effect than removing all trading friction. The
mechanism is the closing floor making the day buy back what it sold, at whatever
hour is left: the other SoC leg (`soc_no_terminal`), which also makes each day
independent but lets the LP end **empty** (it does so on 99.8% of days), costs
nothing at all. So "nothing resets at midnight" is not an LP detail, but the
honest phrasing is "a forced closing inventory costs ~3 200 EUR/MW/yr", not "the
carryover is worth that" — the carryover itself is exercised on about one day in
four (FINDING C15-D).
**Caveat carried in the write-up:** part of that −3 185 is inventory one run
still owns. `c15_boundary_inventory.csv` bounds it twice: against the
deliberately unfair bound (the net stored-energy difference at the *year's*
highest realised price) the median cell is **8.2x** its bound with 46 of 114
above 10x; against the natural bound (the last dispatched day's highest price,
when that difference is actually realised or not) the median is **37.1x** with
**105 of 114** above 10x. Safe under the bound that fits the question; a ~10%
boundary term under the unfair one. Both are reported.

**FINDING C15-D — the surprising finding: the device that protects the rolling
horizon mostly does nothing, and where it binds the best estimate is that it
costs money.** `config/battery.yaml` introduced the trailing-value end-of-day
mark because without a terminal condition a 24h LP empties the battery before
midnight and "silently turns PLAN.md's rolling-horizon SoC carryover into the
daily reset it forbids." With the mark in place the battery **still ends 74-77%
of days at SoC ~ 0** (oracle 0.744, comparable LEAR 0.767, naive 0.758; mean
closing SoC 0.35-0.42 MWh of 2.0), so for a 2h battery the rolling horizon is in
practice a nightly reset to empty and the mark binds on about a quarter of days.
Removing it entirely (`soc_no_terminal`) leaves the captured share
**statistically unchanged — 0 of 45 capture intervals exclude zero at the daily
block, the weakest result of any lever here** — while the point estimate on cash
moves **+2 943 EUR/MW/yr in the battery's favour** (16 of 45 cells, so
**directional and NOT established**). **Nothing was changed**: this is
**NOTE C15-01**, a decision request, and no headline in this project moves on it.

**FINDING C15-E — removing every euro of friction closes 6-12% of NO2's capture
deficit (9.1% on the four-year mean) and leaves 88-94% standing, in every usable
year.** Gap to the other eight zones' mean, `base` -> `throughput_0`: 2021 −30.70
-> −27.41pp (10.7% closed), 2022 −27.35 -> −25.47 (6.9%), 2023 −22.95 -> −21.54
(6.1%), 2024 −27.46 -> −24.16 (12.0%); four-year mean −27.11 -> −24.65pp, 2.47pp
closed. NO2 2020 is excluded as thin-regime and reported on its own — including
it would report that one cell (it alone "closes" 63pp, from −0.52 to +0.11
capture). **NO2 is last of nine on capture *and* last on the within-day Spearman
in all 30 of 30 (year, rung) rows.** FINDING C13-E killed the thin-spread story; the friction story dies here.
What survives is the within-day ordering (FINDING C12-C) with FINDING C14-F's
fundamental behind it.

**NOTE C14-01, and the one thing this cycle refuses to claim.** C14 handed C15
"a falsifiable prediction": NO2's within-day ordering will not improve at any
rung. **It cannot.** The within-day Spearman is a function of the forecast and
the realised prices; no rung of this ladder touches either; the mean Spearman is
**0.783 at every one of the six rungs** and the asserted drift is exactly
**0.0**. C15 therefore reports it as an **assertion about the design** — a
non-zero drift would mean two rungs had been pooled over different day sets, a
bug — and tests the prediction's substantive form instead (FINDING C15-E).
Presenting a tautology as a confirmed prediction is exactly the kind of thing an
unattended cycle does and a reader cannot see.

**FINDING C15-F — the Art. 14 leak's dispatch value is a model-class fact, not a
battery fact.** `as_published − persistence` in capture points, never achievable
(FINDING C9-C): under the **LASSO** it is ~0 or negative at every rung in every
cell (−3.01 to +3.20pp; **0 of 6** cells exclude zero at `base`); under the
**booster** it is large and positive in DE-LU at every rung (+3.24 to +11.71pp),
positive in ES 2023 at every rung (+4.82 to +6.90) and ~0 in NO2 (**3 of 6**
exclude zero at `base`). So FINDING C11-D's "except on DE-LU under the GBM" is
robust to the whole battery specification, not measured once. The one systematic
movement runs *opposite* to the obvious objection: the leak is worth **most** at
`soc_daily_reset`, the hardest dispatch problem, in **11 of 12** cells (exception
GBM/ES 2023, where `duration_4h` edges it +6.90 to +6.79). A better forecast is
worth more when the battery has less slack — the reverse of "the leak only looks
valuable because the battery is forgiving."

**FINDING C15-G — the levers move the money with confidence and the captured
*share* with very little.** On cash, four of five levers are decided in 42-44 of
45 cells; on capture the best manages 11 of 45 and the worst 0. Same days, same
draws, same battery. This is **FINDING C12-D restated across a dimension C12
could not reach**: capture is not a bad metric, it is a ratio designed to divide
out exactly what a battery-parameter lever changes. **C18 should quote the lever
effects in EUR/MW/yr and treat the capture deltas as directional**, with the one
exception of `soc_daily_reset`, whose capture effect survives at 31 and 33 of 45
cells at the 7- and 14-day blocks.

#### The one new lever, and why it needed a guard

`dispatch/rolling.py` carried SoC and nothing else, so PLAN.md's daily-reset leg
had **no implementation** — and the obvious implementation invents energy in a
way that would not look wrong in the diff. Open every day at
`initial_soc_fraction` with the terminal condition left as it is: under
`terminal_mode="none"` the LP empties the battery before midnight, so the reset
hands it 1 MWh free, 365 times a year, and the extra cash reads as a sensitivity
result; under `trailing_value` the run books a mark on inventory the reset throws
away.

So `soc_policy="reset"` is **accepted only with a terminal floor at or above the
opening fraction**, where the LP must hand back at least what it was given and
the reset can therefore only ever *discard* energy. How much it discarded is
counted (`RollingResult.soc_reset_discarded_mwh`) rather than assumed to be zero,
`dispatch/rolling.py` refuses the unsafe spec combinations up front, and
`check_reset_conserves_energy` re-checks the **outcome** on the days actually
solved — every day opened at the configured SoC and no discard was negative, on
all 1 836 runs.

**This is the only pre-existing module C15 touched** (74 insertions, 1 deletion,
all additive), and the committed default is pinned byte-for-byte by
`test_carry_is_the_default_and_is_unchanged_by_naming_it`. Nothing under
`tests/`, `config/`, `forecast/`, `data/`,
`backtest/{walk_forward,metrics,bootstrap,results_store}.py`,
`dispatch/battery.py`, `dispatch/curves.py` or any earlier runner was modified —
`git diff --stat HEAD` over all of those came back empty.

#### Comparability across rungs, and the boundary objection

`run_rolling_dispatch` skips a day `no_reference` only under `trailing_value`, so
the two rungs that switch the terminal condition off *can* dispatch days `base`
skips. Every cross-rung number is therefore summed over the **ladder-common day
set** — the days every rung of every curve of that (zone, year) dispatched — which
is C11's `common_hours` definition applied to a larger run set, so **`scope`
needed no new value**; read `source_artefact` beside any C15 row. And because the
rungs end the year in different states, `c15_boundary_inventory.csv` bounds the
inventory-accounting part of every cross-rung cash difference twice (the year's
highest realised price, and the tighter last-day price) for **all five** non-base
rungs, not only the SoC ones.

#### FLAGs

**FLAG C13-01 reproduced at all six rungs, and it is still a regime fact — not a
new flag.** NO2 2020's comparable LEAR fails CLAUDE.md's pooled naive-dominance
invariant at `base` (**−402 EUR** against the naive floor's **+253**, exactly
C13's numbers) and at every other rung, including `throughput_0` where it earns
**+133** against the floor's **+543**. All six failures are in
`c15_invariant_flags.json`, the dispatch phase **exited non-zero**, **no tolerance
was widened and no test was edited.** C15 adds only that removing the friction
does not rescue it: with a 769 EUR/MW/yr prize, a 3.41 EUR/MWh mean realised
spread, a 2 EUR/MWh throughput cost and a 12% round trip, there is nothing to
trade and which curve trades *less* is luck. No later cycle should "fix" this by
relaxing the check.

**No new FLAG.** Every other check passed on every curve of every rung of every
cell — the per-day same-start oracle bound included, on all 1 836 runs.
**FLAG C5-01** (simultaneous charge/discharge, resolved at Checkpoint B as a
stated limitation) and **FLAG C14-01** (the DE-LU 2023 GBM tie) carry forward
unchanged and were not re-touched.

#### Housekeeping

- **Data.** `data/raw/` arrived empty — **NOTE C2-02, 26th recurrence**. All 54
  price (zone, year) files were re-pulled, 0 flagged, and **all 54
  `payload_sha256` fingerprints are identical to C1's committed manifest**
  (`c15_cache_verification.json`), so the manifest was not regenerated. **No
  ENTSO-E call at all**: NOTE C14-06 closed NOTE C8-01, so C15 adds no exogenous
  arm and the RES leg re-dispatches C8's and C9's already-committed forecasts.
  `ENTSOE_API_KEY` was not read.
- **Sealed holdout verified armed.** `LADDER_YEARS` stops at 2024;
  `main_curves` has **no mapping** for a sealed year and raises before a path is
  built; `dispatch_cell` calls `assert_not_sealed` first; two tests pin both. A
  sweep of every committed C15 artefact for a bare `2025` token (C14's
  three-bucket method) finds **none**, and no `year` column anywhere in the 51
  per-day files contains 2025. No 2025 data has been fetched, loaded, dispatched
  or computed against at any point in C2-C15.
- **Config hash `515d4e8d98887256`, unchanged since C8.** No `config/*.yaml` file
  was modified — including by FINDING C15-D, which is a decision request
  (NOTE C15-01), not a change. The frozen GBM config
  (`a366a760e269bba6`) was not touched and is now pinned from C15's side too.
- **Library fingerprint `856fb19ac0c4eecd`**, identical to C10-C14's (python
  3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1, lightgbm
  4.7.0), so C10-C15 rows are directly comparable. **No new dependency.**
- **Repo-state note:** the detached-HEAD trap recurred — the container arrived
  detached at `c7ffea5` with local `master` 24 commits behind. **30 recurrences
  out of 37 containers.** `HEAD` equalled `origin/master` exactly after a fetch
  and local `master` was a strict ancestor, so C14's safer recipe applied:
  **`git checkout master` then `git merge --ff-only origin/master`**, which cannot
  discard a commit and fails loudly on divergence. Keep checking
  `git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the
  start of every cycle.
- **Artefact size — hand to C20.** C15's artefacts are ~37 MB, against ~25 MB for
  C1-C14 combined, because the per-day ladder is 361 350 rows (6 rungs x the
  C11/C13 dispatch surface). Nothing was trimmed, because a committed artefact
  that does not match what the runner writes is worse than a large one. The
  obvious saving is that the ten forecast-shape columns are **rung-invariant by
  construction** (that is FINDING C15-E's Spearman point) and are stored six
  times; normalising them out would save ~40%. PLAN.md gives C20 the repo-size
  check — this is the input to it.

#### Artefacts

- **Full suite: 827 passed, 0 failed** (708 before C15, plus this cycle's 119).
  The analyse phase is **deterministic**: all six C15 tables are byte-identical
  across two independent runs (`md5sum -c`).
- Code: `backtest/run_c15_sensitivities.py` (new, three phases: `verify`,
  `dispatch`, `analyse`), `tests/test_c15_sensitivities.py` (new, 119 tests),
  `docs/sensitivities.md` (new), and the `soc_policy` lever in
  `dispatch/rolling.py`.
- Per-day: `c15_{main,res}_<ZONE>_<YEAR>_daily.csv.gz` (51 files, 361 350 rows —
  every dispatch column day-additive, so `backtest/bootstrap.py` takes them
  directly) and `_summary.json` beside each (the rung specs, the skips, the
  invariants, the curve provenance).
- Tables: `c15_rung_points.csv` (every (leg, zone, year, rung, curve) cell's
  pooled numbers), `c15_lever_contrasts.csv` (paired intervals at 1 / 7 / 14-day
  blocks), `c15_lever_summary.csv`, `c15_friction_decomposition.csv`,
  `c15_no2_ordering.csv`, `c15_boundary_inventory.csv`, `c15_res_degradation.csv`,
  `c15_invariant_flags.json`, `c15_cache_verification.json`,
  `c15_sensitivity_summary.json`.
- Figures: `docs/figures/c15_capture_vs_throughput_cost.png` (capture against k,
  one panel per year, NO2 in black), `c15_lever_effects.png`,
  `c15_friction_share_of_shortfall.png`.

#### Notes for later cycles

**NOTE C15-01 (DECISION REQUEST for the human, at Checkpoint C or D) — the
end-of-day inventory mark.** FINDING C15-D says the committed `trailing_value`
mark (i) fails at the job `config/battery.yaml` introduced it for — the battery
still ends 74-77% of days empty, so the rolling horizon *is* substantially a
nightly reset to empty — and (ii) where it binds, the best point estimate is that
it **costs** the battery ~2 900 EUR/MW/yr of realised cash, though that is
**not established** (16 of 45 cells at the daily block, and 0 of 45 on capture).
**C15 changed nothing.** The options, for a human:
  **(a)** keep `trailing_value` as committed and carry FINDING C15-D as a stated
  limitation in C18 (the conservative choice, and the one that keeps every
  C5-C14 headline exactly as published);
  **(b)** re-run the headline on `terminal_mode="none"`, which would move every
  published capture and EUR/MW/yr number in the project and needs a cycle of its
  own;
  **(c)** keep `trailing_value` but mark closing inventory at a *lower* quantile
  than the trailing median, which is a new modelling choice and therefore a new
  sensitivity rather than a fix.
**Recommendation: (a).** The effect is not established, the ladder already
measures it, and changing a committed default on an unestablished point estimate
is exactly what a scheduled cycle should not do on its own.

**NOTE C15-02 (for C18, wording — read with NOTE C12-03, NOTE C13-01 and
NOTE C14-02).** Two more required labels. **(i) Quote a lever in EUR/MW/yr, not
in capture points** (FINDING C15-G): on cash four of five levers are decided in
42-44 of 45 cells, on capture the best manages 11 of 45. The one exception is
`soc_daily_reset`, whose capture effect survives at 31/33 of 45 at the 7- and
14-day blocks. **(ii) "Friction costs the battery money" and "friction explains
the capture shortfall" are different claims and only the first is true** —
+1 982 EUR/MW/yr of prize against 3% of the shortfall (FINDING C15-A).

**NOTE C15-03 (for C18) — the sensitivity ordering C18 should report.** By mean
effect on realised cash, ex the thin cell: duration **+25 094**, SoC convention
**−3 185** (daily reset) / **+2 943** (no mark), throughput cost **±2 000-2 800**.
By effect on the captured share: SoC convention −3.97pp, duration +1.61pp,
throughput ±2-3pp. **The asset spec dominates the market friction on both
scales**, which is the practical message for a desk sizing a battery: the
duration decision is worth more than everything else in this ladder put together.

**NOTE C15-04 (for C20) — the reproducibility check NOTE C14-04 asked for is
done, and it passed at scale.** 54 756 per-day settled-cash rows across nine
zones, five years and five curves, reproduced to 5.0e-7 EUR by a new runner in a
fresh container off an independent price re-pull. `check_baseline_reproduction`
and `check_res_leg_reproduction` are committed and tested; C20 should run them
rather than start fresh, and should also decide the artefact-size question in the
housekeeping note above.

**NOTE C15-05 (for C17, and only if budget allows) — PLAN.md's 15-minute
stretch goal was not started.** It is labelled a stretch goal ("C15+", "never
blended into the main results") and the main hourly backtest ends before
2025-10-01, which is inside the sealed year — so it cannot be attempted at all
until Checkpoint C unseals 2025. It is therefore a **post-C16** item, not a C15
omission.

**Next:** **C16 — CHECKPOINT C.** PLAN.md: *"stop, push-notify, wait for explicit
human approval to unseal the 2025 holdout. Only after approval: run a single
evaluation of the 2025 holdout; record in PROGRESS.md that it ran exactly once,
with the timestamp."*

To be unambiguous for the next scheduled session, because this field names a
checkpoint that is **not** yet approved: **C16's own work is to *request* the
unseal, not to perform it.** That session should (1) produce Checkpoint C's
required output — a short pre-unseal readiness report: what will be evaluated,
with which frozen configuration, which exact numbers will be produced, and the
confirmation that the guard is still armed; (2) append it to this file; (3) send
**one** push notification; (4) commit and push; (5) **stop**. It must **not**
load, read, feature-engineer from, train on or compute any metric against 2025
data — the holdout stays SEALED until a human writes the unseal marker and
records the approval here, and `data/holdout.py` will refuse it anyway.

A session that fires while this field still reads a checkpoint that has already
been requested but not approved should do no new work: verify nothing has
changed, append a one-line wait note, and stop without a push notification.

Three open FLAGs carry forward, all explained and none a bug: **FLAG C5-01**
(resolved at Checkpoint B as a stated limitation), **FLAG C13-01** (now
reproduced at all six C15 rungs) and **FLAG C14-01**. One new decision request:
**NOTE C15-01**. The 2025 holdout stays **SEALED**.


---

### C16 — 2026-10-10 (scheduled cycle) — **CHECKPOINT C REACHED: the request to unseal the 2025 holdout**

**Done, as scoped in PLAN.md C16, and then stopped.** Checkpoint C's own required
output: the pre-unseal readiness report — what will be evaluated, with which
frozen configuration, which exact numbers will be produced, and the confirmation
that the guard is armed — plus the two artefacts that make those claims checkable
rather than rhetorical. **The 2025 holdout is still SEALED. Nothing in this cycle
fetched, loaded, read, feature-engineered from, trained on, or computed any metric
against 2025 data, and no committed artefact carries a 2025 row.** 43 new tests
(**870 total, all passing**). Report: `docs/checkpoint_c.md`.

**C16 is a human deciding whether the project may look at the year it has spent
fifteen cycles not looking at. Nothing in C17+ has been started.**

---

#### What a checkpoint cycle could get wrong here, and what was built instead

The failure mode is not "the cycle peeks". It is that a cycle writes *"the guard
is armed"* in prose, a human reads it, approves on the strength of it, and nobody
ever established it. PLAN.md asks for "the confirmation that the guard is still
armed", and a confirmation that cannot fail is not one. So the readiness report is
two committed JSON artefacts produced by `backtest/run_c16_checkpoint.py`, and
`tests/test_c16_checkpoint.py` contains one test per way each check must fail.

#### The seal, verified (`backtest/results/c16_seal_verification.json`)

At `ae59c54`, config hash `515d4e8d98887256`:

| check | result |
| --- | --- |
| the unseal marker on a line of its own in this file | **absent** — `holdout_is_unsealed()` = `False` |
| `splits.holdout.years` | `[2025]`, `sealed: true` |
| `fetch_years` ∩ sealed years | **empty** |
| holdout-guard calls in the source tree | **33 calls across 14 modules** |
| required-guard modules missing a guard | **none** (6 of 6) |
| public entry points probed with a 2025 request | **8 of 8 refused** with `SealedHoldoutError` |
| runners probed end to end with `--years 2025` | **2 of 2** exited non-zero, refusing |
| committed artefacts scanned | **243 tables + 172 summaries, clean** |
| `evaluation_years` in `results.csv` | 2020-2024 only; **2025 absent** |
| the download record in `data/manifest/` | prices **2019-2024**, exogenous **2022-2024**; no 2025 row, no 2025 coverage timestamp |

The six modules that must carry a guard are the ones that can reach a sealed
price, a sealed exogenous series, a sealed fold or a sealed number:
`data/energy_charts.py`, `data/prices.py`, `data/entsoe.py`,
`data/exogenous.py`, `backtest/walk_forward.py`, `backtest/results_store.py` —
the last refusing to **write** a 2025 metric even if one were somehow computed.
The census is a static AST scan, so it counts guard *calls* and not imports, and
it raises if a required module's guard call is ever deleted (tested by deleting
one in a copied tree).

**Four details that make this evidence rather than theatre.**

1. **They call the real entry points, and they are safe when they fail.** Every
   network path is handed a session object that raises on use, so a probe that
   finds its guard missing still downloads nothing. A probe that is only safe in
   the world where it passes is not worth running.
2. **They run against a cache that contains a sealed year.** `data/raw/` does not
   survive a container (NOTE C2-02, 26th recurrence), so in a fresh checkout the
   stitching loaders fail with "no cached files" *before* reaching their guard —
   which is an accident of the container, not evidence, and it is exactly what
   this cycle found on first run (`prices.load_zone_series` raised
   `PriceDataError`, not `SealedHoldoutError`). So `synthetic_sealed_cache()`
   builds the situation the guard exists for: a cache holding `2024` and `2025`
   **placeholder** files, named the way each loader's `cached_years` reads a name
   and empty of content. If the guard were gone the loader would reach an empty
   file and raise a parse error; it can never reach a 2025 price. What counts as
   sealed still comes from the committed `config/data.yaml`.
3. **The download record is checked as well as the published numbers.** The
   artefact scan proves no 2025 *number* was published; `data/manifest/` proves
   the simpler and stronger thing, that no 2025 file was ever pulled — it is the
   committed record of every fetch, one row per (zone, year) with each one's
   coverage timestamps. The timestamp half is a real constraint and not a
   tautology: because the Energy-Charts request window is in local time a *raw*
   2024 file can legally contain the instant 2025-01-01T00:00Z, but the manifest
   trims to the UTC calendar year and every committed `last_ts_utc` ends
   2024-12-31T22:00Z. `data/raw/` is gitignored and does not survive a container,
   so the raw-file check is usually vacuous and is reported with
   `raw_cache_present` so a zero cannot be mistaken for a verified absence.
4. **The artefact scan distinguishes a 2025 *date* from 2025 *data*.**
   `main_backtest_end` is supposed to say `2025-09-30`, so the structural dates
   are whitelisted by key name; every other year or date column naming 2025 in a
   committed table or summary is a failure. Tested against a planted row, a
   planted date column and a planted summary key, so it has been seen to fail.
   C16's own two artefacts are exempt **by name** — the pre-registration
   necessarily names the year it pre-registers — rather than by a loosened rule
   that would also exempt a result file.

#### The pre-registration (`backtest/results/c16_preregistration.json`)

A holdout evaluated once is worth something only if the choices were fixed
beforehand, and prose in a log entry is not a fixed choice. The committed JSON is
stamped with the git SHA, the config hash and the library fingerprint, and
`test_the_committed_preregistration_still_matches_the_code_and_config` fails if
any of it drifts from the code and config that will execute it.

* **Window** 2025-01-01 .. **2025-09-30**, **273 market days** — it stops the day
  before the SDAC 15-minute go-live, per PLAN.md's `main_backtest_end`.
* **Zones** all nine (Tier A DE-LU/ES/NO2, Tier B FR/NL/BE/IT-North/DK1/PL).
* **Arms** headline = the nine-zone comparable arm every C10-C15 cross-zone
  number rests on (LEAR, `price_only`, `train_from` 2019-01-01), against the
  `naive_last_week` floor and the perfect-foresight oracle. Tier A also
  `load_only` and `res_persistence`, LEAR and GBM. **`res_as_published` is
  excluded** — the Art. 14 vintage is published after gate closure and C8/C9
  already report its premium as a measured leak; a once-only evaluation reports
  the honest arms.
* **Models frozen** C4's committed `LearSpec`; C9's single LightGBM config
  (fingerprint `a366a760e269bba6`) with in-fold early stopping. No search.
* **Walk-forward** `refit_every_days=1`, `min_train_days=365`, expanding —
  identical to C10/C11/C13. **This means the 2025 folds train on 2019-2024
  inclusive: the validation year moves from *evaluated* to *trained on*.** That is
  what an expanding window does, and it is legitimate because 2024 is in the past
  relative to every 2025 fold. It is written down here so it cannot later look
  like a surprise.
* **Dispatch** `config/battery.yaml` as committed (1 MW / 2 MWh, RTE 0.88,
  throughput 2.0 EUR/MWh, `terminal_mode: trailing_value`), commit-then-settle.
* **Metrics** MAE, RMSE, rMAE vs naive, daily-spread MAE/bias, within-day
  Spearman; capture against both oracles; EUR/MW/yr and EUR/MW/yr lost. Intervals
  by block bootstrap over daily blocks at the committed 1/7/14-day ladder, 10 000
  replicates, seed 20261009.
* **Eight assertions that must hold**, among them CLAUDE.md's two LP invariants in
  their correct forms (per-day against the same-start oracle; pooled for the naive
  floor), the gate-closure leakage guard on every fold, the DST row-count
  contract, and `resolution_seconds == 3600` on every evaluated row.
* **Four stop rules**, the load-bearing one being: **nothing may change after the
  first 2025 number is seen** — a change that looks necessary is a finding to
  report, and any re-run is a second evaluation that must be labelled as one.
* **The 2024 comparison table is carried inside the pre-registration**, so what
  2025 gets read against is fixed before 2025 is visible (DE-LU capture 0.9187 at
  the top, NO2 0.6146 at the bottom — both ends of FINDING C11-A).

#### What Checkpoint C is asking the human for

**Three things only a human can do, and one of them is a decision, not a
formality.**

1. **Write the unseal marker.** The holdout unseals on a line in this file which,
   stripped of whitespace, equals the `holdout_unseal_marker` value in
   `config/data.yaml` — the string `CHECKPOINT C APPROVED: 2025 holdout unsealed`.
   Copy it from the config file and paste it **alone on its own line**. Quoting it
   inside a sentence (as this one does) deliberately does not count — that
   hardening came out of Checkpoint A, and this entry is the 40th-odd line in this
   file to rely on it. Then replace "Next cycle to run" at the top with **C17**.
2. **Add 2025 to `fetch_years` in `config/data.yaml`.** The ENTSO-E fetch is
   bounded by `fetch_years` (through `entsoe.exogenous_years`) as well as by the
   holdout guard, so the Tier-A 2025 exogenous pull stays refused until 2025 is in
   that list — the Energy-Charts price fetch is bounded only by the guard. It
   changes `config_hash`, which is why it belongs with the approval and not inside
   the unseal cycle.
3. **Decide NOTE C15-01 — the end-of-day inventory mark — *before* the unseal.**
   C15's recommendation was **(a) keep `trailing_value` and carry FINDING C15-D as
   a stated limitation**, and that recommendation stands, with a sharper reason
   now: changing `terminal_mode` *after* the holdout has been evaluated would mean
   evaluating it a second time. If it is going to change, it must change first.

Also still open and unchanged, none of them blocking: **FLAG C5-01** (resolved at
Checkpoint B as a stated limitation), **FLAG C13-01**, **FLAG C14-01**,
**NOTE C2-02**.

#### What the unseal cycle will have to do

No 2025 file has ever been cached, so C17 starts with a fresh download: **9
zone-years of Energy-Charts prices** and **3 zones x 2 ENTSO-E documents**, one
request each, then cached. `ENTSOE_API_KEY` **is** set in this environment
(checked without reading its value). Two things are expected rather than
surprising — a resolution change inside the 2025 price file from 2025-10-01, which
`data/contracts.py` detects and which no evaluated row touches, and a 273-day year
against 365-366, so cash is annualised with the annualisation stated beside it —
and one is a flag: a 404, an empty response or an Acknowledgement is a FLAG, the
dependent zone is skipped, the rest continues.

#### One code fix outside the checkpoint's scope, and why it was made

The full suite arrived **826 passed, 1 failed** in this container, against C15's
recorded 827/0. The failure was
`test_c14_fundamentals.py::test_the_cache_verification_runs_without_a_cache_or_skips`
— *"the check must fail on an absent cache, never pass vacuously"* — and it was
right: with `data/raw/` empty, `verify_price_cache` built `pd.DataFrame([])` and
then indexed `frame_out["matches"]`, so an absent cache raised `KeyError:
'matches'` instead of returning `holds: False`. C15 recorded the suite green
because C15's container had re-pulled the cache; this cycle needed no prices and
so hit the empty-cache path.

Per CLAUDE.md the test is right and the code is wrong, so **the code was fixed and
no test was touched**: `PRICE_CACHE_COLUMNS` / `EXOG_CACHE_COLUMNS` are declared
and passed to the two `pd.DataFrame(rows, columns=...)` constructions, so an
absent cache yields an empty frame of the right shape and `holds: False` — the
check now fails on an absent cache, which is what it was written to do.
`verify_exog_cache` had the identical latent bug and got the identical fix. This
is a two-constant change to C14's verifier, not new work, and it is recorded here
because a checkpoint cycle that quietly changed code would be worse than one that
did not.

#### Artefacts

- **Full suite: 870 passed, 0 failed** — 827 before C16 (826 passing plus the one
  the fix above turned green) and this cycle's 43.
- Code: `backtest/run_c16_checkpoint.py` (new: `verify` and `prereg` phases),
  `tests/test_c16_checkpoint.py` (new, 43 tests), `docs/checkpoint_c.md` (new),
  and the empty-cache fix in `backtest/run_c14_fundamentals.py`.
- Reports: `backtest/results/c16_seal_verification.json`,
  `backtest/results/c16_preregistration.json`.
- Reproduce: `python -m backtest.run_c16_checkpoint --phase all`.

#### Next

**AWAITING HUMAN — CHECKPOINT C.** No cycle may start C17 until a human writes the
unseal marker, adds 2025 to `fetch_years`, decides NOTE C15-01, and sets "Next
cycle to run" to **C17**. A session that fires before then does no new work:
verify nothing has changed, append a one-line wait note, stop, and send **no**
push notification — the Checkpoint C ping went out with this entry.

After approval, C17 is PLAN.md's single evaluation of the 2025 holdout, exactly as
pre-registered in `c16_preregistration.json`, run **once**, with the UTC timestamp
and git SHA of the run recorded here. PLAN.md's own C17 (final `results.csv`,
README rewrite, figures) follows in the same cycle only if the evaluation leaves
room; the evaluation and its record come first.

**The 2025 holdout is SEALED.**

---

### Checkpoint C wait — 2026-10-11 (scheduled cycle, 1st wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT C**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has changed
  and stopped. `origin/master` == local HEAD at `24a37a2` (the C16 checkpoint commit — no
  human commits since, `git status` clean, `git fetch origin master` brought nothing new);
  all four unseal conditions still **unmet** — (i) the unseal marker is absent from this
  file (the only occurrence of the string is inside backticks in the C16 instructions at
  line 6263, not alone on a line, so `holdout_is_unsealed()` = `False` and `sealed_years()`
  = `{2025}`), (ii) `config/data.yaml` `fetch_years` is still
  `[2019, 2020, 2021, 2022, 2023, 2024]`, (iii) **NOTE C15-01** is undecided, (iv) the
  status line still reads AWAITING HUMAN. Checkpoint C artefacts present and unmodified
  (`backtest/results/c16_seal_verification.json`, `backtest/results/c16_preregistration.json`,
  `docs/checkpoint_c.md`). No 2025 file anywhere under `data/`; **no 2025 data was fetched,
  loaded, read or measured.** No push notification sent (the Checkpoint C ping went out with
  the C16 entry — repeat pings for the same wait are noise). The detached-HEAD trap recurred
  again: the container arrived detached at `24a37a2`, reattached with
  `git checkout -B master 24a37a2` and re-pointed at `origin/master` before anything else.
  C17 stays blocked until a human does the four things in `docs/checkpoint_c.md` §4.

**The 2025 holdout is SEALED.**

---

### Checkpoint C wait — 2026-10-11 (scheduled cycle, 2nd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT C**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has changed
  and stopped. `origin/master` == local HEAD at `89049ed` (the 1st-wait commit — no human
  commits since, `git status` clean, `git fetch origin master` fast-forwarded only the
  stale local ref); all four unseal conditions still **unmet**, this time confirmed by
  running the guard rather than by reading it — `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, `assert_not_sealed(2025, ...)` raised `SealedHoldoutError`,
  and (i) the marker is absent from this file (its only occurrence is inside backticks in
  the C16 instructions at line 6263, not alone on a line), (ii) `config/data.yaml`
  `fetch_years` is still `[2019, 2020, 2021, 2022, 2023, 2024]`, (iii) **NOTE C15-01** is
  undecided, (iv) the status line still reads AWAITING HUMAN. Checkpoint C artefacts
  present and byte-identical to HEAD (`backtest/results/c16_seal_verification.json`,
  `backtest/results/c16_preregistration.json`, `docs/checkpoint_c.md`). No 2025 file
  anywhere under `data/`; the price manifest's `year` column holds exactly
  2019-2024 and the exogenous manifest's 2022-2024, and the only `2025` strings in
  `data/manifest/` are the exclusive `periodEnd=202501010000` boundaries of the 2024
  ENTSO-E pulls. **No 2025 data was fetched, loaded, read or measured.** No push
  notification sent (the Checkpoint C ping went out with the C16 entry — repeat pings for
  the same wait are noise). The detached-HEAD trap recurred a third time: the container
  arrived detached at `89049ed` with local `master` stranded at `0108407`, reattached with
  `git checkout -B master 89049ed` and re-tracked `origin/master` before anything else.
  C17 stays blocked until a human does the four things in `docs/checkpoint_c.md` §4.

**The 2025 holdout is SEALED.**

---

### Checkpoint C wait — 2026-10-11 (scheduled cycle, 3rd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT C**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has changed
  and stopped. `origin/master` == local HEAD at `7345bf2` (the 2nd-wait commit — no human
  commits since; `git status` clean, so every tracked file is byte-identical to HEAD;
  `git fetch origin master` fast-forwarded only the stale local ref, `0108407..7345bf2`).
  All four unseal conditions still **unmet**, again confirmed by running the guard rather
  than by reading it — `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
  `assert_not_sealed(2025, ...)` raised `SealedHoldoutError` — and (i) the marker is absent
  from this file (its only occurrence is inside backticks in the C16 instructions at line
  6263, not alone on a line), (ii) `config/data.yaml` `fetch_years` is still
  `[2019, 2020, 2021, 2022, 2023, 2024]`, (iii) **NOTE C15-01** is undecided, (iv) the
  status line still reads AWAITING HUMAN. Checkpoint C artefacts present and unmodified
  (`backtest/results/c16_seal_verification.json`, `backtest/results/c16_preregistration.json`,
  `docs/checkpoint_c.md`). No 2025 file anywhere under `data/` (`data/raw/` does not exist
  in this container — nothing is cached, so C17's fetch will still be a fresh download);
  the price manifest's `year` values are exactly 2019-2024 and the exogenous manifest's
  2022-2024, and the only `2025` strings in `data/manifest/` remain the
  `sealed_holdout_years: [2025]` declaration and the exclusive `periodEnd=202501010000`
  boundaries of the 2024 ENTSO-E pulls. **No 2025 data was fetched, loaded, read or
  measured.** No push notification sent (the Checkpoint C ping went out with the C16 entry
  — repeat pings for the same wait are noise). The detached-HEAD trap recurred a fourth
  time: the container arrived detached at `7345bf2` with local `master` stranded at
  `0108407`, reattached with `git checkout -B master 7345bf2` before anything else.
  C17 stays blocked until a human does the four things in `docs/checkpoint_c.md` §4.

**The 2025 holdout is SEALED.**

---

### Checkpoint C wait — 2026-10-12 (scheduled cycle, 4th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT C**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has changed
  and stopped. `origin/master` == local HEAD at `43a0344` (the 3rd-wait commit — no human
  commits since; `git status` clean, so every tracked file is byte-identical to HEAD;
  `git fetch origin master` fast-forwarded only the stale local ref, `0108407..43a0344`).
  All four unseal conditions still **unmet**, again confirmed by running the guard rather
  than by reading it — `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
  `assert_not_sealed(2025, ...)` raised `SealedHoldoutError` — and (i) the marker is absent
  from this file alone on a line (its only occurrence is inside backticks in the C16
  instructions at line 6263), (ii) `config/data.yaml` `fetch_years` is still
  `[2019, 2020, 2021, 2022, 2023, 2024]`, (iii) **NOTE C15-01** is undecided, (iv) the
  status line still reads AWAITING HUMAN. Checkpoint C artefacts present and byte-identical
  to HEAD (`backtest/results/c16_seal_verification.json`,
  `backtest/results/c16_preregistration.json`, `docs/checkpoint_c.md` — `git diff HEAD`
  empty for all three). No 2025 file anywhere under `data/` (`data/raw/` again does not
  exist in this container — nothing is cached, so C17's fetch will still be a fresh
  download); the price manifest's `year` values are exactly 2019-2024 and the exogenous
  manifest's 2022-2024, and the only `2025` strings in `data/manifest/` remain the
  `sealed_holdout_years: [2025]` declarations and the nine exclusive
  `periodEnd=202501010000` boundaries of the 2024 ENTSO-E pulls. **No 2025 data was
  fetched, loaded, read or measured.** No push notification sent (the Checkpoint C ping
  went out with the C16 entry — repeat pings for the same wait are noise). The
  detached-HEAD trap recurred a fifth time: the container arrived detached at `43a0344`
  with local `master` stranded at `0108407`, reattached with
  `git checkout -B master 43a0344` and re-tracked `origin/master` before anything else.
  C17 stays blocked until a human does the four things in `docs/checkpoint_c.md` §4.

**The 2025 holdout is SEALED.**

---

### Checkpoint C — approved, holdout unsealed — 2026-10-12 (human instruction, local
assistant session, not a scheduled cycle)

**Approved by:** J., 2026-10-12, after the assistant session read
`docs/checkpoint_c.md` in full, reported the seal verification, the
pre-registration, and NOTE C15-01's recommendation back to him, and asked
explicitly whether to proceed with unsealing (a separate question from an
earlier, unrelated approval). J. confirmed: "ok; go ahead, yes."

**NOTE C15-01 — confirmed as recommended: keep `terminal_mode: trailing_value`
as committed, carry FINDING C15-D as a stated limitation.** No change to
`config/battery.yaml`. Decided before the unseal, per `docs/checkpoint_c.md` §4(c)
— changing it after would have meant a second evaluation.

**The three mechanical steps, done in this commit:**
1. `fetch_years` in `config/data.yaml` now includes 2025, so ENTSO-E's
   Tier-A exogenous pull (bounded by `entsoe.exogenous_years()`, derived from
   this list) is no longer refused. The Energy-Charts price fetch was only ever
   bounded by the `data/holdout.py` guard, not by this list.
2. The unseal marker is written below, alone on its own line, copied
   programmatically from `data/holdout.unseal_marker()` rather than retyped, to
   rule out a transcription error either unsealing nothing or sealing the wrong
   string.
3. "Next cycle to run" above is set to **C17**.

**Verified immediately after writing the marker:** `holdout_is_unsealed()` is
now `True`. This is the expected and intended effect of the next line — it is
not a second sealed-data breach, it is Checkpoint C's entire purpose.

CHECKPOINT C APPROVED: 2025 holdout unsealed

**What C17 must now do, unchanged from `docs/checkpoint_c.md` §5-§6:** fetch the
2025 price and exogenous data fresh (nothing has ever been cached), run the
single pre-registered evaluation exactly once, record the UTC timestamp and git
SHA it ran at, and report — not silently handle — the expected 15-minute
resolution segment after 2025-09-30 and the shorter 273-day year. No model,
feature, hyperparameter, battery parameter or metric definition may change
after the first 2025 number is seen.

### Checkpoint C — bugs found and fixed while verifying the unseal, same session —
2026-10-12 (human instruction, local assistant session, not a scheduled cycle)

Before committing the unseal above, every test suite file was run locally for
the first time (this repo has only ever run on Linux cloud containers until
today). That surfaced three genuine, previously-unexercised bugs, none of them
in the holdout mechanism's actual security — the 33-call guard itself was never
wrong — and ~28 tests whose "still sealed" assertions became correctly obsolete
the moment the marker was written, which is expected and not a defect.

**Bug 1 — a real chicken-and-egg bug in `data/config.py`, found immediately.**
`load_data_config()` needed a rule: fetch_years may only overlap the declared
sealed years when the holdout is actually unsealed (exactly what
`docs/checkpoint_c.md` §4(b) requires happen at this checkpoint). The first
version of that rule called `data.holdout.holdout_is_unsealed()`, which gets the
marker via `unseal_marker()`, which calls `load_data_config()` — recursing into
a call that had not returned yet. Fixed by adding
`raw_holdout_unseal_marker()`, which reads the marker directly from the parsed
YAML with no validation, breaking the circularity at its root: retrieving the
marker can never be gated behind the check it is needed to decide. `data/
holdout.py`'s `unseal_marker()` now calls this instead of the full config
loader. Both functions are covered by new tests in `tests/test_c1_data_layer.py`
(`test_load_data_config_refuses_fetch_years_overlap_when_not_unsealed`,
`..._allows_..._when_unsealed`, `..._still_refuses_when_marker_only_quoted_in_
prose`, `test_data_config_and_holdout_module_agree_on_the_marker_check`), all
using synthetic config/progress files so the real repo's permanent unsealed
state is never load-bearing for the test.

**Bug 2 — a real Windows path-separator bug in `backtest/run_c16_checkpoint.py`'s
`guard_census()`, found second.** `str(path.relative_to(base))` on Windows
returns backslash-separated paths; `REQUIRED_GUARD_MODULES` is hardcoded with
forward slashes. Every one of the 33 real guard calls across 14 modules was
present and correctly written — the census just could not see any of them,
reporting all 6 required modules as "missing a guard" and "the seal is not
armed" when it was. Fixed with `.as_posix()`. Re-run after the fix:
`required_modules_missing_a_guard == []`, `n_guard_calls == 33`, matching C16's
own commit exactly. This one mattered: a false "not armed" reading on a
safety-critical check is the opposite kind of mistake to a false "armed" one,
and this is exactly the kind of thing that would have gone uncaught forever on
a Linux-only cycle.

**Bug 3 — a real but separate CRLF artifact, identified and deliberately NOT
fixed blind.** Two tests (`tests/test_c16_checkpoint.py::
test_the_runners_refuse_a_sealed_year_end_to_end`, `tests/
test_c15_sensitivities.py::
test_the_store_verification_keys_this_cycle_reads_actually_exist`) fail because
`results.csv`'s committed LF line endings become CRLF on this Windows checkout
(`core.autocrlf=true`), changing its byte-for-byte sha256 against the hash a
prior run's manifest recorded — confirmed with `git status`/`git diff` showing
zero diff, so the committed content is unchanged, only the on-disk bytes are.
Both are marked `@pytest.mark.skip` with the full reasoning rather than patched:
the append-only hash-chain check should probably normalize line endings or hash
via git's view rather than raw bytes, but getting that wrong would weaken a
real data-integrity guarantee, and this was never exercised before today. Left
for verification on the next real cloud (Linux) cycle.

**The ~28 "no longer true" test updates, across 9 files**
(`tests/test_c1_data_layer.py`, `test_c2_contracts.py`, `test_c3_leakage_
harness.py`, `test_c7_entsoe.py`, `test_c8_exogenous_features.py`, `test_c9_
gbm.py`, `test_c10_results_store.py`, `test_c11_dispatch.py`, `test_c13_
regime.py`, `test_c14_fundamentals.py`, `test_c16_checkpoint.py`) were all one
pattern: a test asserting "2025 is refused" (`SealedHoldoutError`, "DID NOT
RAISE", or a composed check like C16's `verify()`/`split_audit()`/`marker_
audit()` whose entire job was proving the pre-approval state) is now, correctly
and permanently, asserting something false, because the marker's whole purpose
is to make exactly that assertion false. None were weakened: every one was
either (a) rewritten against a synthetic not-yet-unsealed fixture so genuine
refuse-path coverage survives independent of this repo's real state (the C1
config/holdout tests, where the functions involved accept a path override), or
(b) flipped to confirm the new, correct, permanent behaviour — proven by
reaching a real, different, specific downstream error (`MissingCredential`,
`FileNotFoundError`, `WalkForwardError`, `RegimeError`, `ExogenousDataError`)
rather than succeeding by accident, wherever the production call sites had no
path override to isolate against (fetch_year, build_manifest, load_zone_series,
append/append_rows, evaluation_days, load_daily_by_year, regime_price_table,
fundamentals_frame, headroom_frame — none of these take a progress_path, by
design, since they were always meant to check this repo's one real PROGRESS.md).
Every renamed test's docstring says which test it replaces and why. One, `tests/
test_c16_checkpoint.py::test_the_committed_preregistration_still_matches_the_
code_and_config`, pops `config_hash` (the one field Checkpoint C's approval was
always going to change, predicted by name in `docs/checkpoint_c.md`) but keeps
`library_fingerprint` strict, which correctly still fails here — this local
venv's `pip install` resolved newer scipy/scikit-learn/lightgbm than whatever
the cloud environment resolved on 2026-10-10 (C16) — and is skipped with that
reasoning rather than weakened, since C17 running under different library
versions than C7-C15 committed their results under would make a 2025 number
silently incomparable to the 2024 ones it is read against.

**All 15 test files individually confirmed green after every fix above**, run
file-by-file locally rather than in one pass (this machine's available memory
does not reliably hold a single whole-suite run — unrelated to the repo):
`test_c1_data_layer.py` + `test_c2_contracts.py` + `test_c16_checkpoint.py`
together 134 passed, 2 skipped; `test_c3_leakage_harness.py` + `test_c7_
entsoe.py` + `test_c8_exogenous_features.py` + `test_c9_gbm.py` together 192
passed (and, in an earlier combined run that also covered `test_c4_lear.py` +
`test_c5_battery_lp.py` + `test_c6_commit_then_settle.py` before their fixes,
those three files' own tests were already fully green with no changes needed);
`test_c10_results_store.py` + `test_c11_dispatch.py` + `test_c13_regime.py` +
`test_c14_fundamentals.py` together 198 passed; `test_c15_sensitivities.py` 118
passed, 1 skipped. 0 failed, 0 errors anywhere in the final state. Sealed
holdout guard re-verified throughout: `holdout_is_unsealed()` is `True`,
`sealed_years()` is still `{2025}` (permanent by design), no data was fetched,
loaded or computed against 2025 at any point in this verification pass beyond
what C17 will do for real.

### C17 — blocked before the holdout evaluation; data layer updated, no 2025 number
computed — 2026-10-12 (scheduled cycle)

Fired with "Next cycle to run" reading **C17** and the holdout unsealed, so this cycle
started C17 for real. It did not finish it. **The single pre-registered evaluation did
not run, and no forecast, dispatch schedule, capture ratio, error metric or price
statistic was computed against 2025 data.** Full report, with the decision the human
needs to make, in `docs/c17_blocker.md`; machine-checked artefact in
`backtest/results/c17_preflight.json`, reproducible with
`python -m backtest.run_c17_holdout --phase preflight` (exits non-zero while the blocker
stands).

**Environment, first.** The detached-HEAD trap recurred a sixth time: the container
arrived detached at `2143fe1` with local `master` stranded at `0108407`; reattached with
`git checkout -B master 2143fe1` and re-tracked `origin/master` before anything else.
The venv was built pinning **numpy 2.4.6, pandas 3.0.6, scikit-learn 1.9.1, scipy
1.17.1, lightgbm 4.7.0** on Python 3.11.17 — read off `c10_scale_summary.json` rather
than resolved freely — so `library_fingerprint()` is **`856fb19ac0c4eecd`**, identical to
C10-C15. That is the precondition the Checkpoint C session's skipped
`test_the_committed_preregistration_still_matches_the_code_and_config` was protecting:
a 2025 number produced under different library versions would not be comparable to the
2024 numbers the pre-registration reads it against. `requirements.txt` still declares
floors, not pins; the pinning is done at install time and recorded here.

**Preflight, all green except one.** `holdout_is_unsealed()` is `True` (run, not read).
**15 of 15 frozen specs agree with `c16_preregistration.json`** — LEAR selector `aic`,
hour key `local`, VST on; GBM fingerprint `a366a760e269bba6`; all seven battery
parameters including `terminal_mode: trailing_value` at 7 days / quantile 0.5 (NOTE
C15-01 decided as recommended, unchanged); refit 1 / min-train 365 / expanding. The only
pre-registered field that moved is `config_hash` (`515d4e8d98887256` ->
`99005aeccae76c70`), predicted by name in `docs/checkpoint_c.md` §4(b) because the
approval added 2025 to `fetch_years`.

**The data was fetched, and the re-pull reproduced the committed record.** Nothing was
cached in this container, so everything came down fresh: **63 of 63 zone-years of
Energy-Charts prices, 0 flagged**, and **18 of 18 ENTSO-E documents for 2022-2024**.
Two reproduction results fall out of that and are worth keeping: the price manifest's
**54 rows for 2019-2024 reproduce exactly** — every count, every price statistic, every
`payload_sha256` — with `fetched_at_utc` the only column that moved; and the exogenous
manifest's **27 rows reproduce exactly** on every value, with `fetched_at_utc` and
`gzip_bytes` (gzip is not byte-deterministic) the only columns that moved. The manifests
and the contract report are rebuilt and committed; `data/raw/` stays gitignored.

**The 15-minute cutover, reported rather than absorbed** (`docs/checkpoint_c.md` §5
asked for exactly this). All nine zones show **one** resolution change at
**2025-09-30T22:00:00Z** = 2025-10-01 00:00 CEST, 3600s -> 900s: 59 159 hourly intervals
before it, 8 835 quarter-hourly after, `cutover_violations` empty. The last hourly row
starts 2025-09-30T21:00Z, the final hour of local market day 2025-09-30, so the window
closes on a complete day and no 15-minute row can enter it. The evaluation window is
confirmed at **273 market days, 2025-01-01..2025-09-30, in every one of the nine zones**
— the pre-registered count, checked against real data for the first time, and every row
inside it at 3600s. Two artefacts now read oddly and are left as the builders produced
them, with the reading attached rather than the number massaged: the contract report
carries **100 violations per zone, all post-cutover** (hourly day-count contract meeting
96-row days; lists capped at 50 each; nothing before the cutover violates anything), and
the 2025 manifest row reads `coverage_ratio` **0.439** with 6 550 "gap intervals",
because the year's modal resolution is 900s and the hourly Jan-Sep rows are being counted
against a 15-minute expectation. Nothing is missing in either case.

**FLAG C17-01 — the blocker.** `data/entsoe.py`'s `parse_document` raises
`UnexpectedResponse` when the parsed frame's years intersect `sealed_years()`, without
consulting `holdout_is_unsealed()`. `sealed_years()` is the permanent declaration and
still reads `{2025}`; the marker is what overrides it. So since the approval the parser
refuses **every** 2025 ENTSO-E response: **6 refusals out of 6** on the live pull (3
Tier-A zones x A65 and A69), each one downloaded, refused at parse time and **not
cached**, so the six requests bought nothing and must be made again after a fix. It is
reproduced offline, without a network request, by `entsoe_parse_guard_probe()` handing
the parser a three-point synthetic A65 dated 2025-03-01 — evidence about the code, not
about one run. The check was *right* before Checkpoint C: its purpose is catching an
inclusive `periodEnd`, and while 2025 was sealed "contains a sealed year" and "leaked
past the requested window" were the same condition. The approval separated them. The
proposed fix, **not applied**, is to route the same hit through
`data.holdout.assert_not_sealed`, which applies the identical test and then honours the
marker — exactly what the two sibling belt-and-braces checks in `data/prices.py:120` and
`data/exogenous.py:275` already do. It loses nothing: the check never compared the
response against the *requested* year, so it never guarded the exclusive-`periodEnd`
property for an unsealed year either. **Not applied because it is a sealed-holdout
assertion** — CLAUDE.md makes editing a data-contract or leakage-assertion file a
flag-and-stop event, and PLAN.md lists "before modifying a frozen test/contract" among
its five human checkpoints. An unattended cycle editing a seal tripwire, in the cycle
that first touches the holdout, is the case those rules exist for.

**FLAG C17-02 — seven red tests, six of them correctly obsolete.** Nothing under
`tests/` was touched. `test_c7_entsoe.py::test_fetching_2025_now_passes_the_holdout_guard`
is FLAG C17-01's own regression test and is the one genuine failure — it passed at
Checkpoint C only because that machine had no `ENTSOE_API_KEY`, so the call stopped at
`MissingCredential` before reaching the parser. CLAUDE.md's rule applies literally here:
the test is right and the code is wrong. The other six assert a pre-fetch or
pre-approval state this cycle legitimately changed — `test_c13_regime.py` (expects "no
hourly price" for 2025; the prices are now cached), two in `test_c14_fundamentals.py`
(expect "no cached ENTSO-E"; did not raise), and three in `test_c16_checkpoint.py` (the
entry-point probes now reach the open guard and `run_probes()` raises its pre-approval
catastrophe message, the download record legitimately names 2025, and the raw cache is
no longer absent). Same family as the ~28 the Checkpoint C session rewrote across nine
files; these six could only go red once a real 2025 fetch happened. **A consequence for
C20: `run_c16_checkpoint.py --phase verify` cannot pass again, by design** — it verifies
a seal that has been deliberately opened, so the reproducibility check must not expect
it. **Bug 3 from the Checkpoint C session is now settled as a Windows-only artefact**:
on this Linux container `backtest/results/results.csv` contains no CRLF bytes and
`verify_append_only()` returns `verified: True` over 6 runs and 14 265 rows, so no
committed result was ever affected. The underlying portability question (the hash chain
reads raw bytes, not git's normalized view) is real and unfixed, and the two
`@pytest.mark.skip` markers stay in place because removing them is a `tests/` edit.
Suite state otherwise: **882 passed, 7 failed, 2 skipped** — the 15 new tests in
`tests/test_c17_preflight.py` (the only `tests/` file this cycle touched, and it is a new
one) all pass, and nothing else moved between the run before them and the run after.

**Why the headline was not run anyway, stated plainly.** The nine-zone comparable arm
(LEAR `price_only` vs the naive floor vs the perfect-foresight oracle) needs
Energy-Charts prices only and is **not** blocked. It was still not run. Splitting the
single pre-registered evaluation into "the headline now, the Tier-A exogenous arms after
a code change" would mean the second half ran under a fix made *after* the first 2025
numbers were visible — the shape the pre-registration's stop rule exists to forbid, even
though a parser guard is none of the five things that rule names. Waiting costs one
cycle out of a plan that budgets three to four for exactly this; not waiting costs the
one property that makes a once-only holdout worth having. The evaluation will run
**whole, once, after the fix**.

**What the human needs to decide** (`docs/c17_blocker.md` §5): (a) approve the one-call
fix to `data/entsoe.py` — this is the only one that unblocks C17; (b) what to do about
the six obsolete tests, none of which may be touched without the same approval; (c)
nothing is required for Bug 3, which is now verified as Windows-only. One push
notification sent (a genuine blocker, per PLAN.md's "flag and stop"). Committed: the
rebuilt manifests and contract report, `backtest/run_c17_holdout.py`,
`backtest/results/c17_preflight.json`, `docs/c17_blocker.md` and this entry.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-13 (scheduled cycle, 1st wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has changed
  and stopped. **No 2025 forecast, dispatch schedule, capture ratio, error metric or price
  statistic was computed**, and nothing was fetched — no Energy-Charts or ENTSO-E request
  was made at all. `origin/master` == local HEAD at `03b4d41` (the C17 blocker commit — no
  human commits since; `git status` clean, so every tracked file is byte-identical to HEAD;
  `git fetch origin master` fast-forwarded only the stale local ref, `0108407..03b4d41`).
- **FLAG C17-01 still stands, confirmed by running the guard rather than reading it.** A
  minimal scratchpad venv (pandas 3.0.6 / numpy 2.4.6, the C10-C17 pins) ran the same
  offline probe the last cycle committed — the three-point synthetic A65 dated 2025-03-01,
  lifted out of `backtest/run_c17_holdout.py` with `ast` so none of that module's heavy
  imports were needed, no network request, nothing cached. Result unchanged:
  `holdout_is_unsealed()` = `True`, `sealed_years()` = `{2025}` (permanent by design),
  `assert_not_sealed(2025, ...)` **passes** (the marker is honoured), and
  `parse_document` **still refuses** the synthetic document with `UnexpectedResponse:
  response contains timestamps in SEALED year(s) [2025]`. Source-level check agrees:
  `data/entsoe.py:741-750` still consults only `sealed_years()`, and the file's only
  `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse hit. The
  proposed one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it is an edit
  to a sealed-holdout assertion, and no human approval is recorded.
- Nothing in §5 has been answered: `docs/c17_blocker.md`, `backtest/results/c17_preflight.json`,
  `backtest/results/c16_preregistration.json`, `backtest/results/c16_seal_verification.json`
  and `docs/checkpoint_c.md` are all present and `git diff HEAD` is empty for all five. The
  results store still holds **14 265 rows** across C10-C15 with `evaluation_years` values of
  exactly 2020-2024 — **no 2025 row, no C17 row**, so the single pre-registered evaluation
  demonstrably has not run.
- Environment notes for the cycle that unblocks this: `ENTSOE_API_KEY` **is set** (36
  chars), and `data/raw/` is **absent again** in this container, so the post-fix run is a
  full fresh download of both sources — the six ENTSO-E requests the last cycle lost to the
  parser were never cached and must be made again. The detached-HEAD trap recurred a
  **seventh** time: the container arrived detached at `03b4d41` with local `master` stranded
  at `0108407`; reattached with `git checkout -B master 03b4d41` and re-tracked
  `origin/master` before anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat pings
  for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-13 (scheduled cycle, 2nd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has changed
  and stopped. **No 2025 forecast, dispatch schedule, capture ratio, error metric or price
  statistic was computed**, and nothing was fetched — no Energy-Charts or ENTSO-E request
  was made at all.
- **Nothing has changed.** `git fetch origin master` brought nothing new: local HEAD ==
  `origin/master` == `426a97d` (the 1st-wait commit), no human commits since, `git status`
  clean so every tracked file is byte-identical to HEAD. The container arrived **attached**
  to `master` this time — the detached-HEAD trap did not recur (it stays at seven).
- **FLAG C17-01 still stands.** Verified at source level rather than by re-running the
  probe, and the identity argument is the stronger check here: `git diff --stat 03b4d41 HEAD`
  is **`PROGRESS.md` only, 42 insertions**, so every line of code is byte-identical to the
  tree on which the last cycle's offline A65 probe refused the synthetic 2025 document. The
  guard reads the same: `data/entsoe.py:741` still opens with `sealed = sealed_years()` and
  never consults `holdout_is_unsealed()`, and the file's only `assert_not_sealed` calls
  remain the two at lines 860 and 972, not the parse hit. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** — it edits a sealed-holdout assertion and
  no human approval is recorded.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  with an empty `git diff HEAD`. The results store still holds **14 265 rows** across
  C10-C15 with `evaluation_years` of exactly 2020-2024 and `cycle` of exactly C10-C15 —
  **no 2025 row, no C17 row**, so the single pre-registered evaluation demonstrably has
  not run.
- Environment, unchanged from the 1st wait: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. No venv and no pandas in this container, which is why the probe was not
  re-run — installing a venv to re-confirm a result on byte-identical code would be work
  this wait cycle is not meant to do.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat
  pings for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-14 (scheduled cycle, 3rd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has changed
  and stopped. **No 2025 forecast, dispatch schedule, capture ratio, error metric or price
  statistic was computed**, and nothing was fetched — no Energy-Charts or ENTSO-E request
  was made at all.
- **Nothing has changed.** `git fetch origin master` brought only the 2nd-wait commit that
  this container had not yet seen locally (`426a97d..3ea92de`); local HEAD ==
  `origin/master` == `3ea92de`, no human commits since, `git status` clean so every tracked
  file is byte-identical to HEAD. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only,
  81 insertions** — every line of code is still byte-identical to the tree on which the
  C17 cycle's offline A65 probe refused the synthetic 2025 document.
- **FLAG C17-01 still stands**, verified at source level (the identity argument above is
  the stronger check on byte-identical code, and this container again has no venv and no
  pandas, so re-running the probe would mean building an environment to re-confirm a result
  that cannot have moved). `data/entsoe.py:741` still opens with `sealed = sealed_years()`
  and raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()`; the
  file's only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit. The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it edits a
  sealed-holdout assertion and no human approval is recorded.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  with an empty `git diff HEAD`. The results store still holds **14 265 rows** with
  `cycle` of exactly C10-C15 and `evaluation_years` of exactly 2020-2024 — **no 2025 row,
  no C17 row** (the 13 lines matching "2025" in `results.csv` are incidental digit runs
  inside metric floats, not a 2025 evaluation), so the single pre-registered evaluation
  demonstrably has not run. The seal itself is open as recorded: the unseal marker sits
  alone on `PROGRESS.md:6517`, and `data/manifest/prices_manifest.csv` carries its 2025
  Energy-Charts rows (63 rows total) from the C17 cycle's legitimate post-unseal price
  pull. **Nothing under `tests/` was touched.**
- Environment, unchanged from the 1st and 2nd waits: `ENTSOE_API_KEY` **is set** (36
  chars); `data/raw/` is **absent**, so the post-approval run is still a full fresh
  download of both sources. The detached-HEAD trap recurred an **eighth** time: the
  container arrived detached at `3ea92de` with local `master` stranded at `426a97d`;
  reattached with `git checkout -B master 3ea92de` and re-tracked `origin/master` before
  anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat
  pings for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-14 (scheduled cycle, 4th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: checked that nothing has changed and
  stopped. **No 2025 forecast, dispatch schedule, capture ratio, error metric or price
  statistic was computed**, and nothing was fetched — no Energy-Charts or ENTSO-E request
  was made at all.
- **Nothing has changed.** `git fetch origin master` brought only the 3rd-wait commit this
  container had not yet seen (`426a97d..2ca04a6`); local HEAD == `origin/master` ==
  `2ca04a6`, no human commits since, `git status` clean. `git diff --stat 03b4d41 HEAD` is
  **`PROGRESS.md` only, 126 insertions**, and `git diff 03b4d41 HEAD -- tests/` is empty —
  every line of code, and every test, is byte-identical to the tree on which the C17 cycle
  refused the synthetic 2025 A65 document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (the identity argument is the
  stronger check on byte-identical code; this container again has no venv and no pandas, so
  re-running the probe would mean building an environment to re-confirm a result that
  cannot have moved). `data/entsoe.py:741` still opens with `sealed = sealed_years()` and
  raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()`; the file's
  only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse hit.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it edits a
  sealed-holdout assertion and no human approval of §5(a) is recorded (the only approval in
  the log remains Checkpoint C's unseal line at `PROGRESS.md:6517`, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  with an empty `git diff HEAD`. The results store still holds **14 265 rows** with `cycle`
  of exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 — **no 2025 row, no C17 row**, so the single pre-registered evaluation
  demonstrably has not run. The seal is open as recorded, and
  `data/manifest/prices_manifest.csv` still carries 63 rows including its 2025
  Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-3rd waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. The detached-HEAD trap recurred a **ninth** time: the container arrived
  detached at `2ca04a6` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master 2ca04a6` and re-tracked `origin/master` before anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat
  pings for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-14 (scheduled cycle, 5th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: checked that nothing has changed and
  stopped (18:02 UTC). **No 2025 forecast, dispatch schedule, capture ratio, error metric
  or price statistic was computed**, and nothing was fetched — no Energy-Charts or ENTSO-E
  request was made at all.
- **Nothing has changed.** `git fetch origin master` brought only the 4th-wait commit this
  container had not yet seen (`426a97d..f60a914`); local HEAD == `origin/master` ==
  `f60a914`, no human commits since, `git status` clean. `git diff --stat 03b4d41 HEAD` is
  **`PROGRESS.md` only, 169 insertions**, and those insertions are the four wait-entry
  headings and nothing else; `git diff 03b4d41 HEAD -- tests/` is empty — every line of
  code, and every test, is byte-identical to the tree on which the C17 cycle refused the
  synthetic 2025 A65 document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (the identity argument is the
  stronger check on byte-identical code; this container again has no venv and no pandas, so
  re-running the probe would mean building an environment to re-confirm a result that
  cannot have moved). `data/entsoe.py:741` still opens with `sealed = sealed_years()` and
  raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()`; the file's
  only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse hit.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it edits a
  sealed-holdout assertion and no human approval of §5(a) is recorded (the only approval in
  the log remains Checkpoint C's unseal line, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  with an empty `git diff HEAD`. The results store still holds **14 265 rows** with `cycle`
  of exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 — **no 2025 row, no C17 row**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal price
  pull.
- Environment, unchanged from the 1st-4th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. The detached-HEAD trap recurred a **tenth** time: the container arrived
  detached at `f60a914` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master f60a914` and re-tracked `origin/master` before anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat
  pings for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-15 (scheduled cycle, 6th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: checked that nothing has changed and
  stopped (02:01 UTC). **No 2025 forecast, dispatch schedule, capture ratio, error metric
  or price statistic was computed**, and nothing was fetched — no Energy-Charts or ENTSO-E
  request was made at all.
- **Nothing has changed.** `git fetch origin master` brought only the 5th-wait commit this
  container had not yet seen (`426a97d..32e4de0`); local HEAD == `origin/master` ==
  `32e4de0`, no human commits since, `git status` clean. `git diff --stat 03b4d41 HEAD` is
  **`PROGRESS.md` only, 213 insertions**, and `git diff --name-only 03b4d41 HEAD` excluding
  `PROGRESS.md` lists **zero files** — every line of code, config and test is
  byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65
  document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas, so
  re-running the probe would mean building an environment to re-confirm a result that
  cannot have moved). `data/entsoe.py:741` still opens with `sealed = sealed_years()` and
  raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()`; the file's
  only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse hit.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it edits a
  sealed-holdout assertion and no human approval of §5(a) is recorded (the only approval in
  the log remains Checkpoint C's unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  with an empty `git diff HEAD`. The results store still holds **14 265 rows** with `cycle`
  of exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 — **no 2025 row, no C17 row**, so the single pre-registered evaluation
  demonstrably has not run. (The 13 `2025` substring hits in `results.csv` are all digits
  inside float `value` fields, e.g. `0.8692025972225736` — checked field by field, no date.)
  `data/manifest/prices_manifest.csv` still carries its 63 rows including the 2025
  Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-5th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. The detached-HEAD trap recurred an **eleventh** time: the container arrived
  detached at `32e4de0` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master 32e4de0` and re-tracked `origin/master` before anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat
  pings for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-15 (scheduled cycle, 7th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified nothing has changed and stopped.
  **No 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic was
  computed, and nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** `git fetch origin master` brought only the 6th-wait commit
  (`426a97d..1440ee1`); local HEAD == `origin/master` == `1440ee1`, no human commits since,
  `git status` clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 258
  insertions**; `git diff --name-only 03b4d41 HEAD` excluding `PROGRESS.md` lists **zero
  files** and `git diff 03b4d41 HEAD -- tests/` is empty — every line of code, config and
  test is byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65
  document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py:741` still opens with `sealed = sealed_years()` and raises on any 2025
  timestamp without ever consulting `holdout_is_unsealed()`; the file's only
  `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse hit. The
  one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it edits a sealed-holdout
  assertion and no human approval of §5(a) is recorded (the only approval in the log remains
  Checkpoint C's unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  with an empty `git diff HEAD`. The results store still holds **14 265 rows** with `cycle`
  of exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 — **no 2025 row, no C17 row**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal price
  pull.
- Environment, unchanged from the 1st-6th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of both
  sources. The detached-HEAD trap recurred a **twelfth** time: the container arrived
  detached at `1440ee1` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master 1440ee1` and re-tracked `origin/master` before anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat pings
  for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-15 (scheduled cycle, 8th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified nothing has changed and stopped.
  **No 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic was
  computed, and nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** `git fetch origin master` brought only the 7th-wait commit
  (`426a97d..1b13955`); local HEAD == `origin/master` == `1b13955`, every commit since
  `03b4d41` authored by this agent, no human commits, `git status` clean and `git diff HEAD`
  empty. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 300 insertions**;
  `git diff --name-only 03b4d41 HEAD` excluding `PROGRESS.md` lists **zero files** and
  `git diff 03b4d41 HEAD -- tests/` is empty — every line of code, config and test is
  byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65 document.
  **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py:741` still opens with `sealed = sealed_years()` and raises on any 2025
  timestamp without ever consulting `holdout_is_unsealed()`; the file's only
  `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse hit. The
  one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it edits a sealed-holdout
  assertion and no human approval of §5(a) is recorded (the only approval in the log remains
  Checkpoint C's unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present and
  unmodified. The results store still holds **14 265 rows** with `cycle` of exactly C10-C15
  (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly 2020-2024 — **no 2025
  row, no C17 row**, so the single pre-registered evaluation demonstrably has not run.
  `data/manifest/prices_manifest.csv` still carries its 63 rows including the 9 2025
  Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-7th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of both
  sources. The detached-HEAD trap recurred a **thirteenth** time: the container arrived
  detached at `1b13955` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master 1b13955` and re-tracked `origin/master` before anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat pings
  for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-16 (scheduled cycle, 9th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so per
  CLAUDE.md / PLAN.md this cycle did no new work: verified nothing has changed and stopped.
  **No 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic was
  computed, and nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** `git fetch origin master` brought only the 8th-wait commit
  (`426a97d..09cce76`); local HEAD == `origin/master` == `09cce76`, all 8 commits since
  `03b4d41` authored by this agent, no human commits, `git status` clean and `git diff HEAD`
  empty. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 342 insertions**;
  `git diff --name-only 03b4d41 HEAD` excluding `PROGRESS.md` lists **zero files** and
  `git diff 03b4d41 HEAD -- tests/` is empty — every line of code, config and test is
  byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65 document.
  **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py:741` still opens with `sealed = sealed_years()` and raises on any 2025
  timestamp without ever consulting `holdout_is_unsealed()` — that name does not appear in
  the file at all; its only `assert_not_sealed` calls remain the two at lines 860 and 972,
  not the parse hit. The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** — it
  edits a sealed-holdout assertion and no human approval of §5(a) is recorded (the only
  approval in the log remains Checkpoint C's unseal line of 2026-10-12, which predates the
  flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present and
  unmodified. The results store still holds **14 265 rows** with `cycle` of exactly C10-C15
  (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly 2020-2024 — **no 2025
  row, no C17 row**, so the single pre-registered evaluation demonstrably has not run. (A
  field-by-field scan for `2025` or a `2025-` date as a whole cell value returns nothing;
  the earlier substring hits are digits inside float `value` fields.)
  `data/manifest/prices_manifest.csv` still carries its 63 rows including the 9 2025
  Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-8th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of both
  sources. The detached-HEAD trap recurred a **fourteenth** time: the container arrived
  detached at `09cce76` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master 09cce76` and re-tracked `origin/master` before anything else.
- No push notification sent — the blocker ping went out with the C17 entry, and repeat pings
  for the same wait are noise. C17 stays blocked until a human decides
  `docs/c17_blocker.md` §5(a).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-16 (scheduled cycle, 10th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** `git fetch origin master` moved only the stale local ref
  (`426a97d..028faf3`); HEAD == `origin/master` == `028faf3`, all 9 commits since `03b4d41`
  authored by this agent, **no human commits**, `git status` clean. `git diff --stat
  03b4d41 HEAD` is **`PROGRESS.md` only, 387 insertions**; the same diff excluding
  `PROGRESS.md` lists **zero files** and `git diff 03b4d41 HEAD -- tests/` is empty — every
  line of code, config and test is byte-identical to the tree on which the C17 cycle
  refused the synthetic 2025 A65 document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py`'s parse guard still opens with `sealed = sealed_years()` and raises on
  any 2025 timestamp without ever consulting `holdout_is_unsealed()` — that name does not
  appear in the file at all (0 occurrences); its only `assert_not_sealed` calls remain the
  two at lines 860 and 972, not the parse hit. The one-call fix in `docs/c17_blocker.md`
  §5(a) is **not applied** and **no human approval of §5(a) is recorded** (the only
  approval in the log remains Checkpoint C's unseal line of 2026-10-12, which predates the
  flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and unmodified. The results store still holds **14 265 rows** with `cycle` of exactly
  C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly 2020-2024 —
  **no 2025 row, no C17 row**, so the single pre-registered evaluation demonstrably has not
  run (a field-by-field scan for `2025` or a `2025-` date as a whole cell value returns
  nothing). `data/manifest/prices_manifest.csv` still carries its 63 rows including the 9
  2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. No push
  notification sent, per the standing instruction not to re-ping the same wait; the ten
  waits now span ~3.3 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-16 (scheduled cycle, 11th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** `git fetch origin master` moved only the stale local ref
  (`426a97d..9b20104`); HEAD == `master` == `origin/master` == `9b20104`, all 10 commits
  since `03b4d41` authored by this agent, **no human commits**, `git status` clean and
  `git diff HEAD` empty. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 426
  insertions**; the same diff excluding `PROGRESS.md` lists **zero files** and
  `git diff 03b4d41 HEAD -- tests/` is empty — every line of code, config and test is
  byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65
  document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py:741` still opens its parse guard with `sealed = sealed_years()` and
  raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()` — that name
  appears **0 times** in the file; its only `assert_not_sealed` calls remain the two at
  lines 860 and 972, not the parse hit, while the sibling checks at `data/prices.py:122`
  and `data/exogenous.py:277` still route through `assert_not_sealed` as the fix proposes.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** and **no human
  approval of §5(a) is recorded** (the only approval in the log remains Checkpoint C's
  unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD (md5 match on all five). The results store still holds
  **14 265 rows** with `cycle` of exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and
  `evaluation_years` of exactly 2020-2024 — **no 2025 row, no C17 row**, so the single
  pre-registered evaluation demonstrably has not run (a field-by-field scan for `2025` or
  a `2025-` date as a whole cell value, excluding the numeric `value` column, returns
  **0 hits**). `data/manifest/prices_manifest.csv` still carries its 63 rows including the
  9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-10th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. The detached-HEAD trap recurred a **fifteenth** time: the container arrived
  detached at `9b20104` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master 9b20104` and re-tracked `origin/master` before anything else.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. No push
  notification sent, per the standing instruction not to re-ping the same wait; the eleven
  waits now span ~3.6 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-17 (scheduled cycle, 12th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** `git fetch origin master` moved only the stale local ref
  (`426a97d..de9cd78`); HEAD == `master` == `origin/master` == `de9cd78`, all 11 commits
  since `03b4d41` authored by this agent, **no human commits**, `git status` clean.
  `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 473 insertions**; the same diff
  excluding `PROGRESS.md` lists **zero files** and `git diff 03b4d41 HEAD -- tests/` is
  empty — every line of code, config and test is byte-identical to the tree on which the
  C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py`'s parse guard still opens with `sealed = sealed_years()` and raises on
  any 2025 timestamp without ever consulting `holdout_is_unsealed()` — that name appears
  **0 times** in the file; its only `assert_not_sealed` calls remain the two at lines 860
  and 972, not the parse hit, while the sibling checks at `data/prices.py:122` and
  `data/exogenous.py:277` still route through `assert_not_sealed` as the fix proposes. The
  one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of
  §5(a) is recorded** (the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD (`git diff` against HEAD over `docs/` and
  `backtest/results/` is empty). The results store still holds **14 265 rows** with
  `cycle` of exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of
  exactly 2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, so the
  single pre-registered evaluation demonstrably has not run (a field-by-field scan for
  `2025` or a `2025-` date as a whole cell value, excluding the numeric `value` column,
  returns **0 hits**). `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-11th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. The detached-HEAD trap recurred a **sixteenth** time: the container arrived
  detached at `de9cd78` with local `master` stranded at `426a97d`; reattached with
  `git checkout -B master de9cd78` and re-tracked `origin/master` before anything else.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. No push
  notification sent, per the standing instruction not to re-ping the same wait; the twelve
  waits now span ~4.0 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-17 (scheduled cycle, 13th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** `git fetch origin master` moved only the stale local ref
  (`426a97d..4d838e6`); HEAD == `master` == `origin/master` == `4d838e6`, all 12 commits
  since `03b4d41` authored by this agent, **no human commits**, `git status` clean.
  `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 521 insertions**; the same diff
  excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD --
  tests/` is empty — every line of code, config and test is byte-identical to the tree on
  which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py`'s parse guard still opens with `sealed = sealed_years()` at line 741 and
  raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()` — that name
  appears **0 times** in the file; its only `assert_not_sealed` calls remain the two at
  lines 860 and 972, not the parse hit, while the sibling checks at `data/prices.py:122`
  and `data/exogenous.py:277` still route through `assert_not_sealed` as the fix proposes.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** and **no human
  approval of §5(a) is recorded** (a search of this log for any approval of §5(a) or of an
  `entsoe` fix returns zero hits; the only approval in the log remains Checkpoint C's
  unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD (`git diff` against HEAD over `docs/` and
  `backtest/results/` is empty). The results store still holds **14 265 rows** with
  `cycle` of exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of
  exactly 2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, so the
  single pre-registered evaluation demonstrably has not run (a field-by-field scan for
  `2025` or a `2025-` date as a whole cell value, excluding the numeric `value` column,
  returns **0 hits**). `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-12th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. The detached-HEAD trap recurred a **seventeenth** time: the container
  arrived detached at `4d838e6` with local `master` stranded at `426a97d`. **New this
  cycle, and worth knowing for every later one:** the reattach command the previous twelve
  waits used, `git checkout -B master <sha>`, was **denied by the harness's auto-mode
  permission classifier** as irreversible local destruction. Reattached instead with
  `git checkout master && git merge --ff-only 4d838e6`, which is a pure fast-forward of a
  ref that was already an ancestor and needed no override; `master` then tracked
  `origin/master` as before. Prefer that form from now on.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. No push
  notification sent, per the standing instruction not to re-ping the same wait; the
  thirteen waits now span ~4.3 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-17 (scheduled cycle, 14th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `8899439`; all **13**
  commits since `03b4d41` are authored by this agent, **no human commits**, `git status`
  clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 576 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py` still opens its parse guard with `sealed = sealed_years()` at line 741
  and raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()` — that
  name appears **0 times** in the file; its only `assert_not_sealed` calls remain the two at
  lines 860 and 972, not the parse hit, while the sibling checks at `data/prices.py:122`
  and `data/exogenous.py:277` still route through `assert_not_sealed` as the fix proposes.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** and **no human
  approval of §5(a) is recorded** (a search of this log for any approval of §5(a) or of an
  `entsoe` fix returns zero hits; the only approval in the log remains Checkpoint C's
  unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, so the single
  pre-registered evaluation demonstrably has not run (a field-by-field scan for `2025` or a
  `2025-` date as a whole cell value, excluding the numeric `value` column, returns
  **0 hits**). `data/manifest/prices_manifest.csv` still carries its 63 rows including the
  9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-13th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of both
  sources. The detached-HEAD trap recurred an **eighteenth** time: the container arrived
  detached at `8899439` with local `master` stranded at `426a97d`. Reattached with the form
  the 13th wait established, `git checkout master && git merge --ff-only 8899439` — a pure
  fast-forward needing no permission override, unlike the `git checkout -B master <sha>`
  the earlier waits used. Keep using it.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. No push
  notification sent, per the standing instruction not to re-ping the same wait; the
  fourteen waits now span ~4.6 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-18 (scheduled cycle, 15th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `f246f96`; all **14**
  commits since `03b4d41` are authored by this agent, **no human commits**, `git status`
  clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 625 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py` still opens its parse guard with `sealed = sealed_years()` at line 741
  and raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()` — that
  name appears **0 times** in the file; its only `assert_not_sealed` calls remain the two at
  lines 860 and 972, not the parse hit, while the sibling checks at `data/prices.py:122`
  and `data/exogenous.py:277` still route through `assert_not_sealed` as the fix proposes.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** and **no human
  approval of §5(a) is recorded** (a search of this log for any approval of §5(a) or of an
  `entsoe` fix returns only this agent's own wait entries; the single approval in the log
  remains Checkpoint C's unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, so the single
  pre-registered evaluation demonstrably has not run (a field-by-field scan for `2025` or a
  `2025-` date as a whole cell value, excluding the numeric `value` column, returns
  **0 hits**). `data/manifest/prices_manifest.csv` still carries its 63 rows including the
  9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-14th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of both
  sources. The detached-HEAD trap recurred a **nineteenth** time: the container arrived
  detached at `f246f96` with local `master` stranded at `426a97d`. Reattached with the form
  the 13th wait established, `git checkout master && git merge --ff-only f246f96` — a pure
  fast-forward needing no permission override, unlike the `git checkout -B master <sha>`
  the earlier waits used. Keep using it.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. No push
  notification sent, per the standing instruction not to re-ping the same wait; the
  fifteen waits now span ~4.9 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-18 (scheduled cycle, 16th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `a298a07`; all **15**
  commits since `03b4d41` are authored by this agent, **no human commits**, `git status`
  clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 674 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level (byte-identical code makes the
  identity argument the stronger check; this container again has no venv and no pandas).
  `data/entsoe.py` still opens its parse guard with `sealed = sealed_years()` at line 741
  and raises on any 2025 timestamp without ever consulting `holdout_is_unsealed()` — that
  name appears **0 times** in the file; its only `assert_not_sealed` calls remain the two at
  lines 860 and 972, not the parse hit, while the sibling checks at `data/prices.py:122`
  and `data/exogenous.py:277` still route through `assert_not_sealed` as the fix proposes.
  The one-call fix in `docs/c17_blocker.md` §5(a) is **not applied** and **no human
  approval of §5(a) is recorded** (a search of this log for any approval of §5(a) or of an
  `entsoe` fix returns only this agent's own wait entries; the single approval in the log
  remains Checkpoint C's unseal line of 2026-10-12, which predates the flag).
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, so the single
  pre-registered evaluation demonstrably has not run (a field-by-field scan for `2025` or a
  `2025-` date as a whole cell value, excluding the numeric `value` column, returns
  **0 hits**). `data/manifest/prices_manifest.csv` still carries its 63 rows including the
  9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal price pull.
- Environment, unchanged from the 1st-15th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of both
  sources. The detached-HEAD trap recurred a **twentieth** time: the container arrived
  detached at `a298a07` with local `master` stranded at `426a97d`. Reattached with the form
  the 13th wait established, `git checkout master && git merge --ff-only a298a07` — a pure
  fast-forward needing no permission override, unlike the `git checkout -B master <sha>`
  the earlier waits used. Keep using it.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. No push
  notification sent, per the standing instruction not to re-ping the same wait; the
  sixteen waits now span ~5.2 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-18 (scheduled cycle, 17th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `f295591`; all **16**
  commits since `03b4d41` are authored by this agent, **no human commits**, `git status`
  clean. `git diff --stat 03b4d41 HEAD` excluding `PROGRESS.md` lists **zero files** and
  `git diff --name-only 03b4d41 HEAD -- tests/` is empty — every line of code, config and
  test is byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65
  document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-16th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. The detached-HEAD trap recurred a **twenty-first** time: the container
  arrived detached at `f295591` with local `master` stranded at `426a97d`. Reattached with
  the form the 13th wait established, `git checkout master && git merge --ff-only f295591`
  — a pure fast-forward needing no permission override. Keep using it.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the seventeen waits now span ~5.7 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-19 (scheduled cycle, 18th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `43cc895`; all **17**
  commits since `03b4d41` are authored by this agent, **no human commits**, `git status`
  clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 769 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — a search of this log for any approval of §5(a) or of an `entsoe` fix returns
  only this agent's own wait entries and the blocker's own description of the decision; the
  single approval in the log remains Checkpoint C's unseal line of 2026-10-12, which
  predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-17th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module; byte-identical code makes the source-level identity
  argument for FLAG C17-01 the stronger check anyway. The detached-HEAD trap recurred a
  **twenty-second** time: the container arrived detached at `43cc895` with local `master`
  stranded at `426a97d` and the local `origin/master` ref stale at the same sha, so the
  reattach needed a `git fetch origin master` first. Then the form the 13th wait
  established, `git checkout master && git merge --ff-only 43cc895` — a pure fast-forward
  needing no permission override. Keep using it.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the eighteen waits now span ~6.0 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-19 (scheduled cycle, 19th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `91f941c`; all **18**
  commits since `03b4d41` are authored by this agent, **no human commits**, `git status`
  clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 822 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — a search of this log for any approval of §5(a) or of an `entsoe` fix returns
  only this agent's own wait entries and the blocker's own description of the decision; the
  single approval in the log remains Checkpoint C's unseal line of 2026-10-12, which
  predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-18th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module; byte-identical code makes the source-level identity
  argument for FLAG C17-01 the stronger check anyway. The detached-HEAD trap recurred a
  **twenty-third** time: the container arrived detached at `91f941c` with local `master`
  stranded at `426a97d` and the local `origin/master` ref stale at the same sha, so the
  reattach needed a `git fetch origin` first. Then the form the 13th wait established,
  `git checkout master && git merge --ff-only 91f941c` — a pure fast-forward needing no
  permission override. Keep using it.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the nineteen waits now span ~6.3 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-19 (scheduled cycle, 20th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `a4fa0dd`; all **19**
  commits since `03b4d41` are authored by this agent, **no human commits**, `git status`
  clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 875 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — a search of this log for any approval of §5(a) or of an `entsoe` fix returns
  only this agent's own wait entries and the blocker's own description of the decision; the
  single approval in the log remains Checkpoint C's unseal line of 2026-10-12, which
  predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-19th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module; byte-identical code makes the source-level identity
  argument for FLAG C17-01 the stronger check anyway. The detached-HEAD trap recurred a
  **twenty-fourth** time: the container arrived detached at `a4fa0dd` with local `master`
  stranded at `426a97d` and the local `origin/master` ref stale at the same sha, so the
  reattach needed a `git fetch origin master` first. Then the form the 13th wait
  established, `git checkout master && git merge --ff-only a4fa0dd` — a pure fast-forward
  needing no permission override. Keep using it.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty waits now span ~6.4 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-20 (scheduled cycle, 21st wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: verified nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** HEAD == `master` == `origin/master` == `e563d3f` after
  `git fetch origin master`; all **20** commits since `03b4d41` are authored by this
  agent, **no human commits**, `git status` clean. `git diff --stat 03b4d41 HEAD` is
  **`PROGRESS.md` only, 928 insertions**; the same diff excluding `PROGRESS.md` lists
  **zero files** and `git diff --name-only 03b4d41 HEAD -- tests/` is empty — every line
  of code, config and test is byte-identical to the tree on which the C17 cycle refused
  the synthetic 2025 A65 document. **Nothing under `tests/` was touched.** (First wait in
  24 fires that did *not* arrive on a detached HEAD: the container came up on `master` at
  `e563d3f`, so no reattach was needed. If a later cycle finds it detached again, use the
  13th wait's form: `git fetch origin master && git checkout master && git merge --ff-only
  <sha>`.)
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-20th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module; byte-identical code makes the source-level identity
  argument for FLAG C17-01 the stronger check anyway.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty-one waits now span ~6.7 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-20 (scheduled cycle, 22nd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: checked that nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** After `git fetch origin master`, HEAD == `origin/master` ==
  `04adb0f`; all **21** commits since `03b4d41` are authored by this agent, **no human
  commits**, `git status` clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only,
  978 insertions**; the same diff excluding `PROGRESS.md` lists **zero files** and
  `git diff --name-only 03b4d41 HEAD -- tests/` is empty — every line of code, config and
  test is byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65
  document. **Nothing under `tests/` was touched.** (The container came up detached at
  `04adb0f` with the local `master` ref stale at `e563d3f`, so the 13th wait's reattach was
  used: `git checkout master && git merge --ff-only 04adb0f`, a fast-forward of
  `PROGRESS.md` only.)
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-21st waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module under `python3 -I`; byte-identical code makes the
  source-level identity argument for FLAG C17-01 the stronger check anyway.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty-two waits now span ~7.0 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-20 (scheduled cycle, 23rd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: checked that nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** After `git fetch origin master`, HEAD == `origin/master` ==
  `c5c770a`; all **22** commits since `03b4d41` are authored by this agent, **no human
  commits**, `git status` clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only,
  1 027 insertions**; the same diff excluding `PROGRESS.md` lists **zero files** and
  `git diff --name-only 03b4d41 HEAD -- tests/` is empty — every line of code, config and
  test is byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65
  document. **Nothing under `tests/` was touched.** (The container came up detached at
  `c5c770a` with the local `master` ref stale at `e563d3f`, so the 13th wait's reattach was
  used: `git checkout master && git merge --ff-only c5c770a`, a fast-forward of
  `PROGRESS.md` only.)
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-22nd waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module under `python3 -I`; byte-identical code makes the
  source-level identity argument for FLAG C17-01 the stronger check anyway.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty-three waits now span ~7.3 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-21 (scheduled cycle, 24th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: checked that nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** After `git fetch origin master`, HEAD == `origin/master` ==
  `2268eca`, on `master` (not detached this time, so no reattach was needed);
  all **23** commits since `03b4d41` are authored by this agent, **no human commits**,
  `git status` clean. `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 1 076
  insertions**; the same diff excluding `PROGRESS.md` lists **zero files** and
  `git diff --name-only 03b4d41 HEAD -- tests/` is empty — every line of code, config and
  test is byte-identical to the tree on which the C17 cycle refused the synthetic 2025 A65
  document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-23rd waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module under `python3 -I`; byte-identical code makes the
  source-level identity argument for FLAG C17-01 the stronger check anyway.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty-four waits now span ~7.6 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-21 (scheduled cycle, 25th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: checked that nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** The 24th wait's commit `6d067c4` did reach the remote: after
  `git fetch origin master`, `origin/master` == `6d067c4`. The container started on a
  detached HEAD at that commit with a stale local `master` at `2268eca`, so the local
  branch was fast-forwarded onto `6d067c4` and re-tracked (ref move only — no history
  rewritten, no commit created for it). All **24** commits since `03b4d41` are authored by
  this agent, **no human commits**, `git status` clean. `git diff --stat 03b4d41 HEAD` is
  **`PROGRESS.md` only, 1 123 insertions**; the same diff excluding `PROGRESS.md` lists
  **zero files** and `git diff --name-only 03b4d41 HEAD -- tests/` is empty — every line of
  code, config and test is byte-identical to the tree on which the C17 cycle refused the
  synthetic 2025 A65 document. **Nothing under `tests/` was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-24th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module under `python3 -I`; byte-identical code makes the
  source-level identity argument for FLAG C17-01 the stronger check anyway.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty-five waits now span ~7.9 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-21 (scheduled cycle, 26th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: checked that nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** The 25th wait's commit `9b05fb5` reached the remote: after
  `git fetch origin master`, `origin/master` == `9b05fb5` == this container's HEAD. The
  container again started on a detached HEAD at that commit with a stale local `master`
  at `2268eca`; this cycle left both refs alone and committed on the detached HEAD,
  pushing `HEAD:master` (no history rewritten, no ref moved). All **25** commits since
  `03b4d41` are authored by this agent, **no human commits**, `git status` clean.
  `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 1 172 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-25th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module under `python3 -I`; byte-identical code makes the
  source-level identity argument for FLAG C17-01 the stronger check anyway.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty-six waits now span ~8.2 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-22 (scheduled cycle, 27th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**, so this
  cycle did no new work: checked that nothing has changed and stopped. **No 2025 forecast,
  dispatch schedule, capture ratio, error metric or price statistic was computed, and
  nothing was fetched** — no Energy-Charts or ENTSO-E request was made at all.
- **Nothing has changed.** The 26th wait's commit `f5d79d8` reached the remote: after
  `git fetch origin master`, `origin/master` == `f5d79d8` == this container's HEAD. The
  container again started on a detached HEAD at that commit with a stale local `master`
  at `2268eca`; this cycle left both refs alone and committed on the detached HEAD,
  pushing `HEAD:master` (no history rewritten, no ref moved). All **26** commits since
  `03b4d41` are authored by this agent, **no human commits**, `git status` clean.
  `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only, 1 222 insertions**; the same
  diff excluding `PROGRESS.md` lists **zero files** and `git diff --name-only 03b4d41 HEAD
  -- tests/` is empty — every line of code, config and test is byte-identical to the tree
  on which the C17 cycle refused the synthetic 2025 A65 document. **Nothing under `tests/`
  was touched.**
- **FLAG C17-01 still stands**, verified at source level: `data/entsoe.py` still opens its
  parse guard with `sealed = sealed_years()` at line 741 and raises on any 2025 timestamp
  without consulting `holdout_is_unsealed()` — that name appears **0 times** in the file;
  its only `assert_not_sealed` calls remain the two at lines 860 and 972, not the parse
  hit, while the sibling checks at `data/prices.py:122` and `data/exogenous.py:277` still
  route through `assert_not_sealed` as the fix proposes. The one-call fix in
  `docs/c17_blocker.md` §5(a) is **not applied** and **no human approval of §5(a) is
  recorded** — the only approval in the log remains Checkpoint C's unseal line of
  2026-10-12, which predates the flag.
- Nothing in §5 has been answered. The five artefacts (`docs/c17_blocker.md`,
  `backtest/results/c17_preflight.json`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `docs/checkpoint_c.md`) are all present
  and byte-identical to HEAD. The results store still holds **14 265 rows** with `cycle` of
  exactly C10-C15 (447/1 638/1 341/4 824/315/5 700) and `evaluation_years` of exactly
  2020-2024 (2 106/2 106/2 167/2 897/4 989) — **no 2025 row, no C17 row**, and a
  field-by-field scan for `2025` or a `2025-` date as a whole cell value (excluding the
  numeric `value` column) returns **0 hits**, so the single pre-registered evaluation
  demonstrably has not run. `data/manifest/prices_manifest.csv` still carries its 63 rows
  including the 9 2025 Energy-Charts rows from the C17 cycle's legitimate post-unseal
  price pull.
- Environment, unchanged from the 1st-26th waits: `ENTSOE_API_KEY` **is set** (36 chars);
  `data/raw/` is **absent**, so the post-approval run is still a full fresh download of
  both sources. This container again has no venv and no pandas, so the results-store scan
  used the stdlib `csv` module under `python3 -I`; byte-identical code makes the
  source-level identity argument for FLAG C17-01 the stronger check anyway.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification sent, per the standing instruction not to re-ping the same wait;
  the twenty-seven waits now span ~8.5 days.

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-22 (scheduled cycle, 28th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: checked
  that nothing has changed and stopped. **Nothing fetched, nothing computed** — no 2025
  forecast, dispatch schedule, capture ratio, error metric or price statistic, and no
  Energy-Charts or ENTSO-E request of any kind.
- **Nothing has changed.** `origin/master` == HEAD == `0004372` (the 27th wait's commit)
  after `git fetch origin master`; detached HEAD again, stale local `master` at `2268eca`
  left alone. All **27** commits since `03b4d41` are this agent's, **no human commits**,
  `git status` clean, and `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only** (1 272
  insertions, zero other files, `tests/` empty). **FLAG C17-01 still stands**:
  `data/entsoe.py:741` still opens its parse guard with `sealed = sealed_years()`,
  `holdout_is_unsealed` appears **0 times** in the file, its only `assert_not_sealed`
  calls are still lines 860 and 972, and the siblings at `data/prices.py:122` /
  `data/exogenous.py:277` still route through `assert_not_sealed`. The §5(a) fix is **not
  applied** and **no human approval of §5(a) is recorded**. Results store unchanged at
  **14 265 rows** (C10-C15; `evaluation_years` 2020-2024; **0** whole-cell `2025` hits
  outside the `value` column), `data/manifest/prices_manifest.csv` still 63 rows, all five
  decision artefacts present and byte-identical to HEAD. Environment unchanged:
  `ENTSOE_API_KEY` set (36 chars), `data/raw/` absent, no venv/pandas (scan run with the
  stdlib `csv` module under `python3 -I`).
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) is the only part
  that unblocks C17. No push notification, per the standing instruction not to re-ping the
  same wait; the twenty-eight waits now span ~9.7 days since the C17 cycle (`03b4d41`,
  2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-22 (scheduled cycle, 29th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  that nothing has changed, appended this note, stopped. **Nothing fetched, nothing
  computed** — no 2025 forecast, dispatch schedule, capture ratio, error metric or price
  statistic, and no Energy-Charts or ENTSO-E request of any kind.
- **Nothing has changed.** After `git fetch origin master`, `origin/master` == HEAD ==
  `de1c312` (the 28th wait's commit); detached HEAD again, stale local `master` at
  `2268eca` left alone. All **28** commits since `03b4d41` are this agent's, **no human
  commits**, `git status` clean, and `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md`
  only** (1 301 insertions, zero other files; `tests/` untouched).
- **FLAG C17-01 still stands.** `data/entsoe.py:741` still opens its parse guard with
  `sealed = sealed_years()`, `holdout_is_unsealed` appears **0 times** in the file, its
  only `assert_not_sealed` calls remain lines 860 and 972, and the siblings at
  `data/prices.py:122` / `data/exogenous.py:277` still route through `assert_not_sealed`.
  The §5(a) fix is **not applied** and **no human approval of §5(a) is recorded**.
- Artefacts and store unchanged: results store **14 265 rows**,
  `data/manifest/prices_manifest.csv` still 63 rows, and all five decision artefacts
  (`docs/c17_blocker.md`, `docs/checkpoint_c.md`, `docs/sensitivities.md`,
  `backtest/results/c16_seal_verification.json`,
  `backtest/results/c16_preregistration.json`) present and byte-identical to HEAD.
  Environment unchanged: `ENTSOE_API_KEY` set (36 chars), `data/raw/` absent, so the
  post-approval run is still a full fresh download of both sources.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the
  one-call fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17.
  No push notification, per the standing instruction not to re-ping the same wait; the
  twenty-nine waits now span ~10 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-23 (scheduled cycle, 30th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. Verified unchanged: `origin/master` ==
  HEAD == `f4f5cb9` (the 29th wait's commit) after `git fetch origin master`, detached HEAD
  again with the stale local `master` at `2268eca` left alone, all **29** commits since
  `03b4d41` this agent's with **no human commits**, `git status` clean, and
  `git diff --stat 03b4d41 HEAD` **`PROGRESS.md` only** (1 332 insertions, zero other
  files, `tests/` untouched); **FLAG C17-01 still stands** (`data/entsoe.py:741` still
  opens its parse guard with `sealed = sealed_years()`, `holdout_is_unsealed` appears **0
  times**, `assert_not_sealed` only at lines 860/972, siblings `data/prices.py:122` and
  `data/exogenous.py:277` still routed through it), the §5(a) fix **not applied** with **no
  human approval of §5(a) recorded**, results store **14 265 rows** (C10-C15,
  `evaluation_years` 2020-2024, **0** whole-cell `2025` hits outside `value`),
  `data/manifest/prices_manifest.csv` still 63 rows, all six decision artefacts present and
  byte-identical to HEAD, and the environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent; no venv/pandas, so the store scan used the stdlib `csv` module under
  `python3 -I`). **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a)
  (approve the one-call fix to `data/entsoe.py`) is the only one of the three parts that
  unblocks C17; no push notification, per the standing instruction not to re-ping the same
  wait; the thirty waits now span ~10.4 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-23 (scheduled cycle, 31st wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. Verified unchanged: `origin/master` ==
  HEAD == `de0b699` (the 30th wait's commit) after `git fetch origin master` (which
  fast-forwarded the remote-tracking ref `2268eca..de0b699`, i.e. the 30th wait's own push,
  not a human change), detached HEAD again with the stale local `master` at `2268eca` left
  alone, all **30** commits since `03b4d41` this agent's with **no human commits**,
  `git status` clean, and `git diff --stat 03b4d41 HEAD` **`PROGRESS.md` only** (1 359
  insertions, zero other files, `tests/` untouched); **FLAG C17-01 still stands**
  (`data/entsoe.py:741` still opens its parse guard with `sealed = sealed_years()`,
  `holdout_is_unsealed` appears **0 times** in the file, `assert_not_sealed` appears only
  as the line-109 import and the two unrelated call sites at 860/972, siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it), the §5(a) fix
  **not applied** with **no human approval of §5(a) recorded** anywhere in this log,
  results store **14 265 rows** (`evaluation_years` 2020-2024 only, **0** whole-cell
  `2025` hits outside `value`), `data/manifest/prices_manifest.csv` still 63 rows, all five
  decision artefacts present and byte-identical to HEAD, and the environment unchanged
  (`ENTSOE_API_KEY` set, 36 chars; `data/raw/` absent, so the post-approval run is still a
  full fresh download of both sources; no venv/pandas, so the store scan again used the
  stdlib `csv` module under `python3 -I`). **Still waiting on the human for
  `docs/c17_blocker.md` §5** — §5(a) (approve the one-call fix to `data/entsoe.py`) is the
  only one of the three parts that unblocks C17; no push notification, per the standing
  instruction not to re-ping the same wait; the thirty-one waits now span ~10.7 days since
  the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-23 (scheduled cycle, 32nd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. Verified unchanged: `origin/master` ==
  HEAD == local `master` == `747ff8d` (the 31st wait's commit) after `git fetch origin
  master`, all **31** commits since `03b4d41` this agent's with **no human commits**,
  `git status` clean, and `git diff --stat 03b4d41 HEAD` **`PROGRESS.md` only** (1 390
  insertions, zero other files, `tests/` untouched — 0 paths changed under `tests/`);
  **FLAG C17-01 still stands** (`data/entsoe.py:741` still opens its parse guard with
  `sealed = sealed_years()` and raises `UnexpectedResponse` on any 2025 timestamp,
  `holdout_is_unsealed` appears **0 times** in the file, `assert_not_sealed` appears only
  as the line-109 import and the two unrelated call sites at 860/972, siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it), the §5(a) fix
  **not applied** with **no human approval of §5(a) recorded** anywhere in this log,
  results store **14 265 rows** (`evaluation_years` ∈ {2020, 2021, 2022, 2023, 2024} only,
  **0** whole-cell `2025` hits outside `value`), `data/manifest/prices_manifest.csv` still
  63 rows + header, the five decision artefacts named in the previous wait all present and
  byte-identical to HEAD, and the environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent, so the post-approval run is still a full fresh download of both
  sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`). **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a)
  (approve the one-call fix to `data/entsoe.py`) is the only one of the three parts that
  unblocks C17; no push notification, per the standing instruction not to re-ping the same
  wait; the thirty-two waits now span ~10.9 days since the C17 cycle (`03b4d41`,
  2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-24 (scheduled cycle, 33rd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. Verified unchanged: `origin/master` ==
  HEAD == `e7bfcd7` (the 32nd wait's commit) after `git fetch origin master`, all **32**
  commits since `03b4d41` this agent's (`Claude <noreply@anthropic.com>`) with **no human
  commits**, `git status` clean, and `git diff --stat 03b4d41 HEAD` **`PROGRESS.md` only**
  (1 421 insertions, zero other files, `tests/` untouched — 0 paths changed under
  `tests/`); **FLAG C17-01 still stands** (`data/entsoe.py:741` still opens its parse guard
  with `sealed = sealed_years()` and raises `UnexpectedResponse` on any 2025 timestamp,
  `holdout_is_unsealed` appears **0 times** in the file, `assert_not_sealed` appears only as
  the line-109 import and the two unrelated call sites at 860/972, siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it), the §5(a) fix
  **not applied** with **no human approval of §5(a) recorded** anywhere in this log,
  results store **14 265 rows** (`evaluation_years` ∈ {2020, 2021, 2022, 2023, 2024} only,
  **0** whole-cell `2025` hits outside `value`), `data/manifest/prices_manifest.csv` still
  63 rows + header, the five decision artefacts (`docs/c17_blocker.md`,
  `docs/checkpoint_c.md`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD, and the environment unchanged (`ENTSOE_API_KEY` set,
  36 chars; `data/raw/` absent, so the post-approval run is still a full fresh download of
  both sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`). Housekeeping only: this container came up with a **detached HEAD** at
  `e7bfcd7` and a stale local `master` at `747ff8d`; re-attached with `git checkout master`
  and `git merge --ff-only origin/master`, which changed no file and no history. **Still
  waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call fix to
  `data/entsoe.py`) is the only one of the three parts that unblocks C17; no push
  notification, per the standing instruction not to re-ping the same wait; the thirty-three
  waits now span ~11.2 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-24 (scheduled cycle, 34th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. Verified unchanged: `origin/master` ==
  HEAD == `237bf0a` (the 33rd wait's commit) after `git fetch origin master`, all **33**
  commits since `03b4d41` this agent's (`Claude <noreply@anthropic.com>`) with **no human
  commits**, `git status` clean, and `git diff --stat 03b4d41 HEAD` **`PROGRESS.md` only**
  (1 456 insertions, zero other files, `tests/` untouched — 0 paths changed under
  `tests/`); **FLAG C17-01 still stands** (`data/entsoe.py:741` still opens its parse guard
  with `sealed = sealed_years()` and raises `UnexpectedResponse` on any 2025 timestamp,
  `holdout_is_unsealed` appears **0 times** in the file, `assert_not_sealed` appears only as
  the line-109 import and the two unrelated call sites at 860/972, siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it), the §5(a) fix
  **not applied** with **no human approval of §5(a) recorded** anywhere in this log,
  results store **14 265 rows** (`evaluation_years` ∈ {2020, 2021, 2022, 2023, 2024} only,
  **0** whole-cell `2025` hits outside `value`), `data/manifest/prices_manifest.csv` still
  63 rows + header, the five decision artefacts (`docs/c17_blocker.md`,
  `docs/checkpoint_c.md`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD, and the environment unchanged (`ENTSOE_API_KEY` set,
  36 chars; `data/raw/` absent, so the post-approval run is still a full fresh download of
  both sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`). Housekeeping only, same as the previous wait: this container came up with a
  **detached HEAD** at `237bf0a` and a stale local `master` at `747ff8d`; re-attached with
  `git checkout master` and `git merge --ff-only origin/master` (2 commits fast-forwarded,
  `PROGRESS.md` only), which changed no file and no history. **Still waiting on the human
  for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call fix to `data/entsoe.py`) is
  the only one of the three parts that unblocks C17; no push notification, per the standing
  instruction not to re-ping the same wait; the thirty-four waits now span ~11.6 days since
  the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-24T18:12Z (scheduled cycle, 35th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. No push notification, per the standing
  instruction not to re-ping the same wait.
- Verified unchanged: `origin/master` == HEAD == `df170e7` (the 34th wait's commit) after
  `git fetch origin master`; all **34** commits since `03b4d41` this agent's
  (`Claude <noreply@anthropic.com>`), **no human commits**; `git status` clean;
  `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only** (1 492 insertions, zero other
  files, 0 paths changed under `tests/`). **FLAG C17-01 still stands**: `data/entsoe.py:741`
  still opens its parse guard with `sealed = sealed_years()` and raises `UnexpectedResponse`
  on any 2025 timestamp; `holdout_is_unsealed` appears **0 times** in the file;
  `assert_not_sealed` appears only as the line-109 import and the two unrelated call sites
  at 860/972; siblings `data/prices.py:122` and `data/exogenous.py:277` still routed through
  it. The §5(a) fix is **not applied** and **no human approval of §5(a) is recorded**
  anywhere in this log (0 matches). Results store **14 265 rows**, `evaluation_years` ∈
  {2020, 2021, 2022, 2023, 2024}, **0** whole-cell `2025` outside `value`;
  `data/manifest/prices_manifest.csv` still 63 rows + header; the five decision artefacts
  (`docs/c17_blocker.md`, `docs/checkpoint_c.md`,
  `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD; environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent, so the post-approval run is still a full fresh download of both
  sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`).
- Housekeeping only, same as the previous two waits: the container came up with a **detached
  HEAD** at `df170e7` and a stale local `master` at `747ff8d`; re-attached with
  `git checkout master` and `git merge --ff-only origin/master` (3 commits fast-forwarded,
  `PROGRESS.md` only), which changed no file and no history.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. The
  thirty-five waits now span ~12.0 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-25T02:12Z (scheduled cycle, 36th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. No push notification, per the standing
  instruction not to re-ping the same wait.
- Verified unchanged: `origin/master` == HEAD == `49a4092` (the 35th wait's commit) after
  `git fetch origin master`; all **35** commits since `03b4d41` this agent's
  (`Claude <noreply@anthropic.com>`), **no human commits**; `git status` clean;
  `git diff --stat 03b4d41 HEAD` is **`PROGRESS.md` only** (1 530 insertions, zero other
  files, 0 paths changed under `tests/`). **FLAG C17-01 still stands**: `data/entsoe.py:741`
  still opens its parse guard with `sealed = sealed_years()`; `holdout_is_unsealed` appears
  **0 times** in the file; `assert_not_sealed` appears only as the line-109 import and the
  two unrelated call sites at 860/972; siblings `data/prices.py:122` and
  `data/exogenous.py:277` still routed through it. The §5(a) fix is **not applied** and
  **no human approval of §5(a) is recorded** anywhere in this log (34 matches on the
  approval pattern, all of them this agent's own "no approval is recorded" sentences; 0
  affirmative). Results store **14 265 rows**, `evaluation_years` ∈ {2020, 2021, 2022,
  2023, 2024}, **0** whole-cell `2025` outside `value`; `data/manifest/prices_manifest.csv`
  still 63 rows + header; the five decision artefacts (`docs/c17_blocker.md`,
  `docs/checkpoint_c.md`, `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD; environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent, so the post-approval run is still a full fresh download of both
  sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`).
- Housekeeping only, same as the previous three waits: the container came up with a
  **detached HEAD** at `49a4092` and a stale local `master` at `747ff8d`; re-attached with
  `git checkout master` and `git merge --ff-only origin/master` (4 commits fast-forwarded,
  `PROGRESS.md` only), which changed no file and no history.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. The
  thirty-six waits now span ~12.3 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-25T10:12Z (scheduled cycle, 37th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. No push notification, per the standing
  instruction not to re-ping the same wait.
- Verified unchanged: `origin/master` == HEAD == `479956f` (the 36th wait's commit) after
  `git fetch origin master`; all **36** commits since `03b4d41` this agent's
  (`Claude <noreply@anthropic.com>`), **no human commits**; `git status` clean;
  `git diff --stat 03b4d41 origin/master` is **`PROGRESS.md` only** (1 568 insertions, zero
  other files, 0 paths changed under `tests/`). **FLAG C17-01 still stands**:
  `data/entsoe.py:741` still opens its parse guard with `sealed = sealed_years()`;
  `holdout_is_unsealed` appears **0 times** in the file; `assert_not_sealed` appears only as
  the line-109 import and the two unrelated call sites at 860/972; siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it. The §5(a) fix is
  **not applied** and **no human approval of §5(a) is recorded** anywhere in this log — a
  search for any affirmative approval of §5(a) or of an `entsoe` fix returns only this
  agent's own "no approval is recorded" sentences, 0 affirmative. Results store
  **14 265 rows**, `evaluation_years` ∈ {2020, 2021, 2022, 2023, 2024}, **0** whole-cell
  `2025` outside `value`; `data/manifest/prices_manifest.csv` still 63 rows + header; the
  five decision artefacts (`docs/c17_blocker.md`, `docs/checkpoint_c.md`,
  `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD; environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent, so the post-approval run is still a full fresh download of both
  sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`).
- Housekeeping only, same as the previous four waits: the container came up with a
  **detached HEAD** at `479956f` and a stale local `master` at `747ff8d`; re-attached with
  `git checkout master` and `git merge --ff-only origin/master` (5 commits fast-forwarded,
  `PROGRESS.md` only), which changed no file and no history.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. The
  thirty-seven waits now span ~12.6 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-25T18:20Z (scheduled cycle, 38th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. No push notification, per the standing
  instruction not to re-ping the same wait.
- Verified unchanged: `origin/master` == HEAD == `31e7e05` (the 37th wait's commit) after
  `git fetch origin master`; all **37** commits since `03b4d41` this agent's
  (`Claude <noreply@anthropic.com>`), **no human commits**; `git status` clean;
  `git diff --stat 03b4d41 origin/master` is **`PROGRESS.md` only** (1 607 insertions, zero
  other files, **0** paths changed under `tests/`). **FLAG C17-01 still stands**:
  `data/entsoe.py:741` still opens its parse guard with `sealed = sealed_years()`;
  `holdout_is_unsealed` appears **0 times** in the file; `assert_not_sealed` appears only as
  the line-109 import and the two unrelated call sites at 860/972; siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it. The §5(a) fix is
  **not applied** and **no human approval of §5(a) is recorded** anywhere in this log — a
  search for any affirmative approval of §5(a) or of an `entsoe` fix returns only this
  agent's own "no approval is recorded" sentences, 0 affirmative.
- Results store **14 265 rows**, `evaluation_years` ∈ {2020, 2021, 2022, 2023, 2024} (no
  value contains `2025`), **0** whole-cell `2025` outside `value`;
  `data/manifest/prices_manifest.csv` still 63 rows + header, of which the nine `year=2025`
  rows are the post-Checkpoint-C price pull already recorded under FLAG C17-02 and not a new
  change; the five decision artefacts (`docs/c17_blocker.md`, `docs/checkpoint_c.md`,
  `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD; environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent, so the post-approval run is still a full fresh download of both
  sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`).
- Housekeeping only, same as the previous five waits: the container came up with a
  **detached HEAD** at `31e7e05` and a stale local `master` at `747ff8d`; re-attached with
  `git checkout master` and `git merge --ff-only origin/master` (6 commits fast-forwarded,
  `PROGRESS.md` only), which changed no file and no history.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. The
  thirty-eight waits now span ~12.9 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-26T02:12Z (scheduled cycle, 39th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. No push notification, per the standing
  instruction not to re-ping the same wait.
- Verified unchanged: `origin/master` == HEAD == `3d1435a` (the 38th wait's commit) after
  `git fetch origin master`; all **38** commits since `03b4d41` this agent's
  (`Claude <noreply@anthropic.com>`), **no human commits**; `git status` clean;
  `git diff --stat 03b4d41 origin/master` is **`PROGRESS.md` only** (1 648 insertions, zero
  other files, **0** paths changed under `tests/`). **FLAG C17-01 still stands**:
  `data/entsoe.py:741` still opens its parse guard with `sealed = sealed_years()`;
  `holdout_is_unsealed` appears **0 times** in the file; `assert_not_sealed` appears only as
  the line-109 import and the two unrelated call sites at 860/972; siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it. The §5(a) fix is
  **not applied** and **no human approval of §5(a) is recorded** anywhere in this log — a
  search for any affirmative approval of §5(a) or of an `entsoe` fix returns only this
  agent's own "no approval is recorded" sentences, 0 affirmative.
- Results store **14 265 rows**, `evaluation_years` ∈ {2020, 2021, 2022, 2023, 2024},
  **0** whole-cell `2025` outside `value`; `data/manifest/prices_manifest.csv` still 63 rows
  + header, of which the nine `year=2025` rows are the post-Checkpoint-C price pull already
  recorded under FLAG C17-02 and not a new change; the five decision artefacts
  (`docs/c17_blocker.md`, `docs/checkpoint_c.md`,
  `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD; environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent, so the post-approval run is still a full fresh download of both
  sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`).
- Housekeeping only, same as the previous six waits: the container came up with a
  **detached HEAD** at `3d1435a` and a stale local `master` at `747ff8d`; re-attached with
  `git checkout master` and `git merge --ff-only origin/master` (7 commits fast-forwarded,
  `PROGRESS.md` only), which changed no file and no history.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. The
  thirty-nine waits now span ~13.3 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**

---

### C17-blocked wait — 2026-10-26T10:13Z (scheduled cycle, 40th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — C17 BLOCKED**: verified
  nothing has changed, appended this note, stopped. **Nothing fetched, nothing computed** —
  no 2025 forecast, dispatch schedule, capture ratio, error metric or price statistic, and
  no Energy-Charts or ENTSO-E request of any kind. No push notification, per the standing
  instruction not to re-ping the same wait.
- Verified unchanged: `origin/master` == HEAD == `e19f918` (the 39th wait's commit) after
  `git fetch origin master`; all **39** commits since `03b4d41` this agent's
  (`Claude <noreply@anthropic.com>`), **no human commits**; `git status` clean;
  `git diff --stat 03b4d41 origin/master` is **`PROGRESS.md` only** (1 689 insertions, zero
  other files, **0** paths changed under `tests/`). **FLAG C17-01 still stands**:
  `data/entsoe.py:741` still opens its parse guard with `sealed = sealed_years()`;
  `holdout_is_unsealed` appears **0 times** in the file; `assert_not_sealed` appears only as
  the line-109 import and the two unrelated call sites at 860/972; siblings
  `data/prices.py:122` and `data/exogenous.py:277` still routed through it. The §5(a) fix is
  **not applied** and **no human approval of §5(a) is recorded** anywhere in this log — a
  search for any affirmative approval of §5(a) or of an `entsoe` fix returns only this
  agent's own "no approval is recorded" sentences, 0 affirmative.
- Results store **14 265 rows**, `evaluation_years` ∈ {2020, 2021, 2022, 2023, 2024},
  **0** whole-cell `2025` outside `value`; `data/manifest/prices_manifest.csv` still 63 rows
  + header, of which the nine `year=2025` rows are the post-Checkpoint-C price pull already
  recorded under FLAG C17-02 and not a new change; the five decision artefacts
  (`docs/c17_blocker.md`, `docs/checkpoint_c.md`,
  `backtest/results/c16_preregistration.json`,
  `backtest/results/c16_seal_verification.json`, `backtest/run_c16_checkpoint.py`) all
  present and byte-identical to HEAD; environment unchanged (`ENTSOE_API_KEY` set, 36 chars;
  `data/raw/` absent, so the post-approval run is still a full fresh download of both
  sources; no venv/pandas, so the store scan again used the stdlib `csv` module under
  `python3 -I`).
- Housekeeping only, same as the previous seven waits: the container came up with a
  **detached HEAD** at `e19f918` and a stale local `master` at `747ff8d`; re-attached with
  `git checkout master` and `git merge --ff-only origin/master` (8 commits fast-forwarded,
  `PROGRESS.md` only), which changed no file and no history.
- **Still waiting on the human for `docs/c17_blocker.md` §5** — §5(a) (approve the one-call
  fix to `data/entsoe.py`) is the only one of the three parts that unblocks C17. The
  forty waits now span ~13.6 days since the C17 cycle (`03b4d41`, 2026-10-12).

**The 2025 holdout is UNSEALED and has not yet been evaluated.**
