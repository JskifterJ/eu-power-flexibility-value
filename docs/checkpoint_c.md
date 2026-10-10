# Checkpoint C — the request to unseal the 2025 holdout

**Status: the 2025 holdout is SEALED. This document asks a human to unseal it,
and nothing in this cycle has been allowed to read it.**

PLAN.md C16: *"CHECKPOINT C: stop, push-notify, wait for explicit human approval
to unseal the 2025 holdout. Only after approval: run a single evaluation of the
2025 holdout; record in PROGRESS.md that it ran exactly once, with the
timestamp."*

A holdout evaluated once is worth something only if two things are true: that
nothing has peeked at it, and that every choice about how it will be evaluated
was fixed before it became visible. This document is the evidence for the first
and the record of the second. Both are machine-checked rather than asserted:

| artefact | what it is |
| --- | --- |
| `backtest/results/c16_seal_verification.json` | the seal, verified: marker, config, guard census, live refusals, artefact scan, download record |
| `backtest/results/c16_preregistration.json` | the single evaluation, specified in full, stamped with this commit and config hash |
| `backtest/run_c16_checkpoint.py` | the runner that produces both (`--phase verify`, `--phase prereg`) |
| `tests/test_c16_checkpoint.py` | 43 tests, including one per way the verification must fail |

Reproduce it with:

```
python -m backtest.run_c16_checkpoint --phase all
```

---

## 1. The seal, as verified

Verified at `ae59c54` / config `515d4e8d98887256`:

| check | result |
| --- | --- |
| the unseal marker on a line of its own in `PROGRESS.md` | **absent** — `holdout_is_unsealed()` is `False` |
| config `splits.holdout.years` | `[2025]`, `sealed: true` |
| `fetch_years` ∩ sealed years | **empty** — an ordinary cycle cannot pull 2025 |
| holdout-guard calls in the source tree | **33 calls across 14 modules** |
| required-guard modules missing a guard | **none** (6 of 6 guarded) |
| public entry points probed with a 2025 request | **8 of 8 refused** with `SealedHoldoutError` |
| runners probed end to end with `--years 2025` | **2 of 2 exited non-zero**, refusing |
| committed artefacts scanned for a 2025 row | **243 tables + 172 summaries, clean** |
| `evaluation_years` in `results.csv` | 2020-2024 only; **2025 absent** |
| the download record in `data/manifest/` | prices 2019-2024, exogenous 2022-2024; **no 2025 row, no 2025 coverage timestamp** |

The six modules that *must* carry a guard are the ones that can reach a sealed
price, a sealed exogenous series, a sealed fold or a sealed number:
`data/energy_charts.py`, `data/prices.py`, `data/entsoe.py`,
`data/exogenous.py`, `backtest/walk_forward.py`, `backtest/results_store.py` —
the last of which refuses to *write* a 2025 metric even if one were somehow
computed.

Four details make this a check rather than a ceremony.

**The refusal probes call the real entry points, and they are safe when they
fail.** Each network path is handed a session object that raises on use, so a
probe that finds its guard missing still cannot download a byte of the holdout.
A probe that must be safe only in the world where it passes is not worth
running.

**The probes run against a cache that contains a sealed year.** `data/raw/` does
not survive a container, so in a fresh checkout the stitching loaders fail with
"no cached files" and their guard is never exercised — an accident of the
container, not evidence. So `synthetic_sealed_cache()` builds the situation the
guard exists for: a cache holding `2024` and `2025` placeholder files, correctly
named for year discovery and empty of content. If the guard were gone, the
loader would reach an empty file and raise a parse error; it can never reach a
2025 price. What counts as sealed still comes from the committed
`config/data.yaml`.

**The download record is checked as well as the published numbers.** The artefact
scan proves no 2025 *number* was published; `data/manifest/` proves the simpler
and stronger thing — that no 2025 file was ever pulled. It is the committed
record of every fetch, one row per (zone, year) with each one's coverage
timestamps, so a sealed year in it would mean a download happened whatever was
later computed from it. The timestamp half is a real constraint, not a tautology:
because the Energy-Charts request window is in local time a *raw* 2024 file can
legally contain the instant 2025-01-01T00:00Z, but the manifest trims to the UTC
calendar year and every committed `last_ts_utc` ends 2024-12-31T22:00Z.
`data/raw/` is gitignored and does not survive a container, so the raw-file check
is usually vacuous and is reported with `raw_cache_present` so that a zero cannot
be mistaken for a verified absence.

