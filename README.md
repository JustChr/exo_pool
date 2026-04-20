# Exo Pool – Home Assistant Integration

A custom integration to connect your Zodiac iAqualink **Exo** pool system to Home Assistant.
Real-time state sync via AWS IoT MQTT (same protocol as the official app) — no MQTT broker or addon required.

---

## What's New

### 20 Apr 2026 – v0.1.21

- **Entity cleanup** – Removed redundant sensors (SWC Output %, SWC Low Output %, Error Code Text) and the Power switch. Renamed entities for consistency: "Chlorinator", "Chlorinator Output/Low Output/Low Mode", "Error", "Authentication", "MQTT Connected", "Device Online".
- **Aux 2 switch** hides automatically when Aux 2 is in heat pump mode (climate entity takes over).
- **Refresh Interval** moved to the integration's Configure dialog (no longer a number entity in the dashboard).
- **MQTT Connected** sensor now shows the actual MQTT client connection state.

### 19 Apr 2026 – v0.1.20

- **State bounce fix** – After sending a command via MQTT (e.g. turning off the chlorinator), the UI no longer flips back to the old state. AWS IoT echoes back an intermediate shadow update before the device processes the command; that stale update is now ignored during the 5-second post-write settling window.

### 19 Apr 2026 – v0.1.19

- **Instant switches** – Aux, Chlorinator, Power and all other switches now toggle immediately with no post-write cooldown. On failure a HA error notification is shown and a single automatic retry is attempted.
- **Batch schedule updates** – New `exo_pool.set_schedules` service sends all schedule changes in one API call, triggering only one cooldown period. Bulk updates that previously took several minutes now complete in ~45 seconds.
- **Code cleanup** – `api.py` split into `write_manager.py`, `coordinator.py`, and `auth.py` for cleaner structure and easier testing.

### 15 Apr 2026 – v0.1.18

- **Real-time MQTT push** – connects to the same AWS IoT shadow endpoint as the official iAqualink app. Sub-second state sync with no extra setup; credentials come from the Zodiac login API automatically.
- Writes (set points, switches, schedules) go via MQTT when connected — no 429 rate limit errors under normal conditions.
- REST polling kept as a 1-hour fallback if MQTT disconnects.
- AWS credentials refreshed automatically before expiry.
- Added `awsiotsdk` dependency (installed automatically by HACS).

### 7 Feb 2026

- Fixed 401 "token expired" errors that could occur on schedule writes; improved related logging.

### 6 Feb 2026

- Much better protection against cloud rate-limits — API calls are spaced out and reads/writes no longer overlap.
- Write queue: multiple quick changes are merged and applied safely instead of hammering the cloud API.
- New manual refresh service; pH, ORP and other optional entities now appear reliably without restart.

### 11 Jan 2026

- Default REST poll interval set to 10 minutes; temporarily boosted to 10 s for 60 s after a user change.
- SWC sensors corrected; SWC low mode now uses the correct `low` shadow field.
- Added `exo_pool.reload` service.

### Earlier

- **20 Oct 2025** – Single-speed pump (SSP) support.
- **23 Sep 2025** – Experimental climate entity for heat pump (Aux 2 heat mode).
- **15 Sep 2025** – Configurable API refresh rate.
- **3 Sep 2025** – Schedule binary sensors and set-schedule service.

---

## Installation (via HACS)

> This is a community fork. Add it as a **custom repository** in HACS first.

