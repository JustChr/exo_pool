"""Write queue for Exo Pool: batches and serialises device-state changes."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optimistic coordinator-data helpers
# ---------------------------------------------------------------------------

def _set_nested_value(target: dict, keys: list[str], value) -> None:
    node = target
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def _build_nested_dict(keys: list[str], value) -> dict:
    nested = value
    for key in reversed(keys):
        nested = {key: nested}
    return nested


def _apply_desired_update(
    coordinator: DataUpdateCoordinator, keys: list[str], value
) -> None:
    data = coordinator.data or {}
    _set_nested_value(data, keys, value)
    coordinator.async_set_updated_data(data)


def _apply_heating_update(
    coordinator: DataUpdateCoordinator, key: str, value
) -> None:
    data = coordinator.data or {}
    data.setdefault("heating", {})[key] = value
    coordinator.async_set_updated_data(data)


def _apply_schedule_update(
    coordinator: DataUpdateCoordinator, schedule_key: str, patch: dict
) -> None:
    data = coordinator.data or {}
    schedules = data.setdefault("schedules", {})
    schedules.setdefault(schedule_key, {}).update(patch)
    coordinator.async_set_updated_data(data)


# ---------------------------------------------------------------------------
# Write item & manager
# ---------------------------------------------------------------------------

@dataclass
class _WriteItem:
    kind: str
    key: str
    target: str
    payload: dict
    futures: list[asyncio.Future] = field(default_factory=list)
    merge_func: Callable[[dict, dict], dict] | None = None
    extra_delay: float = 0.0


class _WriteManager:
    """Serialise and coalesce write operations per config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._pending: dict[str, _WriteItem] = {}
        self._order: list[str] = []
        self._worker_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def enqueue(self, item: _WriteItem) -> None:
        from .api import _get_entry_store, NO_READ_WINDOW_SECONDS
        async with self._lock:
            store = _get_entry_store(self._hass, self._entry)
            store["no_read_until"] = time.monotonic() + NO_READ_WINDOW_SECONDS
            existing = self._pending.get(item.key)
            if existing:
                if existing.merge_func:
                    existing.payload = existing.merge_func(existing.payload, item.payload)
                else:
                    existing.payload = item.payload
                existing.extra_delay = max(existing.extra_delay, item.extra_delay)
                existing.futures.extend(item.futures)
            else:
                self._pending[item.key] = item
                self._order.append(item.key)
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = self._hass.async_create_task(self._worker())

    async def _worker(self) -> None:
        from .api import (
            _get_entry_store,
            _cooldown_remaining,
            _set_cooldown,
            _schedule_debounced_refresh,
            POST_WRITE_COOLDOWN_SECONDS,
            WRITE_GAP_SECONDS,
            SCHEDULE_REFRESH_DELAY,
        )
        while True:
            async with self._lock:
                if not self._order:
                    return
                key = self._order.pop(0)
                item = self._pending.pop(key, None)
            if item is None:
                continue

            cooldown = _cooldown_remaining(self._hass, self._entry)
            if cooldown > 0:
                await asyncio.sleep(cooldown)

            try:
                store = _get_entry_store(self._hass, self._entry)
                store["write_in_flight"] = store.get("write_in_flight", 0) + 1
                try:
                    await _execute_write(self._hass, self._entry, item)
                except Exception as first_err:
                    if item.kind == "pool":
                        _LOGGER.warning(
                            "Pool write %s failed (%s), retrying in 3s",
                            item.key,
                            first_err,
                        )
                        await asyncio.sleep(3.0)
                        await _execute_write(self._hass, self._entry, item)
                    else:
                        raise
            except Exception as err:
                for future in item.futures:
                    if not future.done():
                        future.set_exception(err)
            else:
                for future in item.futures:
                    if not future.done():
                        future.set_result(None)
                if item.kind == "pool":
                    store = _get_entry_store(self._hass, self._entry)
                    store["write_quiet_until"] = time.monotonic() + 5.0
                    _schedule_debounced_refresh(self._hass, self._entry)
                else:
                    _set_cooldown(
                        self._hass,
                        self._entry,
                        POST_WRITE_COOLDOWN_SECONDS + item.extra_delay,
                        reason="post_write",
                    )
                    store = _get_entry_store(self._hass, self._entry)
                    store["write_quiet_until"] = (
                        time.monotonic() + POST_WRITE_COOLDOWN_SECONDS
                    )
                    if item.kind == "schedule":
                        _schedule_debounced_refresh(
                            self._hass, self._entry, delay=SCHEDULE_REFRESH_DELAY
                        )
            finally:
                store = _get_entry_store(self._hass, self._entry)
                store["write_in_flight"] = max(0, store.get("write_in_flight", 0) - 1)

            store = _get_entry_store(self._hass, self._entry)
            mqtt_client = store.get("mqtt_client")
            if not (mqtt_client and mqtt_client.connected):
                await asyncio.sleep(WRITE_GAP_SECONDS)


