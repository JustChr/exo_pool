from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .api import get_coordinator, ERROR_CODES
from .const import DOMAIN, FILTER_PUMP_TYPE_MAP, device_info as _device_info, swc0
from homeassistant.const import EntityCategory
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform for Exo Pool."""
    # Initialize or retrieve shared coordinator
    coordinator = await get_coordinator(hass, entry)

    # Add sensors
    entities = [
        TempSensor(entry, coordinator),
        ORPSensor(entry, coordinator),
        PHSensor(entry, coordinator),
        ErrorCodeSensor(entry, coordinator),
        WifiRssiSensor(entry, coordinator),
        HardwareSensor(entry, coordinator),
    ]
    async_add_entities(entities)


# Sensor Classes
class TempSensor(CoordinatorEntity, SensorEntity):
    """Representation of a temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:pool-thermometer"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Temperature"
        self._attr_unique_id = f"{entry.entry_id}_temp"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return swc0(self.coordinator.data).get("sns_3", {}).get("value")


class ORPSensor(CoordinatorEntity, SensorEntity):
    """Representation of an ORP sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-check"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "ORP"
        self._attr_unique_id = f"{entry.entry_id}_orp"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return swc0(self.coordinator.data).get("sns_2", {}).get("value")

    @property
    def extra_state_attributes(self):
        """Provide additional ORP attributes."""
        return {"set_point": swc0(self.coordinator.data).get("orp_sp")}


class PHSensor(CoordinatorEntity, SensorEntity):
    """Representation of a pH sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:test-tube"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "pH"
        self._attr_unique_id = f"{entry.entry_id}_ph"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        value = swc0(self.coordinator.data).get("sns_1", {}).get("value")
        return value / 10 if value is not None else None

    @property
    def extra_state_attributes(self):
        """Provide additional pH attributes."""
        set_point = swc0(self.coordinator.data).get("ph_sp")
        return {"set_point": set_point / 10 if set_point is not None else None}


class ErrorCodeSensor(CoordinatorEntity, SensorEntity):
    """Representation of an error code sensor."""

    _attr_icon = "mdi:alert-circle"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Error Code"
        self._attr_unique_id = f"{entry.entry_id}_error_code"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return swc0(self.coordinator.data).get("error_code")

    @property
    def extra_state_attributes(self):
        """Provide the error message as an attribute."""
        code = swc0(self.coordinator.data).get("error_code")
        return {
            "error_message": ERROR_CODES.get(
                int(code) if code is not None else 0, "Unknown Error"
            )
        }


class WifiRssiSensor(CoordinatorEntity, SensorEntity):
    """Representation of a WiFi RSSI sensor."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "dBm"
    _attr_icon = "mdi:wifi"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "WiFi RSSI"
        self._attr_unique_id = f"{entry.entry_id}_wifi_rssi"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        """Return the WiFi RSSI value."""
        return self.coordinator.data.get("debug", {}).get("RSSI")


class HardwareSensor(CoordinatorEntity, SensorEntity):
    """Representation of hardware configuration information."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:information-outline"

    def __init__(self, entry: ConfigEntry, coordinator):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Hardware"
        self._attr_unique_id = f"{entry.entry_id}_hardware"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        """Return a summary of enabled hardware capabilities."""
        hw = swc0(self.coordinator.data)
        capabilities = []
        if hw.get("ph_only", 0) == 1:
            capabilities.append("PH")
        if hw.get("dual_link", 0) == 1:
            capabilities.append("ORP")
        pump_type_label = self._get_filter_pump_type_label()
        if pump_type_label:
            capabilities.append(pump_type_label)
        return ", ".join(capabilities) if capabilities else "None"

    @property
    def extra_state_attributes(self):
        """Provide detailed hardware capability flags."""
        hw = swc0(self.coordinator.data)
        pump_type_label = self._get_filter_pump_type_label()
        return {
            "filter_pump_type": pump_type_label,
            "variable_speed_pump": pump_type_label == "VSP"
            or (pump_type_label is None and hw.get("vsp", 0) == 1),
            "ph_control": hw.get("ph_only", 0) == 1,
            "orp_control": hw.get("dual_link", 0) == 1,
        }

    def _get_filter_pump_type_label(self):
        """Translate the filter pump type code into a label."""
        hw = swc0(self.coordinator.data)
        pump_type_value = hw.get("filter_pump", {}).get("type")
        pump_type_label = FILTER_PUMP_TYPE_MAP.get(pump_type_value)
        if pump_type_label:
            return pump_type_label
        if hw.get("vsp", 0) == 1:
            return FILTER_PUMP_TYPE_MAP.get(2)
        return None
