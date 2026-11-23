"""CLI: C17 — the holdout cycle: its preflight, and the one evaluation.

    python -m backtest.run_c17_holdout --phase preflight
    python -m backtest.run_c17_holdout --phase evaluate --year 2024   # rehearsal
    python -m backtest.run_c17_holdout --phase evaluate               # the holdout

PLAN.md C16: *"Only after approval: run a single evaluation of the 2025
holdout; record in PROGRESS.md that it ran exactly once, with the timestamp."*
``docs/checkpoint_c.md`` §5 hands that run to C17 and asks it to do four things
before anything is measured: fetch 2025 fresh, confirm the evaluation will be
the one that was pre-registered, **report** rather than silently handle the
15-minute segment after 2025-09-30, and **report** the shorter 273-day year.

The module has two halves, and they are separated on purpose.

The **preflight** (``--phase preflight``) computes no forecast, no dispatch and
no metric, on 2025 or any other year. It only establishes whether the
pre-registered evaluation *can* run as written, and writes down what it found.
That matters because of the pre-registration's own stop rule: the evaluation
happens once, and nothing may change after the first 2025 number is seen. A
precondition discovered afterwards is a precondition discovered too late. The
preflight was all of C17 that ran in the cycle that found FLAG C17-01.

The **evaluation** (``--phase evaluate``, or its four phases run one at a time)
is the run itself, and it is gated on the preflight's own conjunction — not on
a second copy of it. It runs once (a committed ledger, no override flag), whole
(all nine zones, in one process), and only in the registered environment. See
the section header further down for the three properties it enforces and why
each one is a gate rather than a note. ``--year 2024`` is the rehearsal: the
identical path on the visible validation year, writing ``c17_rehearsal_*``
artefacts and appending nothing to the store.

What the preflight checks, in order
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

Check 5 was the one that failed (FLAG C17-01), and it failed on this repo's
own code rather than on the source: :func:`data.entsoe.parse_document` rejected
any response carrying a timestamp in a year that ``sealed_years()`` lists,
without asking :func:`data.holdout.holdout_is_unsealed` whether the human had
since unsealed it. Before Checkpoint C that predicate was right. After it, it
refused the whole Tier-A 2025 pull. :func:`entsoe_parse_guard_probe` reproduces
the failure mode without a network request, by handing the parser a three-row
synthetic A65 document dated inside the window — so the finding in the artefact
is a *demonstration*, not a reading of the source. The probe is kept, and now
answers the other way: the one-call fix was applied under the human's §5(a)
approval on 2026-11-20, and the six refused documents were fetched on
2026-11-22.

Check 3 is the one standing in its place, and it is an environment fact rather
than a code fact: the pre-registered fingerprint pins CPython **3.11.17**, and
no cloud container here can install that patch release — see
``docs/c17_environment.md``. The gate is deliberately not negotiable from
inside this module.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest import run_c13_regime as c13
from backtest.metrics import daily_shape_table, rmae, score
from backtest.results_store import (
    ResultRow,
    append_rows,
    library_fingerprint,
    library_versions,
    verify_append_only,
)
from backtest.run_c3_naive import RESULTS_DIR, git_sha
from backtest.run_c5_oracle_lp import (
    check_day_lengths,
    check_value_added_non_negative,
    load_realised,
    simultaneity_flag,
)
from backtest.run_c11_dispatch import (
    FULL_HISTORY_FROM,
    ORACLE_MODEL,
    ORACLE_VARIANT,
    beats_naive,
    mae_on_days,
    pooled_capture,
)
from backtest.run_c13_regime import (
    DAILY_COLUMNS as C13_DAILY_COLUMNS,
    STORE_METRICS as C13_STORE_METRICS,
)
from backtest.walk_forward import WalkForwardSpec, evaluation_days, run_walk_forward
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
from data.holdout import assert_not_sealed, holdout_is_unsealed, unseal_marker
from data.manifest import MANIFEST_CSV
from data.prices import load_zone_series
from dispatch.battery import BatterySpec
from dispatch.curves import (
    Curve,
    assert_curve_aligns,
    assert_settlement_is_not_a_readback,
    capture_frame,
    check_decision_value_added_non_negative,
    check_per_day_dominance,
    common_days,
    report_realised_losses,
    same_start_oracle,
)
from dispatch.rolling import RollingResult, run_rolling_dispatch
from forecast.features import build_features
from forecast.gbm import GbmSpec
from forecast.lear import LearSpec, lear_factory
from forecast.models import NaiveLastWeek
from forecast.timing import market_days, zone_timezone

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
    parser.add_argument(
        "--phase",
        choices=["preflight", "compute", "dispatch", "analyse", "ingest", "evaluate"],
        default="preflight",
        help="'evaluate' runs compute, dispatch, analyse and ingest in one process "
             "— the holdout is evaluated whole or not at all",
    )
    parser.add_argument("--zones", nargs="*", default=None,
                        help="zone keys (default: all nine)")
    parser.add_argument("--year", type=int, default=HOLDOUT_YEAR,
                        help=f"evaluation year (default {HOLDOUT_YEAR}, the holdout; "
                             f"{REHEARSAL_YEAR} is the visible rehearsal)")
    parser.add_argument("--out", default=None,
                        help="preflight only: artefact filename inside the results "
                             "directory (default c17_preflight.json)")
    parser.add_argument("--refit-every", type=int, default=1,
                        help="walk-forward refit cadence in days (pre-registered: 1)")
    parser.add_argument("--min-train-days", type=int, default=365,
                        help="walk-forward minimum training days (pre-registered: 365)")
    parser.add_argument("--train-window-days", type=int, default=None,
                        help="walk-forward rolling window (pre-registered: expanding)")
    parser.add_argument("--no-append", action="store_true",
                        help="compute and write artefacts, append nothing to the store")
    parser.add_argument("--results-path", default=None,
                        help="override the store path (tests)")
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


ENV_APPROVAL = "c17_environment_approval.json"


def approved_environment_deviation(live_fp: str) -> dict[str, Any]:
    """NOTE C17-01 option (a): a human-approved, exactly-named fingerprint.

    Not a relaxation: the live fingerprint must equal the one fingerprint J.
    approved (CPython 3.11.18 + the five pinned libraries). Anything else --
    another patch, another library version -- still blocks.
    """
    path = RESULTS_DIR / ENV_APPROVAL
    if not path.exists():
        return {"approved": False, "reason": f"{ENV_APPROVAL} absent"}
    rec = json.loads(path.read_text(encoding="utf-8"))
    ok = live_fp == rec["approved_fingerprint"]
    return {"approved": ok, "record": rec,
            "reason": None if ok else "live fingerprint is not the approved one"}


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
        "library_fingerprint_approved_deviation": approved_environment_deviation(live_fp),
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


def collect_preflight(
    prereg: dict[str, Any], zone_keys: list[str], verbose: bool = True
) -> dict[str, Any]:
    """Every precondition, run rather than read, as one payload.

    Extracted from :func:`preflight` unchanged so the evaluation phase gates on
    *exactly* the checks the preflight reports, rather than on a second,
    drifting copy of them. The payload is the artefact; the printing is a view
    of it.
    """
    if verbose:
        print("=== C17 preflight — no forecast, dispatch or metric is computed ===\n",
              flush=True)

    seal = unseal_state()
    if verbose:
        print(f"  unseal           holdout_is_unsealed={seal['holdout_is_unsealed']}  "
              f"sealed_years declaration still {seal['sealed_years_declaration']}",
              flush=True)

    specs = spec_agreement(prereg)
    if verbose:
        print(f"  frozen specs     {specs['n_checked']} checked, "
              f"{len(specs['disagreements'])} disagreement(s)", flush=True)
        for name, block in specs["disagreements"].items():
            print(f"    DRIFT {name}: live {block['live']!r} != "
                  f"preregistered {block['preregistered']!r}", flush=True)

    prov = provenance(prereg)
    if verbose:
        print(f"  provenance       library_fingerprint "
              f"{'MATCHES' if prov['library_fingerprint_matches'] else 'DIFFERS'} "
              f"({prov['library_fingerprint_live']}); config_hash "
              f"{prov['config_hash_live']} vs {prov['config_hash_preregistered']} "
              f"(a change here was predicted)", flush=True)

    record = download_record()
    if verbose:
        print(f"  download record  {record['n_2025_rows']} zone-year row(s) for 2025; "
              f"manifest years {record['years_present']}", flush=True)

    window = window_report(zone_keys)
    if verbose:
        print(f"  window           "
              f"{'all nine zones' if window['all_zones_match_the_preregistered_window'] else 'MISMATCH'}"
              f" at {EXPECTED_MARKET_DAYS} market days, "
              f"2025-01-01..{LAST_MARKET_DAY}, every row hourly", flush=True)
        for zone_key, block in window["per_zone"].items():
            print(f"    {zone_key:9s} {block['n_evaluation_days']:>4} days  "
                  f"{block['n_hourly_rows_before_cutover']:>6} hourly rows  "
                  f"cutover {block['resolution_changes']}", flush=True)

    exog = exogenous_path(prereg)
    if verbose:
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
    # NOTE C17-01 (a): only the one human-approved fingerprint clears this blocker.
    if prov["library_fingerprint_approved_deviation"]["approved"]:
        blockers["library_fingerprint_moved"] = False
    standing = sorted(name for name, hit in blockers.items() if hit)
    if verbose:
        for name in standing:
            if name != "tier_a_2025_pull_blocked":
                print(f"    BLOCKER {name}", flush=True)

    return {
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


def preflight(args: argparse.Namespace) -> int:
    prereg = load_preregistration()
    zone_keys = args.zones or list(load_zones())
    unknown = [z for z in zone_keys if z not in load_zones()]
    if unknown:
        raise PreflightError(f"unknown zone key(s): {unknown}")

    payload = collect_preflight(prereg, zone_keys)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / (args.out or PREFLIGHT)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.write("\n")
    print(f"\n  verdict          {payload['status']}", flush=True)
    print(f"  -> {out}", flush=True)
    return 1 if payload["blockers_standing"] else 0

# ---------------------------------------------------------------------------
# The evaluation — the run `c16_preregistration.json` specifies
# ---------------------------------------------------------------------------
#
# Everything below is the *second* half of C17: the single, pre-registered
# evaluation of the 2025 holdout. It is deliberately thin. Every number it
# produces comes out of code that produced a published 2020-2024 number — C4's
# LEAR through C3's walk-forward harness, C5/C6's rolling LP, C11's
# ``pooled_capture``, C12's metric layer and bootstrap, C13's per-year table
# builders — because the holdout's whole purpose is to be *comparable* to those
# numbers, and a re-implementation that agreed to four decimals would still not
# be the same experiment.
#
# Three properties are enforced here rather than trusted:
#
# 1. **It runs once.** ``c17_holdout_run_ledger.json`` is committed, so the
#    record survives the container. A completed holdout entry makes a second
#    ``--phase evaluate --year 2025`` refuse outright. There is no override
#    flag: a second evaluation is a human's decision and must be labelled as
#    one (``c16_preregistration.json`` stop rules).
# 2. **It runs whole, or not at all.** The pre-registered window is 273 market
#    days in nine zones; a cycle that evaluated three zones and stopped would
#    have spent the holdout on a third of the question. ``evaluate`` runs
#    compute -> dispatch -> analyse -> ingest in one process and only writes a
#    ``completed`` ledger entry when all four finished.
# 3. **It runs in the registered environment.** The gate is
#    :func:`collect_preflight`, unchanged — the same conjunction the preflight
#    reports, including ``library_fingerprint_moved``. A 2025 capture ratio
#    computed under different libraries is not comparable to the 2024 one it
#    would be read against, and that is the comparison the whole project is for.
#
# The rehearsal year is how this code is tested without spending the holdout:
# ``--phase evaluate --year 2024`` runs the identical path on the visible
# validation year, writes ``c17_rehearsal_*`` artefacts that can never be
# mistaken for holdout ones, and appends nothing to the store.

#: Curve names. Identical spellings to C11/C13 — the store key and every
#: per-day artefact column join on them.
ORACLE_CURVE = "oracle"
COMPARABLE_CURVE = "lear_full_history"
NAIVE_CURVE = "naive"

#: Prediction-artefact columns, in C13's spelling.
LEAR_COLUMN = "y_pred_lear_price_only"
NAIVE_COLUMN = "y_pred_naive_last_week"

#: ``curve -> (model, exog_variant, train_from)``, C10's taxonomy.
STORE_KEY: dict[str, tuple[str, str, str]] = {
    ORACLE_CURVE: (ORACLE_MODEL, ORACLE_VARIANT, ""),
    COMPARABLE_CURVE: ("lear", "price_only", FULL_HISTORY_FROM),
    NAIVE_CURVE: ("naive_last_week", "", FULL_HISTORY_FROM),
}

#: The once-only record. Committed, because the container is not.
RUN_LEDGER = "c17_holdout_run_ledger.json"

#: The year the rehearsal runs on: PLAN.md's validation year, visible since C4.
REHEARSAL_YEAR = 2024

#: Point metrics written to the store, C13's set exactly.
STORE_METRICS: tuple[str, ...] = C13_STORE_METRICS


class HoldoutRunError(RuntimeError):
    """The evaluation may not run, or may not run the way it was asked to."""


# ---------------------------------------------------------------------------
# Artefact naming — holdout and rehearsal can never collide
# ---------------------------------------------------------------------------


def run_tag(year: int) -> str:
    return "c17_holdout" if year == HOLDOUT_YEAR else "c17_rehearsal"


def predictions_path(zone: str, year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{zone}_{year}_predictions.csv.gz"


def compute_summary_path(zone: str, year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{zone}_{year}_compute.json"


def daily_path(zone: str, year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{zone}_{year}_daily.csv.gz"


def dispatch_summary_path(zone: str, year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{zone}_{year}_summary.json"


def metrics_path(year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{year}_metrics.csv"


def intervals_path(year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{year}_intervals.csv"


def invariant_flags_path(year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{year}_invariant_flags.json"


def evaluation_report_path(year: int):
    return RESULTS_DIR / f"{run_tag(year)}_{year}_evaluation.json"


# ---------------------------------------------------------------------------
# The window: every evaluated row is hourly and precedes the SDAC cutover
# ---------------------------------------------------------------------------


def hourly_through_cutover(prices: pd.DataFrame, zone_key: str) -> pd.DataFrame:
    """The price series truncated at the 15-minute cutover, asserted hourly.

    The 2025 cache file is a mixed-resolution year by construction: SDAC moved
    the market time unit on 2025-10-01 and Energy-Charts returns both segments
    in one response. PLAN.md ends the main hourly backtest the day before, so
    the truncation is the pre-registered window, not a convenience — and it
    happens *before* the feature build, so no 15-minute row can reach a lag, a
    rolling mean or a target. The post-cutover segment is reported by the
    preflight and by :func:`window_report`; it is never resampled.
    """
    index = pd.DatetimeIndex(prices.index)
    kept = prices.loc[index < CUTOVER_UTC]
    segments = resolution_segments(pd.DatetimeIndex(kept.index))
    offenders = [int(s.seconds) for s in segments if int(s.seconds) != HOURLY_SECONDS]
    if offenders:
        raise HoldoutRunError(
            f"{zone_key}: the pre-cutover segment of the price series is not hourly "
            f"— resolutions {sorted(set(offenders))}s found. The pre-registration "
            f"asserts resolution_seconds == 3600 on every evaluated row; a "
            f"resolution change inside the window is a FLAG, not a resample."
        )
    kept = kept.copy()
    kept.attrs = dict(prices.attrs)
    return kept


def window_for(zone_key: str, year: int) -> tuple[Any, list[dt.date], pd.DataFrame]:
    """``(feature matrix, evaluation days, hourly prices)`` for one zone-year.

    The post-cutover cut is applied twice on purpose, and the second one should
    never bite: :func:`hourly_through_cutover` removes the 15-minute rows before
    the feature build, so the feature matrix cannot carry a market day after
    2025-09-30 in the first place. The day filter here is the belt to that
    braces, and the count it drops is reported rather than assumed to be zero.
    """
    frame = load_zone_series(zone_key)
    prices = hourly_through_cutover(frame, zone_key)
    matrix = build_features(prices, zone_key)
    built = evaluation_days(matrix, [year])
    days = [d for d in built if d <= LAST_MARKET_DAY]
    dropped = [d for d in built if d > LAST_MARKET_DAY]
    if dropped:
        print(
            f"  {zone_key} {year}: {len(dropped)} market day(s) after "
            f"{LAST_MARKET_DAY} dropped from the window (first {dropped[0]}) — the "
            f"price truncation should already have prevented these",
            flush=True,
        )
    if not days:
        raise HoldoutRunError(
            f"{zone_key} {year}: no evaluation day survived the feature build"
        )
    if year == HOLDOUT_YEAR and len(days) != EXPECTED_MARKET_DAYS:
        raise HoldoutRunError(
            f"{zone_key} {year}: the window holds {len(days)} market days, not the "
            f"pre-registered {EXPECTED_MARKET_DAYS}. The window is pre-registered; "
            f"a mismatch is a FLAG, not something to evaluate around."
        )
    return matrix, days, prices


# ---------------------------------------------------------------------------
# The once-only ledger
# ---------------------------------------------------------------------------


def load_ledger() -> dict[str, Any]:
    path = RESULTS_DIR / RUN_LEDGER
    if not path.exists():
        return {
            "cycle": "C17",
            "what_this_is": (
                "the once-only record of the 2025 holdout evaluation. PLAN.md C16: "
                "'evaluate it exactly once'. A completed entry for the holdout year "
                "makes a further evaluate run refuse; there is no override flag, "
                "because a second evaluation is a human's decision and has to be "
                "labelled as one."
            ),
            "evaluations": [],
        }
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_ledger(ledger: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with (RESULTS_DIR / RUN_LEDGER).open("w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2, default=str)
        fh.write("\n")


def ledger_entry_for(ledger: dict[str, Any], year: int) -> dict[str, Any] | None:
    for entry in ledger.get("evaluations", []):
        if int(entry.get("year", -1)) == year:
            return entry
    return None


def open_ledger_entry(year: int, prereg: dict[str, Any]) -> tuple[dict, dict]:
    """Create or resume this year's entry. Refuses a completed holdout year."""
    ledger = load_ledger()
    entry = ledger_entry_for(ledger, year)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if entry is not None and entry.get("status") == "completed":
        if year == HOLDOUT_YEAR:
            raise HoldoutRunError(
                f"the {year} holdout was already evaluated, at "
                f"{entry.get('finished_at_utc')} on git {entry.get('git_sha')}. "
                f"PLAN.md C16 and c16_preregistration.json allow exactly one "
                f"evaluation. A re-run is a SECOND evaluation: it needs a human's "
                f"decision, has to be labelled as one wherever its numbers appear, "
                f"and this runner will not start it."
            )
        ledger["evaluations"].remove(entry)
        entry = None
    if entry is None:
        entry = {
            "year": year,
            "is_the_sealed_holdout": year == HOLDOUT_YEAR,
            "status": "in_progress",
            "started_at_utc": now,
            "git_sha": git_sha(),
            "config_hash": config_hash(),
            "library_fingerprint": library_fingerprint(),
            "library_versions": library_versions(),
            "preregistration_git_sha": prereg["git_sha"],
            "phases_completed": [],
            "resumptions": [],
        }
        ledger.setdefault("evaluations", []).append(entry)
    else:
        entry["resumptions"].append(
            {"at_utc": now, "git_sha": git_sha(),
             "phases_already_completed": list(entry.get("phases_completed", []))}
        )
        print(
            f"  RESUMING an evaluation of {year} opened at "
            f"{entry.get('started_at_utc')}; phases already completed: "
            f"{entry.get('phases_completed')}. Nothing already computed is "
            f"recomputed, so this is the same evaluation, not a second one.",
            flush=True,
        )
    write_ledger(ledger)
    return ledger, entry