**The artefact scan knows the difference between a 2025 date and 2025 data.**
`main_backtest_end` is *supposed* to say `2025-09-30`, so the structural dates
are whitelisted by key name; every other year or date column naming 2025 in any
committed table or summary is a failure. The scan is tested against planted
rows, planted date columns and planted summary keys, so it has been seen to
fail.

## 2. What the single evaluation will do, fixed in advance

All of this is in `c16_preregistration.json`, and
`test_the_committed_preregistration_still_matches_the_code_and_config` fails if
any of it drifts from the code and config that will execute it.

**Window.** 2025-01-01 to **2025-09-30**, 273 market days. It stops there
because the SDAC 15-minute go-live is 2025-10-01 and PLAN.md ends the main
hourly backtest the day before; native 15-minute analysis stays a labelled
stretch goal that is never blended into the main results.

**Zones.** All nine. Tier A: DE-LU, ES, NO2. Tier B: FR, NL, BE, IT-North, DK1,
PL.

**Arms.** The headline is the nine-zone comparable arm every cross-zone number
in C10-C15 is built on — LEAR, `price_only`, `train_from` 2019-01-01 — against
the `naive_last_week` floor and the perfect-foresight oracle ceiling. Tier A
additionally gets `price_only`, `load_only` and `res_persistence` for both LEAR
and GBM. **`res_as_published` is excluded**: the Art. 14 D-1 wind/solar forecast
is published at 18:00 on D-1, after gate closure, and C8/C9 already report its
premium as a measured leak. A once-only holdout evaluation reports the honest
arms.

**Models, frozen.** C4's committed `LearSpec` (per-hour LASSO, AIC selector,
in-fold scaling and `asinh`, local hour key) and C9's one fixed LightGBM config
(fingerprint `a366a760e269bba6`, in-fold early stopping). PLAN.md forbids a
hyperparameter search across cycles, and a holdout is not an occasion to start
one.

**Walk-forward.** `refit_every_days=1`, `min_train_days=365`, expanding window —
identical to C10/C11/C13. The expanding window means the 2025 folds train on
2019-2024 inclusive: the validation year moves from *evaluated* to *trained on*.
That is what an expanding window does and it is legitimate, because 2024 is in
the past relative to every 2025 fold.

**Dispatch.** `config/battery.yaml` as committed: 1 MW / 2 MWh, round-trip 0.88
split symmetrically, throughput cost 2.0 EUR/MWh discharged, initial SoC 0.5,
`terminal_mode: trailing_value` (7-day trailing median, quantile 0.5).
Commit-then-settle: solve on the forecast vector, freeze the schedule, value at
realised prices.

**Metrics.** MAE, RMSE, rMAE vs naive, daily-spread MAE and bias, within-day
Spearman; capture against both the rolled and the same-start oracle,
EUR/MW/yr, EUR/MW/yr lost to forecast error. Intervals: block bootstrap over
daily blocks at the committed 1 / 7 / 14-day ladder, 10 000 replicates, seed
20261009.

**Assertions that must hold on every run.** Per-day
`value(forecast @ realised) <= value(same-start oracle @ realised)`; pooled
`value(naive @ realised) <= value(forecast @ realised)`; no LP objective from a
forecast-price solve reported as a realised value; the gate-closure leakage
guard on every feature of every fold, train and test; every training target
published before its fold's gate closure; row counts per (zone, local day)
against the DST whitelist; `resolution_seconds == 3600` on every evaluated row;
and no evaluated market day on or after 2025-10-01.

**Stop rules.** The evaluation runs **once**, and PROGRESS.md records the UTC
timestamp and the git SHA it ran at. A failing invariant is a FLAG and a stop,
not an occasion to adjust the model, the config or the window. **Nothing —
model, feature set, hyperparameter, battery parameter or metric definition —
may change after the first 2025 number is seen**; a change that looks necessary
is a finding to report, and any re-run is a second evaluation that must be
labelled as one.

