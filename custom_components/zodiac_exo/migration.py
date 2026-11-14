"""Take over a setup from the old "Exo Pool" (exo_pool) integration.

Up to v0.2.x this integration used the domain ``exo_pool``. There are two ways
an old setup reaches the renamed integration:

1. The old config entry was deleted (required by Home Assistant's
   Marketplace, which refuses to uninstall an integration that is still
   configured). Home Assistant keeps deleted entities, with their entity ID,
   name, icon, area, labels and hidden/disabled state, so it can restore them
   if they come back. On the first setup of a new entry we re-key those
   records from ``exo_pool`` to ``zodiac_exo``, so Home Assistant restores
   them for the new entities. The device's area, name and labels are copied
   too. Only the device ID changes.
2. The old config entry is still there but its code was removed (manual
   installs). The config flow offers to adopt it. The adopted entry carries
   ``MIGRATE_FROM`` in its data, and on first setup the old device and
   entities are moved over (device ID kept), then the old entry is removed.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

import attr

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import IntegrationNotFound, async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

OLD_DOMAIN = "exo_pool"
MIGRATE_FROM = "migrate_from_entry_id"
_REQUIRED_KEYS = ("email", "password", "serial_number")
_HAS_NEW_CONFIG_ENTRY_ID = "new_config_entry_id" in inspect.signature(
    dr.DeviceRegistry.async_update_device
).parameters


async def async_legacy_installed(hass: HomeAssistant) -> bool:
    """Return True if the old exo_pool integration's code is still installed."""
    try:
        await async_get_integration(hass, OLD_DOMAIN)
    except IntegrationNotFound:
        return False
    return True


def legacy_candidates(hass: HomeAssistant) -> list[ConfigEntry]:
    """Old exo_pool entries that can be adopted (not yet set up here)."""
    configured = {e.unique_id for e in hass.config_entries.async_entries(DOMAIN)}
    return [
        entry
        for entry in hass.config_entries.async_entries(OLD_DOMAIN)
        if all(entry.data.get(k) for k in _REQUIRED_KEYS)
        and entry.data["serial_number"] not in configured
    ]


def adopted_title(old: ConfigEntry) -> str:
    """Keep a user-chosen title, otherwise switch the default to the new name."""
    if old.title.startswith("Exo Pool"):
        return "Zodiac Exo" + old.title[len("Exo Pool"):]
    return old.title


