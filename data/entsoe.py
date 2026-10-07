"""ENTSO-E Transparency Platform client for the Tier-A exogenous forecasts.

Two documents, both day-ahead (``processType`` A01), per PLAN.md C7:

* **A65 — Art. 6.1.B day-ahead total load forecast.** ``leakage_status: safe``:
  published at latest 2h before day-ahead gate closure, so the archived vintage
  is information a bidder genuinely held.
* **A69 — Art. 14.1.D day-ahead wind and solar generation forecast.**
  ``leakage_status: FLAGGED``: published at 18:00 on D-1, *after* gate closure
  for delivery day D, and revised intraday. The archived vintage is therefore
  **not** what a bidder had. This module fetches it because C8 needs it for the
  mandatory degradation sensitivity (as-published vs persistence-degraded); it
  carries the flag with it so no later cycle can forget.

The same three standing rules as :mod:`data.energy_charts` are implemented here
rather than trusted to the caller, plus two this source adds:

* **Never re-download cached data.** :func:`fetch_year` returns the cached path
  untouched if it exists. No ``--force`` flag: refetching is a human act.
  ENTSO-E throttles abusive tokens (CLAUDE.md), so this matters more here.
* **A 404 / Acknowledgement / unexpected response is a FLAG, not a puzzle.** The
  platform answers a malformed or out-of-range request with HTTP 400 and an
  ``Acknowledgement_MarketDocument`` carrying a ``Reason`` code — never with an
  error that looks like data. Any such response raises
  :class:`UnexpectedResponse` with the reason code and text. Nothing is guessed,
  no alternate document type or domain is tried.
* **UTC internally.** ENTSO-E stamps every ``timeInterval`` in UTC and this
  module keeps it that way. Positions are converted to timestamps by
  ``start + (position - 1) * resolution``; no local-time arithmetic happens here.
* **The security token never reaches disk, a log line or an exception.** Every
  string that could carry it goes through :func:`redact` first. In particular
  the cached provenance records a URL with ``securityToken=<REDACTED>``, unlike
  :mod:`data.energy_charts` which can safely store the real (key-free) URL.
* **A sealed year can never arrive by the back door.** ENTSO-E's ``periodEnd``
  is the *exclusive* end of the window, so fetching calendar year ``Y`` must
  name the instant ``(Y+1)-01-01T00:00Z`` — the only spelling that returns the
  year's last interval (verified in C7: an end of ``Y-12-31T23:00`` returns 92
  of 96 quarter-hours for that day). Naming that boundary is not an observation
  of year ``Y+1``, but rather than rely on that argument,
  :func:`parse_document` asserts positively that **no returned timestamp falls
  in a sealed year** — so if the platform ever did return a point past the
  boundary while fetching 2024, it raises instead of caching it.

Curve types, which is the thing that would silently corrupt this series
-----------------------------------------------------------------------
Every response observed in C7 is ``curveType A03`` — a *variable-sized block*
curve. Positions are **sparse**: an omitted position means "the previous
point's value still holds". One real example, DE-LU solar day-ahead for
2024-01-01 at PT15M::

    <Point><position>1</position><quantity>0</quantity></Point>
    <Point><position>29</position><quantity>52.58</quantity></Point>
    ...

Positions 2-28 are absent and mean *zero* (the value carried from position 1),
not *missing*. Parsing position-by-row would yield a 26-row "day" full of
holes; parsing it as a dense index would shift every value. :func:`expand_points`
implements the block semantics, and the C7 tests pin it against a
hand-computed sparse curve. ``A01`` (fixed-size sequence, every position
present) is also accepted; anything else is a FLAG.

Summing psrTypes, and the one place this source is genuinely ragged
------------------------------------------------------------------
``wind_forecast_da_mw`` is ``B18 + B19`` (offshore + onshore). Where only
*some* components cover an interval the sum is **NaN**, never a partial total:
treating an absent component as zero would understate wind by that whole fleet.
C7 found this live in DE-LU 2023 — on 2023-10-28 the publication for onshore
wind and solar splits around a missing ``22:00Z-23:00Z`` while offshore wind
runs straight through, that instant being 2023-10-29 00:00 CEST, the first hour
of the 25-hour local DST day. Those intervals are counted on
``frame.attrs['partial_psr_intervals']`` and surfaced by the exogenous manifest
and :mod:`data.exog_contracts`, because a gap that is reported is a known
limitation and a gap that is filled is a modelling bug that looks like clean
data. Overlapping Periods that *disagree* still raise — that is a contradiction,
not a gap.

The one exception is decided by the payload, not by the zone: a component that
is **identically zero wherever it is published** is not a fleet, so its absence
contributes zero. NO2 is the live case — offshore wind B18 appears for 48 hours
of 2022 and 192 of 2024, is absent from 2023, and is ``0.0`` at every published
point. Without the exception a stray all-zero stub would wipe out the wind
feature for a whole Tier-A zone; with it, DE-LU's absent *onshore* wind still
goes to NaN, because that component is worth tens of GW. Which components the
test caught is recorded on ``frame.attrs['zero_components']``.

Sub-hourly input is normal here and is **not** aggregated by this module: DE-LU
and ES publish both documents at PT15M, NO2 at PT60M. Aggregation to the hourly
market time unit is :mod:`data.aggregate`'s one documented method, applied by
:mod:`data.exogenous`, so the raw cache keeps native resolution.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from data.config import REPO_ROOT, Zone, load_data_config, load_zones
from data.holdout import assert_not_sealed, sealed_years

GL_NAMESPACE = "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"
NS = {"ns": GL_NAMESPACE}

RESOLUTION_SECONDS = {
    "PT15M": 900,
    "PT30M": 1800,
    "PT60M": 3600,
    "PT1H": 3600,
}

REDACTION = "<REDACTED>"


class UnexpectedResponse(RuntimeError):
    """The platform answered, but not with the documented payload. A FLAG."""


class FetchFailed(RuntimeError):
    """The request could not be completed after the configured retries. A FLAG."""


class MissingCredential(RuntimeError):
    """``ENTSOE_API_KEY`` is not set. Per CLAUDE.md a FLAG, not a hard stop."""


# ---------------------------------------------------------------------------
# Token hygiene
# ---------------------------------------------------------------------------


def redact(text: str, token: str | None = None) -> str:
    """Remove the security token from any string before it is stored or printed.

    Both the literal token (when known) and any ``securityToken=...`` query
    parameter are replaced, so a URL built by ``requests`` and a message quoted
    from the platform are both safe. Called on *every* path that writes a
    provenance record, prints a line or raises.
    """
    out = str(text)
    if token:
        out = out.replace(token, REDACTION)
    return re.sub(r"(securityToken=)[^&\s\"']+", r"\1" + REDACTION, out)


def api_token(config: dict[str, Any] | None = None) -> str:
    """The security token from the environment, or raise :class:`MissingCredential`.

    The value is returned for immediate use in a request and is never logged,
    stored, or included in an exception message.
    """
    cfg = config or load_data_config()
    var = cfg["sources"]["entsoe"]["key_env_var"]
    token = os.environ.get(var)
    if not token:
        raise MissingCredential(
            f"{var} is not set in this environment. Per CLAUDE.md: flag this in "
            f"PROGRESS.md and continue with Tier-B / Energy-Charts-only work "
            f"rather than blocking the cycle."
        )
    return token


def api_key_is_set(config: dict[str, Any] | None = None) -> bool:
    """Whether the token is present. Tests presence only — never reads the value."""
    cfg = config or load_data_config()
    return bool(os.environ.get(cfg["sources"]["entsoe"]["key_env_var"]))


# ---------------------------------------------------------------------------
# Document specs (config-driven)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesSpec:
    """One output column, and the psrTypes that roll up into it."""

    name: str
    psr_types: tuple[str, ...]
    non_negative: bool = True


@dataclass(frozen=True)
class EntsoeDocument:
    """One ENTSO-E document type this project knows how to read."""

    key: str
    document_type: str
    process_type: str
    domain_param: str
    title: str
    leakage_status: str
    leakage_note: str
    expected_business_types: tuple[str, ...]
    series: tuple[SeriesSpec, ...]

    @property
    def column_names(self) -> list[str]:
        return [s.name for s in self.series]

    @property
    def psr_to_series(self) -> dict[str, str]:
        """``{psrType: column name}``. Empty for a document with no MktPSRType."""
        return {psr: s.name for s in self.series for psr in s.psr_types}

    @property
    def carries_psr_type(self) -> bool:
        return any(s.psr_types for s in self.series)


def load_documents(config: dict[str, Any] | None = None) -> dict[str, EntsoeDocument]:
    """``{document_key: EntsoeDocument}`` from ``config/data.yaml``."""
    cfg = config or load_data_config()
    raw = cfg["sources"]["entsoe"].get("documents")
    if not isinstance(raw, dict) or not raw:
        raise UnexpectedResponse(
            "data.yaml sources.entsoe has no non-empty 'documents' mapping"
        )
    out: dict[str, EntsoeDocument] = {}
    for key, spec in raw.items():
        series = tuple(
            SeriesSpec(
                name=name,
                psr_types=tuple(sspec.get("psr_types") or ()),
                non_negative=bool(sspec.get("non_negative", True)),
            )
            for name, sspec in (spec.get("series") or {}).items()
        )
        if not series:
            raise UnexpectedResponse(f"entsoe document {key!r} declares no series")
        mixed = {bool(s.psr_types) for s in series}
        if len(mixed) > 1:
            raise UnexpectedResponse(
                f"entsoe document {key!r} mixes psrType-carrying and "
                f"psrType-free series; one document is one or the other"
            )
        out[key] = EntsoeDocument(
            key=key,
            document_type=str(spec["document_type"]),
            process_type=str(spec["process_type"]),
            domain_param=str(spec["domain_param"]),
            title=str(spec.get("title", key)),
            leakage_status=str(spec.get("leakage_status", "UNKNOWN")),
            leakage_note=str(spec.get("leakage_note", "")).strip(),
            expected_business_types=tuple(spec.get("expected_business_types") or ()),
            series=series,
        )
    return out


def document_spec(
    document_key: str, config: dict[str, Any] | None = None
) -> EntsoeDocument:
    docs = load_documents(config)
    if document_key not in docs:
        raise UnexpectedResponse(
            f"unknown entsoe document key {document_key!r}; known: {sorted(docs)}"
        )
    return docs[document_key]


def exogenous_years(config: dict[str, Any] | None = None) -> list[int]:
    """Fetchable years for exogenous data: ``fetch_years`` from 2022 onward.

    2019-2021 are excluded by PLAN.md (no archived D-1 forecast vintage), not by
    the API — which answers happily for them. The bound lives in config and is
    applied here so no caller can quietly widen it.
    """
    cfg = config or load_data_config()
    floor = int(cfg["sources"]["entsoe"]["exogenous_available_from_year"])
    return [int(y) for y in cfg["fetch_years"] if int(y) >= floor]


def all_series_names(config: dict[str, Any] | None = None) -> list[str]:
    return [s.name for doc in load_documents(config).values() for s in doc.series]


def series_owner(
    series_name: str, config: dict[str, Any] | None = None
) -> EntsoeDocument:
    """The document a given output column comes from."""
    for doc in load_documents(config).values():
        if series_name in doc.column_names:
            return doc
    raise UnexpectedResponse(
        f"unknown exogenous series {series_name!r}; known: {all_series_names(config)}"
    )


# ---------------------------------------------------------------------------
# Cache layout
# ---------------------------------------------------------------------------


def cache_dir(config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_data_config()
    return REPO_ROOT / cfg["sources"]["entsoe"]["cache_dir"]


def cache_path(
    zone_key: str, document_key: str, year: int, config: dict[str, Any] | None = None
) -> Path:
    """Raw XML for one (zone, document, year). Gzipped — a year of DE-LU A69 is ~13 MB."""
    return cache_dir(config) / document_key / zone_key / f"{year}.xml.gz"


def meta_path(
    zone_key: str, document_key: str, year: int, config: dict[str, Any] | None = None
) -> Path:
    """Provenance sidecar for one cached document. Holds a *redacted* URL."""
    return cache_path(zone_key, document_key, year, config).with_suffix(".meta.json")


def cached_years(
    zone_key: str, document_key: str, config: dict[str, Any] | None = None
) -> list[int]:
    directory = cache_dir(config) / document_key / zone_key
    if not directory.exists():
        return []
    years = []
    for path in directory.glob("*.xml.gz"):
        try:
            years.append(int(path.name.split(".", 1)[0]))
        except ValueError:
            continue
    return sorted(years)


# ---------------------------------------------------------------------------
# Response validation and parsing
# ---------------------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def acknowledgement_reason(xml_bytes: bytes) -> tuple[str, str] | None:
    """``(code, text)`` if the payload is an ``Acknowledgement_MarketDocument``.

    This is how ENTSO-E says "no", including for an out-of-range window, an
    unknown domain, a bad token, or simply no matching data. CLAUDE.md names it
    explicitly as a FLAG, so it is detected here and never mistaken for data.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    if "Acknowledgement" not in _strip_ns(root.tag):
        return None
    code = text = ""
    for reason in root.iter():
        name = _strip_ns(reason.tag)
        if name == "code" and not code:
            code = (reason.text or "").strip()
        elif name == "text" and not text:
            text = (reason.text or "").strip()
    return code or "?", text or "(no reason text)"


