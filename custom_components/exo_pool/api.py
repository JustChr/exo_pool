import random

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import aiohttp_client
from datetime import timedelta
import aiohttp
import logging
import time
import asyncio

from .write_manager import (
    _WriteItem,
    get_write_manager as _get_write_manager,
    _build_nested_dict,
    _apply_desired_update,
    _apply_heating_update,
    _apply_schedule_update,
)

_LOGGER = logging.getLogger(__name__)

# Header names we want to surface when present on any response
_RATE_LIMIT_HEADERS = frozenset(
    h.lower()
    for h in (
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
        "RateLimit-Policy",
        "X-Rate-Limit-Limit",
        "X-Rate-Limit-Remaining",
        "X-Rate-Limit-Reset",
    )
)


_SENSITIVE_HEADER_NAMES = frozenset(
    h.lower()
    for h in (
        "Authorization",
        "Set-Cookie",
        "X-Amz-Security-Token",
        "X-Amzn-Remapped-Authorization",
    )
)


def _log_response_headers(
    response: aiohttp.ClientResponse, *, label: str
) -> None:
    """Log all response headers at DEBUG; highlight any rate-limit headers at INFO."""
    headers_dict = {
        k: ("REDACTED" if k.lower() in _SENSITIVE_HEADER_NAMES else v)
        for k, v in response.headers.items()
    }
    _LOGGER.debug("%s response headers: %s", label, headers_dict)
    rate_headers = {
        k: v for k, v in headers_dict.items() if k.lower() in _RATE_LIMIT_HEADERS
    }
    if rate_headers:
        _LOGGER.info("%s rate-limit headers found: %s", label, rate_headers)


# API endpoints and keys from config_flow.py and REST sensors
LOGIN_URL = "https://prod.zodiac-io.com/users/v1/login"
REFRESH_URL = "https://prod.zodiac-io.com/users/v1/refresh"
DATA_URL_TEMPLATE = "https://prod.zodiac-io.com/devices/v1/{}/shadow"
API_KEY_PROD = "EOOEMOW4YR6QNB11"
API_KEY_R = "EOOEMOW4YR6QNB07"

# Error code translation
ERROR_CODES = {
    0: "No Error",
    3: "Low Conductivity",
    4: "Check Output",
    6: "Low Water Temp",
    7: "pH Dosing Stop",
    9: "ORP Stop",
}

# Domain constant
DOMAIN = "exo_pool"
# User-configurable refresh interval (seconds)
REFRESH_OPTION_KEY = "refresh_interval"
REFRESH_DEFAULT = 600
REFRESH_MIN = 300
REFRESH_MAX = 3600
BOOST_INTERVAL = 10
BOOST_DURATION = 60
MIN_REQUEST_INTERVAL = 5.0
DEBOUNCED_REFRESH_DELAY = 30.0
WRITE_GAP_SECONDS = 8.0
POST_WRITE_COOLDOWN_SECONDS = 45.0
NO_READ_WINDOW_SECONDS = 30.0
MIN_REFRESH_GUARD_SECONDS = 120.0
SCHEDULE_REFRESH_DELAY = 180.0
READ_DEFERRAL_JITTER_MIN = 15.0
READ_DEFERRAL_JITTER_MAX = 45.0
DEBOUNCE_JITTER_MIN = 30.0
DEBOUNCE_JITTER_MAX = 90.0

# AWS IoT MQTT
IOT_ENDPOINT = "a1zi08qpbrtjyq-ats.iot.us-east-1.amazonaws.com"
IOT_REGION = "us-east-1"
MQTT_CREDENTIAL_REFRESH_BUFFER = 300  # refresh 5 min before expiry
REST_FALLBACK_INTERVAL = 3600  # 1 hour REST poll - last resort when MQTT is dead


def get_auth_state(hass: HomeAssistant, entry: ConfigEntry) -> tuple[bool, str | None]:
    """Return (auth_failed, last_error) from the entry store."""
    store = _get_entry_store(hass, entry)
    return store.get("auth_failed", False), store.get("auth_last_error")


