from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .api import get_coordinator, set_pool_value
from .const import DOMAIN, device_info as _device_info
import logging

_LOGGER = logging.getLogger(__name__)

_LOGGER.debug("Switch platform module loaded")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switch platform for Exo Pool."""
    _LOGGER.debug("Setting up switch platform for entry: %s", entry.entry_id)
    coordinator = await get_coordinator(hass, entry)
    entities = [
        ORPBoostSwitch(entry, coordinator),
        PowerSwitch(entry, coordinator),
        ChlorinatorSwitch(entry, coordinator),
        Aux1Switch(entry, coordinator),
        Aux2Switch(entry, coordinator),
        SWCLowModeSwitch(entry, coordinator),
    ]
    async_add_entities(entities)


class _ExoSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for Exo Pool switches with optimistic state and error handling."""

    _pool_setting: str

    def __init__(self, entry: ConfigEntry, coordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = _device_info(entry)

    async def _apply(self, value: bool) -> None:
        try:
            await set_pool_value(self.hass, self._entry, self._pool_setting, int(value))
        except Exception as err:
            raise HomeAssistantError(f"{self._attr_name}: {err}") from err

    async def async_turn_on(self, **kwargs) -> None:
        await self._apply(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._apply(False)


class ORPBoostSwitch(_ExoSwitch):
    """Representation of an ORP Boost switch."""

    _pool_setting = "boost"
    _attr_icon = "mdi:water-pump"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(entry, coordinator)
        self._attr_name = "ORP Boost"
        self._attr_unique_id = f"{entry.entry_id}_orp_boost"

    @property
    def is_on(self):
        return bool(
            self.coordinator.data.get("equipment", {}).get("swc_0", {}).get("boost")
        )

    @property
    def available(self):
        return (
            self.coordinator.data is not None
            and "equipment" in self.coordinator.data
            and "swc_0" in self.coordinator.data["equipment"]
        )

    @property
    def extra_state_attributes(self):
        time_str = (
            self.coordinator.data.get("equipment", {})
            .get("swc_0", {})
            .get("boost_time")
        )
        if time_str and isinstance(time_str, str) and ":" in time_str:
            try:
                hours, minutes = map(int, time_str.split(":"))
                return {"boost_time_remaining": hours * 60 + minutes}
            except (ValueError, TypeError):
                _LOGGER.error("Invalid boost_time format: %s", time_str)
                return {}
        return {}


class PowerSwitch(_ExoSwitch):
    """Representation of a Power switch."""

    _pool_setting = "exo_state"
    _attr_icon = "mdi:power"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(entry, coordinator)
        self._attr_name = "Power"
        self._attr_unique_id = f"{entry.entry_id}_exo_state"

    @property
    def is_on(self):
        return bool(
            self.coordinator.data.get("equipment", {}).get("swc_0", {}).get("exo_state")
        )

    @property
    def available(self):
        return (
            self.coordinator.data is not None
            and "equipment" in self.coordinator.data
            and "swc_0" in self.coordinator.data["equipment"]
        )


class ChlorinatorSwitch(_ExoSwitch):
    """Representation of a Chlorinator switch."""

    _pool_setting = "production"
    _attr_icon = "mdi:water-plus"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(entry, coordinator)
        self._attr_name = "Chlorinator"
        self._attr_unique_id = f"{entry.entry_id}_production"

    @property
    def is_on(self):
        return bool(
            self.coordinator.data.get("equipment", {})
            .get("swc_0", {})
            .get("production")
        )

    @property
    def available(self):
        return (
            self.coordinator.data is not None
            and "equipment" in self.coordinator.data
            and "swc_0" in self.coordinator.data["equipment"]
        )


class Aux1Switch(_ExoSwitch):
    """Representation of an Aux 1 switch."""

    _pool_setting = "aux_1.state"
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(entry, coordinator)
        self._attr_name = "Aux 1"
        self._attr_unique_id = f"{entry.entry_id}_aux_1"

    @property
    def is_on(self):
        return bool(
            self.coordinator.data.get("equipment", {})
            .get("swc_0", {})
            .get("aux_1", {})
            .get("state")
        )

    @property
    def available(self):
        return (
            self.coordinator.data is not None
            and "equipment" in self.coordinator.data
            and "swc_0" in self.coordinator.data["equipment"]
        )


class Aux2Switch(_ExoSwitch):
    """Representation of an Aux 2 switch."""

    _pool_setting = "aux_2.state"
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(entry, coordinator)
        self._attr_name = "Aux 2"
        self._attr_unique_id = f"{entry.entry_id}_aux_2"

    @property
    def is_on(self):
        return bool(
            self.coordinator.data.get("equipment", {})
            .get("swc_0", {})
            .get("aux_2", {})
            .get("state")
        )

    @property
    def available(self):
        return (
            self.coordinator.data is not None
            and "equipment" in self.coordinator.data
            and "swc_0" in self.coordinator.data["equipment"]
        )


class SWCLowModeSwitch(_ExoSwitch):
    """Representation of a SWC low mode switch."""

    _pool_setting = "low"
    _attr_icon = "mdi:water-minus"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(entry, coordinator)
        self._attr_name = "SWC Low Mode"
        self._attr_unique_id = f"{entry.entry_id}_swc_low_mode"

    @property
    def is_on(self):
        return bool(
            self.coordinator.data.get("equipment", {}).get("swc_0", {}).get("low")
        )

    @property
    def available(self):
        return (
            self.coordinator.data is not None
            and "equipment" in self.coordinator.data
            and "swc_0" in self.coordinator.data["equipment"]
        )
