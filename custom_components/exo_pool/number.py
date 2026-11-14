"""Number platform for Exo Pool."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import get_coordinator, set_pool_value
from .const import device_info as _device_info, swc0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the number platform for Exo Pool."""
    coordinator = await get_coordinator(hass, entry)

    async_add_entities(
        [
            ExoPoolSwcOutputNumber(entry, coordinator),
            ExoPoolSwcLowOutputNumber(entry, coordinator),
        ]
    )

    created_orp = False
    created_ph = False

    @callback
    def _maybe_add_capabilities() -> None:
        """Add ORP / pH set points once the hardware reports the capability."""
        nonlocal created_orp, created_ph
        hw = swc0(coordinator.data)
        new_entities: list[NumberEntity] = []
        if hw.get("dual_link", 0) == 1 and not created_orp:
            new_entities.append(ExoPoolORPSetPointNumber(entry, coordinator))
            created_orp = True
        if hw.get("ph_only", 0) == 1 and not created_ph:
            new_entities.append(ExoPoolPHSetPointNumber(entry, coordinator))
            created_ph = True
        if new_entities:
            async_add_entities(new_entities)

    _maybe_add_capabilities()
    entry.async_on_unload(coordinator.async_add_listener(_maybe_add_capabilities))


class _ExoNumber(CoordinatorEntity, NumberEntity):
    """Base class for Exo Pool number entities backed by an swc_0 field."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _field: str
    _unique_suffix: str
    _scale: float = 1.0

    def __init__(self, entry: ConfigEntry, coordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._unique_suffix}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        value = swc0(self.coordinator.data).get(self._field)
        if value is None:
            return None
        return value / self._scale if self._scale != 1.0 else value

    @property
    def available(self) -> bool:
        return super().available and bool(swc0(self.coordinator.data))

    async def async_set_native_value(self, value: float) -> None:
        raw = int(round(value * self._scale))
        try:
            await set_pool_value(self.hass, self._entry, self._field, raw)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"{self.name}: {err}") from err


class ExoPoolORPSetPointNumber(_ExoNumber):
    """ORP set point (mV)."""

    _attr_name = "ORP Set Point"
    _attr_icon = "mdi:water-check"
    _attr_native_step = 10
    _attr_native_min_value = 600
    _attr_native_max_value = 900
    _attr_native_unit_of_measurement = "mV"
    _field = "orp_sp"
    _unique_suffix = "orp_set_point"

    @property
    def available(self) -> bool:
        return super().available and swc0(self.coordinator.data).get("dual_link", 0) == 1


class ExoPoolPHSetPointNumber(_ExoNumber):
    """pH set point (device stores pH × 10)."""

    _attr_name = "pH Set Point"
    _attr_icon = "mdi:test-tube"
    _attr_native_step = 0.1
    _attr_native_min_value = 6.0
    _attr_native_max_value = 7.6
    _field = "ph_sp"
    _unique_suffix = "ph_set_point"
    _scale = 10.0

    @property
    def available(self) -> bool:
        return super().available and swc0(self.coordinator.data).get("ph_only", 0) == 1


class ExoPoolSwcOutputNumber(_ExoNumber):
    """Chlorinator output percentage."""

    _attr_name = "Chlorinator Output"
    _attr_icon = "mdi:water-percent"
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_unit_of_measurement = PERCENTAGE
    _field = "swc"
    _unique_suffix = "swc_output_set"


class ExoPoolSwcLowOutputNumber(_ExoNumber):
    """Chlorinator output percentage in low mode."""

    _attr_name = "Chlorinator Low Output"
    _attr_icon = "mdi:water-percent"
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_unit_of_measurement = PERCENTAGE
    _field = "swc_low"
    _unique_suffix = "swc_low_output_set"
