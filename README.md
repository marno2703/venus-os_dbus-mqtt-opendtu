# venus-os_dbus-mqtt-opendtu

Autodiscovery OpenDTU PV inverter driver for Victron Energy Venus OS.

This fork exposes each OpenDTU inverter as its own Victron D-Bus PV inverter service and forwards ESS power limits directly back to OpenDTU over MQTT. It does not require manually configured instances, fixed inverter topics, Home Assistant automations, Node-RED flows, or an MQTT bridge.

Original project license and copyright notices are kept where required. See [LICENSE](LICENSE).

## What It Does

The driver subscribes to the OpenDTU MQTT wildcard topic:

```text
opendtu/+/status/power
```

Whenever a power message arrives, the inverter serial number is extracted from the topic. For example:

```text
opendtu/114183123456/status/power
```

creates this Venus OS D-Bus service automatically:

```text
com.victronenergy.pvinverter.mqtt_114183123456
```

If an inverter stops publishing for the internal timeout period, its D-Bus service is removed again.

## Requirements

- Victron Energy Venus OS with ESS enabled
- OpenDTU running and publishing inverter power values to MQTT
- MQTT broker reachable from the Victron device
- SSH access to the Victron device

## Quick Start Installation

Run these three lines in an SSH shell on the Victron device:

```sh
curl -L -o /tmp/download_dbus-mqtt-opendtu.sh https://raw.githubusercontent.com/marno2703/venus-os_dbus-mqtt-opendtu/master/download.sh
bash /tmp/download_dbus-mqtt-opendtu.sh
nano /data/etc/dbus-mqtt-opendtu/config.ini
```

The download script installs or updates the driver in:

```text
/data/etc/dbus-mqtt-opendtu
```

and adds it to:

```text
/data/rc.local
```

This keeps the driver persistent across Venus OS firmware updates.

## Configuration

Copy or edit:

```text
/data/etc/dbus-mqtt-opendtu/config.ini
```

Minimal example:

```ini
[MQTT]
broker_address = 192.168.1.10
broker_port = 1883
username =
password =
base_topic = opendtu
```

Only the MQTT broker connection and the OpenDTU base topic are configured manually. Inverter IDs, D-Bus service names, and device instances are derived automatically at runtime.

## How The Limit Feedback Works

Victron ESS writes the requested AC power limit to the D-Bus path:

```text
/Ac/MaxPower
```

The driver catches that write on the matching inverter service, maps it back to the inverter serial number, and publishes the limit directly to OpenDTU:

```text
opendtu/<serial>/cmd/limit_nonpersistent_absolute
```

Payload format:

```json
{"value": 250}
```

The limit is non-persistent, so it is suitable for dynamic zero-feed-in control.