def mark_phase(ledger: dict[str, Any], entry: dict[str, Any], phase: str) -> None:
    if phase not in entry["phases_completed"]:
        entry["phases_completed"].append(phase)
    write_ledger(ledger)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def evaluation_gate(
    prereg: dict[str, Any], year: int, zone_keys: list[str]
) -> dict[str, Any]:
    """Refuse the holdout evaluation unless every precondition holds.

    The conjunction is :func:`collect_preflight`'s, not a second copy of it.
    ``library_fingerprint_moved`` is in it deliberately: the holdout is read
    against C10-C15's 2024 numbers, every one of which was produced under
    ``856fb19ac0c4eecd``, and two numbers from two library sets are not a
    comparison. A rehearsal year is gated only on the specs agreeing.
    """
    payload = collect_preflight(prereg, zone_keys, verbose=True)
    if year != HOLDOUT_YEAR:
        print(
            f"\n  REHEARSAL on {year}: the holdout gate is not applied. Artefacts "
            f"are written as {run_tag(year)}_* and nothing is appended to the "
            f"store.",
            flush=True,
        )
        return {"gated": False, "year": year, "preflight": payload}
    if payload["blockers_standing"]:
        raise HoldoutRunError(
            "the pre-registered evaluation may not run — standing blocker(s): "
            + ", ".join(payload["blockers_standing"])
            + ". c16_preregistration.json's preconditions are not a checklist to "
            "note and proceed past: a precondition discovered after the first 2025 "
            "number is seen is a precondition discovered too late."
        )
    return {"gated": True, "year": year, "preflight": payload}


