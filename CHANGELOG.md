# Changelog

## 0.2.0-opendtu

- Rebuilt the driver as an OpenDTU-specific Venus OS service.
- Added MQTT autodiscovery via `solar/+/0/+` and `solar/+/name`.
- Added dynamic D-Bus PV inverter services per OpenDTU inverter serial number.
- Added direct ESS limit feedback to `<base_topic>/<serial>/cmd/limit_nonpersistent_absolute`.
- Added filtering so only long numeric inverter serial numbers are accepted.
- Added OpenDTU `name` forwarding to the Venus OS D-Bus `/CustomName`.
- Removed manual instances, generic MQTT payload handling, fixed topic configuration, and non-OpenDTU device support.
- Changed installation to the persistent `/data/etc/dbus-mqtt-opendtu` path.
