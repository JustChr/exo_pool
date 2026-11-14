"""The Zodiac Exo integration."""
from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from . import api as exo_api
from .api import async_cleanup_entry, get_coordinator
from .const import DOMAIN, PLATFORMS, swc0
from .migration import MIGRATE_FROM, async_adopt_legacy_entry

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")

_TARGET_FIELDS = {
    vol.Optional(ATTR_ENTITY_ID): vol.Any(cv.entity_id, [cv.entity_id]),
    vol.Optional(ATTR_DEVICE_ID): vol.Any(cv.string, [cv.string]),
}

SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        **_TARGET_FIELDS,
        vol.Optional("schedule"): cv.string,
        vol.Optional("start"): cv.string,
        vol.Optional("end"): cv.string,
        vol.Optional("rpm"): vol.All(vol.Coerce(int), vol.Range(min=0, max=4000)),
    }
)

DISABLE_SCHEDULE_SCHEMA = vol.Schema(
    {**_TARGET_FIELDS, vol.Optional("schedule"): cv.string}
)

SET_SCHEDULES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.Any(cv.string, [cv.string]),
        vol.Required("schedules"): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required("schedule"): cv.string,
                        vol.Optional("start"): cv.string,
                        vol.Optional("end"): cv.string,
                        vol.Optional("rpm"): vol.All(
                            vol.Coerce(int), vol.Range(min=0, max=4000)
                        ),
                    }
                )
            ],
        ),
    }
)

