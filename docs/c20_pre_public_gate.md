# C20 — the pre-public gate, run after publication

**Status: the gate ran on 2026-11-22. It passes, after two fixes it made in the
course of running. It should have run on 2026-10-29 or earlier; it did not, and
this document is as much about that as about the findings.**

PLAN.md gives C20 one sentence:

> `gitleaks` secret scan; repo size / raw-data check; licence + attribution
> check; reproducibility check (fresh clone, cached-subset run); align README
> claims with actual results.

Five clauses, five phases of `backtest/run_c20_gate.py`, five committed
artefacts (`backtest/results/c20_*.json`). Everything below is readable from
those files; this document says what they mean and which of them a human still
has to decide something about.

## 0. Why this ran out of order, and what that changes

FLAG C-E-01: **the repository has been public since 2026-10-29**, at the owner's
instruction, outside Checkpoint E, which is the checkpoint that was meant to
decide it. The gate that was supposed to run *before* that had never run. So
this cycle ran it 24 days late, against a page the world could already read.

That changes what the gate is for. A pre-publication gate blocks a release. A
post-publication gate produces a list of things that are already true of a live
page, and the only useful response to a finding is to fix it now and say what it
was. That is what happened with the two attribution findings in §3.

It is also a deliberate departure from PLAN.md's cycle order — C17's holdout
evaluation comes first and is still blocked (NOTE C17-01). The 2026-11-22 cycle
left scheduled cycles an ordered instruction to run C20 rather than log another
wait entry if NOTE C17-01 was still unanswered. It was still unanswered. **The
human can veto this ordering**; nothing in it computes a 2025 number or touches
the holdout.

## 1. Secret scan — clean, 181 commits, 806 blobs

| | |
| --- | --- |
| commits scanned | **181** (the full history, not the container's 50-commit clone) |
| blobs scanned | **806** of 839, images skipped, `.csv.gz` decompressed first |
| bytes scanned | **352 MB** decompressed |
| findings | **0** |
| `detect-secrets` findings | 663, triaged: 661 expected hashes, 2 benign prose, **0 unresolved** |

Nothing in this repository's history is a credential. The 72 regex hits that
were allowed are the empty `.env.example` template and prose in `PROGRESS.md`
naming the environment variable; the allowance is pinned to those exact paths,
so the same text anywhere else is still a finding (tested by planting it in a
second file).

The 661 `Hex High Entropy String` findings are this project's provenance trail —
SHA-256 payload fingerprints in `data/manifest/`, 40-hex git SHAs and 16-hex
library fingerprints in `backtest/results/`. They are classified by *shape*, not
waved through by type: a high-entropy string at a results path that is not
hash-shaped is reported unresolved and fails the phase.

**NOTE C20-01 — PLAN.md names `gitleaks`, and `gitleaks` did not run.** The
release tarball downloads in this container (HTTP 200), but executing an ad-hoc
downloaded binary is refused by the environment's safety policy, and working
around that refusal is not something an unattended cycle should do. The phase
does the same job with two scanners that are installable and auditable instead:
`detect-secrets` 1.5.0 from PyPI over the tracked tree, and a project-specific
regex scan over every blob in every commit. The project-specific set is the one
with teeth here — the only credentials this project ever holds are
`ENTSOE_API_KEY` and `AGSI_API_KEY`, and an ENTSO-E security token is a UUID.
**A human should still run `gitleaks detect --source . --redact` locally**: it is
one command, it is PLAN.md's named tool, and a second independent rule set is
worth having on a repository that is already public.

## 2. Repo size and raw data — clean

| | |
| --- | --- |
| HEAD tree | 607 files, **71.7 MiB** |
| of which `backtest/results/` | 66.3 MiB |
| full history, blobs uncompressed | 163 MiB over 839 blobs |
| largest committed file ever | `results.csv`, 4.1 MiB |
| files at or over GitHub's 50 MiB warning | **0** |
| paths ever added matching `data/raw/`, `*.parquet` or a real `.env` | **0** of 608 |

CLAUDE.md's rule — never commit bulk raw data — holds across the whole history,
not just the current tree. That distinction matters: a raw pull committed in
March and deleted in April is still in the clone a reader gets today. It was
checked against every commit's *additions*.

`.gitignore` was probed rather than read: `git check-ignore` on eight paths that
must be ignored and four that must not. All twelve are right, including the one
rule that is easy to get backwards — `!.env.example`, the negation that decides
whether the key template ships. (The first version of this probe reported that
rule as a failure, because `check-ignore -v` prints the matching rule for a
negation too; the probe now reads the `!`.)

### The artefact-size decision NOTE C15-04 handed C20

C15 asked a real question: its per-day artefacts are ~37 MB against ~25 MB for
C1–C14 combined, because the ten forecast-shape columns are rung-invariant by
construction and are stored six times. Normalising them out would save ~40%.

**Decision: no. Keep every artefact exactly as the runner writes it.** Four
reasons, recorded in `c20_repo_size.json` so a later cycle does not have to
rediscover them:

1. The repo is nowhere near a real limit — no file reaches GitHub's 50 MiB
   warning, the tree is 72 MiB against a 1 GiB recommendation.
2. C15's own principle, which this gate agrees with: a committed artefact that
   does not match what the runner writes is worse than a large one.
3. Rewriting 51 artefacts would invalidate the reproduction evidence built on
   them — NOTE C15-04's 54 756-row check and §4's fresh-clone comparison both
   read those exact files.
4. It is a destructive rewrite of published numbers to save ~25 MB a reader will
   never notice, which is the class of change an unattended cycle should not
   make on its own.

Revisit if the tree passes ~500 MiB or a single artefact approaches 50 MiB.

## 3. Licence and attribution — two real findings, both fixed

This is the phase that found something, and what it found had been live on a
public page for 24 days.

**Finding 1 — the README carried no data attribution at all.** Not the
Energy-Charts one, not the ENTSO-E one, and no statement that the MIT licence in
`LICENSE` covers the code but not the data. `backtest/results/` is 66 MB of
derived Energy-Charts data and `docs/figures/` is 20 derived figures; CC BY 4.0
requires attribution wherever the material or an adaptation is distributed, and
the attribution existed only in `config/data.yaml`, in `docs/`, and inside the
figures themselves. An MIT banner over CC BY 4.0 data, with no attribution in
the file a reader actually reads, is the mistake.

**Fixed**: README now has a *Data sources, licence and attribution* section
naming both sources, both licences, and the fact that the derived artefacts are
derived works. The gate asserts the required tokens are present, so it cannot
silently disappear again.

**Finding 2 — three committed figures shipped with no attribution.** A figure
travels on its own: a reader who lifts a PNG out of `docs/figures/` has no
`config/data.yaml` to consult. 17 of the 20 figures bake the attribution into
the image; C15's three (`c15_capture_vs_throughput_cost.png`,
`c15_lever_effects.png`, `c15_friction_share_of_shortfall.png`) did not, because
`write_figures` never got the line the other modules have.

