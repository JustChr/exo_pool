"""Diagnostics support for Zodiac Exo."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import get_mqtt_connected
from .const import DOMAIN, SENSITIVE_KEYS

REDACT_FIELDS: set[str] = {
    *SENSITIVE_KEYS,
    "user_id",
    "serial_number",
    "sn",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry with sensitive fields redacted."""
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = store.get("coordinator")
    last_exception = getattr(coordinator, "last_exception", None)
    update_interval = getattr(coordinator, "update_interval", None)
    diag = {
        "config_entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "mqtt_connected": get_mqtt_connected(hass, entry),
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "last_exception": str(last_exception) if last_exception else None,
            "update_interval_seconds": update_interval.total_seconds()
            if update_interval
            else None,
            "data": getattr(coordinator, "data", None),
        },
    }
    return async_redact_data(diag, REDACT_FIELDS)
