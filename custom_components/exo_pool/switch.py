"""Switch platform for Exo Pool."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import get_coordinator, set_pool_value
from .const import device_info as _device_info, swc0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switch platform for Exo Pool."""
    coordinator = await get_coordinator(hass, entry)
    async_add_entities(
        [
            ORPBoostSwitch(entry, coordinator),
            ChlorinatorSwitch(entry, coordinator),
            Aux1Switch(entry, coordinator),
            Aux2Switch(entry, coordinator),
            ChlorinatorLowModeSwitch(entry, coordinator),
        ]
    )


class _ExoSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for Exo Pool switches backed by an swc_0 field."""

    _attr_has_entity_name = True
    _pool_setting: str
    _unique_suffix: str

    def __init__(self, entry: ConfigEntry, coordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._unique_suffix}"
        self._attr_device_info = _device_info(entry)

    def _raw_value(self) -> Any:
        node: Any = swc0(self.coordinator.data)
        for key in self._pool_setting.split("."):
            node = node.get(key) if isinstance(node, dict) else None
        return node

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value()
        return None if value is None else bool(value)

    @property
    def available(self) -> bool:
        return super().available and bool(swc0(self.coordinator.data))

    async def _apply(self, value: bool) -> None:
        try:
            await set_pool_value(self.hass, self._entry, self._pool_setting, int(value))
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"{self.name}: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._apply(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._apply(False)


class ORPBoostSwitch(_ExoSwitch):
    """ORP Boost switch."""

    _attr_name = "ORP Boost"
    _attr_icon = "mdi:water-pump"
    _pool_setting = "boost"
    _unique_suffix = "orp_boost"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        time_str = swc0(self.coordinator.data).get("boost_time")
        if isinstance(time_str, str) and ":" in time_str:
            try:
                hours, minutes = map(int, time_str.split(":")[:2])
                return {"boost_time_remaining": hours * 60 + minutes}
            except (ValueError, TypeError):
                _LOGGER.debug("Invalid boost_time format: %s", time_str)
        return {}


class ChlorinatorSwitch(_ExoSwitch):
    """Chlorinator (salt water chlorine production) switch."""

    _attr_name = "Chlorinator"
    _attr_icon = "mdi:water-plus"
    _pool_setting = "production"
    _unique_suffix = "production"


class Aux1Switch(_ExoSwitch):
    """Aux 1 relay switch."""

    _attr_name = "Aux 1"
    _attr_icon = "mdi:toggle-switch"
    _pool_setting = "aux_1.state"
    _unique_suffix = "aux_1"


class Aux2Switch(_ExoSwitch):
    """Aux 2 relay switch (unavailable when Aux 2 drives the heat pump)."""

    _attr_name = "Aux 2"
    _attr_icon = "mdi:toggle-switch"
    _pool_setting = "aux_2.state"
    _unique_suffix = "aux_2"

    @property
    def available(self) -> bool:
        if swc0(self.coordinator.data).get("aux_2", {}).get("mode") == 3:
            return False
        return super().available


class ChlorinatorLowModeSwitch(_ExoSwitch):
    """Chlorinator low mode switch."""

    _attr_name = "Chlorinator Low Mode"
    _attr_icon = "mdi:water-minus"
    _pool_setting = "low"
    _unique_suffix = "swc_low_mode"