**Fixed**: `backtest/run_c15_sensitivities.py` now defines `ATTRIBUTION` from
`config/data.yaml`'s string and emits it on all three figures, and the three
PNGs were regenerated **from the committed tables** (`c15_rung_points.csv`,
`c15_friction_decomposition.csv`) — no number was recomputed and none moved.

The check behind both is worth stating because it has one deliberate piece of
slack: a figure's producing module passes if it emits every required token
(`Energy-Charts`, `Fraunhofer ISE`, `CC BY 4.0`), not if it emits
`config/data.yaml`'s string verbatim. C14's three figures use residual load as
well as prices and carry a *richer* line that names ENTSO-E too. A superset is
correct attribution, not drift, and a gate that failed it would be teaching the
next cycle to write a worse caption.

## 4. Reproducibility — an independent clone lands on the published numbers exactly

PLAN.md asks for a fresh clone and a cached-subset run. Three legs, because
"reproducible" means different things at different layers.

### Leg (a) — the committed artefacts agree with each other

NOTE C15-04's `check_baseline_reproduction` and `check_res_leg_reproduction`,
imported not re-written, over the whole committed C15 ladder. This is the
54 756-row check C15 already passed; running it again is cheap and it is the
thing that would break first if an artefact were edited by hand.

### Leg (b) — the price cache fingerprints

`verify_price_cache`, when a cache exists. An absent `data/raw/` is reported as
**not evidence**, never as a pass.

### Leg (c) — the fresh clone, which is the one that answers the reader's question

A clone of the public repository, taken anonymously, into a throwaway directory:

| | |
| --- | --- |
| clone HEAD | `7058c8b`, 181 commits, not shallow |
| environment | a new venv, resolved **freely from the clone's own `requirements.txt`** |
| resolved set | python 3.11.18, numpy 2.4.6, **pandas 3.1.1**, scikit-learn 1.9.1, scipy 1.17.1, lightgbm 4.7.0 |
| `library_fingerprint` | **`f4e33081974da285`** — neither the published `856fb19ac0c4eecd` nor this container's `00a12bd6aadb09f3` |
| data | its own Energy-Charts pull of DE-LU 2019–2023; **5 of 5 payload fingerprints match C1's committed manifest** |

