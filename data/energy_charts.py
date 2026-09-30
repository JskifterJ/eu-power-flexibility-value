"""Energy-Charts day-ahead price client, with a fetch-once local cache.

Energy-Charts (Fraunhofer ISE, ``api.energy-charts.info``) is the key-free
critical path for day-ahead prices in all nine zones — see PLAN.md. Data is
CC BY 4.0 and must be attributed.

Three standing rules from CLAUDE.md are implemented here rather than trusted to
the caller:

* **Never re-download cached data.** :func:`fetch_year` returns the cached path
  untouched if the file already exists. There is deliberately no ``--force``
  flag: refetching is a human act (delete the file on purpose).
* **A 404 / empty / unexpected response is a FLAG, not a puzzle.** Anything the
  documented schema does not cover raises :class:`UnexpectedResponse`. Nothing
  is guessed, no alternate endpoint is tried, nothing is swallowed by a bare
  ``except``. Retries cover transport errors and 5xx/429 only.
* **UTC internally.** The API returns ``unix_seconds`` (UTC epoch), which is
  parsed straight to a tz-aware UTC index. No local-time arithmetic happens
  anywhere in this module.

Request window convention: a year ``Y`` is requested as
``start=Y-01-01&end=Y-12-31`` and the parsed result is then truncated to
``[Y-01-01T00:00Z, Y+1-01-01T00:00Z)``. The request deliberately never names a
date outside ``Y`` — that keeps the sealed-holdout guard simple and means a
fetch of 2024 cannot ask the API for 2025. Whether the API treats ``end`` as
inclusive is *not* assumed: the manifest reports expected-vs-actual row counts
and the last timestamp, so a mismatch shows up at Checkpoint A instead of
being silently filled.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from data.config import REPO_ROOT, Zone, load_data_config, load_zones
from data.holdout import assert_not_sealed

PRICE_COLUMN = "price_eur_mwh"
EXPECTED_UNIT = "EUR / MWh"


class UnexpectedResponse(RuntimeError):
    """The API answered, but not with the documented price payload. A FLAG."""


class FetchFailed(RuntimeError):
    """The request could not be completed after the configured retries. A FLAG."""


# ---------------------------------------------------------------------------
# Cache layout
# ---------------------------------------------------------------------------


def cache_dir(config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_data_config()
    return REPO_ROOT / cfg["sources"]["energy_charts"]["cache_dir"]


def cache_path(zone_key: str, year: int, config: dict[str, Any] | None = None) -> Path:
    """Where the raw JSON for one (zone, year) lives. Gitignored on purpose."""
    return cache_dir(config) / zone_key / f"{year}.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Response validation and parsing
# ---------------------------------------------------------------------------


def validate_payload(payload: Any, context: str) -> dict[str, Any]:
    """Check a decoded response against the documented schema, or raise.

    Documented shape (``GET /price``)::

        {"unix_seconds": [int, ...], "price": [float|None, ...],
         "unit": "EUR / MWh", "deprecated": bool, "license_info": "..."}
    """
    if not isinstance(payload, dict):
        raise UnexpectedResponse(
            f"{context}: response decoded to {type(payload).__name__}, expected an object"
        )
    if not payload:
        raise UnexpectedResponse(f"{context}: response was an empty object")

    missing = [k for k in ("unix_seconds", "price") if k not in payload]
    if missing:
        raise UnexpectedResponse(
            f"{context}: response is missing {missing}; keys present: {sorted(payload)}"
        )

    seconds, prices = payload["unix_seconds"], payload["price"]
    if not isinstance(seconds, list) or not isinstance(prices, list):
        raise UnexpectedResponse(
            f"{context}: 'unix_seconds'/'price' are "
            f"{type(seconds).__name__}/{type(prices).__name__}, expected lists"
        )
    if not seconds:
        raise UnexpectedResponse(f"{context}: 'unix_seconds' is empty (no data returned)")
    if len(seconds) != len(prices):
        raise UnexpectedResponse(
            f"{context}: length mismatch — {len(seconds)} timestamps vs {len(prices)} prices"
        )
    if not all(isinstance(s, int) and not isinstance(s, bool) for s in seconds):
        raise UnexpectedResponse(f"{context}: 'unix_seconds' contains non-integer entries")
    if any(b - a <= 0 for a, b in zip(seconds, seconds[1:])):
        raise UnexpectedResponse(f"{context}: 'unix_seconds' is not strictly increasing")
    for value in prices:
        if value is not None and not isinstance(value, (int, float)):
            raise UnexpectedResponse(
                f"{context}: 'price' contains a {type(value).__name__} entry"
            )
    if payload.get("deprecated"):
        raise UnexpectedResponse(f"{context}: API marked this response 'deprecated': true")
    unit = payload.get("unit")
    if unit is not None and str(unit).replace(" ", "") != EXPECTED_UNIT.replace(" ", ""):
        raise UnexpectedResponse(
            f"{context}: unexpected unit {unit!r}, expected {EXPECTED_UNIT!r}"
        )
    return payload


def parse_payload(payload: dict[str, Any], context: str) -> pd.DataFrame:
    """Decoded payload -> UTC-indexed price frame, with **no** windowing applied.

    This is the whole of what the source returned. Callers that want one UTC
    calendar year use :func:`payload_to_frame`; callers stitching a continuous
    multi-year series (see :mod:`data.prices`) need the untruncated form,
    because the final UTC hour of year ``Y`` is only ever present in file
    ``Y+1`` — see the request-window convention in ``docs/data_layer.md``.
    """
    validate_payload(payload, context)
    index = pd.to_datetime(payload["unix_seconds"], unit="s", utc=True)
    frame = pd.DataFrame({PRICE_COLUMN: pd.Series(payload["price"], dtype="float64")})
    frame.index = pd.DatetimeIndex(index, name="timestamp_utc")
    frame.attrs["unit"] = payload.get("unit", EXPECTED_UNIT)
    frame.attrs["license_info"] = payload.get("license_info", "")
    return frame


def payload_to_frame(payload: dict[str, Any], year: int, context: str) -> pd.DataFrame:
    """Decoded payload -> UTC-indexed frame truncated to calendar year ``year``.

    Points outside the year are dropped by *timestamp*, never by value, and the
    count of dropped points is returned on ``frame.attrs['n_out_of_window']``.
    """
    frame = parse_payload(payload, context)

    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    in_window = (frame.index >= start) & (frame.index < end)
    trimmed = frame.loc[in_window]
    trimmed.attrs["n_out_of_window"] = int((~in_window).sum())
    trimmed.attrs["unit"] = payload.get("unit", EXPECTED_UNIT)
    trimmed.attrs["license_info"] = payload.get("license_info", "")
    if trimmed.empty:
        raise UnexpectedResponse(
            f"{context}: no returned timestamps fall inside {year} "
            f"(first={frame.index[0]}, last={frame.index[-1]})"
        )
    return trimmed


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def price_request(zone: Zone, year: int, config: dict[str, Any] | None = None) -> tuple[str, dict]:
    """The (url, params) for one (zone, year). Never names a date outside ``year``."""
    cfg = config or load_data_config()
    source = cfg["sources"]["energy_charts"]
    url = source["base_url"].rstrip("/") + source["price_endpoint"]
    params = {
        "bzn": zone.bzn,
        "start": f"{year}-01-01",
        "end": f"{year}-12-31",
    }
    return url, params


def fetch_year(
    zone_key: str,
    year: int,
    config: dict[str, Any] | None = None,
    session: requests.Session | None = None,
    sleep_after: bool = True,
) -> tuple[Path, bool]:
    """Fetch one (zone, year) of day-ahead prices into the cache.

    Returns ``(path, downloaded)``. ``downloaded`` is False when the cache
    already held the file, in which case no request is made at all.
    """
    cfg = config or load_data_config()
    assert_not_sealed(year, f"fetch Energy-Charts prices for {zone_key} {year}")

    zone = load_zones()[zone_key]
    path = cache_path(zone_key, year, cfg)
    if path.exists():
        return path, False

    url, params = price_request(zone, year, cfg)
    context = f"energy-charts /price {zone.bzn} {year}"
    request_cfg = cfg["sources"]["energy_charts"]["request"]
    backoffs = list(request_cfg.get("retry_backoff_seconds", [5, 15, 45]))
    max_retries = int(request_cfg.get("max_retries", 3))
    http = session or requests.Session()

    last_transient: str | None = None
    for attempt in range(max_retries):
        try:
            response = http.get(url, params=params, timeout=request_cfg["timeout_seconds"])
        except requests.RequestException as exc:  # transport-level only
            last_transient = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise UnexpectedResponse(
                        f"{context}: HTTP 200 but body is not JSON ({exc}); "
                        f"first 200 bytes: {response.text[:200]!r}"
                    ) from exc
                # Validate (and window-check) before anything touches the disk,
                # so the cache never holds a payload we would not accept.
                validate_payload(payload, context)
                payload_to_frame(payload, year, context)
                path.parent.mkdir(parents=True, exist_ok=True)
                meta = {
                    "_fetch_meta": {
                        "source": "energy-charts",
                        "url": response.url,
                        "zone_key": zone_key,
                        "bzn": zone.bzn,
                        "year": year,
                        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                        "http_status": response.status_code,
                        "licence": cfg["sources"]["energy_charts"]["licence"],
                        "attribution": cfg["sources"]["energy_charts"]["attribution"],
                    }
                }
                with path.open("w", encoding="utf-8") as fh:
                    json.dump({**meta, **payload}, fh)
                if sleep_after:
                    time.sleep(float(request_cfg.get("sleep_between_requests_seconds", 2.0)))
                return path, True

            if response.status_code in (429,) or 500 <= response.status_code < 600:
                last_transient = f"HTTP {response.status_code}"
            else:
                # 404 and every other 4xx: a FLAG. Do not guess another endpoint.
                raise UnexpectedResponse(
                    f"{context}: HTTP {response.status_code} for {response.url} — "
                    f"flag this in PROGRESS.md rather than trying alternatives. "
                    f"First 200 bytes: {response.text[:200]!r}"
                )

        if attempt < max_retries - 1:
            time.sleep(backoffs[min(attempt, len(backoffs) - 1)])

    raise FetchFailed(
        f"{context}: giving up after {max_retries} attempts; last error: {last_transient}"
    )


def read_cached_year(
    zone_key: str, year: int, config: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Load one cached (zone, year) file as a UTC-indexed price frame."""
    assert_not_sealed(year, f"load cached Energy-Charts prices for {zone_key} {year}")
    path = cache_path(zone_key, year, config)
    if not path.exists():
        raise FileNotFoundError(f"no cached Energy-Charts price file at {path}")
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    frame = payload_to_frame(payload, year, f"cached {path}")
    frame.attrs["cache_path"] = str(path)
    frame.attrs["fetch_meta"] = payload.get("_fetch_meta", {})
    return frame


def cached_years(zone_key: str, config: dict[str, Any] | None = None) -> list[int]:
    """Years present in the cache for a zone, ascending."""
    directory = cache_dir(config) / zone_key
    if not directory.exists():
        return []
    years = []
    for path in directory.glob("*.json"):
        try:
            years.append(int(path.stem))
        except ValueError:
            continue
    return sorted(years)
