# Independent pre-build audit

**Auditor:** Claude (Opus), dispatched as an independent subagent with no
involvement in designing the original plan — instructed to act as a skeptical
outside quant/energy-storage reviewer and stress-test the plan before any code
was written.
**Date:** 2026-09-28
**Verdict:** GO, conditional on four changes (all incorporated into `PLAN.md`).

This is the verbatim report. `PLAN.md` is the curated, actionable version —
read that first for what to actually do. This file is the reasoning trail.

---

## Bottom line up front

The analytical design is better than most portfolio projects and the
three-curve (oracle / model / naive) framing is genuinely sound. But the plan
has one hard blocker that breaks a start tonight (ENTSO-E token lead time),
two data sources that are wrong for the job they've been given (Open-Meteo,
AGSI+), one likely-fatal silent bug in the LP (forecast run valued on forecast
prices), and one execution-model pathology nobody had designed against (21
unattended cycles hill-climbing on test metrics and eventually editing the
tests). All fixable. Verdict: GO, conditional on four changes.

## 1. Data access reality check

### ENTSO-E — NOT same-day.
Access is manually granted: register an account, then email
`transparency@entsoe.eu` with subject "Restful API access"; only after the
helpdesk grants it does a token-generation button appear. Official target 3
working days; real-world range 1-7+ days.

Sequencing fix: (1) human sends the request immediately — this is a human
step (external credential, email account) and must not be left to an agent
cycle; (2) make the first several cycles token-free using the **Fraunhofer
ISE Energy-Charts API** (`api.energy-charts.info`) — no registration, no key,
CC BY 4.0, day-ahead prices at 15-min resolution across European bidding
zones, plus generation by source and cross-border flows. ENTSO-E becomes an
enhancement for exogenous features on a few zones, not a dependency for the
project existing.

Additional live risk: the Transparency Platform was migrated in September
2026 and briefly 404'd against `web-api.tp.entsoe.eu/api` (entsoe-py issue
#548, since closed as a server bug). Pin the client library version; every
cycle should smoke-test one call before running any pipeline code; a 404 is a
FLAG, not a puzzle — an unattended agent must not start guessing endpoints.

### AGSI+ (GIE) — instant access, wrong dataset.
Free self-service key at `agsi.gie.eu/account`, no blocker. But gas storage
fullness is not a gas price — it's a slow-moving stock variable, and the
storage-to-price relationship flips sign across the sample (2022: low
storage, high price; 2023-24: high storage, low price). Dropped as a feature.
Replaced with a stated limitation in the write-up (what you'd use instead:
TTF day-ahead/front-month via a paid feed) — worth more to a trading-desk
reader than the feature would have been.

### Open-Meteo — a real leakage trap.
"Historical Weather API" is ERA5 reanalysis (actuals), not forecasts. The
"Previous Runs" API (fixed-lead-time forecast vintages) only goes back to
~2024 for most models. Feeding reanalysis in as if it were a D-1 forecast is
a trained-in leak that inflates exactly the "% of flexibility value captured"
number the project's headline rests on. Dropped entirely from the main model.
ENTSO-E's own D-1 wind/solar forecasts replace it (they encode weather the
way the market actually saw it). ERA5 may only appear as an explicitly
labelled "perfect weather foresight" sensitivity run, never in the main spec.

## 2. Leakage risks specific to this design

- **RES forecast publication timing (Reg. (EU) 543/2013 Art. 14(1))**: D-1
  wind/solar forecasts are published no later than 17:00 CET D-1 — five hours
  *after* SDAC gate closure (12:00 CET) — and revised intraday. ENTSO-E TP
  serves the current version, not the 12:00-D-1 vintage; there is no free
  vintage archive. This is used anyway in the EPF literature, but the
  write-up must name and quantify it: run the model twice, once with the
  forecast as-is and once with it deliberately degraded (empirical D-1 error
  distribution, or a persistence-only version), and report the delta. A small
  delta defends the headline; a large delta is the project's most honest
  "surprising finding."
- **Load forecast is clean** (Art. 6(1): published >=2h before gate closure,
  ~10:00 CET) — safe to use as-is. Never mix in actual/revised load (A16).
