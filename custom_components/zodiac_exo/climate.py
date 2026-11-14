"""Climate platform for Zodiac Exo (heat pump on Aux 2)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import get_coordinator, set_heating_value, set_pool_value
from .const import device_info as _device_info, swc0

_LOGGER = logging.getLogger(__name__)

AUX2_MODE_HEAT = 3

# Home Assistant 2026.11 introduced the native_* temperature API on
# ClimateEntity and deprecated temperature_unit / current_temperature /
# target_temperature for entities. Older versions only know the legacy names.
_HAS_NATIVE_TEMPERATURE_API = hasattr(ClimateEntity, "native_temperature_unit")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up climate entity for Zodiac Exo heat pump (Aux 2 mode heat)."""
    coordinator = await get_coordinator(hass, entry)
    created = False

    def _should_create() -> bool:
        return swc0(coordinator.data).get("aux_2", {}).get("mode") == AUX2_MODE_HEAT

    @callback
    def _maybe_create() -> None:
        nonlocal created
        if created or not _should_create():
            return
        async_add_entities([ExoHeatPumpClimate(entry, coordinator)])
        created = True

    _maybe_create()
    if not created:
        _LOGGER.debug(
            "Aux 2 not in heat mode; climate entity will be created when detected"
        )
    # Aux 2 may be switched to heat mode later
    entry.async_on_unload(coordinator.async_add_listener(_maybe_create))


class ExoHeatPumpClimate(CoordinatorEntity, ClimateEntity):
    """Heat pump climate entity backed by top-level 'heating' data."""

    _attr_has_entity_name = True
    _attr_name = "Heat Pump"
    _attr_icon = "mdi:heat-pump"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0

    def __init__(self, entry: ConfigEntry, coordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_heat_pump"
        self._attr_device_info = _device_info(entry)

    # -- data helpers ------------------------------------------------------

    @property
    def _heating(self) -> dict:
        return (self.coordinator.data or {}).get("heating") or {}

    @property
    def _aux2(self) -> dict:
        return swc0(self.coordinator.data).get("aux_2") or {}

    # -- state -------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Available while Aux 2 stays in heat mode and heating data exists."""
        return (
            super().available
            and self._aux2.get("mode") == AUX2_MODE_HEAT
            and (self.coordinator.data or {}).get("heating") is not None
        )

    @property
    def native_current_temperature(self) -> float | None:
        return swc0(self.coordinator.data).get("sns_3", {}).get("value")

    @property
    def native_target_temperature(self) -> float | None:
        return self._heating.get("sp")

    if not _HAS_NATIVE_TEMPERATURE_API:
        # Legacy API for Home Assistant < 2026.11. Never defined on newer
        # versions, so no deprecation warnings are raised there.
        @property
        def temperature_unit(self) -> str:
            return UnitOfTemperature.CELSIUS

        @property
        def current_temperature(self) -> float | None:
            return self.native_current_temperature

        @property
        def target_temperature(self) -> float | None:
            return self.native_target_temperature

    @property
    def min_temp(self) -> float:
        return float(self._heating.get("sp_min", 10))

    @property
    def max_temp(self) -> float:
        return float(self._heating.get("sp_max", 40))

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self._aux2.get("state") == 1 else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if self._aux2.get("state") == 1 or self._heating.get("state") == 2:
            return HVACAction.HEATING
        return HVACAction.OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        heating = self._heating
        aux2 = self._aux2
        return {
            "aux2_mode": aux2.get("mode"),
            "aux2_type": aux2.get("type"),
            "aux2_state": aux2.get("state"),
            "heating_state_raw": heating.get("state"),
            "enabled": heating.get("enabled"),
            "sp_min": heating.get("sp_min"),
            "sp_max": heating.get("sp_max"),
            "vsp_rpm_index": heating.get("vsp_rpm_index"),
            "vsp_rpm_list": heating.get("vsp_rpm_list"),
            "priority_enabled": heating.get("priority_enabled"),
        }

    # -- commands ----------------------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        try:
            value = int(round(float(temp)))
        except (TypeError, ValueError) as err:
            raise HomeAssistantError(f"Invalid temperature: {temp}") from err
        value = max(int(self.min_temp), min(int(self.max_temp), value))
        try:
            await set_heating_value(self.hass, self._entry, "sp", value)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Heat Pump: {err}") from err

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in (HVACMode.HEAT, HVACMode.OFF):
            raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")
        try:
            await set_pool_value(
                self.hass, self._entry, "aux_2.state", 1 if hvac_mode == HVACMode.HEAT else 0
            )
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Heat Pump: {err}") from err

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
