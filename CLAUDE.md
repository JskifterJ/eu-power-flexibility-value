# Instructions for any Claude session working in this repo

This project is built across many unattended, scheduled sessions (roughly
every 8 hours), not one continuous human-supervised session. These rules
exist because of that — read them before doing anything else, every time.

## Read first, every session

1. `PLAN.md` — the design and the ~21-cycle plan. Find "next cycle to run" in
   `PROGRESS.md`, then read that cycle's entry in `PLAN.md`.
2. `PROGRESS.md` — the running log. Append to it, never rewrite history in it.

## Hard rules — do not deviate from these without flagging and stopping

- **Never edit anything under `tests/`, or any data-contract/leakage-assertion
  file, without first appending a FLAG entry to `PROGRESS.md` explaining why
  and stopping for human review.** If a test is failing, the test is
  probably right and the code is wrong — fix the code. Making a red test
  green by editing the test is the single most dangerous thing an unattended
  cycle can do here, and it will not look wrong in the diff.
- **The 2025 calendar year is a SEALED HOLDOUT.** Do not load, read, feature-
  engineer from, train on, or compute any metric against 2025 data until
  `PROGRESS.md` records that Checkpoint C (Cycle 16) has been explicitly
  approved by the human. When it is unsealed, evaluate it exactly once and
  record the timestamp.
- **Everything internally in UTC.** Local hour-of-day is an explicit feature
  column, never used for resampling or alignment. Assert expected row count
  per (zone, day) against a DST whitelist rather than silently
  dropping/filling on a mismatch.
- **A 404, an empty/Acknowledgement API response, or any other unexpected
  data-source behavior is a FLAG, not a puzzle.** Do not guess alternate
  endpoints or silently swallow it in a try/except. Log it to `PROGRESS.md`,
  skip only the dependent work, and continue with what doesn't need it.
- **Never re-download data that's already cached** (check the manifest in
  `data/manifest/` first). ENTSO-E rate-limits/throttles abusive tokens.
- **Never commit `.env`, API keys, or bulk raw data.** `data/raw/` is
  gitignored on purpose — commit fetch scripts and the manifest, not the raw
  pulls.
- **Never change repo visibility to public.** Only a human does this, at
  Checkpoint E (Cycle 21), never an agent cycle.
- **At a checkpoint cycle: do the checkpoint's own required output, then
  stop.** Append the status to `PROGRESS.md`, send one push notification
  (one line, plain, say what's ready for review), commit and push whatever
  is safely committable, and end the session — do not continue into the next
  cycle's work even if tool budget remains.
- **Keep the battery LP's core invariants as executable assertions and run
  them every cycle they apply**: `value(forecast schedule @ realised prices)
  <= value(oracle schedule @ realised prices)` every day; `value(naive @
  realised) <= value(forecast @ realised)` on average (not per-day — per-day
  violations are real and expected, not bugs). Never report an LP's own
  objective value from a run solved on forecast prices as if it were the
  realised value ("commit-then-settle": solve on forecast, freeze the
  schedule, value at realised).

## End of every cycle

Append a dated entry to `PROGRESS.md`: what was done, what's next, any FLAGs
raised. Commit with a clear message. Push.

## If ENTSOE_API_KEY is required but not set

Flag it in `PROGRESS.md` and continue with whatever work doesn't depend on
it (Tier-B zones, Energy-Charts-only work) rather than blocking the cycle.