def resolution_seconds(resolution: str, context: str) -> int:
    key = str(resolution).strip().upper()
    if key not in RESOLUTION_SECONDS:
        raise UnexpectedResponse(
            f"{context}: unsupported resolution {resolution!r}; known: "
            f"{sorted(RESOLUTION_SECONDS)}"
        )
    return RESOLUTION_SECONDS[key]


def expand_points(
    positions: list[int],
    quantities: list[float],
    n_slots: int,
    curve_type: str,
    context: str,
) -> list[float]:
    """Positions/quantities -> a dense list of ``n_slots`` values.

    ``A03`` (variable-sized block): an omitted position carries the previous
    point's value forward. ``A01`` (fixed-size sequence): every position must be
    present. Both require position 1 — without it the leading block's value is
    undefined, and assuming anything there would invent data.
    """
    if not positions:
        raise UnexpectedResponse(f"{context}: Period contains no Point elements")
    if len(positions) != len(quantities):
        raise UnexpectedResponse(
            f"{context}: {len(positions)} positions vs {len(quantities)} quantities"
        )
    if any(b <= a for a, b in zip(positions, positions[1:])):
        raise UnexpectedResponse(
            f"{context}: positions are not strictly increasing ({positions[:10]}...)"
        )
    if positions[0] != 1:
        raise UnexpectedResponse(
            f"{context}: Period starts at position {positions[0]}, not 1 — the "
            f"leading block's value is undefined and will not be guessed"
        )
    if positions[-1] > n_slots:
        raise UnexpectedResponse(
            f"{context}: position {positions[-1]} exceeds the {n_slots} slot(s) the "
            f"Period's timeInterval and resolution allow"
        )

    if curve_type == "A01":
        if len(positions) != n_slots:
            raise UnexpectedResponse(
                f"{context}: curveType A01 is a fixed-size sequence but holds "
                f"{len(positions)} of {n_slots} position(s) — missing "
                f"{n_slots - len(positions)}"
            )
        return list(quantities)

    if curve_type != "A03":
        raise UnexpectedResponse(f"{context}: unsupported curveType {curve_type!r}")

    dense: list[float] = [float("nan")] * n_slots
    for index, (position, quantity) in enumerate(zip(positions, quantities)):
        stop = positions[index + 1] - 1 if index + 1 < len(positions) else n_slots
        for slot in range(position - 1, stop):
            dense[slot] = quantity
    return dense


