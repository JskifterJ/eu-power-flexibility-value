# Plan

**Read this file and `PROGRESS.md` first, every cycle, before doing anything
else.** This is the curated, actionable plan. `docs/audit.md` is the full
reasoning trail behind it — read it if you need the "why," not the "what."

## Goal

Forecast European day-ahead power prices across a tiered set of bidding
zones, dispatch a representative battery against those forecasts via a
rolling-horizon LP, and measure how much of the theoretical (perfect
foresight) flexibility value is actually capturable once realistic forecast
error is accounted for — compared across zones with genuinely different
price-formation regimes. Deliverable: a public GitHub repo (once approved)
plus a 4-6 page write-up, built as a portfolio piece for commodity-trading
graduate-programme applications (Gunvor and similar).

## Scope decisions (post-audit — do not deviate without flagging)

- **Zones, tiered:**
  - **Tier A (deep — full exogenous features, 3 models, full LP, CIs,
    sensitivities): DE-LU, ES, NO2.** Thermal/RES-mixed, solar-dominated,
    hydro-dominated — three different price-formation regimes.
  - **Tier B (light — price-history features only, naive + LEAR, same LP):
    FR, NL, BE, IT-North, DK1, PL.**
- **Data sources:**
  - **Energy-Charts API** (`api.energy-charts.info`, Fraunhofer ISE, no key,
    CC BY 4.0) — primary source for day-ahead prices, all zones. This is the
    key-free critical path; nothing in cycles C1-C6 depends on ENTSO-E.
  - **ENTSO-E Transparency Platform** — Tier-A only, once the API key is
    configured for the cloud environment (see note below): D-1 load forecast
    (Art. 6, safe — published >=2h pre-gate-closure) and D-1 wind/solar
    forecast (Art. 14 — flagged: published *after* gate closure, revised
    intraday; see the degradation-sensitivity requirement in C8).
  - **Open-Meteo: NOT used as a forecast input.** Its "historical weather" is
    reanalysis (actuals), which would be a trained-in leakage bug. May only
    appear as an explicitly labelled "perfect weather foresight" sensitivity
    run, never in the main model.
  - **AGSI+ gas storage: NOT used as a gas-price proxy.** Weak, sign-unstable
    relationship to price. Replaced by a stated limitation in the write-up.
- **Training/test split:** train 2019-2023 (exogenous features only from
  2022 onward — no archived forecast vintages exist earlier), validate on
  2024 (visible, may be used to iterate), **2025 is a SEALED HOLDOUT — do not
  load, read, or evaluate against it until Checkpoint C is explicitly
  approved (Cycle 16), and evaluate it exactly once.**
- **Time handling:** everything internally in UTC. Local hour-of-day is an
  explicit feature, never used for resampling. Assert expected row count per
  (zone, day) with a DST whitelist.
- **15-minute cutover:** main hourly backtest ends 2025-09-30 (day before the
  SDAC 15-min go-live). Post-cutover native 15-min analysis is a labelled
  stretch goal (C15+), never blended into the main results.
- **Models:** naive (same hour last week) as floor; LEAR (regularised linear,
  per-hour LASSO, in-fold scaling/selection); gradient boosting — **one fixed
  LightGBM config with in-fold early stopping, no hyperparameter search
  across cycles** (tuning against repeatedly-visible metrics is a leakage
  vector in this execution model).
- **Metrics:** MAE, RMSE, rMAE vs naive (drop sMAPE — useless with
  negative/near-zero prices). Decision-relevant: error in daily max-min
  spread, within-day Spearman rank correlation of hourly price ordering.
  Battery: % of perfect-foresight value captured, EUR/MW/yr lost to forecast
  error, block-bootstrap CIs over daily blocks, reported per-year and pooled,
  full distribution not just the mean.

## Battery LP — non-negotiable invariants

- **Commit-then-settle**: the forecast run optimises on the forecast price
  vector, freezes that schedule, then values it at *realised* prices. Never
  report the LP's own objective value from the forecast run.
- Assert every cycle these apply: `value(forecast @ realised) <=
  value(oracle @ realised)` every day; `value(naive @ realised) <=
  value(forecast @ realised)` on average (not per-day).
- Rolling horizon (24h, D+1), realised end-of-day SoC carried into the next
  day, terminal SoC condition/value — never reset SoC to zero at midnight.
- Symmetric round-trip efficiency (sqrt(0.88) per leg), throughput/cycling
  cost (~2-5 EUR/MWh discharged), explicit check for simultaneous
  charge/discharge under negative prices (flag if found — LP artefact, needs
  a penalty term or MILP).
- State plainly in the write-up: no intraday re-optimisation, no ancillary
  services, no per-zone grid-fee/levy differences (unless a sourced constant
  is added), price-taker assumption. These are limitations, not omissions to
  hide.

## Standing rules

See `CLAUDE.md` — every cycle reads it automatically. Summary: never edit
`tests/` or a data contract without flagging first; a 404/empty API response
is a flag, not a puzzle to solve around; never re-download cached data; never
touch the 2025 holdout before Checkpoint C; never make the repo public; log
every cycle's work to `PROGRESS.md`; stop fully at a checkpoint (don't
continue into the next cycle's work even if budget remains) and send a push
notification.

## ENTSO-E API key note

