# Progress log

## Current status

- **Next cycle to run:** **AWAITING HUMAN — CHECKPOINT B.** C6 is complete and
  Checkpoint B is reached. Do **not** start C7 until a human has reviewed and
  replaced this line. A scheduled cycle that fires while this still reads
  "AWAITING HUMAN" should verify nothing has changed, append a one-line note that
  it checked and is still waiting, and stop — without a push notification (the
  Checkpoint B ping has already been sent; repeat pings for the same wait are
  noise). See the C6 entry at the end of the log for everything below.
- **What Checkpoint B wants:** (1) eyeball the three week figures
  `docs/figures/c6_dispatch_week_DE-LU_{2024-05-20,2024-11-04,2024-12-02}.png`
  against the Checkpoint A price plots — does the dispatch look like a battery
  buying low and selling high, and does SoC carry across midnight rather than
  reset? (2) sanity-check the headline: **87–92% of perfect-foresight value
  captured** by a price-history-only LEAR on DE-LU 2024, **6,047 EUR/MW/yr lost
  to forecast error**, oracle **74,399** / model **68,179** / naive **62,868**
  EUR/MW/yr. (3) decide **FLAG C5-01**. (4) confirm or overturn **NOTE C4-02**.
  (5) **NOTE C3-01** and **NOTE C4-01** are still open and unchanged.
- **To approve and continue:** replace this "Next cycle to run" line with
  **C7** and record the approval in the log, as Checkpoint A was closed.
- **Human checkpoints:** **Checkpoint B reached 2026-10-02 (C6) — awaiting
  review.** Checkpoint A closed 2026-10-01 (human session, local, not a
  scheduled cycle). Next after B is **Checkpoint C at C16** (unsealing 2025).
- **`ENTSOE_API_KEY` is now set in the cloud environment** (first observed by the
  7th Checkpoint B wait cycle, 2026-10-05; value never read or logged). PLAN.md's
  "ENTSO-E API key note" is now stale — **C7 can run its full intended scope** and
  does not need the Tier-B-only fallback. Re-confirm at the start of C7.
- **Open FLAGs:** **FLAG C5-01** — simultaneous charge/discharge in the dispatch
  LP, exactly as PLAN.md anticipated. **Still open, still non-blocking, committed
  default deliberately unchanged (pure LP).** C6 added the decisive evidence: the
  artefact *flatters the oracle* (+125.47 EUR) and *penalises the forecast
  curves* (model −0.49, naive −89.88), so the pure LP's capture ratio is biased
  **against** the model — 0.9187 under the LP vs **0.9203 under the MILP**, a
  shift of **+0.16pp**. A human picks (a) MILP as default, (b) keep the pure LP
  and carry it as a stated limitation, or (c) add the `c_t + d_t <= P`
  single-inverter constraint. None of the three changes any conclusion.
- **Open decision requests, all non-blocking:**
  - **NOTE C3-01** — the daily-aggregate feature names in `config/features.yaml`
    say `lag_24h` but the only leak-free window is the last fully-public UTC day
    (`D-2`); rename them or keep the names and rely on `docs/forecast_harness.md`?
    See the C3 entry. C5 and C6 did not touch `config/features.yaml`.
  - **NOTE C4-01** — should `destroys_skill()` in `backtest/diagnostics.py` be
    re-based on the new `TrainMedianBaseline`? See FINDING C4-A in the C4 entry.
    Proposed, deliberately not done: that file holds a PLAN.md leakage assertion.
    A human picks. Unchanged by C6.
  - **NOTE C2-02** — the raw cache does not survive a container, so every cycle
    re-pulls DE-LU (6 files, ~1 MB). 4th recurrence. See the C2 entry for the
    three options.
  - **NOTE C4-02 — now DECIDED by C6, confirmable or reversible by the human.**
    The one declined hour a year is **excluded, and the day is reported
    excluded**; every pooled number is computed over the common 365-day set.
    Priced rather than argued: dispatching it from the `impute` variant would
    have earned **−33.47 EUR** (the day is a loss), so excluding it does not
    flatter the model. See the C6 entry.
- **Sealed holdout (2025):** SEALED — do not touch until the human records
  approval of Checkpoint C (C16) here, using the marker string defined in
  `config/data.yaml` -> `holdout_unseal_marker` (never reproduced in this file).
  Guard verified armed in C6, before and after the work: marker-alone-on-a-line
  count 0, `holdout_is_unsealed()` = `False`, `sealed_years()` = `{2025}`, and no
  2025 file exists in the cache. No 2025 data has been fetched, loaded,
  dispatched or computed against at any point in C2, C3, C4, C5 or C6.
- **ENTSOE_API_KEY:** set in this environment (verified C1b). C7 precondition
  satisfied; not needed before then, and not read in C2-C6.
- **Config hash:** `84f7bf31591d1e7f`, unchanged by C6 (no `config/*.yaml` file
  was modified). It last moved in C5 when `config/battery.yaml` was added.
- **Repo-state note:** the detached-HEAD trap recurred again in C6 — the
  container arrived on a detached HEAD at `f653618`. Reattached with
  `git checkout -B master f653618` and re-pointed at `origin/master` before any
  work. **8 recurrences out of 14 containers.** Keep checking
  `git rev-parse --abbrev-ref HEAD` at the start of every cycle.

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
