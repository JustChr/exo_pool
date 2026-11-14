"""Config flow for Exo Pool."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client

from .api import REFRESH_DEFAULT, REFRESH_MAX, REFRESH_MIN, REFRESH_OPTION_KEY
from .auth import async_login
from .const import API_KEY_R, DEVICES_URL, DOMAIN, redact

_LOGGER = logging.getLogger(__name__)

LOGIN_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


class CannotConnect(Exception):
    """Error talking to the API."""


class InvalidAuth(Exception):
    """Credentials were rejected."""


async def _async_authenticate(hass, email: str, password: str) -> dict:
    """Log in and return the parsed login response."""
    session = aiohttp_client.async_get_clientsession(hass)
    try:
        status, result, _ = await async_login(session, email, password)
    except aiohttp.ClientError as err:
        raise CannotConnect from err
    _LOGGER.debug("Login response status: %s, data: %s", status, redact(result))
    if status in (400, 401, 403):
        raise InvalidAuth
    if (
        status != 200
        or result is None
        or "authentication_token" not in result
        or not (result.get("userPoolOAuth") or {}).get("IdToken")
    ):
        raise CannotConnect
    return result


class ExoPoolOptionsFlow(OptionsFlow):
    """Options flow for Exo Pool (REST poll interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(REFRESH_OPTION_KEY, REFRESH_DEFAULT)
        schema = vol.Schema(
            {
                vol.Optional(REFRESH_OPTION_KEY, default=int(current)): vol.All(
                    vol.Coerce(int), vol.Range(min=REFRESH_MIN, max=REFRESH_MAX)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class ExoPoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Exo Pool."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        self._login: dict = {}
        self._systems: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ExoPoolOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for iAqualink credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._login = await _async_authenticate(
                    self.hass, user_input["email"], user_input["password"]
                )
            except InvalidAuth:
                errors["base"] = "auth_failed"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"
            else:
                self._email = user_input["email"]
                self._password = user_input["password"]
                return await self.async_step_select_system()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(LOGIN_SCHEMA, user_input),
            errors=errors,
        )

    async def _async_fetch_systems(self) -> dict[str, str]:
        """Return {label: serial} for all eXO devices on the account."""
        session = aiohttp_client.async_get_clientsession(self.hass)
        params = {
            "api_key": API_KEY_R,
            "authentication_token": self._login["authentication_token"],
            "user_id": self._login.get("id"),
            "timestamp": 1663228298244,  # Required dummy value
        }
        async with session.get(DEVICES_URL, params=params) as resp:
            result = await resp.json(content_type=None)
        if not isinstance(result, list):
            _LOGGER.debug("Unexpected device list response: %s", type(result).__name__)
            return {}
        return {
            f"{s.get('serial_number')} ({s.get('name') or 'Unnamed'})": s["serial_number"]
            for s in result
            if isinstance(s, dict)
            and s.get("device_type") == "exo"
            and s.get("serial_number")
        }

    async def async_step_select_system(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick which eXO system to add."""
        if user_input is not None and user_input.get("system") in self._systems:
            serial_number = self._systems[user_input["system"]]
            await self.async_set_unique_id(serial_number)
            self._abort_if_unique_id_configured()
            oauth = self._login.get("userPoolOAuth") or {}
            data = {
                "email": self._email,
                "password": self._password,
                "auth_token": self._login["authentication_token"],
                "id_token": oauth.get("IdToken"),
                "user_id": self._login.get("id"),
                "serial_number": serial_number,
            }
            if refresh_token := oauth.get("RefreshToken"):
                data["refresh_token"] = refresh_token
            return self.async_create_entry(
                title=f"Exo Pool ({serial_number})", data=data
            )

        try:
            self._systems = await self._async_fetch_systems()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            _LOGGER.debug("Failed to fetch device list", exc_info=True)
            return self.async_abort(reason="cannot_connect")

        if not self._systems:
            return self.async_abort(reason="no_systems")

        return self.async_show_form(
            step_id="select_system",
            data_schema=vol.Schema(
                {vol.Required("system"): vol.In(list(self._systems))}
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication when the stored credentials stop working."""
        self._email = entry_data.get("email")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the (new) password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            email = user_input["email"]
            try:
                await _async_authenticate(self.hass, email, user_input["password"])
            except InvalidAuth:
                errors["base"] = "auth_failed"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during re-authentication")
                errors["base"] = "unknown"
            else:
                # Drop cached tokens so the integration logs in fresh.
                data = {
                    k: v
                    for k, v in entry.data.items()
                    if k not in ("id_token", "refresh_token", "auth_token", "expires_at")
                }
                data.update(email=email, password=user_input["password"])
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                LOGIN_SCHEMA, {"email": self._email or entry.data.get("email")}
            ),
            errors=errors,
        )
