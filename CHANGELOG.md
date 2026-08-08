# Changelog

## 0.2.0-opendtu

- Rebuilt the driver as an OpenDTU-specific Venus OS service.
- Added MQTT autodiscovery via the configured OpenDTU base topic.
- Added dynamic D-Bus PV inverter services per OpenDTU inverter serial number.
- Added explicit D-Bus `/Serial` values per inverter.
- Added direct ESS limit feedback to `<base_topic>/<serial>/cmd/limit_nonpersistent_absolute`.
- Added filtering so only long numeric inverter serial numbers are accepted.
- Added OpenDTU `name` forwarding to the Venus OS D-Bus `/CustomName`.
- Changed startup behavior so retained `name` topics alone do not create disconnected placeholder devices.
- Changed D-Bus device instance allocation to sequential values starting at `100`.
- Removed manual instances, generic MQTT payload handling, fixed topic configuration, and non-OpenDTU device support.
- Changed installation to the persistent `/data/etc/dbus-mqtt-opendtu` path.
