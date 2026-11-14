# Changelog

## v0.3.0 – 14 Nov 2026

**The integration has been renamed. Reinstall it once; your entity settings are restored automatically.** See *Upgrading from "Exo Pool"* in the README.

- **New name: Zodiac iAqualink Exo.** Another integration already uses the name "Exo Pool". The domain changes from `exo_pool` to `zodiac_exo`, and the repository moves to `JustChr/ha-zodiac-iaqualink-exo`. The old URL redirects.
- **Settings carried over.** After you delete *Exo Pool* and add *Zodiac iAqualink Exo*, the entities get back their entity IDs (including ones you chose yourself), history, names, icons, areas, labels and hidden/disabled state. The device's area and name are copied too. You log in again, and device-based automation steps need the device selected again.
- If an old *Exo Pool* entry is still configured but its files are gone (manual installs), adding the integration offers to take it over completely, login and device included.
- **Actions renamed (breaking).** Change `exo_pool.set_schedule`, `exo_pool.set_schedules`, `exo_pool.disable_schedule` and `exo_pool.reload` to the matching `zodiac_exo.*` action.
- CI now also boots Home Assistant 2025.1 (the oldest supported version) and the latest release, and runs the smoke test on both.

## v0.2.0 – 14 Nov 2026

**Requires Home Assistant 2025.1 or newer.**

- **Climate deprecation warnings fixed** – The heat pump entity now uses Home Assistant's new `native_*` temperature API (HA 2026.11+), so the "provides the deprecated temperature_unit / current_temperature / target_temperature" warnings are gone. Older HA versions keep working.
- **Re-authentication** – If iAqualink rejects the stored login (e.g. after a password change) Home Assistant now shows a *Re-authenticate* prompt instead of failing silently.
- **No duplicate setups** – Each pool system can only be added once (existing installs are migrated automatically).
- **Reload / unload fixed** – Reloading the integration no longer leaves the old instance polling the cloud in the background, and a failed start-up is retried cleanly instead of coming up without data.
- **MQTT reliability** – After a network blip the connection now resubscribes without blocking the MQTT I/O thread (previously every blip escalated to a full credential refresh). Heartbeat timers are created on the event loop (thread-safety fix), and disconnecting no longer blocks Home Assistant.
- **REST polling** – While MQTT is connected the REST safety poll stays at 1 hour; it no longer drops back to the configured interval after a change.
- **Device actions** – "Set schedule" / "Disable schedule" device actions now validate correctly in automations (`ACTION_SCHEMA` was missing).
- **Services** – Inputs are validated (bad times/RPM are rejected with a clear error); with a single Exo Pool configured, no device needs to be selected.
- **Privacy** – Passwords, tokens and AWS credentials are no longer written to the debug log; diagnostics also redact the serial number.
- **pH set point** – Values are rounded properly before sending (e.g. 7.3 → 73).
- **Entity naming** – Entities use Home Assistant's device-based naming (`has_entity_name`). Existing entity IDs are unchanged; friendly names are now prefixed with the device name (e.g. "Exo Pool Temperature").
- Error messages from failed writes are shown as proper Home Assistant errors.
- Added Home Assistant integration tests and a CI workflow.
- **New icon and logo** – shown in Home Assistant (2026.x reads them from the integration's `brand/` folder) and in HACS. Manifest now declares its category (Water › Pools & spas) and cloud connectivity.

## v0.1.21 – 20 Apr 2026

- **Entity cleanup** – Removed redundant sensors (SWC Output %, SWC Low Output %, Error Code Text) and the Power switch (not controllable via API).
- **Renamed entities** for consistency: "Chlorinator" (binary sensor), "Chlorinator Output / Low Output / Low Mode" (numbers/switch), "Error", "Authentication", "MQTT Connected", "Device Online".
- **Aux 2 switch** hides automatically when Aux 2 is configured as a heat pump (climate entity takes over).
- **Refresh Interval** moved from a number entity to the integration's Configure dialog (Settings → Devices & Services → Exo Pool → Configure).
- **MQTT Connected** sensor now reflects the actual MQTT client state rather than data presence.
- **Authentication** sensor is always available (was incorrectly gated on coordinator data).

## v0.1.20 – 19 Apr 2026

- **State bounce fix** – After sending a command via MQTT (e.g. turning off the chlorinator), the UI no longer flips back to the old state. AWS IoT echoes back an intermediate shadow update before the device processes the command; that stale update is now ignored during the 5-second post-write settling window.

## v0.1.19 – 19 Apr 2026

- **Instant switches** – All switches toggle immediately with no post-write cooldown. On failure a HA error notification is shown and a single automatic retry is attempted.
- **Batch schedule updates** – New `exo_pool.set_schedules` service sends all schedule changes in one API call. Bulk updates that previously took several minutes now complete in ~45 seconds.
- **Code cleanup** – `api.py` split into `write_manager.py`, `coordinator.py`, and `auth.py`.

## v0.1.18 – 15 Apr 2026

- **Real-time MQTT push** – connects to the same AWS IoT shadow endpoint as the official iAqualink app. Sub-second state sync; credentials come from the Zodiac login API automatically.
- Writes go via MQTT when connected — no 429 rate limit errors under normal conditions.
- REST polling kept as a 1-hour fallback if MQTT disconnects.
- AWS credentials refreshed automatically before expiry.
- Added `awsiotsdk` dependency (installed automatically by HACS).

## 7 Feb 2026

- Fixed 401 "token expired" errors that could occur on schedule writes.

## 6 Feb 2026

- Rate-limit protection — API calls are spaced out and reads/writes no longer overlap.
- Write queue: multiple quick changes are merged and applied safely.
- pH, ORP and other optional entities now appear reliably without restart.

## 11 Jan 2026

- Default REST poll interval set to 10 minutes; temporarily boosted to 10 s for 60 s after a user change.
- SWC low mode now uses the correct `low` shadow field.
- Added `exo_pool.reload` service.

## Earlier

- **20 Oct 2025** – Single-speed pump (SSP) support.
- **23 Sep 2025** – Climate entity for heat pump (Aux 2 heat mode).
- **15 Sep 2025** – Configurable API refresh rate.
- **3 Sep 2025** – Schedule binary sensors and set-schedule service.
