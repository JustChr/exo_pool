# Exo Pool – Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/release/JustChr/exo_pool.svg)](https://github.com/JustChr/exo_pool/releases)
[![License](https://img.shields.io/github/license/JustChr/exo_pool.svg)](LICENSE)

Control and monitor your **Zodiac iAqualink Exo** pool system directly from Home Assistant — real-time updates via the same cloud connection as the official app. No extra hardware, no MQTT broker, no addon required.

---

## Compatibility

**Supported devices:** Zodiac iAqualink **Exo** series (European market).

> Not compatible with other iAqualink hardware (e.g. iQ20, iAqualink 3.0). Use the built-in [iAqualink integration](https://www.home-assistant.io/integrations/iaqualink/) for those.

Confirmed working:

- **Exo IQ LS** (dual-link ORP & pH, Zodiac VSP pump)

Have success with another model? [Open a discussion!](https://github.com/JustChr/exo_pool/discussions)

---

## Installation

> **Requires [HACS](https://hacs.xyz).** Add this as a custom repository first.

1. In Home Assistant open **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/JustChr/exo_pool` with category **Integration**
3. Search for **Exo Pool** and click **Download**
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration**, search for **Exo Pool**, and enter your Zodiac iAqualink credentials

---

## What you get

### Monitor

| Entity | What it shows |
|---|---|
| Water Temperature | Current pool water temperature |
| pH | Current pH value |
| ORP | Oxidation-reduction potential (water sanitation level) |
| Error Code | Active error code from the device |
| Wi-Fi RSSI | Signal strength of the device's Wi-Fi connection |
| Hardware Info | Detected hardware capabilities (pump type, ORP/pH module) |
| Filter Pump | Whether the filter pump is currently running |
| Chlorinator | Whether the salt water chlorinator is currently producing |
| Error | Whether the device has an active error |
| MQTT Connected | Whether the integration's real-time connection to Zodiac's cloud is active |
| Device Online | Whether the pool device itself is reachable in the cloud |
| Authentication | Whether your credentials are valid |
| Schedule sensors | One sensor per pump/chlorinator schedule (active, start/end times, type) |

### Control

| Entity | What it controls |
|---|---|
| Chlorinator switch | Enable/disable chlorine production |
| Chlorinator Output | Target output level (0–100 %) |
| Chlorinator Low Mode | Enable reduced-output mode (e.g. for night/off-peak) |
| Chlorinator Low Output | Target output level in low mode |
| ORP Boost | Temporarily boost chlorine production |
| Aux 1 / Aux 2 | Auxiliary relay outputs (e.g. lighting, heating valve) |
| pH Set Point | Target pH value (when pH module is present) |
| ORP Set Point | Target ORP value (when ORP module is present) |
| Climate (heat pump) | Heat pump target temperature and mode (appears automatically when Aux 2 is in heat mode) |
| Refresh button | Force an immediate data refresh |

---

## Configuration

After installation, the integration connects automatically using your Zodiac credentials. No manual MQTT or API setup is required.

**REST poll interval** (fallback when the real-time connection is unavailable):
Go to **Settings → Devices & Services → Exo Pool → Configure** and set the interval (300–3600 seconds). Under normal operation this rarely fires.

---

## Schedules

Each schedule on the device is exposed as a binary sensor with these attributes:

| Attribute | Description |
|---|---|
| `schedule` | Schedule key (e.g. `sch1`) |
| `enabled` | Whether the schedule is enabled |
| `start_time` | Scheduled start (HH:MM) |
| `end_time` | Scheduled end (HH:MM) |
| `type` | `vsp` (variable speed pump), `swc` (chlorinator), or `aux` |
| `rpm` | Target RPM — VSP schedules only |

### Services

#### `exo_pool.set_schedule` — update a single schedule

Target by entity:

```yaml
action: exo_pool.set_schedule
data:
  entity_id: binary_sensor.schedule_filter_pump
  start: "08:00"
  end: "22:00"
  rpm: 2000        # VSP only, optional
```

Or target by device and schedule key:

```yaml
action: exo_pool.set_schedule
data:
  device_id: 1a2b3c4d5e6f7g8h9i0j
  schedule: sch1
  start: "08:00"
  end: "22:00"
```

#### `exo_pool.set_schedules` — update multiple schedules in one call

All changes are sent together — only one settling period regardless of how many schedules you update:

```yaml
action: exo_pool.set_schedules
data:
  schedules:
    - schedule: sch1
      start: "08:00"
      end: "22:00"
    - schedule: sch2
      start: "10:00"
      end: "20:00"
      rpm: 2500
    - schedule: sch3
      start: "00:00"
      end: "00:00"   # 00:00–00:00 disables a schedule
```

#### `exo_pool.disable_schedule` — disable a schedule

```yaml
action: exo_pool.disable_schedule
data:
  entity_id: binary_sensor.schedule_salt_water_chlorinator
```

#### `exo_pool.reload` — reload the integration

```yaml
action: exo_pool.reload
```

### Device Actions (no YAML needed)

In the automation editor under **Device → your Exo Pool device → Actions**, you can trigger *Set schedule* and *Disable schedule* directly from the UI.

---

## Dashboard examples

The examples below show common patterns — adapt entity IDs and schedule keys to match your device.

### Example 1: Simple pool card

A tile card showing the most important values at a glance:

```yaml
type: entities
title: Pool
entities:
  - entity: sensor.exo_pool_temperature
    name: Water Temperature
  - entity: sensor.exo_pool_ph
    name: pH
  - entity: sensor.exo_pool_orp
    name: ORP
  - entity: switch.exo_pool_chlorinator
    name: Chlorinator
  - entity: binary_sensor.exo_pool_filter_pump
    name: Filter Pump
  - entity: binary_sensor.exo_pool_error
    name: Error
```

---

### Example 2: Schedule management UI

This pattern lets you manage pump schedules without touching YAML after initial setup.

**How it works:**
- `input_boolean` helpers act as on/off toggles for each schedule
- `input_datetime` helpers store the start and end times
- A script validates the input and calls `exo_pool.set_schedules`

**Helper entities to create** (Settings → Helpers):

| Type | Entity ID | Name |
|---|---|---|
| Toggle | `input_boolean.pool_schedule_1` | Pool Schedule 1 |
| Toggle | `input_boolean.pool_schedule_2` | Pool Schedule 2 |
| Date/Time (time only) | `input_datetime.pool_schedule_1_start` | Schedule 1 Start |
| Date/Time (time only) | `input_datetime.pool_schedule_1_end` | Schedule 1 End |
| Date/Time (time only) | `input_datetime.pool_schedule_2_start` | Schedule 2 Start |
| Date/Time (time only) | `input_datetime.pool_schedule_2_end` | Schedule 2 End |

**Dashboard card** (requires [mushroom-cards](https://github.com/piitaya/lovelace-mushroom) and [time-picker-card](https://github.com/GeorgeSG/lovelace-time-picker-card)):

```yaml
type: grid
cards:
  - type: heading
    heading: Schedules
    heading_style: title
  - type: custom:mushroom-entity-card
    entity: input_boolean.pool_schedule_1
    name: Schedule 1
    layout: horizontal
    tap_action:
      action: toggle
    grid_options:
      columns: full
  - type: horizontal-stack
    cards:
      - type: custom:time-picker-card
        entity: input_datetime.pool_schedule_1_start
        name: Start
        layout:
          embedded: true
        minute_step: 15
      - type: custom:time-picker-card
        entity: input_datetime.pool_schedule_1_end
        name: End
        layout:
          embedded: true
        minute_step: 15
  - type: custom:mushroom-entity-card
    entity: input_boolean.pool_schedule_2
    name: Schedule 2
    layout: horizontal
    tap_action:
      action: toggle
    grid_options:
      columns: full
  - type: horizontal-stack
    cards:
      - type: custom:time-picker-card
        entity: input_datetime.pool_schedule_2_start
        name: Start
        layout:
          embedded: true
        minute_step: 15
      - type: custom:time-picker-card
        entity: input_datetime.pool_schedule_2_end
        name: End
        layout:
          embedded: true
        minute_step: 15
  - type: tile
    entity: script.pool_apply_schedules
    name: Apply
    icon: mdi:content-save
    grid_options:
      columns: full
    tap_action:
      action: perform-action
      perform_action: script.pool_apply_schedules
```

**Script** — validates input, then sends all schedules in a single call:

```yaml
alias: Pool – Apply Schedules
mode: single
sequence:
  - variables:
      s1_active: "{{ is_state('input_boolean.pool_schedule_1', 'on') }}"
      s2_active: "{{ is_state('input_boolean.pool_schedule_2', 'on') }}"
      s1_start: "{{ states('input_datetime.pool_schedule_1_start') }}"
      s1_end:   "{{ states('input_datetime.pool_schedule_1_end') }}"
      s2_start: "{{ states('input_datetime.pool_schedule_2_start') }}"
      s2_end:   "{{ states('input_datetime.pool_schedule_2_end') }}"
      s1_start_min: >
        {% set t = s1_start.split(':') %}
        {{ t[0] | int * 60 + t[1] | int }}
      s1_end_min: >
        {% set t = s1_end.split(':') %}
        {{ t[0] | int * 60 + t[1] | int }}
      s2_start_min: >
        {% set t = s2_start.split(':') %}
        {{ t[0] | int * 60 + t[1] | int }}
      s2_end_min: >
        {% set t = s2_end.split(':') %}
        {{ t[0] | int * 60 + t[1] | int }}
      s1_error: "{{ s1_active and s1_start_min | int >= s1_end_min | int }}"
      s2_error: "{{ s2_active and s2_start_min | int >= s2_end_min | int }}"
      overlap: >
        {{ s1_active and s2_active
           and s1_start_min | int < s2_end_min | int
           and s2_start_min | int < s1_end_min | int }}
  - if:
      - condition: template
        value_template: "{{ s1_error or s2_error or overlap }}"
    then:
      - action: persistent_notification.create
        data:
          title: Invalid schedules
          message: >
            {% if s1_error %}Schedule 1: start must be before end.{% endif %}
            {% if s2_error %}Schedule 2: start must be before end.{% endif %}
            {% if overlap %}Schedules 1 and 2 overlap.{% endif %}
      - stop: Validation failed
  - action: exo_pool.set_schedules
    data:
      schedules:
        - schedule: sch1
          start: "{{ '00:00' if not s1_active else s1_start }}"
          end:   "{{ '00:00' if not s1_active else s1_end }}"
        - schedule: sch2
          start: "{{ '00:00' if not s2_active else s2_start }}"
          end:   "{{ '00:00' if not s2_active else s2_end }}"
```

> **Tip:** If your chlorinator schedule should start slightly after and end slightly before the pump schedule (to avoid running without water flow), offset the times using `timedelta`:
> ```yaml
> chlor_start: "{{ (today_at(s1_start) + timedelta(minutes=5)).strftime('%H:%M') }}"
> chlor_end:   "{{ (today_at(s1_end)   - timedelta(minutes=5)).strftime('%H:%M') }}"
> ```
> Then pass `chlor_start` / `chlor_end` to the chlorinator schedule and `s1_start` / `s1_end` to the pump schedule.

---

## Limitations

- Exo devices only — use the core iAqualink integration for other Zodiac hardware.
- Schedule keys (`sch1`, `sch2`, …) are assigned by the device firmware; check the `schedule` attribute on the schedule sensors to find yours.
- Disabling a schedule is done by setting both start and end to `00:00`.
- RPM is only relevant for VSP (variable speed pump) schedules.
- The heat pump climate entity only appears when Aux 2 is configured for heat mode.

---

## Glossary

| Term | Meaning |
|---|---|
| **ORP** | Oxidation-Reduction Potential — measures how effectively the water sanitises itself. Higher = better disinfection (typical target: 650–750 mV). |
| **pH** | Measure of water acidity/alkalinity. Ideal pool range: 7.2–7.6. |
| **SWC** | Salt Water Chlorinator — generates chlorine from dissolved salt in the water. |
| **VSP** | Variable Speed Pump — a pump whose speed (RPM) can be adjusted by the controller. |
| **SSP** | Single Speed Pump — a pump that runs at one fixed speed. |
| **Aux** | Auxiliary relay output on the controller (e.g. for lighting or a heating valve). |
| **MQTT** | The messaging protocol used by Zodiac's cloud to push real-time updates. |
| **Schedule key** | Internal identifier for a pump/chlorinator schedule, e.g. `sch1`. Find yours in the schedule sensor's attributes. |

---

## Support

- **Bugs / Feature Requests:** [GitHub Issues](https://github.com/JustChr/exo_pool/issues)
- **Q&A / Discussion:** [GitHub Discussions](https://github.com/JustChr/exo_pool/discussions)

---

## History

The Home Assistant core iAqualink integration never supported Exo devices (European Zodiac-branded chlorinators) — see [this discussion](https://github.com/flz/iaqualink-py/discussions/16).
This is a fork of [benjycov/exo_pool](https://github.com/benjycov/exo_pool), extended with real-time MQTT support, batch schedule writes, and ongoing maintenance.

See [CHANGELOG.md](CHANGELOG.md) for the full version history.
