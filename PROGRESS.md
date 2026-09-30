# Progress log

## Current status

- **Next cycle to run:** **AWAITING HUMAN — CHECKPOINT A.** C2 is complete and
  stops here by design. Do **not** start C3 (walk-forward harness + naive model,
  DE-LU) until a human has reviewed the Checkpoint A artefacts listed in the C2
  log entry below and recorded approval here. A scheduled cycle that fires while
  this line still says AWAITING HUMAN should verify nothing has changed, append a
  one-line note that it checked and is still waiting, send no push notification,
  and stop.
- **Human checkpoints pending:** **Checkpoint A — open, awaiting review.**
  Artefacts ready: `data/manifest/prices_manifest.csv` (unchanged from C1),
  `data/manifest/contract_report.{csv,json}`, `data/manifest/dst_whitelist.csv`,
  and 11 figures in `docs/figures/`. Three decisions are requested — see
  "Checkpoint A: what needs a human" in the C2 entry.
- **Open FLAGs:** none. Two non-blocking NOTEs raised this cycle (C2-01
  `raw_sha256` is not reproducible by construction; C2-02 the raw cache does not
  survive a container, so every cycle re-pulls). Neither blocks any work.
- **Sealed holdout (2025):** SEALED — do not touch until the human records
  approval of Checkpoint C (C16) here, using the marker string defined in
  `config/data.yaml` -> `holdout_unseal_marker` (never reproduced in this file).
  Guard verified armed this cycle, before and after the work: marker count 0,
  `holdout_is_unsealed()` = `False`. No 2025 data was fetched, loaded or computed
  against at any point in C2.
- **ENTSOE_API_KEY:** set in this environment (verified C1b). C7 precondition
  satisfied; not needed before then, and not used this cycle.
- **Repo-state note:** the detached-HEAD trap **did** recur this cycle — the
  container arrived on a detached HEAD at `6227d69`. Reattached with
  `git checkout -B master 6227d69` and re-pointed at `origin/master` before any
  work. Keep checking `git rev-parse --abbrev-ref HEAD` at the start of every
  cycle; this is now 4 recurrences out of 9 containers.

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
