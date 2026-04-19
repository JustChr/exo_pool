"""Authentication helpers for Exo Pool (login, token refresh, AWS credentials)."""
from __future__ import annotations

import logging
import time

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


async def _full_login(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> None:
    """Perform full login with email and password."""
    from .api import (
        _async_rate_limit,
        _log_response_headers,
        _set_auth_failed,
        _get_entry_store,
        API_KEY_PROD,
        LOGIN_URL,
    )

    headers = {"Content-Type": "application/json", "User-Agent": "okhttp/3.14.7"}
    payload = {
        "api_key": API_KEY_PROD,
        "email": entry.data["email"],
        "password": entry.data["password"],
    }
    _LOGGER.debug("Login payload: %s", {**payload, "password": "REDACTED"})
    await _async_rate_limit(hass, entry)
    async with session.post(LOGIN_URL, json=payload, headers=headers) as response:
        _LOGGER.debug("Login response status: %s", response.status)
        _log_response_headers(response, label="Login")
        if response.status != 200:
            error_text = await response.text()
            _LOGGER.error("Failed to authenticate: %s", error_text)
            _set_auth_failed(_get_entry_store(hass, entry), error_text)
            raise Exception(f"Authentication failed: {error_text}")
        data = await response.json()
        _LOGGER.debug(
            "Login response data: %s",
            {k: v if k != "id_token" else v[:10] + "..." for k, v in data.items()},
        )
        id_token = data.get("userPoolOAuth", {}).get("IdToken")
        refresh_token = data.get("userPoolOAuth", {}).get("RefreshToken")
        auth_token = data.get("authentication_token")
        user_id = data.get("id")
        expires_in = data.get("userPoolOAuth", {}).get("ExpiresIn", 3600)
        if not id_token:
            _LOGGER.error("No userPoolOAuth.IdToken in response: %s", data)
            _set_auth_failed(_get_entry_store(hass, entry), "No userPoolOAuth.IdToken received")
            raise Exception("No userPoolOAuth.IdToken received")
        if not auth_token:
            _LOGGER.error("No authentication_token in response: %s", data)
            _set_auth_failed(_get_entry_store(hass, entry), "No authentication_token received")
            raise Exception("No authentication_token received")
        update_data = {
            **entry.data,
            "id_token": id_token,
            "auth_token": auth_token,
            "user_id": user_id,
            "expires_at": time.time() + expires_in - 60,
        }
        if refresh_token:
            update_data["refresh_token"] = refresh_token
        hass.config_entries.async_update_entry(entry, data=update_data)
        _store_aws_credentials(hass, entry, data)


async def _refresh_token(
    hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession
) -> bool:
    """Refresh token using refresh_token. Returns True on success."""
    from .api import (
        _async_rate_limit,
        _log_response_headers,
        REFRESH_URL,
    )

    headers = {"Content-Type": "application/json", "User-Agent": "okhttp/3.14.7"}
    payload = {
        "email": entry.data["email"],
        "refresh_token": entry.data["refresh_token"],
    }
    _LOGGER.debug("Refresh token payload: %s", {**payload, "refresh_token": "REDACTED"})
    await _async_rate_limit(hass, entry)
    async with session.post(REFRESH_URL, json=payload, headers=headers) as response:
        _LOGGER.debug("Refresh response status: %s", response.status)
        _log_response_headers(response, label="Token refresh")
        if response.status != 200:
            error_text = await response.text()
            _LOGGER.error("Failed to refresh token: %s", error_text)
            return False
        data = await response.json()
        _LOGGER.debug(
            "Refresh response data: %s",
            {k: v if k != "id_token" else v[:10] + "..." for k, v in data.items()},
        )
        id_token = data.get("userPoolOAuth", {}).get("IdToken")
        refresh_token = data.get("userPoolOAuth", {}).get("RefreshToken")
        auth_token = data.get("authentication_token")
        user_id = data.get("id")
        expires_in = data.get("userPoolOAuth", {}).get("ExpiresIn", 3600)
        if not id_token:
            _LOGGER.error("No userPoolOAuth.IdToken in refresh response: %s", data)
            return False
        update_data = {
            **entry.data,
            "id_token": id_token,
            "auth_token": auth_token,
            "user_id": user_id,
            "expires_at": time.time() + expires_in - 60,
        }
        if refresh_token:
            update_data["refresh_token"] = refresh_token
        hass.config_entries.async_update_entry(entry, data=update_data)
        _store_aws_credentials(hass, entry, data)
        return True


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
        except Exception as err:
            _LOGGER.debug("Token refresh failed during write: %s", err)

    if not refreshed:
        await _full_login(hass, entry, session)