async def async_adopt_legacy_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move devices/entities of the old entry to ``entry`` and remove the old one."""
    old_id = entry.data[MIGRATE_FROM]
    hass.config_entries.async_update_entry(
        entry, data={k: v for k, v in entry.data.items() if k != MIGRATE_FROM}
    )
    old = hass.config_entries.async_get_entry(old_id)
    if old is None or old.domain != OLD_DOMAIN:
        return

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # Entities first: on HA 2026.11+ moving a device also re-parents its
    # entities, which would hide them from the loop below.
    moved = 0
    for ent in er.async_entries_for_config_entry(ent_reg, old_id):
        unique_id = ent.unique_id
        if unique_id.startswith(old_id):
            unique_id = entry.entry_id + unique_id[len(old_id):]
        try:
            ent_reg.async_update_entity_platform(
                ent.entity_id,
                DOMAIN,
                new_config_entry_id=entry.entry_id,
                new_unique_id=unique_id,
            )
            moved += 1
        except ValueError:
            _LOGGER.warning("Could not take over %s from Exo Pool", ent.entity_id)

    for device in dr.async_entries_for_config_entry(dev_reg, old_id):
        identifiers = {
            (DOMAIN, entry.entry_id) if domain == OLD_DOMAIN else (domain, ident)
            for domain, ident in device.identifiers
        }
        if _HAS_NEW_CONFIG_ENTRY_ID:  # HA 2026.11+: devices have a single entry
            dev_reg.async_update_device(
                device.id,
                new_config_entry_id=entry.entry_id,
                new_identifiers=identifiers,
            )
        else:
            dev_reg.async_update_device(
                device.id,
                add_config_entry_id=entry.entry_id,
                new_identifiers=identifiers,
            )
            dev_reg.async_update_device(device.id, remove_config_entry_id=old_id)

    _LOGGER.info(
        "Took over Exo Pool entry %s (%d entities); removing the old entry",
        old.title,
        moved,
    )
    await hass.config_entries.async_remove(old_id)
    if not hass.config_entries.async_entries(OLD_DOMAIN):
        ir.async_delete_issue(
            hass, HOMEASSISTANT_DOMAIN, f"integration_not_found.{OLD_DOMAIN}"
        )



# Two deleted setups orphaned this close together are ambiguous (two pools
# removed at once), so neither is adopted automatically.
_AMBIGUOUS_WINDOW = 3600


def _old_entry_id(unique_id: str) -> str:
    """Unique IDs are "<config entry id>_<key>"; entry IDs contain no "_"."""
    return unique_id.split("_", 1)[0]


@callback
def async_adopt_deleted_entities(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Let a new entry inherit the deleted entities of a removed Exo Pool setup.

    Returns the old config entry ID that was adopted, or None.
    """
    ent_reg = er.async_get(hass)
    if er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        return None  # not the first setup
    deleted: dict[tuple[str, str, str], Any] = ent_reg.deleted_entities
    groups: dict[str, list[tuple[tuple[str, str, str], Any]]] = {}
    for key, record in deleted.items():
        if record.platform == OLD_DOMAIN and "_" in record.unique_id:
            groups.setdefault(_old_entry_id(record.unique_id), []).append((key, record))
    if not groups:
        return None

    def orphaned_at(old_id: str) -> float:
        return max((r.orphaned_timestamp or 0) for _, r in groups[old_id])

    ranked = sorted(groups, key=orphaned_at, reverse=True)
    if len(ranked) > 1 and orphaned_at(ranked[0]) - orphaned_at(ranked[1]) < _AMBIGUOUS_WINDOW:
        _LOGGER.warning(
            "Found several removed Exo Pool setups; not restoring their entity "
            "settings automatically"
        )
        return None

    old_id = ranked[0]
    for key, record in groups[old_id]:
        unique_id = entry.entry_id + record.unique_id[len(old_id):]
        new_key = (key[0], DOMAIN, unique_id)
        if new_key in deleted:
            continue
        del deleted[key]
        deleted[new_key] = attr.evolve(record, platform=DOMAIN, unique_id=unique_id)
    ent_reg.async_schedule_save()
    _LOGGER.info(
        "Restoring the settings of %d entities from the removed Exo Pool setup",
        len(groups[old_id]),
    )
    return old_id


@callback
def async_restore_device_settings(
    hass: HomeAssistant, old_id: str, device_id: str
) -> None:
    """Copy area, name and labels of the removed Exo Pool device (best effort)."""
    dev_reg = dr.async_get(hass)
    try:
        container = getattr(dev_reg, "_deleted_devices", None)
        if container is None:
            container = dev_reg.deleted_devices
        old = next(
            (d for d in list(container.values()) if (OLD_DOMAIN, old_id) in d.identifiers),
            None,
        )
    except Exception:  # noqa: BLE001 - registry internals differ between versions
        _LOGGER.debug("Could not read the removed Exo Pool device", exc_info=True)
        return
    if old is None:
        return
    device = dev_reg.async_get(device_id)
    if device is None:
        return
    changes: dict[str, Any] = {}
    if old.area_id and not device.area_id:
        changes["area_id"] = old.area_id
    if old.name_by_user and not device.name_by_user:
        changes["name_by_user"] = old.name_by_user
    if getattr(old, "labels", None) and not device.labels:
        changes["labels"] = set(old.labels)
    if changes:
        dev_reg.async_update_device(device_id, **changes)
