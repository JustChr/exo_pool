"""Home Assistant integration tests (require pytest-homeassistant-custom-component)."""
from __future__ import annotations

import copy
import time
from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.plugins")

from homeassistant import config_entries  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.zodiac_exo.const import (  # noqa: E402
    DATA_URL_TEMPLATE,
    DEVICES_URL,
    DOMAIN,
    LOGIN_URL,
)

SERIAL = "JT00000000"

REPORTED = {
    "aws": {"status": "connected"},
    "debug": {"RSSI": -55, "Version Firmware": "V85W4"},
    "heating": {"sp": 28, "sp_min": 15, "sp_max": 32, "state": 0, "enabled": 1},
    "equipment": {
        "swc_0": {
            "sn": SERIAL,
            "production": 1,
            "boost": 0,
            "low": 0,
            "swc": 40,
            "swc_low": 10,
            "ph_sp": 72,
            "orp_sp": 700,
            "ph_only": 1,
            "dual_link": 1,
            "error_code": 0,
            "error_state": 0,
            "sns_1": {"value": 73},
            "sns_2": {"value": 690},
            "sns_3": {"value": 26},
            "aux_1": {"state": 0, "mode": 0},
            "aux_2": {"state": 1, "mode": 3},
            "filter_pump": {"state": 1, "type": 2},
        }
    },
    "schedules": {
        "sch1": {
            "id": "sch_1",
            "name": "Filter Pump",
            "endpoint": "vsp1",
            "enabled": 1,
            "active": 1,
            "rpm": 2000,
            "timer": {"start": "08:00", "end": "20:00"},
        }
    },
}

LOGIN_RESPONSE = {
    "id": "user-1",
    "authentication_token": "auth-token",
    "userPoolOAuth": {"IdToken": "id-token", "RefreshToken": "rt", "ExpiresIn": 3600},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def no_mqtt():
    """Never open a real MQTT connection."""
    with patch("custom_components.zodiac_exo.api._connect_mqtt", return_value=False):
        yield


def _entry(**data) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Zodiac Exo ({SERIAL})",
        unique_id=SERIAL,
        data={
            "email": "user@example.com",
            "password": "secret",
            "auth_token": "auth-token",
            "id_token": "id-token",
            "user_id": "user-1",
            "serial_number": SERIAL,
            "expires_at": time.time() + 3600,
            **data,
        },
    )


async def _setup(hass: HomeAssistant, aioclient_mock, reported=None) -> MockConfigEntry:
    aioclient_mock.get(
        DATA_URL_TEMPLATE.format(SERIAL),
        json={"state": {"reported": copy.deepcopy(reported or REPORTED)}},
    )
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_entities_and_unloads(
    hass: HomeAssistant, aioclient_mock, caplog
) -> None:
    entry = await _setup(hass, aioclient_mock)
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.exo_pool_temperature").state == "26"
    assert hass.states.get("sensor.exo_pool_ph").state == "7.3"
    assert hass.states.get("switch.exo_pool_chlorinator").state == "on"
    assert hass.states.get("number.exo_pool_ph_set_point").state == "7.2"
    assert hass.states.get("number.exo_pool_orp_set_point").state == "700"
    # Aux 2 drives the heat pump, so the plain switch is unavailable
    assert hass.states.get("switch.exo_pool_aux_2").state == "unavailable"

    climate = hass.states.get("climate.exo_pool_heat_pump")
    assert climate is not None
    assert climate.state == "heat"
    assert climate.attributes["current_temperature"] == 26
    assert climate.attributes["temperature"] == 28
    assert climate.attributes["min_temp"] == 15
    assert climate.attributes["max_temp"] == 32
    assert "deprecated" not in caplog.text

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_climate_set_temperature_writes_heating_sp(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await _setup(hass, aioclient_mock)
    aioclient_mock.post(DATA_URL_TEMPLATE.format(SERIAL), json={})

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.exo_pool_heat_pump", "temperature": 30.4},
        blocking=True,
    )
    posts = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert posts[-1][2] == {"state": {"desired": {"heating": {"sp": 30}}}}
    assert hass.states.get("climate.exo_pool_heat_pump").attributes["temperature"] == 30

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_ph_set_point_is_sent_as_integer(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock)
    aioclient_mock.post(DATA_URL_TEMPLATE.format(SERIAL), json={})

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.exo_pool_ph_set_point", "value": 7.3},
        blocking=True,
    )
    posts = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert posts[-1][2] == {"state": {"desired": {"equipment": {"swc_0": {"ph_sp": 73}}}}}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_rejected_login_starts_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(LOGIN_URL, status=401, text='{"message":"bad credentials"}')
    entry = _entry(expires_at=0)
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == config_entries.SOURCE_REAUTH for f in flows)


