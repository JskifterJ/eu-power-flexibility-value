# The append-only results store (C10)

PLAN.md C10 asks for the harness to be scaled to all nine zones and for
*"results written append-only, each row tagged with git SHA + config hash"*.
This document is the record of how that was built, what the schema means, and
the four design choices that are load-bearing.

Code: `backtest/results_store.py`, `backtest/run_c10_scale.py`.
Tests: `tests/test_c10_results_store.py` (46), `tests/test_c10_scale_out.py` (27).
Artefacts: `backtest/results/results.csv`, `backtest/results/results_runs.json`,
`backtest/results/c10_scale_summary.json`,
`backtest/results/c10_tierb_<ZONE>_2024_{predictions.csv.gz,folds.csv,summary.json}`.

---

## Why a store at all

Through C9 every number lived in a per-cycle JSON summary. That worked while
there were three zones and one model, and it stops working at nine zones x up
to nine series x a growing metric list: the C18 write-up would be assembled by
hand out of twelve files, and nothing would stop two cycles from quoting the
same metric at different values. From C10 the numbers accumulate in one table,
and the per-cycle summaries remain as the detailed provenance behind each row.

The store is **append-only** because this project is built by unattended
cycles. A cycle that notices an inconvenient number and "corrects" it in place
leaves a diff that looks like tidying. The store's one promise is therefore:

> An earlier cycle's number may be **superseded** by a later row. It is never
> changed in place.

## The schema, and why it is long

A row is `(run, zone, model, arm, scope, metric) -> value`. One metric per row.

The wide alternative — one row per series with `mae`, `rmse`, … columns — reads
better and breaks on the first cycle that adds a metric. C11 adds per-day
capture ratios, C12 adds daily-spread error, within-day Spearman and
block-bootstrap bounds; every one of those would be a column that every
previously-appended row lacks. In long format a new metric is a new *value* in
an existing column, so the schema C10 froze is the schema C12 still writes
into.

**The extension point is the metric name, never the column list.** That is also
why `tests/test_c10_results_store.py` deliberately does *not* pin the full
column tuple the way `tests/test_c9_gbm.py` pins `GbmSpec`: CLAUDE.md makes
editing a test a flag-and-stop event, and a schema frozen by test would turn a
routine C11/C12 append into a blocked cycle. What the tests do pin is that the
provenance columns PLAN.md requires are present, that metric names C11/C12 will
want are accepted, and that a header change is refused as a migration rather
than absorbed.

| group | columns |
|---|---|
| provenance | `run_id`, `appended_at_utc`, `cycle`, `git_sha`, `config_hash`, `library_fingerprint` |
| what was measured | `zone`, `tier`, `regime`, `model`, `model_fingerprint`, `exog_variant`, `vintage` |
| how it was measured | `train_from`, `evaluation_years`, `refit_every_days`, `min_train_days`, `train_window_days`, `n_folds`, `scope` |
| the number | `metric`, `value`, `n`, `n_scored` |
| where it came from | `source_artefact`, `source_cycle`, `source_git_sha` |

`n` and `n_scored` ride along on every row rather than being metrics of their
own: they are part of reading the number, not a separate measurement.

## Append-only is verified, not promised

Two mechanisms, both executable:

1. **Prefix identity on every write.** `append_rows` reads the file's existing
   bytes, appends, and then asserts the new file still *starts with* those exact
   bytes. A rewrite that happens to produce a plausible table fails here.
2. **A hash chain in `results_runs.json`.** Each run records the SHA-256 of the
   whole file as it stood after that run appended — which is the hash of its
   first `n_rows_after` data rows. `verify_append_only()` replays those hashes
   against the file's own prefixes, so an edit to any earlier row is detectable
   long after the run that wrote it is gone.

The chain also catches a deleted row, a row appended by hand with no manifest
entry (its provenance would be unverifiable), and a manifest that is not in
append order. Each of those has a test.

A column change is a **migration**, not an append: `append_rows` refuses a file
whose header is not exactly the code's `SCHEMA`, and says so. The migration
route is to write a new file and record it in PROGRESS.md, leaving the old one
intact.

## Provenance includes the libraries

Every row carries the `git_sha` and `config_hash` PLAN.md asks for, plus the
model's own config fingerprint where it has one (`GbmSpec.fingerprint()` =
`a366a760e269bba6` for every C9 row) — and a `library_fingerprint`.

The last one is the C9 entry's closing suggestion, taken up. The GBM
fingerprint pins the values *we* set; everything `GbmSpec.booster_params()`
does not name (`max_depth`, `max_cat_threshold`, `min_data_per_group`) comes
from the installed LightGBM, so a major-version bump that moved a default would
change results without moving the fingerprint. The row carries a 16-hex hash
over `{python, numpy, pandas, scikit-learn, scipy, lightgbm}`; the run manifest
keeps the full version dict. A library that is not installed is recorded as
`"absent"` rather than omitted, because an omitted key would quietly change the
fingerprint's meaning.