- **Rolling-retrain leaks**: scalers/imputers/transforms must be fit *inside*
  the training fold only (asinh/variance-stabilising transform for negative
  prices, winsorisation thresholds, LEAR's LassoLarsIC/CV selection). Weekly
  retrain windows must not reach across the train/test boundary. Global
  ffill/bfill before splitting is a one-line invisible leak (bfill pulls the
  future backwards) — impute inside the fold only.
- **Hyperparameter/test leakage across 21 unattended cycles** is the
  execution model's own emergent risk: an agent that can see test metrics and
  "improve" the model over repeated cycles is hill-climbing on the test set,
  and no single commit looks wrong. Mitigation: 2024 is validation (visible),
  **2025 is a sealed holdout**, evaluated exactly once, late in the plan,
  behind a standing rule that no cycle may unseal it without a flagged human
  checkpoint.
- **DST**: 23h/25h local days break a naive 24xN reshape. The dangerous
  failure mode isn't a crash, it's an agent "fixing" the crash by dropping or
  forward-filling a row, silently shifting hour-of-day alignment for the rest
  of the series. Rule: everything internally in UTC, local hour-of-day only
  as an explicit feature, with an assertion on expected per-day row count and
  an explicit DST whitelist.
- **Silent empty API responses**: ENTSO-E can return HTTP 200 with a
  no-data/Acknowledgement document. A `try/except` that swallows this
  produces a NaN column that gets imputed and trained on. Non-negotiable: a
  data contract per (zone, series, year) with expected row counts, a hard
  fail (non-zero exit + FLAG in PROGRESS.md) beyond a small tolerance, and a
  committed manifest (row counts, min/max/mean, negative-hour count, hash) so
  any later cycle silently changing the data layer shows up as a git diff.
- **Cache discipline**: never re-pull already-cached (zone, series, range)
  data — ENTSO-E rate-limits/throttles abusive tokens.
- **Repo hygiene**: don't commit bulk raw data to a public repo; attribute
  Energy-Charts (CC BY 4.0) and ENTSO-E reuse; `.gitignore` from commit 1;
  `gitleaks` scan as a hard pre-publish gate.
- **Structural breaks in the 2019-2025 panel**: PL joined SDAC/MRC only in
  June 2021; Italy reconfigured bidding zones 1 Jan 2021; NO2 gained
  NordLink/North Sea Link in 2021 (changing its price level and correlation
  to DE/GB); NO2 and DK1 are hydro/reservoir-driven with no reservoir feature
  in scope — expect and state weaker performance there rather than discover
  it live in an interview.
- **15-minute cutover (30 Sep 2025 trading day, 1 Oct 2025 delivery)**:
  aggregating four quarter-hour prices to hourly is only well-defined as a
  volume-weighted average (state this), and hourly aggregation destroys
  exactly the intra-hour spread a 2-hour battery monetises — so post-cutover
  battery numbers are a lower bound and not comparable to the pre-cutover
  period. Main hourly backtest ends 2025-09-30; native 15-min analysis is a
  labelled stretch goal, not core scope.

## 3. Battery LP realism

The oracle/model/naive-through-one-LP framing is standard and defensible, but
several implementation details determine whether the numbers mean anything.

- **Critical bug to design against — "commit-then-settle": the forecast run
  must optimise on the forecast price vector, freeze that schedule, then
  value it at realised prices.** Reporting the LP's own objective value from
  the forecast run instead can make the forecast schedule appear to beat
  perfect foresight — the LP solves cleanly and the number looks great, so an
  unattended agent will not catch it on its own. Encode as assertions, every
  cycle they apply: `value(forecast schedule @ realised) <= value(oracle
  schedule @ realised)` must hold every day; `value(naive @ realised) <=
  value(forecast @ realised)` on average, not per day (per-day violations are
  real and interesting, not bugs).
- **Daily horizon with SoC reset to zero at midnight destroys value** and
  truncates the overnight-charge/morning-discharge cycle that dominates in
  winter. Use a rolling horizon: optimise D+1 over 24h, carry realised
  end-of-day SoC into the next day's initial condition, impose a terminal SoC
  condition or value, or the LP always empties the battery at 23:00
  regardless of price.
- **Missing physics/economics, ranked by how much they change the answer:**
  1. Cycling/degradation cost omitted biases the headline in the project's
     own favour — without a throughput cost the LP chases arbitrarily small
     spreads, which likely *overstates* the value lost to forecast error.
     Add ~2-5 EUR/MWh discharged, or a cap of ~1.5 cycles/day.
  2. No intraday market: real BESS correct DA positions in continuous
     intraday up to 15-30 min before delivery, so a DA-only study likely
     *overstates* the cost of DA forecast error. State this even without
     modelling it.
  3. No ancillary services (FCR/aFRR has historically been the majority of
     European BESS revenue; DA arbitrage is not the asset's actual business
     case) — one sentence in the write-up.
  4. Charging-side grid fees/levies differ enormously by zone (Germany
     exempts storage from grid fees under time-limited EnWG SS118(6); other
     zones don't) and directly threaten the cross-zone ranking. Either add a
     crude sourced per-zone charging-cost constant, or state loudly that the
     metric is "gross spot arbitrage margin," not asset revenue.
  5. Apply round-trip efficiency symmetrically (sqrt(0.88) per leg), not
     one-sided; state whether MW is at the grid connection and whether MWh is
     usable or nameplate capacity.
  6. Price-taker assumption is fine at 1MW — say so, and note portfolio-scale
     arbitrage erodes via self-cannibalisation.
  7. **LP-vs-MILP bug**: with symmetric losses and no binary
     charge/discharge constraint, the LP can simultaneously charge and
     discharge to burn energy during negative prices. Given the number of
     negative-price hours in DE/NL/ES 2024-25, this will happen. Add an
     explicit check for simultaneous charge/discharge; if it appears, either
     add a binary (MILP) or a penalty term — the LP solves cleanly either
     way, so this needs an active check, not just trust in the solver.
- **Metrics fixes**: drop sMAPE (near-useless with prices crossing zero and
  hundreds of negative/near-zero hours per zone 2024-25); use MAE, RMSE, and
  rMAE relative to naive (the `epftoolbox` convention). Add decision-relevant
  metrics: error in the daily max-min spread, and within-day Spearman rank
  correlation of hourly price ordering — what the battery actually trades.
  Likely finding: capture ratio tracks rank correlation better than RMSE,
  i.e. the best-RMSE model isn't the best-money model — a stronger interview
  story than a zone table alone. CIs via block bootstrap over whole days (or
  months), not iid hours; report per-year as well as pooled, and the
  distribution of daily capture ratio (left-skewed, occasional very bad
  days), not just the mean.

## 4. Feasibility under ~21 unattended 8-hourly cycles

Compute is not the binding constraint (LEAR ~25k small fits total; GBM ~1,040
fits; the LP is ~200k tiny problems — all minutes to a few hours via
HiGHS/LEAR/LightGBM defaults on a laptop-class cloud instance). The binding
constraints are the ENTSO-E token, per-zone data idiosyncrasies, agent rework
when an early schema decision turns out wrong, and the write-up (the actual
deliverable, which always gets squeezed).

**Scope cut, highest-leverage change: 10-deep -> 3-deep + 6-light.**
- Tier A (deep): **DE-LU, ES, NO2** — thermal/RES-mixed, solar-dominated,
  hydro-dominated: three genuinely different price-formation regimes, a
  better story than ten zones of the same thing. Full exogenous features, all
  3 models, full LP, CIs, all sensitivities.
- Tier B (light): **FR, NL, BE, IT-North, DK1, PL** — price-history-only
  features (lags + calendar), naive + LEAR only, same LP. Needs exactly one
  series per zone (day-ahead price), free via Energy-Charts — nearly zero
  data risk. Still produces the 9-row comparison table.

**Drop outright**: Open-Meteo, AGSI, exogenous features before 2022 (no
archived vintages exist), the native-15-min study (stretch only), and GBM
hyperparameter search (one fixed LightGBM config with in-fold early stopping
— tuning across cycles is precisely where test leakage creeps in, and "I
fixed the config deliberately to avoid test-set hill-climbing" is a stronger
line than a tuned model).

**Hard checkpoints — a cycle must stop and flag, not proceed:**
1. Before any cycle depends on the ENTSO-E token.
2. After the data manifest is first built — a human eyeballs row counts and
   plotted price series before any model is fit. A data layer poisoned at
   cycle 2 and discovered at cycle 18 is the single most expensive failure
   mode in this execution model.
3. Before the sealed 2025 holdout is evaluated.
4. Before the repo is made public (secret scan, licence/attribution, raw-data
   size, README claims vs actual results).
5. Any cycle that would modify `tests/`, a leakage assertion, a data
   contract, or a frozen config — without this rule the agent will eventually
   make a red test green by editing the test, the most dangerous single
   behaviour in an unattended loop.
6. Before the "surprising finding" is finalised — "surprising" and "bug" are
   the same observation until a human checks.

## 5. Does it prove what it needs to prove?

Honest answer: it over-delivers on ML/engineering and under-delivers on
physical energy trading. Gunvor's grad programme is oil/gas/power/shipping
(Clearlake)/renewables (Nyera) — physical, logistics-and-credit flavoured. A
power-price ML backtest reads as quant/analyst, not trader. Still a strong
differentiator against the median applicant, and the storage angle maps to
Nyera, but on its own doesn't read as commercial instinct.

The project does not help pass the 40-minute Math/Logic/Python test — that's
numerical reasoning under time pressure (mental arithmetic, ratios,
probability/EV, logic puzzles, timed pandas/numpy drills), which has a
strictly higher expected return on reaching the next round than the last few
build cycles would. If the schedule is squeezed, squeeze the project, not
test prep.

**Highest-value cheap additions, ranked:**
1. One page: "What a desk would additionally need" — position limits and
   stop-loss, mark-to-market/VaR on an open spread position, curve
   construction (monthly/quarterly forward -> hourly shape, and why the
   shaping assumption *is* the trade), imbalance exposure/BRP responsibility,
   exchange margin and counterparty/credit lines, REMIT unplanned-outage
   messages as a live fundamentals feed, and what data you'd buy (Montel/
   EEX/LSEG). Largest credibility gain per unit effort in the entire plan.
2. A fundamentals chapter: price vs residual load (load - wind - solar) per
   Tier-A zone, showing the convex thermal merit-order stack, the
   negative-price floor, the 2022 level shift — demonstrates thinking in
   merit order, not just features.
3. Frame the conclusion as a decision, not a metric: in which zones does
   forecast skill pay for itself, set against a plausible annual cost of a
   forecasting capability — P&L against cost and risk, not RMSE.
4. A one-page executive summary at the front, with the table and three
   bullets.

**On the agent-built commit history**: a public repo with dozens of
machine-paced commits at exact 8-hour intervals is itself a visible signal.
Best option: own it in the README (what was specified, the leakage tests
required, the checkpoints reviewed, the bugs caught) — in 2026 this is a
differentiator and converts a potential weakness into evidence of engineering
judgment. Acceptable: squash history. Do not present it as hand-built.

## 6. Revised plan

See `PLAN.md` for the curated cycle-by-cycle plan (C0-C21) this audit
produced.

## 7. Go / no-go

GO, conditional on: (1) the human sending the ENTSO-E access request and
setting up the repo/standing rules immediately, not left to an agent cycle;
(2) Energy-Charts as the key-free critical path so early cycles don't depend
on the token; (3) dropping Open-Meteo-as-forecast and AGSI-as-gas-price; (4)
scoping to 3 deep + 6 light zones with five checkpoints as genuine hard
stops, including a standing rule that no cycle may edit tests or contracts
unattended.

The largest residual risk is not the analytics, it's the unattended dynamic:
repeated cycles with visibility into test metrics, plus the freedom to edit
assertions, will produce a repo that looks rigorous and is quietly overfit if
not actively guarded against. Seal the holdout, freeze the tests, require a
human flag to touch either.

**Sources cited by the audit:** ENTSO-E Transparency Platform token help
article; amsleser.no ENTSO-E API token walkthrough; entsoe-py GitHub issue
#548 (Sept 2026 404s after TP migration); Open-Meteo Historical Forecast API,
Previous Runs API, and GitHub issue #694 on archive start dates; GIE
AGSI+/ALSI API user manual and login page; EPEX SPOT announcement of the
15-minute MTU go-live (trading day 30 Sept 2025, delivery 1 Oct 2025);
Commission Regulation (EU) 543/2013 Art. 6(1) and Art. 14(1); the
Energy-Charts API (Fraunhofer ISE).
