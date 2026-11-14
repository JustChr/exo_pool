"""Boot a real HomeAssistant core and exercise the zodiac_exo integration.

Works on Windows, where pytest-homeassistant-custom-component cannot run.
Network is replaced by a fake aiohttp session; MQTT is disabled. Run it against
two HA versions (one < 2026.11, one >= 2026.11) to cover both climate API paths.

Usage:
    python -m venv .venv-smoke
    .venv-smoke/Scripts/pip install homeassistant==2026.11.1 awsiotsdk   # any HA >= 2025.1
    .venv-smoke/Scripts/python scripts/smoke_test.py [repo_root]

Prints ok/FAIL per check and "RESULT: PASS" when everything works.
"""
import asyncio
import copy
import json
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
CFG = Path(tempfile.mkdtemp(prefix="exo_smoke_"))
shutil.copytree(REPO / "custom_components", CFG / "custom_components")
sys.path.insert(0, str(CFG))

log_records: list[logging.LogRecord] = []


class _Capture(logging.Handler):
    def emit(self, record):
        log_records.append(record)


logging.basicConfig(level=logging.WARNING)
logging.getLogger().addHandler(_Capture())

from homeassistant import config_entries, loader  # noqa: E402
from homeassistant.const import __version__ as HA_VERSION  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import (  # noqa: E402
    area_registry as ar,
    category_registry as cr,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    issue_registry as ir,
    label_registry as lr,
    translation,
)

SERIAL = "JT00000000"
REPORTED = {
    "aws": {"status": "connected"},
    "debug": {"RSSI": -55, "Version Firmware": "V85W4"},
    "heating": {"sp": 28, "sp_min": 15, "sp_max": 32, "state": 0, "enabled": 1},
    "equipment": {"swc_0": {
        "sn": SERIAL, "production": 1, "boost": 0, "low": 0, "swc": 40, "swc_low": 10,
        "ph_sp": 72, "orp_sp": 700, "ph_only": 1, "dual_link": 1, "error_code": 0,
        "error_state": 0, "sns_1": {"value": 73}, "sns_2": {"value": 690},
        "sns_3": {"value": 26}, "aux_1": {"state": 0, "mode": 0},
        "aux_2": {"state": 1, "mode": 3}, "filter_pump": {"state": 1, "type": 2},
    }},
    "schedules": {"sch1": {"id": "sch_1", "name": "Filter Pump", "endpoint": "vsp1",
                           "enabled": 1, "active": 1, "rpm": 2000,
                           "timer": {"start": "08:00", "end": "20:00"}}},
}
LOGIN_OK = {"id": "user-1", "authentication_token": "auth-token",
            "userPoolOAuth": {"IdToken": "id-token", "RefreshToken": "rt", "ExpiresIn": 3600}}


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body
        self.headers = {}

    async def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)

    async def json(self, content_type=None):
        return json.loads(await self.text())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self):
        self.calls = []
        self.login_status = 200

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if "devices.json" in url:
            return FakeResponse(200, [{"serial_number": SERIAL, "name": "Pool", "device_type": "exo"}])
        return FakeResponse(200, {"state": {"reported": copy.deepcopy(REPORTED)}})

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if url.endswith("/login"):
            return FakeResponse(self.login_status, LOGIN_OK if self.login_status == 200 else "{}")
        return FakeResponse(200, {})


failures: list[str] = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