# ---------------------------------------------------------------------------
# Phase: compute — the forecasts
# ---------------------------------------------------------------------------


def compute_zone(zone_key: str, year: int, spec: WalkForwardSpec) -> dict[str, Any]:
    """The naive floor and the comparable LEAR, walked forward over the window.

    This is C13's ``compute_zone_year`` applied to the holdout window: the same
    ``WalkForwardSpec``, the same ``LearSpec``, the same expanding window over
    the whole cached history. The expanding window means a 2025 fold trains on
    2019-2024 inclusive — the validation year moves from 'evaluated' to
    'trained on', which is what an expanding window does and what the
    pre-registration says it does.
    """
    assert_not_sealed(year, f"walk {zone_key} forward across {year}")
    zone = load_zones()[zone_key]
    lear_spec = LearSpec()

    print(f"\n=== {zone_key} {year} (tier {zone.tier}, {zone.regime}) ===", flush=True)
    matrix, days, prices = window_for(zone_key, year)
    stitch = prices.attrs["stitch_report"]
    print(f"  prices {len(prices)} hourly rows through the cutover; evaluating "
          f"{len(days)} market days {days[0]}..{days[-1]}", flush=True)

    naive = run_walk_forward(matrix, NaiveLastWeek, days, spec)
    lear = run_walk_forward(matrix, lear_factory(lear_spec, name="lear"), days, spec)
    if not lear.y_true.index.equals(naive.y_true.index):
        raise HoldoutRunError(
            f"{zone_key} {year}: the LEAR and the naive floor were evaluated on "
            f"different indices — they would not be comparable"
        )
    naive_scores = score(naive.y_true, naive.y_pred)
    lear_scores = score(lear.y_true, lear.y_pred)
    ratio = rmae(lear.y_true, lear.y_pred, naive.y_pred)
    print(f"  naive MAE {naive_scores.mae:.3f}   LEAR MAE {lear_scores.mae:.3f}   "
          f"rMAE {ratio:.4f}   coverage {lear_scores.coverage:.5f}", flush=True)

    frame = pd.DataFrame(
        {
            "market_day": matrix.market_day.reindex(lear.y_true.index).to_numpy(),
            "y_true": lear.y_true.to_numpy(dtype="float64"),
            LEAR_COLUMN: lear.y_pred.to_numpy(dtype="float64"),
            NAIVE_COLUMN: naive.y_pred.to_numpy(dtype="float64"),
        },
        index=lear.y_true.index,
    )
    late = [d for d in frame["market_day"].astype(str) if d > LAST_MARKET_DAY.isoformat()]
    if late:
        raise HoldoutRunError(
            f"{zone_key} {year}: {len(late)} predicted hour(s) carry a market day "
            f"on or after the cutover, first {late[0]}"
        )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(predictions_path(zone_key, year), float_format="%.4f")

    summary = {
        "cycle": "C17",
        "phase": "compute",
        "is_the_sealed_holdout": year == HOLDOUT_YEAR,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "libraries": library_versions(),
        "library_fingerprint": library_fingerprint(),
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "evaluation_years": [year],
        "train_from": FULL_HISTORY_FROM,
        "walk_forward_spec": spec.as_dict(),
        "lear_spec": lear_spec.as_dict(),
        "price_series": stitch.as_dict(),
        "feature_build": matrix.report.as_dict(),
        "n_rows": int(len(matrix.index)),
        "n_evaluation_days": len(days),
        "first_day": days[0].isoformat(),
        "last_day": days[-1].isoformat(),
        "window_ends_before_the_sdac_cutover": days[-1] <= LAST_MARKET_DAY,
        "scores": {
            "naive_last_week": naive_scores.as_dict(),
            "lear_price_only": lear_scores.as_dict(),
        },
        "rmae_vs_naive": round(ratio, 6),
        "n_folds": len(lear.folds),
        "walk_forward": lear.as_dict(),
        "leakage_guards": {
            "check_leakage": True,
            "what_ran": (
                "run_walk_forward's default: forecast.leakage.assert_no_leakage on "
                "the train AND test matrix of every fold (every feature's max "
                "timestamp against that row's gate closure), plus "
                "_assert_training_targets_were_public (every training target "
                "published before the fold's gate closure). Both raise rather than "
                "warn, so a summary that exists at all is a run in which they held."
            ),
            "n_folds_checked": len(lear.folds),
            "preregistered_assertions_covered": [
                "every feature's max timestamp precedes its row's gate closure",
                "every training target was published before the fold's gate closure",
            ],
        },
        "note": (
            "the pre-registered headline arm: C4's committed LearSpec on price and "
            "calendar features, expanding window over the whole cached history, "
            "against the same-hour-last-week floor. Identical configuration to the "
            "nine-zone comparable arm every C10-C15 cross-zone number is built on."
        ),
    }
    with compute_summary_path(zone_key, year).open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
        fh.write("\n")
    lear.folds_frame().to_csv(
        RESULTS_DIR / f"{run_tag(year)}_{zone_key}_{year}_folds.csv", index=False
    )
    return summary


