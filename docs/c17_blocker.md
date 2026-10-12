# C17 — blocked before the holdout evaluation, and the decision it needs

**Status: the pre-registered 2025 evaluation did NOT run. No forecast, no
dispatch and no metric was computed against 2025 data in this cycle.**

The holdout is unsealed and everything the pre-registration asks for is in
place except one thing: this repo's own ENTSO-E parser still refuses every
2025 response, because a sealed-year tripwire inside it was never taught that
a human can unseal the holdout. Fixing it means editing a sealed-holdout
assertion, which CLAUDE.md makes a flag-and-stop event and PLAN.md lists among
its five human checkpoints. So this cycle stopped and wrote this instead.

Everything below is reproducible with:

```
python -m backtest.run_c17_holdout --phase preflight
```

which writes `backtest/results/c17_preflight.json` and exits non-zero while
the blocker stands.

---

## 1. What is ready

| check | result |
| --- | --- |
| `holdout_is_unsealed()` | **True** — the marker is a line of its own in `PROGRESS.md` |
| frozen specs vs `c16_preregistration.json` | **15 of 15 agree**, 0 drift (LEAR selector/hour-key/VST, GBM fingerprint `a366a760e269bba6`, all seven battery parameters, all three walk-forward parameters) |
| `library_fingerprint` | **`856fb19ac0c4eecd` — matches**. Python 3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1, lightgbm 4.7.0, pinned in the venv to the versions C10–C15 published under |
| `config_hash` | `99005aeccae76c70` vs the pre-registered `515d4e8d98887256` — **the one field allowed to move**, predicted by name in `checkpoint_c.md` §4(b) because the approval added 2025 to `fetch_years` |
| Energy-Charts 2025 prices | **9 of 9 zone-years fetched**, 0 flagged, now in the manifest |
| the evaluation window | **273 market days, 2025-01-01 … 2025-09-30, in all nine zones**, exactly the pre-registered count |
| resolution inside the window | **one segment, 3600 s, every zone**. 59 159 hourly rows per zone |
| ENTSO-E 2022–2024 | **18 of 18 documents fetched**; re-pull reproduces the committed exogenous manifest on every value including `payload_sha256` |

Two reproduction results worth keeping, both off a fresh container with an
empty cache and an independent re-pull:

* **The price manifest's 54 rows for 2019–2024 reproduce exactly** — every
  count, every price statistic, every `payload_sha256` — with `fetched_at_utc`
  the only column that moved.
* **The exogenous manifest's 27 rows reproduce exactly** on every value;
  `fetched_at_utc` and `gzip_bytes` (gzip is not byte-deterministic) are the
  only columns that moved.

## 2. The 15-minute cutover, reported rather than handled silently

`checkpoint_c.md` §5 asked C17 to report this, not absorb it.

The SDAC go-live is visible in all nine zones at exactly the predicted instant:
**one** resolution change, at **2025-09-30T22:00:00Z** = 2025-10-01 00:00 CEST,
3600 s → 900 s. Before it: 59 159 hourly intervals from 2018-12-31T23:00Z. After
it: 8 835 quarter-hourly intervals to 2025-12-31T22:45Z.

The last hourly row starts at 2025-09-30T21:00Z, which is the final hour of
local market day 2025-09-30 — so the window closes on a **complete** day and no
15-minute row can enter it. `data/contracts.py` detects the change and
`cutover_violations` is empty, meaning it landed where the config says it
should.

Two consequences that must be read with the artefacts rather than around them:

* **The contract report now carries 100 violations per zone, and every one of
  them is post-cutover.** They are the hourly day-count contract meeting
  96-row days: the earliest is UTC day 2025-09-30 (22 hourly + 8 quarter-hourly
  rows), and the lists are capped at 50 each. Nothing before the cutover
  violates anything. This is the contract working, not failing.
