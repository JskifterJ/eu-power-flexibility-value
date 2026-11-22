# eu-power-flexibility-value

**Status: work in progress. Not yet a finished deliverable — no result here has been
through the pre-public review gate, and the out-of-sample holdout has not been evaluated
yet.**

> This line used to say the repository was private during the build. It is public (since
> 2026-10-29, at the owner's instruction, ahead of the checkpoint that was meant to do it),
> so that sentence was corrected rather than left standing on a public page. The review gate
> it describes — Cycle 20 in `PLAN.md`: secret scan, licence and attribution check,
> reproducibility from a fresh clone, and an alignment check between the claims in this file
> and the actual results — has **not** run. Read anything here as a build log, not as a
> finding.

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

Two things that process has not delivered as designed, stated here rather than only in the
log: the repository was made public before the checkpoint meant to decide that, and the
2025 holdout — unsealed by the owner on 2026-10-12 — has still not been evaluated, because
the environment its evaluation was pre-registered in cannot be rebuilt in the cloud
container the cycles run in (`docs/c17_environment.md`). Both are open items in
`PROGRESS.md`, not oversights discovered by a reader.