def get_write_manager(hass: HomeAssistant, entry: ConfigEntry) -> _WriteManager:
    from .api import _get_entry_store
    store = _get_entry_store(hass, entry)
    manager = store.get("write_manager")
    if manager is None:
        manager = _WriteManager(hass, entry)
        store["write_manager"] = manager
    return manager


# ---------------------------------------------------------------------------
# Write execution
# ---------------------------------------------------------------------------

async def _execute_write(
    hass: HomeAssistant, entry: ConfigEntry, item: _WriteItem
) -> None:
    from .api import _get_entry_store
    if item.kind == "pool":
        desired = {"equipment": {"swc_0": item.payload}}
    elif item.kind == "heating":
        desired = {"heating": {item.target: item.payload}}
    elif item.kind == "schedule":
        desired = {"schedules": item.payload}
    else:
        raise Exception(f"Unknown write kind: {item.kind}")

    store = _get_entry_store(hass, entry)
    mqtt_client = store.get("mqtt_client")
    if mqtt_client and mqtt_client.connected:
        _LOGGER.debug("Writing %s via MQTT: %s", item.key, desired)
        try:
            mqtt_client.publish_desired(desired)
            return
        except Exception:
            _LOGGER.warning(
                "MQTT write failed for %s - falling back to REST",
                item.key,
                exc_info=True,
            )

    _LOGGER.debug("Writing %s via REST fallback", item.key)
    await _execute_write_rest(hass, entry, item, desired)


async def _execute_write_rest(
    hass: HomeAssistant,
    entry: ConfigEntry,
    item: _WriteItem,
    desired: dict,
) -> None:
    from .api import (
        _get_entry_store,
        _async_rate_limit,
        _log_response_headers,
        _refresh_authentication,
        _set_cooldown,
        _get_configured_interval_seconds,
        DATA_URL_TEMPLATE,
    )
    serial_number = entry.data["serial_number"]
    id_token = entry.data.get("id_token")
    if not id_token:
        raise Exception(f"No id_token available for write {item.key}")

    payload = {"state": {"desired": desired}}
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "okhttp/3.14.7",
        "Authorization": f"Bearer {id_token}",
    }
    url = DATA_URL_TEMPLATE.format(serial_number)
    _LOGGER.debug("Writing %s at %s with payload: %s", item.key, url, payload)
    session = aiohttp_client.async_get_clientsession(hass)
    response_status, response_text = await _post_write(
        hass, entry, session, url, payload, headers, item.key
    )
    if _is_token_expired_response(response_status, response_text):
        _LOGGER.warning(
            "Write got 401 unauthorized for %s; refreshing token and retrying once",
            item.key,
        )
        await _refresh_authentication(hass, entry, session)
        id_token = entry.data.get("id_token")
        if not id_token:
            raise Exception(f"No id_token available after refresh for write {item.key}")
        headers["Authorization"] = f"Bearer {id_token}"
        response_status, response_text = await _post_write(
            hass, entry, session, url, payload, headers, item.key
        )
    if response_status == 429:
        _LOGGER.warning("Rate limited during write %s: %s", item.key, response_text)
        _set_cooldown(hass, entry, _get_configured_interval_seconds(entry), reason="write_429")
        raise Exception(f"Rate limited for write {item.key}: {response_text}")
    if response_status != 200:
        _LOGGER.error(
            "Write failed for %s: %s (Status: %s)", item.key, response_text, response_status
        )
        raise Exception(
            f"Write failed for {item.key}: {response_text} (Status: {response_status})"
        )


def _is_token_expired_response(status: int, body: str) -> bool:
    if status != 401:
        return False
    return True


async def _post_write(
    hass: HomeAssistant,
    entry: ConfigEntry,
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    headers: dict,
    item_key: str,
) -> tuple[int, str]:
    from .api import _async_rate_limit, _log_response_headers
    await _async_rate_limit(hass, entry)
    async with session.post(url, json=payload, headers=headers) as response:
        _log_response_headers(response, label=f"Write ({item_key})")
        response_text = await response.text()
        _LOGGER.debug("Write response for %s: %s %s", item_key, response.status, response_text)
        return response.status, response_text