* **The 2025 manifest row reads `coverage_ratio` 0.439 and 6 550 gap
  intervals.** Those are computed at the year's *modal* resolution, which is
  900 s because the 15-minute segment outnumbers the hourly one. The 6 550
  "gaps" are the hourly Jan–Sep rows counted against a 15-minute expectation.
  Nothing is missing. The row is left as the builder produced it — the
  manifest's job is to record the download, not to flatter it — and the reading
  is attached in `c17_preflight.json`.

## 3. The blocker

`data/entsoe.py`, inside `parse_document`, checks the parsed frame's years
against `sealed_years()` and raises `UnexpectedResponse` on a hit:

```python
sealed = sealed_years()
if sealed:
    hit = sorted(set(int(y) for y in frame.index.year) & sealed)
    if hit:
        raise UnexpectedResponse(
            f"{context}: response contains timestamps in SEALED year(s) {hit}. ..."
        )
```

`sealed_years()` is the **permanent declaration** in `config/data.yaml`. It
still reads `{2025}` after Checkpoint C and is supposed to — the unseal marker
is what overrides it, and `data/holdout.holdout_is_unsealed()` is the only
function that knows about the marker. This check never asks it. So since the
approval it refuses **every** 2025 ENTSO-E response.

**It was right before Checkpoint C.** Its stated purpose is to catch an
inclusive `periodEnd` — a 2024 request coming back with 2025 rows. While 2025
was sealed, "contains a sealed year" and "leaked past the requested window"
were the same condition. The approval separated them.

**Observed, 6 times out of 6.** The live fetch pulled 2022–2024 for all three
Tier-A zones and both documents (18 downloads) and was refused on all six 2025
requests:

```
FLAG DE-LU load_forecast_da 2025:       UnexpectedResponse: ... SEALED year(s) [2025]
FLAG DE-LU wind_solar_forecast_da 2025: UnexpectedResponse: ... SEALED year(s) [2025]
FLAG ES    load_forecast_da 2025:       UnexpectedResponse: ... SEALED year(s) [2025]
FLAG ES    wind_solar_forecast_da 2025: UnexpectedResponse: ... SEALED year(s) [2025]
FLAG NO2   load_forecast_da 2025:       UnexpectedResponse: ... SEALED year(s) [2025]
FLAG NO2   wind_solar_forecast_da 2025: UnexpectedResponse: ... SEALED year(s) [2025]
```

The response was downloaded, refused at parse time and **not cached**, so the
six requests bought nothing and will have to be made again after the fix.

**Reproduced in code, not just in a log.** `entsoe_parse_guard_probe()` in
`backtest/run_c17_holdout.py` hands `parse_document` a three-point synthetic
A65 document dated 2025-03-01 — no network request, nothing cached — and
records the refusal. A log line is evidence about a run; this is evidence about
the code.

**The repo's own test suite already says this is a bug.**
`tests/test_c7_entsoe.py::test_fetching_2025_now_passes_the_holdout_guard`
asserts that `fetch_year("DE-LU", load_forecast_da, 2025)` gets *past* the seal
guard. It passed on the machine it was written on only because no
`ENTSOE_API_KEY` was set there, so the call stopped earlier at
`MissingCredential`. With a real key it reaches the parser and fails. CLAUDE.md:
*"If a test is failing, the test is probably right and the code is wrong — fix
the code."*

### The proposed fix (not applied)

Route the same hit through the guard that knows about the marker, which is what
the two sibling belt-and-braces checks already do (`data/prices.py:120`,
`data/exogenous.py:275`):

```python
sealed = sealed_years()
if sealed:
    hit = sorted(set(int(y) for y in frame.index.year) & sealed)
    if hit:
        assert_not_sealed(
            hit,
            f"parse a response for {context} carrying timestamps in year(s) {hit} "
            f"(ENTSO-E's periodEnd is meant to be exclusive)",
        )
```

`assert_not_sealed` applies the identical sealed-year test and then consults
`holdout_is_unsealed()`. The tripwire keeps working for every year that is
still sealed, and yields only to the human's approval.

**What the fix does not cost.** The check never compared the response against
the *requested* year, so it never guarded the exclusive-`periodEnd` property
for an unsealed year — there was nothing there to lose. Nothing that was being
checked stops being checked.

