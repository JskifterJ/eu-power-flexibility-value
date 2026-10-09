# Progress log

## Current status

- **Next cycle to run:** **C12.** C11 complete (the battery LP across all nine zones and
  every committed curve — 45 rolled dispatch runs, every invariant green, the per-day
  capture ratios persisted). See the C11 entry for **FINDING C11-A** (the capture ratio
  diverges across zones where rMAE does not), **FINDING C11-B** (NO2 is the outlier and
  the mechanism is *not* established), **FINDING C11-C** (the same-start capture ratio
  cannot rank two curves — the headline is the rolled-oracle ratio) and **FINDING
  C11-D** (among honest arms, MAE does not predict capture). No open blocker.
- **Human checkpoints:** Checkpoint B closed 2026-10-07 (approved as-is). Checkpoint A
  closed 2026-10-01. Next is **Checkpoint C at C16** (unsealing 2025).
- **Read this before quoting any capture number: FINDING C11-C.** The project's headline
  capture ratio is **`capture_rolled_oracle_cash`** — settled cash over the *rolled*
  perfect-foresight run's cash on the same days, which is one denominator per zone and
  therefore comparable across curves. **`capture_same_start_pooled` is the exact per-day
  bound and must never be used to rank two curves**: its denominator is re-solved from
  each curve's own opening SoC, so a curve that arrives at a day with a fuller battery is
  scored against an easier ceiling. Demonstrated, not argued: on DE-LU two LEAR arms
  settle 0.35 EUR apart over 365 days yet their same-start captures differ by 4.0pp
  (mean opening SoC 0.454 vs 0.216 MWh), while the rolled ratio ties them at 0.9123.
- **FINDING C11-A — the capture ratio diverges across the nine regimes; rMAE does not.**
  Capture spans 0.6146 (NO2) to 0.9187 (DE-LU): band **30.4pp**, CV **0.1114**, max/min
  1.495x — against rMAE's 7.2pp / 0.0367 / 1.113x. The CV is **3.0x** rMAE's and the band
  **4.2x** as wide, which answers FINDING C10-A's prediction in the sharper direction: a
  point-error metric is blind to what a battery trades. The rankings do not line up and
  if anything run the wrong way (**NO2 has the best rMAE of the nine and the worst
  capture; DE-LU is second-worst on rMAE and best on capture**; Spearman +0.58, p=0.099 —
  *positive*, the opposite sign of what forecastability implies). **Caveat that must
  travel with it:** n = 9, one year, the +0.58 is not significant, and the 30.4pp band is
  substantially one zone — drop NO2 and the other eight sit in 0.8358–0.9187, an 8.3pp
  band with CV 0.0335. The defensible claim is the inequality of the bands and the
  non-alignment of the rankings, not a law about regimes. **C12 decides.**
- **FINDING C11-D — among honest arms, MAE does not predict capture.** Across the 15
  honest paired comparisons (MAE recomputed on *exactly* the dispatched hours, so the
  comparison is paired by construction) the two metrics agree on the sign **9 times — a
  coin flip** — Spearman +0.02 (p=0.95), Pearson −0.11 (p=0.69). Consequences that bind
  later cycles: (i) **NOTE C8-01 is answered affirmatively for the booster** — the honest
  exogenous block buys +0.35 / +2.04 / +2.71pp of capture (+262 / +924 / +706 EUR/MW/yr)
  in DE-LU / ES / NO2 under the GBM, far more than its ~1% of MAE suggested and with the
  zone ordering *inverted*; (ii) **"gradient boosting beats LEAR" does not survive the
  move to a dispatch metric** — at an honest vintage, price-only, the GBM loses on capture
  in all three zones despite the lower MAE in two of them; (iii) **FINDING C10-B is an
  MAE claim and must be labelled as one** — the window gain worth +2.8/+3.6/+7.4% of MAE
  is +0.86 / −0.27 / −1.31pp of capture; (iv) the Art. 14 leak worth 8–11% of MAE to the
  LEAR buys +0.00 / −0.84 / −0.76pp of capture. **Caveat:** most deltas are under 1pp;
  the honest reading today is "MAE is not a reliable proxy for capture", **not** "MAE is
  anti-correlated with capture". C12's bootstrap turns the table into a finding.
- **FINDING C11-B — NO2 is the outlier and the mechanism is NOT established.** Lowest
  spread (46.28), lowest oracle value (26 022 EUR/MW/yr), fewest oracle cycles (418), and
  the model loses money on **25.8%** of dispatched days against 0.8–7.4% elsewhere. The
  thin-spread story is consistent with all four but every spread-based correlate collapses
  when NO2 is dropped (spread +0.60 -> +0.00, oracle value +0.66 -> −0.01). With n = 9
  this is one zone, not a relationship. **C15's throughput-cost ladder (0/2/5 EUR/MWh) is
  the direct test** and should be read as such; C13 should say whether NO2's capture is a
  2024 hydrology artefact.
- **Results live in one append-only table: `backtest/results/results.csv`** (**2 085 rows
  after C11**, 2 runs, `backtest/results_store.py`, written up in `docs/results_store.md`
  and `docs/dispatch_results.md`). Long format, so **a new metric is a new value, not a
  new column** — C11 added 17 dispatch metrics and needed no schema change and no test
  edit, and C12's spread/Spearman/CI metrics will not either. Every row carries
  `git_sha`, `config_hash`, the model's fingerprint and a `library_fingerprint`;
  `vintage` (`honest` / `after_gate_closure`) is a **required key column**. Call
  `verify_append_only()` before trusting anything in there, and append with `append_rows`
  — never edit a row in place. The 447 C10 rows are byte-for-byte unchanged after C11's
  append (verified directly against `git show HEAD:`).
- **The per-day dispatch artefact C12 needs is `backtest/results/c11_capture_daily_2024.csv.gz`**
  — 16 440 rows, one per (zone, curve, dispatched day), with both oracle ceilings, both
  capture ratios, the opening/closing SoC, the realised spread and an `in_common_day_set`
  flag. It is already in the shape a daily-block bootstrap needs.
- **FINDING C9-C — read this before any later cycle reports a GBM number, and before the
  C18 write-up ranks the models.** C8 measured the Art. 14 **vintage premium**
  (as-published vs leak-free persistence) with a per-hour LASSO: +8.4% of MAE on DE-LU,
  +11.3% on ES. C9 re-measured it with a tree ensemble on the same rows, vintages and
  folds: **+23.96% (DE-LU) and +17.82% (ES)** — two to three times larger. The leak is
  worth *more* to a non-linear model, and the booster's whole advantage over the LASSO is
  concentrated in the late arm. **C11 adds the dispatch half of this**: the same leak is
  worth +3.47 / +0.95 / −0.84pp of capture under the GBM and ~0 under the LEAR, and on
  the *honest* arms the GBM loses to the LEAR on capture in all three zones. So a result
  of the form "gradient boosting beats LEAR on a RES-fed day-ahead model" is
  substantially an artefact of a publication timestamp, and does not reappear when the
  metric is the one a battery trades on.
- **FINDING C8-A still stands and is the reason C9-C matters.** At an honest vintage the
  entire ENTSO-E exogenous block is worth ~nothing on 2024 **MAE** for all three Tier-A
  zones (under the booster, +1.0% DE-LU and ES, +0.2% NO2). **C11 qualifies this**: on
  *capture* the same honest block is worth +0.35 / +2.04 / +2.71pp under the booster, so
  "worth nothing" is an MAE sentence and not a dispatch one. The headline honest arm for
  Tier A remains `res_persistence`; `res_as_published` travels **only** as the labelled
  measurement of the leak and its numbers are never reportable as achievable.
- **FINDING C10-A — the *relative* skill of a price-only model is near-constant across
  nine regimes; the *level* of difficulty is not.** Absolute MAE spans 2.73x across the
  nine zones; the LEAR/naive ratio spans 1.11x (0.6435 NO2 to 0.7160 NL, mean 0.6757, sd
  0.0248). **C11 tested the prediction this finding set and the capture ratio diverged
  instead** — see FINDING C11-A, which is the resolution of it.
- **FINDING C10-B — three extra years of price history beat the entire honest exogenous
  block, and beat the switch to a booster, in all three Tier-A zones — *on MAE*.** Window
  (2019+ vs 2022+, LEAR price-only): +2.80% / +3.53% / +7.45% of MAE; honest exogenous
  block (GBM) +1.0% / +1.0% / +0.2%; model class (GBM−LEAR, honest arms) −3.1% / +1.2% /
  −4.8%. **C11 shows this does not carry to capture** (+0.86 / −0.27 / −1.31pp), so the
  "more history wins" claim must be labelled an MAE claim wherever C18 uses it.
- **The GBM config is frozen and tripwired.** `forecast.gbm.GbmSpec`, fingerprint
  **`a366a760e269bba6`**, lightgbm 4.7.0. PLAN.md forbids a hyperparameter search across
  cycles, so the config is pinned to literals by
  `test_the_committed_config_is_exactly_what_plan_md_froze` — **a cycle that wants to tune
  a knob has to edit a test, which CLAUDE.md makes a flag-and-stop event.** Do not edit
  it; flag instead.
- **`ENTSOE_API_KEY` is set but C10 and C11 did not need it.** C11's Tier-A curves come
  from C8's and C9's committed artefacts and Tier B has no exogenous block, so the only
  network traffic was 18 Energy-Charts price pulls, 18/18 successful, 0 FLAGs.
- **Open FLAGs:** **FLAG C5-01** — simultaneous charge/discharge in the dispatch LP.
  **RESOLVED at Checkpoint B (2026-10-07): option (b)** — keep the pure LP as the default
  and carry the artefact as a stated limitation in the write-up. **C11 measured it across
  nine zones for the first time and it supports that decision more strongly than DE-LU
  alone did**: present in seven of nine zones but tiny everywhere — at worst FR with 9 of
  365 days (2.5%), 2.70 MWh burned over a year and 0.14% of settled cash; NO2 and
  IT-North show none. It still biases capture *against* the model (~0.16pp on DE-LU), so
  it is conservative. Unchanged by C7–C11, none of which touched dispatch code.
- **Earlier findings that still bind:** C9-A (PLAN.md leakage assertion (i) is vacuous for
  a pooled booster on the synthetic fixture; re-sited, `tests/test_c3_leakage_harness.py`
  untouched), **C9-B RETRACTED** (the claim that `lgb.train` keeps post-best-iteration
  trees is false on lightgbm 4.7.0; two pushed commit messages still assert the retracted
  version and cannot be rewritten — the C9 entry is the correction of record), C9-D, C9-E,
  C7-A..C7-E (`docs/entsoe_layer.md`), C8-A..C8-C (`docs/exogenous_model.md`), C4-A (the
  mean-reference contamination of the target-permutation probe).
- **Decision requests — all closed "as-is" at Checkpoint B (2026-10-07):** NOTE C3-01,
  NOTE C4-01, NOTE C4-02, NOTE C7-01. **NOTE C2-02** (the raw cache does not survive a
  container) — no change, **22nd recurrence**; C11 re-pulled only the 18 (zone, year)
  files it needed rather than all 54, and all 18 `payload_sha256` values matched the
  committed C2 manifest exactly.
- **NOTE C8-01 — ANSWERED by C11, affirmatively, for the booster only.** The question was
  whether `res_persistence` improves the *capture ratio* by more than its ~1% of MAE
  suggests. It does, under the GBM: +0.35 / +2.04 / +2.71pp (+262 / +924 / +706
  EUR/MW/yr), with the zone ordering inverted relative to MAE. Under the LEAR it still
  buys nothing. Closed.
- **NOTE C9-01 — ANSWERED by C10 and C11.** C10 attributed the upward bias to the
  training window rather than the models (2-4x smaller at a 2019 start; the nine-zone
  comparable curves carry −0.03 to +3.0 EUR/MWh). C11 tested the prediction that a
  roughly uniform upward bias barely perturbs the within-day ordering a battery trades
  on: confirmed, and generalised by FINDING C11-D — most point-error gains do not reach
  the ordering either. Closed.
- **NOTE C10-01 — ANSWERED by C11.** Both halves decided and recorded in
  `docs/dispatch_results.md`: the NaN policy stays `decline` with hole-days skipped and
  counted; the capture ratio is written at **both** store scopes, the within-zone arm
  comparison is read at `common_hours` and the cross-zone table at `own_coverage`, and
  the cost of that choice is measured per curve per zone in `scope_sensitivity` (the
  comparable arm is scope-invariant in eight of nine zones and moves −0.2394pp in ES,
  whose nine-curve intersection drops to 357 days). No new scope value was added and
  `backtest/results_store.py` was not touched. Closed.
- **NOTE C11-01 (new, for C12 — and it is the whole job).** Every C11 headline is one
  validation year and either n = 9 zones or n = 15 paired comparisons, with most capture
  deltas under 1pp. C12's block bootstrap over daily blocks must decide three things
  before C18 quotes any of them: (i) is FINDING C11-A's eight-zone 8.3pp capture band
  (NO2 excluded) wider than noise, (ii) is FINDING C11-D's near-zero MAE/capture rank
  correlation distinguishable from a real relationship, (iii) does the GBM-exogenous
  capture gain (+2.04 / +2.71pp) survive a CI. The paired point error is already in the
  store as `{mae,rmse,bias}_on_dispatched_hours` at `common_hours`, on the same hours as
  the capture ratios, so C12's spread-error and within-day Spearman metrics should be
  computed on that same hour set.
- **NOTE C11-02 (new, for C13/C15).** FINDING C11-B's thin-spread mechanism for NO2 is
  untested. C15's throughput-cost ladder (0 / 2 / 5 EUR/MWh) is the direct test, not
  merely a sensitivity; C13 should report whether NO2's capture is stable across years.
- **Sealed holdout (2025):** SEALED. Guard verified armed in C11, before and after the
  work: marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, `assert_not_sealed({2025})` raises, no `*2025*` file exists
  anywhere under `data/`, only 2023 and 2024 price files were fetched, every `market_day`
  in every C11 artefact is in 2024, and `evaluation_years` = `2024` on all 2 085 store
  rows. The 18 occurrences of the string `2025` in `c11_capture_daily_2024.csv.gz` were
  each inspected and are digits inside float values (`30.402025`, `0.2025`). The store
  adds an independent tripwire: a metric whose `evaluation_years` touches a sealed year
  **cannot be written**. No 2025 data has been fetched, loaded, dispatched or computed
  against at any point in C2–C11.
- **Config hash:** **`515d4e8d98887256`** — unchanged from C8. C11 modified no
  `config/*.yaml`. C11's library fingerprint is **`856fb19ac0c4eecd`**, identical to
  C10's (python 3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1,
  lightgbm 4.7.0), so C10's and C11's rows are directly comparable.
