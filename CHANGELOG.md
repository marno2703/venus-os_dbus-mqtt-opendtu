# Changelog

## 0.2.0-opendtu

- Rebuilt the driver as an OpenDTU-specific Venus OS service.
- Added MQTT autodiscovery via the configured OpenDTU base topic.
- Added dynamic D-Bus PV inverter services per OpenDTU inverter serial number.
- Added explicit D-Bus `/Serial` values per inverter.
- Added direct ESS limit feedback to `<base_topic>/<serial>/cmd/limit_nonpersistent_absolute` with a raw numeric payload.
- Added Fronius-compatible PV inverter D-Bus service names and `/FroniusDeviceType` for Victron ESS feed-in limiting.
- Added OpenDTU max-power learning from `status/limit_relative = 100` and `status/limit_absolute`.
- Added upper and lower limit clamping before publishing limits to OpenDTU.
- Added filtering so only long numeric inverter serial numbers are accepted.
- Added OpenDTU `name` forwarding to the Venus OS D-Bus `/CustomName`.
- Added discovery logs for inverter serial numbers and assigned DeviceInstance values.
- Added `/data/etc/dbus-mqtt-opendtu/runtime_state.json` for MQTT topic and D-Bus discovery diagnostics.
- Added `/data/etc/dbus-mqtt-opendtu/max_powers.json` for learned inverter max-power persistence.
- Added configurable debug logging via `[DRIVER] debug = 1`.
- Added explicit logs and runtime-state events for Victron `/Ac/PowerLimit` limit writes and OpenDTU limit publishes.
- Changed startup behavior so retained `name` topics alone do not create disconnected placeholder devices.
- Changed inverter service creation to require a channel `0` `power` metric.
- Changed each inverter service to use its own private D-Bus connection, allowing multiple services in one process.
- Changed D-Bus device instance allocation to skip already used Venus OS instances and persist serial-to-instance mappings.
- Changed installation to stop and remove the legacy `dbus-mqtt-pv` service during migration.
- Changed updates to stop the existing `dbus-mqtt-opendtu` service before replacing files.
- Removed manual instances, generic MQTT payload handling, fixed topic configuration, and non-OpenDTU device support.
- Changed installation to the persistent `/data/etc/dbus-mqtt-opendtu` path.