def compute(args: argparse.Namespace) -> int:
    zone_keys = args.zones or list(load_zones())
    spec = WalkForwardSpec(
        refit_every_days=args.refit_every,
        min_train_days=args.min_train_days,
        train_window_days=args.train_window_days,
    )
    done: list[str] = []
    for zone_key in zone_keys:
        if predictions_path(zone_key, args.year).exists():
            print(f"{zone_key} {args.year}: artefact already present, skipped",
                  flush=True)
            continue
        compute_zone(zone_key, args.year, spec)
        done.append(zone_key)
    print(f"\ncompute phase done: {len(done)} zone(s) — {', '.join(done) or 'none'}")
    return 0


# ---------------------------------------------------------------------------
# Phase: dispatch — commit-then-settle through the rolling LP
# ---------------------------------------------------------------------------

#: The per-day artefact's columns, in C12/C13's spelling exactly. Identical
#: column names are what let C13's table builders read a C17 frame.
DAILY_COLUMNS: tuple[str, ...] = C13_DAILY_COLUMNS

#: ``(curve, column, model, exog_variant)`` for the two forecast curves.
C17_ARMS: tuple[tuple[str, str, str, str], ...] = (
    (COMPARABLE_CURVE, LEAR_COLUMN, "lear", "price_only"),
    (NAIVE_CURVE, NAIVE_COLUMN, "naive_last_week", ""),
)