async def test_config_flow_creates_entry_and_blocks_duplicates(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.post(LOGIN_URL, json=LOGIN_RESPONSE)
    aioclient_mock.get(
        DEVICES_URL,
        json=[
            {"serial_number": SERIAL, "name": "Pool", "device_type": "exo"},
            {"serial_number": "OTHER", "name": "Spa", "device_type": "iaqua"},
        ],
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com", "password": "secret"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_system"

    with patch("custom_components.zodiac_exo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"system": f"{SERIAL} (Pool)"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL
    assert result["data"]["refresh_token"] == "rt"

    # Adding the same system again aborts
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com", "password": "secret"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"system": f"{SERIAL} (Pool)"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_config_flow_invalid_auth(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(LOGIN_URL, status=401, text="{}")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com", "password": "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "auth_failed"}


async def test_reauth_flow_updates_password(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(LOGIN_URL, json=LOGIN_RESPONSE)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch("custom_components.zodiac_exo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": "user@example.com", "password": "new-secret"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-secret"
    assert "id_token" not in entry.data


async def test_takeover_of_old_exo_pool_entry(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A leftover v0.2.x (exo_pool) entry is adopted with its registry entries."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    aioclient_mock.get(
        DATA_URL_TEMPLATE.format(SERIAL),
        json={"state": {"reported": copy.deepcopy(REPORTED)}},
    )
    old = MockConfigEntry(
        domain="exo_pool",
        title=f"Exo Pool ({SERIAL})",
        unique_id=SERIAL,
        data=dict(_entry().data),
        options={"refresh_interval": 900},
    )
    old.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=old.entry_id,
        identifiers={("exo_pool", old.entry_id)},
        name="Exo Pool",
    )
    ph = ent_reg.async_get_or_create(
        "sensor",
        "exo_pool",
        f"{old.entry_id}_ph",
        config_entry=old,
        device_id=device.id,
        suggested_object_id="exo_pool_ph",
    )
    ent_reg.async_update_entity(ph.entity_id, name="Pool pH")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "migrate"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    new = result["result"]
    assert new.state is ConfigEntryState.LOADED
    assert new.options == {"refresh_interval": 900}
    assert "migrate_from_entry_id" not in new.data
    assert not hass.config_entries.async_entries("exo_pool")

    moved = ent_reg.async_get("sensor.exo_pool_ph")
    assert moved.platform == DOMAIN
    assert moved.config_entry_id == new.entry_id
    assert moved.unique_id == f"{new.entry_id}_ph"
    assert moved.name == "Pool pH"
    assert moved.device_id == device.id
    assert ent_reg.async_get("sensor.exo_pool_ph_2") is None
    assert hass.states.get("sensor.exo_pool_ph").state == "7.3"
    assert dev_reg.async_get(device.id).identifiers == {(DOMAIN, new.entry_id)}


async def test_takeover_refused_while_old_integration_installed(
    hass: HomeAssistant,
) -> None:
    MockConfigEntry(
        domain="exo_pool", unique_id=SERIAL, data=dict(_entry().data)
    ).add_to_hass(hass)
    with patch(
        "custom_components.zodiac_exo.config_flow.async_legacy_installed",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "legacy_still_installed"


async def test_settings_of_deleted_exo_pool_setup_are_restored(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Deleting Exo Pool and adding Zodiac Exo keeps entity IDs and settings."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    old = MockConfigEntry(domain="exo_pool", unique_id=SERIAL, data=dict(_entry().data))
    old.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=old.entry_id, identifiers={("exo_pool", old.entry_id)}
    )
    dev_reg.async_update_device(device.id, name_by_user="Pool")
    ph = ent_reg.async_get_or_create(
        "sensor", "exo_pool", f"{old.entry_id}_ph", config_entry=old, device_id=device.id
    )
    ent_reg.async_update_entity(
        ph.entity_id, new_entity_id="sensor.pool_ph", hidden_by=er.RegistryEntryHider.USER
    )
    await hass.config_entries.async_remove(old.entry_id)
    await hass.async_block_till_done()
    assert ent_reg.async_get("sensor.pool_ph") is None

    entry = await _setup(hass, aioclient_mock)

    restored = ent_reg.async_get("sensor.pool_ph")
    assert restored.platform == DOMAIN
    assert restored.unique_id == f"{entry.entry_id}_ph"
    assert restored.hidden_by is er.RegistryEntryHider.USER
    assert hass.states.get("sensor.pool_ph").state == "7.3"
    assert dev_reg.async_get(restored.device_id).name_by_user == "Pool"
    assert not [k for k in ent_reg.deleted_entities if k[1] == "exo_pool"]
