"""Authentication helpers for Zodiac Exo (login, token refresh, AWS credentials)."""
from __future__ import annotations

import logging
import time

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from .const import API_KEY_PROD, LOGIN_URL, REFRESH_URL, USER_AGENT, redact

_LOGGER = logging.getLogger(__name__)

# HTTP status codes from the login endpoint that mean "credentials rejected"
# (as opposed to a temporary server / network problem).
_AUTH_REJECTED_STATUSES = (400, 401, 403)


class ExoAuthError(HomeAssistantError):
    """Temporary failure while authenticating (network, server error)."""


async def async_login(
    session: aiohttp.ClientSession, email: str, password: str
) -> tuple[int, dict | None, str]:
    """POST to the login endpoint. Returns (status, json or None, raw text)."""
    payload = {"api_key": API_KEY_PROD, "email": email, "password": password}
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    async with session.post(LOGIN_URL, json=payload, headers=headers) as response:
        text = await response.text()
        try:
            data = await response.json(content_type=None)
        except ValueError:
            data = None
        return response.status, data if isinstance(data, dict) else None, text


async def _full_login(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> None:
    """Perform full login with email and password."""
    from .api import _async_rate_limit, _get_entry_store, _set_auth_failed

    store = _get_entry_store(hass, entry)
    await _async_rate_limit(hass, entry)
    try:
        status, data, text = await async_login(
            session, entry.data["email"], entry.data["password"]
        )
    except aiohttp.ClientError as err:
        raise ExoAuthError(f"Login request failed: {err}") from err

    _LOGGER.debug("Login response status: %s", status)
    if status in _AUTH_REJECTED_STATUSES:
        _LOGGER.error("Login rejected (status %s)", status)
        _set_auth_failed(store, f"Login rejected (status {status})")
        raise ConfigEntryAuthFailed("Zodiac Exo login rejected; please re-authenticate")
    if status != 200 or data is None:
        _LOGGER.error("Login failed (status %s)", status)
        _set_auth_failed(store, f"Login failed (status {status})")
        raise ExoAuthError(f"Login failed (status {status})")

    _LOGGER.debug("Login response data: %s", redact(data))
    oauth = data.get("userPoolOAuth") or {}
    id_token = oauth.get("IdToken")
    auth_token = data.get("authentication_token")
    if not id_token or not auth_token:
        _set_auth_failed(store, "Login response missing tokens")
        raise ExoAuthError("Login response missing tokens")

    _apply_tokens(hass, entry, data)


async def _refresh_token(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> bool:
    """Refresh token using refresh_token. Returns True on success."""
    from .api import _async_rate_limit, _log_response_headers

    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    payload = {
        "email": entry.data["email"],
        "refresh_token": entry.data["refresh_token"],
    }
    await _async_rate_limit(hass, entry)
    async with session.post(REFRESH_URL, json=payload, headers=headers) as response:
        _LOGGER.debug("Refresh response status: %s", response.status)
        _log_response_headers(response, label="Token refresh")
        if response.status != 200:
            _LOGGER.debug("Token refresh failed with status %s", response.status)
            return False
        data = await response.json(content_type=None)
    if not isinstance(data, dict):
        return False
    _LOGGER.debug("Refresh response data: %s", redact(data))
    if not (data.get("userPoolOAuth") or {}).get("IdToken"):
        _LOGGER.debug("No userPoolOAuth.IdToken in refresh response")
        return False
    _apply_tokens(hass, entry, data)
    return True


def _apply_tokens(hass: HomeAssistant, entry: ConfigEntry, data: dict) -> None:
    """Persist tokens from a login/refresh response and store AWS credentials."""
    from .api import _clear_auth_state, _get_entry_store

    oauth = data.get("userPoolOAuth") or {}
    update_data = {
        **entry.data,
        "id_token": oauth.get("IdToken"),
        "expires_at": time.time() + oauth.get("ExpiresIn", 3600) - 60,
    }
    if auth_token := data.get("authentication_token"):
        update_data["auth_token"] = auth_token
    if user_id := data.get("id"):
        update_data["user_id"] = user_id
    if refresh_token := oauth.get("RefreshToken"):
        update_data["refresh_token"] = refresh_token
    hass.config_entries.async_update_entry(entry, data=update_data)
    _clear_auth_state(_get_entry_store(hass, entry))
    _store_aws_credentials(hass, entry, data)


def _store_aws_credentials(
    hass: HomeAssistant, entry: ConfigEntry, data: dict
) -> None:
    """Extract and store AWS credentials from a login/refresh response."""
    from .api import _get_entry_store

    credentials = data.get("credentials")
    if not credentials:
        _LOGGER.debug("No AWS credentials in response - MQTT will use REST fallback")
        return
    store = _get_entry_store(hass, entry)
    store["aws_credentials"] = credentials
    _LOGGER.debug(
        "Stored AWS credentials (expire %s)",
        credentials.get("Expiration", "unknown"),
    )


async def _refresh_authentication(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> None:
    """Refresh tokens using refresh_token when possible, falling back to full login."""
    refreshed = False
    if "refresh_token" in entry.data:
        try:
            refreshed = await _refresh_token(hass, entry, session)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Token refresh failed: %s", err)

    if not refreshed:
        await _full_login(hass, entry, session)
