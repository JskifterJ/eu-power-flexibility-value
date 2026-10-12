"""Loading and light validation of the YAML config under ``config/``.

Config is data, not code: nothing here computes anything about prices. The
point of this module is that every later cycle reads the same zone list, the
same date ranges and the same sealed-holdout declaration from one place, and
fails loudly if they are missing or malformed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

VALID_TIERS = ("A", "B")


class ConfigError(RuntimeError):
    """Raised when the committed config is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Zone:
    """One bidding zone."""

    key: str
    tier: str
    bzn: str
    local_tz: str
    entsoe_domain: str | None = None
    regime: str | None = None
    notes: str | None = None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    if not isinstance(loaded, dict):
        raise ConfigError(f"config file {path} did not parse to a mapping")
    return loaded


@lru_cache(maxsize=None)
def load_zones(config_dir: Path | None = None) -> dict[str, Zone]:
    """Return ``{zone_key: Zone}`` from ``config/zones.yaml``."""
    cfg = _read_yaml((config_dir or CONFIG_DIR) / "zones.yaml")
    raw = cfg.get("zones")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("zones.yaml has no non-empty 'zones' mapping")

    zones: dict[str, Zone] = {}
    for key, spec in raw.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"zone {key!r} is not a mapping")
        for required in ("tier", "bzn", "local_tz"):
            if not spec.get(required):
                raise ConfigError(f"zone {key!r} is missing required field {required!r}")
        if spec["tier"] not in VALID_TIERS:
            raise ConfigError(
                f"zone {key!r} has tier {spec['tier']!r}, expected one of {VALID_TIERS}"
            )
        zones[key] = Zone(
            key=key,
            tier=spec["tier"],
            bzn=spec["bzn"],
            local_tz=spec["local_tz"],
            entsoe_domain=spec.get("entsoe_domain"),
            regime=spec.get("regime"),
            notes=spec.get("notes"),
        )
    return zones


def raw_holdout_unseal_marker(config_dir: Path | None = None) -> str:
    """The unseal marker string, read directly from data.yaml.

    Deliberately bypasses load_data_config()'s validation, including its
    sealed/fetch_years-overlap check below. That check has to know the marker
    to decide whether an overlap is legitimate (holdout unsealed) or a defect
    (not yet), so retrieving the marker can never itself be gated behind that
    check passing — this function is the bootstrapping path out of that
    circularity. data/holdout.py's unseal_marker() calls this rather than
    load_data_config(), for the same reason.
    """
    cfg = _read_yaml((config_dir or CONFIG_DIR) / "data.yaml")
    if "holdout_unseal_marker" not in cfg:
        raise ConfigError("data.yaml is missing required key 'holdout_unseal_marker'")
    return str(cfg["holdout_unseal_marker"])


@lru_cache(maxsize=None)
def load_data_config(
    config_dir: Path | None = None, progress_path: Path | None = None
) -> dict[str, Any]:
    """Return the parsed ``config/data.yaml``, validated for the keys we rely on.

    ``progress_path`` is forwarded to the sealed/fetch_years-overlap check below
    (which PROGRESS.md to read for the unseal marker) and otherwise unused;
    every existing call site omits it and gets the real repo's PROGRESS.md, as
    before. It exists so a test can point at a synthetic PROGRESS.md instead of
    depending on this repo's real, now-permanently-unsealed one.
    """
    cfg = _read_yaml((config_dir or CONFIG_DIR) / "data.yaml")

    for required in ("splits", "fetch_years", "sources", "time", "holdout_unseal_marker"):
        if required not in cfg:
            raise ConfigError(f"data.yaml is missing required key {required!r}")

    holdout = cfg["splits"].get("holdout", {})
    if not holdout.get("sealed", False):
        raise ConfigError(
            "data.yaml declares splits.holdout.sealed as false. Unsealing is a "
            "human action at Checkpoint C, recorded in PROGRESS.md — not a config edit."
        )
    sealed_years = set(holdout.get("years") or [])
    overlap = sealed_years.intersection(cfg["fetch_years"])
    if overlap:
        # Checkpoint C (docs/checkpoint_c.md §4(b)) requires adding the holdout
        # year(s) to fetch_years once unsealed, because entsoe.exogenous_years()
        # derives from this list. splits.holdout.sealed/years stay permanently
        # "true"/[2025] by design (the check above) — they are the declaration
        # of what the holdout *is*, not whether it is currently sealed; that is
        # a PROGRESS.md fact, not a config fact. So an overlap is only a defect
        # when the holdout is NOT actually unsealed.
        #
        # This deliberately does NOT call data.holdout.holdout_is_unsealed():
        # that function gets the marker via unseal_marker(), and routing this
        # check back through load_data_config() for the marker would make
        # retrieving the marker depend on this very check having already
        # passed — see raw_holdout_unseal_marker()'s docstring. The marker
        # string is already sitting in `cfg`, parsed above, so it is read
        # directly instead. Kept in step with data/holdout.py's check by
        # test_data_config_and_holdout_module_agree_on_the_marker_check in
        # tests/test_c1_data_layer.py.
        marker = cfg["holdout_unseal_marker"]
        progress_file = progress_path or (REPO_ROOT / "PROGRESS.md")
        unsealed = progress_file.exists() and any(
            line.strip() == marker
            for line in progress_file.read_text(encoding="utf-8").splitlines()
        )
        if not unsealed:
            raise ConfigError(
                f"fetch_years overlaps the sealed holdout years {sorted(overlap)} "
                "and the holdout is not unsealed — refusing to run"
            )
    return cfg


@lru_cache(maxsize=None)
def load_battery_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed ``config/battery.yaml`` (C5 onwards).

    Only presence of the three top-level sections is checked here; the physical
    sanity of the numbers (positive power, efficiency in ``(0, 1]``, a known
    terminal mode) belongs to :class:`dispatch.battery.BatterySpec`, which is
    where a caller can actually act on it.
    """
    cfg = _read_yaml((config_dir or CONFIG_DIR) / "battery.yaml")
    for required in ("battery", "terminal", "solver"):
        if required not in cfg:
            raise ConfigError(f"battery.yaml is missing required key {required!r}")
    return cfg


@lru_cache(maxsize=None)
def load_feature_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed ``config/features.yaml``."""
    cfg = _read_yaml((config_dir or CONFIG_DIR) / "features.yaml")
    if "target" not in cfg:
        raise ConfigError("features.yaml is missing 'target'")
    return cfg


def sealed_years(config_dir: Path | None = None) -> set[int]:
    """Calendar years that must not be fetched, loaded or measured against."""
    cfg = load_data_config(config_dir)
    return {int(y) for y in (cfg["splits"]["holdout"].get("years") or [])}


def zones_for_tier(tier: str, config_dir: Path | None = None) -> list[Zone]:
    """All zones in a tier, in config order."""
    if tier not in VALID_TIERS:
        raise ConfigError(f"unknown tier {tier!r}")
    return [z for z in load_zones(config_dir).values() if z.tier == tier]


def config_hash(config_dir: Path | None = None) -> str:
    """Stable hash over all committed config, for tagging result rows (C10)."""
    directory = config_dir or CONFIG_DIR
    payload = {}
    for path in sorted(directory.glob("*.yaml")):
        payload[path.name] = _read_yaml(path)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