The user already has an ENTSO-E API key. It is **not yet available to cloud
routine cycles** (cloud sessions can't read local files/env vars) — it needs
to be configured as an environment variable on the cloud environment via
claude.ai/code before Cycle 7. If a cycle reaches C7 and `ENTSOE_API_KEY` is
not set, **flag it in PROGRESS.md and continue with Tier-B-only /
Energy-Charts-only work instead of blocking.**

## Cycle-by-cycle plan (~21 cycles, one per ~8h fire)

- **C0** — (done, human+local-assistant) repo skeleton, PLAN.md, CLAUDE.md,
  docs/audit.md, .gitignore, private GitHub repo created.
- **C1** — Config schema (zones, ranges, feature spec as YAML). Energy-Charts
  client + local cache. Pull day-ahead prices, all 9 zones, 2019-today. Build
  the manifest (rows per zone-year, min/max/mean, negative-hour count, hash).
  No modelling yet.
- **C2** — Data contract tests (expected row count per day incl. DST
  whitelist; resolution-change detection at 2025-10-01; gap report). Hourly
  aggregation, volume-weighted where relevant, method documented. Plot every
  zone's price series. **-> CHECKPOINT A: stop, push-notify, wait for human
  review of manifest + plots before any modelling.**
- **C3** — Walk-forward harness + naive model, DE-LU only. Leakage tests
  written *before* the real model, as executable assertions: (i) shifting
  the feature matrix forward one day must degrade metrics; (ii) a
  deliberately inserted future-timestamped feature must be caught by a guard
  comparing every feature's max timestamp to gate closure; (iii) target
  permutation must destroy skill.
- **C4** — LEAR (per-hour LASSO, in-fold scaling/asinh transform, in-fold
  IC/CV selection), DE-LU, walk-forward on 2024 (validation) only.
- **C5** — Battery LP v1, DE-LU, oracle curve only. Rolling horizon, SoC
  carryover + terminal condition, symmetric efficiency, throughput cost,
  simultaneous charge/discharge check. Unit tests: hand-computed toy price
  vector, value monotone in spread, value = 0 on a flat curve.
- **C6** — Commit-then-settle machinery, all three curves (oracle/model/
  naive), DE-LU. Assert oracle >= model >= naive on pooled value. **->
  CHECKPOINT B: stop, push-notify, wait for human to eyeball one zone
  end-to-end (a week of dispatch against the price plot) before scaling out.**
- **C7** — If `ENTSOE_API_KEY` is configured: ENTSO-E client, D-1 load
  forecast (safe) + D-1 wind/solar forecast (flagged) for Tier-A zones;
  extend manifest/contracts. If not configured: flag and continue with
  Tier-B work instead of blocking.
- **C8** — Exogenous features into LEAR for Tier A. Build the RES-forecast
  degradation sensitivity (model with as-published forecast vs a
  deliberately degraded/persistence version) as a first-class experiment.
- **C9** — GBM, one fixed LightGBM config, in-fold early stopping, Tier A
  only. No hyperparameter search.
- **C10** — Scale the harness: Tier A (3 models, exogenous features) + Tier B
  (naive + LEAR, price-only). Results written append-only, each row tagged
  with git SHA + config hash.
- **C11** — LP across all 9 zones x all curves; persist per-day capture
  ratios.
- **C12** — Metrics layer: MAE, RMSE, rMAE vs naive, daily-spread error,
  within-day Spearman; capture ratio; EUR/MW/yr; block-bootstrap CIs over
  daily blocks.
- **C13** — Regime analysis: 2022 crisis year reported separately; per-year
  tables; pre/post 2025-10-01 flagged; negative-hour counts per zone.
- **C14** — Fundamentals chapter: price vs residual load (load - wind -
  solar) per Tier-A zone, merit-order commentary.
- **C15** — Sensitivities: throughput cost 0/2/5 EUR/MWh; daily-reset vs
  rolling-horizon SoC; RES-forecast degradation; 2h vs 4h duration. This is
  where the honest findings live — look here first for the "surprising
  finding."
- **C16** — **-> CHECKPOINT C: stop, push-notify, wait for explicit human
  approval to unseal the 2025 holdout.** Only after approval: run a single
  evaluation of the 2025 holdout; record in PROGRESS.md that it ran exactly
  once, with the timestamp.
- **C17** — Final `results.csv`, rewrite README as the real findings summary
  (Energy-Charts CC BY 4.0 + ENTSO-E attribution; agent-built disclosure
  retained/updated), figures.
- **C18** — Write-up draft (4-6 pages): 1-page executive summary; method;
  results; the surprising finding; **Limits** section (RES-forecast vintage
  caveat, DA-only/no intraday, no ancillary services, no per-zone grid fees,
  price-taker, no reservoir data for NO2/DK1, hourly aggregation post-cutover,
  zone structural breaks); plus the "what a desk would additionally need"
  page (position limits, curve construction, credit lines, REMIT, etc.).
- **C19** — **-> CHECKPOINT D: stop, push-notify, wait for human to read the
  write-up, verify the surprising finding isn't a bug, and hand-check three
  numbers in the table.**
- **C20** — `gitleaks` secret scan; repo size / raw-data check; licence +
  attribution check; reproducibility check (fresh clone, cached-subset run);
  align README claims with actual results.
- **C21** — **-> CHECKPOINT E (mandatory, human-only): make the repo
  public.** The agent must never flip repo visibility itself. After the
  human does this, update CV/cover-letter materials in `~/code/career`.

**Buffer note:** assume 3-4 of the ~21 cycles get lost to data pathologies.
If behind by C13, cut C14 and all stretch items. Never cut the write-up or
the checkpoints.

## What "flag and stop" means in practice

If a cycle hits a checkpoint, or a genuine blocker (missing credential,
persistent API failure, an invariant assertion failing in a way that isn't
an expected/explained finding), it must:
1. Append a clear entry to `PROGRESS.md` describing what happened and what
   it's waiting on.
2. Send a push notification (one line, plain, e.g. "Checkpoint B reached —
   battery LP ready for review on DE-LU").
3. Commit and push whatever work is safely committable.
4. **Stop.** Do not continue into the next cycle's work in the same session,
   even if tool budget remains.
