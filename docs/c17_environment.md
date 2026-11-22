# C17 — the one blocker left, and it is the container, not the code

**Status: the pre-registered evaluation of the 2025 holdout is written, tested
and unblocked on every count but one. It has not run. No 2025 forecast,
dispatch, capture ratio or error metric exists.**

This file is for the human. It states one fact, gives the evidence, and asks
one question.

## 1. The fact

`backtest/results/c16_preregistration.json` — written and committed at
Checkpoint C while the holdout was still sealed — pins the environment the
single evaluation must run in:

```
library_fingerprint: 856fb19ac0c4eecd
  python 3.11.17
  numpy 2.4.6   pandas 3.0.6   scikit-learn 1.9.1   scipy 1.17.1
  lightgbm 4.7.0
```

The fingerprint is `sha256(json.dumps(versions, sort_keys=True))[:16]` over
exactly that dict (`backtest/results_store.py`), **including the CPython patch
version**. Every number C10–C15 published carries it, and the holdout's whole
purpose is to be read against those numbers.

In this cloud container the five numerical libraries install at exactly the
pinned versions. **CPython 3.11.17 does not exist here and cannot be made to.**

```
python 3.11.18 + the five pinned libraries -> 00a12bd6aadb09f3
python 3.11.17 + the five pinned libraries -> 856fb19ac0c4eecd   (pre-registered)
python 3.11.15 + the five pinned libraries -> e330d89eba746dd9
```

So `--phase preflight` reports exactly one standing blocker,
`library_fingerprint_moved`, and `--phase evaluate --year 2025` refuses on it.
That refusal is correct and deliberate: the gate is the preflight's own
conjunction, there is no override flag, and an unattended cycle must not decide
on its own that a pre-registered environment is close enough.

## 2. The evidence

| what was tried | result |
| --- | --- |
| system interpreter | `Python 3.11.18 (main, Oct 26 2026) [GCC 13.3.0]` |
| `uv python install 3.11.17` | `error: No download found for request: cpython-3.11.17-linux-x86_64-gnu` |
| `uv python list --all-versions`, 3.11 line | 3.11.18 (system), then 3.11.15, .14, .13, .12, .11, .10, .9 as downloads — **no .16 or .17** |
| source build from python.org | `HTTP/1.1 403 Forbidden (agent proxy: no rule or network setting allows this host)` |
| source build from the CPython git tag | not attempted: this session's GitHub access is scoped to this repository, and cloning another is denied |

The pinned libraries themselves are not the problem — PyPI is reachable and
`uv pip install numpy==2.4.6 pandas==3.0.6 scikit-learn==1.9.1 scipy==1.17.1
lightgbm==4.7.0` resolves exactly. Only the interpreter is unobtainable.

This is not specific to this container. Every scheduled cycle gets a fresh one
from the same image, so **no future cloud cycle will clear this gate either**
unless something changes.

## 3. What is ready, so that the decision is about one thing only

* `backtest/run_c17_holdout.py` now carries the evaluation the pre-registration
  specifies: `--phase compute | dispatch | analyse | ingest`, and `--phase
  evaluate` which runs all four in one process. It runs **once** (a committed
  ledger, `c17_holdout_run_ledger.json`, with no override flag), **whole**
  (`--zones` may not narrow the nine), and only in the **registered
  environment**.
* It reuses rather than re-implements: C4's `LearSpec`, C3's walk-forward, C5/C6's
  rolling LP and commit-then-settle, C11's `pooled_capture`, C12's metric layer
  and bootstrap, C13's per-year table builders. A 2025 capture ratio is produced
  by the same lines of Python as the 2020–2024 ones, which is what makes it
  comparable at all.
* `tests/test_c17_evaluation.py` (29 tests) exercises every gate by making it
  fail, not by watching it pass.
