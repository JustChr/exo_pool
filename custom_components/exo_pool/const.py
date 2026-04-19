from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

DOMAIN = "exo_pool"

# Mapping of Exo filter pump type codes to human readable labels.
FILTER_PUMP_TYPE_MAP = {
    1: "SSP",  # Single Speed Pump
    2: "VSP",  # Variable Speed Pump
}

_DEVICE_INFO_BASE = {
    "name": "Exo Pool",
    "manufacturer": "Zodiac",
    "model": "Exo",
}


def device_info(entry: ConfigEntry) -> dict:
    """Return the shared device info dict for all Exo Pool entities."""
    return {**_DEVICE_INFO_BASE, "identifiers": {(DOMAIN, entry.entry_id)}}


def swc0(data: dict | None) -> dict:
    """Return the swc_0 equipment dict from coordinator data, or {}."""
    return (data or {}).get("equipment", {}).get("swc_0", {})