def _series_frame(
    period: ET.Element, curve_type: str, context: str
) -> tuple[pd.DatetimeIndex, list[float], int]:
    """One ``<Period>`` -> (UTC index, dense values, resolution seconds)."""
    start_text = period.findtext("ns:timeInterval/ns:start", namespaces=NS)
    end_text = period.findtext("ns:timeInterval/ns:end", namespaces=NS)
    if not start_text or not end_text:
        raise UnexpectedResponse(f"{context}: Period has no timeInterval start/end")
    start = pd.Timestamp(start_text)
    end = pd.Timestamp(end_text)
    if start.tz is None or end.tz is None:
        raise UnexpectedResponse(
            f"{context}: Period timeInterval {start_text}..{end_text} is not "
            f"UTC-stamped — refusing to assume a timezone"
        )
    start, end = start.tz_convert("UTC"), end.tz_convert("UTC")
    if end <= start:
        raise UnexpectedResponse(
            f"{context}: Period end {end_text} does not follow start {start_text}"
        )

    seconds = resolution_seconds(
        period.findtext("ns:resolution", default="", namespaces=NS), context
    )
    span = int((end - start).total_seconds())
    if span % seconds:
        raise UnexpectedResponse(
            f"{context}: Period spans {span}s, not a whole multiple of the "
            f"{seconds}s resolution"
        )
    n_slots = span // seconds

    positions, quantities = [], []
    for point in period.findall("ns:Point", NS):
        position_text = point.findtext("ns:position", namespaces=NS)
        quantity_text = point.findtext("ns:quantity", namespaces=NS)
        if position_text is None or quantity_text is None:
            raise UnexpectedResponse(
                f"{context}: Point is missing position and/or quantity"
            )
        try:
            positions.append(int(position_text))
            quantities.append(float(quantity_text))
        except ValueError as exc:
            raise UnexpectedResponse(
                f"{context}: Point position/quantity not numeric "
                f"({position_text!r}/{quantity_text!r})"
            ) from exc

    dense = expand_points(positions, quantities, n_slots, curve_type, context)
    index = pd.date_range(start=start, periods=n_slots, freq=pd.Timedelta(seconds=seconds))
    return pd.DatetimeIndex(index, name="timestamp_utc"), dense, seconds