1. In Home Assistant open **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/JustChr/exo_pool` with category **Integration**.
3. Search for **Exo Pool** and click **Download**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration**, search for **Exo Pool**, and follow the prompts.

---

## Features

| Category | Entities |
|---|---|
| **Sensors** | Water temperature, pH, ORP, error code, Wi-Fi RSSI, hardware info |
| **Binary sensors** | Filter pump, chlorinator, error, authentication, MQTT connected, device online, one sensor per schedule |
| **Switches** | ORP boost, chlorinator, Aux 1, Aux 2 (hidden when heat pump active), chlorinator low mode |
| **Numbers** | Chlorinator output, chlorinator low output; pH / ORP set points when hardware supports them |
| **Climate** | Heat pump control (appears automatically when Aux 2 is in heat mode) |
| **Services** | `set_schedule`, `set_schedules`, `disable_schedule`, `reload` |

**Real-time updates** via AWS IoT MQTT — same protocol as the official app. No MQTT broker or addon required.

**Configurable REST fallback** – the REST poll interval (300–3600 s) is configured via **Settings → Devices & Services → Exo Pool → Configure**. Under normal MQTT operation this rarely fires.

---

## Schedule Services

Each schedule is exposed as a binary sensor with attributes: `schedule`, `enabled`, `start_time`, `end_time`, `type` (`vsp` | `swc` | `aux`), and `rpm` (VSP only).

### `exo_pool.set_schedule`

Update a single schedule:

```yaml
service: exo_pool.set_schedule
data:
  entity_id: binary_sensor.schedule_filter_pump_2
  start: "11:00"
  end: "23:00"
  rpm: 2000            # VSP only, optional
```

Or target by device and schedule key:

```yaml
service: exo_pool.set_schedule
data:
  device_id: 1a2b3c4d5e6f7g8h9i0j
  schedule: sch6
  start: "11:00"
  end: "23:00"
```

### `exo_pool.set_schedules`

Update multiple schedules in a **single API call** — one cooldown regardless of how many you change:

```yaml
service: exo_pool.set_schedules
data:
  device_id: 1a2b3c4d5e6f7g8h9i0j   # optional if only one device
  schedules:
    - schedule: sch1
      start: "08:00"
      end: "22:00"
    - schedule: sch2
      start: "10:00"
      end: "20:00"
      rpm: 2000
    - schedule: sch3
      start: "00:00"
      end: "00:00"   # 00:00–00:00 disables the schedule
```

### `exo_pool.disable_schedule`

Disable a schedule (sets start and end to `00:00`):

```yaml
service: exo_pool.disable_schedule
data:
  entity_id: binary_sensor.schedule_salt_water_chlorinator_2
```

### `exo_pool.reload`

Reload the integration:

```yaml
service: exo_pool.reload
data:
  entry_id: 8955375327824e14ba89e4b29cc3ec9a   # optional if only one entry
```

---

## Device Actions (Automations)

In the automation editor: **Device → your Exo Pool device → Actions** exposes *Set schedule* and *Disable schedule* directly, without needing to write YAML.

---

## Limitations

- Exo devices only; use the core iAqualink integration for other hardware.
- Commands go via MQTT when connected (near-instant). If MQTT is unavailable, writes fall back to REST which may be subject to rate limits.
- Schedule keys and endpoint names are determined by the device; disabling is modelled as `00:00–00:00`.
- RPM is only relevant to VSP schedules.
- The climate entity only appears when Aux 2 is configured for heat mode.

---

## Compatibility

Confirmed working with:

- **Exo IQ LS** (dual-link ORP & pH, Zodiac VSP pump)

Have success with another model? Open a discussion!

---

## History

The core iAqualink integration never supported Exo devices (European Zodiac-branded chlorinators). See: [flz/iaqualink-py#16](https://github.com/flz/iaqualink-py/discussions/16).
This fork of [benjycov/exo_pool](https://github.com/benjycov/exo_pool) adds MQTT support, batch writes, structural improvements, and ongoing maintenance.

---

## Development

### Prerequisites

- Docker
- Python 3.9+
- A Zodiac iAqualink account with an Exo device

### Quick start

```bash
git clone https://github.com/JustChr/exo_pool.git
cd exo_pool

echo "EXO_EMAIL=your@email.com" > .env
echo "EXO_PASSWORD=yourpassword" >> .env

make dev
# Open http://localhost:8125  (login: dev / devdevdev)
```

### Useful commands

```bash
make test       # run unit + integration tests
make logs       # tail the HA container logs
make restart    # restart HA after code changes
make stop       # stop the container
```

### Running tests

```bash
pip install pytest pytest-asyncio awsiotsdk
python3 -m pytest tests/ -v
```

Tests are isolated from Home Assistant — no HA installation required.

---

## Support

- **Bugs / Feature Requests**: [GitHub Issues](https://github.com/JustChr/exo_pool/issues)
- **Q&A / Discussion**: [GitHub Discussions](https://github.com/JustChr/exo_pool/discussions)