## The vintage label is part of the key

FINDING C9-C: the Art. 14 `res_as_published` arm — RES forecasts published at
18:00 on D-1, six hours after the gate the model is predicting — buys **18-24%
of MAE** that no bidder could have had. A store that lets that number be read
without its label is a trap, so `vintage` is a required key column taking
`honest` or `after_gate_closure`, an unknown value is refused, and
`honest_rows()` is the filter a reporting cycle should reach for by default.
A cycle that wants the late arm has to ask for it by name.

## Sealed holdout

`append_rows` parses `evaluation_years` and runs `data.holdout.assert_not_sealed`
on it, so a metric computed against 2025 cannot be *written* even if some future
caller computes one by mistake. A spelling the guard cannot read (`"validation"`)
is refused rather than waved through — better to refuse an unparseable label
than to let the guard see no year. `"2024-2025"` is caught.

---

# The C10 scale-out

`backtest/run_c10_scale.py` runs in two phases, on purpose.

## `compute` — Tier B, the only new fitting in this cycle

Six zones (FR, NL, BE, IT-North, DK1, PL) x `naive_last_week` + `train_mean` +
LEAR on price-history and calendar features only, walked forward daily across
2024, expanding window over the whole cached price history. Writes
`c10_tierb_<ZONE>_2024_*`. Each zone is independent, so the phase takes
`--zones` and several processes may run it in parallel — nothing is appended to
the store here, which is what makes that safe.

**Tier B trains on the full price history (2019+), not on C8's aligned 2022
start.** Tier A's four arms are cut from 2022-01-01 because no archived ENTSO-E
forecast vintage exists earlier; Tier B has no exogenous block and so no such
constraint, and runs C4's committed `LearSpec` on everything available. The
nine-zone comparable row set is therefore `lear` / `price_only` /
`train_from=2019-01-01`, which exists for Tier A too: C8 ran exactly that as its
`full_history_reference` and committed it as `y_pred_price_only_full_history`.
The cross-zone table is like-for-like by construction rather than by assertion.

## `ingest` — one process, one append

Reads every committed artefact (C8's LEAR arms, C9's GBM arms, this cycle's
Tier-B runs), **recomputes** every metric from the prediction columns,
cross-checks each recomputed number against the number its source summary
committed, and appends the lot as a single run.

**Why Tier A is ingested rather than refitted.** Refitting 24 model-arms would
spend hours reproducing committed numbers and — worse — would let the store's
Tier-A rows drift from the artefacts the findings were written against if any
spec had moved. C9 set the precedent by reading C8's LEAR predictions instead of
refitting them; C10 extends it with three assertions per zone:

* C8's and C9's prediction **indices must be equal** — a mismatch means the two
  cycles did not evaluate the same hours, and is refused rather than realigned;
* their committed **realised prices must agree** with each other, and
* both must agree with a **freshly loaded price series** from this cycle's
  re-pulled cache (NOTE C2-02 makes that re-pull happen every cycle anyway, so
  the check is free);
* every metric is **recomputed from the predictions** and asserted equal to the
  committed value to the artefact's own `%.4f` precision (`5e-4`). The tolerance
  is the artefact's precision, not a margin chosen to let a disagreement pass.

The cross-check report is written into `c10_scale_summary.json`, so the store
shows its own working.

## What `scope` means

* `own_coverage` — each series scored on the hours it answered.
* `common_hours` — every series of that zone re-scored on the intersection of
  all of them. For Tier A that is the intersection over exactly the nine series
  C9's artefact carries, which is what makes the recomputation checkable against
  C9's committed `common_hours` block (DE-LU 8 782, ES 8 591, NO2 8 783).

The two tiers' intersections are over different series sets, which is why the
nine-zone comparable table is built from `own_coverage` rows and carries
`n_scored` beside every number: LEAR declines one hour a year — the autumn DST
hour whose 24-hour lag the gate-closure mask blanks, FINDING C3-A — so it is
8 783 against the naive floor's 8 784. The comparison is on effectively
identical hours and the column says so rather than a footnote.

## Reading the store

```python
from backtest.results_store import honest_rows, latest_results, pivot_metric, verify_append_only

verify_append_only()                      # the chain, before trusting anything
pivot_metric("mae", honest_rows())        # zone x series, leak-free rows only
latest_results()                          # one row per measurement, newest run wins
```

`latest_results()` orders by append time then run id and keeps the last row per
measurement key, so a later run supersedes an earlier value deterministically
while both remain in the file.
