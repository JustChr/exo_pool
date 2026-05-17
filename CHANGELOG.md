# Changelog

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