def parse_document(
    xml_bytes: bytes,
    document_key: str,
    context: str,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Raw XML -> UTC-indexed frame, one column per configured series.

    Native resolution is preserved; nothing is aggregated or reindexed here.
    An ``Acknowledgement_MarketDocument``, an unexpected document/process type,
    an unexpected unit, an unknown psrType and an unsupported curveType are all
    :class:`UnexpectedResponse` — i.e. a FLAG. Sealed-holdout timestamps are
    rejected positively, so the exclusive-``periodEnd`` argument in this
    module's docstring is checked rather than assumed.
    """
    cfg = config or load_data_config()
    spec = document_spec(document_key, cfg)
    expected_unit = str(cfg["sources"]["entsoe"]["expected_unit"])
    supported = {str(c) for c in cfg["sources"]["entsoe"]["supported_curve_types"]}

    ack = acknowledgement_reason(xml_bytes)
    if ack is not None:
        code, text = ack
        raise UnexpectedResponse(
            f"{context}: ENTSO-E returned an Acknowledgement_MarketDocument "
            f"(Reason code {code}): {text} — flag this in PROGRESS.md rather "
            f"than trying another document type, domain or window."
        )

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise UnexpectedResponse(f"{context}: body is not well-formed XML ({exc})") from exc

    if _strip_ns(root.tag) != "GL_MarketDocument":
        raise UnexpectedResponse(
            f"{context}: root element is {_strip_ns(root.tag)!r}, expected "
            f"'GL_MarketDocument'"
        )
    got_type = root.findtext("ns:type", default="", namespaces=NS)
    got_process = root.findtext("ns:process.processType", default="", namespaces=NS)
    if got_type != spec.document_type:
        raise UnexpectedResponse(
            f"{context}: document type is {got_type!r}, expected {spec.document_type!r}"
        )
    if got_process != spec.process_type:
        raise UnexpectedResponse(
            f"{context}: processType is {got_process!r}, expected "
            f"{spec.process_type!r} (day-ahead) — a different vintage would change "
            f"the leakage status of this feature"
        )

    time_series = root.findall("ns:TimeSeries", NS)
    if not time_series:
        raise UnexpectedResponse(
            f"{context}: GL_MarketDocument contains no TimeSeries (no data returned)"
        )

    # Collect per (column, psrType) so a duplicate timestamp *within* one
    # psrType is a defect, while B18 + B19 rolling up into one wind column is
    # the intended sum.
    parts: dict[tuple[str, str], list[pd.Series]] = {}
    interval_parts: list[pd.Series] = []
    resolutions: set[int] = set()
    psr_map = spec.psr_to_series

    for series_element in time_series:
        business = series_element.findtext("ns:businessType", default="", namespaces=NS)
        if spec.expected_business_types and business not in spec.expected_business_types:
            raise UnexpectedResponse(
                f"{context}: TimeSeries businessType {business!r} is not one of "
                f"{list(spec.expected_business_types)}"
            )
        unit = series_element.findtext(
            "ns:quantity_Measure_Unit.name", default="", namespaces=NS
        )
        if unit != expected_unit:
            raise UnexpectedResponse(
                f"{context}: quantity unit is {unit!r}, expected {expected_unit!r}"
            )
        curve_type = series_element.findtext("ns:curveType", default="", namespaces=NS)
        if curve_type not in supported:
            raise UnexpectedResponse(
                f"{context}: curveType {curve_type!r} is not supported "
                f"(known: {sorted(supported)}) — the block semantics of an "
                f"unknown curve type would silently corrupt the series"
            )

        psr = series_element.findtext(
            "ns:MktPSRType/ns:psrType", default="", namespaces=NS
        )
        if spec.carries_psr_type:
            if not psr:
                raise UnexpectedResponse(
                    f"{context}: TimeSeries has no MktPSRType/psrType, but "
                    f"{document_key!r} is a psrType-carrying document"
                )
            if psr not in psr_map:
                raise UnexpectedResponse(
                    f"{context}: psrType {psr!r} is not mapped to any series in "
                    f"config/data.yaml (known: {sorted(psr_map)}) — a new "
                    f"generation type in this document is a FLAG, not something "
                    f"to drop silently"
                )
            column = psr_map[psr]
        else:
            if psr:
                raise UnexpectedResponse(
                    f"{context}: TimeSeries carries psrType {psr!r}, but "
                    f"{document_key!r} declares no psrType series"
                )
            column = spec.series[0].name
            psr = "-"

        periods = series_element.findall("ns:Period", NS)
        if not periods:
            raise UnexpectedResponse(f"{context}: TimeSeries contains no Period")
        for period in periods:
            index, values, seconds = _series_frame(period, curve_type, context)
            resolutions.add(seconds)
            parts.setdefault((column, psr), []).append(
                pd.Series(values, index=index, dtype="float64")
            )
            # Each row's true interval length, taken from its own Period rather
            # than inferred from index spacing. A TSO can change resolution
            # mid-year (ES went PT60M -> PT15M on 2022-05-23), and a delta-based
            # guess cannot tell that change from a gap: the row before a
            # one-hour hole in a PT15M series has a 4500s forward delta. Hourly
            # aggregation in data/exogenous.py needs the real value.
            interval_parts.append(pd.Series(seconds, index=index, dtype="int64"))

    # One series per (column, psrType): concatenate its periods, reject overlap.
    per_psr: dict[tuple[str, str], pd.Series] = {}
    for key, chunks in parts.items():
        combined = pd.concat(chunks).sort_index()
        duplicated = combined.index.duplicated()
        if duplicated.any():
            first = combined.index[duplicated][0]
            raise UnexpectedResponse(
                f"{context}: {key[0]} psrType {key[1]} has "
                f"{int(duplicated.sum())} duplicate timestamp(s), first at "
                f"{first.isoformat()} — overlapping Periods are a FLAG, not "
                f"something to de-duplicate by guesswork"
            )
        per_psr[key] = combined

    # Roll psrTypes up into their configured columns by summation (wind =
    # offshore + onshore). Alignment is on the union of timestamps, and an
    # interval covered by only *some* components becomes **NaN**, never a
    # partial sum: treating an absent component as zero would understate the
    # total by that whole fleet.
    #
    # This is a real condition, not a hypothetical. DE-LU 2023 (found in C7):
    # on 2023-10-28 the German day-ahead publication for onshore wind (B19) and
    # solar (B16) splits into two Periods around a missing 22:00Z-23:00Z, while
    # offshore wind (B18) runs straight through — so wind has four quarter-hours
    # with B18 but no B19. That instant is 2023-10-29 00:00 CEST, the first hour
    # of the 25-hour local DST day: the publication for the long day starts an
    # hour late for two of the three psrTypes.
    #
    # Earlier in C7 this raised, which cost a whole training year for four
    # intervals. CLAUDE.md says to skip only the *dependent* work, and this
    # project's standing rule is that a gap stays a gap and gets reported
    # (:mod:`data.prices`) rather than filled. So the four intervals become NaN
    # and are counted on the frame's attrs, where the exogenous manifest and
    # :mod:`data.exog_contracts` both surface them to a human. NaN cannot be
    # mistaken for a real low-wind hour; zero could.
    # One exception, and it is decided by the data rather than by zone: a
    # component that is **identically zero wherever it is published** does not
    # exist as a fleet, so its absence really does contribute zero. NO2 is the
    # live case (found in C7): offshore wind B18 is published for just 48 hours
    # of 2022 and 192 of 2024, absent from 2023 altogether, and *every*
    # published value is 0.0 — Norway's NO2 has no offshore wind to forecast and
    # the TSO emits an occasional all-zero stub. Treating its absence as NaN
    # would wipe out the NO2 wind feature for a whole Tier-A zone on the
    # strength of a stub; treating DE-LU's absent onshore wind as zero would
    # understate wind by tens of GW. The all-zero test separates the two
    # honestly, is asserted against the payload rather than assumed, and is
    # recorded in ``attrs['zero_components']`` so a human can overrule it.
    columns: dict[str, pd.Series] = {}
    partial_psr: dict[str, list[str]] = {}
    zero_components: dict[str, list[str]] = {}
    for series_spec in spec.series:
        members = {k[1]: v for k, v in per_psr.items() if k[0] == series_spec.name}
        if not members:
            continue
        if len(members) == 1:
            columns[series_spec.name] = next(iter(members.values()))
            continue

        all_zero = {
            psr
            for psr, values in members.items()
            if len(values.dropna()) > 0 and bool((values.dropna() == 0).all())
        }
        if all_zero:
            zero_components[series_spec.name] = sorted(all_zero)

        frame = pd.concat(
            members.values(), axis=1, keys=list(members), sort=True
        )
        # An absent interval of an all-zero component is filled with the zero it
        # demonstrably is; an absent interval of a real component stays NaN.
        for psr in all_zero:
            frame[psr] = frame[psr].fillna(0.0)
        incomplete = frame.isna().any(axis=1)
        total = frame.sum(axis=1)
        total[incomplete] = float("nan")
        if incomplete.any():
            partial_psr[series_spec.name] = [
                t.isoformat() for t in frame.index[incomplete][:50]
            ]
        columns[series_spec.name] = total

    if not columns:
        raise UnexpectedResponse(
            f"{context}: no configured series found in the response "
            f"(expected {spec.column_names})"
        )

    frame = pd.DataFrame(columns).sort_index()
    frame.index.name = "timestamp_utc"

    # One interval length per output row. Components overlap heavily, so the
    # same timestamp appears in several parts; they must agree, because a row
    # that is 900s long for wind and 3600s long for solar would make "does this
    # hour tile exactly?" unanswerable.
    intervals = pd.concat(interval_parts) if interval_parts else pd.Series(dtype="int64")
    if not intervals.empty:
        disagreeing = intervals.groupby(level=0).nunique()
        clashes = disagreeing[disagreeing > 1]
        if len(clashes):
            raise UnexpectedResponse(
                f"{context}: {len(clashes)} timestamp(s) are published at two "
                f"different resolutions in the same document, first at "
                f"{clashes.index[0].isoformat()} — refusing to guess an interval "
                f"length"
            )
        intervals = intervals.groupby(level=0).first().reindex(frame.index)
        if intervals.isna().any():
            missing = frame.index[intervals.isna()]
            raise UnexpectedResponse(
                f"{context}: {len(missing)} output row(s) have no interval length, "
                f"first at {missing[0].isoformat()} — this is a parser bug, not a "
                f"source defect"
            )
    # Stored as a positionally-aligned tuple of ints, not a Series: pandas
    # compares every `attrs` value with `==` inside `concat`, and a Series or
    # ndarray there raises instead of answering.
    frame.attrs["interval_seconds"] = tuple(int(v) for v in intervals.to_numpy())

    sealed = sealed_years()
    if sealed:
        hit = sorted(set(int(y) for y in frame.index.year) & sealed)
        if hit:
            raise UnexpectedResponse(
                f"{context}: response contains timestamps in SEALED year(s) {hit}. "
                f"ENTSO-E's periodEnd is meant to be exclusive, so this must not "
                f"happen; refusing to parse or cache it. See CLAUDE.md and "
                f"data/holdout.py."
            )

    frame.attrs["unit"] = expected_unit
    frame.attrs["document_key"] = document_key
    frame.attrs["document_type"] = spec.document_type
    frame.attrs["process_type"] = spec.process_type
    frame.attrs["leakage_status"] = spec.leakage_status
    frame.attrs["resolutions_seconds"] = sorted(resolutions)
    frame.attrs["n_time_series"] = len(time_series)
    frame.attrs["psr_types_seen"] = sorted({k[1] for k in per_psr})
    # Intervals where a summed column had some but not all of its psrTypes, so
    # the value is NaN rather than a partial sum. Surfaced by the exogenous
    # manifest and contract report.
    frame.attrs["partial_psr_intervals"] = partial_psr
    frame.attrs["n_partial_psr_intervals"] = sum(len(v) for v in partial_psr.values())
    # Components that were identically zero wherever published, so their absent
    # intervals were filled with zero rather than left NaN. See above.
    frame.attrs["zero_components"] = zero_components
    return frame


def payload_to_frame(
    xml_bytes: bytes,
    document_key: str,
    year: int,
    context: str,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """:func:`parse_document`, truncated to UTC calendar year ``year``.

    Points outside the year are dropped by *timestamp*, never by value, and the
    count is reported on ``frame.attrs['n_out_of_window']``.
    """
    frame = parse_document(xml_bytes, document_key, context, config)
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    in_window = (frame.index >= start) & (frame.index < end)
    trimmed = frame.loc[in_window].copy()
    trimmed.attrs = dict(frame.attrs)
    trimmed.attrs["n_out_of_window"] = int((~in_window).sum())
    intervals = frame.attrs.get("interval_seconds")
    if intervals:
        trimmed.attrs["interval_seconds"] = tuple(
            v for v, keep in zip(intervals, in_window) if keep
        )
    if trimmed.empty:
        raise UnexpectedResponse(
            f"{context}: no returned timestamps fall inside {year} "
            f"(first={frame.index[0]}, last={frame.index[-1]})"
        )
    return trimmed


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def period_bounds(year: int) -> tuple[str, str]:
    """ENTSO-E ``periodStart``/``periodEnd`` (``yyyyMMddHHmm``, UTC) for a year.

    ``periodEnd`` is the platform's *exclusive* window end, so the full year
    requires naming ``(Y+1)-01-01T00:00Z``. See this module's docstring for why
    that is not a sealed-year read, and :func:`parse_document` for the assertion
    that checks it rather than trusting it.
    """
    return f"{year}0101" + "0000", f"{year + 1}0101" + "0000"


def document_request(
    zone: Zone, document_key: str, year: int, config: dict[str, Any] | None = None
) -> tuple[str, dict[str, str]]:
    """The (url, params) for one (zone, document, year), **without** the token.

    The token is added at request time only, so nothing that handles this dict
    — a log line, a test assertion, a cached provenance record — can leak it.
    """
    cfg = config or load_data_config()
    source = cfg["sources"]["entsoe"]
    spec = document_spec(document_key, cfg)
    if not zone.entsoe_domain:
        raise UnexpectedResponse(
            f"zone {zone.key!r} has no entsoe_domain in config/zones.yaml"
        )
    start, end = period_bounds(year)
    params = {
        "documentType": spec.document_type,
        "processType": spec.process_type,
        spec.domain_param: zone.entsoe_domain,
        "periodStart": start,
        "periodEnd": end,
    }
    return source["base_url"], params


def fetch_year(
    zone_key: str,
    document_key: str,
    year: int,
    config: dict[str, Any] | None = None,
    session: requests.Session | None = None,
    sleep_after: bool = True,
) -> tuple[Path, bool]:
    """Fetch one (zone, document, year) into the cache.

    Returns ``(path, downloaded)``; ``downloaded`` is False when the cache
    already held the file, in which case no request is made at all.
    """
    cfg = config or load_data_config()
    spec = document_spec(document_key, cfg)
    assert_not_sealed(year, f"fetch ENTSO-E {document_key} for {zone_key} {year}")

    allowed = exogenous_years(cfg)
    if year not in allowed:
        raise UnexpectedResponse(
            f"refusing to fetch ENTSO-E {document_key} for {year}: exogenous "
            f"features are declared available only for {allowed} "
            f"(config sources.entsoe.exogenous_available_from_year and "
            f"fetch_years). PLAN.md: no archived D-1 forecast vintage exists "
            f"before 2022."
        )

    zone = load_zones()[zone_key]
    path = cache_path(zone_key, document_key, year, cfg)
    if path.exists():
        return path, False

    token = api_token(cfg)
    url, params = document_request(zone, document_key, year, cfg)
    context = f"entsoe {spec.document_type}/{spec.process_type} {zone_key} {year}"
    request_cfg = cfg["sources"]["entsoe"]["request"]
    backoffs = list(request_cfg.get("retry_backoff_seconds", [5, 15, 45]))
    max_retries = int(request_cfg.get("max_retries", 3))
    http = session or requests.Session()

    last_transient: str | None = None
    for attempt in range(max_retries):
        try:
            response = http.get(
                url,
                params={**params, "securityToken": token},
                timeout=request_cfg["timeout_seconds"],
            )
        except requests.RequestException as exc:  # transport-level only
            last_transient = redact(f"{type(exc).__name__}: {exc}", token)
        else:
            body = response.content
            if response.status_code == 200:
                # Validate before anything touches the disk, so the cache can
                # never hold a payload we would not accept.
                frame = payload_to_frame(body, document_key, year, context, cfg)
                path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(path, "wb") as fh:
                    fh.write(body)
                meta = {
                    "source": "entsoe-transparency-platform",
                    "url_redacted": redact(response.url, token),
                    "zone_key": zone_key,
                    "entsoe_domain": zone.entsoe_domain,
                    "document_key": document_key,
                    "document_type": spec.document_type,
                    "process_type": spec.process_type,
                    "document_title": spec.title,
                    "leakage_status": spec.leakage_status,
                    "year": year,
                    "period_start": params["periodStart"],
                    "period_end": params["periodEnd"],
                    "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "http_status": response.status_code,
                    "raw_bytes": len(body),
                    "gzip_bytes": path.stat().st_size,
                    "n_rows_parsed": int(len(frame)),
                    "resolutions_seconds": frame.attrs.get("resolutions_seconds", []),
                    "licence": cfg["sources"]["entsoe"]["licence"],
                    "attribution": cfg["sources"]["entsoe"]["attribution"],
                }
                with meta_path(zone_key, document_key, year, cfg).open(
                    "w", encoding="utf-8"
                ) as fh:
                    json.dump(meta, fh, indent=2)
                    fh.write("\n")
                if sleep_after:
                    time.sleep(
                        float(request_cfg.get("sleep_between_requests_seconds", 3.0))
                    )
                return path, True

            if response.status_code in (429,) or 500 <= response.status_code < 600:
                last_transient = f"HTTP {response.status_code}"
            else:
                # 400 + Acknowledgement, 401 bad token, 404, every other 4xx:
                # a FLAG. Do not guess another document type, domain or window.
                ack = acknowledgement_reason(body)
                detail = (
                    f"Acknowledgement Reason code {ack[0]}: {ack[1]}"
                    if ack
                    else redact(response.text[:400], token)
                )
                raise UnexpectedResponse(
                    f"{context}: HTTP {response.status_code} — {detail}. Flag this "
                    f"in PROGRESS.md rather than trying alternatives."
                )

        if attempt < max_retries - 1:
            time.sleep(backoffs[min(attempt, len(backoffs) - 1)])

    raise FetchFailed(
        f"{context}: giving up after {max_retries} attempts; last error: "
        f"{last_transient}"
    )


def read_cached_year(
    zone_key: str,
    document_key: str,
    year: int,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Load one cached (zone, document, year) as a UTC-indexed frame."""
    cfg = config or load_data_config()
    assert_not_sealed(
        year, f"load cached ENTSO-E {document_key} for {zone_key} {year}"
    )
    path = cache_path(zone_key, document_key, year, cfg)
    if not path.exists():
        raise FileNotFoundError(f"no cached ENTSO-E document at {path}")
    with gzip.open(path, "rb") as fh:
        body = fh.read()
    frame = payload_to_frame(body, document_key, year, f"cached {path}", cfg)
    frame.attrs["cache_path"] = str(path)
    sidecar = meta_path(zone_key, document_key, year, cfg)
    if sidecar.exists():
        with sidecar.open("r", encoding="utf-8") as fh:
            frame.attrs["fetch_meta"] = json.load(fh)
    else:
        frame.attrs["fetch_meta"] = {}
    return frame