RELOAD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.Any(cv.string, [cv.string]),
        vol.Optional("entry_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Zodiac Exo from a config entry."""
    _LOGGER.debug("Setting up Zodiac Exo entry %s", entry.entry_id)

    if MIGRATE_FROM in entry.data:
        await async_adopt_legacy_entry(hass, entry)

    # Entries created before v0.2.0 have no unique_id; backfill it so the
    # same system cannot be added twice.
    serial = entry.data.get("serial_number")
    if entry.unique_id is None and serial and not any(
        other.unique_id == serial
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        hass.config_entries.async_update_entry(entry, unique_id=serial)

    try:
        coordinator = await get_coordinator(hass, entry)
    except (ConfigEntryAuthFailed, ConfigEntryNotReady):
        await async_cleanup_entry(hass, entry)
        raise
    except Exception as err:
        await async_cleanup_entry(hass, entry)
        raise ConfigEntryNotReady(f"Failed to initialize Zodiac Exo: {err}") from err

    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Zodiac",
        name="Exo Pool",
        model="Exo",
    )

    @callback
    def _update_device_info() -> None:
        if not coordinator.data:
            return
        serial_number = swc0(coordinator.data).get("sn")
        sw_version = coordinator.data.get("debug", {}).get("Version Firmware")
        device = device_registry.async_get(device_entry.id)
        if device and (device.sw_version, device.serial_number) != (
            sw_version,
            serial_number,
        ):
            device_registry.async_update_device(
                device_entry.id, sw_version=sw_version, serial_number=serial_number
            )

    entry.async_on_unload(coordinator.async_add_listener(_update_device_info))
    _update_device_info()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await exo_api.async_set_refresh_interval(
        hass,
        entry,
        entry.options.get(exo_api.REFRESH_OPTION_KEY, exo_api.REFRESH_DEFAULT),
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await async_cleanup_entry(hass, entry)
    return unloaded


# -----------------------
# Services
# -----------------------


def _normalize_time(val: str | None) -> str | None:
    if val is None:
        return None
    if not isinstance(val, str) or not TIME_RE.match(val):
        raise ServiceValidationError("Invalid time format; expected HH:MM or HH:MM:SS")
    hours, minutes = int(val[0:2]), int(val[3:5])
    if hours > 23 or minutes > 59:
        raise ServiceValidationError(f"Invalid time: {val}")
    return val[0:5]


def _single(value, what: str) -> str:
    """Normalize a target value that may be a list into a single string."""
    if isinstance(value, list):
        if not value:
            raise ServiceValidationError(f"No {what} selected")
        if len(value) > 1:
            raise ServiceValidationError(f"Select a single {what}")
        return value[0]
    if isinstance(value, str):
        return value
    raise ServiceValidationError(f"Invalid {what} target")


def _find_entry_from_device(hass: HomeAssistant, device_id) -> ConfigEntry:
    device_id = _single(device_id, "device")
    device = dr.async_get(hass).async_get(device_id)
    if not device:
        raise ServiceValidationError("Device not found")
    for domain, entry_id in device.identifiers:
        if domain == DOMAIN:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry:
                return entry
    raise ServiceValidationError("Device is not a Zodiac Exo device")


def _default_entry(hass: HomeAssistant) -> ConfigEntry:
    entries = hass.config_entries.async_entries(DOMAIN)
    if len(entries) != 1:
        raise ServiceValidationError("Select a Zodiac Exo device")
    return entries[0]


def _loaded(entry: ConfigEntry) -> ConfigEntry:
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("Zodiac Exo config entry is not loaded")
    return entry


def _parse_schedule_from_entity_unique_id(unique_id: str | None) -> str | None:
    marker = "_schedule_"
    if unique_id and marker in unique_id:
        return unique_id.split(marker, 1)[1]
    return None


def _resolve_target(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[ConfigEntry, str | None]:
    """Resolve service call target to (entry, schedule_key or None)."""
    schedule_key = call.data.get("schedule")
    if entity_id := call.data.get(ATTR_ENTITY_ID):
        entity_id = _single(entity_id, "entity")
        ent = er.async_get(hass).async_get(entity_id)
        if not ent or ent.platform != DOMAIN:
            raise ServiceValidationError(f"{entity_id} is not a Zodiac Exo entity")
        entry = hass.config_entries.async_get_entry(ent.config_entry_id)
        if entry is None:
            raise ServiceValidationError("Config entry not found")
        if not schedule_key:
            schedule_key = _parse_schedule_from_entity_unique_id(ent.unique_id)
        return _loaded(entry), schedule_key
    if device_id := call.data.get(ATTR_DEVICE_ID):
        return _loaded(_find_entry_from_device(hass, device_id)), schedule_key
    return _loaded(_default_entry(hass)), schedule_key


async def _known_schedules(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    coordinator = await get_coordinator(hass, entry)
    return (coordinator.data or {}).get("schedules", {}) or {}


def _rpm_for(schedules: dict, schedule_key: str, rpm):
    """RPM only applies to variable-speed-pump schedules."""
    endpoint = (schedules.get(schedule_key) or {}).get("endpoint", "")
    return rpm if str(endpoint).lower().startswith("vsp") else None


def _register_services(hass: HomeAssistant) -> None:
    async def handle_reload(call: ServiceCall) -> None:
        if entry_id := call.data.get("entry_id"):
            entry = hass.config_entries.async_get_entry(entry_id)
            if not entry or entry.domain != DOMAIN:
                raise ServiceValidationError("Config entry not found")
        elif device_id := call.data.get(ATTR_DEVICE_ID):
            entry = _find_entry_from_device(hass, device_id)
        else:
            entry = _default_entry(hass)
        await hass.config_entries.async_reload(entry.entry_id)

    async def handle_set_schedule(call: ServiceCall) -> None:
        entry, schedule_key = _resolve_target(hass, call)
        if not schedule_key:
            raise ServiceValidationError(
                "Missing schedule key; select a schedule entity or provide schedule"
            )
        schedules = await _known_schedules(hass, entry)
        if schedule_key not in schedules:
            raise ServiceValidationError(f"Unknown schedule: {schedule_key}")
        await exo_api.update_schedule(
            hass,
            entry,
            schedule_key,
            start=_normalize_time(call.data.get("start")),
            end=_normalize_time(call.data.get("end")),
            rpm=_rpm_for(schedules, schedule_key, call.data.get("rpm")),
        )

    async def handle_disable_schedule(call: ServiceCall) -> None:
        entry, schedule_key = _resolve_target(hass, call)
        if not schedule_key:
            raise ServiceValidationError(
                "Missing schedule key; select a schedule entity or provide schedule"
            )
        if schedule_key not in await _known_schedules(hass, entry):
            raise ServiceValidationError(f"Unknown schedule: {schedule_key}")
        await exo_api.update_schedule(
            hass, entry, schedule_key, start="00:00", end="00:00", rpm=None
        )

    async def handle_set_schedules(call: ServiceCall) -> None:
        if device_id := call.data.get(ATTR_DEVICE_ID):
            entry = _loaded(_find_entry_from_device(hass, device_id))
        else:
            entry = _loaded(_default_entry(hass))
        schedules = await _known_schedules(hass, entry)

        items = call.data["schedules"]
        if not items:
            raise ServiceValidationError("No schedules provided")

        batch: dict[str, dict] = {}
        for item in items:
            schedule_key = item["schedule"]
            if schedule_key not in schedules:
                raise ServiceValidationError(f"Unknown schedule: {schedule_key}")
            batch[schedule_key] = {
                "start": _normalize_time(item.get("start")),
                "end": _normalize_time(item.get("end")),
                "rpm": _rpm_for(schedules, schedule_key, item.get("rpm")),
            }
        await exo_api.update_schedules(hass, entry, batch)

    hass.services.async_register(DOMAIN, "reload", handle_reload, schema=RELOAD_SCHEMA)
    hass.services.async_register(
        DOMAIN, "set_schedule", handle_set_schedule, schema=SET_SCHEDULE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "set_schedules", handle_set_schedules, schema=SET_SCHEDULES_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "disable_schedule",
        handle_disable_schedule,
        schema=DISABLE_SCHEDULE_SCHEMA,
    )