def load_prediction_frame(zone: str, year: int, realised: pd.Series) -> pd.DataFrame:
    """This cycle's prediction artefact, checked hour-for-hour against prices."""
    path = predictions_path(zone, year)
    if not path.exists():
        raise HoldoutRunError(
            f"{zone} {year}: {path.name} is missing — run the compute phase first"
        )
    frame = pd.read_csv(path, dtype={"market_day": str})
    for column in ("timestamp_utc", "market_day", "y_true", LEAR_COLUMN, NAIVE_COLUMN):
        if column not in frame.columns:
            raise HoldoutRunError(f"{path.name} has no {column!r} column")
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp_utc"], utc=True))
    frame = frame.set_index(index).sort_index()
    aligned = realised.reindex(frame.index)
    if aligned.isna().any():
        raise HoldoutRunError(
            f"{zone} {year}: {int(aligned.isna().sum())} forecast timestamp(s) have "
            f"no realised price — the artefact and the price cache disagree"
        )
    gap = float(
        np.nanmax(
            np.abs(frame["y_true"].to_numpy(dtype=float) - aligned.to_numpy(dtype=float))
        )
    )
    if gap > 1e-6:
        raise HoldoutRunError(
            f"{zone} {year}: the artefact's y_true differs from the realised price "
            f"series by up to {gap:.6g} EUR/MWh — one of the two is not what was scored"
        )
    frame.attrs["max_y_true_vs_realised_gap"] = gap
    return frame


