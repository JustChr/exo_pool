from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import PERCENTAGE
from .api import get_coordinator, set_pool_value
from .const import DOMAIN, device_info as _device_info, swc0
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the number platform for Exo Pool."""
    _LOGGER.debug("Setting up number platform for entry: %s", entry.entry_id)
    coordinator = await get_coordinator(hass, entry)

    def _capabilities() -> tuple[bool, bool]:
        hw = swc0(coordinator.data)
        return hw.get("ph_only", 0) == 1, hw.get("dual_link", 0) == 1

    entities: list[NumberEntity] = [
        ExoPoolSwcOutputNumber(entry, coordinator),
        ExoPoolSwcLowOutputNumber(entry, coordinator),
    ]

    ph_capable, orp_capable = _capabilities()
    created_orp = False
    created_ph = False
    if orp_capable:
        entities.append(ExoPoolORPSetPointNumber(entry, coordinator))
        created_orp = True
    if ph_capable:
        entities.append(ExoPoolPHSetPointNumber(entry, coordinator))
        created_ph = True

    async_add_entities(entities)

    def _maybe_add_capabilities() -> None:
        nonlocal created_orp, created_ph
        ph_capable_now, orp_capable_now = _capabilities()
        new_entities: list[NumberEntity] = []
        if orp_capable_now and not created_orp:
            new_entities.append(ExoPoolORPSetPointNumber(entry, coordinator))
            created_orp = True
            _LOGGER.debug("Discovered ORP capability; adding ORP set point number")
        if ph_capable_now and not created_ph:
            new_entities.append(ExoPoolPHSetPointNumber(entry, coordinator))
            created_ph = True
            _LOGGER.debug("Discovered pH capability; adding pH set point number")
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_maybe_add_capabilities)


class ExoPoolORPSetPointNumber(CoordinatorEntity, NumberEntity):
    """Representation of an Exo Pool ORP set point number entity."""

    _attr_icon = "mdi:water-check"
    _attr_mode = "box"
    _attr_native_step = 10
    _attr_native_min_value = 600
    _attr_native_max_value = 900

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "ORP Set Point"
        self._attr_unique_id = f"{entry.entry_id}_orp_set_point"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return swc0(self.coordinator.data).get("orp_sp")

    async def async_set_native_value(self, value):
        try:
            await set_pool_value(self.hass, self._entry, "orp_sp", int(value))
        except Exception as err:
            raise HomeAssistantError(f"ORP Set Point: {err}") from err

    @property
    def available(self):
        return swc0(self.coordinator.data).get("dual_link", 0) == 1


class ExoPoolPHSetPointNumber(CoordinatorEntity, NumberEntity):
    """Representation of an Exo Pool pH set point number entity."""

    _attr_icon = "mdi:test-tube"
    _attr_mode = "box"
    _attr_native_step = 0.1
    _attr_native_min_value = 6.0
    _attr_native_max_value = 7.6

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "pH Set Point"
        self._attr_unique_id = f"{entry.entry_id}_ph_set_point"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        value = swc0(self.coordinator.data).get("ph_sp")
        return value / 10 if value is not None else None

    async def async_set_native_value(self, value):
        try:
            await set_pool_value(self.hass, self._entry, "ph_sp", value * 10)
        except Exception as err:
            raise HomeAssistantError(f"pH Set Point: {err}") from err

    @property
    def available(self):
        return swc0(self.coordinator.data).get("ph_only", 0) == 1


class ExoPoolSwcOutputNumber(CoordinatorEntity, NumberEntity):
    """Representation of an Exo Pool SWC output number entity."""

    _attr_icon = "mdi:water-percent"
    _attr_mode = "box"
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Chlorinator Output"
        self._attr_unique_id = f"{entry.entry_id}_swc_output_set"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return swc0(self.coordinator.data).get("swc")

    async def async_set_native_value(self, value):
        try:
            await set_pool_value(self.hass, self._entry, "swc", int(value))
        except Exception as err:
            raise HomeAssistantError(f"SWC Output: {err}") from err

    @property
    def available(self):
        return self.coordinator.data is not None and bool(self.coordinator.data)


class ExoPoolSwcLowOutputNumber(CoordinatorEntity, NumberEntity):
    """Representation of an Exo Pool SWC low output number entity."""

    _attr_icon = "mdi:water-percent"
    _attr_mode = "box"
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Chlorinator Low Output"
        self._attr_unique_id = f"{entry.entry_id}_swc_low_output_set"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return swc0(self.coordinator.data).get("swc_low")

    async def async_set_native_value(self, value):
        try:
            await set_pool_value(self.hass, self._entry, "swc_low", int(value))
        except Exception as err:
            raise HomeAssistantError(f"SWC Low Output: {err}") from err

    @property
    def available(self):
        return self.coordinator.data is not None and bool(self.coordinator.data)


