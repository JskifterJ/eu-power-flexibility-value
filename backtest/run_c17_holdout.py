"""CLI: C17 — the holdout cycle's preflight.

    python -m backtest.run_c17_holdout --phase preflight

PLAN.md C16: *"Only after approval: run a single evaluation of the 2025
holdout; record in PROGRESS.md that it ran exactly once, with the timestamp."*
``docs/checkpoint_c.md`` §5 hands that run to C17 and asks it to do four things
before anything is measured: fetch 2025 fresh, confirm the evaluation will be
the one that was pre-registered, **report** rather than silently handle the
15-minute segment after 2025-09-30, and **report** the shorter 273-day year.

This module is that preflight, and in this cycle it is all of C17 that ran.
**It computes no forecast, no dispatch and no metric, on 2025 or any other
year** — it only establishes whether the pre-registered evaluation *can* run
as written, and writes down what it found. That matters because of the
pre-registration's own stop rule: the evaluation happens once, and nothing may
change after the first 2025 number is seen. A precondition discovered
afterwards is a precondition discovered too late.

What it checks, in order
------------------------
1. **The unseal.** ``holdout_is_unsealed()`` is the function, not the prose:
   the marker must be a line of its own in ``PROGRESS.md``. ``sealed_years()``
   still reads ``{2025}`` afterwards and is *supposed* to — the declaration is
   permanent and the marker is what overrides it, which is exactly the
   distinction check 5 turns out to depend on.
2. **The frozen specs.** LEAR, GBM, battery and walk-forward, each compared
   field by field against ``c16_preregistration.json``. A silent drift here
   would mean evaluating the holdout with a model nobody registered.
3. **The library fingerprint.** C10-C15 published every number under
   ``856fb19ac0c4eecd``. A 2025 number produced under a different numpy or
   scikit-learn is not comparable to the 2024 number it is read against, and
   the pre-registration's whole comparison table is that reading.
4. **The price data.** The download record, the resolution change, and the
   evaluation window: 273 market days per zone, 2025-01-01..2025-09-30, every
   one of them at 3600 seconds.
5. **The exogenous path.** Whether the Tier-A 2025 ENTSO-E pull is reachable.

Check 5 is the one that failed, and it failed on this repo's own code rather
than on the source: :func:`data.entsoe.parse_document` rejects any response
carrying a timestamp in a year that ``sealed_years()`` lists, without asking
:func:`data.holdout.holdout_is_unsealed` whether the human has since unsealed
it. Before Checkpoint C that predicate was right. After it, it refuses the
whole Tier-A 2025 pull. :func:`entsoe_parse_guard_probe` reproduces it without
a network request, by handing the parser a three-row synthetic A65 document
dated inside the window — so the finding in the artefact is a *demonstration*,
not a reading of the source.

Editing that check is editing a sealed-holdout assertion, which CLAUDE.md
makes a flag-and-stop event and PLAN.md makes one of its five checkpoints. So
this cycle does not edit it. It writes the probe, the proposed one-call fix and
the reasoning into ``c17_preflight.json`` and stops.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

import pandas as pd

from backtest.results_store import library_fingerprint, library_versions
from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.walk_forward import WalkForwardSpec, evaluation_days
from data.config import (
    config_hash,
    load_battery_config,
    load_data_config,
    load_zones,
    sealed_years,
)
from data.contracts import detect_resolution_changes, resolution_segments
from data.entsoe import (
    UnexpectedResponse,
    api_key_is_set,
    exogenous_years,
    parse_document,
)
from data.holdout import holdout_is_unsealed, unseal_marker
from data.manifest import MANIFEST_CSV
from data.prices import load_zone_series
from dispatch.battery import BatterySpec
from forecast.features import build_features
from forecast.gbm import GbmSpec
from forecast.lear import LearSpec

#: The pre-registration this cycle is held to, written and committed at C16
#: while the holdout was still sealed.
PREREGISTRATION = "c16_preregistration.json"

#: Where this cycle's findings go.
PREFLIGHT = "c17_preflight.json"

#: The evaluation window, from the pre-registration. Re-derived from the file
#: at run time; these are the values a reader should expect to see.
HOLDOUT_YEAR = 2025
LAST_MARKET_DAY = dt.date(2025, 9, 30)
EXPECTED_MARKET_DAYS = 273

#: The instant SDAC moved the day-ahead market time unit from 60 to 15 minutes:
#: 2025-10-01 00:00 CEST. Every evaluated row must precede it.
CUTOVER_UTC = pd.Timestamp("2025-09-30T22:00:00Z")

#: Seconds per market time unit in the evaluated window.
HOURLY_SECONDS = 3600


class PreflightError(RuntimeError):
    """The preflight cannot answer a question it was asked to answer."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["preflight"], default="preflight")
    parser.add_argument("--zones", nargs="*", default=None,
                        help="zone keys (default: all nine)")
    return parser.parse_args(argv)


