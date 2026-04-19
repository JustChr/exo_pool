"""Coordinator setup for Exo Pool."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def get_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> DataUpdateCoordinator:
    """Get or create a shared DataUpdateCoordinator for the config entry."""
    from .api import (
        _get_entry_store,
        _get_configured_interval_seconds,
        _connect_mqtt,
        async_update_data,
    )

    store = _get_entry_store(hass, entry)
    if "coordinator" in store:
        return store["coordinator"]

    seconds = _get_configured_interval_seconds(entry)
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Exo Pool",
        update_method=lambda: async_update_data(hass, entry),
        update_interval=timedelta(seconds=seconds),
    )
    store["coordinator"] = coordinator

    # asyncio.Event lets the MQTT shadow callback signal us instantly,
    # replacing the old polling loop (20 × 0.5s sleeps).
    mqtt_ready = asyncio.Event()

    def _on_first_data() -> None:
        mqtt_ready.set()

    unsubscribe = coordinator.async_add_listener(_on_first_data)

    mqtt_connected = await hass.async_add_executor_job(_connect_mqtt, hass, entry)

    if mqtt_connected:
        try:
            await asyncio.wait_for(mqtt_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass
        finally:
            unsubscribe()

        if coordinator.data:
            _LOGGER.info("Initial data loaded via MQTT - skipping REST fetch")
        else:
            _LOGGER.warning(
                "MQTT connected but no shadow data received - falling back to REST"
            )
            await coordinator.async_config_entry_first_refresh()
    else:
        unsubscribe()
        _LOGGER.info("MQTT not available - loading initial data via REST")
        await coordinator.async_config_entry_first_refresh()

    return store["coordinator"]


def cleanup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up MQTT client and scheduled tasks for a config entry."""
    from .api import _get_entry_store

    store = _get_entry_store(hass, entry)

    mqtt_client = store.get("mqtt_client")
    if mqtt_client:
        try:
            mqtt_client.disconnect()
        except Exception:
            _LOGGER.debug("Error disconnecting MQTT during cleanup", exc_info=True)

    for task_key in ("credential_refresh_task", "debounce_refresh_task", "boost_task"):
        if task := store.get(task_key):
            task.cancel()