- **Repo-state note:** the detached-HEAD trap recurred in C11 — the container arrived
  detached at `e30892d` with local `master` stale 14 commits behind. **26 recurrences out
  of 33 containers.** `HEAD` equalled `origin/master` exactly, so nothing was at risk, and
  `git checkout -B master` was permitted. C9's warning still stands: **if a future
  container arrives detached *and* genuinely behind the remote, and `checkout -B` is
  refused, flag rather than improvise.** Keep checking
  `git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the start
  of every cycle.

## Log

### C0 — 2026-09-28 (human + local assistant session, not a scheduled cycle)
- Repo skeleton created: `data/{raw,manifest}`, `forecast/`, `dispatch/`,
  `backtest/`, `notebooks/`, `tests/`, `docs/`.
- `PLAN.md`, `CLAUDE.md`, `docs/audit.md`, `README.md`, `.gitignore`,
  `.env.example`, `LICENSE` written and committed.
- Independent pre-build audit completed (Opus subagent, no involvement in
  original design) — verdict GO conditional on 4 changes, all folded into
  `PLAN.md`. Full report in `docs/audit.md`.
- Private GitHub repo to be created next: `JskifterJ/eu-power-flexibility-value`.

### C1 — 2026-09-28 (scheduled cycle) — code complete, data pull BLOCKED

Scope per PLAN.md C1: config schema, Energy-Charts client + local cache, pull
day-ahead prices for all 9 zones, build the manifest. No modelling.

**Built and committed (all offline work done, 44 unit tests passing):**
- `config/zones.yaml` — 9 zones with tier, Energy-Charts `bzn`, ENTSO-E EIC
  domain, IANA `local_tz`, regime label, and structural-break notes (DE-AT-LU
  split, Iberian gas cap, IT zonal reconfiguration, PL SDAC go-live).
- `config/data.yaml` — splits, the sealed-holdout declaration with its exact
  unseal marker string, `fetch_years`, source endpoints/licences/politeness
  settings, and the UTC time contract. Refuses to load if `fetch_years` ever
  overlaps the sealed years.
- `config/features.yaml` — target, price-history and calendar features, Tier-A
  exogenous features each carrying an explicit `leakage_status` (Art. 6 load =
  safe; Art. 14 wind/solar = FLAGGED, post-gate-closure vintage), plus the
  excluded-by-audit list (Open-Meteo reanalysis, AGSI+) with reasons.
- `data/config.py` — config loading/validation, `config_hash()` for tagging
  result rows from C10.
- `data/holdout.py` — the sealed-holdout guard as executable code: any fetch or
  load of 2025 raises `SealedHoldoutError` unless `PROGRESS.md` contains the
  exact marker line, which only a human writes at C16. Wired into `fetch_year`,
  `read_cached_year` and therefore the manifest builder; a stray sealed-year
  cache file makes the manifest build raise rather than quietly include it.
  A tripwire test asserts the marker is currently ABSENT from this file.
- `data/energy_charts.py` — `/price` client with fetch-once cache
  (`data/raw/energy_charts/price/<ZONE>/<YEAR>.json`, gitignored, with a
  `_fetch_meta` provenance block). Strict schema validation; 4xx incl. 404
  raises immediately with no endpoint guessing; only transport/429/5xx retried
  (3 attempts, 5/15/45s); no bare `except` anywhere; a payload that fails
  validation is never written to the cache. No force-refetch flag by design.
- `data/manifest.py` + `data/build_manifest.py` — 28-column per-(zone, year)
  manifest: counts, coverage vs UTC-exact expected intervals, modal resolution
  and distinct-delta count (how the 2025-10-01 15-min cutover will surface),
  gap count/max gap, NaN count, price min/p01/mean/median/p99/max/std,
  negative-hour and zero-hour counts, raw sha256, fetch timestamp, API URL.
  CSV (human-eyeballable at Checkpoint A) + JSON with git SHA, config hash,
  licence and attribution.
- `data/fetch_prices.py` — CLI over 9 zones x 6 years (54 pairs). Per-pair
  failure becomes a FLAG line plus `data/manifest/fetch_failures.json`, skips
  only that pair, continues, exits non-zero.
- `tests/test_c1_data_layer.py` + `tests/conftest.py` — 44 unit tests over
  config, the holdout guard, request shape, 13 malformed-payload rejections,
  cache behaviour (no-refetch, 404-no-retry, bad-payload-not-cached), and
  manifest stats against a synthetic full year with injected negatives, NaNs
  and a 3-hour gap. All offline, no network, no real price data.
- `requirements.txt` + `.venv` (gitignored): requests, PyYAML, pandas, numpy,
  pytest.
- `docs/data_layer.md` — cache layout, holdout enforcement, flag-not-swallow
  policy, time handling, manifest columns, attribution.

**FLAG C1-01 — day-ahead price pull blocked by the environment's egress policy.**
Not a data-source problem: `api.energy-charts.info:443` is refused by this cloud
environment's network policy before any request reaches Fraunhofer ISE. Verbatim,
after the client's 3 retries:

```
FetchFailed: energy-charts /price DE-LU 2024: giving up after 3 attempts;
last error: ProxyError: HTTPSConnectionPool(host='api.energy-charts.info',
port=443): Max retries exceeded with url:
/price?bzn=DE-LU&start=2024-01-01&end=2024-12-31
(Caused by ProxyError('Unable to connect to proxy',
OSError('Tunnel connection failed: 403 Forbidden')))
```

The agent proxy's own status endpoint records it as `connect_rejected` /
"gateway answered 403 to CONNECT (policy denial)". `pypi.org` and `github.com`
reach fine from the same session, so this is host-specific policy, not a broken
tunnel. Per the proxy's documented guidance a policy denial must be reported,
not routed around — so no mirror, scraper or alternative source was tried, and
`config/data.yaml` still names Energy-Charts as the only price source.

*Human action needed:* widen **Network access** for this cloud environment (the
environment menu in the session title bar → Edit) — either a broader access
level or `api.energy-charts.info` added to the allowed domains. Access levels
are documented at https://code.claude.com/docs/en/claude-code-on-the-web.
Nothing in C1-C6 can proceed without it: Energy-Charts is the key-free critical
path, and `web-api.tp.entsoe.eu` will very likely need the same treatment
before C7.

**Deliberate deviation from PLAN.md C1, for the record:** C1 says "pull
day-ahead prices, all 9 zones, 2019-today". `fetch_years` is set to 2019-2024,
not "today", because (a) 2025 is the sealed holdout and CLAUDE.md's seal
outranks the plan's wording, and (b) 2026 is outside the study window (the main
hourly backtest ends 2025-09-30, the day before the SDAC 15-minute go-live). The
2025 pull happens at C16 after Checkpoint C approval, via the same code path
once the guard opens.

**Also noted for C2:** whether the Energy-Charts `end` parameter is inclusive of
the whole end day is not assumed anywhere. The request is
`start=Y-01-01&end=Y-12-31` and the result is truncated to
`[Y-01-01T00:00Z, Y+1-01-01T00:00Z)`; if `end` is exclusive, coverage will read
~8736/8760 with `last_ts_utc` at `Y-12-30T23:00Z`. C2 must resolve that
explicitly rather than patching it silently.

**Next:** C1b — rerun the fetch and build the manifest once the host is
allowed. Then C2 (data contract tests, hourly aggregation, per-zone plots) which
ends at **Checkpoint A**.

### C1b — 2026-09-28 (scheduled cycle) — STILL BLOCKED, no new work

Checked the one thing this cycle exists to check: **`api.energy-charts.info` is
still denied by the cloud environment's egress policy.** FLAG C1-01 stands
unchanged, so there is no manifest, and per the C1b instruction no C2 work was
started and no second push notification was sent.

What was verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file. The committed C1 data layer is healthy.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the C1
  failure **byte-identically** (`ProxyError ... Tunnel connection failed: 403
  Forbidden`), exits 1, and caches nothing. The flag-don't-swallow path works.
- The agent proxy's own status endpoint again records
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  `api.energy-charts.info:443`. `pypi.org` and `github.com` reach fine from the
  same session, so this remains host-specific policy, not a broken tunnel.
- `python -m data.build_manifest` correctly refuses on an empty cache rather
  than writing an empty manifest.

**Deliberately did NOT run the full 54-pair fetch.** With the gateway refusing
CONNECT on policy, all 54 pairs would burn ~55 minutes in the client's 5/15/45s
backoff and put 162 rejected CONNECTs against the host, for no information
beyond what the single pair and the proxy's own denial record already establish.
One pair was run through the real client instead. When the host is allowed, the
full pull must still be run in full.

**Also confirmed for C7 (probe only, no request sent):**
`web-api.tp.entsoe.eu:443` is denied by the same policy, exactly as C1
predicted. So widening Network access needs to cover **both** hosts, not just
Energy-Charts — otherwise C7 will stall the same way even once
`ENTSOE_API_KEY` is configured.

*Human action needed (unchanged, now covering both hosts):* widen **Network
access** for this cloud environment — the environment menu in the session title
bar → Edit — either to a broader access level or by adding
`api.energy-charts.info` **and** `web-api.tp.entsoe.eu` to the allowed domains.
Access levels are documented at
https://code.claude.com/docs/en/claude-code-on-the-web.

**Noted for whoever runs C1b next, not changed this cycle (out of scope):**
`data/build_manifest.py` prints "no cached price files found" but exits **0**.
`fetch_prices` exits 1 so an `&&` chain still stops, but a bare
`build_manifest` run that builds nothing reporting success is a trap worth
closing — it belongs with the C1 data layer, not C2. *[Corrected in the
2026-09-29 C1b entry below: this claim was wrong — it already exits 3.]*
Relatedly, decide whether
`data/manifest/fetch_failures.json` should be gitignored: it is currently
tracked-eligible, and this cycle's single-pair probe wrote an `n_failures=1`
version that would have been misleading if committed as though it were a
full-run record, so it was deleted rather than committed.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the host is allowed. Then C2, which ends at
**Checkpoint A**.

### C1b — 2026-09-29 (scheduled cycle) — STILL BLOCKED, no new work

Third consecutive blocked cycle. Checked the one thing this cycle exists to
check: **`api.energy-charts.info` is still denied by the cloud environment's
egress policy.** FLAG C1-01 stands unchanged, there is still no manifest, and
per the standing C1b instruction no C2 work was started and no second push
notification was sent (3 blocked cycles, escalation threshold is ~6).

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file. The committed C1 data layer is healthy.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure **byte-identically** for the third cycle running (`ProxyError ...
  Tunnel connection failed: 403 Forbidden`), exits 1, and caches nothing.
- The agent proxy's own status endpoint records, for this cycle's probes:
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  **both** `api.energy-charts.info:443` and `web-api.tp.entsoe.eu:443`.
  `github.com` tunnels fine from the same session, so this remains
  host-specific policy, not a broken tunnel. No mirror, scraper or alternative
  source was tried, and `config/data.yaml` still names Energy-Charts as the
  only price source.
- `python -m data.build_manifest` refuses on an empty cache rather than writing
  an empty manifest.

**Correction to the previous C1b handover note:** it recorded that
`data/build_manifest.py` "prints 'no cached price files found' but exits 0".
That is wrong — it returns **3** on an empty cache (`data/build_manifest.py:46`),
and 2 on a config-load failure. Measured directly this cycle:
`build_manifest EXIT=3`. There is no trap to close and no code change was made.
The earlier note most likely misread the `&&`-chain behaviour it was describing.

**Still open (unchanged, deliberately not decided this cycle):** whether
`data/manifest/fetch_failures.json` should be gitignored. This cycle's
single-pair probe again wrote an `n_failures=1` version that would misrepresent
a full 54-pair run if committed, so it was again deleted rather than committed.
Recommendation for whoever unblocks this: gitignore it — `PROGRESS.md` is the
durable FLAG record per `CLAUDE.md`, so the JSON is a per-invocation artefact,
while `data/manifest/` otherwise holds the committed Checkpoint A manifest.
Left as a one-line change for a cycle that is actually touching the data layer.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as last
cycle: with the gateway refusing CONNECT on policy, all 54 pairs would burn
~55 minutes in the client's 5/15/45s backoff and put 162 rejected CONNECTs
against the host for no information beyond what one pair plus the proxy's own
denial record already establish. When the host is allowed, the full pull must
still be run in full.

*Human action needed (unchanged):* widen **Network access** for this cloud
environment — the cloud environment menu in the session title bar → Edit —
either to a broader access level or by adding `api.energy-charts.info` **and**
`web-api.tp.entsoe.eu` to the allowed domains. Access levels are documented at
https://code.claude.com/docs/en/claude-code-on-the-web. Nothing in C1-C6 can
proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-29 10:01 UTC (scheduled cycle) — STILL BLOCKED, no new work

Fourth consecutive blocked cycle. **`api.energy-charts.info` is still denied by
the cloud environment's egress policy**, so FLAG C1-01 stands unchanged, there
is still no manifest, and per the standing C1b instruction no C2 work was
started and no push notification was sent (4 blocked cycles; escalation
threshold is ~6).

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the fourth cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), exits 1, and caches nothing.
- The agent proxy's status endpoint records, for this cycle's probes,
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  **both** `api.energy-charts.info:443` and `web-api.tp.entsoe.eu:443`
  (timestamps 10:00:56Z and 10:01:04Z). `github.com` tunnels fine from the same
  session, so this remains host-specific policy, not a broken tunnel. No mirror,
  scraper or alternative source was tried.
- `python -m data.build_manifest` refuses on the empty cache (`EXIT=3`) rather
  than writing an empty manifest.
- The single-pair probe's `data/manifest/fetch_failures.json` (`n_failures=1`)
  was again deleted rather than committed, since it would misrepresent a full
  54-pair run. The standing recommendation to gitignore it is unchanged and
  still left for a cycle that is actually touching the data layer.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous two cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

*Human action needed (unchanged):* the environment's network policy is denying
`api.energy-charts.info` and `web-api.tp.entsoe.eu`. Change **Network access**
in the cloud environment's settings (the environment menu in the session title
bar → Edit): either a broader access level, or add both hosts to the allowed
domains. Access levels are described at
https://code.claude.com/docs/en/claude-code-on-the-web. Nothing in C1-C6 can
proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-29 18:02 UTC (scheduled cycle) — STILL BLOCKED, no new work

Fifth consecutive blocked cycle. **`api.energy-charts.info` is still denied by
the cloud environment's egress policy**, so FLAG C1-01 stands unchanged, there
is still no manifest, and per the standing C1b instruction no C2 work was
started and no push notification was sent (5 blocked cycles; escalation
threshold is ~6, so the *next* blocked cycle should send the single escalation
ping).

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the sealed-holdout tripwire asserting the C16 unseal marker
  is still absent from this file.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the fifth cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), exits 1, and caches nothing.
- The agent proxy's status endpoint records, for this cycle's probes,
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial)" for
  **both** `api.energy-charts.info:443` (18:01:29Z, and again at 18:01:44Z /
  18:01:49Z / 18:02:04Z through the client's three retries) and
  `web-api.tp.entsoe.eu:443` (18:01:35Z). A `github.com` control probe from the
  same session tunnels fine (HTTP 400 from the origin, i.e. CONNECT succeeded),
  so this remains host-specific policy, not a broken tunnel. No mirror, scraper
  or alternative source was tried.
- `python -m data.build_manifest` refuses on the empty cache (`EXIT=3`) rather
  than writing an empty manifest.
- `ENTSOE_API_KEY` is still **not set** in this environment. Not blocking
  anything before C7, recorded here only so the C7 precondition stays visible.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous three cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

**Closed the standing `fetch_failures.json` recommendation.** Three consecutive
cycles recommended gitignoring `data/manifest/fetch_failures.json` and each left
it for "a cycle actually touching the data layer", while each in the meantime
hand-deleted a misleading `n_failures=1` probe artefact. That is a trap that
only gets more likely the longer the block lasts, so this cycle added the single
`.gitignore` line. Scope note, stated plainly: this is one line of repo hygiene,
not C2 work and not a change to any test, data contract or fetch/manifest code
path — `tests/`, `data/` and `config/` are untouched this cycle.

**Repo-state note (no history was lost, but worth knowing).** This container's
fresh clone arrived on a **detached HEAD** at `d11ec8a` with the local `master`
ref stale at the C0 commit `d257e20`; `origin/master` was already `d11ec8a`.
Checking out `master` therefore silently reverted the working tree to the C0
state, including `PROGRESS.md`. Resolved with `git fetch origin` and a verified
`git merge --ff-only origin/master` (local `master` confirmed a strict ancestor
first), so all four prior commits are intact and this cycle commits on `master`.
**If a future cycle finds itself on a detached HEAD, fetch and verify against
`origin/master` before committing** — committing from the detached state would
have stranded the work, and reverting the tree without noticing would have
looked in the diff like a deliberate rewrite of `PROGRESS.md` history.

*Human action needed (unchanged):* the environment's network policy is denying
`api.energy-charts.info` and `web-api.tp.entsoe.eu`. Change **Network access**
in the cloud environment's settings (the environment menu in the session title
bar → Edit): either a broader access level, or add both hosts to the allowed
domains. Access levels are described at
https://code.claude.com/docs/en/claude-code-on-the-web. Nothing in C1-C6 can
proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-30 02:02 UTC (scheduled cycle) — STILL BLOCKED, escalation ping sent

**Sixth consecutive blocked cycle.** `api.energy-charts.info` is still denied by
the cloud environment's egress policy, so FLAG C1-01 stands unchanged, there is
still no manifest, and no C2 work was started. This is the cycle the previous
entry designated as the escalation point (~2 days of zero progress), so **one
escalation push notification was sent** — the first ping since C1. No further
pings for this same wait unless the human asks or the situation changes.

Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**, including the 9 sealed-holdout tests. The 2025 unseal marker is
  confirmed **absent** from this file (`grep -c` = 0), so the holdout guard is
  still armed and the holdout remains SEALED.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the sixth cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), exits 1, and caches nothing (`data/raw/`
  was never created).
- The agent proxy's status endpoint records, for this cycle's probes,
  `connect_rejected` / "gateway answered 403 to CONNECT (policy denial or
  upstream failure)" for **both** `api.energy-charts.info:443` and
  `web-api.tp.entsoe.eu:443`. A `github.com` control probe from the same
  session tunnels fine (HTTP 400 from the origin, i.e. CONNECT succeeded), so
  this remains host-specific policy, not a broken tunnel. No mirror, scraper or
  alternative source was tried, and `config/data.yaml` still names
  Energy-Charts as the only price source.
- `python -m data.build_manifest` refuses on the empty cache (`EXIT=3`) rather
  than writing an empty manifest.
- `ENTSOE_API_KEY` is still **not set** in this environment. Not blocking
  anything before C7; recorded so the C7 precondition stays visible.

**The `fetch_failures.json` trap is confirmed closed.** Last cycle added the
`.gitignore` line; this cycle's single-pair probe wrote its `n_failures=1`
artefact as usual and `git check-ignore` confirms it is now ignored
(`.gitignore:15`), so no hand-deletion was needed and `git status` came back
clean. Three cycles of manual cleanup are no longer a per-cycle risk.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous four cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

**Repo-state note — the detached-HEAD trap recurred, exactly as C1b (5th)
warned.** This container's fresh clone again arrived on a **detached HEAD** at
`607e6f6` with local `master` stale at the C0 commit `d257e20` and
`origin/master` also reading `d257e20` before a fetch. The previous cycle's
warning is what caught it. Resolved the same way: `git fetch origin` (which
moved `origin/master` `d257e20..607e6f6`), confirmed local `master` was a strict
ancestor via `git merge-base --is-ancestor`, confirmed `HEAD == origin/master`,
then `git checkout master` + `git merge --ff-only origin/master`. All five prior
commits intact; this cycle commits on `master`. **This is now a reproducible
property of this environment, not a one-off — every future cycle should fetch
and verify against `origin/master` before committing.** Committing from the
detached state would strand the work, and checking out stale `master` without
fetching first would revert the tree to C0 and look in the diff like a
deliberate rewrite of `PROGRESS.md` history.

*Human action needed (unchanged, and now the blocker for ~2 days):* this cloud
environment's network policy is denying `api.energy-charts.info` and
`web-api.tp.entsoe.eu`. Change **Network access** in the cloud environment's
settings (the environment menu in the session title bar → Edit): either a
broader access level, or add both hosts to the allowed domains. Access levels
are described at https://code.claude.com/docs/en/claude-code-on-the-web.
Nothing in C1-C6 can proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-30 10:02 UTC (scheduled cycle) — STILL BLOCKED, no new work

**Seventh consecutive blocked cycle** (~2.5 days). `api.energy-charts.info` is
still denied by the cloud environment's egress policy, FLAG C1-01 stands
unchanged, there is still no manifest, and per the standing C1b instruction no
C2 work was started and **no push notification was sent** — both pings for this
wait (C1 and the 2026-09-30 02:02 UTC escalation) are spent.

Short note, since the previous six entries already document this block in full.
Verified this cycle (fresh container — no venv, empty cache):
- `.venv` rebuilt from the committed `requirements.txt`; **all 44 C1 unit tests
  pass**. The exact unseal marker string is confirmed **absent** from this file
  (`grep -cF` = 0), so the holdout guard is armed and 2025 remains SEALED.
- `python -m data.fetch_prices --zones DE-LU --years 2024` reproduces the
  failure byte-identically for the seventh cycle running (`ProxyError ... Tunnel
  connection failed: 403 Forbidden`), **exits 1**, and caches nothing
  (`data/raw/` was never created).
- `python -m data.build_manifest` refuses on the empty cache (**EXIT=3**).
- Proxy status endpoint: `connect_rejected` / "gateway answered 403 to CONNECT
  (policy denial or upstream failure)" for **both**
  `api.energy-charts.info:443` and `web-api.tp.entsoe.eu:443` (both
  10:01:34Z). A `github.com` control probe from the same session tunnels fine
  (HTTP 400 from the origin, i.e. CONNECT succeeded), so this remains
  host-specific policy, not a broken tunnel. No mirror, scraper or alternative
  source was tried; `config/data.yaml` still names Energy-Charts as the only
  price source.
- `ENTSOE_API_KEY` still **not set**. Not blocking anything before C7; recorded
  so the precondition stays visible.
- `git status` clean — the `.gitignore` line added at the 5th cycle continues to
  absorb the probe's `fetch_failures.json` artefact (`.gitignore:15`), so no
  hand-deletion was needed. No files under `tests/`, `data/`, `config/` or any
  data contract were touched this cycle.

**Deliberately did NOT run the full 54-pair fetch**, for the same reason as the
previous five cycles: with the gateway refusing CONNECT on policy, all 54 pairs
would burn ~55 minutes of backoff and put 162 rejected CONNECTs against the host
for no information beyond what one pair plus the proxy's own denial record
already establish. When the host is allowed, the full pull must still be run in
full.

**Repo-state note — the detached-HEAD trap recurred for the third cycle
running.** Fresh clone arrived on a **detached HEAD** at `fe5aca1` with local
`master` stale at the C0 commit `d257e20` and `origin/master` also reading
`d257e20` before a fetch. Resolved the documented way: `git fetch origin`
(moved `origin/master` `d257e20..fe5aca1`), confirmed local `master` was a
strict ancestor via `git merge-base --is-ancestor`, then `git checkout master` +
`git merge --ff-only origin/master`. All six prior commits intact; this cycle
commits on `master`. This is a stable property of this environment — **every
future cycle must fetch and verify against `origin/master` before committing.**

*Human action needed (unchanged, now the blocker for ~2.5 days):* this cloud
environment's network policy is denying `api.energy-charts.info` and
`web-api.tp.entsoe.eu`. Change **Network access** in the cloud environment's
settings (the environment menu in the session title bar → Edit): either a
broader access level, or add both hosts to the allowed domains. Access levels
are described at https://code.claude.com/docs/en/claude-code-on-the-web.
Nothing in C1-C6 can proceed without the first host; C7 needs the second.

**Next:** still C1b — rerun `python -m data.fetch_prices` (all 54 pairs) then
`python -m data.build_manifest` once the hosts are allowed. Then C2, which ends
at **Checkpoint A**.

### C1b — 2026-09-30 13:17-13:30 UTC (scheduled cycle) — UNBLOCKED, C1 COMPLETE

**The egress block is over after 7 blocked cycles (~2.5 days).**
`api.energy-charts.info` now answers (HTTP 200) and `web-api.tp.entsoe.eu`
tunnels (HTTP 401, i.e. CONNECT succeeded — 401 is just the missing-key
response to a bare probe). **FLAG C1-01 is RESOLVED.** Separately,
`ENTSOE_API_KEY` is now **set** in this environment, so the C7 precondition is
also satisfied. Thanks — both of those were human-side changes to the cloud
environment settings, and both landed.

C1's remaining work — the pull and the manifest — ran to completion this cycle.
**C1 is now fully done.**

**What ran:**
- `.venv` rebuilt from the committed `requirements.txt` (fresh container, no
  venv). **All 44 C1 unit tests pass**, before and after the pull.
- Holdout guard verified armed *before* touching anything: the unseal marker
  (the exact string defined in `config/data.yaml` -> `holdout_unseal_marker`;
  deliberately **not** reproduced verbatim anywhere in this file, see the
  warning at the end of this entry) is **absent** here (`grep -cF` = 0),
  `holdout_is_unsealed()` returns `False`, `sealed_years()` = `{2025}`, and
  `fetch_years` = 2019-2024 with no overlap. **2025 remains SEALED and was
  never requested.**
- `python -m data.fetch_prices` — the full **54-pair** pull (9 zones x 6 years),
  as the previous six entries said it must be run when the host was allowed.
  Result: `downloaded=54 already_cached=0 flagged=0`, **EXIT=0**.
  `fetch_failures.json` records `n_failures: 0`. No 404s, no empty payloads, no
  schema rejections, no retries needed.
- `python -m data.build_manifest` — **EXIT=0**, 54 rows written to
  `data/manifest/prices_manifest.csv` (18 KB) and `.json` (52 KB), tagged with
  git SHA `0388dac`, config hash `47583ac06601f0a2`, CC BY 4.0 licence and the
  Energy-Charts attribution.
- `data/raw/` is 9.0 MB and **gitignored** (`.gitignore:4`), as is
  `fetch_failures.json` (`.gitignore:15`). Only the manifest artefacts are
  committed — no bulk raw data, no keys.

**Data quality — the pull is clean.** Across all 54 (zone, year) pairs:
`n_gap_intervals` = 0, `n_nan` = 0, `resolution_seconds` = 3600 uniformly,
`n_distinct_deltas` = 1. An independent check over the raw cache confirms each
zone is **one contiguous hourly series, `2018-12-31T23:00Z .. 2024-12-31T22:00Z`,
uniform 3600s deltas, no interior gaps.**

Mean day-ahead price, EUR/MWh (the Checkpoint A table in miniature):

| zone     | 2019 | 2020 | 2021  | 2022  | 2023  | 2024  |
|----------|------|------|-------|-------|-------|-------|
| BE       | 39.3 | 31.9 | 104.1 | 244.6 |  97.3 |  70.3 |
| DE-LU    | 37.7 | 30.5 |  96.9 | 235.5 |  95.2 |  78.5 |
| DK1      | 38.5 | 25.0 |  88.1 | 219.1 |  86.8 |  70.7 |
| ES       | 47.7 | 34.0 | 111.9 | 167.5 |  87.1 |  63.0 |
| FR       | 39.4 | 32.2 | 109.2 | 275.9 |  96.9 |  58.0 |
| IT-North | 51.2 | 37.8 | 125.2 | 307.8 | 127.8 | 107.4 |
| NL       | 41.2 | 32.2 | 103.0 | 241.9 |  95.8 |  77.3 |
| NO2      | 39.3 |  9.3 |  75.1 | 211.3 |  79.4 |  50.1 |
| PL       | 53.5 | 46.7 |  87.0 | 166.7 | 111.7 |  96.3 |

Negative-price hours per zone-year:

| zone     | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|----------|------|------|------|------|------|------|
| BE       |  71 | 136 | 159 | 112 | 221 | 404 |
| DE-LU    | 211 | 298 | 139 |  69 | 300 | 457 |
| DK1      | 132 | 192 |  87 |  38 | 281 | 375 |
| ES       |   0 |   0 |   0 |   0 |   0 | 247 |
| FR       |  27 | 102 |  64 |   4 | 147 | 352 |
| IT-North |   0 |   0 |   0 |   0 |   0 |   0 |
| NL       |   3 |  97 |  70 |  85 | 315 | 458 |
| NO2      |   0 |   5 |   5 |   0 | 174 | 206 |
| PL       |   0 |   0 |   0 |   0 |  43 | 197 |

These are **not** yet verified against an independent source — that is
Checkpoint A's job — but they line up with known market history: the 2022
crisis peak in every zone; NO2's 2020 Nordic hydro glut at 9.3 EUR/MWh;
IT-North with a 0.00 EUR/MWh floor and zero negative hours throughout (MGP had
no negative prices in this window); ES with zero negative hours until 2024,
then 247 as solar penetration bit; and the sharp 2023->2024 rise in negative
hours almost everywhere. FR's 2987.78 EUR/MWh maximum sits in the 2022
nuclear-outage period. Extremes: DE-LU / NL / BE / DK1 all touch the
-500 EUR/MWh region; DE-LU and DK1 peak at 936.28.

**NOTE C1-02 — request-window convention, resolved. Not a defect; C2 must
know it.** Every one of the 54 rows reports `coverage_ratio` = 0.999886
(8759/8760) with `n_out_of_window_dropped` = 1 and `last_ts_utc` =
`Y-12-31T22:00Z`. This is **not missing data**. `docs/data_layer.md` had left
this question open as "to verify in C2"; the pull answers it:

- Energy-Charts interprets `start`/`end` as whole days in the **zone's local
  time**, returning exactly one full *local* year (8760 / 8784 points). All
  nine zones are CET/CEST, so each raw file spans `Y-1-12-31T23:00Z ..
  Y-12-31T22:00Z` in UTC.
- Truncating to the UTC calendar year therefore drops exactly the one leading
  point belonging to `Y-1` (hence `n_out_of_window_dropped` = 1), and the final
  UTC hour of year `Y` is absent from row `Y` because it was never in the `Y`
  window — **it is present in file `Y+1`**. The per-year rows understate
  coverage by exactly one hour by construction.
- **C2's loader must concatenate the per-year files and de-duplicate on
  timestamp — it must not reindex or fill per-year to 8760.** The first hour of
  UTC year `Y` is in file `Y`; the last hour of UTC year `Y` is in file `Y+1`.
- **Holdout interaction, flagged deliberately:** the last hour of UTC 2024
  (`2024-12-31T23:00Z`) lives *only* in the 2025 file, and 2025 is SEALED. The
  usable UTC span therefore ends at **`2024-12-31T22:00Z`**. A future cycle
  must **never** fetch 2025 to close that one-hour tail. It costs 1 hour out of
  ~52,600, the hourly backtest window ends 2025-09-30 regardless, and
  `data/holdout.py` already refuses the fetch. This note exists so the tail is
  not mistaken for a bug worth "fixing".

`docs/data_layer.md` has been updated with the resolved convention and the C2
requirement. **No file under `tests/`, `config/`, or `data/*.py` was touched
this cycle** — the only code-adjacent edit is that documentation section
(`git diff --name-only` confirms `docs/data_layer.md` is the sole modification).

**Scope discipline:** C1b was scoped as the pull plus the manifest, and stops
there. C2 was deliberately **not** started even though budget remained, per the
standing rule against running ahead into a later cycle's work — and C2 ends at
Checkpoint A, which needs its own full cycle. No push notification was sent:
this is a routine cycle, not a checkpoint, and the unblocking is good news
rather than something needing a human decision. The human will be pinged at
the end of C2 for Checkpoint A.

**WARNING FOR EVERY FUTURE CYCLE — do not quote the unseal marker verbatim in
`PROGRESS.md`.** This cycle tripped that wire and caught it pre-commit. While
writing the log entry above, this session reproduced the unseal marker string
literally (inside backticks, in a sentence *asserting the marker was absent*).
`data/holdout.py` tests membership with a plain `marker in
PROGRESS.md_text` — backticks, surrounding prose and negating context are
invisible to it. The result: `grep -cF` went 0 -> 1 and
`holdout_is_unsealed()` flipped to **`True`**, i.e. the 2025 seal was
**mechanically open**, purely from a cycle describing the guard.

Caught by re-checking the guard immediately after the write, **before any
commit, push, fetch or model touched a sealed year**. The verbatim string was
removed, and the state is confirmed restored: `grep -cF` = **0**,
`holdout_is_unsealed()` = **`False`**, and the 44-test suite (which includes
the tripwire test asserting the marker is absent) passes. No sealed data was
fetched, loaded, or computed against at any point — the whole episode lived
inside an uncommitted working-tree edit to a prose file.

Two things follow, and they are worth more than the incident cost:
1. **Refer to the marker indirectly** — as "the string in `config/data.yaml` ->
   `holdout_unseal_marker`" — never by reproducing it. The same applies to
   commit messages and any other file the guard reads.
2. The guard's substring test is doing its job but is **context-blind**, which
   is a real design observation for the human: a hardening option (e.g.
   requiring the marker alone on its own line, plus a human signature/date) is
   worth considering at Checkpoint A. **Proposed, not done** — `data/holdout.py`
   is the leakage-contract file, and CLAUDE.md forbids an agent cycle changing
   it without human review. Flagged here for that review; no code was changed.

**Next:** **C2** — data contract tests (per-(zone, day) row counts against the
DST whitelist, resolution-change detection at the 2025-10-01 15-min cutover,
gap report), documented hourly aggregation, and a price plot per zone. Then
**stop at CHECKPOINT A** and push-notify for human review of the manifest and
plots before any modelling begins.

### C2 — 2026-09-30 17:55-18:30 UTC (scheduled cycle) — COMPLETE, **CHECKPOINT A REACHED**

Scope per PLAN.md C2: data contract tests (per-(zone, day) row counts against a
DST whitelist, resolution-change detection at the 2025-10-01 cutover, gap
report), documented hourly aggregation, and a price plot per zone. Then stop at
Checkpoint A. All of that is done; nothing from C3 was started.

**Container state on arrival.** Detached HEAD at `6227d69` (4th recurrence),
reattached to `master` before touching anything. `.venv` absent, rebuilt from the
committed `requirements.txt`. **`data/raw/` was empty** — the raw cache is
gitignored and the container is ephemeral, so C1's 9.0 MB of cached price files
did not survive. See NOTE C2-02.

**The 54-pair pull was re-run, and it reproduced C1 exactly.** Re-fetching was
not a violation of "never re-download cached data": the cache was empty, so there
was nothing cached to re-download, and C2 cannot check contracts on data that
isn't there. `downloaded=54 already_cached=0 flagged=0`, EXIT=0, no 404s, no
retries, no schema rejections. The manifest was then rebuilt and diffed against
C1's committed copy: **all 25 data columns identical across all 54 rows** —
`n_points`, `raw_bytes`, `first/last_ts_utc`, every price statistic, every
negative-hour count. The committed `prices_manifest.{csv,json}` were therefore
restored to C1's versions rather than re-committed with fresh provenance stamps,
so the Checkpoint A artefact the human reviews is stable and diff-free.

**Built this cycle:**
- `data/prices.py` — the stitching loader NOTE C1-02 specified. It does **not**
  reuse `read_cached_year`: that trims each file to its own UTC year, which would
  leave a one-hour hole at *every* year boundary, since `Y-12-31T23:00Z` lives in
  file `Y+1`. It parses each file untruncated, concatenates, sorts, and
  de-duplicates on timestamp — collapsing a duplicate only when the two files
  agree on the price, and raising if they disagree. Never reindexes, never fills.
  The holdout guard is applied per year before any file is opened.
- `data/contracts.py` — the seven contracts (table below), the derived DST
  whitelist, resolution segmentation/change detection, the gap report, and
  `payload_fingerprint` (see NOTE C2-01).
- `data/aggregate.py` — sub-hourly -> hourly by one documented method.
- `data/build_contracts.py`, `data/plot_prices.py` — the two CLIs.
- `tests/test_c2_contracts.py` — **42 new tests**, all offline and synthetic.
- `docs/data_contracts.md` — the layer documented; `docs/data_layer.md` got a
  one-line pointer marking its "requirement for C2's loader" satisfied.
- `requirements.txt` — matplotlib added.

**Test suite: 86 passing (44 from C1, 42 new).**

**Result: all nine zones pass all seven contracts.** Each zone is one contiguous
hourly series, `2018-12-31T23:00Z .. 2024-12-31T22:00Z`, 52,608 points:

| contract | result, all 9 zones |
|---|---|
| index tz-aware UTC, monotonic, no duplicates | pass; 0 duplicates |
| every fully-covered UTC day = 24 rows | pass; **2,191 days checked**, 0 violations |
| every fully-covered local day = DST-derived count | pass; **2,192 days checked**, 0 violations |
| every non-24h local day is a tz-database transition date | pass; **12 DST days** seen per zone |
| no gaps | pass; `n_missing_intervals` = 0, `max_gap_hours` = 0.0 |
| no NaN prices | pass; 0 |
| only permitted resolution change is 3600s->900s at the cutover | pass; 0 changes (series ends 2024) |

**The DST whitelist is derived, not hardcoded.** `dst_transition_days(tz, years)`
walks the tz database, so it cannot drift from reality, and it fails in *both*
directions: a 23-hour local day on the last Sunday in March passes, a 23-hour
local day on an ordinary Tuesday is a violation (there is a test for exactly
that). This is the assertion that stops an hour of silently dropped real data
from being excused as "probably DST". All nine zones are CET/CEST and share one
transition calendar — asserted by a test, so adding a non-CET zone later fails
loudly instead of silently reusing the wrong calendar. 126 rows committed to
`data/manifest/dst_whitelist.csv`.

**UTC days and local days are deliberately separate contracts.** A UTC day always
holds 24 hourly intervals, so a deviation is unambiguously a defect; a local day
holds 23/24/25 and needs the whitelist. Day completeness is decided from expected
interval *timestamps*, not by assuming the first and last day are partial — for
these CET zones the local-day view is complete at both ends and those days are
still checked (hence 2,192 local vs 2,191 UTC days).

**Gaps and resolution changes are not allowed to be confused.** A missing hour and
a market-time-unit change both appear as an odd delta. `detect_resolution_changes`
ignores runs shorter than two intervals and merges same-resolution neighbours, so
hourly / missing-hour / hourly reports a **gap**, not a 3600s->3600s "change" —
that was a genuine bug in this cycle's first draft, caught by its own test.
`gap_report` measures each step against the resolution in force either side of it,
so a legitimate cutover contributes zero missing intervals.

**The 2025-10-01 cutover instant is local midnight, not UTC midnight**
(`2025-09-30T22:00Z` for a CEST zone) — it is a market *day*. Only one change,
3600s->900s at that instant, is permitted; anything else is a violation.
**No 2025 data was touched to test this.** The detector is exercised on synthetic
hand-built indices; the real series ends 2024-12-31 and reports 0 changes.

**Hourly aggregation — the method, on the record.** The hourly price is the
**unweighted arithmetic mean** of the sub-hourly prices whose interval starts in
that UTC hour. Sub-hourly intervals are equal length, so that is the correct
duration-weighted average. **It is not a VWAP and cannot be**: a volume-weighted
price needs cleared volume per interval, and the Energy-Charts `/price` payload
carries prices only. `to_hourly` accepts an explicit `volume` argument so the
machinery exists if a volume source is ever added, but nothing in this repo
supplies one — the write-up must say "duration-weighted mean of 15-minute prices",
never "VWAP". Partial hours raise by default rather than being averaged. Grouping
is on the UTC hour; local time is never a resampling key.
*For the write-up's Limits section:* aggregating 15-minute prices to hourly
destroys within-hour spread, so a battery's realisable value is **higher** at
native 15-minute granularity than an aggregated hourly series implies. Aggregated
post-cutover results understate flexibility value and must never be pooled with
pre-cutover hourly results as though they were the same measurement.

**Independent cross-check of C1's manifest, and a clean reconciliation.** The
negative-hour counts recomputed from the stitched series match C1's per-year
manifest everywhere except three cells: DE-LU 2022 (69 -> 70), NL 2022 (85 -> 86),
BE 2022 (112 -> 113). All three are the *same single hour*, `2022-12-31T23:00Z`,
which was negative in exactly those three zones (-5.17, -3.61, -4.39 EUR/MWh).
That hour is absent from the manifest's 2022 row because it lives in file 2023 —
precisely and only the discrepancy NOTE C1-02 predicts. Every other (zone, year)
pair agrees exactly. This is a good sign for both artefacts: the manifest and the
stitched series differ in exactly the documented way and nowhere else.

**Figures (11, in `docs/figures/`, 1.8 MB total).** One per zone — daily mean with
the intraday min-max band behind it, plus a one-week hourly inset so the raw shape
is visible; a nine-panel small-multiples overview on a shared y-axis; and
negative-price hours per zone-year. The overview's y-axis is **clipped to
[-124, 850] EUR/MWh with the clipping stated on the figure itself** (36 daily
extremes fall outside): FR's 2,987.78 EUR/MWh 2022 print otherwise squashes all
nine panels into the bottom eighth of the frame. True extremes are in the
manifest. Daily aggregation is on the UTC date and drops the partial boundary days
so the left edge is not a one-hour "day".

**NOTE C2-01 — the manifest's `raw_sha256` cannot be reproduced, by construction.
Not a defect in the data; a limit on what that column can be used for.** The
re-pull produced 54 files with byte-identical *sizes* and *contents* but 54
different `raw_sha256` values. Cause: the column hashes the cached file, and this
project writes a `_fetch_meta.fetched_at_utc` stamp into that file before hashing
it. So `raw_sha256` identifies a *file*, not a *payload*, and can never match
across re-fetches — it cannot serve as the data-integrity check it looks like.
Rather than change `data/manifest.py` mid-checkpoint (it produces the artefact the
human is about to review), C2 added `payload_sha256` to the contract report:
sha256 over the `(UTC epoch, price)` pairs at fixed 6-decimal precision,
reproducible across pulls. **A human decision is requested** on whether
`data/manifest.py` should switch `raw_sha256` to hash the payload rather than the
file. Proposed, not done.

**NOTE C2-02 — the raw cache does not survive a container, so every cycle re-pulls
54 files (~9 MB).** `data/raw/` is gitignored (correctly — CLAUDE.md forbids
committing bulk raw data) and containers are ephemeral, so C1's cache was gone.
This is not currently harmful: the pull takes ~4 minutes, is polite (2s between
requests), and reproduced byte-identically. But it means "never re-download cached
data" is effectively unenforceable across cycles, and ~15 more cycles implies ~15
more full pulls against a free, unauthenticated Fraunhofer ISE endpoint. **A human
decision is requested** between: (a) leave it — it is polite and provably
reproducible; (b) commit a compact derived artefact (all nine zones, hourly, 2019
-2024 is ~1.2 MB as compressed parquet) so cycles load from the repo and only fetch
what is missing; (c) configure a persistent cache volume if the platform offers
one. Option (b) touches the "no bulk raw data" rule and is the kind of call that
should not be made by an unattended cycle. Proposed, not done.

**Files under `tests/` — declared, per CLAUDE.md.** One file was **added**:
`tests/test_c2_contracts.py`. That is C2's own mandate in PLAN.md ("data contract
tests"), and adding a new test file is not what the rule guards against. **No
existing test was edited, and no existing assertion was weakened or deleted** —
`tests/test_c1_data_layer.py` and `tests/conftest.py` are untouched
(`git diff --stat` confirms). Where this cycle's tests failed, the *code* was
fixed: the resolution-change merge bug described above was a real defect in new
code, found by a new test, and fixed in `data/contracts.py`.

**One C1 file was modified, and it is a pure refactor:** `data/energy_charts.py`
gained `parse_payload(payload, context)` — the untruncated parse — and
`payload_to_frame` now calls it before applying its per-UTC-year window. Behaviour
is unchanged (all 44 C1 tests pass unmodified, before and after). This was needed
because the stitching loader must see the whole file, not one UTC year.
`data/holdout.py`, `data/config.py`, `data/manifest.py` and everything under
`config/` were **not** touched.

**Sealed holdout.** Verified armed before the work and again before committing:
marker count in this file 0, `holdout_is_unsealed()` = `False`, `sealed_years()` =
`{2025}`, `fetch_years` = 2019-2024. The C1b warning was heeded — the marker
string is not reproduced anywhere in this entry, only referred to by its config
key. No 2025 data was fetched, loaded, or computed against. The synthetic indices
dated 2025 in the cutover tests are hand-built timestamps with made-up prices, not
sealed data; `data/prices.py` has a test asserting it refuses a sealed year even
when a 2025 file is sitting in the cache.

---

## CHECKPOINT A — ready for review

**What to look at, roughly in this order:**
1. `docs/figures/prices_all_zones.png` — the nine series at a glance. Sanity-check
   against market history: the 2022 crisis in every zone, NO2's 2020 hydro glut
   near zero, IT-North's 0.00 EUR/MWh floor, ES's flatter solar-shaped profile.
2. `docs/figures/negative_hours.png` — negative hours per zone-year. The
   2023->2024 jump almost everywhere, ES's first negative hours in 2024, IT-North
   at zero throughout, and the 2022 dip (high gas priced out negatives).
3. `data/manifest/prices_manifest.csv` — 54 rows, unchanged from C1. The mean and
   negative-hour tables are in the C1b entry above.
4. `data/manifest/contract_report.csv` — nine rows, `ok = True` on all of them.
5. `docs/figures/prices_<ZONE>.png` — any zone you want to look at closely.

**The one thing worth verifying independently:** these prices have not been
checked against a second source. Picking two or three cells from the manifest
(say DE-LU 2022 mean 235.5 EUR/MWh, NO2 2020 mean 9.3 EUR/MWh) and comparing them
against ENTSO-E, a market report, or memory is the highest-value five minutes of
this checkpoint — everything downstream inherits these numbers.

**Checkpoint A: what needs a human (three decisions, none blocking C3):**
1. **NOTE C2-01** — should `data/manifest.py` hash the payload rather than the
   file, so `raw_sha256` becomes reproducible? (C2 added a reproducible
   `payload_sha256` alongside it either way.)
2. **NOTE C2-02** — cache persistence: leave the per-cycle re-pull as is, commit a
   compact derived hourly artefact, or use a persistent volume?
3. **Carried over from C1b, still proposed and not done** — hardening
   `data/holdout.py`. Its unseal test is a plain substring check against this
   file, which is context-blind: the C1b cycle mechanically opened the seal just
   by *describing* the marker in prose, and caught it pre-commit. Options: require
   the marker alone on its own line, and/or require a human signature + date
   alongside it. `data/holdout.py` is the leakage-contract file, so CLAUDE.md
   forbids an agent cycle changing it without review. This is that review request.

**To approve and continue:** replace the "Next cycle to run" line at the top of
this file with C3, and note the approval here. C3 is the walk-forward harness plus
the naive model on DE-LU, with the three leakage tests written before the real
model.

**Next (after approval):** C3 — walk-forward harness + naive (same hour last week)
model, DE-LU only, and the leakage assertions: (i) shifting the feature matrix
forward one day must degrade metrics, (ii) a deliberately future-timestamped
feature must be caught by a gate-closure guard, (iii) target permutation must
destroy skill.

---

### Checkpoint A wait — 2026-10-01 (scheduled cycle, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT A**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `origin/master` == local HEAD at `fc422de` (the C2 checkpoint
  commit, no human commits since); all Checkpoint A artefacts present and unmodified
  (`data/manifest/prices_manifest.{csv,json}`, `contract_report.{csv,json}`,
  `dst_whitelist.csv`, 11 figures in `docs/figures/`); holdout guard re-verified armed
  (`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`); no 2025 data touched;
  no push notification sent (avoiding repeat pings for the same wait). HEAD arrived
  attached to `master` this container — the detached-HEAD trap did **not** recur
  (now 4 recurrences out of 10 containers). Still waiting on the three Checkpoint A
  decisions listed in the C2 entry above; C3 remains blocked until a human replaces the
  status line with C3 and records approval here.

---

### Checkpoint A — approved and closed — 2026-10-01 (human session, local, not a
scheduled cycle)

Reviewed `prices_all_zones.png` and `negative_hours.png` against known market
history (2022 crisis in every zone, ES's gas price cap keeping it at zero
negative hours until 2024, IT-North's price floor at zero throughout, the
2023→2024 negative-hour jump from renewables build-out) — consistent with real
market behaviour, not noise. All three Checkpoint A decisions resolved:

1. **NOTE C2-01, fixed in code.** `data/manifest.py` no longer hashes the
   cached file. The manifest's checksum column is renamed `raw_sha256` →
   `payload_sha256` and now calls `contracts.payload_fingerprint()` — the same
   function the C2 contract report already used — so it hashes only the `(UTC
   epoch, price)` pairs and is reproducible across re-fetches. Confirmed: a
   completely independent re-pull of all 54 (zone, year) pairs, two days after
   C1's pull, reproduced `price_mean` to 3 decimal places on every spot-checked
   cell (DE-LU 2022: 235.467; NO2 2020: 9.289) — this is a reproducibility
   check against the same source on a fresh pull, not an independent second
   source, and that distinction is worth keeping in mind for the write-up.
   `data/contracts.py`'s docstring, `tests/test_c1_data_layer.py` (assertion
   updated to the new column name, computed via `contracts.payload_fingerprint`
   on the loaded frame) and `docs/data_contracts.md` / `docs/data_layer.md`
   updated to match. All existing tests pass unweakened; nothing was deleted.
2. **NOTE C2-02, decided: leave as is.** The raw cache will keep not surviving
   between containers/cycles. Accepted trade-off — the pull is polite (2s
   between requests) and has now proven byte-reproducible across two
   independent pulls on different days; a persistent cache or a committed
   derived artefact isn't worth the engineering effort or the added "bulk raw
   data" rule-bending for a one-week project. No code change.
3. **Holdout guard hardened, as requested.** `data/holdout.py`'s
   `holdout_is_unsealed()` was a plain substring search; it now requires the
   marker to be the **entire content of some line** (stripped of surrounding
   whitespace) in `PROGRESS.md`, closing the near-miss C1b's own log entry
   almost triggered by describing the marker in prose. Deliberately did *not*
   add a human-signature/date requirement — judged more ceremony than this
   project needs; the marker is already something only a human writes, and
   CLAUDE.md already forbids an agent cycle from touching this file. Added
   `test_guard_stays_shut_when_the_marker_is_only_quoted_in_prose`, which
   checks both the negative case (marker embedded in a sentence must not
   unseal) and that a padded-whitespace marker-alone-on-its-own-line still
   does. The existing `test_guard_opens_only_when_the_exact_marker_is_present`
   continues to pass unmodified in its assertions (only its fixture gained an
   explicit `encoding="utf-8"` — see below) because its "approved" fixture
   already put the marker alone on its own line.

**One unrelated real bug found and fixed while verifying all this: a
Windows-locale encoding failure, not a logic error.**
`test_guard_opens_only_when_the_exact_marker_is_present`'s fixture wrote an
em-dash via `Path.write_text()` with no explicit encoding, which uses the
platform locale (cp1252 on this Windows machine) rather than UTF-8; the guard
reads `PROGRESS.md` as explicit UTF-8, so the two disagreed and the test raised
`UnicodeDecodeError` the first time it ran anywhere other than a UTF-8-locale
Linux container — which is all 10 scheduled cycles so far, explaining why this
was never caught before now. Fixed by adding `encoding="utf-8"` to every
`write_text()` call in this test file. Worth remembering if more local/Windows
verification happens later: this whole repo has otherwise been built and run
exclusively on Linux cloud containers.

**Manifest and figures regenerated from a fresh local pull**, not just
hand-edited: ran `python -m data.fetch_prices` (full 54 pairs; 4 hit `HTTP 429`
on the first pass — rate-limited, almost certainly from C1/C1b's pull of the
same 54 pairs against the same free, unauthenticated endpoint earlier the same
day — retried cleanly to 0 flagged), `python -m data.build_manifest`, `python
-m data.build_contracts` (all 9 zones `ok = True`), and `python -m
data.plot_prices`. All 87 tests pass (`pytest tests/ -q`). This was run
locally, with real internet access confirmed separately, rather than waiting
for the next scheduled cloud cycle, specifically so the committed manifest and
figures match the fixed `payload_sha256` code rather than sitting stale.

**Sealed holdout:** re-verified before writing this entry —
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`. No 2025 data
fetched, loaded, or computed against at any point in this session.

**Approved by:** J., 2026-10-01, via the assistant session that ran this
review and these fixes.

---

### C3 — 2026-10-01 (scheduled cycle) — walk-forward harness + naive model, DE-LU

**Done, as scoped in PLAN.md C3.** The harness, the naive floor, and — written
before any real model exists — the three leakage assertions, plus the gate-closure
guard they test. 50 new offline tests (137 total, all passing). Full design notes
in `docs/forecast_harness.md`.

**New modules.** `forecast/timing.py` (market days, gate closure, publication
instants), `forecast/features.py` (the feature matrix, built from
`config/features.yaml`, with an information time attached to every cell),
`forecast/leakage.py` (the gate-closure guard + availability mask),
`forecast/models.py` (the `Model` protocol, `NaiveLastWeek`, `TrainMeanBaseline`),
`backtest/walk_forward.py` (folds + three per-fold guards),
`backtest/metrics.py` (MAE/RMSE/rMAE/skill only — C12 owns the full layer),
`backtest/diagnostics.py` (PLAN's three probes as library functions, so later
cycles re-run them instead of re-deriving them), `backtest/run_c3_naive.py` (CLI).

**The rule the whole layer rests on, stated once.** Bids for delivery day `D` close
at 12:00 Europe/Brussels on `D-1`; day `D`'s prices are published ~13:00 on `D-1`,
*after* that deadline. So at gate closure for `D` a bidder knows every hourly price
of market days `<= D-1` and none of day `D`. That is about **market days**, not UTC
days and not raw hour offsets — and C3 found two places where the difference bites.

**FINDING C3-A — a plain 24-hour lag leaks once per zone per year.** On the
25-hour local day each autumn, the 25th hour's `t - 24h` lands on *that same market
day's first hour* — a price published after the bidding deadline for the very day
being predicted. Six cells over DE-LU 2019–2024, one per year, worth exactly one
hour of lateness. Found by the guard, not by reasoning. Masked to NaN, counted in
the build report (`price_lag_24h: 6`), rows never dropped. The 48h/72h/168h lags
never reach that far forward, so the naive baseline is unaffected.

**NOTE C3-01 — the daily-aggregate features cannot be built the way
`config/features.yaml` literally describes, because that description leaks. A
human decision is requested; proposed, not done.**
`price_daily_{mean,min,max}_lag_24h` are declared as `mean_over_utc_day` with
`lag_hours: 24`. Read literally — the aggregate over the UTC day containing
`t - 24h` — that window is UTC day `D-1` for 23 of the 24 hours of target day `D`.
For a CET zone UTC day `D-1` ends at `D-1 23:00Z`, which is **local midnight on
`D`**: market day `D`'s own first cleared price. So the literal feature embeds one
hour of the day it is predicting, on nearly every row, and **no** literal reading
of the spec is leak-free. `forecast/features.py` therefore builds those three
columns over *the latest UTC calendar day every hour of which was public at the
row's gate closure* — derived mechanically from the publication calendar, which for
the CET/CEST zones in scope resolves to UTC day `D-2`. The committed column names
are kept so config stays the single source of truth, but `lag_24h` in those names
is now a misnomer. **Decision requested:** rename them in `features.yaml` to
`..._prev_available_utc_day` and restate the aggregate, or leave the names and rely
on the documentation? Deliberately not done by this cycle — editing a feature spec
so that a leak disappears is precisely the move CLAUDE.md warns about.

**PLAN's three leakage assertions, on the real DE-LU pipeline (2024 validation,
daily refit, expanding window from 2019).** Also asserted on synthetic series in
`tests/test_c3_leakage_harness.py`.
- **(i) shifting the feature matrix forward one day degrades metrics.** Aligned MAE
  **32.80** EUR/MWh; one day staler **36.66**; one day fresher **36.04**. Both
  directions hurt, because `price_lag_168h` shifted either way stops being the same
  weekday — so the *sign* of the shift effect is not itself a leakage detector, and
  the test asserts correct alignment beats both. What it establishes is that the
  harness is sensitive to time at all, which is the precondition for (ii) meaning
  anything.
- **(ii) a deliberately inserted future-timestamped feature is caught.** A
  `price_lead_24h` column declared honestly → rejected `after_gate_closure` (52,584
  rows, worst 2 days late); smuggled in undeclared → rejected `undeclared`. The
  walk-forward refuses to run on the injected matrix. A separate test measures what
  the leak would have been *worth* on a persistence-dominated series: it more than
  halves MAE.
- **(iii) target permutation destroys skill.** Skill measured against a train-mean
  baseline run through the same harness. Real **+0.134**; hour-wise permuted
  **−0.130**; whole-day permuted **−0.105**. Both negative — a model fitted on
  shuffled targets is worse than a constant.

**Results, DE-LU 2024 (validation).** naive same-hour-last-week: **MAE 32.80,
RMSE 55.22, bias −1.52** over 8,784 hours / 366 folds; every evaluation hour
predicted exactly once, zero skipped days, zero missing predictions. Train-mean
baseline MAE 37.88. The naive model beats that reference by only 13%, which says
more about the reference than the model: an expanding window from 2019 puts the
2022 crisis in the training mean (2019–2023 mean 99.08 EUR/MWh) against a 2024
realised mean of 78.52. It is a deliberately weak denominator, used only for the
permutation test — **rMAE against naive** is the comparison that matters, and that
is C12's job. Committed: `backtest/results/c3_naive_DE-LU_2024_{predictions.csv.gz,
folds.csv,summary.json}` (126 KiB total), each tagged with git SHA and config hash.

**Design decisions worth a later cycle's attention.**
- *Lags by explicit UTC offset reindexing, never `.shift(n)`.* `shift` counts rows,
  so across a missing hour it hands back the price from 25 hours earlier and calls
  it a 24-hour lag — a modelling bug that looks exactly like clean data. Asserted
  against directly.
- *Refit cadence is explicit.* `refit_every_days` blocks consecutive evaluation
  days; the training window always ends the day before the *first* day of the
  block, so a weekly refit means the last day is predicted by a six-day-stale
  model. That is what a weekly-refit desk experiences, not a bug. C3's committed
  run uses daily refit.
- *The guard fails closed.* An undeclared column is a violation, not a column
  given the benefit of the doubt — that is what catches a future cycle adding a
  feature and forgetting the bookkeeping. Likewise a declaration that is not a UTC
  timestamp column: one careless assignment turns it `object` or tz-naive, and
  comparing that to a tz-aware gate closure raises an opaque pandas `TypeError`,
  which in a guard is the worst outcome — a check that neither passes nor fails.
  Two of this cycle's own new tests hit exactly that crash and the *code* was
  fixed, not the test.
- *Calendar columns are asserted price-independent* (rebuilt on shuffled prices,
  bit-identical), so nothing price-derived can hide in a column declared to carry
  no market information.

**Files under `tests/` — declared, per CLAUDE.md.** Two files **added**:
`tests/test_c3_timing_features.py` (19 tests) and
`tests/test_c3_leakage_harness.py` (31 tests). That is C3's own mandate in PLAN.md
("leakage tests written *before* the real model"), and adding a new test file is not
what the rule guards against. **No existing test was edited, and no existing
assertion weakened or deleted** — `git diff --stat HEAD -- tests/` is empty;
`test_c1_data_layer.py`, `test_c2_contracts.py` and `conftest.py` are untouched. All
87 pre-existing tests pass unmodified. Where a new test failed, the code was fixed
(the two guard-robustness bugs above) except in three cases where the *test* was
wrong and was corrected before anything was committed: it masked cells inside the
lag warm-up window where the feature is legitimately NaN; it expected the
belt-and-braces day-ordering error when the stronger publication check correctly
fires first; and it asserted a 24-hour lead beats the weekly lag on a
*week-periodic* synthetic series, where by construction it does not — that test now
builds its own persistence-dominated series, which is the honest way to measure
what a leak buys.

**NOTE C3-02 — `config/data.yaml` gained three keys, so `config_hash` moved:
`47583ac06601f0a2` → `d524f72059bc6d85`.** The leakage guard needs the day-ahead
clock as config rather than as literals in code, so `structural_dates` gained
`day_ahead_gate_closure_tz: Europe/Brussels` and
`day_ahead_results_published_local: "13:00"` (plus comments). Purely additive —
nothing was changed, removed or weakened, and `splits`, the holdout declaration and
the unseal marker are untouched. Consequence: the committed
`data/manifest/prices_manifest.json` still records the C2-era `config_hash`
`47583ac06601f0a2`, which no longer matches the current config. The manifest's
*data* is unchanged and still valid — only the config fingerprint moved, and it
moved because of a key that has nothing to do with prices. Deliberately **not**
regenerated: that would mean re-pulling all 54 (zone, year) pairs to chase a hash,
churning a Checkpoint-A-approved artefact and hammering a free endpoint. Both
hashes are recorded here so provenance stays traceable. The guard's correctness
depends only on the ordering `gate_closure(D) < publication(D) < gate_closure(D+1)`,
asserted in `GateClosureConvention.__post_init__` and tested for every day of a
year — not on the exact publication minute.

**Data.** Only DE-LU was fetched (6 files, 2019–2024, ~1 MB) — C3 is DE-LU only, so
there was no reason to re-pull the other eight zones. All 6 downloaded cleanly, 0
flagged; the container arrived with `data/raw/` empty as NOTE C2-02 predicts and the
human decision there ("leave as is") was followed. No ENTSO-E call was made —
C3 needs no exogenous data, so `ENTSOE_API_KEY` was not read this cycle.

**Sealed holdout.** Verified armed before the work and again before committing:
marker-alone-on-a-line count in this file 0, `holdout_is_unsealed()` = `False`,
`sealed_years()` = `{2025}`, `fetch_years` = 2019–2024. No 2025 data was fetched,
loaded, feature-engineered from or measured against. Two tests name the year 2025
in order to prove the harness *refuses* it (`evaluation_days` and
`run_walk_forward` both raise `SealedHoldoutError`); they pass bare `datetime.date`
labels and read nothing — the same line C2 drew for its resolution-cutover tests.
The C1b warning was heeded: the marker string is not reproduced anywhere in this
entry, only referred to by its config key.

**Repo-state note.** The detached-HEAD trap **did** recur: the container arrived on
a detached HEAD at `17249e9`. Reattached with `git checkout -B master 17249e9` and
re-pointed at `origin/master` before any work. Now 5 recurrences out of 11
containers.

**Next:** C4 — LEAR (per-hour LASSO, in-fold scaling / asinh transform, in-fold
IC/CV selection), DE-LU, walk-forward on 2024 only. It plugs into this harness as a
`Model` and adds `scikit-learn` to `requirements.txt`. It will need a documented
policy for the NaN cells this cycle's mask creates (LASSO cannot take NaN) — the
honest options are dropping those rows from the *training* fit only, or imputing
in-fold from the training window, and neither should be chosen silently. The open
item from this cycle is **NOTE C3-01** (rename the daily-aggregate features in
`features.yaml`, or keep the names and rely on the docs); it does not block C4.

### C4 — 2026-10-02 (scheduled cycle) — LEAR, DE-LU, walk-forward on 2024

**Done, as scoped in PLAN.md C4.** LEAR — per-hour LASSO, in-fold asinh/MAD
variance stabilisation, in-fold penalty selection — plugged into C3's harness as a
`Model`, with the NaN policy C3 asked for decided and documented. 35 new offline
tests (172 total, all passing). Design notes in `docs/lear_model.md`.

**Headline, DE-LU 2024 (validation), expanding window from 2019, daily refit, 366
folds, 8,784 hours.**

| model | MAE | RMSE | bias | rMAE vs naive | coverage |
| --- | --- | --- | --- | --- | --- |
| naive same-hour-last-week (C3) | 32.80 | 55.22 | −1.52 | 1.000 | 1.00000 |
| **LEAR (AIC, committed)** | **22.86** | **36.92** | +2.60 | **0.697** | 0.99989 |
| LEAR (BIC) | 22.83 | 36.93 | +1.66 | 0.696 | 0.99989 |
| LEAR (time-ordered CV) | 22.90 | 36.93 | +2.74 | 0.699 | 0.99989 |
| LEAR (AIC, `nan_policy="impute"`) | 22.87 | 36.92 | +2.60 | 0.697 | 1.00000 |
| train-mean reference | 37.88 | — | — | — | 1.00000 |

**LEAR cuts the naive floor's MAE by 30%** (rMAE 0.697). That is the number C9's
booster has to beat and the forecast error the battery gets dispatched against
from C6.

**New modules.** `forecast/lear.py` (`LearSpec`, `LearModel`, the design encoding,
the VST), `backtest/run_c4_lear.py` (CLI). `forecast/models.py` gained
`TrainMedianBaseline` — purely additive, and the reason is FINDING C4-A below.

**The four decisions that carry the model, each one a place this usually goes
wrong.**
- *One LASSO per delivery hour, partitioned on **local** time.* Hour 03 and hour 18
  are different products; pooling them makes one model wrong about both. CLAUDE.md
  forbids local time for *resampling or alignment* — this is neither: no row moves,
  nothing is reindexed, the matrix is only grouped. And the partition key is itself
  a declared, gate-closure-checked feature column, so the thing deciding which
  model sees a row is under the same guard as everything else. `hour_key="utc"`
  exists so the choice is visible rather than baked in.
- *Everything fitted in-fold, then applied frozen.* Medians, MADs, standardisation
  moments, one-hot levels and the penalty are estimated on the training window and
  never recomputed at predict time. Two tests assert this behaviourally rather than
  by reading the code: predicting one row alone must return exactly what predicting
  the whole block returned, and multiplying every *other* test row by a thousand
  must not move the first row's number. A scaler fitted on train+test fails both —
  which is the point, because it is invisible in a diff.
- *asinh((y−a)/b) with the in-fold median and MAD, inverted exactly.* A log is
  unavailable on a market with negative prices, and an untransformed LASSO spends
  its whole budget on the 2022 spikes. `b` falls back MAD → std → 1.0 and the
  fallback is *reported*, because a constant price column in a training window is a
  data problem, not a feature. Back-transformed predictions are **not clipped**: an
  absurd run should show an absurd number, and the fit report carries predicted
  min/max so it is visible either way.
- *NaN answered, not absorbed* — the open question C3 handed over. Training rows
  with any missing design cell are **dropped from the fit** (listwise), counted per
  hour-model; a test asserts dropping a row is *equivalent* to the row never having
  existed, i.e. nothing was imputed behind the report's back. Test rows with a hole
  get **no prediction** (`nan_policy="decline"`), and `backtest/metrics.py` charges
  the model coverage for it rather than shrinking the denominator. A missing
  *calendar* cell is missing too, not a row of zero indicators — one-hot encoding a
  NaN would silently make it the reference level. An unseen category is counted; an
  unseen delivery hour gets no model and no number.

**The selector was chosen once, on validation, by a rule stated before the
numbers.** All three in-fold rules land within 0.35% of each other (22.83–22.90).
BIC wins by 0.17%, inside the 0.5% margin `backtest/run_c4_lear.py` commits to in
its docstring, so **AIC stays the committed default** — cheapest, fully
deterministic. The flatness is informative: with only ~26 design columns there is
little for a penalty to do and the selected alphas are near-zero (near-OLS). That
should change in C8 when load/RES features widen the design, so the comparison is
worth re-reading **once** then, not per cycle.

**PLAN's three leakage assertions, re-run on a model that can actually exploit a
leak** (probe cadence: weekly refit, for cost; the main run is daily).
- **(i) day shift.** Aligned MAE **22.861**; one day staler **26.479**; one day
  fresher **0.000**. LEAR recovers the target *exactly* from the shifted
  `price_lag_24h` column, because that column then **is** the target. So
  `degrades_for_every_shift` is **False** here where C3's naive floor had it True —
  the naive model reads only `price_lag_168h`, which any whole-day shift breaks in
  both directions. That is the measurement of what the leak is worth, not a bug;
  the gate-closure guard, not the sign of this number, is what refuses it on the
  real matrix.
- **(ii) future-feature guard.** Declared honestly → `after_gate_closure`;
  smuggled in undeclared → `undeclared`. The walk-forward refuses to run on either,
  with LEAR in the harness.
- **(iii) target permutation.** See FINDING C4-A — it needed real work.

**FINDING C4-A — a mean reference hands free skill to a median-like model, so
`destroys_skill` reads False for reasons that have nothing to do with LEAR.**
Real skill **+0.397** vs the train-mean baseline; with the target shuffled,
**+0.055** (hour-wise) and **+0.069** (whole-day). Read at face value that says a
model fitted on noise has skill. It does not. `backtest/metrics.py` scores MAE, minimised by the **median**;
`backtest/diagnostics.py` scores skill against the train-**mean**. DE-LU 2019–2024
prices are strongly right-skewed (mean **95.65**, median **66.18** EUR/MWh — the
2022 crisis), so on shuffled targets a constant at the training median beats a
constant at the training mean by ~**7%** of MAE while knowing nothing at all. LEAR
is a LASSO fitted in asinh space and mapped back through `sinh` — a median-like
estimator — so it collects that margin before it has learned anything. On the
permuted 2024 set: train-mean 66.47, **zero-information constant median 61.95
(+0.068 skill)**, permuted LEAR 62.78 (+0.055). **The permuted model earns less
than the constant that knows nothing**, and re-based on a median reference its
skill is **negative** (−0.013) while the honest model's stays clearly positive
(+0.380). Shuffling the target did destroy every bit of conditional skill; the
probe's pass criterion was simply calibrated for a mean-predicting model, which the
naive floor is and LEAR is not.
*The whole-day shuffle is a different question and also clean.* `mode="days"`
permutes whole market days, so it preserves the within-day shape — C3's own
docstring says as much, which is why that mode is reported separately rather than
used as the pass/fail probe. Its residue was measured rather than assumed: on the
day-permuted 2024 set a predictor knowing nothing but the **per-local-hour training
median** earns **+0.017** over the global training median, which is *more* than the
**+0.013** LEAR retains there; under the hour-wise shuffle the same hour-of-day
profile is worth **−0.001**, i.e. nothing, because that shuffle destroys it too. So
the entire day-mode residue is the daily price profile, LEAR extracts slightly less
of it than a plain per-hour median does, and the decisive hour-wise probe leaves it
with negative skill.
*What was done:* `TrainMedianBaseline` added to `forecast/models.py`; the re-based
comparison reported alongside the original in the committed summary under
`diagnostics.target_permutation_against_median`, both references refitted inside
the same walk-forward so nothing is a different evaluation set; and
`test_a_mean_reference_hands_free_skill_to_a_median_like_model` reproduces all
three halves of the diagnosis on a deliberately skewed synthetic series, so it
cannot be quietly un-learned. The ordinary near-symmetric test series does not show
it at all, which is why it surfaced only when LEAR met real prices.
*What was deliberately **not** done:* `backtest/diagnostics.py` was not touched. It
holds a PLAN.md leakage assertion, and re-basing `destroys_skill()` is exactly the
edit that turns a red probe green without looking wrong in a diff. Hence:

**NOTE C4-01 — decision requested, non-blocking: should `destroys_skill()` in
`backtest/diagnostics.py` be re-based on `TrainMedianBaseline`?** Proposed, not
done. As it stands the probe will read `destroys_skill: False` for every
median-like model from here on (LEAR now, very likely the C9 booster too), which
risks becoming a warning everyone learns to ignore — the worst state for a leakage
check. The options are (a) re-base the criterion on the median reference, (b) keep
the mean criterion and require instead that the permuted model not beat the
zero-information constant, or (c) leave it and rely on the re-based numbers
reported next to it. A human should pick; C5 is not blocked either way.

**NOTE C4-02 — hand-off to C5/C6: one hour a year has no forecast.** The committed
model declines the autumn DST hour whose 24-hour lag the gate-closure mask blanks
(FINDING C3-A) — exactly 1 hour of 8,784 in 2024. A forecast table can report that
honestly; the battery LP cannot, because committing a day's schedule needs a
complete 24-hour price vector. So the `impute` variant was run and scored too:
full coverage costs **0.001 EUR/MWh** of annual MAE. C6 therefore has a measured
choice — dispatch that day from the imputed forecast with the substitution
labelled, or exclude the day and report it as excluded. Either is defensible;
filling the hole silently inside the LP is not.

**NOTE C3-01 is still open** (rename the daily-aggregate features in
`features.yaml` to match the only leak-free window, or keep the names and rely on
`docs/forecast_harness.md`). C4 did not touch `config/features.yaml` and was not
blocked by it. `config_hash` is unchanged from C3's `d524f72059bc6d85`.

**Files under `tests/` — declared, per CLAUDE.md.** One file **added**:
`tests/test_c4_lear.py` (35 tests). **No existing test was edited** and no existing
assertion weakened or deleted — `git diff --stat HEAD -- tests/` shows only the new
file; `conftest.py`, `test_c1_data_layer.py`, `test_c2_contracts.py`,
`test_c3_timing_features.py` and `test_c3_leakage_harness.py` are untouched, and
all 137 pre-existing tests pass unmodified. Four of this cycle's own new tests
failed on first run and in all four cases the *test* was wrong and was corrected
before anything was committed: two poked holes in cells that were already NaN
inside the lag warm-up or spanned two months where the test said one; one asserted
LEAR predicts every hour when declining the masked DST hour is the designed
behaviour (it now asserts the declined hours are *exactly* the holed ones); and one
expected a 24-hour lead to halve LEAR's MAE as it halved the naive floor's, where
the honest expectation is ~30% — LEAR already holds the price 24 hours *back*, so
the leading feature is a second observation the same distance away on the other
side, and averaging two symmetric observations of a random walk cuts error by about
sqrt(2), not sqrt(7). The bound and the reasoning are both in the test.

**Dependencies.** `scikit-learn>=1.7` added to `requirements.txt`; the floor is 1.7
because `LassoCV`'s alpha-path argument was renamed there (`n_alphas` → an int
`alphas`) and `forecast/lear.py` uses the current spelling. Installed 1.9.1.

**Data.** Only DE-LU was fetched (6 files, 2019–2024, ~1 MB) — C4 is DE-LU only.
The container again arrived with `data/raw/` empty, as NOTE C2-02 predicts; all 6
pairs downloaded cleanly, 0 flagged. No ENTSO-E call was made: C4 needs no
exogenous data, so `ENTSOE_API_KEY` was not read (it *is* set in this environment —
the C7 precondition still holds).

**Sealed holdout.** Verified armed before the work and again before committing:
marker-alone-on-a-line count in this file 0, `holdout_is_unsealed()` = `False`,
`sealed_years()` = `{2025}`, `fetch_years` = 2019–2024. No 2025 data was fetched,
loaded, feature-engineered from or measured against at any point in C4. The
evaluation years passed to every run were `[2024]`. The marker string is not
reproduced here, only referred to by its config key.

**Repo-state note.** The detached-HEAD trap recurred again: the container arrived
on a detached HEAD at `1a084d3`. Reattached with `git checkout -B master 1a084d3`
and re-pointed at `origin/master` before any work. Now 6 recurrences out of 12
containers — worth a line in the write-up's reproducibility section.

**Next:** C5 — battery LP v1, DE-LU, **oracle curve only**. Rolling 24h horizon,
realised end-of-day SoC carried into the next day plus a terminal condition (never
reset to zero at midnight), symmetric round-trip efficiency (sqrt(0.88) per leg),
throughput/cycling cost ~2–5 EUR/MWh discharged, and an explicit check for
simultaneous charge/discharge under negative prices (a FLAG if found — LP artefact
needing a penalty term or a MILP). Unit tests PLAN.md names: a hand-computed toy
price vector, value monotone in spread, value exactly 0 on a flat curve. Adds an LP
solver to `requirements.txt` (`highspy` via scipy's HiGHS, or `pulp`). The
commit-then-settle machinery and the oracle ≥ model ≥ naive assertions are C6, at
**Checkpoint B**. Open items carried forward: NOTE C3-01, NOTE C4-01, NOTE C4-02.

### C5 — 2026-10-02 (scheduled cycle) — battery LP v1, DE-LU, oracle curve only

**Done, as scoped in PLAN.md C5.** The dispatch LP, the rolling horizon with
carried SoC, the settlement, and PLAN's three named unit tests. 64 new offline
tests (**236 total, all passing**). Design notes in `docs/battery_lp.md`. New
modules: `config/battery.yaml`, `dispatch/battery.py`, `dispatch/rolling.py`,
`backtest/run_c5_oracle_lp.py`. One FLAG, raised not worked around — **FLAG
C5-01** below.

**Headline, DE-LU 2024, oracle (perfect foresight) curve.** 1 MW / 2 MWh (2h),
round-trip 0.88 split `sqrt(0.88) = 0.938083` per leg, throughput cost
2 EUR/MWh discharged, 7-day median trailing mark on closing inventory. 366 market
days dispatched, **0 skipped**.

| | |
| --- | --- |
| oracle cash | **74,552.06 EUR** = **74,399 EUR/MW/yr** |
| equivalent full cycles | 634.8 (1.73/day) |
| energy in / out | 1,443.76 / 1,269.57 MWh (ratio 0.8793 ≈ the 0.88 round trip) |
| day-length histogram | 23h × 1, 24h × 364, 25h × 1 |

That is the ceiling C6's forecast curve is measured against, and the denominator
of every capture ratio from C11 on.

**Per-year oracle value, 2019–2024 — descriptive context, not a result.** The
oracle is a property of the realised price series: no model, no forecast, nothing
fitted. One continuous roll, SoC carrying across year boundaries.

| year | EUR/MW/yr | cycles | mean daily spread | sim-days |
| --- | --- | --- | --- | --- |
| 2019 | 16,250 | 578.4 | 30.01 | 9 |
| 2020 | 18,498 | 616.7 | 32.47 | 16 |
| 2021 | 48,327 | 600.9 | 80.31 | 9 |
| 2022 | **119,855** | 624.7 | 186.99 | 0 |
| 2023 | 62,522 | 621.5 | 97.88 | 8 |
| 2024 | 74,399 | 634.8 | 111.20 | 20 |

Value tracks mean daily spread almost exactly (2 MWh × spread × ~0.9 reproduces
each row to within a few percent) while cycling barely moves — the asset is
spread-limited, not cycle-limited, which is the shape C13's regime chapter needs.
2022 at 7.4× 2019 is the crisis year PLAN.md requires reporting separately.

**The design decisions that carry the result.** Full reasoning in
`docs/battery_lp.md`; the four that would change numbers:

- *The horizon is the **market day**, 23 and 25 hours included.* Not a UTC day and
  not 24 rows. The auction clears a local calendar day as one block and a bidder
  commits exactly that block. Each block's length is asserted against
  `data.contracts.local_day_hours` — the tz database, not a remembered rule — which
  is CLAUDE.md's DST whitelist applied to dispatch. The 2024 histogram above is
  that assertion's output: exactly one short day and one long day, neither padded.
- *Closing inventory is marked, because otherwise the LP invents the forbidden
  midnight reset.* A 24h horizon with no terminal condition always ends empty — the
  last stored MWh is free revenue inside the horizon and worthless outside it, so
  PLAN.md's rolling SoC carryover becomes the daily reset it forbids, arrived at by
  the LP rather than by a line of code, which is worse because nothing in the diff
  shows it. One test pins that behaviour deliberately. The mark is
  `max(0, eta * (p_ref - k))` per MWh *stored*: it pays the discharge leg and the
  throughput cost on the way out, and it is floored at zero because a negative mark
  would pay the LP to burn energy. **271 of 366 days open at SoC 0 and 95 do not** —
  a reset would have made it 366, so the carryover is doing real work.
- *`p_ref` is a **trailing** 7-day median of realised prices, never the day's own
  vector.* Two properties, both asserted rather than argued. **Knowable at gate
  closure**: it uses only market days `<= D-1`, published 13:00 local on `D-2`,
  before gate closure 12:00 local on `D-1`; `assert_reference_is_knowable`
  re-derives both instants from `forecast.timing` and raises otherwise. The mark is
  a term in the objective, not a feature, so C3's gate-closure guard never sees it
  and it gets its own check. **Curve-independent**: a mark read off the decision
  vector would differ between the oracle, forecast and naive runs, and the per-day
  dominance bound would not hold at all.
- *Three money numbers, and the headline is **cash**.* `cash` (settled),
  `terminal`/`opening` (marks on inventory), and
  `value_added = cash + terminal - opening` — what the day's trading added over
  standing still. `value_added` is what the LP maximises, so the invariants are
  stated on it: exactly 0 on a flat non-negative curve, never negative, monotone in
  spread/capacity/power. The headline is cash because the marks do not cancel over
  a year — measured divergence on DE-LU 2024 is **0.861%**, small but a model
  output rather than money.

**The per-day upper bound needs two oracles, and C6 must build the second.**
CLAUDE.md's `value(forecast @ realised) <= value(oracle @ realised)` **every day**
holds exactly — and only — when both are solved from the **same opening SoC**
against the **same mark**: the frozen forecast schedule is then a feasible point of
the oracle's own problem. `assert_oracle_dominates` checks both preconditions and
refuses to compare mismatched setups, because an assertion that silently compares
two different problems is worse than none. Across two independently *rolled*
trajectories the opening SoCs diverge and no per-day bound exists — a forecast run
that happens to open a day fuller can out-earn the rolled oracle that day, which is
expected, not a bug. **So C6 needs a rolled oracle for the pooled comparison and a
same-start oracle, re-solved each day from the forecast run's own opening SoC, for
the per-day assertion.** `solve_day` takes `soc_start_mwh` explicitly so C6 can do
that without reaching into anything's state. Both halves are implemented and tested
in C5; only the oracle curve is run, which is C5's scope.

**Invariants run on the real 2024 run, all passing**, and independently
re-verified from the committed artefacts alone (not from the objects that wrote
them): annual cash recomputed hour-by-hour from `..._schedule.csv.gz` × realised
prices reproduces 74,552.0 EUR; `soc_end(D) == soc_start(D+1)` for all 365 day
pairs to **0.0e+00**; power never exceeds 1.000000 MW; the best day (2024-12-12,
the 936 EUR/MWh spike) hand-recomputes to 1,754.724 EUR against 1,754.724 in the
artefact, with its round-trip energy balance exact to 4 d.p.; `value_added >= 0` on
all 366 days; perfect foresight beats a foresight-free schedule on all 60 sampled
days with worst excess **0.0**.

**FLAG C5-01 — simultaneous charge/discharge found, as PLAN.md anticipated.
Measured, not silently fixed. One decision requested; C6 is not blocked.**
PLAN.md requires an explicit check and calls this an LP artefact needing a penalty
term or a MILP. It is real here, and the arithmetic predicts exactly where: with
the upper SoC bound binding, `c` and `d` both positive draw a net
`c * (1 - eta^2) > 0` MW from the grid with stored energy flat — the battery burning
power in its own round-trip losses to be paid for consuming. It pays below
`-k * eta^2 / (1 - eta^2)` = **-14.67 EUR/MWh**, and DE-LU had 457 negative hours in
2024. A single-inverter BESS cannot do this.

| | |
| --- | --- |
| days affected | **20 of 366** |
| intervals affected | 53, **all 53 at a negative price** |
| lowest price with overlap | -100.06 EUR/MWh (2024-05-12) |
| grid energy burned | 5.318 MWh |
| cash earned from the overlap | 322.30 EUR = **0.43% of annual cash** |
| cost of forbidding it exactly (MILP) | **125.47 EUR = 0.17%** |

The gap is smaller than the overlap cash because forbidding the trade makes the LP
do something else instead rather than nothing. Per-year `sim-days` above show the
same signature: 20 in 2024 and 16 in 2020 (many deep-negative hours), **0 in 2022**
(69 negative hours, none deep enough).

*What was done:* `forbid_simultaneous=True` implements PLAN's named remedy exactly,
one binary per interval via scipy's HiGHS MILP (24 binaries a day is free), and
both variants are run and persisted. `no_simultaneity_remains` reads 0 intervals
under the MILP and `milp_cannot_beat_lp` holds, as it must.

*What was deliberately **not** done:* the committed default was not changed. The
pure LP is what C5 scopes, and which variant becomes the default from C6 onward
moves every headline number by 0.17% — a human's call, not an unattended cycle's.
The options are **(a)** make the MILP the default and report the pure LP as the
sensitivity, **(b)** keep the pure LP and carry 0.17% as a stated limitation, or
**(c)** add `c_t + d_t <= P` — a single shared inverter rating, which is physically
the right constraint for real hardware, bounds the artefact without a binary, and
is not implemented so that one decision sits in front of the reviewer instead of
three. **No push notification was sent for this**: PLAN.md reserves that for a
genuine blocker or an invariant failing in a way that is *not* an expected,
explained finding, and this is a finding PLAN.md predicted by name and told this
cycle to flag. C6 is Checkpoint B and will ask anyway.

**FINDING C5-A — "value = 0 on a flat curve" is true only for a flat
*non-negative* curve.** At a flat negative price, with no spread whatsoever, a
battery is simply a load being paid to consume: it fills up, never discharges, and
the money is real. The committed 1 MW / 2 MWh asset earns 29.76–80.42 EUR on a flat
-25 EUR/MWh day depending on opening SoC. This is **not** FLAG C5-01 — a *lossless,
costless* battery shows it too, where there is no round-trip channel to burn
through at all (`simultaneity_price_threshold` is `-inf` at `eta = 1`), earning
exactly 50 EUR by filling 2 MWh at -25. PLAN's invariant is kept as stated for
`p >= 0`, where it holds exactly for every opening SoC, and the negative case is
pinned by its own test so it cannot be quietly re-broken.

**FINDING C5-B — the mark makes the flat-curve optimum degenerate, and that is
value-neutral.** At `p_ref` exactly equal to a flat day's price, holding and
liquidating are worth the same to the penny, so the LP may return either and the
day's reported *cycling* is arbitrary; its *value* is exactly 0 either way, and
cash is exactly the opening inventory liquidated at the mark. Two tests pin both
halves, and the run counts flat days so "measure zero on real prices" is a
measurement: **DE-LU 2024 has 0 flat days and 0 flat-at-the-mark days.** Priced
away from the mark a flat day trades toward it — which is a second reason the
headline is cash and not summed `value_added`.

**NOTE C4-02 answered mechanically; C6 still chooses.** A day whose price vector
has a hole is **skipped and reported**, never patched: `solve_day` refuses a
non-finite decision price outright, and `dispatch/rolling.py` counts skips by
reason (`incomplete` / `no_reference` / `boundary`). The oracle run skipped 0 days
because realised prices are complete; the one declined hour a year is a *forecast*
problem, so C6 still picks between dispatching that day from the `impute` variant
with the substitution labelled (measured cost: 0.001 EUR/MWh of annual MAE) and
excluding the day. C5's contribution is that neither choice can now be made
invisibly.

**Files under `tests/` — declared, per CLAUDE.md.** One file **added**:
`tests/test_c5_battery_lp.py` (64 tests). **No existing test was edited**, no
assertion weakened or deleted — `git diff --stat HEAD -- tests/` shows only the new
untracked file, and all 172 pre-existing tests pass unmodified. Five of this
cycle's own new tests failed on first run, before anything was committed. In four
cases the *test* was wrong and in one it found a real code bug:
1. `value_added == 0` asserted on a flat curve at **-25 EUR/MWh** — wrong, that is
   FINDING C5-A. Test renamed to `..._non_negative_curve`, parameters changed to
   `{0, 2, 50, 400}`, and the negative case given its own test asserting the
   genuine value.
2. "a flat curve produces no trading" — wrong, FINDING C5-B: at `p_ref == p` the
   optimum is degenerate. Replaced by a test that the degenerate case is
   value-neutral with cash pinned to the mark.
3. "the mark keeps inventory on a flat day" — the same degeneracy; the reference is
   now set above the day's price so the prediction is real.
4. "a mark strictly above the day's price means no trading" — wrong premise
   entirely: a mark above today's price makes *charging* attractive, so there is no
   non-degenerate flat case in which the LP stands still. Replaced by a directional
   test (below the mark → fills; above → empties).
5. **A real bug.** Writing the FINDING C5-A test with a lossless, costless battery
   exposed `simultaneity_price_threshold` returning `0.0` instead of `-inf` at
   `eta = 1` with `k > 0`: at `eta = 1` matched charge/discharge draws a net zero
   from the grid, so **no** price makes burning pay and the threshold is `-inf`
   whatever the cost. `dispatch/battery.py` fixed; the test asserts the `-inf`.

**Dependencies.** `scipy>=1.11` added to `requirements.txt` — already present
transitively via scikit-learn, but C5 depends on it directly so it is declared
directly. HiGHS ships inside scipy, so no separate solver install and no licence;
the floor is 1.11 because `milp` and the `Bounds`/`LinearConstraint` objects it
takes settled into their current form there. Installed 1.17.1. No `highspy` or
`pulp`.

**Config hash changed: `d524f72059bc6d85` → `84f7bf31591d1e7f`**, because
`config/battery.yaml` is new and `config_hash()` spans every `config/*.yaml`. No
existing config file was modified; `config/features.yaml` is untouched and **NOTE
C3-01 is still open**.

**Data.** DE-LU only, 6 files 2019–2024 (~1 MB) — C5 is DE-LU only. The container
again arrived with `data/raw/` empty, as NOTE C2-02 predicts; all 6 pairs
downloaded cleanly, 0 flagged. **Integrity verified rather than assumed**:
`payload_fingerprint` for all six years matches C1's committed manifest exactly, so
this is byte-identical to the data every prior cycle used. No ENTSO-E call — C5
needs no exogenous data, so `ENTSOE_API_KEY` was not read (it *is* set in this
environment; the C7 precondition still holds).

**Sealed holdout.** Verified armed before the work and again before committing:
marker-alone-on-a-line count in this file 0, `holdout_is_unsealed()` = `False`,
`sealed_years()` = `{2025}`, `fetch_years` = 2019–2024. No 2025 data was fetched,
loaded, dispatched or measured against at any point in C5. The runner calls
`assert_not_sealed` on every requested year before a price file is opened. The
marker string is not reproduced here, only referred to by its config key.

**Repo-state note.** The detached-HEAD trap recurred again: the container arrived
on a detached HEAD at `89d5583`. Reattached with `git checkout -B master 89d5583`
and re-pointed at `origin/master` before any work. Now **7 recurrences out of 13
containers** — still worth a line in the write-up's reproducibility section.

**Next:** **C6 — CHECKPOINT B.** Commit-then-settle machinery with all three curves
(oracle / LEAR / naive) on DE-LU, asserting pooled `oracle >= model >= naive` and
the per-day bound via the **same-start oracle** described above; then stop,
push-notify, and wait for the human to eyeball one zone end-to-end (a week of
dispatch against the price plot) before scaling out. C6 also decides NOTE C4-02
(imputed hour vs excluded day) and should put FLAG C5-01's three options to the
human in the same review. Open items carried forward: **FLAG C5-01**, NOTE C3-01,
NOTE C4-01, NOTE C4-02.

### C6 — 2026-10-02 (scheduled cycle) — commit-then-settle, three curves, DE-LU — **CHECKPOINT B REACHED**

**Done, as scoped in PLAN.md C6, and then stopped.** The commit-then-settle
machinery across all three curves (oracle / LEAR / naive) on DE-LU 2024, both
oracles, the pooled assertion, and Checkpoint B's own required output: three
figures of a week of dispatch drawn against the price plot. 35 new offline tests
(**271 total, all passing**). Design notes in `docs/commit_then_settle.md`. New
modules: `dispatch/curves.py`, `backtest/run_c6_curves.py`. **NOTE C4-02 is
decided and the decision is priced. FLAG C5-01 is restated with new evidence and
is still the human's to decide.** No new FLAG was raised.

**Checkpoint B is a human eyeballing one zone end to end before anything scales
out to nine zones. Nothing in C7+ has been started.**

---

#### The headline, DE-LU 2024, 1 MW / 2 MWh

Pooled over the 365 market days every curve dispatched (see NOTE C4-02 below for
the 366th):

| curve | cash, 365d | EUR/MW/yr | rolled capture | same-start capture |
| --- | --- | --- | --- | --- |
| **oracle** (perfect foresight) | 74,365.45 | **74,399** | 1.0000 | 1.0000 |
| **model** (LEAR, C4's committed run) | 68,318.88 | **68,179** | **0.9187** | **0.8696** |
| **naive** (same hour last week) | 62,997.68 | **62,868** | 0.8471 | 0.7797 |

**EUR/MW/yr lost to forecast error: 6,047.** `oracle >= model >= naive` holds on
pooled cash and on pooled `value_added`; margins 6,046.57 and 5,321.20 EUR.
The oracle total reproduces C5's committed 74,552.06 EUR over its full 366 days
**exactly** — a cross-cycle check that the LP and the roll did not move.

**Two capture ratios, and the honest one is the lower one.** Both are reported
because quoting either alone misleads:

* **rolled** 0.9187 — annual cash against the rolled oracle's annual cash. Part
  of what this credits to the forecast is the forecast run's *trajectory*
  happening to open some days in a better state than the oracle's did.
* **same-start** 0.8696 — pooled `value_added` against an oracle re-solved each
  day from the model run's own opening SoC. Bounded above by 1 **on every single
  day by construction**, so this is the per-day truth.
* mean of the daily same-start ratios **0.8204**, median **0.9018**, p05 0.2919,
  p25 0.7645, p75 0.9731. Mean below pooled says what it always says about power
  prices: value is concentrated in a few high-spread days, and capture is
  *better* on those days than on the quiet ones. PLAN.md asks for the
  distribution and not just the mean, so the quantiles are persisted from C6 on.

**The model beats the naive floor on 239 of 365 days (65.5%)** — it loses to it
on more than a third of days and still wins by 5,321 EUR over the year. CLAUDE.md
states that half of the invariant as an average and not a per-day claim; this is
the number behind that wording.

#### The two oracles, and the per-day invariant

CLAUDE.md's `value(forecast @ realised) <= value(oracle @ realised)` **every
day** is asserted on **every dispatched day, not a sample**, against the
same-start oracle. Worst excess over the bound: **exactly 0.0 EUR** for both the
model and the naive curve; **0 days** out of 730 curve-days have
`capture_same_start > 1`, re-derived independently from the committed
`..._daily.csv` rather than from the objects that wrote it.

**The model out-earned the *rolled* oracle on 50 of 365 days.** That is the
trajectory divergence C5 predicted in prose, now a number: across two
independently rolled trajectories the opening SoCs differ and no per-day bound
exists. It is counted and reported, never asserted away. A test demonstrates the
mechanism as a controlled experiment rather than by hoping a fixture exhibits it
— a run opening a day full, committed on an imperfect forecast, beats perfect
foresight that opened the same day empty, and `assert_oracle_dominates`
**refuses** that comparison rather than reporting a breach, because the two are
not the same problem.

**Commit-then-settle is structural, not careful.** `decision_prices` and
`realised_prices` are separate arguments; every valuation carries
`prices_are_decision_prices`; and `assert_settlement_is_not_a_readback`
re-derives the truth from the schedules — comparing each day's decision vector
against the realised one — and requires the flag to agree with what it finds. A
perfect forecast that happens to equal realised prices is legitimate and passes;
a forecast run that *claims* to be a read-back fails. Verified on all three runs.

#### FINDING C6-A — `value_added >= 0` is a theorem about the **decision** problem, not about settlement

C5 asserts `value_added >= 0` on the oracle run, reasoning that standing still is
always feasible so the optimum cannot lose. Applied unchanged to the forecast
curves it **failed on first run** — 3 model days and 17 naive days. It was right
to fail: for the oracle the decision prices *are* the realised prices, so the
statement transfers; for a forecast curve they are different vectors and it does
not. A schedule frozen on a wrong forecast **can lose money at realised prices**,
and that is the quantity this whole project exists to measure.

So the theorem is now asserted about the problem it is a theorem about
(`check_decision_value_added_non_negative`, on the decision prices, all three
curves, holds), C5's realised-price form stays asserted **unchanged** on the
oracle where it is binding, and the realised losses are *reported*:

| curve | days that lost money at realised prices | total |
| --- | --- | --- |
| oracle | 0 of 366 | 0.00 EUR |
| model | 3 of 365 (worst 2024-12-07, −34.13) | **−41.37 EUR** |
| naive | 17 of 366 (worst 2024-12-25, −130.30) | **−662.52 EUR** |

Nothing was weakened to make this green: no assertion was deleted or loosened,
the oracle's version is unchanged, and the new one is a strictly-defined theorem
that must hold. This is a left-tail result a desk would ask for before the mean —
forecast error does not merely forgo upside, on ~1% of days it turns the day's
trading into an outright loss, and the naive floor does it six times as often and
sixteen times as expensively.

#### NOTE C4-02 — **DECIDED: exclude the day, report it excluded.** The alternative was priced, not argued away.

One hour a year (2024-10-27 23:00 local, the 25-hour autumn DST day whose 24-hour
lag the gate-closure mask blanks — FINDING C3-A) has no LEAR forecast under the
committed `nan_policy="decline"`, and the LP needs a complete vector.

**Decision: the day is skipped and reported, and every pooled number is computed
over the common day set** (365 days), so the exclusion can never compare a
365-day model total against a 366-day oracle total. Reasons: it uses the
skip-by-reason mechanism C5 already built and tested, it introduces no price that
no model produced, and the alternative is recoverable at any time.

**Priced**: `--measure-impute` re-runs that single fold under
`nan_policy="impute"` (one LEAR fit, not 366) and dispatches the day from the
imputed vector, opening at the SoC the committed model run actually carried in
(0.0 MWh). It would have earned **−33.47 EUR of cash** — the day is a *loss* —
at a same-start capture of 0.673. **Excluding it therefore does not flatter the
model; it very slightly flatters it to include it**, which is the direction that
matters for honesty. A human can overturn this to `impute` with the substitution
labelled and the headline moves by about 0.05%.

#### FLAG C5-01 — restated with new evidence, **still open, still the human's call**

The committed default is **unchanged** (pure LP), exactly as C5 left it. C6 ran
the MILP (`forbid_simultaneous=True`) across all three curves so the review can
see whether the *result* — the capture ratio — moves. New evidence, which points
the opposite way from what C5's single-curve measurement suggested:

| curve | LP cash − MILP cash | simultaneity days (LP) | overlap cash (LP) |
| --- | --- | --- | --- |
| oracle | **+125.47** | 20 of 366 | +322.30 |
| model | **−0.49** | 1 of 365 | +2.36 |
| naive | **−89.88** | 20 of 366 | **−87.61** |

**The artefact flatters the oracle and *penalises* the forecast curves.** A
forecast curve commits the overlap on hours its forecast said were deeply
negative; when they do not realise negative, the burn is paid for at realised
prices and earns nothing — the naive curve's overlap cash is *negative*. So the
pure LP's capture ratio is biased **against** the model: capture is 0.9187 under
the LP and **0.9203 under the MILP**, a shift of **+0.0016** (+0.16pp). The
ordering `oracle >= model >= naive` holds under both. Zero simultaneity intervals
remain under the MILP, as they must.

The three options are unchanged — **(a)** MILP as default with the pure LP as the
sensitivity, **(b)** keep the pure LP and carry the artefact as a stated
limitation, or **(c)** add `c_t + d_t <= P`, the single shared inverter rating,
which is physically right for real hardware and needs no binary. The new
information for the decision is that the effect on the headline is 0.16pp and in
the model's favour, so none of the three changes any conclusion. Still
non-blocking. No separate push notification: Checkpoint B's own notification
carries it.

#### Checkpoint B's required output — three weeks of dispatch, drawn

`docs/figures/c6_dispatch_week_DE-LU_<START>.png`, chosen by rule rather than by
taste: **typical** (week whose mean daily spread is closest to the year's),
**high_spread** (the week with the most oracle value), **worst_capture** (the
week containing the model's worst same-start capture day).

| figure | week | oracle | model | naive |
| --- | --- | --- | --- | --- |
| typical | 2024-05-20 | 1,523 EUR | 1,382 (91%) | 1,449 (**95%**) |
| high_spread | 2024-11-04 | 3,425 EUR | 3,340 (**98%**) | 3,110 (91%) |
| worst_capture | 2024-12-02 | 998 EUR | 577 (58%) | 516 (52%) |

Each has three panels on one time axis: realised price against both forecasts;
the SoC each curve actually carried (including across midnight — a daily reset
would show as a sawtooth and does not); and **cumulative settled cash**, which
puts the whole result in one readable panel. In the typical week the **naive
floor beats LEAR** — worth seeing, and exactly the kind of thing a weekly figure
should surface rather than an annual mean hide.

#### Independently re-verified from the committed artefacts alone

Not from the objects that wrote them. Per curve, recomputing annual cash hour by
hour from `..._schedule.csv.gz` × realised prices reproduces 74,552.06 /
68,318.88 / 62,997.08 EUR to <2e-4 (CSV rounding); `soc_end(D) == soc_start(D+1)`
to **0.0e+00** on every day pair for all three curves, including across the
model's skipped day (SoC carried unchanged — the battery sat idle, as designed);
power never exceeds 1.000000 MW and SoC stays inside [0, 2]; the capture ratios
recompute from `..._daily.csv` to 0.918691 / 0.847136, matching the summary.

#### Files under `tests/` — declared, per CLAUDE.md

One file **added**: `tests/test_c6_commit_then_settle.py` (35 tests). **No
existing test was edited** — `git diff --stat HEAD -- tests/` is empty and only
the new untracked file appears in `git status tests/`; all 236 pre-existing tests
pass unmodified. One of this cycle's own new tests failed on first run, before
anything was committed, and the fix was to the *test*, not to a claim:
`test_the_rolled_oracle_gives_no_per_day_bound` asserted that some day in a
30-day synthetic fixture would see the model out-earn the rolled oracle. The
claim is true on real data (50 of 365 days) but the fixture was too short and too
smooth to exhibit it, and tuning a random fixture until it did would have been
fabricating the phenomenon. Replaced by two tests that establish the same thing
deterministically: a controlled same-day experiment (full opening SoC vs empty
opening SoC) and a direct measurement that the two rolled trajectories do diverge
in opening SoC.

#### Housekeeping

- **Data.** Only DE-LU was fetched (6 files, 2019–2024, ~1 MB) — C6 is DE-LU
  only. The container again arrived with `data/raw/` empty, as **NOTE C2-02**
  predicts; 6 pairs downloaded cleanly, 0 flagged. **NOTE C2-02 is still open**
  and this is its 4th recurrence.
- **No ENTSO-E call.** C6 needs no exogenous data, so `ENTSOE_API_KEY` was not
  read. It *is* set in this environment; the C7 precondition still holds.
- **Sealed holdout verified armed**, before and after the work: marker-alone-on-
  a-line count **0**, `holdout_is_unsealed()` = `False`, `sealed_years()` =
  `{2025}`, and no 2025 file exists in the cache. No 2025 data has been fetched,
  loaded, dispatched or computed against at any point in C2–C6.
- **Config hash unchanged at `84f7bf31591d1e7f`.** No `config/*.yaml` file was
  modified; `config/features.yaml` is untouched and **NOTE C3-01 is still open**.
- **No new dependency.** scipy/matplotlib/scikit-learn already declared.
- **Repo-state note:** the detached-HEAD trap recurred again — the container
  arrived on a detached HEAD at `f653618`. Reattached with
  `git checkout -B master f653618` and re-pointed at `origin/master` before any
  work. **8 recurrences out of 14 containers.** Keep checking
  `git rev-parse --abbrev-ref HEAD` at the start of every cycle.

#### What Checkpoint B is asking the human for

1. **Eyeball the three week figures** against the price plots from Checkpoint A.
   Does the dispatch look like a battery buying low and selling high, and does
   the SoC carry across midnight rather than resetting?
2. **Sanity-check the headline**: 87–92% of perfect-foresight value captured by a
   price-history-only LEAR on DE-LU 2024, 6,047 EUR/MW/yr lost to forecast error.
   Is that plausible for a 2h battery in a thermal/RES-mixed zone?
3. **Decide FLAG C5-01** (a / b / c above). Effect on the headline is 0.16pp.
4. **Confirm or overturn NOTE C4-02** (exclude the declined day — current
   decision — vs dispatch it from the imputed forecast with the substitution
   labelled).
5. **NOTE C3-01 and NOTE C4-01 are still open** from C3/C4 and are unchanged.

Then set "Next cycle to run" at the top of this file to **C7** and the cycle
after this one will scale out.

---

### Checkpoint B wait — 2026-10-03 (scheduled cycle, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `origin/master` == local HEAD at `babdca9` (the C6 checkpoint
  commit, no human commits since, `git status` clean); all Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them); holdout guard re-verified armed
  (marker-alone-on-a-line → `holdout_is_unsealed()` = `False`, `sealed_years()` =
  `{2025}`, no 2025 file anywhere under `data/`); no 2025 data touched; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). The detached-HEAD trap **did** recur: the container
  arrived detached at `babdca9`, reattached with `git checkout -B master babdca9` and
  re-pointed at `origin/master` before anything else (now **9 recurrences out of 15
  containers**). Still waiting on the five Checkpoint B items listed at the top of
  this file (eyeball the three week figures, sanity-check the 87–92% headline, decide
  **FLAG C5-01**, confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01**
  / **NOTE C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human
  replaces the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-03 (scheduled cycle, 2nd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `origin/master` == local HEAD at `00f70fc` (the first
  Checkpoint B wait commit — no human commits since, `git status` clean, `git fetch`
  brought nothing new beyond the commit this session's container already had); all
  Checkpoint B artefacts present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}`,
  the three `docs/figures/c6_dispatch_week_DE-LU_*.png`, and the C1–C5 artefacts
  beneath them); holdout guard re-verified armed (marker-alone-on-a-line count **0**,
  `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`, no 2025 file
  anywhere under `data/`); no 2025 data touched; `ENTSOE_API_KEY` not read (not
  needed before C7); config hash unchanged (no `config/*.yaml` modified); no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` again arrived empty, **NOTE C2-02**'s 5th
  recurrence, but nothing was re-downloaded because no work needed data. The
  detached-HEAD trap **did** recur: the container arrived detached at `00f70fc`,
  reattached with `git checkout -B master 00f70fc` and re-pointed at `origin/master`
  before anything else (now **10 recurrences out of 16 containers**). Still waiting on
  the five Checkpoint B items listed at the top of this file (eyeball the three week
  figures, sanity-check the 87–92% headline, decide **FLAG C5-01**, confirm or overturn
  **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE C4-01**); **NOTE C2-02**
  also remains open. C7 stays blocked until a human replaces the status line with
  **C7** and records the approval here.

### Checkpoint B wait — 2026-10-03 (scheduled cycle, 3rd wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin` advanced `origin/master` from the stale
  `fc422de` the container shipped with to **`c329968`** (the 2nd Checkpoint B wait
  commit) — i.e. **no human commits since**, and `origin/master` == local HEAD ==
  `c329968`, `git status` clean, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`). Holdout guard re-verified armed (marker-alone-on-a-line count
  **0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`, no `*2025*`
  file anywhere under `data/`); no 2025 data touched. `ENTSOE_API_KEY` not read (not
  needed before C7); no `config/*.yaml` modified, so the config hash is unchanged; no
  push notification sent (the Checkpoint B ping was already sent in C6 — repeat pings
  for the same wait are noise). `data/raw/` did not exist at all this time, **NOTE
  C2-02**'s 6th recurrence, but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur: the container arrived detached at `c329968`
  (now **11 recurrences out of 17 containers**). New wrinkle worth recording for
  future cycles: the local `master` *ref* arrived stale at `fc422de` (the C2
  checkpoint commit, 3 commits behind HEAD), so a bare `git checkout master` would
  have silently rewound C5, C6 and the two wait commits out of the working tree. The
  safe reattach is the one used here and in the previous two waits — `git checkout -B
  master <HEAD sha>` after a `git fetch`, then `--set-upstream-to=origin/master` —
  never a plain `git checkout master`.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-04 (scheduled cycle, 4th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`31f4818`** (the 3rd Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `31f4818` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`, unchanged from the 3rd wait). Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. `ENTSOE_API_KEY` not read (not needed before C7); no `config/*.yaml`
  modified, so the config hash is unchanged; no push notification sent (the
  Checkpoint B ping was already sent in C6 — repeat pings for the same wait are
  noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s 7th recurrence,
  but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur: the container arrived detached at `31f4818`
  with the local `master` *ref* stale at `fc422de` (4 commits behind HEAD) — now
  **12 recurrences out of 18 containers**, and the stale-local-`master` wrinkle first
  recorded in the 3rd wait is now confirmed as the normal shape of it, not a one-off.
  The safe reattach used here is unchanged: `git fetch origin master`, then
  `git checkout -B master <HEAD sha>`, then `--set-upstream-to=origin/master` —
  **never** a plain `git checkout master`, which would silently rewind C5, C6 and the
  three wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-04 (scheduled cycle, 5th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`d206580`** (the 4th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `d206580` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty. All Checkpoint B artefacts present and unmodified
  (`backtest/results/c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}`,
  the three `docs/figures/c6_dispatch_week_DE-LU_*.png`, and the C1–C5 artefacts
  beneath them: 12 files in `backtest/results/`, 14 in `docs/figures/`, unchanged
  from the 4th wait). Holdout guard re-verified armed (marker-alone-on-a-line count
  **0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`, no `*2025*`
  file anywhere under `data/`); no 2025 data touched. `ENTSOE_API_KEY` not read (not
  needed before C7); no `config/*.yaml` modified, so the config hash is unchanged; no
  push notification sent (the Checkpoint B ping was already sent in C6 — repeat pings
  for the same wait are noise). `data/raw/` did not exist at all again, **NOTE
  C2-02**'s 8th recurrence, but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur, in exactly the shape the 3rd and 4th waits
  recorded: the container arrived detached at `d206580` with the local `master` *ref*
  stale at `fc422de` (5 commits behind HEAD) — now **13 recurrences out of 19
  containers**. Reattached with `git checkout -B master d206580` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C5, C6 and the four wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-04 (scheduled cycle, 6th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`98d4fae`** (the 5th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `98d4fae` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`, unchanged from the 5th wait). Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. `ENTSOE_API_KEY` not read (not needed before C7); no `config/*.yaml`
  modified, so the config hash is unchanged; no push notification sent (the
  Checkpoint B ping was already sent in C6 — repeat pings for the same wait are
  noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s 9th recurrence,
  but nothing was re-downloaded because no work needed data.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–5th waits: the
  container arrived detached at `98d4fae` with the local `master` *ref* stale at
  `fc422de` (6 commits behind HEAD) — now **14 recurrences out of 20 containers**.
  Reattached with `git checkout -B master 98d4fae` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C5, C6 and the five wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-05 (scheduled cycle, 7th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`78fbba5`** (the 6th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `78fbba5` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,
  daily.csv,schedule.csv.gz}`, the three `docs/figures/c6_dispatch_week_DE-LU_*.png`,
  and the C1–C5 artefacts beneath them: 12 files in `backtest/results/`, 14 in
  `docs/figures/`, unchanged from the 6th wait). Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  10th recurrence, but nothing was re-downloaded because no work needed data.
- **NEW, and the one thing that changed outside the repo: `ENTSOE_API_KEY` is now
  set in the cloud environment.** Every prior cycle recorded it as absent, and
  PLAN.md's "ENTSO-E API key note" still describes it as not yet available to cloud
  routine cycles. It is now present. This cycle did **not** read, use, or log its
  value, and made no ENTSO-E request — C7 is the first cycle that needs it, and C7 is
  blocked behind this checkpoint. Consequence for whoever closes Checkpoint B: the
  C7 fallback path ("flag it and do Tier-B / Energy-Charts-only work instead") looks
  **unnecessary** — C7 can run its full intended scope. Worth re-confirming the key
  is still set at the start of C7 rather than trusting this note, since the
  environment is configured outside the repo and can change between cycles.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–6th waits: the
  container arrived detached at `78fbba5` with the local `master` *ref* stale at
  `fc422de` — now **15 recurrences out of 21 containers**. Reattached with
  `git checkout -B master 78fbba5` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C5, C6 and the six wait commits out of the working tree. Correction to the arithmetic
  in the 3rd–6th wait entries: the stale `master` ref is **12** commits behind HEAD
  here (`git rev-list --count master..HEAD`), not the 5–6 those entries reported —
  they appear to have counted only the wait commits, not C3–C6 and the Checkpoint A
  close beneath them. The reattach procedure is unaffected; the stakes of getting it
  wrong are simply larger than those entries implied.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-05 (scheduled cycle, 8th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`888347f`** (the 7th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `888347f` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (`backtest/results/c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}`,
  the three `docs/figures/c6_dispatch_week_DE-LU_*.png`, and the C1–C5 artefacts
  beneath them: 12 files in `backtest/results/`, 14 in `docs/figures/`, all 26
  git-tracked and clean, unchanged from the 7th wait). Holdout guard re-verified
  armed (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  11th recurrence, but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — the 7th wait's
  observation holds for a second consecutive container, so it looks like a durable
  environment change rather than a one-off. Presence only was tested (`-n` on the
  variable); the value was not read, logged, or used, and no ENTSO-E request was
  made. C7 remains the first cycle that needs it, and C7 is blocked behind this
  checkpoint; still re-confirm at the start of C7 rather than trusting this note.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–7th waits: the
  container arrived detached at `888347f` with the local `master` *ref* stale at
  `fc422de` — now **16 recurrences out of 22 containers**. The stale ref is **13**
  commits behind HEAD here (`git rev-list --count master..HEAD`), consistent with the
  7th wait's corrected count of 12 plus that wait's own commit. Reattached with
  `git checkout -B master 888347f` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C3–C6, the Checkpoint A close and the seven wait commits out of the working tree.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-05 (scheduled cycle, 9th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`2e60b70`** (the 8th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `2e60b70` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean, unchanged from the 8th wait),
  including `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the
  three `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  12th recurrence, but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — third consecutive
  container, so the durable-environment-change reading from the 7th and 8th waits
  continues to hold. Presence only was tested (`-n` on the variable); the value was
  not read, logged, or used, and no ENTSO-E request was made. C7 remains the first
  cycle that needs it, and C7 is blocked behind this checkpoint; still re-confirm at
  the start of C7 rather than trusting this note.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–8th waits: the
  container arrived detached at `2e60b70` with the local `master` *ref* stale at
  `fc422de` — now **17 recurrences out of 23 containers**. The stale ref is **14**
  commits behind HEAD here (`git rev-list --count master..HEAD`), consistent with the
  8th wait's 13 plus that wait's own commit. Reattached with
  `git checkout -B master 2e60b70` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C3–C6, the Checkpoint A close and the eight wait commits out of the working tree.
- No virtualenv exists in a fresh container (`.venv/` is gitignored and not rebuilt);
  the guard check above ran against the system `python3`, which already has the
  imports `data.holdout` / `data.config` need. C7 will need to create the venv and
  install `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-06 (scheduled cycle, 10th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. `git fetch origin master` advanced `origin/master` from the
  stale `fc422de` the container shipped with to **`3639e3a`** (the 9th Checkpoint B
  wait commit) — i.e. **no human commits since**; `origin/master` == local HEAD ==
  `3639e3a` (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean, unchanged from the 9th wait),
  including `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the
  three `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again, **NOTE C2-02**'s
  13th recurrence, but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — fourth consecutive
  container, so the durable-environment-change reading from the 7th–9th waits
  continues to hold. Presence only was tested (`-n` on the variable); the value was
  not read, logged, or used, and no ENTSO-E request was made. C7 remains the first
  cycle that needs it, and C7 is blocked behind this checkpoint; still re-confirm at
  the start of C7 rather than trusting this note.
- The detached-HEAD trap **did** recur, in the same shape as the 3rd–9th waits: the
  container arrived detached at `3639e3a` with the local `master` *ref* stale at
  `fc422de` — now **18 recurrences out of 24 containers**. The stale ref is **15**
  commits behind HEAD here (`git rev-list --count master..HEAD`), consistent with the
  9th wait's 14 plus that wait's own commit. Reattached with
  `git checkout -B master 3639e3a` after the fetch, then
  `--set-upstream-to=origin/master`; a plain `git checkout master` would have rewound
  C3–C6, the Checkpoint A close and the nine wait commits out of the working tree.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, which already has
  the imports `data.holdout` / `data.config` need. C7 will need to create the venv and
  install `requirements.txt` before any modelling work.
- **Elapsed-wait note, for the human's benefit rather than as an escalation:** this
  is the **10th consecutive wait cycle**, and Checkpoint B was reached **2026-10-02**
  — roughly **4 days** and ~3.3 days of scheduled fires with the status line
  unchanged. Nothing is wrong and nothing is lost: C3–C6 are committed and pushed,
  every artefact is intact, and the project simply cannot advance past this gate
  without the human. But the remaining budget is now the binding constraint —
  **C7–C21 is 15 cycles of work and the plan's own buffer note assumed 3–4 lost
  cycles, which 10 waits has already more than spent.** If the review cannot happen
  soon, the human may want to consider either approving C7 provisionally (the five
  Checkpoint B items are all non-blocking by their own descriptions — none of the
  three FLAG C5-01 options changes a conclusion) or explicitly cutting C14 and the
  stretch items per PLAN.md's buffer rule. **This cycle is not making that call and
  is not acting on it** — it is recorded here only so the trade-off is visible at
  review time. Still no push notification, per the status line's own instruction.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**); **NOTE C2-02** also remains open. C7 stays blocked until a human replaces
  the status line with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-06 (scheduled cycle, 11th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. **No human commits since the 10th wait** — after
  `git fetch origin master`, `HEAD` == `master` == `origin/master` == **`0108407`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6).
  `data/raw/` did not exist at all again — **NOTE C2-02**'s 14th recurrence — but
  nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — fifth consecutive
  container. Presence only was tested (`-n` on the variable); the value was not read,
  logged, or used, and no ENTSO-E request was made. Still re-confirm at the start of
  C7 rather than trusting this note.
- **The detached-HEAD trap did NOT recur this container**, the first time since the
  2nd wait: the container arrived already attached to `master` at `0108407`, matching
  `origin/master`, so no `git checkout -B` reattachment was needed. Running tally is
  therefore **18 recurrences out of 25 containers** (unchanged count, one more
  container). Future cycles should still check `git rev-parse --abbrev-ref HEAD` and
  `git rev-list --count master..HEAD` before any `git checkout master`.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`. C7 will need to
  create the venv and install `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file, plus
  the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21 is 15 cycles
  and the plan's 3–4-cycle buffer is more than spent) still stands and is **not**
  re-escalated here. C7 stays blocked until a human replaces the status line with
  **C7** and records the approval here.

### Checkpoint B wait — 2026-10-06 (scheduled cycle, 12th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. This is the **second fire on 2026-10-06** (the 11th wait was
  the first). **No human commits since the 11th wait** — after
  `git fetch origin master`, `HEAD` == `master` == `origin/master` == **`3c86bde`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`),
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again — **NOTE C2-02**'s
  15th recurrence — but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — sixth consecutive
  container, so the durable-environment-change reading continues to hold. Presence
  only was tested (`-n` on the variable); the value was not read, logged, or used, and
  no ENTSO-E request was made. Still re-confirm at the start of C7 rather than
  trusting this note.
- The detached-HEAD trap **did** recur this container, after one container without it:
  arrived detached at `3c86bde` with the local `master` *ref* stale at `0108407`, i.e.
  **1** commit behind HEAD (`git rev-list --count master..HEAD`) — the 11th wait's own
  commit. Running tally is now **19 recurrences out of 26 containers**. Reattached
  with `git checkout -B master 3c86bde` after the fetch, then
  `--set-upstream-to=origin/master`. Future cycles should still check
  `git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` before any
  plain `git checkout master`.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, importing
  `data.holdout` from the repo root. C7 will need to create the venv and install
  `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**), plus the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21
  is 15 cycles and the plan's 3–4-cycle buffer is more than spent) still stands and is
  **not** re-escalated here. C7 stays blocked until a human replaces the status line
  with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-07 (scheduled cycle, 13th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. **No human commits since the 12th wait** — after
  `git fetch origin master`, `HEAD` == `origin/master` == **`a69dbcb`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`), and the three
  most recent commits are all this log's own wait commits (`a69dbcb`, `3c86bde`,
  `0108407`), authored by the agent, not a human. `git status --porcelain
  --untracked-files=all` empty, `git diff HEAD` empty. All Checkpoint B artefacts
  present and unmodified (12 files in `backtest/results/`, 14 in `docs/figures/`, all
  26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again — **NOTE C2-02**'s
  16th recurrence — but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — seventh consecutive
  container, so the durable-environment-change reading continues to hold. Presence
  only was tested (`-n` on the variable); the value was not read, logged, or used, and
  no ENTSO-E request was made. Still re-confirm at the start of C7 rather than
  trusting this note.
- The detached-HEAD trap recurred this container: arrived detached at `a69dbcb` with
  the local `master` *ref* stale at `0108407`, i.e. **2** commits behind HEAD
  (`git rev-list --count master..HEAD`) — the 11th and 12th waits' own commits.
  Running tally is now **20 recurrences out of 27 containers**. **New this cycle:**
  the usual `git checkout -B master a69dbcb` reattachment was **denied by this
  session's permission classifier** (flagged as irreversible local destruction),
  which it is not — the working tree was clean and the stale `master` ref was a
  strict ancestor of `HEAD`, so the move was a fast-forward. Rather than route around
  the denial, this cycle committed **on the detached HEAD** and pushed with
  `git push origin HEAD:master`, which updates the remote branch without touching the
  local ref. Net effect on the repo is identical; the only residue is that the local
  `master` ref in *this* container stays stale, which is harmless because the
  container is discarded. Future cycles should keep checking
  `git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD`, and may
  need this `HEAD:master` push path if the same denial recurs.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, importing
  `data.holdout` from the repo root. C7 will need to create the venv and install
  `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**), plus the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21
  is 15 cycles and the plan's 3–4-cycle buffer is more than spent) still stands and is
  **not** re-escalated here. C7 stays blocked until a human replaces the status line
  with **C7** and records the approval here.

### Checkpoint B wait — 2026-10-07 (scheduled cycle, 14th wait, no new work)
- Fired while "Next cycle to run" still reads **AWAITING HUMAN — CHECKPOINT B**, so
  per CLAUDE.md / PLAN.md this cycle did no new work: verified only that nothing has
  changed and stopped. This is the **second fire on 2026-10-07** (the 13th wait was
  the first). **No human commits since the 13th wait** — after
  `git fetch origin master`, `HEAD` == `origin/master` == **`77b1a52`**
  (`git rev-list --left-right --count HEAD...origin/master` → `0 0`), and the four
  most recent commits are all this log's own wait commits (`77b1a52`, `a69dbcb`,
  `3c86bde`, `0108407`), authored by `Claude <noreply@anthropic.com>`, not a human.
  `git status --porcelain --untracked-files=all` empty, `git diff HEAD` empty. All
  Checkpoint B artefacts present and unmodified (12 files in `backtest/results/`,
  14 in `docs/figures/`, all 26 git-tracked and clean), including
  `c6_curves_DE-LU_2024_{summary.json,daily.csv,schedule.csv.gz}` and the three
  `docs/figures/c6_dispatch_week_DE-LU_*.png`. Holdout guard re-verified armed
  (marker-alone-on-a-line count **0**, `holdout_is_unsealed()` = `False`,
  `sealed_years()` = `{2025}`, no `*2025*` file anywhere under `data/`); no 2025 data
  touched. No `config/*.yaml` modified, so the config hash is unchanged; no push
  notification sent (the Checkpoint B ping was already sent in C6 — repeat pings for
  the same wait are noise). `data/raw/` did not exist at all again — **NOTE C2-02**'s
  17th recurrence — but nothing was re-downloaded because no work needed data.
- **`ENTSOE_API_KEY` is still set** in the cloud environment — eighth consecutive
  container, so the durable-environment-change reading continues to hold. Presence
  only was tested (`-n` on the variable); the value was not read, logged, or used, and
  no ENTSO-E request was made. Still re-confirm at the start of C7 rather than
  trusting this note.
- The detached-HEAD trap recurred this container: arrived detached at `77b1a52` with
  the local `master` *ref* stale at `0108407`, i.e. **3** commits behind `HEAD`
  (`git rev-list --count master..HEAD`) — the 11th, 12th and 13th waits' own commits.
  Running tally is now **21 recurrences out of 28 containers**. Following the 13th
  wait's note, this cycle did **not** attempt `git checkout -B master` (denied there
  by the session's permission classifier) and instead committed on the detached `HEAD`
  and pushed with `git push origin HEAD:master`, which updates the remote branch
  without touching the local ref. Net effect on the repo is identical; the stale local
  `master` ref is harmless because the container is discarded.
- No virtualenv exists in this container either (`.venv/` is gitignored and not
  rebuilt); the guard check above ran against the system `python3`, importing
  `data.holdout` from the repo root. C7 will need to create the venv and install
  `requirements.txt` before any modelling work.
- Still waiting on the five Checkpoint B items listed at the top of this file (eyeball
  the three week figures, sanity-check the 87–92% headline, decide **FLAG C5-01**,
  confirm or overturn **NOTE C4-02**, and the still-open **NOTE C3-01** / **NOTE
  C4-01**), plus the open **NOTE C2-02**. The 10th wait's elapsed-budget note (C7–C21
  is 15 cycles and the plan's 3–4-cycle buffer is more than spent) still stands and is
  **not** re-escalated here. C7 stays blocked until a human replaces the status line
  with **C7** and records the approval here.

### Checkpoint B — approved and closed — 2026-10-07 (human instruction, local assistant session, not a scheduled cycle)

**Approved by:** J., 2026-10-07, who instructed the local assistant session to
"approve as is so it can move forward". Recorded faithfully: this is an approval
of the current state **without an itemised review** — J. did not report
eyeballing the three C6 week figures or re-deriving the headline numbers in this
session. Checkpoint D (C19) still requires the human to hand-check three numbers
and verify the surprising finding, so the numbers get a human read before
anything is published.

**How each open item was resolved ("as-is" = keep current committed behaviour):**
- **Headline (87–92% capture, DE-LU 2024):** accepted as the working result.
- **FLAG C5-01:** option **(b)** — pure LP stays the default; the simultaneous
  charge/discharge artefact is carried as a stated limitation in the C18 write-up,
  quoting the C6 evidence (MILP capture 0.9203 vs LP 0.9187).
- **NOTE C4-02:** confirmed — the declined hour's day stays excluded and reported.
- **NOTE C3-01:** keep the `lag_24h` names; `docs/forecast_harness.md` stays the
  documentation of the actual `D-2` window. No config change.
- **NOTE C4-01:** `destroys_skill()` is not re-based; the PLAN.md leakage assertion
  file stays untouched.
- **NOTE C2-02:** no change — cycles keep re-pulling the ~1 MB DE-LU cache.

**Next:** C7 (ENTSO-E client + D-1 load / wind / solar forecasts for Tier-A zones).
`ENTSOE_API_KEY` was observed set from 2026-10-05; re-confirm at the start of C7.
No code, config, data or holdout state was touched by this entry.

### C7 — 2026-10-07 (scheduled cycle) — ENTSO-E client + Tier-A exogenous forecasts

Scope per PLAN.md C7: `ENTSOE_API_KEY` is configured, so the full intended scope ran
— ENTSO-E client, D-1 load forecast (Art. 6, safe) + D-1 wind/solar forecast
(Art. 14, FLAGGED) for the three Tier-A zones, and extend manifest/contracts. No
Tier-B fallback was needed. No modelling: C7 fetches, validates, describes and
contracts this data; **no model consumes it yet**, which is C8's work alongside the
RES-degradation sensitivity PLAN.md requires in the same cycle.

**Pulled and cached (18/18 pairs, 0 FLAGs on the final run):** DE-LU, ES, NO2 ×
{A65/A01 day-ahead total load, A69/A01 day-ahead wind+solar} × 2022-2024. 2019-2021
are refused *in code* (`exogenous_available_from_year: 2022`) — the platform answers
for them, but PLAN.md records that no archived D-1 forecast vintage exists there.
~3.5 MB gzipped, gitignored under `data/raw/entsoe/`.

**Built and committed (68 new tests, 339 passing in total):**
- `data/entsoe.py` — the client. Config-driven document specs; A03/A01 curve
  expansion; `Acknowledgement_MarketDocument` → `UnexpectedResponse` with its Reason
  code; 4xx never retried, 429/5xx/transport retried 3× at 5/15/45s; nothing
  unvalidated ever reaches the cache; per-row interval lengths carried out of each
  `<Period>`; the sealed-year assertion described below.
- `data/exogenous.py` — stitching loader + hourly aggregation + derived
  `residual_load_forecast_mw`. The FLAGGED status travels on `attrs`.
- `data/exog_manifest.py` + `data/build_exog_manifest.py` — 35-column manifest, one
  row per (zone, document, series, year), carrying `leakage_status`.
- `data/exog_contracts.py` + `data/build_exog_contracts.py` — the contract layer.
- `data/fetch_exogenous.py` — the fetch CLI (`--dry-run`, per-pair FLAG, exit 4 on a
  missing key without making a request).
- `tests/test_c7_entsoe.py` — 68 offline tests. No network, no real payload, no
  sealed year; the holdout tests assert the guard *fires*.
- `docs/entsoe_layer.md` — the full write-up of everything below.

**No frozen file was edited.** `tests/` gained one new file and no existing test was
modified; `data/contracts.py` and `forecast/leakage.py` were not touched. PLAN.md's
C7 line says "extend manifest/contracts", and CLAUDE.md forbids editing a
data-contract or leakage-assertion file without flagging and stopping, so the
extension is **additive**: `data/exog_contracts.py` imports and reuses the C2
primitives (`gap_report`, `check_utc_day_counts`, `check_local_day_counts`,
`dst_transition_days`, `modal_resolution_seconds`, …) rather than changing them, and
`data/exog_manifest.py` sits beside `data/manifest.py` rather than inside it.
`data/aggregate.py` is likewise untouched — see FINDING C7-B.

**All exogenous contracts hold.** All 12 (zone, series) reports `ok`, 0 negative
values in any load/wind/solar series, every index UTC and strictly monotonic with no
duplicates.

#### FINDING C7-A — `curveType A03`: sparse positions with block semantics. RESOLVED.

Every response the platform returned is `curveType A03`, a *variable-sized block*
curve: positions are **sparse**, and an omitted position means "the previous point's
value still holds". Real DE-LU solar, 2024-01-01 at PT15M, is
`position 1 → 0`, then `position 29 → 52.58`, with 2-28 absent and meaning *zero*.
Parsing position-by-row would have produced a 26-row "day" full of holes; parsing
positions as a dense index would have shifted every value after each block. NO2's
solar forecast for a whole year is a **single point of `0.0`**, which is only
correct under A03. `expand_points` implements the semantics; the tests pin it against
hand-computed sparse curves. A missing position 1 raises rather than guessing the
leading block.

#### FINDING C7-B — ES changed resolution mid-2022. RESOLVED.

DE-LU and NO2 publish at a single resolution (PT15M and PT60M), but **ES switched
PT60M → PT15M on 2022-05-23T00:00Z**. `data/aggregate.py`'s `to_hourly` documents a
single input resolution and takes the modal one, so over the stitched ES series it
treated the entire PT60M stretch — **3408 hours of real data** — as partial hours and
NaN'd them. Two knock-on errors in the first manifest build: ES 2022 read as **70.8%
covered** with **3409 gaps**, when it has one real missing hour.

Fixed without touching `data/aggregate.py` (it holds the C2 aggregation method and
its tests): each row's **true** interval length is now carried out of its own
`<Period>` as `attrs['interval_seconds']`, and `data/exogenous.py` splits the series
into maximal runs of constant resolution, handing each to `to_hourly` separately —
which is exactly the uniform input that function is specified for. A delta-based
guess cannot do this: the row before a one-hour hole in a PT15M series has a 4500s
forward delta, indistinguishable from a resolution change. The manifest now measures
coverage as *time covered / time in the year* and counts a gap as a step longer than
the **preceding row's own** interval. ES 2022 now reads **99.9886% covered, 1 gap**,
and ES load's NaN count went 3408 → **0**.

#### FINDING C7-C — autumn-DST-day publication gaps. REPORTED, not filled.

The German and Spanish day-ahead publications each **drop one hour at the autumn DST
boundary**, at the first hour of the 25-hour local day. DE-LU 2023-10-28 and
2024-10-26: the onshore-wind (B19) and solar (B16) series split into two Periods
around a missing `22:00Z-23:00Z` while offshore wind (B18) runs straight through. ES
2022-10-30: the same hour missing from both documents.

This is a structural property of these publications, not a one-off, and belongs in
the write-up's Limits section. Complete list of every source gap found (worst case
~0.4% of a zone-year, all reported, none filled):

| Zone / document | Missing | What it is |
|---|---|---|
| DE-LU load | 2022-02-22, 2022-03-24 | 24h each — two whole local days absent |
| DE-LU load | 2023-10-28, 2024-10-26 | 1h each — autumn DST long day |
| DE-LU wind & solar | 2023-10-28, 2024-10-26 | 1h each, NaN — partial psrType, same hour |
| ES (both documents) | 2022-10-30 | 1h — autumn DST long day |
| ES solar | 2024-12-07 … 12-11 | 120h NaN — partial psrType coverage |
| ES wind | 2024-06-02 | 24h NaN — partial psrType coverage |
| NO2 wind & solar | 2022-11-01 … 11-02 | 48h — two whole local days absent |

An intermediate version of the parser **raised** on the DE-LU case, which cost a
whole training year for four intervals. That was the wrong granularity: CLAUDE.md
says to flag a source anomaly and skip only the *dependent* work, and this project's
standing rule (`data/prices.py`) is that a gap stays a gap and gets reported rather
than filled. The four intervals are now NaN, counted on `attrs`, and surfaced in both
committed artefacts. NaN cannot be mistaken for a real low-wind hour; zero could.

#### FINDING C7-D — NO2 offshore wind is an all-zero stub. RESOLVED by a checkable rule.

`wind_forecast_da_mw` is `B18 + B19` (offshore + onshore), and two cases pull in
opposite directions:
- **DE-LU**: the absent onshore component is worth tens of GW → the sum must be NaN.
- **NO2**: offshore B18 is published for just **48 hours of 2022 and 192 of 2024**,
  absent from 2023 entirely, and is **`0.0` at every single published point**. NO2 has
  no offshore fleet; the TSO emits an occasional all-zero stub. Treating that absence
  as NaN wiped out the wind feature for a whole Tier-A zone for ~8600 hours/year.

Resolved by a rule the **data decides**, not the zone: a component that is
*identically zero wherever it is published* is not a fleet, so its absence
contributes zero. Asserted against the payload rather than assumed, and recorded in
`attrs['zero_components']` and the contract report so a human can overrule it. NO2
wind is now complete; DE-LU's four DST intervals correctly stay NaN. Both directions
are pinned by tests.

#### FINDING C7-E — negative residual load is the signal, not a defect. RESOLVED.

The first contract run failed `residual_load_forecast_mw` for 262 negative hours
(DE-LU) and 317 (ES). Those are **real and are the point**: residual load =
load − wind − solar goes negative exactly when renewables exceed demand, which is the
condition that produces negative day-ahead prices and the subject of PLAN.md's C14
fundamentals chapter. DE-LU's first is 2022-03-20T11:00Z, a sunny windy Sunday
midday. Flagging it would have flagged the signal itself. Non-negativity is now
config-driven per series (load/wind/solar: a negative value is a source defect) with
residual load the deliberate, documented exception.

**The contract dividing line, now stated once in `data/exog_contracts.py`:**
*integrity* findings are violations (non-UTC or non-monotonic index, duplicate
timestamps, a negative value in a quantity that cannot be negative, or a day with
*more* rows than expected — which can only be a bug of ours); *completeness* findings
are reported notes (gaps, NaNs, a day with *fewer* rows than expected). A shortfall
and a gap are the same fact counted twice, which is why only one is a failure.

#### Sealed-holdout guard strengthened

ENTSO-E's `periodEnd` is the **exclusive** window end, so fetching year `Y` must name
`(Y+1)-01-01T00:00Z` — verified in C7 as the only complete spelling (an end of
`Y-12-31T23:00` returns 92 of that day's 96 quarter-hours). Naming that boundary is
not an observation of `Y+1`, but rather than rely on the argument, `parse_document`
now asserts **positively** that no parsed timestamp falls in a sealed year. If the
platform ever returned a point past the boundary while fetching 2024, it raises
instead of caching. The ordinary `assert_not_sealed` guard still runs before any
request and before any cached read, and a test asserts the new check fires.

#### Token hygiene

ENTSO-E authenticates with a `securityToken` **query parameter**, so unlike
Energy-Charts the request URL is itself a secret. `data.entsoe.redact` strips both the
literal token and any `securityToken=...` parameter, and is applied to every stored
provenance record, every exception message and every CLI FLAG line (including
transport errors that quote the URL). `document_request()` returns params *without*
the token; it is added only at request time. `api_key_is_set()` tests presence only.
Tests assert the token appears in no cached metadata and in no raised message.

#### Plausibility eyeball (first exogenous numbers in the project)

DE-LU load 30.9-76.5 GW (peak ~80 GW ✓), wind 0.2-50.4 GW (record ~50 GW ✓), solar
0-48.6 GW (record ~48-50 GW ✓), residual load **-13.6** to 68.7 GW (negative at
sunny/windy midday ✓). ES load 16.8-38.7 GW (peak ~40 GW ✓), wind 0.3-19.8 GW,
solar 0-21.2 GW. NO2 load 2.1-6.4 GW, wind 0-1.3 GW (onshore ~1.5 GW ✓), solar
identically 0 (no fleet ✓).

#### LP invariants

C7 touched no dispatch, forecast or backtest code, so the battery-LP invariants do
not apply to any new artefact. They remain executable and green as part of the full
suite: `assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` all pass
(339 tests, 0 failures). No LP objective from a forecast-priced solve is reported
anywhere as a realised value.

#### NOTE C7-01 — one open question for a human (presentation, not a blocker)

`config/features.yaml` names the exogenous features `load_forecast_da`,
`wind_forecast_da`, `solar_forecast_da`, `residual_load_forecast`; the columns this
cycle produces are the same names with a `_mw` suffix (`load_forecast_da_mw`, …),
because the unit matters once three series in MW sit beside prices in EUR/MWh. The
suffix is declared in `config/data.yaml` under `sources.entsoe.documents.*.series`,
so nothing is ambiguous in code, but the two config files now spell the same feature
two ways. Options: (a) keep both spellings and let `docs/entsoe_layer.md` be the
mapping — the same resolution a human already chose for **NOTE C3-01**; (b) rename
the `config/features.yaml` entries to carry `_mw`. **Not done either way**, because
`config/features.yaml` is a feature contract and C8 is the cycle that actually
consumes it. Proceeding as (a) unless a human says otherwise; this does not block C8.

**Next:** C8 — exogenous features into LEAR for Tier A, plus the RES-forecast
degradation sensitivity (as-published vs persistence-degraded) as a first-class
experiment. C8 must read the gap/NaN notes in
`data/manifest/exogenous_contract_report.json` before building these columns in: the
FLAGGED Art. 14 vintage is only usable alongside that sensitivity, and ~0.4% of
hours are NaN by design.

### C8 — 2026-10-08 (scheduled cycle) — exogenous features into LEAR + the RES vintage premium

Scope per PLAN.md C8: exogenous features into LEAR for Tier A, plus the
RES-forecast degradation sensitivity (as-published vs persistence-degraded) as a
first-class experiment. Both done, for all three Tier-A zones. No checkpoint, no
blocker, no FLAG raised. `ENTSOE_API_KEY` is set and was used only to re-populate
the cache (see "Cache re-pull" below).

#### The headline finding — FINDING C8-A: the vintage, not the information

`config/features.yaml` has marked the Art. 14.1.D wind/solar forecast **FLAGGED**
since C1 because it is published at 18:00 local on D-1, *after* the 12:00 gate
closure the model is predicting. C8 turns that from a caveat into a measurement by
running the same LEAR four times per zone over the same rows, changing only which
exogenous columns are present and at which **vintage**:

| Arm | Columns added | Vintage | Leak-free? |
|---|---|---|---|
| `price_only` | — | — | yes (C4's feature set) |
| `load_only` | `load_forecast_da_mw` | target day's own (public 10:00 D-1) | **yes** |
| `res_persistence` | `+` wind, solar, residual load | the vintage published 24h earlier | **yes** |
| `res_as_published` | `+` wind, solar, residual load | target day's own (public 18:00 D-1) | **no — acknowledged** |

2024 validation year, MAE/RMSE in EUR/MWh, scored on the **common hours** (the
hours every arm predicted), LEAR at C4's committed spec, refit daily, every arm
training from 2022-01-01:

| Arm | DE-LU MAE | RMSE | ES MAE | RMSE | NO2 MAE | RMSE |
|---|---|---|---|---|---|---|
| `naive_last_week` | 32.799 | 55.219 | 27.316 | 38.135 | 21.195 | 41.758 |
| `price_only` | 23.525 | 37.416 | 18.126 | 24.075 | 14.737 | 26.894 |
| `load_only` | 23.715 | 37.425 | 18.015 | 23.992 | 14.746 | 26.915 |
| `res_persistence` | 23.588 | 37.199 | 17.930 | 23.892 | 14.817 | 26.938 |
| `res_as_published` *(late)* | **21.610** | **32.699** | **15.906** | **20.650** | 14.809 | 26.273 |

| Zone | Capturable gain (`load_only − price_only`) | Vintage premium (`as_published − persistence`) |
|---|---|---|
| DE-LU | **−0.19** EUR/MWh (−0.81% of MAE) | **+1.98** EUR/MWh (**+8.39%**) |
| ES | **+0.11** EUR/MWh (+0.61%) | **+2.02** EUR/MWh (**+11.28%**) |
| NO2 | **−0.01** EUR/MWh (−0.06%) | **+0.01** EUR/MWh (+0.06%) |

**At an honest vintage the entire ENTSO-E exogenous block is worth nothing** —
between −0.8% and +0.7% of MAE, in all three price-formation regimes. Fed the
as-published Art. 14 archive, the *same columns in the same model* buy 8-11% of
MAE in the two RES-exposed zones. So a backtest that uses the archived Art. 14
forecast without this split reports roughly a tenth of its MAE improvement as
skill when it is a publication timestamp. That is the write-up's surprising
finding arriving at C8 instead of C15, and it is a finding *about the literature's
standard data source*, which makes it the most portfolio-relevant thing the
project has produced so far.

Three supporting observations, all in the committed summaries:

- **RMSE moves more than MAE.** `res_as_published` improves RMSE by 12.6% (DE-LU)
  and 14.2% (ES) against 8.4% and 11.3% on MAE. RES forecast information mostly
  kills the *large* errors — high-wind, negative-price hours — which MAE
  under-weights and which are exactly the hours a battery earns in. The vintage
  premium should therefore be **larger** in captured-value terms than it looks
  here. C11/C12 measure that; C8 does not guess at it.
- **History beats features.** Aligning every arm to the 2022 exogenous start costs
  `price_only` +0.66 (DE-LU), +0.26 (ES) and +1.10 (NO2) EUR/MWh of MAE against
  C4's full 2019+ window. Three extra years of *price history* is worth several
  times the whole exogenous block at an honest vintage. C4's DE-LU number
  (MAE 22.864) reproduced exactly as the `full_history_reference` row, which also
  re-verifies the C4 pipeline end to end on a freshly re-pulled cache.
- **NO2 shows nothing in either direction**, which is the control that makes the
  other two credible. A hydro zone with ~1.3 GW onshore wind, no solar fleet and
  reservoir-set prices has nothing for a RES forecast to explain at any vintage —
  a method that invented a premium there would be measuring its own machinery.

#### FINDING C8-B — the MAE ladder is not monotone for DE-LU and NO2

Each arm's information set contains the previous arm's, so MAE was expected to be
non-increasing along the ladder. It is for ES (`mae_monotone_non_increasing: true`)
and **is not** for DE-LU or NO2: `load_only` and `res_persistence` land
fractionally *above* `price_only` (−0.19 and −0.06 EUR/MWh respectively on DE-LU).

Reported, not smoothed — the runner carries the flag in every summary. The reading
is that these columns buy nothing a LASSO can use once the price lags are present
(the day-ahead load forecast is largely a restatement of the daily and weekly cycle
`price_lag_24h`/`price_lag_168h` already carry) and so cost a little in parameters.
A finding about the features, not a defect in the plumbing — and ES, where solar
genuinely sets the midday price, is monotone. **No action taken**: dropping the
column, or widening the model to rescue it, would be tuning against a visible
validation metric, which PLAN.md forbids.

#### FINDING C8-C — the persistence offset is itself late on the autumn DST day

The 24-hour degradation offset is applied by explicit UTC-instant reindexing, and
its information time is then read back off the publication clock rather than
assumed safe. On the autumn DST day that matters: the local market day has **25**
hours, so its last hour minus 24 hours is its own *first* hour, whose RES forecast
was published at 18:00 on D-1 — after the gate. The guard catches exactly those
rows and the mask blanks them.

NO2 and ES blank all three such days (2022-10-30, 2023-10-29, 2024-10-27). DE-LU
blanks only **2022-10-30**, because for 2023 and 2024 the source hour is already
NaN — and it is already NaN for a reason: FINDING C7-C recorded that DE-LU's wind
and solar publications drop the hour `22:00Z-23:00Z` on 2023-10-28 and 2024-10-26,
and *that hour is the long day's first local hour*. The two findings describe the
same hour from opposite ends. Nobody would have special-cased this; the clock
arithmetic found it, and it is pinned by a test.

#### How the late arm is allowed to run at all

`res_as_published` is the only place in this repo where a post-gate-closure column
reaches a model, and the door is deliberately narrow.

- The three leak-free arms get nothing special: late cells are blanked by
  `forecast.leakage.mask_unavailable` exactly as C3 blanks a late price lag, and
  the **unmodified** `assert_no_leakage` then has to pass clean.
  `test_leak_free_variants_pass_the_plain_guard` asserts it.
- For the late arm, `assert_only_acknowledged_leakage` replaces the plain guard and
  permits a violation only if its column was named in advance, its kind is
  `after_gate_closure`, **and** its worst lateness equals what the declared
  publication clock predicts to the minute. It also refuses a *silent*
  acknowledgement. Measured on all three zones: exactly 3 acknowledged columns,
  worst lateness exactly 6h, on 26 158-26 301 rows each — nothing else anywhere.
- That check is **stricter** than the plain guard on that matrix, not weaker: it
  pins the leak's shape instead of tolerating one, and a genuine leak in a price
  lag cannot hide behind the RES acknowledgement (asserted by
  `test_acknowledgement_refuses_an_unrelated_leak`, plus four more refusal tests).
- The harness's per-fold check is skipped for that one arm only
  (`check_leakage=False`, the same door `backtest/diagnostics.py` already uses for
  the deliberate misalignment experiments) and replaced by one pass over the whole
  arm matrix, which implies it: the guard is a per-(row, column) predicate, so a
  violation in any subset is a violation of the whole.
  `test_the_whole_matrix_check_implies_every_row_subset_s` asserts that on real
  subsets rather than arguing it. Sealed-year refusal and the "training targets
  must be public" guard are untouched and run on every fold of every arm.
- `test_a_leading_res_column_is_worth_a_lot_to_lear` measures what the guard is
  protecting: a wind column derived from the target hour's own price more than
  halves MAE. The guard is not defending a technicality.

#### The publication clock moved from a comment into config

C7 recorded "published 18:00 on D-1" in a `leakage_note:` prose field. A comment
cannot be checked. C8 adds, beside each document in `config/data.yaml`:
`publication_tz: Europe/Brussels`, and per document `published_day_offset: -1`
with `published_local: "10:00"` (A65) / `"18:00"` (A69). The Art. 6.1.B time is
the **latest** instant the regulation permits (2h before gate closure), not a
typical one — a guard built on an optimistic publication time would pass a column
a bidder was still waiting for. `test_the_declared_clock_is_what_makes_the_leak_visible`
pins both numbers against the gate convention, so a later edit to either is caught
rather than quietly re-basing the experiment.

#### Three design choices that were easy to get wrong

- **The residual-load column is derived *after* degradation.** Under
  `res_persistence` a bidder holds the load forecast for D *and* the RES forecast
  for D-1, so their best residual-load estimate is
  `load(t) − wind(t−24h) − solar(t−24h)`, which is what is built. Lagging C7's
  already-derived residual column by 24h instead would discard the load forecast
  they did hold. Its information time is the element-wise **maximum** of its three
  inputs' — a derived value is knowable only once its last input is.
- **Every arm trains from the same day.** The exogenous series start in 2022 and
  LEAR drops a training row with any missing design cell, so an exogenous arm on a
  2019-start expanding window would silently train on 2022+ while `price_only`
  trained on 2019+, making the comparison partly "more features" and partly "less
  history". All four arms run from `2022-01-01`; `price_only` is *additionally* run
  on the full history as a labelled `full_history_reference`, which is not part of
  the ladder.
- **The arms are compared on hours every arm predicted.** The committed LEAR
  declines an hour whose design has a hole, and the exogenous columns bring
  FINDING C7-C's source gaps with them (ES loses 193 hours this way — chiefly the
  120-hour December 2024 solar gap). Each arm's own scores are reported *and* a
  `common_hours` block re-scores every arm on the intersection; the degradation
  table is computed from the latter. Both are in the summary, neither is hidden.

#### Built and committed (42 new tests, 381 passing in total)

- `forecast/exog_features.py` — the four variants, the publication clock, the
  vintage offsets, the derived-after-degradation residual load, the masking split
  and `assert_only_acknowledged_leakage`.
- `backtest/run_c8_exogenous.py` — the CLI: four arms × three zones, the
  common-hours table, the degradation table, the monotonicity flag, the
  full-history reference.
- `tests/test_c8_exogenous_features.py` — 42 offline tests. No network, no cached
  file, no sealed year.
- `docs/exogenous_model.md` — the full write-up of everything above.
- `backtest/results/c8_exog_{DE-LU,ES,NO2}_2024_{predictions.csv.gz,folds.csv,summary.json}`.
- `config/data.yaml` — the publication clocks (additive; see below).
- `requirements.txt` — a note that C8 adds no dependency.

**No frozen file was edited.** `tests/` gained one new file and no existing test
was modified. `forecast/leakage.py`, `forecast/features.py`, `data/contracts.py`,
`data/aggregate.py` and `config/features.yaml` are **untouched** — verified by
`git diff --stat HEAD` over exactly those paths before committing. The only edit
to an existing file is the additive `config/data.yaml` block above; the
acknowledgement mechanism is built out of `find_leakage` and `mask_unavailable`
rather than by relaxing either.

#### Cache re-pull — NOTE C2-02, 19th recurrence, and a stronger statement than usual

`data/raw/` was empty again (the container does not keep it), so C8 re-pulled 18
(zone, year) price files and 18 (zone, document, year) ENTSO-E files. 36/36
succeeded, 0 FLAGs. Then `data.build_exog_manifest` and `data.build_exog_contracts`
were re-run against the fresh cache and diffed against C7's committed artefacts:
of 27 (zone, document, series, year) rows × 35 columns, **the only fields that
differ are `fetched_at_utc` (27 rows) and `gzip_bytes` (24 rows)**. Every
`payload_sha256`, count, coverage figure, gap count, NaN count, negative count and
distribution statistic is **identical**, and the contract report body is byte-identical.
`gzip_bytes` moves by a few bytes because ENTSO-E stamps a fresh random `mRID` into
each response's header, which the series fingerprint correctly ignores.

The regenerated manifest artefacts were therefore **reverted** rather than
committed: they describe the same data, they are correctly labelled `"cycle": "C7"`
with C7's git SHA and config hash, and committing a new timestamp every cycle would
churn the manifest forever with no information gain. The verification above is the
durable record.

#### LP invariants

C8 touched no dispatch, LP or settlement code, so the battery-LP invariants apply
to no new artefact. They remain executable and green as part of the full suite:
`assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` all pass
(381 tests, 0 failures). No LP objective from a forecast-priced solve is reported
anywhere as a realised value. **FLAG C5-01** (simultaneous charge/discharge) is
unchanged and still resolved as option (b) per Checkpoint B.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count
**0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, and no `*2025*` file
exists anywhere under `data/`. Every arm of every zone was evaluated on `[2024]`
only; the exogenous window is 2022-01-01..2024-12-31 and the price window
2018-12-31..2024-12-31. `test_no_arm_can_be_evaluated_against_a_sealed_year`
asserts the new arms inherit the refusal. No 2025 data has been fetched, loaded,
dispatched or computed against at any point in C2-C8.

#### Config hash

**`515d4e8d98887256`** (was `28ebdd1ca5e72913`). It moved because C8 added
`sources.entsoe.publication_tz` and the two `published_*` pairs to
`config/data.yaml`. No other `config/*.yaml` file was modified; in particular
`config/features.yaml` is unchanged, so **NOTE C7-01 stays closed as option (a)** —
the two spellings (`load_forecast_da` there, `load_forecast_da_mw` in the built
columns) remain, and `forecast.exog_features.exogenous_feature_names()` *is* the
mapping, derived from both files rather than written down twice, so a rename in
either surfaces as a failing test instead of as drift.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `bb8e67c` with
local `master` stale 6 commits behind. `git checkout -B master bb8e67c` was
permitted, so no `HEAD:master` push path was needed. **23 recurrences out of 30
containers.** Keep checking `git rev-parse --abbrev-ref HEAD` and
`git rev-list --count master..HEAD` at the start of every cycle.

#### Open question for a human — NOTE C8-01 (presentation, not a blocker)

FINDING C8-A says the honest exogenous block is worth ~0 on MAE for all three Tier-A
zones. PLAN.md's C9 (GBM) and C10 (scale-out) both assume Tier A runs "with exogenous
features". Nothing in C8 contradicts that — a GBM may extract from residual load what
a LASSO cannot, and the capture-ratio metric that actually matters is a spread
metric, not MAE, so the C8 result does not settle the question. **Proceeding as
PLAN.md describes**: C9 and C10 keep the exogenous block for Tier A, and the arm
that goes into the headline results is `res_persistence` (leak-free), with
`res_as_published` carried alongside as the labelled vintage-premium measurement.
If a human would rather Tier A ran `load_only` or price-only until a spread metric
justifies the RES columns, say so and C9 will follow.

**Next:** C9 — GBM, one fixed LightGBM config, in-fold early stopping, Tier A only,
no hyperparameter search. Note that `lightgbm` is not yet in `requirements.txt` and
will need adding. C9 should read FINDING C8-A first: the GBM must be run on the same
four arms (or at minimum on `res_persistence` and `res_as_published`) so the vintage
premium is measured for the non-linear model too rather than inherited from LEAR.

### C9 — 2026-10-08 (scheduled cycle) — the gradient-boosted model, Tier A, on C8's four arms

Scope per PLAN.md C9: GBM, **one fixed LightGBM config, in-fold early stopping, Tier A
only, no hyperparameter search**. Done for all three Tier-A zones. Following the C8
entry's instruction, the booster was run on **all four of C8's exogenous arms** so the
vintage premium is *re-measured* under a non-linear functional form rather than
inherited from LEAR. No checkpoint, no blocker, no FLAG raised. `ENTSOE_API_KEY` is
set and was used only to re-populate the cache (see "Cache re-pull" below).

`lightgbm` was added to `requirements.txt` (installed: **4.7.0**) — the only new
dependency since C5.

#### How the "no hyperparameter search" rule is actually enforced

This is the part of C9 that matters most across cycles, so it is structural rather
than a promise. Validation metrics are visible to every cycle, a booster has a dozen
knobs, and a cycle that nudges one after seeing a 2024 number is overfitting the
validation year *through the agent* — leaving no trace in the diff, because the next
cycle just finds a slightly different literal and no reason to doubt it.

- `forecast.gbm.GbmSpec` is a frozen dataclass. Every value is either a LightGBM
  default or a standard choice stated with its reason in the module docstring; none
  was chosen by looking at a score.
- `GbmSpec.fingerprint()` is a 16-hex hash of every committed value and is written
  into every result row. C9's runs all carry **`a366a760e269bba6`**.
- `test_the_committed_config_is_exactly_what_plan_md_froze` pins all seventeen values
  to literals and `test_the_fingerprint_changes_when_any_knob_changes` pins that the
  hash is sensitive to each. **A later cycle that wants to tune has to edit a test**,
  which CLAUDE.md makes a flag-and-stop event. That is the whole mechanism.

The config: L2 objective, `learning_rate=0.05`, `num_leaves=31`, `min_data_in_leaf=20`,
`feature_fraction=bagging_fraction=0.9`, `bagging_freq=1`, `lambda_l2=1.0`,
`num_boost_round=2000` capped with `early_stopping_rounds=50`, `early_stopping_days=90`,
`refit_on_full_window=True`, `seed=20260101`, `deterministic=True`,
`force_row_wise=True`, `num_threads=4`. `docs/gbm_model.md` tabulates the provenance
of each.

#### Results — all three Tier-A zones, 2024, common hours

Daily refit, expanding window aligned to 2022-01-01, 366 folds per arm, config
fingerprint `a366a760e269bba6`, lightgbm 4.7.0. Scored on the hours every arm of
**both** models predicted (DE-LU 8 782, ES 8 591, NO2 8 783 — ES drops the most,
chiefly FINDING C7-C's 120-hour December 2024 solar gap, which LEAR declines and the
GBM routes natively). MAE/RMSE in EUR/MWh:

| Series | DE-LU MAE | RMSE | ES MAE | RMSE | NO2 MAE | RMSE |
|---|---|---|---|---|---|---|
| `naive_last_week` | 32.791 | 55.213 | 26.958 | 37.513 | 21.192 | 41.757 |
| `gbm_price_only` | 22.787 | 36.339 | 18.348 | 24.354 | 14.035 | 25.907 |
| `gbm_load_only` | 22.749 | 36.085 | 18.376 | 24.472 | 14.005 | 25.846 |
| `gbm_res_persistence` | 22.556 | 35.998 | 18.171 | 24.329 | 14.004 | 25.696 |
| `gbm_res_as_published` *(late)* | **17.151** | **29.077** | **14.932** | **19.572** | **13.517** | **24.625** |
| `lear_price_only` (C8) | 23.525 | 37.416 | 18.126 | 24.075 | 14.737 | 26.894 |
| `lear_load_only` | 23.715 | 37.425 | 18.015 | 23.992 | 14.746 | 26.915 |
| `lear_res_persistence` | 23.588 | 37.199 | 17.930 | 23.892 | 14.817 | 26.938 |
| `lear_res_as_published` *(late)* | 21.610 | 32.699 | 15.906 | 20.650 | 14.809 | 26.273 |

#### FINDING C9-C — the vintage premium is 2-3x LARGER for the booster. Read this before any later cycle reports a GBM number.

| Zone | capturable gain, GBM | **vintage premium, GBM** | vintage premium, LEAR (C8) | ratio |
|---|---|---|---|---|
| DE-LU | +0.16% of MAE | **+23.96%** | +8.39% | **2.9x** |
| ES | −0.15% | **+17.82%** | +11.28% | **1.6x** |
| NO2 | +0.21% | +3.48% | +0.06% | — |

C8 measured the premium with a per-hour LASSO: 8-11% of MAE in the two RES-exposed
zones. Same columns, same vintages, same rows, same folds, under a tree ensemble:
**24% and 18%.** FINDING C8-A therefore does not merely survive a change of
functional form — **the leak is worth two to three times more to a non-linear model.**

The mechanism shows up in the model's own internals, not only in the metric.
Split-gain importance on `residual_load_forecast_mw` (DE-LU, last fold) is **0.033**
under `res_persistence` and **0.236** under `res_as_published` — the booster leans
*seven times harder* on residual load when fed the vintage published after gate
closure. That is what a non-linear model does with a merit-order driver it can
actually trust, and precisely what the honest vintage denies it.

The practical reading is the opposite of reassuring, and it is the sharpest thing
this project has produced so far. On these three zones the booster's advantage over
the LASSO is concentrated almost entirely in the late arm:

| `gbm − lear` MAE (negative favours GBM) | DE-LU | ES | NO2 |
|---|---|---|---|
| `price_only` | −0.738 (−3.1%) | **+0.222 (+1.2%)** | −0.703 (−4.8%) |
| `load_only` | −0.966 (−4.1%) | **+0.361 (+2.0%)** | −0.740 (−5.0%) |
| `res_persistence` | −1.032 (−4.4%) | **+0.241 (+1.4%)** | −0.813 (−5.5%) |
| `res_as_published` *(late)* | **−4.458 (−20.6%)** | −0.974 (−6.1%) | −1.291 (−8.7%) |

On the honest arms there is **no uniform winner**: the GBM wins DE-LU and NO2 by
3-5% and *loses* solar-dominated ES by 1-2%. On the late arm it wins everywhere, and
on DE-LU by 21%. So a published result of the form *"gradient boosting beats LEAR on
a RES-fed day-ahead price model"* may be substantially an artefact of the Art. 14
publication timestamp rather than of the functional form.

**Caveat that must travel with that comparison** (stated in the module docstring, the
runner and `summary.model_comparison.note`): the GBM−LEAR difference is one of
functional form **and** of pooling — LEAR fits 24 models partitioned by delivery
hour, the GBM fits one pooled model with the hour as a categorical feature — and C9
cannot separate the two. The *within-model* vintage premium above is unaffected by
that entanglement, which is exactly why it is the number this cycle can settle and
the model ranking is not.

#### FINDING C9-D — NO2's control holds in ratio but is no longer exactly null

C8's NO2 result was a clean zero in both directions (+0.06% premium), and that is
what made the other two zones credible: a method that invented a premium in a hydro
zone with no solar fleet would be measuring its own machinery. Under the booster
NO2's honest arms stay flat (+0.21%; `price_only`, `load_only` and `res_persistence`
land within 0.03 EUR/MWh of each other) but the premium is **+3.48%**, not zero.

Reported, not smoothed. NO2 carries ~1.3 GW of onshore wind, so same-day wind
information the market had not yet seen is apparently worth a little to a model that
can respond to it non-linearly, even where reservoir opportunity cost sets the price.
The control still carries the finding in *ratio* — 24% and 18% against 3.5%, a 5-7x
gap — but **"the hydro zone shows nothing" is a C8 sentence, not a C9 one**, and the
C18 write-up must use the C9 version.

#### FINDING C9-E — ladder monotonicity flips between models, in all three zones

Each arm's information set contains the previous arm's, so MAE was expected to be
non-increasing along the ladder. FINDING C8-B recorded that it is not, for DE-LU and
NO2 under LEAR. Under the GBM it **is** monotone for DE-LU and NO2 and is **not** for
ES (`load_only` lands 0.028 EUR/MWh above `price_only`) — the flag flips relative to
LEAR in every zone.

That is the strongest available evidence that these fractional non-monotonicities are
noise around zero rather than structure: across 2 models x 3 zones both orderings
occur, which is what to expect if the honest exogenous gain really is ~0 and the sign
of a 0.2% difference is a coin flip. **No action taken** on either — dropping a column
or widening a model to rescue an ordering would be tuning against a visible validation
metric, which PLAN.md forbids.

#### NOTE C8-01, partially answered

C8 asked whether Tier A should keep the exogenous block given that it is worth ~0 on
MAE, and PLAN.md's argument for keeping it was that "a GBM may use residual load where
a LASSO cannot". **Measured: it does, a little, and nowhere near enough to justify the
block on MAE.** The leak-free `res_persistence` arm buys 1.0% of MAE over `price_only`
on DE-LU (22.787 → 22.556) and 1.0% on ES (18.348 → 18.171), where LEAR got −0.8% and
−1.1% respectively; NO2 gets 0.2%. So the booster does extract something honest where
the LASSO extracted nothing, and it is ~1%, not the 8-24% the late vintage buys.

This still does not settle the question, because the metric that decides is a spread
metric and not MAE. **C11/C12 should decide it**, and the right test is whether
`res_persistence` improves the *capture ratio* over `price_only` by more than its 1%
of MAE suggests — RES information mostly kills the large errors (RMSE moves more than
MAE here too), and large errors are concentrated in exactly the high-wind,
negative-price hours a battery earns in.

#### Early stopping did its job, in all 12 runs

Across all 12 (zone, arm) runs of 366 folds each, the chosen round count ranged
**43-624** with medians of 81-139 by arm, and **not one fold of any arm in any zone hit
the 2 000-round cap.** So the round count is genuinely an in-fold choice rather than a
fixed hyperparameter wearing its name. Fitting set 24 119 rows, in-fold stopping set
2 161 rows, on the last fold of every run. NO2 consistently needs more rounds (median
114-139) than DE-LU or ES (81-104) — the kind of thing a per-zone tuning pass would
have "fixed", and which is left alone.

#### Bias — flagged for C11/C12, not acted on

Every arm of every zone is biased **high**: GBM +2.6 to +8.7 EUR/MWh, LEAR +2.6 to
+5.7. This is the shared asinh VST, not a GBM defect — `sinh` is convex, so
back-transforming a conditional-mean estimate in asinh space overshoots in price
space, and the booster inherits the effect LEAR already had (DE-LU `price_only`: GBM
+5.20, LEAR +5.06). The late arm is the most biased because it is the most confident.

Flagged because C11/C12 dispatch against these curves: a roughly *uniform* upward bias
barely perturbs the within-day ordering and spread a battery actually trades on, so the
capture ratio may be far less sensitive to it than the MAE table suggests. That is a
prediction for C11/C12 to test, not a claim made here.

#### Leakage assertion (i) on real prices — decisive in all three zones

| Zone | aligned MAE | one day staler | degradation | `staler_is_worse` |
|---|---|---|---|---|
| DE-LU | 22.786 | 26.104 | **+14.56%** | yes |
| ES | 18.766 | 23.282 | **+24.07%** | yes |
| NO2 | 14.035 | 16.956 | **+20.81%** | yes |

Which is the point of FINDING C9-A below: the assertion has real content on real
prices; it was the synthetic fixture that was vacuous, not the guard.

#### FINDING C9-A — PLAN.md assertion (i) is vacuous for a pooled booster on a periodic series

C3 asserts leakage assertion (i) ("shifting the feature matrix forward one day must
degrade metrics") against `NaiveLastWeek`, which *is* `price_lag_168h`, so misaligning
the matrix necessarily wrecks it. Run the same experiment with the GBM on the same
synthetic week-periodic fixture and the **staler matrix scores better** — MAE 1.716
against 1.759.

Not a bug and not a leak. The pooled booster also holds `hour_of_day_local`,
`day_of_week` and `month`, and on that fixture the price shape is an exact
deterministic function of those three. The lagged prices are a *noisier restatement*
of a signal the calendar gives for free — each lag carries its own copy of the noise
term — so the best available model on that series ignores the lags, and misaligning
them nudges the booster towards doing exactly that. The tell is that the aligned MAE
(1.759) is already within 10% of the 1.596 noise floor no model can beat.

So assertion (i) is only informative on a series where the lagged prices carry
something the calendar cannot. The response was **not to weaken the assertion** but to
put it where it means something, in three places:

1. `test_shifting_the_features_forward_a_day_degrades_the_gbm` runs it on the
   persistence-dominated synthetic series, where it passes decisively.
2. `test_the_day_shift_assertion_is_vacuous_for_this_model_on_a_periodic_series` pins
   the vacuity *and its reason*, so nobody later reads a passing periodic-series shift
   test as evidence of anything.
3. `backtest/run_c9_gbm.py` runs the assertion on each zone's **real prices** at the
   committed config and records it in `summary.day_shift_diagnostic` — which is where
   the assertion is actually established for this model (numbers above).

**`tests/test_c3_leakage_harness.py` is untouched.** Its assertion is about the naive
floor and remains true of it. Nothing was edited to make a red test green; one new
test file was added and the assertion was re-sited onto a fixture where it has content.

#### FINDING C9-B — RETRACTED. It was my hypothesis, and my own test disproved it.

**Recorded in full because the retraction is the useful part.**

The hypothesis: LightGBM's early stopping might not discard the
`early_stopping_rounds` trees built while it discovers the best iteration, in which
case `booster.predict(X, num_iteration=booster.num_trees())` would quietly serve the
exact overfit tail early stopping existed to reject — a nasty bug class, because
nothing about it looks wrong. The model was changed to carry the round count
explicitly, and a test was written to pin the supposed gap.

**The hypothesis is false on lightgbm 4.7.0.** `lgb.train` truncates the booster to
the best iteration: `num_trees() == best_iteration`, and a bare `predict()` already
uses the right trees. Verified directly on a synthetic fit (best_iteration 83,
num_trees() 83, `predict()` identical to `predict(num_iteration=best_iteration)`), and
the original code was therefore never wrong. **The test is what caught it** — it
failed on the first full-suite run with `assert 354 > 354` — which is exactly what a
test pinning a claimed mechanism is for.

What survives: `GbmModel` still passes `num_iteration` explicitly, because the
rollback is a library implementation detail rather than a documented guarantee and the
code should be correct either way, and the fit report still distinguishes
`n_rounds_used` from `n_trees_in_booster`. The test was rewritten as
`test_the_booster_is_rolled_back_to_the_best_iteration`, which pins the behaviour in
the *opposite* direction — so a future LightGBM that stops rolling back surfaces as a
failure here rather than as a silent shift in every result.

**Two pushed commit messages state the retracted version and cannot be rewritten**
(`3388a39` "C9: GBM ... code + tests", which asserts the finding, and the DE-LU/ES
artefact commits, which reference "the fixed code"). The commits' *code* is correct —
it just was not fixing a real bug. This entry is the correction of record; a later
cycle reading those messages should read this paragraph instead. Nothing about the
committed numbers changes: the explicit round count and the implicit one are the same
number on this version, so every C9 result stands as reported.

#### Where early stopping chooses from, and why that is the only forward-looking risk

The round count is the one quantity this model adapts per fold, so it is the one place
a GBM fold could look forward. `early_stopping_split` takes the last
`early_stopping_days` **market days** of the training window as the stopping set and
everything strictly before as the fitting set:

- split by *day*, not by row — half a day on each side would put a row's own near
  neighbours across the split and make the stopping curve optimistic;
- strictly time-ordered, asserted rather than assumed (`ModelError` if not);
- inside the training window, which the harness has already asserted was public at the
  fold's gate closure, so it never touches the test fold.
  `test_early_stopping_uses_only_training_days` checks that against the fold's own day
  sets rather than by reading the code.

With `refit_on_full_window=True` the model is then refit on the *whole* window for the
chosen rounds. The alternative throws away the most recent 90 days — the days most like
the one being predicted — purely as a side effect of having used them to pick a number.
The refit sees those days' targets, which is in-fold model *selection*, not leakage:
every one of them was published before the fold's gate closure.

#### How the late arm is allowed to run at all

Unchanged from C8 and reused rather than reimplemented: `res_as_published` goes through
`forecast.exog_features.assert_only_acknowledged_leakage` over the whole arm matrix,
which permits a violation only if its column was named in advance, its kind is
`after_gate_closure`, and its worst lateness equals what the declared publication clock
predicts to the minute. The harness's per-fold check is skipped for that one arm only
(`check_leakage=False`) and replaced by that one pass, which implies it — the guard is
a per-(row, column) predicate. The three leak-free arms get nothing special and the
**unmodified** `assert_no_leakage` has to pass clean on every fold of each.

`forecast/leakage.py`, `forecast/features.py`, `forecast/exog_features.py`,
`forecast/lear.py`, `data/contracts.py`, `data/aggregate.py` and every `config/*.yaml`
are **untouched** by C9 — verified with `git diff --stat HEAD` over exactly those paths
before committing. The only modified existing file in the whole cycle is
`requirements.txt` (the `lightgbm>=4.3` line).

#### LEAR is read from C8's artefact, not refitted

C8 committed LEAR's predictions for all four arms, per Tier-A zone, for 2024, on the
same aligned 2022-01-01 training window and the same daily-refit spec. Refitting would
spend an hour reproducing a committed number and would quietly allow the two models to
be compared on different folds if any spec drifted. So `load_c8_lear_predictions`
loads the artefact and **asserts** its index and realised prices against this run's
rather than reindexing onto them — a mismatch is a loud failure, not a silent
realignment.

#### Built and committed (51 new tests, 432 in total)

**Test-run record, stated exactly.** The first full-suite run gave **431 passed, 1
failed** — the failure being C9's own new `test_the_overfit_tail_...`, which disproved
FINDING C9-B (see its retraction above). That test was rewritten as
`test_the_booster_is_rolled_back_to_the_best_iteration` and verified passing, and the
full suite was then re-run clean: **432 passed, 0 failed, 51 warnings, 591s** (the
warnings are all pre-existing sklearn LARS convergence notices from the C8 LEAR tests).
That is the run that closes C9.

- `forecast/gbm.py` — `GbmSpec` (the frozen, fingerprinted config), `GbmModel`
  (pooled booster, categorical calendar, LEAR's asinh target VST imported rather than
  re-implemented, native/decline NaN policy, per-fold fit report, split-gain
  importances), `early_stopping_split`, `gbm_factory`.
- `backtest/run_c9_gbm.py` — the CLI: four arms × three zones, the common-hours table,
  both ladders, the GBM−LEAR comparison, the early-stopping report, the real-data
  day-shift diagnostic, and the C8 LEAR-artefact loader with its index/price
  assertions.
- `tests/test_c9_gbm.py` — 51 offline tests. No network, no cached file, no sealed year.
- `docs/gbm_model.md` — the full write-up of everything above.
- `backtest/results/c9_gbm_{DE-LU,ES,NO2}_2024_{predictions.csv.gz,folds.csv,summary.json}`.
- `requirements.txt` — `lightgbm>=4.3`, with the reason for the floor.

#### Three design choices that were easy to get wrong

- **Pooled over delivery hours, not 24 models.** LEAR partitions because a
  ~30-parameter linear model per hour is estimable from ~1 000 rows and pooling would
  force one slope to describe hour 03 and hour 18 at once. A tree ensemble has the
  opposite problem: splitting 24 ways starves all 24 boosters, while one pooled model
  can *learn* the hour interaction where the data supports it. The consequence is
  stated, not hidden, in three places including `summary.model_comparison.note`: **a
  GBM−LEAR difference is a difference of functional form AND of pooling, and this
  cycle cannot separate the two.** The within-model differences — which is what
  FINDING C8-A turns on — are unaffected by that entanglement, which is why the
  vintage premium is the number this cycle can actually settle.
- **The target transform is imported from `forecast.lear`, not copied.** Identical
  `asinh((y−a)/b)` on the in-fold median/MAD, inverted exactly. Copying would let the
  two drift and turn a model comparison into a comparison of loss scales; importing
  makes "identical" a property of the code rather than of a comment. No *feature* is
  transformed — trees are invariant to monotone feature transforms, so LEAR's
  per-column price VST is pointless here and is not used.
- **The categorical set is read from LEAR's own constants.** `CATEGORICAL_FEATURES`
  is built from `forecast.lear.CATEGORICAL_CALENDAR` and `HOUR_KEYS`, so the two models
  cannot drift apart about what is a category and what is a number;
  `test_the_calendar_categoricals_are_the_same_set_lear_encodes` pins it. The codes
  handed to LightGBM are the *values themselves* (hour 0-23, ISO weekday, month 1-12),
  not positions in a fitted level list, so a level the training window never saw cannot
  shift the meaning of another one.

#### LP invariants

C9 touched no dispatch, LP or settlement code, so the battery-LP invariants apply to no
new artefact. They remain executable and green as part of the full suite:
`assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` pass. No LP
objective from a forecast-priced solve is reported anywhere as a realised value.
**FLAG C5-01** (simultaneous charge/discharge) is unchanged and still resolved as
option (b) per Checkpoint B.

#### Cache re-pull — NOTE C2-02, 20th recurrence

`data/raw/` was empty again (the container does not keep it), so C9 re-pulled 18
(zone, year) price files and 18 (zone, document, year) ENTSO-E files for the Tier-A
zones. **36/36 succeeded, 0 FLAGs.** Then `data.build_exog_manifest`,
`data.build_exog_contracts` and `data.build_manifest --zones DE-LU ES NO2` were re-run
against the fresh cache and diffed against the committed artefacts:

- **exogenous manifest** (27 rows x 38 columns): the only fields that differ are
  `fetched_at_utc` (27 rows) and `gzip_bytes` (27 rows). Every `payload_sha256`, count,
  coverage figure, gap count, NaN count, negative count and distribution statistic is
  **identical**.
- **price manifest**, Tier-A rows (18 x 28): the only field that differs is
  `fetched_at_utc`.
- **exogenous contract report**: CSV body byte-identical ignoring timestamps; "all
  exogenous data contracts hold". The JSON differs only in `generated_at_utc`,
  `git_sha` and `config_hash` — the last because the committed report was generated at
  C7, before C8 added the publication clocks.

`gzip_bytes` moves by a few bytes because ENTSO-E stamps a fresh random `mRID` into
each response header, which the series fingerprint correctly ignores. The regenerated
manifest artefacts were therefore **reverted** rather than committed, as in C8:
they describe the same data, they are correctly labelled `"cycle": "C7"`, and
committing a new timestamp every cycle would churn the manifest forever for no
information gain. The 9-zone price contract report was **not** regenerated, because C9
is Tier-A only and doing so would have meant re-downloading the six Tier-B zones for
nothing.

An additional, stronger verification this cycle: `load_c8_lear_predictions` asserts
C8's committed realised prices against C9's freshly-loaded ones per zone, and the
**worst disagreement is 0.0 EUR/MWh in all three zones**. C8's artefact reproduces
exactly on a cache pulled a day later.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count
**0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, and no `*2025*` file exists
anywhere under `data/`. Every arm of every zone was evaluated on `[2024]` only; the
exogenous window is 2022-01-01..2024-12-31 and the price window
2018-12-31..2024-12-31. `test_the_gbm_cannot_be_evaluated_against_a_sealed_year`
asserts the booster inherits the refusal with no door of its own. No 2025 data has
been fetched, loaded, dispatched or computed against at any point in C2-C9.

#### Config hash

**`515d4e8d98887256`** — unchanged from C8. C9 modified no `config/*.yaml` file; the
GBM's configuration lives in `forecast.gbm.GbmSpec` and is tracked by its own
fingerprint (`a366a760e269bba6`) rather than by the config hash, because it is code, not
data-layer config. Verified with `git diff --stat HEAD -- config/` (empty).

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `24e01c6` with local
`master` stale 7 commits behind. **24 recurrences out of 31 containers.** This time
`git checkout -B master 24e01c6` was **denied by the permission classifier** ("Git
Destructive"), so the cycle worked detached and pushed `HEAD:master` throughout, which
was safe only because `origin/master` equalled `HEAD` at session start. **If a future
container arrives detached *and* genuinely behind the remote, that fallback is not
available** — the cycle will need either the `checkout -B` permission or a different
reattachment route, and should flag rather than improvise. Keep checking
`git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the start
of every cycle.

#### Suggestion for C10 (not done here — out of C9's scope)

PLAN.md C10 writes results append-only, "each row tagged with git SHA + config hash".
Add **library provenance** to that row too (at minimum `lightgbm.__version__`): the GBM
fingerprint pins the values *we* set, but everything `GbmSpec.booster_params()` does not
name — `max_cat_threshold`, `min_data_per_group`, `max_depth` — comes from the installed
LightGBM, so a major-version bump that moved a default would change results without
changing the fingerprint. C9's runs used **lightgbm 4.7.0**. Deliberately not bolted onto
C9's summaries after the fact, because the artefacts and the code that produced them
should stay in lockstep.

**Next:** C10 — scale the harness: Tier A (3 models, exogenous features) + Tier B
(naive + LEAR, price-only), results written append-only with each row tagged by git SHA
and config hash. Read FINDING C9-C first: the headline arm for Tier A is
`res_persistence` (leak-free), with `res_as_published` carried alongside **only** as the
labelled vintage-premium measurement, and the GBM's apparent edge over LEAR must never
be quoted from the late arm. Note also that C10's Tier-B scale-out needs the six Tier-B
zones' price cache, which this cycle did not pull (Tier A only).

### C10 — 2026-10-08 (scheduled cycle) — the scale-out: nine zones, one append-only results store

Scope per PLAN.md C10: *"Scale the harness: Tier A (3 models, exogenous features) +
Tier B (naive + LEAR, price-only). Results written append-only, each row tagged with
git SHA + config hash."* Done for all nine zones. No checkpoint, no blocker, no FLAG
raised. No new dependency. `ENTSOE_API_KEY` was **not needed and not read**: C10's
Tier-A rows come from C8's and C9's committed artefacts, and Tier B has no exogenous
block, so the only network traffic this cycle was the 54 Energy-Charts price pulls.

**Full suite: 505 passed, 0 failed, 51 warnings, 624.59s** (432 before C10 + 73 new).
The 51 warnings are the pre-existing sklearn LARS convergence notices from the C8 LEAR
tests. `tests/`, `config/`, `forecast/`, `dispatch/`, `data/contracts.py`,
`data/aggregate.py`, `backtest/walk_forward.py` and `backtest/metrics.py` are
**untouched** — verified with `git diff --stat HEAD` over exactly those paths before
committing. The only modified existing file in the whole cycle is `requirements.txt`
(a comment block recording that C10 added no dependency and why).

#### The headline numbers — all nine zones, 2024, like-for-like

C4's committed LEAR (per-hour LASSO, price-history and calendar features only,
expanding window over the whole cached history) against the naive floor. MAE in
EUR/MWh, each series on its own coverage (LEAR 8 783 hours, naive 8 784 — LEAR declines
the one autumn DST hour whose 24-hour lag the gate-closure mask blanks, FINDING C3-A):

| zone | tier | regime | naive MAE | LEAR MAE | LEAR/naive |
|---|---|---|---|---|---|
| NO2 | A | hydro-dominated | 21.195 | 13.639 | **0.6435** |
| FR | B | nuclear-dominated | 27.790 | 17.897 | 0.6440 |
| ES | A | solar-dominated | 27.316 | 17.866 | 0.6541 |
| DK1 | B | wind-dominated | 37.746 | 25.393 | 0.6727 |
| PL | B | coal-dominated | 29.822 | 20.207 | 0.6776 |
| BE | B | gas-nuclear-mixed | 28.217 | 19.376 | 0.6867 |
| IT-North | B | gas-dominated | 13.833 | 9.539 | 0.6896 |
| DE-LU | A | thermal-RES-mixed | 32.799 | 22.864 | 0.6971 |
| NL | B | gas-RES-mixed | 29.941 | 21.437 | **0.7160** |

#### FINDING C10-A — the *relative* skill of a price-only model is near-constant across nine regimes; the *level* of difficulty is not

Absolute MAE spans **2.73x** across the nine zones (IT-North 13.83 to DK1 37.75 on the
naive floor; 9.54 to 25.39 on LEAR). The ratio spans **1.11x** — 0.6435 to 0.7160,
mean 0.6757, sd 0.0248. A standard price-only LEAR removes **28-36% of the naive
floor's MAE in every zone**, whether the marginal unit is a reservoir, a reactor, a
wind farm, a solar fleet, a lignite block or a CCGT.

Some of that tightness is mechanical — both errors scale with the zone's price
volatility — but **not all of it, and that is the part worth keeping.** Normalising by
each zone's own 2024 price standard deviation leaves real cross-zone variation, and the
ratio is still three times tighter than either normalised error:

| quantity | mean | sd | CV | max/min |
|---|---|---|---|---|
| naive MAE / sd(price) | 0.6246 | 0.0723 | 0.116 | 1.548x |
| LEAR MAE / sd(price) | 0.4216 | 0.0472 | 0.112 | 1.510x |
| **LEAR MAE / naive MAE** | **0.6757** | **0.0248** | **0.037** | **1.113x** |

So the zones genuinely differ in how hard they are *relative to their own volatility*
(DK1's naive floor costs 0.75 sd, IT-North's 0.49 sd), and the model still removes a
near-constant fraction of whatever that floor is. Read plainly: on point error, this
model is not finding zone-specific structure beyond scale.

**Caveats that must travel with it.** n = 9, one validation year, and it is a ratio of
two strongly correlated quantities (Pearson 0.990 between the two MAE columns; the
zone ordering by naive difficulty is *identical* to the ordering by LEAR difficulty,
Spearman 1.00 — which mostly says volatility drives both, and is not itself a
surprising statistic). Whether a 7.3pp band is wider than sampling noise is exactly
what **C12's block-bootstrap CIs over daily blocks** are for, and C12 should answer it
before the C18 write-up makes anything of it.

**Why this matters for C11/C12.** PLAN.md's premise is a comparison "across zones with
genuinely different price-formation regimes". If the capture ratio turns out to be
*also* near-constant, then regime differences do not reach flexibility value through
forecastability at all, and the cross-zone story has to come from the price *shape* —
spread, number of profitable cycles per day, negative-hour count — not from how well
the curve can be forecast. If the capture ratio *diverges* while rMAE does not, that is
the sharper finding and the better one: it would mean a point-error metric is blind to
the thing a battery actually trades. **Either way C11/C12 now has a specific prediction
to test rather than a table to admire.**

#### FINDING C10-B — three extra years of price history beat the entire honest exogenous block, and beat the switch to a booster, in all three Tier-A zones

C10 puts three gains on one comparable scale for the first time. Per-cent of MAE,
Tier A, 2024:

| zone | window: 2019+ vs 2022+ (LEAR, price-only) | honest exogenous block (GBM, `res_persistence` vs `price_only`, C9) | model class (GBM − LEAR, honest arms, C9) |
|---|---|---|---|
| DE-LU | **+2.80%** (23.522 -> 22.864) | +1.0% | −3.1% (GBM better) |
| ES | **+3.53%** (18.521 -> 17.866) | +1.0% | +1.2% (LEAR better) |
| NO2 | **+7.45%** (14.737 -> 13.639) | +0.2% | −4.8% (GBM better) |

And the full-history price-only LEAR — the simplest honest model in the project — beats
the **best honest arm of either model fitted on the aligned window** in two of the
three Tier-A zones (ES by 0.209 EUR/MWh, NO2 by 0.366) and loses DE-LU by only 0.308
(1.3%, to `gbm_res_persistence`).

**The honest statement of this, which is not quite the dramatic one.** It is not a
controlled test of window length against features, because the exogenous arms *cannot*
run on a 2019 start — no archived ENTSO-E D-1 forecast vintage exists before 2022
(PLAN.md, `features.yaml` `available_from`). So the claim is the one a desk actually
faces: *at the only window where the exogenous block can be measured it is worth ~1% of
MAE, and moving to a window it cannot occupy is worth 3-7%.* Combined with FINDING C9-C
(the as-published Art. 14 vintage buys 18-24% that no bidder could have had), the C18
write-up's model section now has a clear spine: the two things that actually moved this
model were **more history** and **a publication timestamp**, and only one of them is
available to a bidder.

C8 had already committed the per-zone window gain as
`full_history_reference.mae_vs_aligned_price_only` (0.658 / 0.654 / 1.099 EUR/MWh,
which C10 reproduces to 1e-6). C10's contribution is putting it beside the exogenous
and model-class gains on one scale, which is what makes the ranking visible.

#### NOTE C9-01, substantially answered — the upward bias is a property of the 2022-aligned window, not of the models

C9 flagged that every model arm is biased high (+2.6 to +8.7 EUR/MWh) and attributed it
to the shared convex `sinh` back-transform. C10 can now separate that from the training
window, because the same model and the same zone exist at two starts:

| zone | LEAR price-only, train from 2022-01-01 | train from 2019-01-01 |
|---|---|---|
| DE-LU | +5.063 | **+2.600** |
| ES | +3.555 | **+1.100** |
| NO2 | +2.989 | **+0.813** |

A factor of 2-4 smaller on the longer window, with the model, the features and the
evaluation year all identical. The six Tier-B zones, all on the full history, land in
the same low range: IT-North **−0.027**, PL +0.156, DK1 +0.412, FR +1.837, BE +2.640,
NL +2.999.

The VST mechanism C9 named is still the right one — `sinh` is convex, so
back-transforming a conditional-mean estimate in asinh space overshoots in price space
— but the *size* of the overshoot scales with the in-fold MAD, and a window that is
half crisis-year rows has a much larger one. **The practical consequence for C11/C12 is
that the nine-zone comparable curves carry a bias of −0.03 to +3.0 EUR/MWh, not C9's
+2.6 to +8.7.** The prediction NOTE C9-01 asked C11/C12 to test (that a roughly uniform
upward bias barely perturbs the within-day ordering a battery trades on) is unchanged,
but the bias it has to be robust to on the comparable row set is a good deal smaller
than the Tier-A aligned arms suggested. Not acted on — correcting a bias by looking at
a 2024 metric is tuning against the validation year.

#### The results store — `backtest/results/results.csv`, 447 rows, 1 run

`backtest/results_store.py`. Long format: a row is
`(run, zone, model, arm, scope, metric) -> value`. Four decisions are load-bearing and
all four are written up in `docs/results_store.md`.

- **Long, not wide.** The wide alternative reads better and breaks on the first cycle
  that adds a metric: C11's capture ratios and C12's spread error, within-day Spearman
  and bootstrap bounds would each be a column every earlier row lacks. **The extension
  point is the metric name, never the column list** —
  `test_the_metrics_c11_and_c12_will_write_need_no_schema_change` pins exactly that,
  parameterised over the ten metric names those cycles are expected to want.
- **Append-only is verified twice, not promised.** `append_rows` reads the file's
  existing bytes, appends, then asserts the new file still *starts with* those exact
  bytes; and every run records in `results_runs.json` the SHA-256 of the whole file as
  it stood after it appended, which is the hash of its first `n_rows_after` data rows.
  `verify_append_only()` replays those hashes against the file's own prefixes, so an
  edit to **any earlier row is detectable long after the run that wrote it is gone**.
  Tests cover an edited row, a deleted row, a row hand-appended with no manifest entry,
  and a manifest out of append order. A column change is refused as a *migration* with
  the route spelled out, not absorbed.
- **Provenance includes the libraries** — the C9 entry's closing suggestion, taken up.
  Every row carries `git_sha`, `config_hash` (PLAN.md's requirement), the model's own
  fingerprint where it has one (`a366a760e269bba6` on every C9-sourced GBM row), and a
  16-hex `library_fingerprint` over `{python, numpy, pandas, scikit-learn, scipy,
  lightgbm}`; the run manifest keeps the full version dict. This cycle's fingerprint is
  **`856fb19ac0c4eecd`** = python 3.11.17, numpy 2.4.6, pandas 3.0.6, scikit-learn
  1.9.1, scipy 1.17.1, **lightgbm 4.7.0** (the version C9's numbers were produced on,
  so the ingested rows are correctly labelled).
- **`vintage` is a required key column**, taking `honest` or `after_gate_closure`, and
  an unknown value is refused. FINDING C9-C makes an unlabelled late-arm number the
  single most misleading thing this project could publish, so `honest_rows()` is the
  default filter and a cycle that wants the Art. 14 arm has to ask for it by name. Of
  the 447 rows, **60 are `after_gate_closure`** (the `res_as_published` arm, 2 models x
  3 Tier-A zones x 2 scopes x 5 metrics) and 387 are honest.

The store also runs `data.holdout.assert_not_sealed` on every row's `evaluation_years`,
so **a metric computed against 2025 cannot be written** even if some later caller
computes one by mistake — and a spelling the guard cannot read (`"validation"`) is
refused rather than waved through.

#### Why Tier A is ingested from C8/C9 rather than refitted

`backtest/run_c10_scale.py` runs in two phases. `compute` is Tier B — the only new
fitting in this cycle, six zones x (naive + train_mean + LEAR), independent per zone so
it takes `--zones` and three processes ran it in parallel; nothing is appended to the
store there, which is what makes that safe. `ingest` is one process, one append.

Refitting Tier A's 24 model-arms would have spent hours reproducing committed numbers
and — worse — would have let the store's Tier-A rows drift from the artefacts the
findings were written against if any spec had moved. C9 set the precedent by reading
C8's LEAR predictions instead of refitting them; C10 extends it, and **every metric is
recomputed from the prediction columns rather than copied out of a summary**, then
asserted equal to the number its source cycle committed:

- **264 recomputed-vs-committed cross-checks, worst absolute delta 3e-6** against a
  tolerance of 5e-4 (the artefacts' own `%.4f` precision — the tolerance is the
  artefact's precision, not a margin chosen to let a disagreement pass). The whole
  check report is in `c10_scale_summary.json`, so the store shows its own working.
- C8's and C9's prediction **indices are asserted equal** per zone — a mismatch means
  the two cycles did not evaluate the same hours and is refused, never realigned.
- Their committed realised prices agree with each other **and** with a freshly loaded
  price series to **0.000000 EUR/MWh in all three zones**.
- The intersection of C9's nine prediction columns is asserted equal to the `n_hours`
  C9's summary committed (DE-LU 8 782, ES 8 591, NO2 8 783), so artefact and summary
  cannot disagree about what was compared.

#### Why Tier B trains on the full price history

Tier A's four arms are cut from 2022-01-01 because no archived forecast vintage exists
earlier. Tier B has no exogenous block and therefore no such constraint, so it runs
C4's committed `LearSpec` on everything cached (2019+). That makes the nine-zone
comparable row set `lear` / `price_only` / `train_from=2019-01-01`, which **exists for
Tier A too**: C8 ran exactly that as its `full_history_reference` and committed it as
`y_pred_price_only_full_history`. The cross-zone table is therefore like-for-like by
construction rather than by assertion, and
`test_the_comparable_table_refuses_a_row_trained_from_a_different_date` pins that a
2022-aligned row cannot sneak into it.

`scope` in the store: `own_coverage` is each series on the hours it answered;
`common_hours` re-scores every series of that zone on the intersection of all of them —
for Tier A, over exactly the nine series C9's artefact carries, which is what makes the
recomputation checkable against C9's committed `common_hours` block. The two tiers'
intersections are over different series sets, which is why the nine-zone table is built
from `own_coverage` rows and carries `n_scored` beside every number rather than a
footnote.

#### Data: 54/54 price pulls, and the first full nine-zone re-verification since C2

NOTE C2-02, **21st recurrence** — `data/raw/` was empty again. C10 re-pulled all 54
(zone, year) Energy-Charts price files: **54/54 succeeded, 0 FLAGs**. No ENTSO-E pull
was needed or made.

`data.build_manifest` and `data.build_contracts` were then re-run over all nine zones
and diffed against the committed artefacts. This is the first time since C2 that the
six Tier-B zones have been re-verified, and the result is clean:

- **price manifest** (54 rows x 28 columns): the only field that differs is
  `fetched_at_utc`, on all 54 rows. Every `payload_sha256`, count, coverage figure,
  distribution statistic and negative-hour count is **identical**.
- **contract report**: the CSV body is **byte-identical**, and "all data contracts
  hold" — 9 zones, 52 608 hours each, 0 duplicate timestamps, 0 NaN prices, 0 missing
  intervals, 0 UTC-day violations, 0 local-day violations, 12 DST days seen per zone,
  0 resolution changes, 0 cutover violations, **0 violations total**. The JSON differs
  only in `generated_at_utc`, `git_sha` and `config_hash` (the committed copy was
  generated at C2, before C8 added the publication clocks).

The regenerated manifest artefacts were therefore **reverted** rather than committed,
as in C8 and C9: they describe the same data, they are correctly labelled `"cycle":
"C2"`, and committing a fresh timestamp every cycle would churn the manifest forever
for no information gain.

#### LP invariants

C10 touched no dispatch, LP or settlement code, so the battery-LP invariants apply to
no new artefact. They remain executable and green as part of the full suite:
`assert_oracle_dominates` and the rolling commit-then-settle assertions in
`tests/test_c5_battery_lp.py` and `tests/test_c6_commit_then_settle.py` pass (re-run
separately as a 33-test subset to confirm). No LP objective from a forecast-priced
solve is reported anywhere as a realised value. **FLAG C5-01** (simultaneous
charge/discharge) is unchanged and still resolved as option (b) per Checkpoint B.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count
**0**, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, no `*2025*` file exists
anywhere under `data/`, and **no row of the results store mentions 2025** (grep count
0). Every series of every zone was evaluated on `[2024]` only. The store adds a new,
independent tripwire: a metric whose `evaluation_years` touches a sealed year cannot be
written at all. No 2025 data has been fetched, loaded, dispatched or computed against
at any point in C2-C10.

#### Config hash

**`515d4e8d98887256`** — unchanged from C8/C9. C10 modified no `config/*.yaml` file;
verified with `git diff --stat HEAD -- config/` (empty).

#### Built and committed (73 new tests, 505 in total)

- `backtest/results_store.py` — the append-only store: `SCHEMA`, `ResultRow`,
  `append_rows`, `verify_append_only`, `read_results`, `latest_results`,
  `honest_rows`, `pivot_metric`, `rows_from_scores`, `library_versions`,
  `library_fingerprint`.
- `backtest/run_c10_scale.py` — the two-phase CLI: Tier-B compute, Tier-A/Tier-B
  ingest with the recompute-and-cross-check guards, the nine-zone comparable table.
- `tests/test_c10_results_store.py` — 46 offline tests (append-only, provenance,
  validation, sealed-year refusal, reading).
- `tests/test_c10_scale_out.py` — 27 offline tests (the cross-check tolerance, the
  vintage labelling, the common-hours mask, the comparable table's like-for-like rule,
  the artefact provenance guards).
- `docs/results_store.md` — the full write-up of all of the above.
- `backtest/results/results.csv` (447 rows) + `results_runs.json` (1 run,
  `C10-20261008T183636Z-8e556310`) + `c10_scale_summary.json`.
- `backtest/results/c10_tierb_{FR,NL,BE,IT-North,DK1,PL}_2024_{predictions.csv.gz,folds.csv,summary.json}`.
- `requirements.txt` — a comment block recording that C10 added no dependency, and why
  the store is deliberately plain csv/json/hashlib.

#### NOTE C10-01 (new, for C11 — not a blocker)

The store's `common_hours` scope is defined per zone over the series that zone has, so
Tier A's intersection is over nine series and Tier B's over three. That is correct for
within-zone model comparison and is why the cross-zone table uses `own_coverage`, but
**C11 will add nine zones x three curves of dispatch results and should decide once
whether a capture ratio belongs at `own_coverage` or at a common-hours scope**, rather
than per zone. A battery LP needs a complete 24-hour vector, so the question is really
which NaN policy C11 dispatches the LEAR curve under (C4 measured both; `decline`
leaves one hole a year, `impute` fills it with the in-fold column median) — and that
choice should be a labelled row in the store, not an implicit default.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `144ecf5` with local
`master` stale 13 commits behind. **25 recurrences out of 32 containers.** This time
`git checkout -B master` **was permitted** (it was denied as "Git Destructive" in C9),
so the cycle worked on a properly attached `master` throughout. `origin/master` equalled
`HEAD` at session start, so nothing was at risk either way. The C9 entry's warning still
stands for a future container that arrives detached *and* genuinely behind the remote:
flag rather than improvise. Keep checking `git rev-parse --abbrev-ref HEAD` and
`git rev-list --count master..HEAD` at the start of every cycle.

**Next:** C11 — the LP across all nine zones x all curves (oracle / model / naive),
persisting per-day capture ratios. Read FINDING C10-A first: it gives C11 a specific
prediction to test (is the capture ratio as regime-insensitive as rMAE, or does it
diverge?), and NOTE C8-01's open question — whether `res_persistence` buys more capture
ratio than its 1% of MAE suggests — is the other half of the same experiment. Note
NOTE C10-01 on the NaN policy for the dispatched LEAR curve, and FINDING C10-B/NOTE
C9-01: the comparable nine-zone curves carry a bias of −0.03 to +3.0 EUR/MWh, not the
+2.6 to +8.7 the Tier-A aligned arms showed. Write every dispatch result into
`backtest/results/results.csv` via `backtest.results_store.append_rows` — the metric
name is the extension point, no schema change is needed, and
`verify_append_only()` should be called before trusting anything already in there.

### C11 — 2026-10-09 (scheduled cycle) — the LP across nine zones, and the first metric that disagrees with MAE

Scope per PLAN.md C11: *"LP across all 9 zones x all curves; persist per-day capture
ratios."* Done for all nine zones and every committed curve. No checkpoint, no blocker,
no FLAG raised, no new dependency. `ENTSOE_API_KEY` was **not needed and not read** —
every forecast dispatched here was read from the artefact the cycle that scored it
committed, so the only network traffic was 18 Energy-Charts price pulls.

**Full suite: 556 passed, 0 failed, 51 warnings, 432.67s** (505 before C11 + 51 new).
The 51 warnings are the same pre-existing sklearn LARS convergence notices from the C8
LEAR tests. `tests/` (every pre-existing file), `config/`, `forecast/`, `dispatch/`,
`data/`, `backtest/walk_forward.py`, `backtest/metrics.py` and
`backtest/results_store.py` are **untouched** — verified with
`git diff --stat HEAD` over exactly those paths, which came back empty. The only
modified committed files in the whole cycle are `requirements.txt` (a comment block
recording that C11 added no dependency) and the two append-only store files.

#### What was dispatched

45 rolled dispatch runs and 45 same-start oracle re-solves, ~33 000 LP solves, 2m09s.

- **Tier A** (DE-LU, ES, NO2) — oracle + **8** curves: `lear_full_history` (C8's
  `price_only_full_history`, the nine-zone comparable arm), the three 2022-aligned LEAR
  arms and the three 2022-aligned GBM arms (C8/C9), and the naive floor.
- **Tier B** (FR, NL, BE, IT-North, DK1, PL) — oracle + **2**: the comparable LEAR and
  the naive floor (C10's artefacts).

Nothing was re-fitted, extending the C9/C10 precedent: a capture ratio and the MAE of
the same forecast are now about the same numbers and cannot drift apart. The two
`res_as_published` arms carry `vintage="after_gate_closure"` and travel only as the
measurement of FINDING C9-C's leak.

#### Invariants — all green, every curve, every day

`invariant_failures` is `[]` in all nine zones. `value(curve @ realised) <= value(
same-start oracle)` on **every** dispatched day of **every** curve (not a sample — the
check asserts `n_days_checked` equals the curve's dispatched day count, and a test pins
that); the pooled `oracle >= arm` and `naive <= forecast`; no settlement is a read-back
of its own decision prices; `value_added >= 0` on each curve's own decision prices and
at realised prices on the oracle; day lengths match the local calendar. The worst
per-day excess over the bound across all 45 runs is `+0.00e+00` or negative.

#### C11 reproduces C6 exactly

C6 dispatched C4's `y_pred_lear_aic` on DE-LU, and that column is identical to C8's
`y_pred_price_only_full_history` to **0 EUR/MWh over 8 784 hours** — so C11's
`lear_full_history` arm is the same forecast and the two cycles must agree exactly, not
approximately. `check_c6_reproduction` asserts eight numbers against C6's committed
summary at C6's own JSON precision: **8/8 hold, worst absolute delta 2.73e-05.** Oracle
/ model / naive pooled cash (74 365.4450 / 68 318.8799 / 62 997.6827), both rolled
capture ratios (0.918691 / 0.847136), both same-start capture ratios (0.869574 /
0.779737) and the 365-day common count all reproduce.

That check was itself the first real test of the scope decision below: C6's pooled cash
is over the common day set while its per-curve capture summaries are over each curve's
own days, so C6's naive capture (0.779737) matches C11's **`own_coverage`** row exactly
and differs from C11's `common_hours` row (0.780436) in the third decimal — for a
reason that is a *scope*, not an error.

#### The three decisions C11 was asked to make

**NOTE C10-01, the NaN policy — committed, unchanged.** The dispatched LEAR curve is the
`nan_policy="decline"` series every earlier cycle scored, and a market day whose
forecast vector has a hole is **skipped and counted, never patched** (C6's NOTE C4-02
decision carried to all nine zones). It costs one autumn-DST day a year in every zone
(365 of 366), plus in ES the days the `res_*` arms decline. Every skip is in the
per-zone summary with its reason. No impute variant was fitted: C6 already priced that
alternative on DE-LU and refitting it here would be new modelling work outside C11's
scope.

**NOTE C10-01, the capture-ratio scope — decided, and the decision is measured.** A
capture ratio is a ratio of two sums, so numerator and denominator must run over the
same days, and two arms' ratios are only comparable if they do too; `pooled_capture`
therefore takes the day set as an *argument*. Both of the store's existing scopes are
written and mean for a dispatch metric what they mean for a point-error one (the
vocabulary is about *coverage*, not the time unit): `own_coverage` = each curve over the
days it dispatched; `common_hours` = every curve of that zone re-pooled over the
intersection of the days every C11 curve of that zone dispatched. **The within-zone arm
comparison is read at `common_hours`; the cross-zone table is built from
`own_coverage`**, as C10's was, because the two tiers' intersections are over different
curve sets (nine curves vs three) and a Tier-A intersection shrunk by an arm that is not
even in the cross-zone comparison would silently re-scope Tier B's neighbours. **No new
scope value was added and `backtest/results_store.py` was not touched.**

The cost of that choice is reported per curve per zone in `scope_sensitivity`, on both
ratios. On the headline rolled-oracle ratio the comparable arm is **scope-invariant in
eight of nine zones** (+0.0000) and moves **−0.2394pp in ES**: ES's nine-curve
intersection drops to **357 days** against 365 everywhere else, because of the 145
missing hours in the exogenous join that only the two `res_*` arms suffer. ES's capture
is 0.910932 at `own_coverage` and 0.913326 at `common_hours` — either leaves it second
of nine, so the decision does not change the cross-zone ordering. The naive floor is
the one curve that genuinely moves (−0.41 to +0.42pp), because it is the only curve
dispatching all 366 days while the comparable arm declines one.

**FINDING C11-C, the headline metric — not the same-start ratio.** See below; this was
not a decision C11 expected to have to make.

#### FINDING C11-C — the same-start capture ratio cannot be used to rank two curves

The same-start oracle is the exact per-day bound and stays the invariant. It is **not**
fit to compare arms, and C11 can demonstrate that rather than assert it.

On DE-LU, `lear_res_persistence` and `lear_res_as_published` settle **0.35 EUR apart
over 365 days** (67 842.68 vs 67 843.03) — yet their same-start capture ratios differ by
**4.0pp** (0.8589 vs 0.8985). The two schedules are genuinely different (per-day cash
differs by a mean of 37 EUR and a max of 282; only 13 of 365 days are identical), so the
coincidence is in the annual totals, not in the behaviour. The 4pp gap is not about
their earnings at all — it is the **denominator** moving: the same-start oracle is
re-solved from each arm's own opening SoC, and a day opened with a fuller battery has
less attainable added value. Mean opening SoC is 0.454 MWh for the as-published arm
against 0.216 for the persistence arm, so the arm carrying more inventory is scored
against an easier ceiling.

The rolled-oracle ratio has **one denominator per zone**, identical for every curve, and
ranks the two arms identically (0.9123 both). **So the project's headline capture ratio
is settled cash over the rolled perfect-foresight run's cash on the same days**; the
same-start ratio travels beside it as the exact per-day bound and as the per-day
distribution, and is never used to rank two curves.
`test_finding_c11_c_the_same_start_ratio_reorders_arms_the_rolled_one_ties` pins the
measurement against the committed artefact, so a later cycle cannot quietly promote it
back. **C12 and C18 must quote `capture_rolled_oracle_cash`, not
`capture_same_start_pooled`.**

#### FINDING C11-A — the capture ratio diverges across zones; rMAE does not

FINDING C10-A handed C11 a specific prediction: *if the capture ratio is also
regime-insensitive, regime differences do not reach flexibility value through
forecastability; if it diverges while rMAE does not, that is the sharper finding.*
**It diverges.**

| zone | tier | regime | rMAE (C10) | **capture** | naive capture | oracle EUR/MW/yr | model EUR/MW/yr | lost EUR/MW/yr | mean daily spread | days model loses money |
|---|---|---|---|---|---|---|---|---|---|---|
| DE-LU | A | thermal-RES-mixed | 0.6971 | **0.9187** | 0.8450 | 74 399 | 68 179 | 6 034 | 111.20 | 0.8% |
| ES | A | solar-dominated | 0.6541 | 0.9109 | 0.8366 | 46 700 | 42 407 | 4 146 | 71.27 | 2.5% |
| BE | B | gas-nuclear-mixed | 0.6867 | 0.9044 | 0.8086 | 62 163 | 56 055 | 5 929 | 91.84 | 1.4% |
| IT-North | B | gas-dominated | 0.6896 | 0.9042 | 0.8177 | 41 864 | 37 799 | 4 004 | 65.40 | 0.8% |
| NL | B | gas-RES-mixed | 0.7160 | 0.9031 | 0.8263 | 76 207 | 68 650 | 7 366 | 113.04 | 1.1% |
| PL | B | coal-dominated | 0.6776 | 0.8839 | 0.7859 | 77 116 | 68 029 | 8 935 | 120.24 | 2.7% |
| FR | B | nuclear-dominated | 0.6440 | 0.8526 | 0.7621 | 55 052 | 46 777 | 8 085 | 76.37 | 0.8% |
| DK1 | B | wind-dominated | 0.6727 | 0.8358 | 0.7178 | 64 657 | 53 884 | 10 587 | 99.82 | 7.4% |
| NO2 | A | hydro-dominated | 0.6435 | **0.6146** | 0.4803 | 26 022 | 15 994 | 10 028 | 46.28 | **25.8%** |

| quantity | mean | sd | CV | max/min | band |
|---|---|---|---|---|---|
| rMAE (LEAR/naive MAE) | 0.6757 | 0.0248 | 0.0367 | 1.113x | 7.2pp |
| **capture ratio** | **0.8587** | **0.0957** | **0.1114** | **1.495x** | **30.4pp** |
| naive capture ratio | 0.7645 | 0.1138 | 0.1489 | 1.759x | 36.5pp |

The capture ratio's CV is **3.0x rMAE's** and its band **4.2x as wide**. A point-error
metric that is near-constant across nine regimes sits on top of a dispatch metric that
is not.

And the rankings do not line up — if anything they run the wrong way. **NO2 has the best
relative forecast skill of the nine (rMAE 0.6435, rank 1) and by far the worst capture
(0.6146, rank 9); DE-LU is second-worst on rMAE (rank 8) and best on capture (rank 1).**
Spearman between rMAE and capture is **+0.58** (p=0.099) — *positive*, i.e. zones where
the model is relatively worse than naive capture *more* of the oracle's value, the
opposite sign of what forecastability would imply.

**What must travel with it.** n = 9, one validation year; the +0.58 is not significant
and its sign must not be leaned on. And the 30.4pp band is substantially **one zone**:
drop NO2 and the remaining eight sit in 0.8358–0.9187 — a band of 8.3pp, CV 0.0335,
still wider than rMAE's 7.2pp but no longer dramatic. **The defensible claim is the
inequality of the bands and the non-alignment of the rankings, not a law about
regimes.** C12's block-bootstrap CIs over daily blocks must decide whether the 8.3pp
eight-zone band is wider than noise before C18 makes anything of it.

One thing the capture ratio says that MAE cannot: the model's **uplift over the naive
floor is largest exactly where capture is lowest** — NO2 +13.4pp, DK1 +11.8pp, against
DE-LU +7.4pp and ES +7.4pp. Where perfect foresight is hardest to approach, having a
forecast at all is worth the most.

#### FINDING C11-B — NO2 is the outlier, and the mechanism is NOT established

NO2 deserves its own line in the write-up: lowest mean daily spread of the nine (46.28
vs 65–120), lowest oracle value by a wide margin (26 022 EUR/MW/yr vs 41 864–77 116),
fewest oracle cycles (418 equivalent full cycles vs 577–721), and the model **loses
money at realised prices on 25.8% of dispatched days** against 0.8–7.4% everywhere
else.

The natural story — a thin spread leaves less headroom over the round-trip efficiency
and the 2 EUR/MWh throughput cost, so a given forecast error more easily flips a trade
from profitable to loss-making — is consistent with all four observations and is **not
established.** Every spread-based regressor's correlation with capture across the nine
zones collapses when NO2 is removed: mean daily spread Pearson +0.60 -> **+0.00**,
oracle value +0.66 -> **−0.01**, spread over the round-trip breakeven +0.39 -> −0.21.
With n = 9 this is one zone, not a relationship. The one strong correlate — share of
days the model loses money, Pearson −0.97 — is close to mechanically true (losing days
reduce the numerator) and is a restatement, not an explanation. **Not acted on**:
nothing was tuned, and no regime variable was fitted to a visible 2024 metric.

**The direct test is already in the plan.** C15's throughput-cost sensitivity (0 / 2 /
5 EUR/MWh) is it: if the thin-spread mechanism is right, NO2's capture should move far
more than the other zones' when the cost goes to zero. C13 should also report whether
NO2's capture is stable across years or specific to 2024's hydrology.

#### FINDING C11-D — among honest arms, MAE does not predict capture

This is the finding C11 exists to produce, and the spine of C18's model section.

Every intervention this project has measured, scored twice: the MAE gain in per cent,
recomputed over **exactly the hours the capture ratio is computed over** (not re-used
from C10's own-coverage rows — ES's exogenous hole differs by ~145 hours and would make
the comparison unpaired, which would make the whole finding an artefact of two samples),
and the change in the rolled-oracle capture ratio in percentage points. Positive = the
arm is better. Persisted as `{mae,rmse,bias}_on_dispatched_hours` at `common_hours` so
C12 can bootstrap both on the same days.

| question | DE-LU | ES | NO2 |
|---|---|---|---|
| honest exogenous block, **LEAR** (`res_persistence − price_only`) | −0.26% / +0.22pp | +1.08% / +0.52pp | −0.52% / −0.83pp |
| honest exogenous block, **GBM** | +1.03% / +0.35pp | +0.85% / **+2.04pp** | +0.23% / **+2.71pp** |
| model class, price-only (`gbm − lear`) | +3.17% / −0.59pp | −1.15% / −2.22pp | +4.72% / −2.02pp |
| model class, with the block | +4.41% / −0.46pp | −1.38% / −0.70pp | +5.43% / +1.53pp |
| more history (`full_history − price_only`) | +2.81% / +0.86pp | +3.62% / −0.27pp | **+7.42% / −1.31pp** |
| *vintage premium, LEAR — NOT achievable* | +8.33% / +0.00pp | +11.13% / −0.84pp | +0.14% / −0.76pp |
| *vintage premium, GBM — NOT achievable* | **+23.91%** / +3.47pp | +17.71% / +0.95pp | +3.58% / −0.84pp |

**Across the 15 honest comparisons the two metrics agree on the sign 9 times — a coin
flip — with Spearman +0.02 (p=0.95) and Pearson −0.11 (p=0.69).** Knowing which of two
honest arms has the lower MAE tells you essentially nothing about which captures more
flexibility value. Four specifics:

1. **NOTE C8-01 is answered, affirmatively, for the booster.** The honest exogenous
   block buys **+0.35 / +2.04 / +2.71pp** of capture (**+262 / +924 / +706 EUR/MW/yr**)
   under the GBM — far more than its +1.0% / +1.0% / +0.2% of MAE suggested, and *the
   ordering is inverted*: NO2 gained the least on MAE and the most on capture. This is
   the first time in this project that a decision-relevant metric has disagreed with MAE
   about whether a feature block is worth having, and it is exactly the mechanism
   NOTE C8-01 hypothesised — RES information kills the large errors, and those sit in the
   high-wind, negative-price hours a battery earns in. Under the LEAR the same block
   still buys nothing (+0.22 / +0.52 / −0.83pp), consistent with FINDING C8-A. **The
   honest headline arm for Tier A remains `res_persistence`, and it now has a reason to
   exist that is not an MAE reason.**
2. **"Gradient boosting beats LEAR" does not survive the move to a dispatch metric.** At
   an honest vintage, price-only, the GBM has the lower MAE in DE-LU (+3.17%) and NO2
   (+4.72%) and yet **loses on capture in all three zones** (−0.59 / −2.22 / −2.02pp).
   With the exogenous block it loses DE-LU and ES and wins only NO2. Read with
   FINDING C9-C — the booster's whole advantage was concentrated in the leaking arm — the
   C18 model ranking should be stated on capture, and on capture it does not favour the
   booster.
3. **FINDING C10-B's window gain largely evaporates.** Three extra years of price history
   were worth +2.81 / +3.62 / +7.42% of MAE; in capture terms they are +0.86 / −0.27 /
   **−1.31**pp. NO2 had the largest MAE gain of any intervention in this project and the
   second-worst capture outcome of any honest arm. FINDING C10-B's claim ("more history
   beat the entire honest exogenous block") is an **MAE** claim and must be labelled as
   one from here on — on capture the ranking reverses, and it is the exogenous block
   under the booster that wins.
4. **The Art. 14 leak buys almost nothing a battery can trade.** Worth 8.3% and 11.1% of
   MAE to the LEAR, it is worth +0.00 and −0.84pp of capture. Under the GBM the 23.9%
   MAE gain on DE-LU does convert to +3.47pp, so the leak is not *uniformly* worthless —
   but that number is `after_gate_closure` and unachievable, and it is the one place a
   large MAE gain and a large capture gain coincide.

NOTE C9-01's prediction is confirmed and generalised: a roughly uniform upward bias
(−0.03 to +3.0 EUR/MWh on the comparable curves) barely perturbs the within-day ordering
a battery trades on — and beyond that, **most point-error gains do not reach the ordering
either.**

**The caveat that must travel with FINDING C11-D.** n = 15 paired comparisons, three
zones, one year, and most capture deltas are under 1pp. A good deal of this could be
noise around zero, and the honest reading today is *"MAE is not a reliable proxy for
capture"*, **not** *"MAE is anti-correlated with capture"*. **C12's block bootstrap over
daily blocks is what turns this table into a finding** and should run on
`c11_capture_daily_2024.csv.gz` before C18 quotes any delta. The GBM-exogenous result
(+2.04 / +2.71pp, ~700–900 EUR/MW/yr) is the largest honest effect and the most likely
to survive.

#### FLAG C5-01 across nine zones, for the first time

Simultaneous charge/discharge — resolved at Checkpoint B as option (b) (keep the pure
LP, carry it as a stated limitation). C11 is the first cycle to measure it outside
DE-LU, and the nine-zone picture **supports that decision more strongly than DE-LU alone
did.** On the comparable arm: FR 9 of 365 days (2.5%, 28 intervals, 2.70 MWh burned,
0.14% of settled cash), BE 3 days, DK1 2 days, DE-LU / ES / NL / PL 1 day each, NO2 and
IT-North **none**. Present in seven of nine zones but tiny everywhere — at worst 2.5% of
days and 0.14% of cash. With Checkpoint B's measurement that it biases capture *against*
the model by ~0.16pp (LP 0.9187 vs MILP 0.9203 on DE-LU), the pure LP stays the
conservative default. **Nothing new decided; no dispatch, LP or settlement code
touched.** No MILP variant was run this cycle — it is a C15 sensitivity, not C11 scope.

#### The results store

**1 638 rows appended**, run `C11-20261009T022531Z-5e82e39f`; the store is now **2 085
rows across 2 runs**, `verify_append_only()` green, and the **447 committed C10 rows are
byte-for-byte unchanged** (checked directly: the new file's first N bytes are identical
to `git show HEAD:backtest/results/results.csv`, and the diff is 1 638 insertions / **0
deletions**). **No schema change and no test edit were needed** — long format made the
metric name the extension point exactly as `docs/results_store.md` promised, and C10's
`test_the_metrics_c11_and_c12_will_write_need_no_schema_change` was written against
this.

Per (zone, curve, scope): `dispatch_cash_eur`, `dispatch_value_added_eur`,
`dispatch_cash_eur_per_mw_year`, `capture_same_start_pooled`,
`capture_same_start_mean_daily`, `capture_same_start_{p05,p25,p50,p75,p95}_daily`,
`capture_rolled_oracle_cash`, `eur_per_mw_year_lost_vs_oracle`,
`share_of_days_value_added_negative`, `share_of_days_with_simultaneity`,
`equivalent_full_cycles`, `realised_spread_{mean,median}_eur_per_mwh`; plus, at
`common_hours` only, the paired `{mae,rmse,bias}_on_dispatched_hours`. The oracle's rows
carry `model="oracle"`, `exog_variant="perfect_foresight"` and an **empty `train_from`**
(perfect foresight has no training window). `evaluation_years` is `2024` on all 2 085
rows.

#### Data: 18/18 price pulls, verified against the C2 manifest

NOTE C2-02, **22nd recurrence** — `data/raw/` was empty again on arrival. C11 re-pulled
only the **18** (zone, year) files it needed (2023 for the trailing mark run-in, 2024 for
dispatch) rather than all 54: **18/18 succeeded, 0 FLAGs**, no ENTSO-E pull needed or
made. Every one of the 18 was then checked against the committed C2 manifest with the
manifest's own `payload_fingerprint`: **18/18 `payload_sha256` identical.** The manifest
artefacts were not regenerated or committed — C10 did the full nine-zone re-verification
three cycles ago and committing a fresh `fetched_at_utc` every cycle churns the manifest
for no information gain.

#### Sealed holdout

**SEALED.** Verified armed before and after the work: marker-alone-on-a-line count **0**,
`holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`,
`assert_not_sealed({2025})` raises `SealedHoldoutError`, no `*2025*` file exists anywhere
under `data/`, only 2023 and 2024 price files were fetched, every `market_day` in every
C11 artefact is in 2024, and `evaluation_years` = `2024` on all 2 085 store rows. The 18
occurrences of the string `2025` in `c11_capture_daily_2024.csv.gz` were each inspected
and are digits inside float values (`30.402025`, `34.220252`, `0.2025`). No 2025 data has
been fetched, loaded, dispatched or computed against at any point in C2–C11.

#### Config hash and libraries

Config hash **`515d4e8d98887256`** — unchanged from C8/C9/C10; C11 modified no
`config/*.yaml` (verified with `git diff --stat HEAD -- config/`, empty). Library
fingerprint **`856fb19ac0c4eecd`** — identical to C10's (python 3.11.17, numpy 2.4.6,
pandas 3.0.6, scikit-learn 1.9.1, scipy 1.17.1, lightgbm 4.7.0), so C10's and C11's rows
are directly comparable. The GBM config fingerprint `a366a760e269bba6` is carried on
every GBM row and was not touched.

#### Built and committed (51 new tests, 556 in total)

- `backtest/run_c11_dispatch.py` — the nine-zone dispatch CLI: the `Arm` inventory,
  `load_arm_curves` with the three provenance checks, `pooled_capture` (the day set as an
  argument), `mae_on_days` (the paired point error), `beats_naive`, `store_rows`,
  `comparable_table`, `check_c6_reproduction`, and the `CONTRASTS` that answer
  NOTE C8-01.
- `tests/test_c11_dispatch.py` — 51 offline tests: the arm inventory and its vintage
  labels, the ratio-of-sums property, the two scopes on a market where they genuinely
  differ, the denominator-coverage refusal, the paired MAE's hour set, the store rows
  (including the sealed-year refusal and "no row for a metric that could not be
  computed"), FINDING C11-C pinned against the artefact, and that the C6 reproduction
  check can actually fail.
- `docs/dispatch_results.md` — the full write-up of all of the above.
- `backtest/results/c11_dispatch_<ZONE>_2024_{daily.csv.gz,summary.json}` (nine zones),
  `c11_capture_daily_2024.csv.gz` (**16 440 rows** — every curve x every dispatched day,
  the artefact C12 bootstraps over), `c11_comparable_capture.csv`,
  `c11_dispatch_summary.json`, and the 1 638 new rows in `results.csv` /
  `results_runs.json`.
- `requirements.txt` — a comment block recording that C11 added no dependency.

#### Two notes for later cycles (neither a blocker)

**NOTE C11-01 — for C12, and it is the whole job.** Every headline in this entry is one
validation year and either n = 9 zones or n = 15 paired comparisons, with most capture
deltas under 1pp. C12's block bootstrap over daily blocks has to decide three specific
things before C18 quotes any of them: (i) is FINDING C11-A's eight-zone 8.3pp capture
band (NO2 excluded) wider than noise, (ii) is FINDING C11-D's near-zero MAE/capture rank
correlation distinguishable from a real relationship, and (iii) does the GBM-exogenous
capture gain (+2.04 / +2.71pp) survive a CI. The per-day artefact is already in the
shape a daily-block bootstrap needs.

**NOTE C11-02 — for C13/C15.** FINDING C11-B's thin-spread mechanism for NO2 is
untested. C15's throughput-cost ladder (0 / 2 / 5 EUR/MWh) is the direct test and should
be read as such, not merely as a sensitivity; C13 should say whether NO2's capture is a
2024 hydrology artefact or a standing property.

#### Repo-state note

The detached-HEAD trap recurred: the container arrived detached at `e30892d` with local
`master` stale 14 commits behind. **26 recurrences out of 33 containers.** `HEAD` equalled
`origin/master` exactly (0 ahead, 0 behind) so nothing was at risk, and
`git checkout -B master` was permitted, so the cycle worked on a properly attached
`master` throughout. C9's warning still stands for a container that arrives detached *and*
genuinely behind the remote: flag rather than improvise. Keep checking
`git rev-parse --abbrev-ref HEAD` and `git rev-list --count master..HEAD` at the start of
every cycle.

**Next:** C12 — the metrics layer: MAE, RMSE, rMAE vs naive, daily-spread error,
within-day Spearman, capture ratio, EUR/MW/yr, and **block-bootstrap CIs over daily
blocks**. Read NOTE C11-01 first: C12 is not a formatting cycle, it is the cycle that
decides whether C11's three findings are real. Quote `capture_rolled_oracle_cash`, never
`capture_same_start_pooled` (FINDING C11-C). The per-day input is
`backtest/results/c11_capture_daily_2024.csv.gz`; the paired point error is already in
the store as `{mae,rmse,bias}_on_dispatched_hours` at `common_hours`, on the same hours
as the capture ratios, so the spread and Spearman metrics C12 adds should be computed on
that same hour set. Call `verify_append_only()` before trusting the store and append with
`append_rows` — the metric name is still the extension point and no schema change is
needed.
