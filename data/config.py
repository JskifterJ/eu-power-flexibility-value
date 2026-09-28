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


@lru_cache(maxsize=None)
def load_data_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed ``config/data.yaml``, validated for the keys we rely on."""
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
        raise ConfigError(
            f"fetch_years overlaps the sealed holdout years {sorted(overlap)} — refusing to run"
        )
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
