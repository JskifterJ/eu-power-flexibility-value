# eu-power-flexibility-value

**Status: work in progress. Not yet a finished deliverable — the out-of-sample holdout
has not been evaluated yet. Read this file as a build log, not as a finding.**

> This line used to say the repository was private during the build. It is public (since
> 2026-10-29, at the owner's instruction, ahead of the checkpoint that was meant to do it),
> so that sentence was corrected rather than left standing on a public page.
>
> The pre-public review gate it used to say had not run — Cycle 20 in `PLAN.md`: secret
> scan, repo size and raw-data check, licence and attribution check, reproducibility from a
> fresh clone, and an alignment check between the claims in this file and the actual
> results — **has now run, after publication rather than before it.** What it found, in
> full, is in `docs/c20_pre_public_gate.md`, and the machine-readable artefacts are the
> `backtest/results/c20_*.json` files. In short: no secret in any of the 181 commits, no raw
> data ever committed, and an independent clone of this repository reproduces the published
> per-day dispatch numbers exactly — but the gate also found that this file was carrying
> neither of the data attributions its sources require, and that three committed figures
> shipped without one. Both are fixed below and in the figures. The holdout is still
> unevaluated, for the reason given at the end of this file.

How much of a battery's theoretical arbitrage value in European day-ahead power
markets is actually capturable once you account for forecast error? This
project forecasts day-ahead prices across a tiered set of European bidding
zones, dispatches a storage asset against those forecasts via a rolling-horizon
LP, and measures the gap between forecast-driven value, perfect-foresight
value, and a naive baseline — with an explicit walk-forward backtest, a sealed
out-of-sample holdout, and stated leakage/limitation checks throughout.

See `PLAN.md` for the full design and cycle plan, `docs/audit.md` for the
independent pre-build audit this plan was revised against, and `PROGRESS.md`
for the running build log. This README will be rewritten as the actual
findings document once the build is complete (see Cycle 17 in `PLAN.md`).

## Data sources, licence and attribution

The **code** in this repository is MIT licensed — see `LICENSE`. The **data** is not the
author's to license, and the derived artefacts in `backtest/results/` and `docs/figures/`
are derived works of two public sources, each of which requires attribution:

- **Day-ahead prices, all nine bidding zones: Energy-Charts (Fraunhofer ISE), CC BY 4.0**
  — `api.energy-charts.info`. Licensed under
  [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
  Every figure built on these prices carries the line
  `Data: Energy-Charts (Fraunhofer ISE), CC BY 4.0`.
- **Tier-A day-ahead load and wind/solar forecasts: ENTSO-E Transparency Platform**
  — `transparency.entsoe.eu`, used under the platform's reuse conditions, which require
  attribution. Figures built on these series name the platform and the article the series
  comes from (Art. 6 load, Art. 14 wind/solar).

Neither source endorses this work. No raw data from either source is committed: `data/raw/`
is gitignored and what is committed is the fetch code plus the manifest in `data/manifest/`,
which records row counts and payload fingerprints so a reader can re-pull the same data and
check they got the same bytes. The attribution strings are declared once, in
`config/data.yaml`, and the C20 gate checks that every committed figure's producing module
emits them.

## Build process disclosure

This repository is being built by an autonomous coding agent (Claude), running
in scheduled unattended cycles, under a written plan with executable leakage
tests, a sealed 2025 holdout, and mandatory human checkpoints before any
result is finalized or the repo is made public. That process — the plan, the
guardrails, and the bugs it caught — is treated as part of the deliverable,
not something to hide. Details in `PLAN.md`.

Two things that process has not delivered as designed, stated here rather than only in the
log: the repository was made public before the checkpoint meant to decide that, and the
2025 holdout — unsealed by the owner on 2026-10-12 — has still not been evaluated, because
the environment its evaluation was pre-registered in cannot be rebuilt in the cloud
container the cycles run in (`docs/c17_environment.md`). Both are open items in
`PROGRESS.md`, not oversights discovered by a reader.