def _set_auth_failed(store: dict, error_text: str) -> None:
    store["auth_failed"] = True
    store["auth_last_error"] = error_text


def _clear_auth_state(store: dict) -> None:
    store["auth_failed"] = False
    store["auth_last_error"] = None


async def _async_rate_limit(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure a minimum delay between API requests for a config entry."""
    store = _get_entry_store(hass, entry)
    lock = store.setdefault("request_lock", asyncio.Lock())
    async with lock:
        last_request = store.get("last_request_ts")
        now = time.monotonic()
        if last_request is not None:
            wait_time = MIN_REQUEST_INTERVAL - (now - last_request)
            if wait_time > 0:
                _LOGGER.debug(
                    "Rate limiting API request for %s, sleeping %.2fs",
                    entry.entry_id,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
        store["last_request_ts"] = time.monotonic()


def _get_cooldown_until(store: dict) -> float:
    return float(store.get("cooldown_until", 0.0))


def _is_write_active(store: dict) -> bool:
    quiet_until = float(store.get("write_quiet_until", 0.0))
    return store.get("write_in_flight", 0) > 0 or time.monotonic() < quiet_until


def _cooldown_remaining(hass: HomeAssistant, entry: ConfigEntry) -> float:
    store = _get_entry_store(hass, entry)
    remaining = _get_cooldown_until(store) - time.monotonic()
    return max(0.0, remaining)


def _set_cooldown(
    hass: HomeAssistant, entry: ConfigEntry, seconds: float, *, reason: str
) -> None:
    store = _get_entry_store(hass, entry)
    cooldown_until = time.monotonic() + seconds
    store["cooldown_until"] = max(_get_cooldown_until(store), cooldown_until)
    _LOGGER.debug(
        "Cooldown set for %s: %.1fs (%s)",
        entry.entry_id,
        seconds,
        reason,
    )


def _schedule_debounced_refresh(
    hass: HomeAssistant, entry: ConfigEntry, *, delay: float = DEBOUNCED_REFRESH_DELAY
) -> None:
    """Schedule a single refresh after delay or cooldown, whichever is later."""
    store = _get_entry_store(hass, entry)
    now = time.monotonic()
    target = max(now + delay, _get_cooldown_until(store))
    target += random.uniform(DEBOUNCE_JITTER_MIN, DEBOUNCE_JITTER_MAX)
    if target <= now:
        target = now

    def _clear_debounce_task() -> None:
        store.pop("debounce_refresh_task", None)
        store.pop("refresh_deadline", None)

    if existing_deadline := store.get("refresh_deadline"):
        if existing_deadline >= target:
            return
        if task := store.get("debounce_refresh_task"):
            task.cancel()

    async def _refresh_later() -> None:
        try:
            await asyncio.sleep(max(0.0, target - time.monotonic()))
        except asyncio.CancelledError:
            return
        no_read_until = store.get("no_read_until")
        if no_read_until and time.monotonic() < no_read_until:
            _clear_debounce_task()
            _schedule_debounced_refresh(hass, entry, delay=0.0)
            return
        if _cooldown_remaining(hass, entry) > 0:
            _clear_debounce_task()
            _schedule_debounced_refresh(hass, entry, delay=0.0)
            return
        last_ok = store.get("last_success_fetch_ts")
        if last_ok and time.monotonic() - last_ok < MIN_REFRESH_GUARD_SECONDS:
            _clear_debounce_task()
            return
        _clear_debounce_task()
        await async_request_refresh(hass, entry, allow_debounce=False)

    store["refresh_deadline"] = target
    store["debounce_refresh_task"] = hass.async_create_task(_refresh_later())


def _should_defer_refresh(hass: HomeAssistant, entry: ConfigEntry, store: dict) -> bool:
    no_read_until = store.get("no_read_until")
    if no_read_until and time.monotonic() < no_read_until:
        return True
    if _is_write_active(store):
        store["write_defer_seconds"] = random.uniform(
            READ_DEFERRAL_JITTER_MIN, READ_DEFERRAL_JITTER_MAX
        )
        return True
    if _cooldown_remaining(hass, entry) > 0:
        return True
    return False


async def async_request_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    manual: bool = False,
    allow_debounce: bool = True,
) -> bool:
    """Request a refresh, respecting any cooldown."""
    store = _get_entry_store(hass, entry)
    if _should_defer_refresh(hass, entry, store):
        if allow_debounce:
            delay = float(store.pop("write_defer_seconds", 0.0))
            _schedule_debounced_refresh(hass, entry, delay=delay)
        if manual:
            _LOGGER.debug(
                "Manual refresh deferred (cooldown/write active), serving cached"
            )
        return False
    coordinator = store.get("coordinator")
    if coordinator:
        if manual:
            _LOGGER.debug("Manual refresh requested, fetching now")
        await coordinator.async_request_refresh()
        return True
    return False


def _merge_dict(base: dict, update: dict) -> dict:
    merged = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


async def async_update_data(hass: HomeAssistant, entry: ConfigEntry):
    """Fetch data from the Exo Pool API, handling token refresh."""
    store = _get_entry_store(hass, entry)
    _clear_auth_state(store)
    no_read_until = store.get("no_read_until")
    if no_read_until and time.monotonic() < no_read_until:
        _schedule_debounced_refresh(hass, entry, delay=0.0)
        coordinator = store.get("coordinator")
        return coordinator.data or {}
    if _is_write_active(store):
        _schedule_debounced_refresh(
            hass,
            entry,
            delay=random.uniform(READ_DEFERRAL_JITTER_MIN, READ_DEFERRAL_JITTER_MAX),
        )
        coordinator = store.get("coordinator")
        return coordinator.data or {}
    if _cooldown_remaining(hass, entry) > 0:
        _schedule_debounced_refresh(hass, entry, delay=0.0)
        coordinator = store.get("coordinator")
        return coordinator.data or {}
    serial_number = entry.data["serial_number"]
    id_token = entry.data.get("id_token")
    expires_at = entry.data.get("expires_at", 0)

    # Log whether this is the initial fetch or a REST fallback
    mqtt_client = store.get("mqtt_client")
    if mqtt_client and mqtt_client.connected:
        _LOGGER.debug("REST poll fired while MQTT is connected (likely initial fetch)")
    elif mqtt_client:
        _LOGGER.warning("REST fallback poll - MQTT is disconnected")
    else:
        _LOGGER.debug("REST fetch (MQTT not yet initialized)")

    # Reuse Home Assistant's shared aiohttp client session
    session = aiohttp_client.async_get_clientsession(hass)
    # Refresh token if missing, expired, or about to expire
    if (
        not id_token
        or store.get("auth_last_error") == '{"message":"The incoming token has expired"}'
        or time.time() > expires_at
    ):
        _LOGGER.debug(
            "Refreshing authentication tokens due to missing, expired, or upcoming expiration"
        )
        refreshed = False
        if "refresh_token" in entry.data:
            # Try refresh first
            try:
                refreshed = await _refresh_token(hass, entry, session)
            except Exception as e:
                _LOGGER.debug("Token refresh failed: %s, falling back to full login", e)

        if not refreshed:
            # Full login
            await _full_login(hass, entry, session)

        id_token = entry.data.get("id_token")  # Update after refresh/login
        _LOGGER.debug("Authentication token refreshed: %s", id_token[:10] + "...")

    # Fetch device data
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "okhttp/3.14.7",
        "Authorization": f"Bearer {id_token}",
    }
    _LOGGER.debug("Fetching data for serial_number: %s", serial_number)
    await _async_rate_limit(hass, entry)
    async with session.get(
        DATA_URL_TEMPLATE.format(serial_number), headers=headers
    ) as response:
        _LOGGER.debug("Data fetch response status: %s", response.status)
        _log_response_headers(response, label="Data fetch")
        if response.status != 200:
            error_text = await response.text()
            is_rate_limited = response.status == 429 or "Too Many Requests" in str(
                error_text
            )
            if is_rate_limited:
                _LOGGER.warning("Rate limited fetching device data: %s", error_text)
                coordinator = (
                    hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
                )
                if coordinator:
                    try:
                        configured = _get_configured_interval_seconds(entry)
                        current = getattr(
                            coordinator,
                            "update_interval",
                            timedelta(seconds=REFRESH_DEFAULT),
                        )
                        cur_s = (
                            int(current.total_seconds()) if current else REFRESH_DEFAULT
                        )
                        if coordinator.data:
                            # Exponential backoff up to REFRESH_MAX
                            new_s = max(cur_s, min(cur_s * 2, REFRESH_MAX))
                            if new_s != cur_s:
                                coordinator.update_interval = timedelta(seconds=new_s)
                                _set_cooldown(
                                    hass,
                                    entry,
                                    new_s,
                                    reason="read_429",
                                )
                                _LOGGER.warning(
                                    "429 Too Many Requests, backing off to %ss",
                                    new_s,
                                )
                            else:
                                _LOGGER.warning(
                                    "429 Too Many Requests, keeping %ss interval",
                                    cur_s,
                                )
                        else:
                            retry_s = max(60, min(configured, REFRESH_MAX))
                            if retry_s != cur_s:
                                coordinator.update_interval = timedelta(seconds=retry_s)
                                _set_cooldown(
                                    hass,
                                    entry,
                                    retry_s,
                                    reason="read_429",
                                )
                                _LOGGER.warning(
                                    "429 Too Many Requests, retrying in %ss",
                                    retry_s,
                                )
                    except Exception as backoff_error:
                        _LOGGER.debug(
                            "Backoff adjustment failed: %s",
                            backoff_error,
                        )
                    backoff_interval = getattr(
                        coordinator,
                        "update_interval",
                        timedelta(seconds=REFRESH_DEFAULT),
                    )
                    _set_cooldown(
                        hass,
                        entry,
                        int(backoff_interval.total_seconds()),
                        reason="read_429",
                    )
                    # Return previous data or empty data to avoid startup failure
                    _LOGGER.debug(
                        "Rate limited, returning cached data to keep coordinator loaded"
                    )
                    return coordinator.data or {}
                return {}

            _LOGGER.error("Failed to fetch device data: %s", error_text)
            if "The incoming token has expired" in error_text:
                store["auth_last_error"] = error_text
            raise UpdateFailed(f"Device data fetch failed: {error_text}")
        data = await response.json()
        _LOGGER.debug("Device data: %s", data)
        reported = data.get("state", {}).get("reported", {})
        coordinator = (
            hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
        )
        store["last_success_fetch_ts"] = time.monotonic()
        if coordinator:
            configured = _get_configured_interval_seconds(entry)
            current = getattr(
                coordinator,
                "update_interval",
                timedelta(seconds=REFRESH_DEFAULT),
            )
            if (
                current
                and int(current.total_seconds()) > configured
                and "boost_task" not in _get_entry_store(hass, entry)
            ):
                coordinator.update_interval = timedelta(seconds=configured)
                _LOGGER.debug(
                    "Restored polling interval to %ss after successful fetch",
                    configured,
                )
        return reported


from .auth import (  # noqa: F401
    _full_login,
    _refresh_token,
    _store_aws_credentials,
    _refresh_authentication,
)


def _get_configured_interval_seconds(entry: ConfigEntry) -> int:
    """Return the configured refresh interval in seconds, clamped to limits."""
    seconds = entry.options.get(REFRESH_OPTION_KEY, REFRESH_DEFAULT)
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = REFRESH_DEFAULT
    return max(REFRESH_MIN, min(REFRESH_MAX, seconds))


def _get_entry_store(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Return the data store for this config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    return hass.data[DOMAIN].setdefault(entry.entry_id, {})


async def _async_boost_refresh_interval(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Temporarily increase polling frequency after a change."""
    store = _get_entry_store(hass, entry)
    coordinator: DataUpdateCoordinator | None = store.get("coordinator")
    if coordinator is None:
        return

    current = coordinator.update_interval
    current_seconds = int(current.total_seconds()) if current else REFRESH_DEFAULT
    if current_seconds > BOOST_INTERVAL:
        coordinator.update_interval = timedelta(seconds=BOOST_INTERVAL)
        _LOGGER.debug(
            "Temporarily increased polling to %ss for %s",
            BOOST_INTERVAL,
            entry.entry_id,
        )

    if task := store.get("boost_task"):
        task.cancel()

    async def _reset_interval() -> None:
        try:
            await asyncio.sleep(BOOST_DURATION)
        except asyncio.CancelledError:
            return
        configured = _get_configured_interval_seconds(entry)
        coordinator.update_interval = timedelta(seconds=configured)
        _LOGGER.debug(
            "Restored polling interval to %ss for %s",
            configured,
            entry.entry_id,
        )
        store.pop("boost_task", None)

    store["boost_task"] = hass.async_create_task(_reset_interval())


async def _async_refresh_and_reconnect(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Refresh AWS credentials and reconnect MQTT.

    Called when MQTT reconnect fails due to expired credentials,
    or proactively by the credential refresh timer.
    """
    try:
        session = aiohttp_client.async_get_clientsession(hass)
        await _refresh_authentication(hass, entry, session)
        await hass.async_add_executor_job(_connect_mqtt, hass, entry)
    except Exception:
        _LOGGER.warning("MQTT credential refresh and reconnect failed", exc_info=True)


def _connect_mqtt(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create and connect the MQTT client if AWS credentials are available.

    Runs in a background thread since awsiotsdk connect is blocking.
    On success, shadow updates feed directly into the coordinator
    via async_set_updated_data, and the REST poll interval is relaxed
    to a 30-minute fallback.
    """
    store = _get_entry_store(hass, entry)
    credentials = store.get("aws_credentials")
    if not credentials:
        # Credentials aren't stored yet - the token was still valid from the
        # previous session so _full_login/_refresh_token wasn't called.
        # Do an explicit token refresh to get AWS credentials.
        _LOGGER.debug("No AWS credentials yet - triggering token refresh to obtain them")
        import asyncio

        async def _fetch_credentials():
            session = aiohttp_client.async_get_clientsession(hass)
            await _refresh_authentication(hass, entry, session)

        future = asyncio.run_coroutine_threadsafe(_fetch_credentials(), hass.loop)
        try:
            future.result(timeout=30)
        except Exception:
            _LOGGER.warning("Failed to obtain AWS credentials", exc_info=True)
            return False
        credentials = store.get("aws_credentials")
        if not credentials:
            _LOGGER.debug("Still no AWS credentials after refresh - skipping MQTT")
            return False

    coordinator = store.get("coordinator")
    if coordinator is None:
        return False

    from .mqtt_client import ExoMqttClient

    mqtt_client = store.get("mqtt_client")
    if mqtt_client is None:
        mqtt_client = ExoMqttClient(
            loop=hass.loop,
            endpoint=IOT_ENDPOINT,
            region=IOT_REGION,
            serial=entry.data["serial_number"],
        )
        store["mqtt_client"] = mqtt_client

    def _on_shadow_update(reported: dict) -> None:
        """Called on HA event loop when MQTT delivers a shadow update."""
        if _is_write_active(_get_entry_store(hass, entry)):
            # A write just completed; the reported shadow still reflects the
            # old state. Ignore this update — the optimistic state is correct
            # and the next MQTT push (or debounced refresh) will confirm it.
            return
        merged = _merge_dict(coordinator.data or {}, reported)
        coordinator.async_set_updated_data(merged)

    mqtt_client.set_shadow_callback(_on_shadow_update)

    def _on_reconnect_failed() -> None:
        """Called on HA event loop when MQTT re-subscribe fails (stale credentials)."""
        _LOGGER.warning("MQTT reconnect failed - refreshing credentials")
        hass.async_create_background_task(
            _async_refresh_and_reconnect(hass, entry),
            name="exo_pool_reconnect_refresh",
        )

    mqtt_client.set_reconnect_failed_callback(_on_reconnect_failed)

    try:
        mqtt_client.connect(credentials)
        # Relax REST polling - MQTT push resets the timer on each update
        coordinator.update_interval = timedelta(seconds=REST_FALLBACK_INTERVAL)
        _LOGGER.info(
            "MQTT connected - REST fallback interval set to %ss",
            REST_FALLBACK_INTERVAL,
        )
    except Exception:
        _LOGGER.warning(
            "MQTT connection failed - continuing with REST polling",
            exc_info=True,
        )
        # Schedule credential refresh on the HA event loop (not from this worker thread)
        hass.loop.call_soon_threadsafe(_schedule_credential_refresh, hass, entry)
        return False
    # Schedule credential refresh on the HA event loop (not from this worker thread)
    hass.loop.call_soon_threadsafe(_schedule_credential_refresh, hass, entry)
    return True


def _schedule_credential_refresh(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Schedule MQTT credential refresh before they expire."""
    store = _get_entry_store(hass, entry)
    credentials = store.get("aws_credentials")
    if not credentials:
        return

    # Cancel any existing refresh task
    if task := store.get("credential_refresh_task"):
        task.cancel()

    expiration_str = credentials.get("Expiration", "")
    if not expiration_str:
        return

    from datetime import datetime, timezone

    try:
        expires_at = datetime.fromisoformat(
            expiration_str.replace("Z", "+00:00")
        ).timestamp()
    except (ValueError, TypeError):
        _LOGGER.warning("Could not parse credential expiration: %s", expiration_str)
        return

    delay = max(0, expires_at - time.time() - MQTT_CREDENTIAL_REFRESH_BUFFER)
    _LOGGER.debug("Scheduling MQTT credential refresh in %.0fs", delay)

    async def _proactive_refresh() -> None:
        await asyncio.sleep(delay)
        _LOGGER.info("Refreshing AWS credentials for MQTT")
        await _async_refresh_and_reconnect(hass, entry)

    store["credential_refresh_task"] = hass.async_create_background_task(
        _proactive_refresh(),
        name="exo_pool_credential_refresh",
    )


from .coordinator import get_coordinator, cleanup_entry  # noqa: F401


async def async_set_refresh_interval(
    hass: HomeAssistant, entry: ConfigEntry, seconds: int
):
    """Update the refresh interval for the coordinator and persist to options."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = REFRESH_DEFAULT
    seconds = max(REFRESH_MIN, min(REFRESH_MAX, seconds))

    store = _get_entry_store(hass, entry)
    coordinator: DataUpdateCoordinator = store["coordinator"]
    if "boost_task" not in store:
        coordinator.update_interval = timedelta(seconds=seconds)
    _LOGGER.debug("Set refresh interval to %ss for %s", seconds, entry.entry_id)

    # Persist to entry options
    new_options = dict(entry.options)
    new_options[REFRESH_OPTION_KEY] = seconds
    hass.config_entries.async_update_entry(entry, options=new_options)


async def set_pool_value(hass, entry, setting, value):
    """Set a pool setting value via the API."""
    id_token = entry.data.get("id_token")
    if not id_token:
        _LOGGER.error("No id_token available for setting %s", setting)
        return

    keys = setting.split(".")
    nested_value = _build_nested_dict(keys, value)
    coordinator = _get_entry_store(hass, entry).get("coordinator")
    if coordinator:
        _apply_desired_update(coordinator, ["equipment", "swc_0"] + keys, value)

    future = asyncio.get_running_loop().create_future()
    item = _WriteItem(
        kind="pool",
        key=f"pool:{setting}",
        target=setting,
        payload=nested_value,
        futures=[future],
    )
    await _get_write_manager(hass, entry).enqueue(item)
    await future


async def set_heating_value(hass, entry, key: str, value, delay_refresh: bool = False):
    """Set a top-level heating value via the API (e.g., sp)."""
    id_token = entry.data.get("id_token")
    if not id_token:
        _LOGGER.error("No id_token available for heating.%s", key)
        return
    coordinator = _get_entry_store(hass, entry).get("coordinator")
    if coordinator:
        _apply_heating_update(coordinator, key, value)

    future = asyncio.get_running_loop().create_future()
    item = _WriteItem(
        kind="heating",
        key=f"heating:{key}",
        target=key,
        payload=value,
        futures=[future],
        extra_delay=10.0 if delay_refresh else 0.0,
    )
    await _get_write_manager(hass, entry).enqueue(item)
    await future


async def update_schedule(
    hass: HomeAssistant,
    entry: ConfigEntry,
    schedule_key: str,
    *,
    start: str | None = None,
    end: str | None = None,
    rpm: int | None = None,
):
    """Update a schedule's timer (and rpm for VSP) via the API."""
    id_token = entry.data.get("id_token")
    if not id_token:
        _LOGGER.error("No id_token available for schedule %s", schedule_key)
        raise Exception("Unauthenticated")

    sched_patch: dict = {}
    if start is not None or end is not None:
        timer: dict = {}
        if start is not None:
            timer["start"] = start
        if end is not None:
            timer["end"] = end
        sched_patch["timer"] = timer
    if rpm is not None:
        try:
            sched_patch["rpm"] = int(rpm)
        except (TypeError, ValueError):
            _LOGGER.warning("Invalid rpm value %s for schedule %s", rpm, schedule_key)
    if not sched_patch:
        _LOGGER.debug("No schedule updates provided for %s", schedule_key)
        return

    coordinator = _get_entry_store(hass, entry).get("coordinator")
    if coordinator:
        _apply_schedule_update(coordinator, schedule_key, sched_patch)

    future = asyncio.get_running_loop().create_future()
    item = _WriteItem(
        kind="schedule",
        key="schedule:batch",
        target="",
        payload={schedule_key: sched_patch},
        futures=[future],
        merge_func=_merge_dict,
    )
    await _get_write_manager(hass, entry).enqueue(item)
    await future


async def update_schedules(
    hass: HomeAssistant,
    entry: ConfigEntry,
    schedules: dict[str, dict],
):
    """Update multiple schedules in a single batched API call."""
    id_token = entry.data.get("id_token")
    if not id_token:
        raise Exception("Unauthenticated")

    batch_payload: dict = {}
    coordinator = _get_entry_store(hass, entry).get("coordinator")

    for schedule_key, params in schedules.items():
        sched_patch: dict = {}
        start = params.get("start")
        end = params.get("end")
        rpm = params.get("rpm")

        if start is not None or end is not None:
            timer: dict = {}
            if start is not None:
                timer["start"] = start
            if end is not None:
                timer["end"] = end
            sched_patch["timer"] = timer
        if rpm is not None:
            try:
                sched_patch["rpm"] = int(rpm)
            except (TypeError, ValueError):
                _LOGGER.warning("Invalid rpm value %s for schedule %s", rpm, schedule_key)

        if sched_patch:
            batch_payload[schedule_key] = sched_patch
            if coordinator:
                _apply_schedule_update(coordinator, schedule_key, sched_patch)

    if not batch_payload:
        _LOGGER.debug("No schedule updates to apply in batch")
        return

    future = asyncio.get_running_loop().create_future()
    item = _WriteItem(
        kind="schedule",
        key="schedule:batch",
        target="",
        payload=batch_payload,
        futures=[future],
        merge_func=_merge_dict,
    )
    await _get_write_manager(hass, entry).enqueue(item)
    await future