def load_preregistration() -> dict[str, Any]:
    path = RESULTS_DIR / PREREGISTRATION
    if not path.exists():
        raise PreflightError(
            f"{path.name} is missing — C17 may not evaluate the holdout without the "
            f"pre-registration it is held to"
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 1 — the unseal
# ---------------------------------------------------------------------------


def unseal_state() -> dict[str, Any]:
    """Run the guard rather than read it, and record both of its two answers.

    ``sealed_years()`` staying ``{2025}`` after approval is correct: the
    declaration in ``config/data.yaml`` is permanent and the marker overrides
    it. Recording both answers side by side is what makes check 5's finding
    legible — that is precisely the distinction the ENTSO-E parser misses.
    """
    return {
        "holdout_is_unsealed": bool(holdout_is_unsealed()),
        "unseal_marker": unseal_marker(),
        "sealed_years_declaration": sorted(int(y) for y in sealed_years()),
        "note": (
            "sealed_years() is the permanent declaration from config/data.yaml; "
            "holdout_is_unsealed() is the human's approval. A guard that reads the "
            "first without the second refuses work the human has approved."
        ),
    }


# ---------------------------------------------------------------------------
# 2-3 — the frozen specs and the library fingerprint
# ---------------------------------------------------------------------------


def spec_agreement(prereg: dict[str, Any]) -> dict[str, Any]:
    """Every frozen choice, compared field by field with the pre-registration."""
    lear = LearSpec().as_dict()
    gbm = GbmSpec()
    battery_cfg = load_battery_config()
    battery = BatterySpec.from_config(battery_cfg).as_dict()
    terminal = battery_cfg.get("terminal") or {}
    wf = prereg["walk_forward"]
    live_wf = WalkForwardSpec(
        refit_every_days=int(wf["refit_every_days"]),
        min_train_days=int(wf["min_train_days"]),
        train_window_days=wf["train_window_days"],
    ).as_dict()

    want_lear = prereg["models_frozen"]["lear"]
    want_battery = prereg["dispatch"]
    checks = {
        "lear_selector": (lear["selector"], want_lear["selector"]),
        "lear_hour_key": (lear["hour_key"], want_lear["hour_key"]),
        "lear_vst": (lear["vst"], want_lear["vst"]),
        "gbm_fingerprint": (
            gbm.fingerprint(), prereg["models_frozen"]["gbm"]["fingerprint"],
        ),
        "battery_power_mw": (battery["power_mw"], want_battery["power_mw"]),
        "battery_duration_hours": (
            battery["duration_hours"], want_battery["duration_hours"],
        ),
        "battery_round_trip_efficiency": (
            battery["round_trip_efficiency"], want_battery["round_trip_efficiency"],
        ),
        "battery_throughput_cost": (
            battery["throughput_cost_eur_per_mwh"],
            want_battery["throughput_cost_eur_per_mwh"],
        ),
        "battery_initial_soc_fraction": (
            battery["initial_soc_fraction"], want_battery["initial_soc_fraction"],
        ),
        "battery_terminal_mode": (
            battery["terminal_mode"], want_battery["terminal_mode"],
        ),
        "battery_trailing_days": (
            int(terminal.get("trailing_days", -1)), want_battery["trailing_days"],
        ),
        "battery_trailing_quantile": (
            float(terminal.get("trailing_quantile", -1.0)),
            want_battery["trailing_quantile"],
        ),
        "walk_forward_refit_every_days": (
            live_wf["refit_every_days"], wf["refit_every_days"],
        ),
        "walk_forward_min_train_days": (
            live_wf["min_train_days"], wf["min_train_days"],
        ),
        "walk_forward_train_window_days": (
            live_wf["train_window_days"], wf["train_window_days"],
        ),
    }
    disagreements = {
        name: {"live": live, "preregistered": want}
        for name, (live, want) in checks.items()
        if live != want
    }
    return {
        "checked": {k: {"live": v[0], "preregistered": v[1]} for k, v in checks.items()},
        "n_checked": len(checks),
        "disagreements": disagreements,
        "all_agree": not disagreements,
        "lear_spec_live": lear,
        "battery_spec_live": battery,
        "terminal_live": dict(terminal),
    }


def provenance(prereg: dict[str, Any]) -> dict[str, Any]:
    """Library fingerprint and config hash against the pre-registered ones.

    The fingerprint must match: every 2024 number the holdout is read against
    was produced under ``856fb19ac0c4eecd``, and a comparison across two
    library sets is not a comparison. The config hash is *expected* to differ —
    ``docs/checkpoint_c.md`` §4(b) predicted it by name, because the approval
    adds 2025 to ``fetch_years``.
    """
    live_fp = library_fingerprint()
    want_fp = prereg["library_fingerprint"]
    live_cfg, want_cfg = config_hash(), prereg["config_hash"]
    return {
        "library_versions": library_versions(),
        "library_fingerprint_live": live_fp,
        "library_fingerprint_preregistered": want_fp,
        "library_fingerprint_matches": live_fp == want_fp,
        "config_hash_live": live_cfg,
        "config_hash_preregistered": want_cfg,
        "config_hash_matches": live_cfg == want_cfg,
        "config_hash_change_was_predicted": live_cfg != want_cfg,
        "config_hash_note": (
            "docs/checkpoint_c.md §4(b) predicted this change by name: the approval "
            "adds 2025 to fetch_years, which is a config edit and therefore a new "
            "config_hash. It is the one pre-registered field allowed to move."
        ),
        "git_sha": git_sha(),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 4 — the price data: the download record, the cutover, the window
# ---------------------------------------------------------------------------


def download_record() -> dict[str, Any]:
    """The committed manifest's 2025 rows — the record that a fetch happened.

    The manifest's per-year columns are computed at the year's *modal*
    resolution, and 2025's modal resolution is 900s because the 15-minute
    segment (8 835 intervals) outnumbers the hourly one (6 550). So the row's
    ``coverage_ratio`` and ``n_gap_intervals`` read as though three quarters of
    the hourly months were missing. They are not: they are hourly rows counted
    against a 15-minute expectation. The number is reported with that reading
    attached rather than quietly recomputed, because the manifest's job is to
    record what was downloaded, not to present it favourably.
    """
    if not MANIFEST_CSV.exists():
        raise PreflightError(f"{MANIFEST_CSV} is missing — run data.build_manifest")
    frame = pd.read_csv(MANIFEST_CSV)
    rows = frame[frame["year"] == HOLDOUT_YEAR]
    return {
        "manifest_path": MANIFEST_CSV.name,
        "n_2025_rows": int(len(rows)),
        "zones_with_a_2025_row": sorted(rows["zone"].astype(str)),
        "years_present": sorted(int(y) for y in frame["year"].unique()),
        "per_zone": {
            str(r["zone"]): {
                "n_points": int(r["n_points"]),
                "modal_resolution_seconds": int(r["resolution_seconds"]),
                "n_distinct_deltas": int(r["n_distinct_deltas"]),
                "first_ts_utc": str(r["first_ts_utc"]),
                "last_ts_utc": str(r["last_ts_utc"]),
                "coverage_ratio_at_modal_resolution": float(r["coverage_ratio"]),
                "fetched_at_utc": str(r["fetched_at_utc"]),
            }
            for _, r in rows.iterrows()
        },
        "price_statistics_deliberately_omitted": (
            "the manifest carries them; this artefact does not repeat them. The "
            "holdout's price level is not something a blocked cycle needs to state."
        ),
        "reading": (
            "coverage_ratio and n_gap_intervals for 2025 are computed against the "
            "year's modal resolution, which is 900s. The hourly Jan-Sep segment is "
            "therefore counted as missing 15-minute intervals. Nothing is missing: "
            "the mixed-resolution year is what SDAC's 2025-10-01 cutover produces."
        ),
    }


def window_report(zone_keys: list[str]) -> dict[str, Any]:
    """The evaluation window, per zone, established without computing anything.

    Three facts the pre-registration asserts and nobody had yet checked against
    real 2025 data: the cutover is where PLAN.md says it is, the window holds
    exactly 273 market days, and every row inside it is hourly.
    """
    per_zone: dict[str, Any] = {}
    for zone_key in zone_keys:
        prices = load_zone_series(zone_key)
        index = pd.DatetimeIndex(prices.index)
        changes = [
            {
                "at_utc": c.at_utc.isoformat(),
                "from_seconds": int(c.from_seconds),
                "to_seconds": int(c.to_seconds),
            }
            for c in detect_resolution_changes(index)
        ]
        hourly = prices.loc[index < CUTOVER_UTC]
        segments = resolution_segments(pd.DatetimeIndex(hourly.index))
        all_hourly = all(int(s.seconds) == HOURLY_SECONDS for s in segments)

        hourly.attrs = dict(prices.attrs)
        matrix = build_features(hourly, zone_key)
        days = [d for d in evaluation_days(matrix, [HOLDOUT_YEAR]) if d <= LAST_MARKET_DAY]
        per_zone[zone_key] = {
            "n_hourly_rows_before_cutover": int(len(hourly)),
            "n_resolution_segments_before_cutover": len(segments),
            "every_pre_cutover_row_is_hourly": bool(all_hourly),
            "resolution_changes": changes,
            "n_evaluation_days": len(days),
            "first_market_day": days[0].isoformat() if days else None,
            "last_market_day": days[-1].isoformat() if days else None,
            "matches_preregistered_window": (
                len(days) == EXPECTED_MARKET_DAYS
                and bool(days)
                and days[-1] == LAST_MARKET_DAY
            ),
        }
    return {
        "cutover_utc": CUTOVER_UTC.isoformat(),
        "last_market_day": LAST_MARKET_DAY.isoformat(),
        "expected_market_days": EXPECTED_MARKET_DAYS,
        "per_zone": per_zone,
        "all_zones_match_the_preregistered_window": all(
            b["matches_preregistered_window"] for b in per_zone.values()
        ),
        "note": (
            "No price, forecast, dispatch or metric value is computed here. These "
            "are counts of rows and days, which is what the pre-registration's "
            "window claim is made of."
        ),
    }


# ---------------------------------------------------------------------------
# 5 — the exogenous path, and the guard that blocks it
# ---------------------------------------------------------------------------

#: A minimal, well-formed A65 (load forecast) document dated inside the
#: evaluation window. Three points, one hour apart, so the probe exercises the
#: parser's real path — curve type, unit, business type, interval tiling — and
#: reaches the sealed-year check with a frame it would otherwise accept.
SYNTHETIC_A65 = """<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <type>A65</type>
  <process.processType>A01</process.processType>
  <TimeSeries>
    <businessType>A04</businessType>
    <quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name>
    <curveType>A01</curveType>
    <Period>
      <timeInterval>
        <start>2025-03-01T00:00Z</start>
        <end>2025-03-01T03:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>40000</quantity></Point>
      <Point><position>2</position><quantity>39000</quantity></Point>
      <Point><position>3</position><quantity>38000</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>
"""


def entsoe_parse_guard_probe() -> dict[str, Any]:
    """Reproduce the blocker locally, with no network request.

    The live fetch already failed six times for six (zone, document) pairs, but
    a log line is evidence about a run and this needs to be evidence about the
    code. So the parser is handed a synthetic A65 document whose only unusual
    property is its date, and the result is recorded. A pass here would mean the
    six live failures came from somewhere else and the diagnosis is wrong.
    """
    probe: dict[str, Any] = {
        "method": (
            "data.entsoe.parse_document is handed a three-point synthetic A65 "
            "document dated 2025-03-01, inside the evaluation window. No network "
            "request is made and nothing is cached."
        ),
        "document_dates_utc": ["2025-03-01T00:00Z", "2025-03-01T02:00Z"],
        "holdout_is_unsealed_at_probe_time": bool(holdout_is_unsealed()),
    }
    try:
        frame = parse_document(
            SYNTHETIC_A65.encode("utf-8"),
            "load_forecast_da",
            "c17 preflight synthetic A65 probe",
        )
    except UnexpectedResponse as exc:
        probe.update(
            parser_accepts_an_unsealed_2025_document=False,
            raised=type(exc).__name__,
            message=str(exc),
        )
    else:
        probe.update(
            parser_accepts_an_unsealed_2025_document=True,
            raised=None,
            message=None,
            n_rows=int(len(frame)),
        )
    return probe


def exogenous_path(prereg: dict[str, Any]) -> dict[str, Any]:
    """Whether the Tier-A 2025 exogenous pull is reachable, and if not, why."""
    cfg = load_data_config()
    years = [int(y) for y in exogenous_years(cfg)]
    probe = entsoe_parse_guard_probe()
    blocked = not probe["parser_accepts_an_unsealed_2025_document"]
    block: dict[str, Any] = {
        "exogenous_years_allowed_by_config": years,
        "year_2025_is_in_fetch_years": HOLDOUT_YEAR in years,
        "entsoe_api_key_present": bool(api_key_is_set(cfg)),
        "parse_guard_probe": probe,
        "tier_a_2025_pull_is_blocked": blocked,
    }
    if blocked:
        block["diagnosis"] = {
            "where": "data/entsoe.py, in parse_document (the sealed-timestamp check)",
            "what": (
                "the check compares the parsed frame's years against sealed_years() "
                "and raises UnexpectedResponse on a hit, without asking "
                "holdout_is_unsealed() whether the human has approved the unseal. "
                "sealed_years() is the permanent declaration in config/data.yaml and "
                "still reads {2025} by design, so after Checkpoint C the check "
                "refuses every 2025 response."
            ),
            "why_it_was_right_before": (
                "its stated purpose is to catch an inclusive periodEnd — a 2024 "
                "request coming back with 2025 rows. While 2025 was sealed, "
                "'contains a sealed year' and 'leaked past the requested window' "
                "were the same condition."
            ),
            "the_two_sibling_checks_that_are_correct": [
                "data/prices.py:120 — belt-and-braces, routes through assert_not_sealed",
                "data/exogenous.py:275 — belt-and-braces, routes through assert_not_sealed",
            ],
            "proposed_fix": (
                "route the same hit through data.holdout.assert_not_sealed(hit, ...) "
                "instead of raising directly, matching the two sibling checks. "
                "assert_not_sealed applies the identical sealed-year test and then "
                "honours holdout_is_unsealed(), so the tripwire keeps working for "
                "every year that is still sealed and yields only to the human's "
                "approval."
            ),
            "what_the_fix_does_not_lose": (
                "the check never compared the response against the *requested* year, "
                "so it never guarded the exclusive-periodEnd property for an unsealed "
                "year. Nothing that was being checked stops being checked."
            ),
            "why_this_cycle_did_not_apply_it": (
                "it is a sealed-holdout assertion. CLAUDE.md makes editing a "
                "data-contract or leakage-assertion file a flag-and-stop event, and "
                "PLAN.md lists 'before modifying a frozen test/contract' as one of "
                "its five human checkpoints. An unattended cycle editing a seal "
                "tripwire, in the cycle that first touches the holdout, is the "
                "case those rules exist for."
            ),
            "scope_of_the_consequence": {
                "blocked": sorted(
                    f"{model}_{variant}"
                    for model in prereg["arms"]["tier_a_exogenous"]["models"]
                    for variant in prereg["arms"]["tier_a_exogenous"]["variants"]
                    if variant != "price_only"
                ),
                "not_blocked": [
                    "the nine-zone headline comparable arm (LEAR price_only)",
                    "the naive_last_week floor",
                    "the perfect-foresight oracle ceiling",
                    "every Tier-B arm",
                    "the Tier-A price_only arms",
                ],
                "note": (
                    "the headline needs Energy-Charts prices only and is unaffected. "
                    "It was nevertheless not run: see the PROGRESS.md entry for why a "
                    "once-only holdout is evaluated whole or not at all."
                ),
            },
        }
    return block


# ---------------------------------------------------------------------------
# The phase
# ---------------------------------------------------------------------------


def preflight(args: argparse.Namespace) -> int:
    prereg = load_preregistration()
    zone_keys = args.zones or list(load_zones())
    unknown = [z for z in zone_keys if z not in load_zones()]
    if unknown:
        raise PreflightError(f"unknown zone key(s): {unknown}")

    print("=== C17 preflight — no forecast, dispatch or metric is computed ===\n",
          flush=True)

    seal = unseal_state()
    print(f"  unseal           holdout_is_unsealed={seal['holdout_is_unsealed']}  "
          f"sealed_years declaration still {seal['sealed_years_declaration']}",
          flush=True)

    specs = spec_agreement(prereg)
    print(f"  frozen specs     {specs['n_checked']} checked, "
          f"{len(specs['disagreements'])} disagreement(s)", flush=True)
    for name, block in specs["disagreements"].items():
        print(f"    DRIFT {name}: live {block['live']!r} != "
              f"preregistered {block['preregistered']!r}", flush=True)

    prov = provenance(prereg)
    print(f"  provenance       library_fingerprint "
          f"{'MATCHES' if prov['library_fingerprint_matches'] else 'DIFFERS'} "
          f"({prov['library_fingerprint_live']}); config_hash "
          f"{prov['config_hash_live']} vs {prov['config_hash_preregistered']} "
          f"(a change here was predicted)", flush=True)

    record = download_record()
    print(f"  download record  {record['n_2025_rows']} zone-year row(s) for 2025; "
          f"manifest years {record['years_present']}", flush=True)

    window = window_report(zone_keys)
    print(f"  window           "
          f"{'all nine zones' if window['all_zones_match_the_preregistered_window'] else 'MISMATCH'}"
          f" at {EXPECTED_MARKET_DAYS} market days, "
          f"2025-01-01..{LAST_MARKET_DAY}, every row hourly", flush=True)
    for zone_key, block in window["per_zone"].items():
        print(f"    {zone_key:9s} {block['n_evaluation_days']:>4} days  "
              f"{block['n_hourly_rows_before_cutover']:>6} hourly rows  "
              f"cutover {block['resolution_changes']}", flush=True)

    exog = exogenous_path(prereg)
    state = "BLOCKED" if exog["tier_a_2025_pull_is_blocked"] else "reachable"
    print(f"\n  exogenous path   {state}", flush=True)
    if exog["tier_a_2025_pull_is_blocked"]:
        print(f"    FLAG {exog['diagnosis']['where']}", flush=True)
        print(f"    {exog['parse_guard_probe']['message']}", flush=True)

    # Every condition that must hold before the once-only evaluation may run.
    # The exogenous blocker is the one that failed in C17, but a drifted spec or
    # a moved library would be just as disqualifying and far easier to miss, so
    # all four gate the verdict and the exit code rather than only being printed.
    blockers = {
        "holdout_not_unsealed": not seal["holdout_is_unsealed"],
        "frozen_spec_drift": not specs["all_agree"],
        "library_fingerprint_moved": not prov["library_fingerprint_matches"],
        "tier_a_2025_pull_blocked": exog["tier_a_2025_pull_is_blocked"],
        "evaluation_window_mismatch": not window[
            "all_zones_match_the_preregistered_window"
        ],
    }
    standing = sorted(name for name, hit in blockers.items() if hit)
    for name in standing:
        if name != "tier_a_2025_pull_blocked":
            print(f"    BLOCKER {name}", flush=True)

    payload = {
        "cycle": "C17",
        "phase": "preflight",
        "status": (
            "BLOCKED — the pre-registered evaluation did not run; no 2025 forecast, "
            "dispatch or metric value was computed"
            if standing
            else "clear to evaluate"
        ),
        "blockers": blockers,
        "blockers_standing": standing,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "preregistration": {
            "file": PREREGISTRATION,
            "written_at_utc": prereg["written_at_utc"],
            "git_sha": prereg["git_sha"],
        },
        "unseal": seal,
        "frozen_specs": specs,
        "provenance": prov,
        "price_download_record": record,
        "evaluation_window": window,
        "exogenous_path": exog,
        "what_this_cycle_measured_on_2025": (
            "row counts, market-day counts, resolution segments and the committed "
            "download record. No price statistic, forecast, dispatch schedule, "
            "capture ratio or error metric was computed on 2025 data."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / PREFLIGHT
    with out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.write("\n")
    print(f"\n  verdict          {payload['status']}", flush=True)
    print(f"  -> {out}", flush=True)
    return 1 if standing else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return preflight(args)


if __name__ == "__main__":
    raise SystemExit(main())
