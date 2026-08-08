# venus-os_dbus-mqtt-opendtu

Autodiscovery OpenDTU PV inverter driver for Victron Energy Venus OS.

This fork exposes each OpenDTU inverter as its own Victron D-Bus PV inverter service and forwards ESS power limits directly back to OpenDTU over MQTT. It does not require manually configured instances, fixed inverter topics, Home Assistant automations, Node-RED flows, or an MQTT bridge.

Original project license and copyright notices are kept where required. See [LICENSE](LICENSE).

## What It Does

The driver subscribes to the OpenDTU MQTT base topic:

```text
solar/#
```

Only topics where the second path segment is a long numeric inverter serial number are accepted. OpenDTU helper topics such as `powerlimiter`, `ac`, `dc`, `dtu`, `device`, `status`, and `radio` are ignored.

The aggregate inverter values are read from channel `0`. Panel channels such as `1`, `2`, `3`, and `4` are ignored. For example:

```text
solar/<serial>/0/power
```

creates this Venus OS D-Bus service automatically:

```text
com.victronenergy.pvinverter.mqtt_<serial>
```

The OpenDTU `name` topic is passed to Venus OS as the D-Bus `/CustomName`, so the inverter appears with its configured OpenDTU name instead of only the serial number.

A Venus OS device is created only after the driver has received at least one channel `0` metric for that inverter. A retained `name` topic alone will not create a disconnected placeholder device.

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

During installation, a legacy `dbus-mqtt-pv` service from the original project is stopped and removed if it exists. After migrating from the old driver, remove stale disconnected entries once in the Venus OS device list.

The installer also stops an existing `dbus-mqtt-opendtu` service before replacing files. This prevents multiple daemon-tools supervisors from running after repeated updates.

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
base_topic = solar
```

Use the MQTT root topic configured in OpenDTU. For the common OpenDTU layout shown above, set:

```ini
base_topic = solar
```

Only the MQTT broker connection and the OpenDTU base topic are configured manually. Inverter IDs, D-Bus service names, display names, and device instances are derived automatically at runtime.

Device instances are assigned automatically from `100` upward. The driver scans existing Venus OS D-Bus services and skips already used values. The serial-to-instance mapping is stored in:

```text
/data/etc/dbus-mqtt-opendtu/device_instances.json
```

This keeps each inverter on the same DeviceInstance after a driver restart.

## Start, Restart, Status, Logs

The installer registers the driver as a Venus OS daemon-tools service:

```text
/service/dbus-mqtt-opendtu
```

After editing `config.ini`, restart the driver:

```sh
bash /data/etc/dbus-mqtt-opendtu/restart.sh
```

You can also control the service directly:

```sh
svc -u /service/dbus-mqtt-opendtu
svc -t /service/dbus-mqtt-opendtu
svc -d /service/dbus-mqtt-opendtu
```

Check whether the service is running:

```sh
svstat /service/dbus-mqtt-opendtu
```

Show the live log:

```sh
tail -n 100 -F /var/log/dbus-mqtt-opendtu/current | tai64nlocal
```

For every detected inverter, the log should contain a line like:

```text
Created D-Bus service for OpenDTU inverter <serial> with DeviceInstance 100
```

## How The Limit Feedback Works

Victron ESS writes the requested AC power limit to the D-Bus path:

```text
/Ac/MaxPower
```

The driver catches that write on the matching inverter service, maps it back to the inverter serial number, and publishes the limit directly to OpenDTU:

```text
solar/<serial>/cmd/limit_nonpersistent_absolute
```

Payload format:

```json
{"value": 250}
```

The limit is non-persistent, so it is suitable for dynamic zero-feed-in control.
