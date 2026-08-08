# Changelog

## 0.2.0-opendtu

- Rebuilt the driver as an OpenDTU-specific Venus OS service.
- Added MQTT autodiscovery via `opendtu/+/status/power`.
- Added dynamic D-Bus PV inverter services per OpenDTU inverter serial number.
- Added direct ESS limit feedback to `opendtu/<serial>/cmd/limit_nonpersistent_absolute`.
- Removed manual instances, generic MQTT payload handling, fixed topic configuration, and non-OpenDTU device support.
- Changed installation to the persistent `/data/etc/dbus-mqtt-opendtu` path.
