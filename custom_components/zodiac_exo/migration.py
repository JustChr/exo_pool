"""Take over a setup from the old "Exo Pool" (exo_pool) integration.

Up to v0.2.x this integration used the domain ``exo_pool``. After the rename
the old config entry stays behind once its files are uninstalled. The config
flow offers to adopt it. The adopted entry carries ``MIGRATE_FROM`` in its
data, and on first setup we move the old device and entities over to the new
entry (keeping entity IDs, names, areas, icons, disabled state and device
ID), then remove the old entry.
"""
from __future__ import annotations

import inspect
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
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