def shape_table_for(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """C12's per-day shape table for one forecast column, with derived flags."""
    table = daily_shape_table(frame["y_true"], frame[column], frame["market_day"].to_numpy())
    table = table.rename(columns={"realised_spread": "realised_spread_forecastwise"})
    table["abs_spread_error"] = table["spread_error"].abs()
    defined = np.isfinite(table["spearman"].to_numpy(dtype=float))
    table["spearman_defined"] = defined.astype(float)
    table["spearman_contrib"] = np.where(
        defined, table["spearman"].to_numpy(dtype=float), 0.0
    )
    return table


def dispatch_zone(
    zone_key: str, year: int, spec: BatterySpec, cfg: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Oracle + comparable LEAR + naive floor through the rolling LP.

    Commit-then-settle, as C6 built it and the pre-registration requires: the
    forecast curves are passed as ``decision_prices`` and the LP's schedule is
    then valued at ``realised``. ``assert_settlement_is_not_a_readback`` is run
    on every curve, so an objective value from a forecast solve cannot reach a
    reported number even by accident.
    """
    assert_not_sealed(year, f"dispatch {zone_key} {year}")
    zone = load_zones()[zone_key]
    tz = zone_timezone(zone_key)
    terminal = cfg.get("terminal") or {}
    roll_kwargs = dict(
        trailing_days=int(terminal.get("trailing_days", 7)),
        trailing_quantile=float(terminal.get("trailing_quantile", 0.5)),
        min_trailing_days=int(terminal.get("min_trailing_days", 1)),
        tz=tz,
    )

    realised = load_realised(zone_key, [year])
    realised = realised.loc[pd.DatetimeIndex(realised.index) < CUTOVER_UTC]
    segments = resolution_segments(pd.DatetimeIndex(realised.index))
    if any(int(s.seconds) != HOURLY_SECONDS for s in segments):
        raise HoldoutRunError(
            f"{zone_key} {year}: the realised series carries a non-hourly segment "
            f"inside the evaluated window — a FLAG, not a resample"
        )
    frame = load_prediction_frame(zone_key, year, realised)
    curves = {
        curve: Curve(
            name=curve,
            prices=frame[column].astype(float),
            source=f"{predictions_path(zone_key, year).name}:{column}",
        )
        for curve, column, _, _ in C17_ARMS
    }

    forecast_days: set[dt.date] = set()
    for curve in curves.values():
        forecast_days |= set(market_days(pd.DatetimeIndex(curve.prices.index), tz).tolist())
    labels = pd.Series(realised.index).dt.tz_convert(tz).dt.date
    wanted = {
        d for d in labels if d.year == year and d <= LAST_MARKET_DAY
    } & forecast_days
    if not wanted:
        raise HoldoutRunError(
            f"{zone_key} {year}: no market day is both in the window and forecast"
        )

    print(f"\n=== {zone_key} {year} (tier {zone.tier}, {zone.regime}) — "
          f"{len(curves)} forecast curve(s) + oracle over {len(wanted)} market days "
          f"{min(wanted)} .. {max(wanted)} ===", flush=True)

    results: dict[str, RollingResult] = {
        ORACLE_CURVE: run_rolling_dispatch(
            zone_key, realised, spec, decision_prices=None, curve=ORACLE_CURVE,
            days=wanted, **roll_kwargs
        )
    }
    for curve, _, _, _ in C17_ARMS:
        results[curve] = run_rolling_dispatch(
            zone_key, realised, spec, decision_prices=curves[curve].prices,
            curve=curve, days=wanted, **roll_kwargs
        )
    bounds = {name: same_start_oracle(res, spec) for name, res in results.items()}
    own = {name: set(res.days) for name, res in results.items()}
    shared = common_days(results)

    pooled: dict[str, dict[str, Any]] = {
        name: {
            "own_coverage": pooled_capture(
                res, bounds[name], results[ORACLE_CURVE], own[name], spec.power_mw
            ),
            "common_hours": pooled_capture(
                res, bounds[name], results[ORACLE_CURVE], shared, spec.power_mw
            ),
        }
        for name, res in results.items()
    }

    # --- the invariants CLAUDE.md requires, every curve -------------------
    invariants: dict[str, dict[str, Any]] = {}
    for name, res in results.items():
        block: dict[str, Any] = {
            "day_lengths_match_local_calendar": check_day_lengths(res, zone_key),
            "settlement_is_not_a_decision_price_readback":
                assert_settlement_is_not_a_readback(res),
            "decision_value_added_non_negative":
                check_decision_value_added_non_negative(res, spec),
        }
        if name == ORACLE_CURVE:
            block["value_added_non_negative_at_realised"] = (
                check_value_added_non_negative(res)
            )
        else:
            block["same_start_oracle_dominates_every_day"] = check_per_day_dominance(
                res, bounds[name]
            )
            block["beats_naive_pooled_common_days"] = (
                {"applicable": False, "reason": "this is the naive floor"}
                if name == NAIVE_CURVE
                else beats_naive(res, results[NAIVE_CURVE], shared)
            )
            arm_cash = pooled[name]["common_hours"]["cash_eur"]
            oracle_cash = pooled[ORACLE_CURVE]["common_hours"]["cash_eur"]
            block["oracle_dominates_pooled_common_days"] = {
                "holds": oracle_cash >= arm_cash - 1e-6,
                "oracle_cash_eur": round(oracle_cash, 4),
                "arm_cash_eur": round(arm_cash, 4),
                "margin_eur": round(oracle_cash - arm_cash, 4),
                "capture_rolled_oracle_cash": round(
                    pooled[name]["common_hours"]["capture_rolled_oracle_cash"], 6
                ),
            }
        invariants[name] = block
    failures = [
        f"{name}.{check}"
        for name, block in invariants.items()
        for check, outcome in block.items()
        if outcome.get("applicable", True) and not outcome.get("holds", True)
    ]
    for name in sorted(results):
        block = pooled[name]["common_hours"]
        rolled = block["capture_rolled_oracle_cash"]
        mark = "OK " if not any(f.startswith(f"{name}.") for f in failures) else "FAIL"
        print(f"  [{mark}] {name:<20} cash {block['cash_eur']:>10,.0f} EUR  "
              f"{block['cash_eur_per_mw_year']:>9,.0f} EUR/MW/yr  "
              f"capture {'  n/a ' if rolled is None else f'{rolled:.4f}'}", flush=True)

    # --- the per-day artefact, in C12/C13's column shape ------------------
    shapes = {curve: shape_table_for(frame, column) for curve, column, _, _ in C17_ARMS}
    shared_labels = {d.isoformat() for d in shared}
    frames: list[pd.DataFrame] = []
    for name, res in results.items():
        captured = capture_frame(res, results[ORACLE_CURVE], bounds[name])
        if captured.empty:
            continue
        block = pd.DataFrame(index=pd.Index(captured["market_day"], name="market_day"))
        block["zone"] = zone_key
        block["curve"] = name
        block["cash"] = captured["cash_eur"].to_numpy(dtype=float)
        block["oracle_cash"] = captured["rolled_oracle_cash_eur"].to_numpy(dtype=float)
        block["lost"] = block["oracle_cash"] - block["cash"]
        block["value_added"] = captured["value_added_eur"].to_numpy(dtype=float)
        block["realised_spread"] = captured["realised_spread"].to_numpy(dtype=float)
        block["in_common_day_set"] = [d in shared_labels for d in block.index]
        block["n_dispatch_hours"] = captured["n_hours"].to_numpy(dtype=int)
        shape_columns = (
            "n_hours", "sum_abs_error", "sum_sq_error", "sum_error",
            "realised_spread_forecastwise", "forecast_spread", "spread_error",
            "abs_spread_error", "spearman", "spearman_contrib", "spearman_defined",
        )
        if name == ORACLE_CURVE:
            for column in shape_columns:
                block[column] = np.nan
            block["model"], block["exog_variant"] = ORACLE_MODEL, ORACLE_VARIANT
            block["train_from"] = ""
        else:
            aligned = shapes[name].reindex(block.index)
            if aligned["n_hours"].isna().any():
                absent = aligned.index[aligned["n_hours"].isna()].tolist()
                raise HoldoutRunError(
                    f"{zone_key} {year}/{name}: {len(absent)} dispatched day(s) have "
                    f"no hourly forecast rows, first {absent[0]} — the dispatch and "
                    f"the prediction artefact disagree about which days exist"
                )
            for column in shape_columns:
                block[column] = aligned[column].to_numpy(dtype=float)
            arm = next(a for a in C17_ARMS if a[0] == name)
            block["model"], block["exog_variant"] = arm[2], arm[3]
            block["train_from"] = FULL_HISTORY_FROM
        block["vintage"] = "honest"
        block["tier"], block["regime"] = zone.tier, zone.regime
        block["year"] = year
        frames.append(block.reset_index())
    daily = pd.concat(frames, ignore_index=True)[list(DAILY_COLUMNS)]
    late = sorted(d for d in daily["market_day"] if d > LAST_MARKET_DAY.isoformat())
    if late:
        raise HoldoutRunError(
            f"{zone_key} {year}: {len(late)} dispatched day(s) fall on or after the "
            f"SDAC cutover, first {late[0]}"
        )

    summary = {
        "cycle": "C17",
        "phase": "dispatch",
        "is_the_sealed_holdout": year == HOLDOUT_YEAR,
        "zone": zone_key,
        "tier": zone.tier,
        "regime": zone.regime,
        "year": year,
        "window_last_market_day": LAST_MARKET_DAY.isoformat(),
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "battery_spec": spec.as_dict(),
        "n_market_days_wanted": len(wanted),
        "dispatched_days_per_curve": {n: len(d) for n, d in sorted(own.items())},
        "n_common_days": len(shared),
        "skipped_days_per_curve": {
            name: [s.as_dict() for s in res.skipped] for name, res in results.items()
        },
        "curve_sources": {
            curve: {
                **curves[curve].as_dict(),
                "source": curves[curve].source,
                "alignment": assert_curve_aligns(curves[curve], realised),
            }
            for curve in curves
        },
        "max_y_true_vs_realised_gap": frame.attrs["max_y_true_vs_realised_gap"],
        "pooled": pooled,
        "invariants": invariants,
        "invariant_failures": failures,
        "realised_losses": {n: report_realised_losses(r) for n, r in results.items()},
        "simultaneity": {n: simultaneity_flag(r, spec) for n, r in results.items()},
        "point_error_on_dispatched_hours": {
            curve: mae_on_days(curves[curve], realised, shared, tz)
            for curve, _, _, _ in C17_ARMS
        },
        "nan_policy": {
            "policy": "decline",
            "decision": "a market day whose forecast vector has a hole is skipped and "
                        "counted, never patched (NOTE C4-02 / NOTE C10-01)",
        },
        "soc_note": (
            "the window is its own rolling run and opens at initial_soc_fraction, "
            "exactly as C11's 2024 run and C13's per-year runs did; SoC carries "
            "across days inside the window and not across its boundary"
        ),
    }
    return summary, daily


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch every zone, recording rather than swallowing a failure.

    C13's treatment, unchanged and for its reasons: the per-day same-start
    oracle bound is a theorem and a violation would be a bug in the LP;
    ``value(naive) <= value(forecast)`` pooled is an empirical claim about an
    average, which CLAUDE.md itself qualifies. So nothing is relaxed, every
    failure is written to the flags file with its numbers, and the phase exits
    non-zero when any were found.
    """
    zone_keys = args.zones or list(load_zones())
    year = args.year
    cfg = load_battery_config()
    spec = BatterySpec.from_config(cfg)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    flagged: list[dict[str, Any]] = []
    n = 0
    for zone_key in zone_keys:
        summary, daily = dispatch_zone(zone_key, year, spec, cfg)
        daily.to_csv(daily_path(zone_key, year), index=False, float_format="%.10g")
        with dispatch_summary_path(zone_key, year).open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
            fh.write("\n")
        n += 1
        for failure in summary["invariant_failures"]:
            curve, _, check = failure.partition(".")
            flagged.append(
                {
                    "zone": zone_key,
                    "year": year,
                    "curve": curve,
                    "check": check,
                    "detail": summary["invariants"][curve][check],
                    "oracle_eur_per_mw_year": summary["pooled"][ORACLE_CURVE][
                        "common_hours"]["cash_eur_per_mw_year"],
                    "curve_eur_per_mw_year": summary["pooled"][curve][
                        "common_hours"]["cash_eur_per_mw_year"],
                    "capture_rolled_oracle_cash": summary["pooled"][curve][
                        "common_hours"]["capture_rolled_oracle_cash"],
                    "realised_spread_mean_eur_per_mwh": summary["pooled"][curve][
                        "common_hours"]["realised_spread_mean_eur_per_mwh"],
                }
            )
    payload = {
        "cycle": "C17",
        "year": year,
        "is_the_sealed_holdout": year == HOLDOUT_YEAR,
        "generated_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "git_sha": git_sha(),
        "note": (
            "CLAUDE.md's pooled naive-dominance invariant, per zone. The per-day "
            "same-start oracle bound is a theorem and is asserted separately. A "
            "flag here is a statement about a regime-year, is labelled wherever "
            "its capture ratio is reported, and belongs in PROGRESS.md as a FLAG."
        ),
        "flags": flagged,
    }
    with invariant_flags_path(year).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.write("\n")
    print(f"\ndispatch phase done: {n} zone(s); {len(flagged)} invariant flag(s)")
    for flag in flagged:
        print(f"  FLAG {flag['zone']} {flag['year']} {flag['curve']}.{flag['check']}: "
              f"margin {flag['detail'].get('margin_eur')} EUR, oracle "
              f"{flag['oracle_eur_per_mw_year']:.0f} EUR/MW/yr, capture "
              f"{flag['capture_rolled_oracle_cash']:.4f}")
    return 1 if flagged else 0


# ---------------------------------------------------------------------------
# Phase: analyse — the metric table and the intervals
# ---------------------------------------------------------------------------


def assemble_daily(zone_keys: list[str], year: int) -> pd.DataFrame:
    """Every zone's per-day artefact in one frame, in C12/C13's column shape."""
    blocks: list[pd.DataFrame] = []
    for zone_key in zone_keys:
        path = daily_path(zone_key, year)
        if not path.exists():
            raise HoldoutRunError(
                f"{path.name} is missing — run the dispatch phase for {zone_key}"
            )
        blocks.append(pd.read_csv(path, dtype={"market_day": str}))
    daily = pd.concat(blocks, ignore_index=True)
    seen = {int(d[:4]) for d in daily["market_day"]}
    if seen != {year}:
        raise HoldoutRunError(
            f"the assembled frame carries market days in {sorted(seen)}, not "
            f"only {year}"
        )
    late = sorted(d for d in daily["market_day"] if d > LAST_MARKET_DAY.isoformat())
    if late:
        raise HoldoutRunError(
            f"{len(late)} assembled day(s) fall on or after the SDAC cutover, "
            f"first {late[0]}"
        )
    return daily


def baseline_comparison(points: pd.DataFrame, prereg: dict[str, Any]) -> pd.DataFrame:
    """The headline arm beside the 2024 number the pre-registration recorded.

    The baseline is read from ``c16_preregistration.json``, which was written
    and committed while the holdout was still sealed — so the comparison cannot
    be a number chosen after seeing the 2025 one.
    """
    baseline = prereg.get("baseline_2024_for_comparison", {})
    rows: list[dict[str, Any]] = []
    frame = points[
        (points["curve"] == COMPARABLE_CURVE) & (points["scope"] == "common_hours")
    ]
    for _, row in frame.iterrows():
        zone = str(row["zone"])
        want = baseline.get(zone, {})
        for metric, value in want.items():
            live = row.get(metric)
            rows.append(
                {
                    "zone": zone,
                    "metric": metric,
                    "holdout_2025": None if live is None or pd.isna(live) else float(live),
                    "preregistered_2024": float(value),
                    "delta": (
                        None if live is None or pd.isna(live)
                        else float(live) - float(value)
                    ),
                }
            )
    return pd.DataFrame(rows)


def analyse(args: argparse.Namespace) -> int:
    prereg = load_preregistration()
    zone_keys = args.zones or list(load_zones())
    year = args.year
    spec = BatterySpec.from_config(load_battery_config())

    daily = assemble_daily(zone_keys, year)
    by_year = c13.curve_days_by_year(daily)
    points = c13.point_table(by_year, spec.power_mw)
    drawn, basis_report = c13.year_replicates(by_year, year, zone_keys, spec.power_mw)
    intervals = c13.interval_rows(drawn, zone_keys)

    points.to_csv(metrics_path(year), index=False, float_format="%.10g")
    intervals.to_csv(intervals_path(year), index=False, float_format="%.10g")
    comparison = baseline_comparison(points, prereg)
    comparison.to_csv(
        RESULTS_DIR / f"{run_tag(year)}_{year}_vs_2024.csv", index=False,
        float_format="%.10g",
    )

    headline = points[
        (points["curve"] == COMPARABLE_CURVE) & (points["scope"] == "common_hours")
    ].set_index("zone")
    print(f"\n=== {year} headline — {COMPARABLE_CURVE}, common_hours basis ===",
          flush=True)
    print(f"  {'zone':<9} {'capture':>8} {'EUR/MW/yr':>11} {'MAE':>7} {'rMAE':>6} "
          f"{'spearman':>9}", flush=True)
    for zone_key in zone_keys:
        if zone_key not in headline.index:
            continue
        row = headline.loc[zone_key]
        print(f"  {zone_key:<9} {row['capture_rolled_oracle_cash']:>8.4f} "
              f"{row['dispatch_cash_eur_per_mw_year']:>11,.0f} "
              f"{row['mae_on_dispatched_hours']:>7.2f} "
              f"{row['rmae_vs_naive_on_dispatched_hours']:>6.3f} "
              f"{row['within_day_spearman_mean']:>9.4f}", flush=True)

    flags_path = invariant_flags_path(year)
    flags = []
    if flags_path.exists():
        with flags_path.open(encoding="utf-8") as fh:
            flags = json.load(fh).get("flags", [])

    report = {
        "cycle": "C17",
        "phase": "analyse",
        "year": year,
        "is_the_sealed_holdout": year == HOLDOUT_YEAR,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config_hash": config_hash(),
        "library_fingerprint": library_fingerprint(),
        "library_versions": library_versions(),
        "zones": list(zone_keys),
        "window": {
            "first_market_day": str(daily["market_day"].min()),
            "last_market_day": str(daily["market_day"].max()),
            "n_days_in_cross_zone_basis": len(drawn.days),
            "basis_report": basis_report,
        },
        "bootstrap": {
            "method": "paired circular moving-block over market days",
            "block_days_ladder": list(c13.BLOCK_LADDER),
            "headline_block_days": c13.HEADLINE_BLOCK,
            "n_replicates": c13.N_REPLICATES,
            "seed": c13.SEED,
        },
        "invariant_flags": flags,
        "n_invariant_flags": len(flags),
        "headline": {
            zone_key: {
                metric: (
                    None if pd.isna(headline.loc[zone_key][metric])
                    else float(headline.loc[zone_key][metric])
                )
                for metric in (
                    "capture_rolled_oracle_cash",
                    "dispatch_cash_eur_per_mw_year",
                    "eur_per_mw_year_lost_vs_oracle",
                    "mae_on_dispatched_hours",
                    "rmae_vs_naive_on_dispatched_hours",
                    "within_day_spearman_mean",
                    c13.ERROR_OVER_HEADROOM,
                )
            }
            for zone_key in zone_keys if zone_key in headline.index
        },
        "vs_preregistered_2024_baseline": comparison.to_dict(orient="records"),
        "outputs": {
            "metrics": metrics_path(year).name,
            "intervals": intervals_path(year).name,
            "comparison": f"{run_tag(year)}_{year}_vs_2024.csv",
        },
    }
    with evaluation_report_path(year).open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
        fh.write("\n")
    print(f"\n  -> {metrics_path(year).name}, {intervals_path(year).name}, "
          f"{evaluation_report_path(year).name}", flush=True)
    return 0


# ---------------------------------------------------------------------------
# Phase: ingest — one append to the store
# ---------------------------------------------------------------------------


def store_rows(points: pd.DataFrame, intervals: pd.DataFrame, year: int) -> list[ResultRow]:
    """Every point metric and its headline-block interval bounds, as rows.

    Long format, as ``docs/results_store.md`` requires: a new evaluation year
    is new *rows*, never a new column and never a schema change.
    """
    rows: list[ResultRow] = []
    bounds = intervals[intervals["block_days"] == c13.HEADLINE_BLOCK]
    for _, row in points.iterrows():
        curve = str(row["curve"])
        key = STORE_KEY.get(curve)
        if key is None:
            raise HoldoutRunError(f"no store key for curve {curve!r}")
        model, variant, train_from = key
        common = dict(
            zone=str(row["zone"]),
            tier=str(row["tier"]),
            regime=str(row["regime"]),
            model=model,
            exog_variant=variant,
            vintage="honest",
            train_from=train_from,
            evaluation_years=str(year),
            scope=str(row["scope"]),
            n=str(int(row["n_days"])),
            n_scored=("" if pd.isna(row.get("n_hours")) else str(int(row["n_hours"]))),
            source_cycle="C17",
            source_artefact=daily_path(str(row["zone"]), year).name,
        )
        for metric in STORE_METRICS:
            value = row.get(metric)
            if value is None or pd.isna(value):
                continue
            rows.append(ResultRow(metric=metric, value=float(value), **common))
        if str(row["scope"]) != "common_hours":
            continue
        selected = bounds[
            (bounds["zone"] == row["zone"])
            & (bounds["year"] == year)
            & (bounds["curve"] == curve)
        ]
        for _, bound in selected.iterrows():
            metric = str(bound["metric"])
            for suffix, column in (
                ("_ci_low", "ci_low"), ("_ci_high", "ci_high"), ("_boot_sd", "boot_sd")
            ):
                rows.append(
                    ResultRow(metric=f"{metric}{suffix}", value=float(bound[column]),
                              **common)
                )
    return rows


def ingest(args: argparse.Namespace) -> int:
    year = args.year
    for path in (metrics_path(year), intervals_path(year)):
        if not path.exists():
            raise HoldoutRunError(f"{path.name} is missing — run the analyse phase first")
    points = pd.read_csv(metrics_path(year))
    intervals = pd.read_csv(intervals_path(year))
    rows = store_rows(points, intervals, year)
    print(f"{len(rows):,} row(s) to append for {year}")
    if year != HOLDOUT_YEAR:
        print(
            f"  {year} is the rehearsal year: nothing is appended. The store's "
            f"{year} rows were written by C11/C12 and re-writing them under a new "
            f"run id would put two rows with different provenance behind one number."
        )
        return 0
    if args.no_append:
        print("--no-append: nothing written")
        return 0
    report = append_rows(
        rows,
        cycle="C17",
        git_sha=git_sha(),
        config_hash=config_hash(),
        path=None if args.results_path is None else Path(args.results_path),
        argv=sys.argv,
        note=(
            "C17: the single pre-registered evaluation of the 2025 holdout "
            f"({EXPECTED_MARKET_DAYS} market days, 2025-01-01..{LAST_MARKET_DAY}, "
            "ending the day before the SDAC 15-minute go-live). The nine-zone "
            "comparable arm (C4's LEAR on price/calendar features, expanding "
            "window from 2019), the same-hour-last-week floor and the "
            "perfect-foresight oracle, dispatched through C5/C6's rolling LP "
            "commit-then-settle and scored with C11's pooled_capture and C12's "
            "metric layer. Intervals are the paired circular moving-block day "
            f"bootstrap, {c13.N_REPLICATES} replicates, seed {c13.SEED}, block "
            f"{c13.HEADLINE_BLOCK} day(s). Specified in c16_preregistration.json "
            "before the holdout was unsealed."
        ),
    )
    print(f"appended {report.n_rows_appended:,} rows as run {report.run_id} "
          f"({report.n_rows_before:,} -> {report.n_rows_before + report.n_rows_appended:,})")
    verification = verify_append_only()
    print(f"verify_append_only: {verification}")
    return 0


# ---------------------------------------------------------------------------
# Phase: evaluate — all four, once, whole
# ---------------------------------------------------------------------------


def evaluate(args: argparse.Namespace) -> int:
    prereg = load_preregistration()
    zone_keys = args.zones or list(load_zones())
    unknown = [z for z in zone_keys if z not in load_zones()]
    if unknown:
        raise HoldoutRunError(f"unknown zone key(s): {unknown}")
    year = args.year
    if year == HOLDOUT_YEAR and sorted(zone_keys) != sorted(load_zones()):
        raise HoldoutRunError(
            "the holdout is evaluated whole or not at all: --zones may not narrow "
            "the pre-registered nine. A cycle that evaluated three zones and "
            "stopped would have spent the once-only evaluation on a third of the "
            "question."
        )

    gate = evaluation_gate(prereg, year, zone_keys)
    ledger, entry = open_ledger_entry(year, prereg)
    entry["gate"] = {
        "blockers_standing": gate["preflight"]["blockers_standing"],
        "library_fingerprint": gate["preflight"]["provenance"]["library_fingerprint_live"],
        "config_hash": gate["preflight"]["provenance"]["config_hash_live"],
    }
    write_ledger(ledger)

    print(f"\n=== C17 evaluation of {year} — compute, dispatch, analyse, ingest ===",
          flush=True)
    rc_compute = compute(args)
    mark_phase(ledger, entry, "compute")
    rc_dispatch = dispatch(args)
    mark_phase(ledger, entry, "dispatch")
    rc_analyse = analyse(args)
    mark_phase(ledger, entry, "analyse")
    rc_ingest = ingest(args)
    mark_phase(ledger, entry, "ingest")

    entry["status"] = "completed"
    entry["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    entry["invariant_flags"] = rc_dispatch
    entry["artefacts"] = {
        "metrics": metrics_path(year).name,
        "intervals": intervals_path(year).name,
        "report": evaluation_report_path(year).name,
        "invariant_flags": invariant_flags_path(year).name,
    }
    write_ledger(ledger)
    print(f"\nevaluation of {year} complete at {entry['finished_at_utc']}; "
          f"ledger {RUN_LEDGER} records it as the "
          f"{'ONE pre-registered holdout evaluation' if year == HOLDOUT_YEAR else 'rehearsal'}.",
          flush=True)
    # A non-zero dispatch return means an invariant flag, which is a FLAG for
    # PROGRESS.md rather than a failure of the evaluation; it is surfaced in the
    # exit code so the cycle cannot miss it.
    return max(rc_compute, rc_dispatch, rc_analyse, rc_ingest)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.phase == "preflight":
        return preflight(args)
    if args.phase == "compute":
        return compute(args)
    if args.phase == "dispatch":
        return dispatch(args)
    if args.phase == "analyse":
        return analyse(args)
    if args.phase == "ingest":
        return ingest(args)
    if args.phase == "evaluate":
        return evaluate(args)
    raise PreflightError(f"unknown phase {args.phase!r}")


if __name__ == "__main__":
    raise SystemExit(main())
