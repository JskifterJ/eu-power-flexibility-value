# eu-power-flexibility-value

**Status: work in progress — repository is private during the build. Not yet a finished deliverable.**

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

## Build process disclosure

This repository is being built by an autonomous coding agent (Claude), running
in scheduled unattended cycles, under a written plan with executable leakage
tests, a sealed 2025 holdout, and mandatory human checkpoints before any
result is finalized or the repo is made public. That process — the plan, the
guardrails, and the bugs it caught — is treated as part of the deliverable,
not something to hide. Details in `PLAN.md`.