## 3. What 2025 will be read against

The validation-year numbers are carried into the pre-registration so the
comparison is fixed before the holdout is visible. Comparable arm (LEAR,
price-only), 2024, from `c13_per_year_metrics.csv`:

| zone | capture | EUR/MW/yr | MAE | within-day Spearman |
| --- | --- | --- | --- | --- |
| DE-LU | 0.9187 | 68 179 | 22.89 | 0.8109 |
| ES | 0.9109 | 42 407 | 17.84 | 0.8354 |
| NO2 | **0.6146** | 15 994 | 13.66 | **0.5781** |
| FR | 0.8526 | 46 777 | 17.87 | 0.8073 |
| NL | 0.9031 | 68 650 | 21.46 | 0.8300 |
| BE | 0.9044 | 56 055 | 19.37 | 0.8329 |
| IT-North | 0.9042 | 37 799 | 9.54 | 0.8852 |
| DK1 | 0.8358 | 53 884 | 25.42 | 0.7062 |
| PL | 0.8839 | 68 029 | 20.24 | 0.8135 |

## 4. Three things only a human can do, and one of them is a decision

**(a) Write the unseal marker.** The holdout unseals on a line in `PROGRESS.md`
which, stripped of whitespace, equals the `holdout_unseal_marker` value in
`config/data.yaml` — currently the string `CHECKPOINT C APPROVED: 2025 holdout
unsealed`. Copy it from the config file and paste it **alone on its own line**;
quoting it inside a sentence (as this one does) deliberately does not count, and
an agent cycle must never write that line. Then set "Next cycle to run" to
**C17**.

**(b) Add 2025 to `fetch_years` in `config/data.yaml`.** The ENTSO-E fetch is
bounded by `fetch_years` (via `entsoe.exogenous_years`) as well as by the
holdout guard, so the Tier-A 2025 exogenous pull stays refused until 2025 is in
that list. The Energy-Charts price fetch is bounded only by the guard. This
changes `config_hash`, which is why it belongs with the approval rather than
inside the unseal cycle.

**(c) Decide NOTE C15-01 — the end-of-day inventory mark — *before* the
unseal.** C15's FINDING C15-D says the committed `trailing_value` mark does not
prevent the nightly degeneration it was introduced for (the battery still ends
74-77% of days empty) and that where it binds, the point estimate is that it
*costs* ~2 900 EUR/MW/yr — not established (16 of 45 cells on cash, 0 of 45 on
capture). C15's recommendation was **(a) keep it and carry the finding as a
stated limitation**. That recommendation stands here, and the reason is now
sharper: changing `terminal_mode` after the holdout has been evaluated would
mean evaluating it a second time. If it is going to change, it must change
first.

## 5. What the unseal cycle will have to do, and what could go wrong

No 2025 file has ever been cached, so C17 starts with a fresh download: **9
zone-years of Energy-Charts prices** and **3 zones × 2 ENTSO-E documents**, one
request each, then cached. `ENTSOE_API_KEY` is present in this environment.

Two things are expected rather than surprising, and one is a flag:

* **A resolution change inside the 2025 price file.** A full-year 2025 pull
  contains 15-minute data from 2025-10-01. `data/contracts.py` detects it; the
  evaluation window ends 2025-09-30 so no 15-minute row is scored, and the
  post-cutover segment is reported, not silently dropped.
* **A shorter year than the others.** 273 market days against 365-366, so
  per-year cash is annualised and the annualisation is stated beside every
  number rather than hidden in it.
* **A 404, an empty response or an Acknowledgement from either source is a
  FLAG**, not a puzzle: the dependent zone is skipped, the rest continues, and
  it goes in `PROGRESS.md`.

## 6. What this cycle did not do

It did not fetch, load, read, feature-engineer from, train on, or compute any
metric against 2025 data. It wrote no 2025 row into any artefact. It did not
write the unseal marker, change `fetch_years`, change `terminal_mode`, or start
any part of C17. The verification above is the evidence for the first two
claims; the diff is the evidence for the rest.