**Why this cycle did not apply it.** It is a sealed-holdout assertion.
CLAUDE.md makes editing a data-contract or leakage-assertion file a
flag-and-stop event; PLAN.md lists "before modifying a frozen test/contract" as
one of its five human checkpoints. An unattended cycle quietly editing a seal
tripwire, in the very cycle that first touches the holdout, is the case those
rules exist for.

## 4. Why the headline was not run anyway

The nine-zone headline arm — LEAR `price_only` against the naive floor and the
perfect-foresight oracle — needs Energy-Charts prices only. It is **not
blocked**. It was still not run, and that is a judgement worth stating plainly
rather than burying.

A holdout evaluated once is worth something only because it is evaluated once.
Splitting the single pre-registered evaluation into "the headline today, the
Tier-A exogenous arms after a code change" would mean the second half ran
under a fix made *after* the first 2025 numbers were visible — which is the
shape the pre-registration's own stop rule exists to forbid, even though a
parser guard is none of the five things it names. The cost of waiting is one
cycle out of a plan that budgets three to four for exactly this. The cost of
not waiting is permanent and unrecoverable.

So: the evaluation runs **whole, once, after the fix**.

## 5. What a human needs to decide

**(a) Approve the one-call fix to `data/entsoe.py` above.** Nothing else in the
file changes. After it, `python -m data.fetch_exogenous` makes the six refused
requests again and caches them.

**(b) Decide what to do about seven tests that are now red, none of which may
be touched without this same approval.** Six of the seven are not defects —
they assert a state this cycle legitimately changed:

| test | why it is red |
| --- | --- |
| `test_c7_entsoe.py::test_fetching_2025_now_passes_the_holdout_guard` | **the genuine bug above.** Green again once (a) is applied, and it is the fix's own regression test |
| `test_c13_regime.py::test_2025_now_passes_the_holdout_guard_in_regime_price_table` | expects `RegimeError "no hourly price"`; 2025 prices are now cached, so the call succeeds |
| `test_c14_fundamentals.py::test_2025_now_passes_the_holdout_guard_in_fundamentals_frame` | expects `ExogenousDataError "no cached ENTSO-E"`; did not raise |
| `test_c14_fundamentals.py::test_2025_now_passes_the_holdout_guard_in_headroom_frame` | same |
| `test_c16_checkpoint.py::test_entry_point_probes_now_pass_the_unsealed_guard` | `run_probes()` raises the pre-approval catastrophe message ("the 2025 holdout is reachable… the one failure this checkpoint exists to catch"), which is now the correct and intended state |
| `test_c16_checkpoint.py::test_the_download_record_names_no_sealed_year` | the download record now legitimately names 2025 |
| `test_c16_checkpoint.py::test_manifest_scan_is_explicit_that_an_absent_raw_cache_is_not_evidence` | the raw cache is no longer absent |

These are the same family the Checkpoint C session already rewrote across nine
files; these three C16 ones and the two C14 ones could only go red once a real
2025 fetch happened, which is why they survived that pass. A consequence worth
noting for C20: **`run_c16_checkpoint.py --phase verify` cannot pass again**,
by design — it verifies a seal that has been deliberately opened.

**(c) Note that Bug 3 from the Checkpoint C session is a Windows-only
artefact, now verified.** On this Linux container `backtest/results/results.csv`
contains no CRLF bytes and `verify_append_only()` returns `verified: True` over
6 runs and 14 265 rows. No committed result is affected. The underlying
portability question — the hash chain reads raw bytes rather than git's
normalized view — is real and unfixed, and the two `@pytest.mark.skip` markers
are still in place because removing them is a `tests/` edit.

## 6. What this cycle did not do

It did not compute any price statistic, forecast, dispatch schedule, capture
ratio or error metric on 2025 data. It did not edit `data/entsoe.py`, any other
guard, any test, any model, any battery parameter or any metric definition. It
did not write a 2025 row into `results.csv`. What it touched: the price and
exogenous manifests and the contract report (rebuilt off the fresh pull, which
is the download record CLAUDE.md requires), one new runner, and this file.