* It was **rehearsed end to end on 2024**, the visible validation year, writing
  `c17_rehearsal_*` artefacts that cannot be confused with holdout ones and
  appending nothing to the store. The rehearsal's 2024 headline is checked
  against the baseline `c16_preregistration.json` recorded while the holdout was
  sealed — see `backtest/results/c17_rehearsal_2024_vs_2024.csv`.
* FLAG C17-01 is closed in practice: the §5(a) fix is in, and all 24 ENTSO-E
  documents including the six that were refused are fetched and in the manifest.

Two preflight artefacts are committed, deliberately.
`backtest/results/c17_preflight.json` is the record of the cycle that found
FLAG C17-01 and is left exactly as it was written — a test pins what that cycle
found, and overwriting it would erase the finding rather than date it.
`backtest/results/c17_preflight_2026-11-22_after_the_entsoe_fix.json` is the
current state: exogenous path `reachable`, one standing blocker,
`library_fingerprint_moved`. When the environment question below is answered,
the evaluation cycle should regenerate the canonical `c17_preflight.json` in
the environment it actually evaluates in.

## 4. The question

**May the single pre-registered evaluation run under CPython 3.11.18 instead of
3.11.17, with the five numerical libraries at exactly their pinned versions?**

Three ways to answer:

**(a) Approve the deviation (recommended).** Every library that can move a
number is identical; the difference is one CPython patch release. The honest
cost is that the deviation has to be stated: `library_fingerprint` on the 2025
rows would read `00a12bd6aadb09f3` rather than `856fb19ac0c4eecd`, and the
write-up has to say that the holdout ran on a patch-newer interpreter than the
2024 baseline. That is a footnote a reader can check, not a hidden assumption —
which is the only reason it is recommended over doing it quietly, and the gate
is built so it cannot be done quietly.

**(b) Run it somewhere with 3.11.17.** A `python:3.11.17` image, or a local
interpreter, plus `uv pip install` of the five pins. The repo is the same; the
command is `python -m backtest.run_c17_holdout --phase evaluate`. This is the
clean answer if it is cheap for you. Note the Windows checkout is 3.14.5 and
would be a *larger* deviation than (a), not a smaller one.

**(c) Re-pin the pre-registration.** Possible without contaminating anything,
because **no 2025 number has been computed**, so nothing has been seen that
could motivate a choice of environment. But it rewrites a Checkpoint-C artefact
after the unseal, so it should be a deliberate human edit with its own
PROGRESS.md entry, not an agent's.

Whatever the answer, it belongs in `PROGRESS.md` in the same shape as the §5(a)
and §5(b) approvals, naming this file and this section.

## 5. One new data FLAG from the fetch, unrelated to the above

**NO2's 2025 Art. 14 wind forecast is mostly unusable after hourly
aggregation.** ENTSO-E also moved to a 15-minute MTU during 2025, so the 2025
documents arrive at mixed resolution (`resolutions_seconds: 900|3600` in
`data/manifest/exogenous_manifest.csv`). `coverage_ratio` is 1.0 and
`n_gap_intervals` is 0 — nothing is missing at native resolution — but the
hourly aggregator declines to average a UTC hour that its sub-hourly intervals
do not tile exactly, and for NO2 that leaves **18 784 NaN hours of 2025** in
`wind_forecast_da_mw` (DE-LU: 4, ES: 96). The NaNs are a deliberate refusal to
partially average, not a silent hole.

What it costs: nothing in the pre-registered headline, which is price-only
(`lear_full_history`, `naive`, `oracle`). It would cost the Tier-A exogenous
ladder for NO2 — and the pre-registration already excludes `res_as_published`,
while NOTE C8-01 is closed with "the honest exogenous block does not have a
reliable positive value, in either model class, either year, any Tier-A zone",
so the ladder is not load-bearing for anything C18 may claim. Recorded here so
that a later cycle reading the NO2 exogenous columns knows why they are thin,
rather than discovering it as a surprise.