Then a bounded recompute of DE-LU 2023 — the forecast layer (C13's walk-forward:
the comparable LEAR plus the naive floor) and the dispatch layer (C15's base
rung through C5/C6's rolling LP) — compared against **the committed blobs in the
clone's own git object store**:

| artefact | rows | numeric columns | worst absolute gap |
| --- | --- | --- | --- |
| `c13_year_DE-LU_2023_predictions.csv.gz` | 8 760 | 3 | **0.0** |
| `c13_year_DE-LU_2023_folds.csv` | 365 | 4 | **0.0** |
| `c15_main_DE-LU_2023_daily.csv.gz` (base rung) | 1 094 | 30 | **0.0** |

and, cross-cycle, the recomputed dispatch against **C13's** committed per-day
cash (`c13_daily_by_year.csv.gz`, 49 284 rows): worst cash gap
**4.27e-07 EUR**, worst oracle cash gap **4.98e-08 EUR**, `holds: true`.

Bit-identical in the forecast layer, bit-identical in the dispatch layer, and
within half a micro-euro of a different cycle's published file. A stranger with
this repository and a network connection gets the published numbers back.

### NOTE C20-02 — but that stranger is **not** reproducing the published environment, and `requirements.txt` is why

The clone resolved to **pandas 3.1.1**, not the 3.0.6 every published number was
produced under. `requirements.txt` declares floors on purpose (its own comment
explains why: pinning would freeze every future cycle), and the exact set lives
only in a prose comment at the bottom of that file and in
`c16_preregistration.json`.

For a public repository that offers reproducibility, that is a gap: a reader has
no single command that reconstructs the published environment. **Suggested fix,
not applied here because it is C17/C18's territory and should be one deliberate
change: commit a `requirements-published.txt` holding the five exact pins, and
point the README at it.** It freezes nothing — the floors stay where they are
for ordinary cycles — and it gives a reader the one thing they currently lack.

### What this says about NOTE C17-01, and what it does not

NOTE C17-01 asks the human whether the single pre-registered holdout evaluation
may run under CPython 3.11.18 instead of 3.11.17, with the five numerical
libraries at exactly their pinned versions. This cycle did not answer that
question and must not. But it produced evidence that bears on it:

> A **larger** library deviation than the one being asked about — a pandas
> *minor* version move, 3.0.6 → 3.1.1, on top of the same CPython patch
> difference — left every number bit-identical, in both the forecast layer
> (8 760 LEAR and naive predictions) and the dispatch layer (1 094 per-day rows
> across 30 columns).

Three limits on how far that carries, stated so nobody over-reads it:

1. **One zone, one year, one model class.** DE-LU 2023, the price-only
   comparable LEAR. LightGBM (C9) and the block bootstrap (C12) were not
   exercised, and the bootstrap is the component where a numpy RNG change would
   show up first.
2. **It is evidence about libraries, not about the pre-registration.** The gate
   that is blocking the holdout is a *pre-registration* gate: its point is that
   an unattended cycle must not decide a registered environment is close enough.
   That is still true, and the runner still refuses.
3. **It does not reduce the decision to a formality.** It makes option (a) look
   cheaper than it did, nothing more. The decision is the human's, and
   `docs/c17_environment.md` §4 is still the document for it.

## 5. README claims — aligned, and the alignment is now machine-checked

The README is still a build log, not C17's findings document, so the useful form
of this check is the inverse of the usual one. Two parts:

**No unbound number.** Every numeric token in the file must be a date, a
calendar year, a cycle reference, a licence version, a legal article, a filename
or a URL — or else be *bound*: named in a table that says which committed
artefact and which field it came from, and checked against it. There is one
bound claim today ("no secret in any of the 181 commits" →
`c20_secret_scan.json: history_scan.n_commits`), it agrees, and there are zero
unbound numbers.

**One consequence to know about before re-running the gate**: that count is the
history as the scan saw it, so the moment a later cycle re-runs
`--phase secrets` on a longer history the artefact moves ahead of the README and
the `claims` phase fails, naming both values. That is the intended behaviour —
a README quoting a stale measurement is exactly what this phase is for — but it
means **re-running the gate and updating that one number go together**. **That table is the thing C17's README rewrite has to grow**: a
findings README quoting a capture ratio adds a row, and the gate re-reads it.

**The factual claims, against artefacts rather than prose.** Three, and the
first has teeth:

| claim | checked against | verdict |
| --- | --- | --- |
| the 2025 holdout has not been evaluated | `results.csv` `evaluation_years` (2020–2024, no 2025) **and** `c17_holdout_run_ledger.json` (no completed holdout entry) | holds |
| the pre-public gate has not run | ≥4 `c20_*.json` artefacts now exist, so the README must no longer say it | holds (the sentence was updated this cycle) |
| the repository is public since a stated date | the log records the flip (FLAG C-E-01) | holds |

## 6. What the gate changed, and what it did not

Changed:

- `README.md` — a new *Data sources, licence and attribution* section, and the
  status block rewritten to say the gate has now run, after publication, with a
  pointer to this file.
- `backtest/run_c15_sensitivities.py` — an `ATTRIBUTION` constant and three
  `fig.text` calls; the three C15 figures regenerated from committed tables.

Not changed, and deliberately: **no result, no metric, no model, no battery
parameter, no config, no data contract, nothing under `tests/` that existed
before this cycle, and nothing in `results.csv`.** The gate imports no
`append_rows` and defines no `ResultRow`; a test asserts that statically, because
a measurement phase that grew into a producer of result rows would be a quiet
way to put an unreviewed number into the store.

## 6b. The suite, and FLAG C20-01

**972 passed, 7 skipped, 5 failed.** The expected red is FLAG C17-03's fingerprint test,
which must stay red until NOTE C17-01 is answered. The other four are new to *this*
container and are **not** this cycle's doing — a pristine `git worktree` at `7058c8b`, with
none of these changes in it, fails the same five in 2.6 seconds:

| test | expects | raised here |
| --- | --- | --- |
| `test_c13_regime.py::test_2025_now_passes_the_holdout_guard_in_regime_price_table` | `SealedHoldoutError` → fail, `RegimeError` → pass | `data.prices.PriceDataError` |
| `test_c14_fundamentals.py::test_2025_now_passes_the_holdout_guard_in_fundamentals_frame` | same shape, `ExogenousDataError` | `data.prices.PriceDataError` |
| `test_c14_fundamentals.py::test_2025_now_passes_the_holdout_guard_in_headroom_frame` | same | `data.prices.PriceDataError` |
| `test_c15_sensitivities.py::test_dispatching_the_sealed_year_raises_before_any_path_is_built` | `(SealedHoldoutError, SensitivityError)` | `data.prices.PriceDataError` |

One cause: `PriceDataError` ("no cached price files for DE-LU") is in none of their
`except` / `pytest.raises` tuples, and `data/raw/` does not survive a container
(NOTE C2-02). The first three are three of the six C17 rewrote under J.'s §5(b) approval,
whose new docstrings claim the rewrite "holds in a container with the cache and in one
without it" — not true as written, and only ever exercised in a container that had just
fetched 2025.

**Nothing about the seal is wrong**, checked directly rather than inferred: `sealed_years()`
is still `{2025}`, `holdout_is_unsealed()` is still `True`, and
`assert_not_sealed({2025}, ...)` returns without raising — exactly the post-Checkpoint-C
state those four tests exist to assert. They fail before they can reach it.

**Not fixed here.** One line each would do it, ideally with the project's own idiom —
`pytest.skip("the price cache is not present in this working tree")`, already used at
`test_c14_fundamentals.py:701` and `test_c17_preflight.py:156/169` for precisely this — but
it is an edit under `tests/`, and CLAUDE.md requires a FLAG and a stop for human review
first. J.'s §5(b) approval named six tests and does not extend to a seventh edit of them.

## 7. What a human still has to do

1. **Decide FLAG C20-01** — four tests are red in any container without a price cache,
   for one trivial reason, and the fix is a `tests/` edit that needs approval. §6b.
2. **Run `gitleaks detect --source . --redact` locally** (NOTE C20-01). One
   command, PLAN.md's named tool, a second rule set.
3. **Decide NOTE C17-01** — still the only thing blocking the holdout, and still
   `docs/c17_environment.md` §4. §4 above is evidence for it, not an answer to
   it.
4. **Decide NOTE C20-02** — whether to commit a `requirements-published.txt`
   with the five exact pins so a reader can reconstruct the published
   environment in one command.
5. **Checkpoint E is already spent.** The repository is public; the gate that was
   meant to precede that has now run and passes. There is nothing left for an
   agent to do about the ordering, and nothing an agent should do about repo
   visibility ever.
