from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

DOMAIN = "exo_pool"

PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "button", "climate"]

# Zodiac / iAqualink API
LOGIN_URL = "https://prod.zodiac-io.com/users/v1/login"
REFRESH_URL = "https://prod.zodiac-io.com/users/v1/refresh"
DATA_URL_TEMPLATE = "https://prod.zodiac-io.com/devices/v1/{}/shadow"
DEVICES_URL = "https://r-api.iaqualink.net/devices.json"
API_KEY_PROD = "EOOEMOW4YR6QNB11"
API_KEY_R = "EOOEMOW4YR6QNB07"
USER_AGENT = "okhttp/3.14.7"

# Mapping of Exo filter pump type codes to human readable labels.
FILTER_PUMP_TYPE_MAP = {
    1: "SSP",  # Single Speed Pump
    2: "VSP",  # Variable Speed Pump
}

# Keys whose values must never end up in logs or diagnostics.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "email",
        "authentication_token",
        "auth_token",
        "id_token",
        "IdToken",
        "AccessToken",
        "RefreshToken",
        "refresh_token",
        "session_id",
        "credentials",
        "AccessKeyId",
        "SecretKey",
        "SessionToken",
        "IdentityId",
    }
)


def redact(data: Any) -> Any:
    """Return a copy of data with sensitive values replaced (for logging)."""
    if isinstance(data, dict):
        return {
            k: ("**REDACTED**" if k in SENSITIVE_KEYS else redact(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the shared device info for all Exo Pool entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Exo Pool",
        manufacturer="Zodiac",
        model="Exo",
    )


def swc0(data: dict | None) -> dict:
    """Return the swc_0 equipment dict from coordinator data, or {}."""
    return (data or {}).get("equipment", {}).get("swc_0", {}) or {}