async def main():
    hass = HomeAssistant(str(CFG))
    hass.config.skip_pip = True
    from homeassistant import bootstrap
    from homeassistant.setup import async_setup_component

    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    await async_setup_component(hass, "homeassistant", {})
    await hass.async_start()

    session = FakeSession()
    with patch("homeassistant.helpers.aiohttp_client.async_get_clientsession", return_value=session), \
         patch("custom_components.zodiac_exo.api._connect_mqtt", return_value=False):
        print(f"HA {HA_VERSION}")

        # --- config flow
        res = await hass.config_entries.flow.async_init("zodiac_exo", context={"source": "user"})
        res = await hass.config_entries.flow.async_configure(
            res["flow_id"], {"email": "u@example.com", "password": "pw"})
        check(res.get("step_id") == "select_system", f"flow -> select_system ({res.get('step_id')}, {res.get('errors')})")
        with patch("custom_components.zodiac_exo.async_setup_entry", return_value=True):
            res = await hass.config_entries.flow.async_configure(res["flow_id"], {"system": f"{SERIAL} (Pool)"})
        check(res["type"] == "create_entry", "flow creates entry")
        entry = res["result"]
        check(entry.unique_id == SERIAL, "entry has unique_id")
        res = await hass.config_entries.flow.async_init("zodiac_exo", context={"source": "user"})
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"email": "u@example.com", "password": "pw"})
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"system": f"{SERIAL} (Pool)"})
        check(res["type"] == "abort" and res["reason"] == "already_configured", "duplicate aborted")

        # --- setup
        with patch("custom_components.zodiac_exo.async_unload_entry", return_value=True):
            await hass.config_entries.async_unload(entry.entry_id)
        hass.config_entries.async_update_entry(entry, data={**entry.data, "expires_at": time.time() + 3600})
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        check(entry.state is config_entries.ConfigEntryState.LOADED, "entry loaded")

        st = hass.states.get
        check(st("sensor.exo_pool_temperature") and st("sensor.exo_pool_temperature").state == "26", "temperature sensor entity_id + value")
        check(st("sensor.exo_pool_ph").state == "7.3", "pH sensor")
        check(st("number.exo_pool_ph_set_point").state == "7.2", "pH set point")
        check(st("switch.exo_pool_aux_2").state == "unavailable", "aux 2 unavailable in heat mode")
        c = st("climate.exo_pool_heat_pump")
        check(c is not None and c.state == "heat", "climate entity state heat")
        check(c.attributes.get("current_temperature") == 26, f"climate current_temperature ({c.attributes.get('current_temperature')})")
        check(c.attributes.get("temperature") == 28, f"climate target ({c.attributes.get('temperature')})")
        check(c.attributes.get("min_temp") == 15 and c.attributes.get("max_temp") == 32, "climate min/max")
        check(any(s.entity_id.startswith("binary_sensor.exo_pool_schedule") for s in hass.states.async_all()), "schedule binary sensor")

        # --- writes
        await hass.services.async_call("climate", "set_temperature",
            {"entity_id": "climate.exo_pool_heat_pump", "temperature": 30.4}, blocking=True)
        posts = [cl for cl in session.calls if cl[0] == "POST"]
        check(posts and posts[-1][2]["json"] == {"state": {"desired": {"heating": {"sp": 30}}}}, f"set_temperature payload {posts[-1][2]['json'] if posts else None}")
        await hass.services.async_call("number", "set_value",
            {"entity_id": "number.exo_pool_ph_set_point", "value": 7.3}, blocking=True)
        posts = [cl for cl in session.calls if cl[0] == "POST"]
        check(posts[-1][2]["json"] == {"state": {"desired": {"equipment": {"swc_0": {"ph_sp": 73}}}}}, f"pH payload {posts[-1][2]['json']}")
        await hass.services.async_call("zodiac_exo", "set_schedule",
            {"entity_id": "binary_sensor.exo_pool_schedule_filter_pump", "start": "09:00", "end": "19:00", "rpm": 1800}, blocking=True)
        check(True, "set_schedule service accepted")
        try:
            await hass.services.async_call("zodiac_exo", "set_schedule",
                {"device_id": "x", "start": "99:00"}, blocking=True)
            check(False, "invalid service call rejected")
        except Exception as err:  # noqa: BLE001
            check(True, f"invalid service call rejected ({type(err).__name__})")

        # --- device action schema exists
        from custom_components.zodiac_exo import device_action
        check(hasattr(device_action, "ACTION_SCHEMA"), "device_action.ACTION_SCHEMA present")

        # --- diagnostics redaction
        from custom_components.zodiac_exo.diagnostics import async_get_config_entry_diagnostics
        diag = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
        check("pw" not in diag and "id-token" not in diag and SERIAL not in diag, "diagnostics redacted")

        # --- unload
        coordinator = hass.data["zodiac_exo"][entry.entry_id]["coordinator"]
        check(await hass.config_entries.async_unload(entry.entry_id), "unload ok")
        await hass.async_block_till_done()
        check(not coordinator._listeners, f"no coordinator listeners left after unload ({len(coordinator._listeners)})")
        check(entry.entry_id not in hass.data.get("zodiac_exo", {}), "entry store removed")

        # --- reload works
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        check(entry.state is config_entries.ConfigEntryState.LOADED, "re-setup ok")
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # --- rejected login -> reauth
        session.login_status = 401
        hass.config_entries.async_update_entry(entry, data={**entry.data, "expires_at": 0})
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        check(entry.state is config_entries.ConfigEntryState.SETUP_ERROR, f"auth failure -> setup error ({entry.state})")
        flows = hass.config_entries.flow.async_progress()
        reauth = [f for f in flows if f["context"]["source"] == "reauth"]
        check(bool(reauth), "reauth flow started")
        session.login_status = 200
        if reauth:
            with patch("custom_components.zodiac_exo.async_setup_entry", return_value=True):
                res = await hass.config_entries.flow.async_configure(
                    reauth[0]["flow_id"], {"email": "u@example.com", "password": "new"})
            check(res.get("reason") == "reauth_successful", f"reauth successful ({res.get('reason')}, {res.get('errors')})")
            check(entry.data["password"] == "new", "password updated")

    bad = [r for r in log_records if "deprecated" in r.getMessage() or "zodiac_exo" in r.getMessage() and r.levelno >= logging.ERROR]
    for r in bad:
        print("  LOG", r.levelname, r.getMessage()[:300])
    check(not any("deprecated" in r.getMessage() for r in log_records), "no deprecation warnings logged")

    await hass.async_stop(force=True)
    shutil.rmtree(CFG, ignore_errors=True)
    print("RESULT:", "PASS" if not failures else f"{len(failures)} FAILURE(S)")
    sys.exit(1 if failures else 0)


asyncio.run(main())
